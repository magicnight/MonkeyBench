"""批量 backfill —— **按交易日**循环(Tushare 官方推荐做法)。

为什么按 trade_date 而非 ts_code:全市场 5500+ 票,按票要循环 5500×2 次小调用;
按交易日只需 ~250 天/年 × 2 次,一次 `daily(trade_date)` 拿全市场当天(~5500 行)。
调用数砍半、连接锐减、每次数据量大 → 又快又稳,且增量每天仅 2 次调用、秒级。

- 断点续传:backfill_log(dataset='daily_by_date')记已拉日期,重跑跳过。
- 增量:只拉缺的交易日(每日跑一次补当天)。
- 稳定:TushareClient 退避重试 + socket 超时(防 hang)。

运行:  PYTHONPATH=src .venv/bin/python -m data.backfill                  # 默认 2015 至今
       PYTHONPATH=src .venv/bin/python -m data.backfill 20100101 20261231
"""
from __future__ import annotations

import sys

from . import universe
from .cache import MarketCache
from .feeds import TushareClient, fetch_to_cache

DATASET = "daily_by_date"


def trading_days(client: TushareClient, start: str, end: str) -> list:
    cal = client.fetch("trade_cal", exchange="SSE", is_open="1",
                        start_date=start, end_date=end, fields="cal_date")
    return sorted(cal["cal_date"].tolist())


def backfill_by_date(cache: MarketCache, client: TushareClient,
                     start: str, end: str, force: bool = False):
    """按交易日逐日拉全市场 daily + adj_factor → 落库。"""
    days = trading_days(client, start, end)
    done = set() if force else cache.done_codes(DATASET)
    todo = [d for d in days if d not in done]
    print(f"[by_date] 交易日 {len(days)} | 已完成 {len(days) - len(todo)} | 待拉 {len(todo)}")
    ok = empty = failed = rows = 0
    for i, d in enumerate(todo, 1):
        try:
            daily = client.fetch("daily", trade_date=d)
            if len(daily) == 0:
                cache.log_backfill(DATASET, d, "empty", 0); empty += 1; continue
            adj = client.fetch("adj_factor", trade_date=d)
            merged = daily.merge(adj[["ts_code", "adj_factor"]], on="ts_code", how="left")
            n = cache.upsert_daily(merged)
            cache.log_backfill(DATASET, d, "ok", n)
            ok += 1; rows += n
        except Exception as e:
            cache.log_backfill(DATASET, d, "failed", 0); failed += 1
            print(f"  ✗ {d}: {str(e)[:60]}")
        if i % 20 == 0:
            print(f"  ...{i}/{len(todo)}  (ok {ok}, empty {empty}, failed {failed}, 累计 {rows:,} 行)")
    print(f"[by_date] 完成:ok {ok}, empty {empty}, failed {failed}, 累计 {rows:,} 行")
    return ok, failed


def backfill_daily(ts_codes, cache: MarketCache, client: TushareClient, force: bool = False):
    """按 ts_code 逐票拉全历史(备用:补个别票时用;全市场请用 backfill_by_date)。"""
    done = set() if force else cache.done_codes("daily")
    todo = [c for c in ts_codes if c not in done]
    print(f"[by_code] 共 {len(ts_codes)} | 待拉 {len(todo)}")
    ok = failed = 0
    for code in todo:
        try:
            n = fetch_to_cache(code, client, cache)
            cache.log_backfill("daily", code, "ok", n); ok += 1
        except Exception as e:
            cache.log_backfill("daily", code, "failed", 0); failed += 1
            print(f"  ✗ {code}: {str(e)[:60]}")
    print(f"[by_code] 完成:ok {ok}, failed {failed}")
    return ok, failed


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else "20150101"
    end = sys.argv[2] if len(sys.argv) > 2 else "20260622"
    cache = MarketCache()
    client = TushareClient()
    print("拉取 stock_basic(含退市)并落盘...")
    basic = universe.fetch_basic(client, include_delisted=True)
    cache.upsert_basic(basic)
    print(f"  stock_basic: {len(basic)} 条")
    print(f"按交易日 backfill:{start} ~ {end}\n")
    backfill_by_date(cache, client, start, end)
    cache.close()


if __name__ == "__main__":
    main()
