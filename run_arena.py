"""C:多票竞技场 —— 用已落盘的票跑 截面动量 vs 一群猴子 vs 买入持有 / 等权。

读 data/cache/market.duckdb(全 cache 命中,不打 API)。每票按板块规则自动判定
(科创 ±20 / 主板 ±10 / ST ±5 ...)。这是项目核心问题的多票版:
**动量扣完成本,能不能打过最好的那只猴子?**

窗口由 START/END 指定(默认 2015–2016,backfill 已按交易日全覆盖这两年的全市场,
含当时退市股 → 抗幸存者偏差)。
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

INITIAL_CASH = 10_000_000.0
START = "20150101"
END = "20161231"


def main():
    cache = MarketCache()
    s_d = f"{START[:4]}-{START[4:6]}-{START[6:]}"
    e_d = f"{END[:4]}-{END[4:6]}-{END[6:]}"
    codes = [r[0] for r in cache.con.execute(
        "SELECT DISTINCT ts_code FROM daily_bar WHERE trade_date BETWEEN ? AND ? ORDER BY ts_code",
        [s_d, e_d]).fetchall()]
    names = cache.get_names()
    print(f"窗口 {START}~{END} 内有数据的票:{len(codes)} 只,构建 MarketData...")
    data = TushareAFeed(codes, cache=cache, start=START, end=END).build()
    print(f"标的:{len(data.symbols)} 只 | 交易日:{len(data.dates)} "
          f"({data.dates[0]} ~ {data.dates[-1]}) | 初始资金:{INITIAL_CASH:,.0f}\n")

    rb = AShareRuleBook(names=names)   # per-symbol 板块规则(自动判主板/创业/科创/ST)
    accounts = [Account(f"monkey-{s:02d}", RandomTrader(seed=s),
                        Portfolio(INITIAL_CASH), rb, is_benchmark=True) for s in range(20)]
    accounts += [
        Account("bnh", BuyAndHoldEqual(), Portfolio(INITIAL_CASH), rb, is_benchmark=True),
        Account("eqw", EqualWeightRebalance(period=21), Portfolio(INITIAL_CASH), rb, is_benchmark=True),
        Account("mom", CrossSectionalMomentum(lookback=60, top_k=30, period=21),
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
