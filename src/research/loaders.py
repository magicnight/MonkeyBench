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


def investment_trend(cache, ts_code: str, years: int = 5, date: str | None = None) -> dict:
    """扩张投入信号 —— 用资产负债表/现金流/利润表判断净利变化是'扩张投入(机遇)'还是
    '衰退/竞争(风险)':在建工程↑/固定资产↑/研发↑ = 投入,再用**毛利率**交叉验证
    (毛利稳=纯投入机遇;毛利同步降=投入叠加竞争,需读公告看投入质量)。PIT:ann_date<=date 已公告年报。

    返回 {verdict, note, fix_assets_growth, cip_to_fix, revenue_growth, rd_growth,
    gross_margin_change, latest:{...}, series:[...]}。"""
    di = int(date) if date else int(_latest_date_di(cache))
    have = {r[0] for r in cache.con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    if not {"balancesheet", "income", "fina_indicator"}.issubset(have):
        return {"ts_code": ts_code, "verdict": "数据不足"}
    rows = cache.con.execute("""
        WITH b AS (SELECT end_date, cip, fix_assets,
                     ROW_NUMBER() OVER (PARTITION BY end_date ORDER BY ann_date DESC) rn
                   FROM balancesheet WHERE ts_code=? AND end_date%10000=1231 AND ann_date<=?),
             i AS (SELECT end_date, total_revenue, rd_exp,
                     ROW_NUMBER() OVER (PARTITION BY end_date ORDER BY ann_date DESC) rn
                   FROM income WHERE ts_code=? AND end_date%10000=1231 AND ann_date<=?),
             f AS (SELECT end_date, grossprofit_margin,
                     ROW_NUMBER() OVER (PARTITION BY end_date ORDER BY ann_date DESC) rn
                   FROM fina_indicator WHERE ts_code=? AND end_date%10000=1231 AND ann_date<=?)
        SELECT b.end_date, b.cip, b.fix_assets, i.total_revenue, i.rd_exp, f.grossprofit_margin
        FROM b JOIN i ON b.end_date=i.end_date AND i.rn=1
               JOIN f ON b.end_date=f.end_date AND f.rn=1
        WHERE b.rn=1 ORDER BY b.end_date DESC LIMIT ?
    """, [ts_code, di, ts_code, di, ts_code, di, years]).fetchall()
    if len(rows) < 2:
        return {"ts_code": ts_code, "verdict": "数据不足"}
    cur, old = rows[0], rows[-1]

    def grow(a, b):
        return round(a / b - 1, 2) if (a and b and b != 0) else None

    cip_cur, fix_cur, gm_cur = cur[1] or 0, cur[2] or 0, cur[5]
    fix_growth = grow(cur[2], old[2])
    rev_growth = grow(cur[3], old[3])
    rd_growth = grow(cur[4], old[4])
    gm_change = round(cur[5] - old[5], 1) if (cur[5] is not None and old[5] is not None) else None
    cip_to_fix = round(cip_cur / fix_cur, 2) if fix_cur else 0.0
    expanding = (fix_growth is not None and fix_growth > 0.5) or cip_to_fix > 0.3

    if expanding and gm_change is not None and gm_change < -2:
        verdict, note = "扩张投入期 · 毛利承压", "在建/固定资产大增(扩产)但毛利率同步下滑——投入叠加竞争,机遇需看投入质量(建议读公告:厂建在哪、产能给谁)"
    elif expanding:
        verdict, note = "扩张投入期 · 毛利稳健", "在建/固定资产大增且毛利率稳——典型成长投入,净利下降多为折旧/费用前置"
    elif rev_growth is not None and rev_growth < -0.1:
        verdict, note = "收缩 / 衰退", "营收下滑且无明显扩张投入——警惕主业衰退"
    else:
        verdict, note = "平稳", "无显著扩张或收缩"

    return {"ts_code": ts_code, "verdict": verdict, "note": note,
            "fix_assets_growth": fix_growth, "cip_to_fix": cip_to_fix,
            "revenue_growth": rev_growth, "rd_growth": rd_growth, "gross_margin_change": gm_change,
            "latest": {"year": str(cur[0])[:4], "cip_yi": round(cip_cur / 1e8, 2),
                       "fix_yi": round(fix_cur / 1e8, 2), "gross_margin": gm_cur},
            "series": [{"year": str(r[0])[:4], "cip_yi": round((r[1] or 0) / 1e8, 2),
                        "fix_yi": round((r[2] or 0) / 1e8, 2), "gross_margin": r[5]}
                       for r in reversed(rows)]}


def _latest_date_di(cache) -> str:
    r = cache.con.execute("SELECT max(trade_date) FROM daily_bar").fetchone()[0]
    return r.strftime("%Y%m%d") if r else "20260623"
