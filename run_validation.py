"""M4 验证应用 —— 给 composite-v2 验明正身:walk-forward OOS 分段 + DSR + PBO。

一次 build 全期 + 一次 Arena(v2/v1/动量/eqw + 猴子×20),提取各账户每日净值 → 收益序列,
喂给 validation 框架:
- walk-forward:逐年 OOS 分段,看 v2 在多少年跑赢最好的猴子(系统化,不手挑时段)。
- DSR:按试验次数 + 偏度峰度校正 v2 夏普显著性。
- PBO:策略池组合对称交叉验证,估"挑最优"的过拟合概率。
运行:.venv/bin/python run_validation.py
"""
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from arena import (Account, Arena, AShareRuleBook, BuyAndHoldEqual,
                   CrossSectionalMomentum, EqualWeightRebalance, Portfolio, RandomTrader)
from arena.leaderboard import _daily_returns
from data.cache import MarketCache
from data.feeds import TushareAFeed
from research.loaders import composite_signals, quality_signals
from research.signal_strategy import SignalStrategy
from research.validation import (deflated_sharpe_ratio, probability_of_backtest_overfitting,
                                 sharpe, sharpe_skew_kurt, walk_forward_windows)

START, END = "20160101", "20260623"
INITIAL = 10_000_000.0
SEG = 252   # 一年约 252 交易日


def main():
    cache = MarketCache()
    s_d, e_d = f"{START[:4]}-{START[4:6]}-{START[6:]}", f"{END[:4]}-{END[4:6]}-{END[6:]}"
    codes = [r[0] for r in cache.con.execute(
        "SELECT DISTINCT ts_code FROM daily_bar WHERE trade_date BETWEEN ? AND ? "
        "AND ts_code NOT LIKE '%.BJ' ORDER BY ts_code", [s_d, e_d]).fetchall()]
    print(f"{START}~{END} | 票池 {len(codes)},构建中(全市场全期,稍慢)...")
    data = TushareAFeed(codes, cache=cache, start=START, end=END).build()
    dates = data.dates
    print(f"标的 {len(data.symbols)} | 交易日 {len(dates)}\n跑竞技场...")

    rb = AShareRuleBook(names=cache.get_names())
    accs = [Account(f"🐒 monkey-{s:02d}", RandomTrader(seed=s), Portfolio(INITIAL), rb, is_benchmark=True)
            for s in range(20)]
    accs += [
        Account("composite-v2", SignalStrategy(lambda d: composite_signals(cache, d),
                                               top_k=30, period=21, name="composite-v2"), Portfolio(INITIAL), rb),
        Account("quality-v1", SignalStrategy(lambda d: quality_signals(cache, d),
                                             top_k=30, period=21, name="quality-v1"), Portfolio(INITIAL), rb),
        Account("momentum", CrossSectionalMomentum(lookback=60, top_k=30, period=21), Portfolio(INITIAL), rb),
        Account("eqw", EqualWeightRebalance(period=21), Portfolio(INITIAL), rb),
    ]
    arena = Arena(data, accs).run()
    rets = {a.strategy.name: _daily_returns(a.equity_curve) for a in arena.accounts}
    monkeys = [n for n in rets if n.startswith("🐒")]
    contenders = [n for n in rets if not n.startswith("🐒")]   # 实际 strategy.name(含后缀)

    # ---- 1. walk-forward:逐年 OOS 分段 ----
    print("=" * 64)
    print("【walk-forward】逐年 OOS:composite-v2 vs 最好的猴子")
    v2 = rets["composite-v2"]
    n_seg = len(v2) // SEG
    wins = 0
    for k in range(n_seg):
        sl = slice(k * SEG, (k + 1) * SEG)
        v2_sr = sharpe(v2[sl])
        best_mk = max(sharpe(rets[m][sl]) for m in monkeys)
        v1_sr = sharpe(rets["quality-v1"][sl])
        win = v2_sr > best_mk
        wins += win
        yr = dates[k * SEG][:4]
        print(f"  {yr}段: v2 {v2_sr:+.3f} | v1 {v1_sr:+.3f} | 最好猴子 {best_mk:+.3f}  {'✅赢' if win else '❌输'}")
    print(f"  → composite-v2 逐年 OOS 胜率: {wins}/{n_seg}")

    # ---- 2. DSR ----
    print("=" * 64)
    print("【DSR】多重检验 + 非正态校正")
    sr, sk, ku = sharpe_skew_kurt(v2)
    cont_srs = [sharpe(rets[c]) for c in contenders]
    sr_std = statistics.pstdev(cont_srs) if len(cont_srs) > 1 else 0.05
    n_trials = len(contenders)
    dsr = deflated_sharpe_ratio(sr, len(v2), n_trials, sr_std, sk, ku)
    print(f"  v2 单期夏普 {sr:.4f} | 偏度 {sk:.2f} 峰度 {ku:.2f} | 试验 {n_trials} | 夏普std {sr_std:.4f}")
    print(f"  → DSR = {dsr:.3f}  ({'✅ 稳健(>0.95)' if dsr > 0.95 else '⚠️ 不显著(需更多 OOS/更少试验)'})")

    # ---- 3. PBO(策略池 CSCV)----
    print("=" * 64)
    print("【PBO】策略池组合对称交叉验证")
    pool = contenders
    matrix = [rets[c] for c in pool]
    pbo = probability_of_backtest_overfitting(matrix, n_splits=10)
    print(f"  策略池 {pool}")
    print(f"  → PBO = {pbo['pbo']:.3f}  ({'✅ 不易过拟合(<0.5)' if pbo['pbo'] < 0.5 else '⚠️ 过拟合风险(>0.5)'})"
          f" | 组合数 {pbo['n_combinations']}")
    print("=" * 64)
    print("注:策略池仅 4 个候选,DSR/PBO 为初步;权重网格的严格 PBO 留作后续。")
    cache.close()


if __name__ == "__main__":
    main()
