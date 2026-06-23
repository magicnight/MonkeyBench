"""回测严谨性验证 —— walk-forward + DSR + PBO,RDP 核心方法论(回答"因子有没有用"的终极武器)。

防止单时段回测 + 多重检验自欺:
- walk_forward_windows / walk_forward_eval:滚动前推,只用过去拟合、未来检验,不手挑时段。
- deflated_sharpe_ratio:按试验次数 + 收益非正态(偏度/峰度)校正夏普显著性
  (Bailey & López de Prado 2014, "The Deflated Sharpe Ratio")。
- probability_of_backtest_overfitting:CSCV 组合对称交叉验证估过拟合概率
  (Bailey, Borwein, López de Prado, Zhu 2017)。

纯标准库(statistics.NormalDist),作用于收益序列/矩阵,与竞技场解耦。
"""
from __future__ import annotations

import math
from itertools import combinations
from statistics import NormalDist

_N = NormalDist()
_EULER = 0.5772156649015329


# ============ 收益统计 helper ============

def sharpe(returns, eps: float = 1e-12) -> float:
    """单期夏普(均值/标准差)。空或零波动 → 0。"""
    n = len(returns)
    if n < 2:
        return 0.0
    mu = sum(returns) / n
    var = sum((r - mu) ** 2 for r in returns) / (n - 1)
    sd = math.sqrt(var)
    return mu / sd if sd > eps else 0.0


def sharpe_skew_kurt(returns):
    """返回 (单期夏普, 偏度, 峰度)。峰度为常规(正态=3)。"""
    n = len(returns)
    if n < 2:
        return 0.0, 0.0, 3.0
    mu = sum(returns) / n
    var = sum((r - mu) ** 2 for r in returns) / (n - 1)
    sd = math.sqrt(var) if var > 0 else 0.0
    if sd == 0:
        return 0.0, 0.0, 3.0
    skew = (sum((r - mu) ** 3 for r in returns) / n) / sd ** 3
    kurt = (sum((r - mu) ** 4 for r in returns) / n) / sd ** 4
    return mu / sd, skew, kurt


# ============ walk-forward 窗口 ============

def walk_forward_windows(dates, train_size: int, test_size: int, step: int | None = None):
    """滚动前推:返回 [(train_dates, test_dates), ...]。

    每个 fold 用 train 段拟合/选参,test 段做样本外(OOS)检验。step 默认 = test_size
    (相邻 fold 的 OOS 段不重叠,拼起来是连续的样本外历史)。"""
    if train_size < 1 or test_size < 1:
        raise ValueError("train_size/test_size 必须 ≥ 1")
    step = step or test_size
    out = []
    i = 0
    while i + train_size + test_size <= len(dates):
        out.append((dates[i:i + train_size], dates[i + train_size:i + train_size + test_size]))
        i += step
    return out


def walk_forward_eval(windows, evaluate):
    """对每个 (train, test) 窗口调 evaluate(train, test) → 结果,汇总成 list。

    evaluate 由调用方提供(可接竞技场:train 段选最优配置,test 段跑 OOS 指标),
    框架本身不绑定竞技场。"""
    return [evaluate(train, test) for train, test in windows]


# ============ Deflated Sharpe Ratio ============

def expected_max_sharpe(sharpe_std: float, n_trials: int) -> float:
    """N 次独立试验下,零假设(真夏普=0)时期望的最大夏普(False Strategy Theorem)。
    sharpe_std = 各试验夏普的标准差。试验越多,光靠运气也能蒙到越高的夏普。"""
    if n_trials < 2 or sharpe_std <= 0:
        return 0.0
    g = _EULER
    return sharpe_std * ((1 - g) * _N.inv_cdf(1 - 1.0 / n_trials)
                         + g * _N.inv_cdf(1 - 1.0 / (n_trials * math.e)))


def deflated_sharpe_ratio(observed_sharpe: float, n_obs: int, n_trials: int,
                          sharpe_std: float, skew: float = 0.0, kurt: float = 3.0) -> float:
    """DSR:在 n_trials 次试验、收益偏度/峰度下,观测夏普显著高于"运气期望最大夏普"的概率。

    observed_sharpe 为单期夏普(与 n_obs 同频)。返回 0–1 概率;**>0.95 才算稳健、非过拟合**。
    多重检验越多(n_trials 大)/收益越左偏厚尾,门槛越高、DSR 越低。"""
    sr0 = expected_max_sharpe(sharpe_std, n_trials)
    denom = 1 - skew * observed_sharpe + (kurt - 1) / 4.0 * observed_sharpe ** 2
    if denom <= 0 or n_obs < 2:
        return float("nan")
    z = (observed_sharpe - sr0) * math.sqrt(n_obs - 1) / math.sqrt(denom)
    return _N.cdf(z)


# ============ PBO via CSCV ============

def probability_of_backtest_overfitting(returns_matrix, n_splits: int = 10) -> dict:
    """CSCV 估回测过拟合概率。returns_matrix:list of N 个配置/策略,每个为等长 T 期收益序列。

    把时间切 n_splits(偶数)块,枚举所有"半数块作 IS / 余下作 OOS"的组合;每组合在 IS 选
    夏普最高的配置,看它在 OOS 的相对排名。**PBO = IS 最优在 OOS 跑输中位数的频率**。
    PBO 越高越过拟合(>0.5 = 样本内最优纯属拟合噪声)。

    返回 {pbo, n_combinations, median_oos_rank}。"""
    M = returns_matrix
    n_cfg = len(M)
    if n_cfg < 2:
        raise ValueError("至少 2 个配置才能比较")
    T = len(M[0])
    S = n_splits
    if S % 2 or S < 2:
        raise ValueError("n_splits 必须为 ≥2 的偶数")
    if T < S:
        raise ValueError("时间期数需 ≥ n_splits")

    blk = T // S
    blocks = [list(range(i * blk, (i + 1) * blk if i < S - 1 else T)) for i in range(S)]

    logits, oos_ranks = [], []
    for is_combo in combinations(range(S), S // 2):
        is_t = [t for s in is_combo for t in blocks[s]]
        oos_t = [t for s in range(S) if s not in is_combo for t in blocks[s]]
        is_sr = [sharpe([M[n][t] for t in is_t]) for n in range(n_cfg)]
        oos_sr = [sharpe([M[n][t] for t in oos_t]) for n in range(n_cfg)]
        n_star = max(range(n_cfg), key=lambda n: is_sr[n])              # IS 最优
        # n_star 在 OOS 的排名:0(最差)..n_cfg-1(最好)
        rank = sorted(range(n_cfg), key=lambda n: oos_sr[n]).index(n_star)
        w = (rank + 1) / (n_cfg + 1)                                    # 相对排名 ∈(0,1)
        logits.append(math.log(w / (1 - w)))
        oos_ranks.append(rank / (n_cfg - 1))                           # 归一 0–1
    pbo = sum(1 for lg in logits if lg < 0) / len(logits)              # logit<0 ⇔ OOS 排名落后半
    return {"pbo": pbo, "n_combinations": len(logits),
            "median_oos_rank": sorted(oos_ranks)[len(oos_ranks) // 2]}
