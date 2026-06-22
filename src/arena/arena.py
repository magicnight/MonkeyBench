"""竞技场:把多个账号在同一份数据、同一个引擎上跑成一场锦标赛。

核心是这个循环的时序,它从物理上保证无未来函数:
  到达 D 日:
    1. new_day —— 昨日买入解锁
    2. 先成交各账号"挂着的单"(D-1 收盘的决策)→ 用 D 的【开盘】成交
    3. 用 D 的【收盘】给各账号估值,记权益曲线
    4. 各账号看 D 的收盘做决策 → 产生挂到 D+1 的单
最后一根 bar 的决策无害地丢弃(没有下一根可成交)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .datafeed import MarketData
from .engine import MatchingEngine
from .eventlog import EventLog
from .market import Order, as_rulebook
from .portfolio import Portfolio
from .strategy import Context, Strategy


@dataclass
class Account:
    account_id: str
    strategy: Strategy
    portfolio: Portfolio
    rules: object  # MarketRules 或 RuleBook(A股按板块 per-symbol 解析)
    is_benchmark: bool = False
    pending: List[Order] = field(default_factory=list)
    equity_curve: List[Tuple[str, float]] = field(default_factory=list)


class Arena:
    def __init__(self, data: MarketData, accounts: List[Account],
                 engine: Optional[MatchingEngine] = None,
                 log: Optional[EventLog] = None):
        self.data = data
        self.accounts = accounts
        self.engine = engine or MatchingEngine()
        self.log = log or EventLog()

    def run(self) -> "Arena":
        for acc in self.accounts:
            acc.strategy.reset()
        # 每个账号的规则解析器:A股 AShareRuleBook 按板块,其余 StaticRuleBook
        books = {acc.account_id: as_rulebook(acc.rules) for acc in self.accounts}

        n = len(self.data.dates)
        for i in range(n):
            date = self.data.dates[i]
            opens = self.data.opens(i)
            closes = self.data.closes(i)

            # 1) 新交易日:解锁
            for acc in self.accounts:
                acc.portfolio.new_day()

            # 2) 成交昨日收盘挂出的单,用今日开盘价 + 该 symbol 的板块规则
            for acc in self.accounts:
                book = books[acc.account_id]
                for order in acc.pending:
                    bar = self.data.bar(order.symbol, i)
                    if bar is None:
                        continue
                    self.engine.fill(order, opens.get(order.symbol, bar.open),
                                     bar.prev_close, book.for_symbol(order.symbol),
                                     acc.portfolio, self.log, date)
                acc.pending = []

            # 3) 用今日收盘估值,记权益
            for acc in self.accounts:
                eq = acc.portfolio.equity(closes)
                acc.equity_curve.append((date, eq))

            # 4) 今日收盘后决策,挂到明日
            if i < n - 1:  # 最后一根不再决策
                for acc in self.accounts:
                    ctx = Context(self.data, i, acc.portfolio,
                                  books[acc.account_id], acc.account_id)
                    acc.pending = acc.strategy.on_bar(ctx) or []

        return self
