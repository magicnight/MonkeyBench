"""共享撮合引擎 —— 整个系统唯一的"成交真相来源"。

所有账号的订单都从这里过,确保排行榜公平:同样的成交时点、同样的规则、
同样的成本。这正是 backtrader/Qlib 自带回测给不了你的语义,所以这层自己写。

堵掉三个"纸面交易会撒谎"的口子:
  1. 未来函数:T 收盘决策 → T+1 开盘成交(由 Arena 的循环保证,引擎只在 open 成交)
  2. 涨跌停:封板时排不进单 —— 涨停拒买、跌停拒卖
  3. 流动性:滑点建模,而非无限流动性按盘口成交

规则按 symbol 解析(主板/创业/科创/ST 各不同):由 Arena 传入该 symbol 的 MarketRules,
引擎只负责"用给定规则撮合"。lot 对齐走 rules.align_buy_qty / align_sell_qty。
"""
from __future__ import annotations

from .eventlog import EventLog
from .market import MarketRules, Order, OrderSide
from .portfolio import Portfolio


class MatchingEngine:
    def fill(
        self,
        order: Order,
        open_price: float,
        prev_close: float,
        rules: MarketRules,
        pf: Portfolio,
        log: EventLog,
        date: str,
    ) -> None:
        """以 open_price 成交一笔市价单(rules 为该 symbol 的板块规则)。拒绝记入日志。"""

        # --- 涨跌停检查:封板就排不进单(与数量无关) ---
        if rules.price_limit_pct is not None and prev_close > 0:
            limit_up = prev_close * (1 + rules.price_limit_pct)
            limit_down = prev_close * (1 - rules.price_limit_pct)
            eps = 1e-6
            if order.side == OrderSide.BUY and open_price >= limit_up - eps:
                log.append(type="reject", reason="limit_up", date=date,
                           account_id=order.account_id, symbol=order.symbol,
                           side=order.side.value, qty=order.qty)
                return
            if order.side == OrderSide.SELL and open_price <= limit_down + eps:
                log.append(type="reject", reason="limit_down", date=date,
                           account_id=order.account_id, symbol=order.symbol,
                           side=order.side.value, qty=order.qty)
                return

        # --- 滑点:买入抬价、卖出压价 ---
        slip = rules.slippage_bps / 1e4
        if order.side == OrderSide.BUY:
            qty = rules.align_buy_qty(order.qty)        # 板块 lot:科创板 ≥200+1,主板 100 整数倍
            if qty <= 0:
                return
            self._fill_buy(order, qty, open_price * (1 + slip), rules, pf, log, date)
        else:
            self._fill_sell(order, open_price * (1 - slip), rules, pf, log, date)

    def _commission(self, notional: float, rules: MarketRules) -> float:
        return max(notional * rules.commission_rate, rules.min_commission)

    def _fill_buy(self, order, qty, price, rules, pf, log, date):
        notional = qty * price
        commission = self._commission(notional, rules)
        total = notional + commission
        if total > pf.cash + 1e-6:
            # 现金不足:按可负担额度 + 板块 lot 重对齐一次
            affordable = pf.cash / (price * (1 + rules.commission_rate))
            qty = rules.align_buy_qty(int(affordable))
            if qty <= 0:
                log.append(type="reject", reason="insufficient_cash", date=date,
                           account_id=order.account_id, symbol=order.symbol,
                           side="buy", qty=order.qty)
                return
            notional = qty * price
            commission = self._commission(notional, rules)
            total = notional + commission

        pf.cash -= total
        pf.positions[order.symbol] = pf.positions.get(order.symbol, 0) + qty
        if rules.lock_same_day_buy:  # T+1:今日买入今日锁定
            pf.locked[order.symbol] = pf.locked.get(order.symbol, 0) + qty
        log.append(type="fill", side="buy", date=date, account_id=order.account_id,
                   symbol=order.symbol, qty=qty, price=round(price, 4),
                   commission=round(commission, 2), cash_after=round(pf.cash, 2))

    def _fill_sell(self, order, price, rules, pf, log, date):
        sellable = pf.sellable(order.symbol)
        if rules.allow_short:
            qty = (order.qty // rules.buy_step) * rules.buy_step
        else:
            qty = rules.align_sell_qty(order.qty, sellable)   # 可一次清仓(含零股)
        if qty <= 0:
            log.append(type="reject", reason="nothing_sellable", date=date,
                       account_id=order.account_id, symbol=order.symbol,
                       side="sell", qty=order.qty)
            return

        gross = qty * price
        commission = self._commission(gross, rules)
        stamp = gross * rules.stamp_duty_sell
        net = gross - commission - stamp

        pf.cash += net
        pf.positions[order.symbol] = pf.positions.get(order.symbol, 0) - qty
        if pf.positions[order.symbol] == 0:
            del pf.positions[order.symbol]
        log.append(type="fill", side="sell", date=date, account_id=order.account_id,
                   symbol=order.symbol, qty=qty, price=round(price, 4),
                   commission=round(commission, 2), stamp=round(stamp, 2),
                   cash_after=round(pf.cash, 2))
