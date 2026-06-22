"""批量 backfill —— 全维度数据,按 Tushare 官方推荐的高效循环方式拉。

- **日线行情**(`daily`):按交易日(`trade_date`)循环,一次拿全市场当天 ~5500 行。
- **估值**(`daily_basic`:PE/PB/PS/换手等):同样按交易日。
- **财务**(`income`/`balancesheet`/`cashflow`/`fina_indicator`):用 `_vip` 接口按
  **报告期**(`period`,季度)循环,一次拿全市场该期 ~6700 行 → ~44 期 × 4 表 ≈ 176 次调用。

为什么这么拉:全市场全历史调用数最小(按天/按期,而非按 5500 票循环),连接锐减、
抗跨境丢包,增量每日/每季秒级。
- 断点续传:backfill_log 按数据集记已拉的日期/报告期,重跑跳过。
- 稳定:TushareClient 退避重试 + socket 超时。

运行:  PYTHONPATH=src .venv/bin/python -m data.backfill                  # 默认 2015 至今,全维度
       PYTHONPATH=src .venv/bin/python -m data.backfill 20100101 20261231
"""
from __future__ import annotations

import sys

from . import universe
from .cache import MarketCache
from .feeds import TushareClient, fetch_to_cache

# 财务四表:(本地表名, tushare vip 接口) —— vip 版支持按 period 拿全市场
FIN_TABLES = [
    ("income", "income_vip"),
    ("balancesheet", "balancesheet_vip"),
    ("cashflow", "cashflow_vip"),
    ("fina_indicator", "fina_indicator_vip"),
]


def trading_days(client: TushareClient, start: str, end: str) -> list:
    cal = client.fetch("trade_cal", exchange="SSE", is_open="1",
                        start_date=start, end_date=end, fields="cal_date")
    return sorted(cal["cal_date"].tolist())


def quarters(start: str, end: str) -> list:
    """季度报告期 YYYYMMDD(0331/0630/0930/1231),落在 [start, end] 内。"""
    years = range(int(start[:4]), int(end[:4]) + 1)
    qs = [f"{y}{md}" for y in years for md in ("0331", "0630", "0930", "1231")]
    return [q for q in qs if start <= q <= end]


def _by_date(cache, client, days, dataset, api, table=None, by_col=None, text_cols=None):
    """按交易日逐日拉某接口(全市场)→ 落库。daily 走 upsert_daily,其余走 upsert_table。"""
    done = cache.done_codes(dataset)
    todo = [d for d in days if d not in done]
    print(f"[{dataset}] 交易日 {len(days)} | 已完成 {len(days) - len(todo)} | 待拉 {len(todo)}")
    ok = failed = rows = 0
    for i, d in enumerate(todo, 1):
        try:
            if dataset == "daily_by_date":
                daily = client.fetch("daily", trade_date=d)
                if len(daily) == 0:
                    cache.log_backfill(dataset, d, "empty", 0); continue
                adj = client.fetch("adj_factor", trade_date=d)
                merged = daily.merge(adj[["ts_code", "adj_factor"]], on="ts_code", how="left")
                n = cache.upsert_daily(merged)
            else:
                df = client.fetch(api, trade_date=d)
                if text_cols:                       # 强制文本列为 string:防 upsert 把"某期全空"的文本列误判成数值
                    for c in text_cols:
                        if c in df.columns:
                            df[c] = df[c].astype("string")
                n = cache.upsert_table(table, df, by_col, d)
            cache.log_backfill(dataset, d, "ok", n); ok += 1; rows += n
        except Exception as e:
            cache.log_backfill(dataset, d, "failed", 0); failed += 1
            print(f"  ✗ {d}: {str(e)[:60]}")
        if i % 30 == 0:
            print(f"  ...{i}/{len(todo)}  (ok {ok}, failed {failed}, {rows:,} 行)")
    print(f"[{dataset}] 完成:ok {ok}, failed {failed}, {rows:,} 行")


def backfill_daily(ts_codes, cache: MarketCache, client: TushareClient, force: bool = False):
    """按 ts_code 逐票拉全历史日线(备用:补个别票;全市场请用主流程)。"""
    done = set() if force else cache.done_codes("daily")
    todo = [c for c in ts_codes if c not in done]
    print(f"[by_code] 待拉 {len(todo)}")
    for code in todo:
        try:
            n = fetch_to_cache(code, client, cache)
            cache.log_backfill("daily", code, "ok", n)
        except Exception as e:
            cache.log_backfill("daily", code, "failed", 0)
            print(f"  ✗ {code}: {str(e)[:60]}")


