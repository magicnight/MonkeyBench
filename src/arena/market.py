"""市场规则、订单、K线 + A股板块规则解析。

设计要点:一个共享引擎,靠不同的 MarketRules 区分市场/板块,而不是写多套引擎。
A 股不同板块(主板/创业/科创/ST)的涨跌停与最小买入不同 → 用 `a_share_rules()` 按
代码前缀/名称解析;`RuleBook` 把"按 symbol 取规则"收敛到引擎边界,引擎核心保持不变。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from enum import Enum
from typing import Dict, Optional


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class Order:
    """策略只产出 Order,完全不碰撮合。市价单,按"下一根 bar 的开盘"成交。"""
    account_id: str
    symbol: str
    side: OrderSide
    qty: int  # 股数,引擎会按板块 lot 规则再对齐


@dataclass(frozen=True)
class Bar:
    date: str
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    prev_close: float  # 上一根的收盘,用于算涨跌停


@dataclass(frozen=True)
class MarketRules:
    """一个市场/板块的交易规则与成本。

    lot 语义:买入 = `min_lot` 起、`lot_step` 递增(主板 100/100;科创板 200/1)。
    未显式给 min_lot/lot_step 时回退到 lot_size。
    """
    name: str
    lot_size: int = 1
    min_lot: Optional[int] = None             # 买入最小股数;None → lot_size
    lot_step: Optional[int] = None            # 买入步长;None → lot_size
    price_limit_pct: Optional[float] = None   # 涨跌停幅度,None = 无限制
    lock_same_day_buy: bool = False           # A股 T+1 为 True
    commission_rate: float = 0.0003           # 佣金费率(双边)
    min_commission: float = 5.0               # 最低佣金
    stamp_duty_sell: float = 0.0              # 印花税(仅卖出)
    slippage_bps: float = 5.0                 # 滑点,基点
    allow_short: bool = False

    @property
    def buy_min(self) -> int:
        return self.min_lot if self.min_lot is not None else self.lot_size

    @property
    def buy_step(self) -> int:
        return self.lot_step if self.lot_step is not None else self.lot_size

    def align_buy_qty(self, qty: int) -> int:
        """买入对齐:不足最小手 → 0;否则 最小手 + 步长整数倍。"""
        lo, step = self.buy_min, self.buy_step
        if qty < lo:
            return 0
        return lo + ((qty - lo) // step) * step

    def align_sell_qty(self, qty: int, holding: int) -> int:
        """卖出对齐:可一次清仓(含零股);部分卖按步长向下取整。"""
        qty = min(qty, holding)
        if qty <= 0:
            return 0
        if qty >= holding:           # 清仓:零股允许一次卖出
            return holding
        return (qty // self.buy_step) * self.buy_step


# --- A 股板块预设(成本相同,差异在涨跌停与 lot)---------------------------------
# 注意:费率/涨跌停随监管变动,落地以交易所/中证登当前规则为准,不要照抄。

A_SHARE = MarketRules(                # 主板(沪 60 / 深 000,001,002,003)
    name="A股-主板",
    lot_size=100,
    price_limit_pct=0.10,            # ±10%
    lock_same_day_buy=True,          # T+1
    commission_rate=0.00025,
    min_commission=5.0,
    stamp_duty_sell=0.0005,          # 卖出 0.05%
    slippage_bps=5.0,
    allow_short=False,
)
A_SHARE_CHINEXT = replace(A_SHARE, name="A股-创业板", price_limit_pct=0.20)   # 300/301 ±20%
A_SHARE_STAR = replace(A_SHARE, name="A股-科创板", price_limit_pct=0.20,      # 688 ±20%
                       min_lot=200, lot_step=1)                               # ≥200 起,+1 递增
A_SHARE_ST = replace(A_SHARE, name="A股-ST(主板)", price_limit_pct=0.05)      # 主板风险警示 ±5%

HK = MarketRules(
    name="港股", lot_size=100, price_limit_pct=None, lock_same_day_buy=False,
    commission_rate=0.0005, min_commission=3.0, stamp_duty_sell=0.001,
    slippage_bps=8.0, allow_short=True,
)
US = MarketRules(
    name="美股", lot_size=1, price_limit_pct=None, lock_same_day_buy=False,
    commission_rate=0.0, min_commission=0.0, stamp_duty_sell=0.0,
    slippage_bps=3.0, allow_short=True,
)

PRESETS = {"A": A_SHARE, "A_CHINEXT": A_SHARE_CHINEXT, "A_STAR": A_SHARE_STAR,
           "A_ST": A_SHARE_ST, "HK": HK, "US": US}


# --- A 股板块解析:按代码前缀 + 名称判定 ----------------------------------------

def a_share_board(symbol: str, name: str = "") -> str:
    """按代码前缀/名称返回板块标签:star / chinext / st / main。

    注意:科创板(688)、创业板(300/301)即便是 ST,涨跌停仍 ±20%(注册制),
    只有**主板** ST/*ST 才降到 ±5%。
    """
    code = symbol.split(".")[0]
    if code.startswith("688"):
        return "star"
    if code.startswith(("300", "301")):
        return "chinext"
    if "ST" in name.upper().replace("*", ""):
        return "st"
    return "main"


_BOARD_RULES = {"star": A_SHARE_STAR, "chinext": A_SHARE_CHINEXT,
                "st": A_SHARE_ST, "main": A_SHARE}


def a_share_rules(symbol: str, name: str = "") -> MarketRules:
    """A 股:按 symbol(+ 可选 name)解析该股票的交易规则。"""
    return _BOARD_RULES[a_share_board(symbol, name)]


class RuleBook(ABC):
    """按 symbol 取交易规则。引擎/Arena 通过它拿到 per-symbol 规则。"""

    @abstractmethod
    def for_symbol(self, symbol: str) -> MarketRules: ...


class StaticRuleBook(RuleBook):
    """所有 symbol 同一套规则(港股/美股/合成数据)。"""

    def __init__(self, rules: MarketRules):
        self.rules = rules

    def for_symbol(self, symbol: str) -> MarketRules:
        return self.rules


class AShareRuleBook(RuleBook):
    """A 股:按代码前缀/名称 per-symbol 解析(主板/创业/科创/ST)。

    names: 可选 symbol→名称映射,用于判定 ST;缺失则按非 ST 处理。
    """

    def __init__(self, names: Optional[Dict[str, str]] = None):
        self.names = names or {}

    def for_symbol(self, symbol: str) -> MarketRules:
        return a_share_rules(symbol, self.names.get(symbol, ""))


def as_rulebook(rules) -> RuleBook:
    """把 MarketRules 或 RuleBook 规范成 RuleBook。"""
    return rules if isinstance(rules, RuleBook) else StaticRuleBook(rules)
