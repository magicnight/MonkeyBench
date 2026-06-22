"""每个虚拟账号的私有状态:现金 + 持仓 + 当日锁定(T+1)。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class Portfolio:
    initial_cash: float
    cash: float = 0.0
    positions: Dict[str, int] = field(default_factory=dict)  # symbol -> 股数
    # 当日买入、当日不可卖的股数(T+1)。每个交易日开盘前清空(昨日买入解锁)。
    locked: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if self.cash == 0.0:
            self.cash = self.initial_cash

    def new_day(self) -> None:
        """新交易日:昨天买入的份额解锁。"""
        self.locked.clear()

    def position(self, symbol: str) -> int:
        return self.positions.get(symbol, 0)

    def sellable(self, symbol: str) -> int:
        """可卖 = 持仓 − 当日锁定。"""
        return self.positions.get(symbol, 0) - self.locked.get(symbol, 0)

    def market_value(self, prices: Dict[str, float]) -> float:
        return sum(qty * prices.get(sym, 0.0) for sym, qty in self.positions.items())

    def equity(self, prices: Dict[str, float]) -> float:
        return self.cash + self.market_value(prices)
