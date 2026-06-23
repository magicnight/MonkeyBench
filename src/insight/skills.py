"""公司分析领域工具 —— 查本地 DuckDB,产出**结构化数据**给 LLM 解读(非 NL2SQL)。

铁律落地:数字全部来自这些确定性工具,LLM 不碰 SQL、不自己算。数据来自 backfill 落盘
的本地库,**不打 API**(数据都在本地了,不舍近求远)。PIT:财务用 ann_date 已知日,防前视。

每个工具 (cache, ...) → dict;`register_company_tools(registry, cache)` 闭包绑定 cache
后注册到 ToolRegistry,LLM agent 即可调用。财务表 end_date/ann_date 是 BIGINT;同
(ts_code,end_date) 有多版本行,一律 ROW_NUMBER 去重。
"""
from __future__ import annotations

from research.loaders import investment_trend, quality_signals


def _latest_date(cache) -> str:
    """库里最新交易日 'YYYYMMDD'(质量分/对标的默认时点)。"""
    r = cache.con.execute("SELECT max(trade_date) FROM daily_bar").fetchone()[0]
    return r.strftime("%Y%m%d") if r else "20260623"


def company_profile(cache, ts_code: str) -> dict:
    """公司概况:名称/板块/上市退市状态 + 最新估值快照(pe/pb/股息/市值)。"""
    b = cache.con.execute(
        "SELECT name,market,list_date,delist_date,list_status FROM stock_basic WHERE ts_code=?",
        [ts_code]).fetchone()
    if not b:
        return {"ts_code": ts_code, "error": "未找到该股票"}
    v = cache.con.execute(
        "SELECT trade_date,close,pe_ttm,pb,ps_ttm,dv_ttm,total_mv "
        "FROM daily_basic WHERE ts_code=? ORDER BY trade_date DESC LIMIT 1", [ts_code]).fetchone()
    return {
        "ts_code": ts_code, "name": b[0], "market": b[1],
        "list_date": b[2], "delist_date": b[3], "list_status": b[4],
        "latest": None if not v else {
            "date": str(v[0]), "close": v[1], "pe_ttm": v[2], "pb": v[3],
            "ps_ttm": v[4], "dv_ttm": v[5],
            "total_mv_yi": round(v[6] / 1e4, 1) if v[6] else None},
    }


def financial_history(cache, ts_code: str, years: int = 5) -> dict:
    """年报财务历史:营收/净利(亿)+ ROE/毛利率/净利率/资产负债率。PIT 去重(取每期最新版本)。"""
    rows = cache.con.execute(
        """WITH f AS (
             SELECT end_date, roe, grossprofit_margin, netprofit_margin, debt_to_assets,
                    ROW_NUMBER() OVER (PARTITION BY end_date ORDER BY ann_date DESC) rn
             FROM fina_indicator WHERE ts_code=? AND end_date%10000=1231),
           i AS (
             SELECT end_date, total_revenue, n_income,
                    ROW_NUMBER() OVER (PARTITION BY end_date ORDER BY ann_date DESC) rn
             FROM income WHERE ts_code=? AND end_date%10000=1231)
         SELECT f.end_date, i.total_revenue, i.n_income, f.roe,
                f.grossprofit_margin, f.netprofit_margin, f.debt_to_assets
         FROM f LEFT JOIN i ON f.end_date=i.end_date AND i.rn=1
         WHERE f.rn=1 ORDER BY f.end_date DESC LIMIT ?""",
        [ts_code, ts_code, years]).fetchall()
    return {"ts_code": ts_code, "annual": [
        {"year": str(r[0])[:4],
         "revenue_yi": round(r[1] / 1e8, 2) if r[1] else None,
         "net_profit_yi": round(r[2] / 1e8, 2) if r[2] else None,
         "roe": r[3], "gross_margin": r[4], "net_margin": r[5], "debt_ratio": r[6]}
        for r in rows]}


def price_performance(cache, ts_code: str) -> dict:
    """复权价表现:上市来 + 近1年(约 250 交易日)涨跌幅。"""
    r = cache.con.execute(
        """WITH p AS (
             SELECT close*adj_factor AS adj,
                    ROW_NUMBER() OVER (ORDER BY trade_date DESC) rd,
                    ROW_NUMBER() OVER (ORDER BY trade_date) ra
             FROM daily_bar WHERE ts_code=? AND close IS NOT NULL AND adj_factor IS NOT NULL)
           SELECT max(CASE WHEN rd=1 THEN adj END) AS latest,
                  max(CASE WHEN ra=1 THEN adj END) AS first,
                  max(CASE WHEN rd=250 THEN adj END) AS yr_ago FROM p""",
        [ts_code]).fetchone()
    latest, first, yr = r if r else (None, None, None)
    return {
        "ts_code": ts_code,
        "since_listing": round(latest / first - 1, 3) if latest and first else None,
        "past_year": round(latest / yr - 1, 3) if latest and yr else None,
    }


