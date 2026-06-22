"""批量 backfill:票池 × 限速拉日线 → 落 DuckDB。

- 断点续传:backfill_log 里 status=ok 的票自动跳过,中断后重跑只补未完成。
- 增量:fetch_to_cache 用 INSERT OR REPLACE,重拉同票更新而非重复。
- manifest:backfill_log 记每票 ok/failed,供审计与失败重试(--retry-failed)。
- 限速:TushareClient 默认对 500/min 硬顶留弹性(~400/min)+ 退避。

运行:  PYTHONPATH=src .venv/bin/python -m data.backfill
"""
from __future__ import annotations

from . import universe
from .cache import MarketCache
from .feeds import TushareClient, fetch_to_cache


def backfill_daily(ts_codes, cache: MarketCache, client: TushareClient, force: bool = False):
    done = set() if force else cache.done_codes("daily")
    todo = [c for c in ts_codes if c not in done]
    print(f"[daily] 共 {len(ts_codes)} | 已完成 {len(ts_codes) - len(todo)} | 待拉 {len(todo)}")
    ok = failed = 0
    for i, code in enumerate(todo, 1):
        try:
            n = fetch_to_cache(code, client, cache)
            cache.log_backfill("daily", code, "ok", n)
            ok += 1
        except Exception as e:
            cache.log_backfill("daily", code, "failed", 0)
            failed += 1
            print(f"  ✗ {code}: {str(e)[:60]}")
        if i % 50 == 0:
            print(f"  ...{i}/{len(todo)}  (ok {ok}, failed {failed})")
    print(f"[daily] 完成:ok {ok}, failed {failed}")
    return ok, failed


def main():
    cache = MarketCache()
    client = TushareClient()

    print("拉取 stock_basic(含退市)并落盘...")
    basic = universe.fetch_basic(client, include_delisted=True)
    cache.upsert_basic(basic)
    print(f"  stock_basic: {len(basic)} 条(含退市/暂停)")

    star = universe.star_codes(basic)
    hs300 = universe.hs300_codes(client)
    codes = sorted(set(star) | set(hs300))
    print(f"票池:科创板 {len(star)} + 沪深300 {len(hs300)} → 去重 {len(codes)} 只\n")

    backfill_daily(codes, cache, client)
    cache.close()


if __name__ == "__main__":
    main()
