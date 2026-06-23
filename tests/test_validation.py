"""M4 验证框架测试 —— walk-forward 窗口 + DSR(多重检验惩罚)+ PBO(区分稳健/过拟合)。

纯统计、确定性构造(不用随机)。PBO 用两个对照矩阵:
- 稳健:配置0 恒定真 edge → IS/OOS 都最优 → PBO 低
- 过拟合:每个配置只在自己那段时间"作弊"高 → IS 最优到 OOS 必崩 → PBO 高
"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from research.validation import (deflated_sharpe_ratio, expected_max_sharpe,
                                 probability_of_backtest_overfitting, sharpe,
                                 sharpe_skew_kurt, walk_forward_eval, walk_forward_windows)


def test_walk_forward_windows():
    dates = list(range(100))
    w = walk_forward_windows(dates, train_size=40, test_size=20)
    assert len(w) == 3                                   # 0-60, 20-80, 40-100
    assert w[0][0] == list(range(40)) and w[0][1] == list(range(40, 60))
    assert w[1][1] == list(range(60, 80))               # OOS 段相邻不重叠
    assert w[2][1] == list(range(80, 100))
    # 拼起来的 OOS 是连续样本外历史
    oos = [t for _, te in w for t in te]
    assert oos == list(range(40, 100))


def test_walk_forward_eval():
    dates = list(range(60))
    w = walk_forward_windows(dates, 20, 20)
    res = walk_forward_eval(w, lambda tr, te: len(te))
    assert res == [20, 20]


def test_sharpe_helpers():
    assert sharpe([]) == 0.0
    assert sharpe([0.01, 0.01, 0.01]) == 0.0            # 零波动
    s, sk, ku = sharpe_skew_kurt([0.01, -0.02, 0.03, -0.01, 0.02])
    assert isinstance(s, float) and ku > 0


def test_expected_max_sharpe_grows_with_trials():
    assert expected_max_sharpe(0.1, 2) < expected_max_sharpe(0.1, 100)
    assert expected_max_sharpe(0.1, 1) == 0.0           # <2 试验无意义


def test_dsr_penalizes_more_trials():
    """同样的观测夏普,试验次数越多 → DSR 越低(蒙中的可能越大)。"""
    few = deflated_sharpe_ratio(0.12, 1000, 5, sharpe_std=0.05)
    many = deflated_sharpe_ratio(0.12, 1000, 500, sharpe_std=0.05)
    assert few > many


def test_dsr_high_sharpe_significant():
    """单期夏普很高 + 试验不多 → DSR 接近 1(稳健)。"""
    d = deflated_sharpe_ratio(0.30, 2000, 10, sharpe_std=0.05)
    assert d > 0.95


def test_dsr_weak_sharpe_not_significant():
    """夏普仅略高于运气期望最大值 → DSR 低。"""
    d = deflated_sharpe_ratio(0.05, 500, 200, sharpe_std=0.06)
    assert d < 0.5


def _robust_matrix(T=120, N=5):
    out = []
    for n in range(N):
        if n == 0:
            out.append([0.02 + 0.003 * math.sin(t * 0.3) for t in range(T)])   # 真 edge:高且稳
        else:
            out.append([0.006 * math.sin(t * 0.3 + n) for t in range(T)])       # 0 均值噪声
    return out


def _overfit_matrix(T=100, N=5):
    seg = T // N
    out = []
    for n in range(N):
        out.append([0.05 if n * seg <= t < (n + 1) * seg else -0.01 for t in range(T)])
    return out


def test_pbo_robust_low():
    r = probability_of_backtest_overfitting(_robust_matrix(), n_splits=10)
    assert r["pbo"] < 0.3                                # 真 edge → 不过拟合
    assert r["n_combinations"] == 252                   # C(10,5)


def test_pbo_overfit_high():
    o = probability_of_backtest_overfitting(_overfit_matrix(), n_splits=10)
    r = probability_of_backtest_overfitting(_robust_matrix(), n_splits=10)
    assert o["pbo"] > r["pbo"]                           # 过拟合矩阵 PBO 明显更高
    assert o["pbo"] > 0.5


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ✓ {name}")
    print("✅ M4 验证框架(walk-forward + DSR + PBO)全部通过")