def quality_score(cache, ts_code: str, date: str | None = None) -> dict:
    """综合质量分(0–1)+ 全市场百分位。PIT:用 date(默认最新交易日)时点的已公告财报。"""
    date = date or _latest_date(cache)
    sig = quality_signals(cache, date)
    s = sig.get(ts_code)
    if s is None:
        return {"ts_code": ts_code, "date": date, "quality_score": None,
                "note": "该日无已公告财报或不在样本"}
    vals = list(sig.values())
    pct = round(100 * sum(1 for v in vals if v < s) / len(vals), 1)
    return {"ts_code": ts_code, "date": date, "quality_score": round(s, 3),
            "percentile": pct, "universe": len(sig)}


def peer_comparison(cache, ts_codes: list, date: str | None = None) -> dict:
    """自定义对标:把多只股票的质量分 + 估值(pe/pb)+ 最新 ROE/净利率并排,供横评。"""
    date = date or _latest_date(cache)
    sig = quality_signals(cache, date)
    peers = []
    for code in ts_codes:
        prof = company_profile(cache, code)
        fin = financial_history(cache, code, years=1)
        latest = prof.get("latest") or {}
        a = fin["annual"][0] if fin.get("annual") else {}
        s = sig.get(code)
        peers.append({
            "ts_code": code, "name": prof.get("name"),
            "quality_score": round(s, 3) if s is not None else None,
            "pe_ttm": latest.get("pe_ttm"), "pb": latest.get("pb"),
            "latest_roe": a.get("roe"), "net_margin": a.get("net_margin")})
    return {"date": date, "peers": peers}


# --- 工具 schema(OpenAI function-calling)+ 注册 ---

_CODE = {"type": "string", "description": "Tushare 代码,如 688205.SH"}


def register_company_tools(registry, cache) -> None:
    """把公司分析工具注册到 registry(闭包绑定本地 cache)。"""
    registry.register(
        "company_profile", "公司概况:名称/板块/上市退市状态 + 最新估值快照(pe/pb/股息/市值)",
        {"type": "object", "properties": {"ts_code": _CODE}, "required": ["ts_code"]},
    )(lambda ts_code: company_profile(cache, ts_code))

    registry.register(
        "financial_history", "年报财务历史:营收/净利(亿)+ ROE/毛利率/净利率/资产负债率(PIT 去重)",
        {"type": "object", "properties": {
            "ts_code": _CODE,
            "years": {"type": "integer", "description": "取近几年年报,默认 5"}},
         "required": ["ts_code"]},
    )(lambda ts_code, years=5: financial_history(cache, ts_code, years))

    registry.register(
        "price_performance", "复权价表现:上市以来 + 近1年涨跌幅",
        {"type": "object", "properties": {"ts_code": _CODE}, "required": ["ts_code"]},
    )(lambda ts_code: price_performance(cache, ts_code))

    registry.register(
        "quality_score", "综合质量分(0–1)+ 全市场百分位(PIT,默认最新交易日)",
        {"type": "object", "properties": {
            "ts_code": _CODE,
            "date": {"type": "string", "description": "时点 YYYYMMDD,默认最新"}},
         "required": ["ts_code"]},
    )(lambda ts_code, date=None: quality_score(cache, ts_code, date))

    registry.register(
        "peer_comparison", "自定义对标:多只股票的质量分 + 估值 + ROE/净利率并排横评",
        {"type": "object", "properties": {
            "ts_codes": {"type": "array", "items": {"type": "string"},
                         "description": "对标股票代码列表"},
            "date": {"type": "string", "description": "时点 YYYYMMDD,默认最新"}},
         "required": ["ts_codes"]},
    )(lambda ts_codes, date=None: peer_comparison(cache, ts_codes, date))

    registry.register(
        "investment_trend", "扩张投入信号:在建工程/固定资产/研发趋势 + 毛利率交叉验证,判断净利变化是"
        "'扩张投入(机遇)'还是'衰退/竞争(风险)'。识别海外建厂/扩产能导致的投入型利润下降。",
        {"type": "object", "properties": {
            "ts_code": _CODE,
            "date": {"type": "string", "description": "时点 YYYYMMDD,默认最新"}},
         "required": ["ts_code"]},
    )(lambda ts_code, date=None: investment_trend(cache, ts_code, date=date))
