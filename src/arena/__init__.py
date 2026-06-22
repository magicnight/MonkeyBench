"""MonkeyBench 竞技场 —— 个人实验性的多账号策略竞技场。

研究层(Qlib/vectorbt,离线)产信号 → 本竞技场(唯一引擎)执行打分 → 排行榜。
排行榜上的官方数字永远只来自这一个引擎,以保证公平对比。
"""
from .arena import Account, Arena
from .datafeed import DataFeed, MarketData, SyntheticFeed
from .engine import MatchingEngine
from .eventlog import EventLog
from .leaderboard import compute, leaderboard, render, summarize
from .market import (
    A_SHARE, A_SHARE_CHINEXT, A_SHARE_ST, A_SHARE_STAR, HK, PRESETS, US,
    AShareRuleBook, Bar, MarketRules, Order, OrderSide, RuleBook, StaticRuleBook,
    a_share_board, a_share_rules, as_rulebook,
)
from .portfolio import Portfolio
from .strategy import Context, Strategy
from .strategies import (
    BuyAndHoldEqual,
    CrossSectionalMomentum,
    EqualWeightRebalance,
    RandomTrader,
)

__all__ = [
    "Account", "Arena", "MatchingEngine", "EventLog",
    "DataFeed", "MarketData", "SyntheticFeed",
    "MarketRules", "A_SHARE", "A_SHARE_CHINEXT", "A_SHARE_STAR", "A_SHARE_ST",
    "HK", "US", "PRESETS", "Bar", "Order", "OrderSide",
    "RuleBook", "StaticRuleBook", "AShareRuleBook",
    "a_share_board", "a_share_rules", "as_rulebook",
    "Portfolio", "Strategy", "Context",
    "RandomTrader", "BuyAndHoldEqual", "EqualWeightRebalance", "CrossSectionalMomentum",
    "compute", "leaderboard", "render", "summarize",
]
