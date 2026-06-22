"""数据源抽象。

关键设计:同一个 MarketData 接口,接"合成数据/历史重放"就是回测,接"每日拉盘"
就是纸面实盘 —— 策略和引擎都感知不到区别。

SyntheticFeed 用一个公共市场因子 + 个股噪声生成相关的几何布朗运动价格,
纯标准库、零依赖、不需要任何 API key,开箱即跑。

真实数据源(akshare A股 / yfinance 美股 / akshare 港股)实现同一个 build() 即可,
见底部 stub。
"""
from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .market import Bar


@dataclass
class MarketData:
    """所有 bar 按 [symbol][date_index] 对齐存放。"""
    symbols: List[str]
    dates: List[str]
    bars: Dict[str, List[Optional[Bar]]] = field(default_factory=dict)

    def bar(self, symbol: str, index: int) -> Optional[Bar]:
        seq = self.bars.get(symbol)
        if seq is None or index < 0 or index >= len(seq):
            return None
        return seq[index]

    def opens(self, index: int) -> Dict[str, float]:
        out = {}
        for s in self.symbols:
            b = self.bar(s, index)
            if b:
                out[s] = b.open
        return out

    def closes(self, index: int) -> Dict[str, float]:
        out = {}
        for s in self.symbols:
            b = self.bar(s, index)
            if b:
                out[s] = b.close
        return out


class DataFeed(ABC):
    @abstractmethod
    def build(self) -> MarketData:
        ...


class SyntheticFeed(DataFeed):
    """合成行情:公共因子 + 个股 idio,产生相关的 GBM 路径。"""

    def __init__(self, n_symbols: int = 8, n_days: int = 504, seed: int = 7,
                 mu_annual: float = 0.06, sigma_annual: float = 0.30,
                 market_beta: float = 0.6, start_price: float = 100.0):
        self.n_symbols = n_symbols
        self.n_days = n_days
        self.seed = seed
        self.mu = mu_annual / 252.0
        self.sigma = sigma_annual / math.sqrt(252.0)
        self.beta = market_beta
        self.start_price = start_price

    def build(self) -> MarketData:
        rng = random.Random(self.seed)
        symbols = [f"SYM{i:03d}" for i in range(self.n_symbols)]
        dates = [f"D{d:04d}" for d in range(self.n_days)]
        bars: Dict[str, List[Optional[Bar]]] = {s: [] for s in symbols}

        prev_close = {s: self.start_price * rng.uniform(0.8, 1.2) for s in symbols}

        for d in range(self.n_days):
            market_shock = rng.gauss(0, self.sigma)  # 当日公共因子
            for s in symbols:
                idio = rng.gauss(0, self.sigma)
                ret = self.mu + self.beta * market_shock + math.sqrt(1 - self.beta**2) * idio
                pc = prev_close[s]
                close = pc * math.exp(ret)
                gap = rng.gauss(0, self.sigma * 0.4)
                open_ = pc * math.exp(gap)
                hi = max(open_, close) * (1 + abs(rng.gauss(0, self.sigma * 0.3)))
                lo = min(open_, close) * (1 - abs(rng.gauss(0, self.sigma * 0.3)))
                vol = rng.uniform(1e6, 5e6)
                bars[s].append(Bar(dates[d], s, round(open_, 3), round(hi, 3),
                                   round(lo, 3), round(close, 3), vol, round(pc, 3)))
                prev_close[s] = close

        return MarketData(symbols=symbols, dates=dates, bars=bars)


# --- 真实数据源 stub(实现同一个 build() 即可无缝替换)---------------------------
#
# class AkShareAFeed(DataFeed):
#     """A股:用 akshare 拉前复权日线。注意必做:前/后复权、含已退市票、停牌处理。"""
#     def __init__(self, symbols, start, end): ...
#     def build(self) -> MarketData:
#         import akshare as ak
#         # ak.stock_zh_a_hist(symbol=..., adjust="qfq", ...) -> 组装成 Bar
#         ...
#
# class YFinanceFeed(DataFeed):
#     """美股:yfinance。"""
#     def build(self) -> MarketData:
#         import yfinance as yf
#         ...
#
# class DailyPullFeed(DataFeed):
#     """纸面实盘:每天定时拉当日行情,落库后 build 出"截至今天"的 MarketData。
#        配 APScheduler 跑日循环。策略代码完全不用改。"""
#     ...
