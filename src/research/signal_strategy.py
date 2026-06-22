"""SignalStrategy —— 读研究层信号(date × symbol → 分数),截面排序持有 top,定期调仓。

研究层(Qlib / 综合评分 scores.py)产出信号,本策略在竞技场执行。**信号是研究层与
执行层的唯一接口**:策略只读分数、不碰引擎,也不关心分数怎么来的(动量 / F-Score / ML 都行)。
"""
from __future__ import annotations

from typing import Callable, List, Mapping, Union

from arena.market import Order
from arena.strategies import _rebalance_to as rebalance_to   # 复用等权调仓
from arena.strategy import Context, Strategy

# 信号形态:{date: {symbol: score}} 或 callable(date) -> {symbol: score}
Signals = Union[Mapping[str, Mapping[str, float]], Callable[[str], Mapping[str, float]]]


class SignalStrategy(Strategy):
    """按信号分数截面排序,每 period 调仓持有 top_k 等权。"""

    def __init__(self, signals: Signals, top_k: int = 20, period: int = 21,
                 name: str | None = None):
        self.signals = signals
        self.top_k = top_k
        self.period = period
        self.name = name or f"📊 signal(k{top_k})"
        self.reset()

    def reset(self) -> None:
        self.counter = 0

    def _scores_on(self, date: str) -> Mapping[str, float]:
        if callable(self.signals):
            return self.signals(date) or {}
        return self.signals.get(date, {})

    def on_bar(self, ctx: Context) -> List[Order]:
        self.counter += 1
        if self.counter % self.period != 1:
            return []
        scores = self._scores_on(ctx.now)
        if not scores:
            return []
        uni = set(ctx.universe)
        ranked = sorted(
            ((s, sc) for s, sc in scores.items() if s in uni and ctx.price(s) is not None),
            key=lambda kv: kv[1], reverse=True,
        )
        winners = [s for s, _ in ranked[: self.top_k]]
        if not winners:
            return []
        return rebalance_to(ctx, winners)
