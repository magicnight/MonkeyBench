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
