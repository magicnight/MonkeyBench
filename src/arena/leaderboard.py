"""排行榜:从权益曲线算指标、排名,打印表格。

指标:总收益、年化夏普、最大回撤、胜率(简化为上涨天数占比)。
基准账号(猴子/买入持有)单独标注,方便一眼看出"真策略到底有没有打过运气"。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

from .arena import Account, Arena

TRADING_DAYS = 252


@dataclass
class Metrics:
    name: str
    is_benchmark: bool
    total_return: float
    sharpe: float
    max_drawdown: float
    win_rate: float
    final_equity: float


def _daily_returns(curve: List[Tuple[str, float]]) -> List[float]:
    vals = [v for _, v in curve]
    rets = []
    for a, b in zip(vals[:-1], vals[1:]):
        rets.append(b / a - 1.0 if a > 0 else 0.0)
    return rets


def _sharpe(rets: List[float]) -> float:
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return 0.0
    return (mean / sd) * math.sqrt(TRADING_DAYS)  # 注:未扣无风险利率,简化


def _max_drawdown(curve: List[Tuple[str, float]]) -> float:
    peak = -math.inf
    mdd = 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd


def compute(acc: Account) -> Metrics:
    curve = acc.equity_curve
    rets = _daily_returns(curve)
    start = curve[0][1] if curve else acc.portfolio.initial_cash
    end = curve[-1][1] if curve else start
    win = sum(1 for r in rets if r > 0) / len(rets) if rets else 0.0
    return Metrics(
        name=acc.strategy.name,
        is_benchmark=acc.is_benchmark,
        total_return=end / start - 1.0 if start > 0 else 0.0,
        sharpe=_sharpe(rets),
        max_drawdown=_max_drawdown(curve),
        win_rate=win,
        final_equity=end,
    )


def leaderboard(arena: Arena, sort_by: str = "sharpe") -> List[Metrics]:
    metrics = [compute(a) for a in arena.accounts]
    metrics.sort(key=lambda m: getattr(m, sort_by), reverse=True)
    return metrics


def render(metrics: List[Metrics]) -> str:
    lines = []
    header = f"{'#':>3}  {'策略':<26}{'总收益':>9}{'夏普':>8}{'最大回撤':>10}{'胜率':>8}  类型"
    lines.append(header)
    lines.append("─" * len(header))
    for rank, m in enumerate(metrics, 1):
        tag = "基准" if m.is_benchmark else "★对手"
        lines.append(
            f"{rank:>3}  {m.name:<26}"
            f"{m.total_return*100:>8.1f}%"
            f"{m.sharpe:>8.2f}"
            f"{m.max_drawdown*100:>9.1f}%"
            f"{m.win_rate*100:>7.1f}%  {tag}"
        )
    return "\n".join(lines)


def summarize(metrics: List[Metrics]) -> str:
    """一句话点评:真策略有没有打过最好的猴子和买入持有。"""
    monkeys = [m for m in metrics if m.name.startswith("🐒")]
    contenders = [m for m in metrics if not m.is_benchmark]
    out = []
    if monkeys:
        best_monkey = max(monkeys, key=lambda m: m.sharpe)
        out.append(f"最好的猴子:{best_monkey.name} 夏普 {best_monkey.sharpe:.2f}"
                   f"(这就是本规模的运气天花板/噪声地板)")
    for c in contenders:
        if monkeys:
            verdict = "✅ 打过了最好的猴子" if c.sharpe > best_monkey.sharpe else "❌ 没打过最好的猴子 → 大概没有真 edge"
            out.append(f"{c.name}:夏普 {c.sharpe:.2f} {verdict}")
    return "\n".join(out)
