"""具体策略:基准"猴子" + 一个真正的截面动量对手。

排行榜的灵魂是这群猴子:跑得最好那只随机交易者的夏普 = 你这个账号规模的
"运气天花板 / 噪声地板"。任何精心设计的策略,扣完成本干不过最好的猴子、
也干不过买入持有,就说明它没有真东西。这等于给排行榜内置了零假设检验。
"""
from __future__ import annotations

import random
from typing import List

from .market import Order, OrderSide
from .strategy import Context, Strategy


class RandomTrader(Strategy):
    """随机交易者。每根 bar 以一定概率随机买/卖。基准,不是给你抄的。"""

    def __init__(self, seed: int, trade_prob: float = 0.3,
                 min_alloc: float = 0.05, max_alloc: float = 0.25):
        self.seed = seed
        self.trade_prob = trade_prob
        self.min_alloc = min_alloc
        self.max_alloc = max_alloc
        self.name = f"🐒 monkey-{seed:02d}"
        self.reset()

    def reset(self):
        self.rng = random.Random(self.seed)

    def on_bar(self, ctx: Context) -> List[Order]:
        if self.rng.random() >= self.trade_prob:
            return []
        sym = self.rng.choice(ctx.universe)
        price = ctx.price(sym)
        if not price:
            return []

        if self.rng.random() < 0.5:  # 买
            budget = ctx.cash * self.rng.uniform(self.min_alloc, self.max_alloc)
            qty = ctx.size_buy(budget, price, sym)
            if qty > 0:
                return [Order(ctx.account_id, sym, OrderSide.BUY, qty)]
        else:                        # 卖
            held = ctx.sellable(sym)
            if held > 0:
                frac = self.rng.uniform(0.3, 1.0)
                step = ctx.rules_for(sym).buy_step
                qty = int((held * frac) // step) * step
                if qty > 0:
                    return [Order(ctx.account_id, sym, OrderSide.SELL, qty)]
        return []


class BuyAndHoldEqual(Strategy):
    """开局等权买入全市场,之后持有不动。最朴素也最难打败的基准之一。"""
    name = "📌 buy&hold-equal"

    def reset(self):
        self.deployed = False

    def on_bar(self, ctx: Context) -> List[Order]:
        if self.deployed:
            return []
        self.deployed = True
        syms = ctx.universe
        budget_each = ctx.cash / len(syms)
        orders = []
        for s in syms:
            p = ctx.price(s)
            if p:
                qty = ctx.size_buy(budget_each, p, s)
                if qty > 0:
                    orders.append(Order(ctx.account_id, s, OrderSide.BUY, qty))
        return orders


class EqualWeightRebalance(Strategy):
    """每 period 个交易日把组合拉回等权。基准。"""

    def __init__(self, period: int = 21):
        self.period = period
        self.name = f"⚖️ eqw-rebal({period})"
        self.reset()

    def reset(self):
        self.counter = 0

    def on_bar(self, ctx: Context) -> List[Order]:
        self.counter += 1
        if self.counter % self.period != 1:
            return []
        return _rebalance_to(ctx, ctx.universe)


class CrossSectionalMomentum(Strategy):
    """截面动量(真正的对手):按过去 lookback 日收益排名,持有 top_k 等权,每 period 调仓。

    这是给你看的"非猴子"样本 —— 跑完看它扣成本后能不能打过最好的猴子。
    """

    def __init__(self, lookback: int = 60, top_k: int = 3, period: int = 21):
        self.lookback = lookback
        self.top_k = top_k
        self.period = period
        self.name = f"📈 momentum(L{lookback},k{top_k})"
        self.reset()

    def reset(self):
        self.counter = 0

    def on_bar(self, ctx: Context) -> List[Order]:
        self.counter += 1
        if self.counter % self.period != 1:
            return []
        scored = []
        for s in ctx.universe:
            hist = ctx.history(s, self.lookback)
            if len(hist) < self.lookback:
                continue  # 跳过历史不足/未上市/停牌的票,而非放弃整轮(多票真实数据必需)
            ret = hist[-1] / hist[0] - 1.0
            scored.append((ret, s))
        if not scored:
            return []
        scored.sort(reverse=True)
        winners = [s for _, s in scored[: self.top_k]]
        return _rebalance_to(ctx, winners)


def _rebalance_to(ctx: Context, target_syms: List[str]) -> List[Order]:
    """把组合调成"在 target_syms 上等权"。先清掉不在目标里的,再买/卖到目标股数。"""
    orders: List[Order] = []
    target_set = set(target_syms)

    # 1) 清掉不在目标里的持仓
    for s in list(ctx._pf.positions.keys()):  # type: ignore[attr-defined]
        if s not in target_set:
            q = ctx.sellable(s)
            if q > 0:
                orders.append(Order(ctx.account_id, s, OrderSide.SELL, q))

    if not target_syms:
        return orders

    # 2) 目标股每只分配等权资金,买卖到目标股数
    equity = ctx.equity()
    budget_each = equity / len(target_syms)
    for s in target_syms:
        p = ctx.price(s)
        if not p:
            continue
        target_qty = ctx.size_buy(budget_each, p, s)
        cur = ctx.position(s)
        diff = target_qty - cur
        if diff > 0:
            orders.append(Order(ctx.account_id, s, OrderSide.BUY, diff))
        elif diff < 0:
            q = min(-diff, ctx.sellable(s))
            if q > 0:
                orders.append(Order(ctx.account_id, s, OrderSide.SELL, q))
    return orders
