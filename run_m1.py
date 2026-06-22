"""M1 最小闭环:拉 688205(德科立,科创板)→ 落 DuckDB → 喂引擎 → 排行榜。

规则用 AShareRuleBook 自动按代码判板块(688 → 科创板 ±20%/lot≥200),验证解析器。
第一次运行打 Tushare API 并落盘 data/cache/market.duckdb;之后从本地读,不再消耗配额。
运行:  .venv/bin/python run_m1.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from arena import (Account, Arena, AShareRuleBook, BuyAndHoldEqual, Portfolio,
                   RandomTrader, leaderboard, render, summarize)
from data.feeds import TushareAFeed

TS_CODE = "688205.SH"
INITIAL_CASH = 1_000_000.0
RULES = AShareRuleBook()   # 按代码自动判板块


def main():
    print(f"构建 MarketData({TS_CODE})...")
    data = TushareAFeed(TS_CODE).build()
    rule = RULES.for_symbol(TS_CODE)
    print(f"\n标的:{TS_CODE} | 交易日:{len(data.dates)} ({data.dates[0]} ~ {data.dates[-1]})"
          f" | 板块:{rule.name}(±{rule.price_limit_pct:.0%}, 买入≥{rule.buy_min} 股)\n")

    accounts = [
        Account(account_id=f"monkey-{s:02d}", strategy=RandomTrader(seed=s),
                portfolio=Portfolio(initial_cash=INITIAL_CASH), rules=RULES, is_benchmark=True)
        for s in range(10)
    ]
    accounts.append(Account(account_id="bnh", strategy=BuyAndHoldEqual(),
                            portfolio=Portfolio(initial_cash=INITIAL_CASH),
                            rules=RULES, is_benchmark=True))

    arena = Arena(data, accounts).run()
    board = leaderboard(arena, sort_by="sharpe")
    print(render(board))
    print("\n── 点评 " + "─" * 40)
    print(summarize(board))
    print(f"\n事件日志:{len(arena.log.events)} 条 | 缓存库:data/cache/market.duckdb")


if __name__ == "__main__":
    main()
