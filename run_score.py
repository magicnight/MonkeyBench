"""M5 接入测:综合质量分(本地 DuckDB,PIT)上竞技场 vs 动量 vs 猴子 vs 买入持有。

核心问题的基本面版:**基本面质量评分扣完成本,能不能打过最好的猴子?**(像揭穿动量那样检验)
质量分由 research.loaders.quality_signals 从本地 DuckDB 算(PIT,无未来函数)。
运行:.venv/bin/python run_score.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from arena import (Account, Arena, AShareRuleBook, BuyAndHoldEqual,
                   CrossSectionalMomentum, EqualWeightRebalance, Portfolio,
                   RandomTrader, leaderboard, render, summarize)
from data.cache import MarketCache
from data.feeds import TushareAFeed
from research.loaders import composite_signals, quality_signals
from research.signal_strategy import SignalStrategy

INITIAL_CASH = 10_000_000.0
START = sys.argv[1] if len(sys.argv) > 1 else "20200101"   # 可传窗口:run_score.py 20160101 20191231
END = sys.argv[2] if len(sys.argv) > 2 else "20231231"


def main():
    cache = MarketCache()
    s_d, e_d = f"{START[:4]}-{START[4:6]}-{START[6:]}", f"{END[:4]}-{END[4:6]}-{END[6:]}"
    codes = [r[0] for r in cache.con.execute(
        "SELECT DISTINCT ts_code FROM daily_bar WHERE trade_date BETWEEN ? AND ? "
        "AND ts_code NOT LIKE '%.BJ' ORDER BY ts_code",   # 排除北交所(非目标)
        [s_d, e_d]).fetchall()]
    names = cache.get_names()
    print(f"窗口 {START}~{END} | 票池 {len(codes)},构建 MarketData...")
    data = TushareAFeed(codes, cache=cache, start=START, end=END).build()
    print(f"标的 {len(data.symbols)} | 交易日 {len(data.dates)} ({data.dates[0]}~{data.dates[-1]})\n")

    rb = AShareRuleBook(names=names)
    accounts = [Account(f"monkey-{s:02d}", RandomTrader(seed=s),
                        Portfolio(INITIAL_CASH), rb, is_benchmark=True) for s in range(20)]
    accounts += [
        Account("bnh", BuyAndHoldEqual(), Portfolio(INITIAL_CASH), rb, is_benchmark=True),
        Account("eqw", EqualWeightRebalance(period=21), Portfolio(INITIAL_CASH), rb, is_benchmark=True),
        Account("mom", CrossSectionalMomentum(lookback=60, top_k=30, period=21),
                Portfolio(INITIAL_CASH), rb, is_benchmark=False),
        Account("quality", SignalStrategy(lambda d: quality_signals(cache, d),
                                          top_k=30, period=21, name="📊 quality-v1"),
                Portfolio(INITIAL_CASH), rb, is_benchmark=False),
        Account("composite", SignalStrategy(lambda d: composite_signals(cache, d),
                                            top_k=30, period=21, name="📊 composite-v2(质量+估值+趋势+行业中性)"),
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