def backfill_financials(cache: MarketCache, client: TushareClient,
                        start: str, end: str, force: bool = False):
    """按报告期(季度)拉财务四表(vip 接口,一次全市场)。"""
    qs = quarters(start, end)
    done = set() if force else cache.done_codes("financials")
    todo = [q for q in qs if q not in done]
    print(f"[financials] 报告期 {len(qs)} | 已完成 {len(qs) - len(todo)} | 待拉 {len(todo)}")
    ok = failed = 0
    for q in todo:
        try:
            for table, api in FIN_TABLES:
                df = client.fetch(api, period=q)
                cache.upsert_table(table, df, "end_date", q)
            cache.log_backfill("financials", q, "ok", 0); ok += 1
            print(f"  ✓ {q}")
        except Exception as e:
            cache.log_backfill("financials", q, "failed", 0); failed += 1
            print(f"  ✗ {q}: {str(e)[:60]}")
    print(f"[financials] 完成:ok {ok}, failed {failed}")


INDEX_CODES = [   # 主流宽基指数(竞技场真实基准)
    ("000001.SH", "上证指数"), ("000300.SH", "沪深300"), ("000905.SH", "中证500"),
    ("000852.SH", "中证1000"), ("399006.SZ", "创业板指"), ("000016.SH", "上证50"),
]


def backfill_disclosure(cache, client, start, end, force=False):
    """按报告期拉 disclosure_date(财报披露计划/实际日)—— PIT 财务的'可知日',防前视。"""
    qs = quarters(start, end)
    done = set() if force else cache.done_codes("disclosure")
    todo = [q for q in qs if q not in done]
    print(f"[disclosure] 报告期 {len(qs)} | 待拉 {len(todo)}")
    ok = failed = 0
    for q in todo:
        try:
            df = client.fetch("disclosure_date", end_date=q)
            n = cache.upsert_table("disclosure_date", df, "end_date", q)
            cache.log_backfill("disclosure", q, "ok", n); ok += 1
        except Exception as e:
            cache.log_backfill("disclosure", q, "failed", 0); failed += 1
            print(f"  ✗ {q}: {str(e)[:60]}")
    print(f"[disclosure] 完成:ok {ok}, failed {failed}")


def backfill_indices(cache, client, start, end, force=False):
    """宽基指数日线(逐指数)+ 申万 L1 行业分类/成分(一次性,做行业中性化用)。"""
    done = set() if force else cache.done_codes("index_daily")
    for code, name in INDEX_CODES:
        if code in done:
            continue
        try:
            df = client.fetch("index_daily", ts_code=code, start_date=start, end_date=end)
            n = cache.upsert_table("index_daily", df, "ts_code", code)
            cache.log_backfill("index_daily", code, "ok", n)
            print(f"  ✓ index_daily {code} {name}: {n} 行")
        except Exception as e:
            cache.log_backfill("index_daily", code, "failed", 0)
            print(f"  ✗ index_daily {code}: {str(e)[:60]}")
    try:
        cls = client.fetch("index_classify", level="L1", src="SW2021")
        cache.con.execute("DROP TABLE IF EXISTS index_classify")
        cache.upsert_table("index_classify", cls)
        print(f"  ✓ index_classify(申万L1): {len(cls)} 行")
        done_m = set() if force else cache.done_codes("index_member")
        for l1 in cls["index_code"].tolist():
            if l1 in done_m:
                continue
            try:
                m = client.fetch("index_member_all", l1_code=l1)
                n = cache.upsert_table("index_member", m, "l1_code", l1)
                cache.log_backfill("index_member", l1, "ok", n)
            except Exception as e:
                cache.log_backfill("index_member", l1, "failed", 0)
                print(f"  ✗ index_member {l1}: {str(e)[:50]}")
        print(f"  ✓ index_member: {len(cls)} 个 L1 行业成分")
    except Exception as e:
        print(f"  ✗ index_classify/member: {str(e)[:60]}")


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "20150101"
    end = sys.argv[2] if len(sys.argv) > 2 else "20260622"
    cache = MarketCache()
    client = TushareClient()

    print("拉取 stock_basic(含退市)并落盘...")
    basic = universe.fetch_basic(client, include_delisted=True)
    cache.upsert_basic(basic)
    print(f"  stock_basic: {len(basic)} 条\n")

    days = trading_days(client, start, end)
    print(f"=== 日线(daily)  {start}~{end} ===")
    _by_date(cache, client, days, "daily_by_date", None)
    print(f"\n=== 估值(daily_basic) ===")
    _by_date(cache, client, days, "daily_basic", "daily_basic", table="daily_basic", by_col="trade_date")
    print(f"\n=== 财务(income/balancesheet/cashflow/fina_indicator,vip 按期) ===")
    backfill_financials(cache, client, start, end)

    cache.close()


if __name__ == "__main__":
    main()
