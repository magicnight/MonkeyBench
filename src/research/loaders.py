"""数据接入层 —— 从本地 DuckDB 读财务/估值,算研究层信号。**不打 API**(数据已 backfill)。

PIT(无未来函数):财务用 `ann_date <= date` 的最新已公告报告 —— 即"截至该日,市场已知的
最新财报"。这一层也是 insight LLM 工具的数据来源(工具查本地,不舍近求远)。
"""
from __future__ import annotations

from .scores import composite_score, cross_section_rank

# 综合质量分用的 fina_indicator 现成指标:(字段, 越大越好?)
_QUALITY = [
    ("roe", True), ("roa", True), ("grossprofit_margin", True), ("netprofit_margin", True),
    ("current_ratio", True), ("debt_to_assets", False), ("assets_turn", True),
]


def quality_signals(cache, date: str) -> dict:
    """某 date 的综合质量分(0–1,越高越优)。PIT:每票取 ann_date<=date 的最新已公告财报,
    多指标截面百分位排名后等权综合。返回 {ts_code: score}。"""
    fields = ", ".join(f for f, _ in _QUALITY)
    sql = f"""
        WITH latest AS (
          SELECT ts_code, {fields},
                 ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY end_date DESC, ann_date DESC) AS rn
          FROM fina_indicator
          WHERE ann_date IS NOT NULL AND ann_date <= ?
        )
        SELECT ts_code, {fields} FROM latest WHERE rn = 1
    """
    df = cache.con.execute(sql, [date]).fetchdf()
    if len(df) == 0:
        return {}
    codes = df["ts_code"].tolist()
    ranks = [cross_section_rank(df[f].tolist(), ascending=good) for f, good in _QUALITY]
    comp = composite_score(ranks)
    return {c: s for c, s in zip(codes, comp) if s is not None}


# 改进版综合分用的质量指标:(字段, 越大越好)
_QUALITY_DIRS = [
    ("roe", True), ("roa", True), ("grossprofit_margin", True), ("netprofit_margin", True),
    ("current_ratio", True), ("debt_to_assets", False), ("assets_turn", True),
]


def composite_signals(cache, date: str, w_quality: float = 0.5, w_value: float = 0.3,
                      w_trend: float = 0.2, industry_neutral: bool = True) -> dict:
    """改进版综合分(0–1):质量 + 估值便宜(pe 惩罚)+ 盈利趋势(ROE 同比),可申万行业内中性化。

    解决纯 quality_signals 三缺陷:① 贵的好公司也高分 → 加 pe 估值分量(高 pe 扣分,德科立
    pe510 必被压低);② 盈利恶化没捕捉 → 加 ROE 年报同比;③ 跨行业不可比 → 申万 L1 行业内
    排名。PIT:财务 ann_date<=date 已公告、行业 in_date<=date<out_date、估值用当日 daily_basic。
    日期跨表类型不一(fina BIGINT / daily_basic VARCHAR / index_member BIGINT),分别传 int/str。"""
    import pandas as pd

    di = int(date)
    fields = ", ".join(f for f, _ in _QUALITY_DIRS)
    q = cache.con.execute(f"""
        WITH q AS (
          SELECT ts_code, end_date, {fields},
                 ROW_NUMBER() OVER (PARTITION BY ts_code ORDER BY end_date DESC, ann_date DESC) rn
          FROM fina_indicator
          WHERE ann_date IS NOT NULL AND ann_date <= ? AND end_date % 10000 = 1231)
        SELECT cur.ts_code, {', '.join('cur.' + f for f, _ in _QUALITY_DIRS)},
               cur.roe - prev.roe AS d_roe
        FROM q cur LEFT JOIN q prev ON cur.ts_code = prev.ts_code AND prev.rn = 2
        WHERE cur.rn = 1
    """, [di]).fetchdf()
    if len(q) == 0:
        return {}
    val = cache.con.execute(
        "SELECT ts_code, pe_ttm FROM daily_basic WHERE trade_date = ?", [date]).fetchdf()
    ind = cache.con.execute(
        "SELECT DISTINCT ts_code, l1_code FROM index_member "
        "WHERE in_date <= ? AND (out_date IS NULL OR out_date > ?)", [di, di]).fetchdf()

    df = q.merge(val, on="ts_code", how="left").merge(ind, on="ts_code", how="left")
    df["l1_code"] = df["l1_code"].fillna("NA")
    df["pe_pen"] = df["pe_ttm"].where(df["pe_ttm"] > 0, 1e9)   # 亏损/负 pe 当最贵

    grp = df.groupby("l1_code") if industry_neutral else None

    def rank(col, ascending):
        return (grp[col] if industry_neutral else df[col]).rank(pct=True, ascending=ascending)

    qr = pd.concat([rank(c, asc) for c, asc in _QUALITY_DIRS], axis=1).mean(axis=1)
    tr = rank("d_roe", True).fillna(0.5)            # 无上一年报 → 趋势中性
    vr = rank("pe_pen", False)                       # pe 越低分越高(便宜)
    comp = (w_quality * qr + w_trend * tr + w_value * vr) / (w_quality + w_trend + w_value)
    return {t: float(s) for t, s in zip(df["ts_code"], comp) if s == s}   # 去 NaN
