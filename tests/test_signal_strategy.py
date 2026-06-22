"""SignalStrategy 端到端测试(合成数据,不碰 DuckDB)。运行:.venv/bin/python tests/test_signal_strategy.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from arena import A_SHARE, Account, Arena, Portfolio, SyntheticFeed
from research.signal_strategy import SignalStrategy


def test_signal_holds_top():
    data = SyntheticFeed(n_symbols=10, n_days=120, seed=3).build()
    # 固定信号:SYM000 最高、SYM009 最低 → 策略应只持有 top3 = SYM000/001/002
    score_by_sym = {s: (100 - i) for i, s in enumerate(data.symbols)}
    signals = {d: score_by_sym for d in data.dates}
    acc = Account("sig", SignalStrategy(signals, top_k=3, period=21),
                  Portfolio(1_000_000.0), A_SHARE)
    Arena(data, [acc]).run()
    held = set(acc.portfolio.positions.keys())
    assert held, "应有持仓"
    assert held.issubset({"SYM000", "SYM001", "SYM002"}), f"应只持 top3,实际 {held}"


def test_empty_signal_no_trade():
    data = SyntheticFeed(n_symbols=5, n_days=60, seed=1).build()
    acc = Account("sig", SignalStrategy({}, top_k=3), Portfolio(1_000_000.0), A_SHARE)
    Arena(data, [acc]).run()
    assert not acc.portfolio.positions, "空信号不应交易"


def test_callable_signal():
    data = SyntheticFeed(n_symbols=6, n_days=80, seed=2).build()
    acc = Account("sig", SignalStrategy(
        lambda d: {s: (10 - i) for i, s in enumerate(data.symbols)}, top_k=2, period=21),
        Portfolio(1_000_000.0), A_SHARE)
    Arena(data, [acc]).run()
    assert set(acc.portfolio.positions.keys()).issubset({"SYM000", "SYM001"})


if __name__ == "__main__":
    for fn in [test_signal_holds_top, test_empty_signal_no_trade, test_callable_signal]:
        fn(); print(f"  ✓ {fn.__name__}")
    print("✅ SignalStrategy 全部通过")
