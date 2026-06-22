"""C:多票竞技场 —— 用已落盘的票跑 截面动量 vs 一群猴子 vs 买入持有 / 等权。

读 data/cache/market.duckdb(全 cache 命中,不打 API)。每票按板块规则自动判定
(科创 ±20 / 主板 ±10 / ST ±5 ...)。这是项目核心问题的多票版:
**动量扣完成本,能不能打过最好的那只猴子?**

运行:  .venv/bin/python run_arena.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from arena import (Account, Arena, AShareRuleBook, BuyAndHoldEqual,
                   CrossSectionalMomentum, EqualWeightRebalance, Portfolio,
                   RandomTrader, leaderboard, render, summarize)
from data.cache import MarketCache
from data.feeds import TushareAFeed

INITIAL_CASH = 10_000_000.0    # 多票需要更大账户才能分散(1000万)
START = "20220101"             # 回测窗口起点(避免老主板票把 union 拉到 1990s)


def main():
    cache = MarketCache()
    codes = [r[0] for r in cache.con.execute(
        "SELECT DISTINCT ts_code FROM daily_bar ORDER BY ts_code").fetchall()]
    names = cache.get_names()
    print(f"已落盘 {len(codes)} 票,构建多票 MarketData(>= {START})...")
    data = TushareAFeed(codes, cache=cache, start=START).build()
    print(f"标的:{len(data.symbols)} 只 | 交易日:{len(data.dates)} "
          f"({data.dates[0]} ~ {data.dates[-1]}) | 初始资金:{INITIAL_CASH:,.0f}\n")

    rb = AShareRuleBook(names=names)   # per-symbol 板块规则(自动判主板/创业/科创/ST)
    accounts = [Account(f"monkey-{s:02d}", RandomTrader(seed=s),
                        Portfolio(INITIAL_CASH), rb, is_benchmark=True) for s in range(20)]
    accounts += [
        Account("bnh", BuyAndHoldEqual(), Portfolio(INITIAL_CASH), rb, is_benchmark=True),
        Account("eqw", EqualWeightRebalance(period=21), Portfolio(INITIAL_CASH), rb, is_benchmark=True),
        Account("mom", CrossSectionalMomentum(lookback=60, top_k=20, period=21),
                Portfolio(INITIAL_CASH), rb, is_benchmark=False),
    ]

    arena = Arena(data, accounts).run()
    board = leaderboard(arena, sort_by="sharpe")
    print(render(board))
    print("\n── 点评 " + "─" * 40)
    print(summarize(board))
    print(f"\n标的池 {len(codes)} 票 | 事件日志 {len(arena.log.events)} 条")
    cache.close()


if __name__ == "__main__":
    main()
