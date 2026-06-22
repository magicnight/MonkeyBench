"""策略插件接口 + Context。

加一个新策略 = 继承 Strategy、实现 on_bar。策略只能看到"截至当前收盘"的信息,
返回订单后由引擎在下一根开盘成交 —— 物理上杜绝未来函数。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from .market import MarketRules, Order, RuleBook
from .portfolio import Portfolio


class Context:
    """喂给策略的只读视图。封装"截至 index 的历史 + 本账号组合状态"。

    规则按 symbol 取(A股不同板块涨跌停/lot 不同):用 `ctx.rules_for(sym)` 或
    `ctx.size_buy(budget, price, sym)`。
    """

    def __init__(self, data, index: int, pf: Portfolio, rulebook: RuleBook,
                 account_id: str, last_close: Optional[Dict[str, float]] = None):
        self._data = data            # MarketData
        self._i = index
        self._pf = pf
        self._book = rulebook
        self.account_id = account_id
        self._last_close = last_close or {}   # 最后已知价(停牌/退市持仓估值用)

    @property
    def now(self) -> str:
        return self._data.dates[self._i]

    @property
    def universe(self) -> List[str]:
        return self._data.symbols

    def rules_for(self, symbol: str) -> MarketRules:
        """该 symbol 的板块规则(主板/创业/科创/ST)。"""
        return self._book.for_symbol(symbol)

    def price(self, symbol: str) -> Optional[float]:
        """当前收盘价。"""
        bar = self._data.bar(symbol, self._i)
        return bar.close if bar else None

    def history(self, symbol: str, n: int) -> List[float]:
        """最近 n 根收盘(含当前),不足则返回更短。"""
        start = max(0, self._i - n + 1)
        return [b.close for b in self._data.bars[symbol][start: self._i + 1] if b is not None]

    # --- 组合状态 ---
    @property
    def cash(self) -> float:
        return self._pf.cash

    def position(self, symbol: str) -> int:
        return self._pf.position(symbol)

    def sellable(self, symbol: str) -> int:
        return self._pf.sellable(symbol)

    def equity(self) -> float:
        """用最后已知价估值(停牌/退市持仓不蒸发)。"""
        return self._pf.equity(self._last_close)

    # --- 工具 ---
    def size_buy(self, budget: float, price: float, symbol: str) -> int:
        """按预算和该 symbol 的板块 lot 规则算可买股数。"""
        if price <= 0:
            return 0
        return self.rules_for(symbol).align_buy_qty(int(budget / price))


class Strategy(ABC):
    name: str = "strategy"

    def reset(self) -> None:
        """每次回测开始前重置内部状态。"""
        pass

    @abstractmethod
    def on_bar(self, ctx: Context) -> List[Order]:
        ...
