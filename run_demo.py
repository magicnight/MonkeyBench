"""演示:20 只随机猴子 + 买入持有 + 等权再平衡 + 1 个截面动量对手,
在 A股 规则下同台跑两年合成数据,看谁能爬上排行榜。

运行:  python run_demo.py
(纯标准库,零依赖,不需要任何 API key)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from arena import (
    Account, Arena, Portfolio, SyntheticFeed, A_SHARE,
    RandomTrader, BuyAndHoldEqual, EqualWeightRebalance, CrossSectionalMomentum,
    leaderboard, render, summarize,
)

INITIAL_CASH = 1_000_000.0
RULES = A_SHARE


def make_account(aid, strategy, is_benchmark):
    return Account(
        account_id=aid,
        strategy=strategy,
        portfolio=Portfolio(initial_cash=INITIAL_CASH),
        rules=RULES,
        is_benchmark=is_benchmark,
    )


def main():
    data = SyntheticFeed(n_symbols=8, n_days=504, seed=7).build()
    print(f"市场:{RULES.name} | 标的:{len(data.symbols)} 只 | "
          f"交易日:{len(data.dates)} | 初始资金:{INITIAL_CASH:,.0f}\n")

    accounts = []
    # 20 只随机猴子(基准,各自不同种子)
    for s in range(20):
        accounts.append(make_account(f"monkey-{s:02d}", RandomTrader(seed=s), True))
    # 买入持有 + 等权再平衡(基准)
    accounts.append(make_account("bnh", BuyAndHoldEqual(), True))
    accounts.append(make_account("eqw", EqualWeightRebalance(period=21), True))
    # 真正的对手:截面动量
    accounts.append(make_account("mom", CrossSectionalMomentum(lookback=60, top_k=3, period=21), False))

    arena = Arena(data, accounts).run()
    board = leaderboard(arena, sort_by="sharpe")

    print(render(board))
    print()
    print("── 点评 " + "─" * 50)
    print(summarize(board))
    print()
    print(f"事件日志条数:{len(arena.log.events)}(成交/拒单/估值,可用于事后归因)")


if __name__ == "__main__":
    main()
