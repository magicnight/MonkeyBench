"""综合质量评分(研究层)—— Piotroski F-Score / Altman Z / 截面工具 / 综合分。

设计:**纯计算**,输入**标准化字段**(不绑 tushare 列名);数据接入层负责把 tushare
财务字段映射成这里的标准名。单票分(F-Score/Z)直接算;截面分(Magic/QMJ)用截面工具组合。
先做**等权 baseline**(可解释、抗过拟合 —— 见动量被多时段揭穿的教训),权重学习留后。
"""
from __future__ import annotations

import math
from typing import Mapping, Optional, Sequence


# ---------------- 单票评分 ----------------

def piotroski_f_score(cur: Mapping, prev: Mapping) -> int:
    """Piotroski F-Score(0–9,越高越健康)。cur/prev:本期与上年同期标准字段。

    字段:roa, cfo(经营现金流), net_profit, lt_debt_ratio(长期负债/总资产),
          current_ratio, shares(总股本), gross_margin, asset_turn。
    """
    s = 0
    # 盈利性(4)
    s += cur["roa"] > 0
    s += cur["cfo"] > 0
    s += cur["roa"] > prev["roa"]
    s += cur["cfo"] > cur["net_profit"]              # 应计质量:现金流 > 净利润
    # 杠杆 / 流动性 / 融资(3)
    s += cur["lt_debt_ratio"] < prev["lt_debt_ratio"]
    s += cur["current_ratio"] > prev["current_ratio"]
    s += cur["shares"] <= prev["shares"]             # 未增发稀释
    # 运营效率(2)
    s += cur["gross_margin"] > prev["gross_margin"]
    s += cur["asset_turn"] > prev["asset_turn"]
    return int(s)


def altman_z_score(x: Mapping) -> float:
    """Altman Z-Score(原始制造业版;>2.99 安全,<1.81 危险)。

    字段:working_capital, retained_earnings, ebit, total_assets, market_cap, total_liab, sales。
    """
    ta = x["total_assets"]
    return (1.2 * x["working_capital"] / ta
            + 1.4 * x["retained_earnings"] / ta
            + 3.3 * x["ebit"] / ta
            + 0.6 * x["market_cap"] / x["total_liab"]
            + 1.0 * x["sales"] / ta)


# ---------------- 截面工具 ----------------

def _bad(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def cross_section_rank(values: Sequence[Optional[float]], ascending: bool = True) -> list:
    """截面百分位排名(0–1,大=好);缺失记 None。QMJ/Magic 用它对异常值稳健。"""
    idx = [(v, i) for i, v in enumerate(values) if not _bad(v)]
    idx.sort(reverse=not ascending)
    out: list = [None] * len(values)
    n = len(idx)
    for rank, (_, i) in enumerate(idx):
        out[i] = rank / (n - 1) if n > 1 else 0.5
    return out


def cross_section_zscore(values: Sequence[Optional[float]]) -> list:
    """截面 z-score;缺失记 None。"""
    xs = [v for v in values if not _bad(v)]
    if len(xs) < 2:
        return [None] * len(values)
    mu = sum(xs) / len(xs)
    sd = math.sqrt(sum((v - mu) ** 2 for v in xs) / (len(xs) - 1))
    if sd == 0:
        return [0.0 if not _bad(v) else None for v in values]
    return [((v - mu) / sd if not _bad(v) else None) for v in values]


def composite_score(rank_lists: Sequence[Sequence[Optional[float]]], weights=None) -> list:
    """把多个截面排名(0–1)加权综合成一个分(0–1)。默认等权;缺失项跳过、按现有权重归一。"""
    m = len(rank_lists)
    if m == 0:
        return []
    n = len(rank_lists[0])
    w = weights or [1.0 / m] * m
    out = []
    for j in range(n):
        pairs = [(rank_lists[k][j], w[k]) for k in range(m) if not _bad(rank_lists[k][j])]
        out.append(sum(v * wk for v, wk in pairs) / sum(wk for _, wk in pairs) if pairs else None)
    return out
