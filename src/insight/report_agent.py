"""DD 式公司分析报告 agent —— LLM 编排 insight 工具收集本地数据,撰写结构化长报告。

铁律:LLM 只调确定性工具拿数字、只负责解读与行文,**绝不自己算/编数**。
配 LLM key 后 `company_dd_report(...)` 端到端产出报告;无 key 时用 MockLLM 验证编排逻辑。

注:真 LLM 接入时需校验 agent.py 里 assistant.tool_calls 回传 messages 的格式是否符合
目标 endpoint(OpenAI 要求 {id,type,function:{name,arguments}} 嵌套)—— 见 [[insight-agent-notes]]。
"""
from __future__ import annotations

from data.codes import to_ts_code
from research.loaders import investment_trend
from research.report import assemble_report, grouped_bar_svg, line_svg, radar_svg

from .agent import Agent, LLM
from .report_spec import DD_SYSTEM, DISCLAIMER
from .skills import (company_profile, financial_history, peer_comparison,
                     price_performance, quality_score, register_company_tools)
from .tools import ToolRegistry


def build_dd_agent(cache, llm: LLM) -> Agent:
    """组装 DD 报告 agent:注册本地数据工具 + DD system prompt。"""
    reg = ToolRegistry()
    register_company_tools(reg, cache)
    return Agent(reg, llm, system=DD_SYSTEM)


def company_dd_report(cache, llm: LLM, ts_code: str, peers: list | None = None,
                      max_turns: int = 8) -> str:
    """对 ts_code 产出 DD 长报告;peers 给定则做自定义对标。返回 Markdown 文本。"""
    ts_code = to_ts_code(ts_code)
    peers = [to_ts_code(p) for p in peers] if peers else peers
    agent = build_dd_agent(cache, llm)
    msg = f"请对 {ts_code} 撰写一份 DD 分析报告。"
    if peers:
        msg += f"并与以下标的对标:{', '.join(peers)}。"
    body = agent.run(msg, max_turns=max_turns)
    body = _apply_charts(body, build_charts(cache, ts_code, peers))   # 占位符嵌图,LLM 漏放则补末尾
    return body + "\n\n" + DISCLAIMER


# --- 降级:无 LLM key 时,工具数据 + 确定性模板 → 结构化报告(含雷达图)---

def _pct(x):
    return f"{round(x * 100, 1)}%" if x is not None else "—"


def _clamp01(x):
    return max(0.0, min(1.0, x))


def _valuation_chart(cache, ts_code: str) -> str:
    """pe_ttm 年末估值历史折线(daily_basic;trade_date 是 VARCHAR,按年取最后一条)。"""
    rows = cache.con.execute(
        "WITH v AS (SELECT substr(trade_date,1,4) yr, pe_ttm, "
        "ROW_NUMBER() OVER (PARTITION BY substr(trade_date,1,4) ORDER BY trade_date DESC) rn "
        "FROM daily_basic WHERE ts_code=? AND pe_ttm IS NOT NULL AND pe_ttm>0) "
        "SELECT yr, pe_ttm FROM v WHERE rn=1 ORDER BY yr", [to_ts_code(ts_code)]).fetchall()
    if len(rows) < 3:
        return ""
    return ('<div class="chart">' + line_svg({"pe_ttm(年末)": [r[1] for r in rows]},
            [r[0] for r in rows], title="pe_ttm 估值历史") + '</div>')


def _divergence_chart(cache, ts_code: str) -> str:
    """股价 vs 基本面背离:年度复权股价 与 净利,各按首年=100 指数化双线(背离一眼可见)。"""
    ts = to_ts_code(ts_code)
    px = cache.con.execute(
        "WITH p AS (SELECT strftime(trade_date,'%Y') yr, close*adj_factor adj, "
        "ROW_NUMBER() OVER (PARTITION BY strftime(trade_date,'%Y') ORDER BY trade_date DESC) rn "
        "FROM daily_bar WHERE ts_code=? AND adj_factor IS NOT NULL AND close IS NOT NULL) "
        "SELECT yr, adj FROM p WHERE rn=1 ORDER BY yr", [ts]).fetchall()
    ni = dict(cache.con.execute(
        "SELECT substr(CAST(end_date AS VARCHAR),1,4), n_income FROM income "
        "WHERE ts_code=? AND end_date%10000=1231 AND n_income IS NOT NULL", [ts]).fetchall())
    px_d = dict(px)
    yrs = [y for y, _ in px if y in ni and ni[y] and px_d[y]]
    if len(yrs) < 3:
        return ""
    p0, n0 = px_d[yrs[0]], ni[yrs[0]]
    if p0 <= 0 or n0 <= 0:
        return ""
    return ('<div class="chart">' + line_svg(
        {"股价(复权,首年=100)": [round(px_d[y] / p0 * 100, 1) for y in yrs],
         "净利(首年=100)": [round(ni[y] / n0 * 100, 1) for y in yrs]},
        yrs, title="股价 vs 净利(背离)") + '</div>')


def build_charts(cache, ts_code: str, peers: list | None = None, date: str | None = None) -> dict:
    """所有图表 → {key: '<div class=chart>svg</div>'}。key:radar/financials/investment/peers。
    LLM 版按 [[CHART:key]] 占位符嵌入对应章节,降级版按节直接取用。"""
    ts_code = to_ts_code(ts_code)
    peers = [to_ts_code(p) for p in peers] if peers else peers
    prof = company_profile(cache, ts_code)
    fin = financial_history(cache, ts_code)
    q = quality_score(cache, ts_code, date)
    annual = fin.get("annual") or []
    cur = annual[0] if annual else {}
    name = prof.get("name") or ts_code
    ch: dict = {}
    if cur:
        dims = {"ROE": _clamp01((cur.get("roe") or 0) / 30),
                "净利率": _clamp01((cur.get("net_margin") or 0) / 50),
                "毛利率": _clamp01((cur.get("gross_margin") or 0) / 100),
                "低杠杆": _clamp01((100 - (cur.get("debt_ratio") or 0)) / 100),
                "综合质量": q.get("quality_score") or 0.0}
        ch["radar"] = f'<div class="chart">{radar_svg(dims, title=f"{name} 财务画像")}</div>'
    if annual:
        yrs = [a["year"] for a in reversed(annual)]
        ch["financials"] = '<div class="chart">' + line_svg(
            {"营收(亿)": [a.get("revenue_yi") for a in reversed(annual)],
             "净利(亿)": [a.get("net_profit_yi") for a in reversed(annual)]},
            yrs, title="营收 vs 净利趋势") + '</div>'
    inv = investment_trend(cache, ts_code, date=date)
    sec = inv.get("series", [])
    if sec:
        ch["investment"] = '<div class="chart">' + line_svg(
            {"在建工程(亿)": [s.get("cip_yi") for s in sec],
             "固定资产(亿)": [s.get("fix_yi") for s in sec]},
            [s.get("year") for s in sec], title="扩张投入趋势") + '</div>'
    if peers:
        pc = peer_comparison(cache, [ts_code] + list(peers), date)
        names = [p.get("name") or p["ts_code"] for p in pc["peers"]]
        ch["peers"] = '<div class="chart">' + grouped_bar_svg(
            {"ROE": [p.get("latest_roe") for p in pc["peers"]],
             "净利率": [p.get("net_margin") for p in pc["peers"]]},
            names, title="对标:ROE vs 净利率(%)") + '</div>'
    if (v := _valuation_chart(cache, ts_code)):
        ch["valuation"] = v
    if (d := _divergence_chart(cache, ts_code)):
        ch["divergence"] = d
    return ch


def _apply_charts(text: str, charts: dict) -> str:
    """把 LLM 报告里的 [[CHART:key]] 占位符替换成对应图表;LLM 漏放的图补到文末(兜底)。"""
    import re
    used = set()

    def repl(m):
        used.add(m.group(1))
        return charts.get(m.group(1), "")

    text = re.sub(r"\[\[CHART:(\w+)\]\]", repl, text)
    leftover = [v for k, v in charts.items() if k not in used]
    if leftover:
        text += "\n\n## 补充图表\n\n" + "\n\n".join(leftover)
    return text


def dd_report_from_data(cache, ts_code: str, peers: list | None = None,
                        date: str | None = None) -> str:
    """无 LLM 的降级 DD 报告:本地工具数据 + 确定性模板 → Markdown(含财务画像雷达图)。

    数字全来自工具、纯模板排版(不做分析性行文)。配 key 后用 company_dd_report 出分析长报告。"""
    ts_code = to_ts_code(ts_code)
    peers = [to_ts_code(p) for p in peers] if peers else peers
    prof = company_profile(cache, ts_code)
    if prof.get("error"):
        return f"# {ts_code}\n\n未找到该股票。"
    fin = financial_history(cache, ts_code)
    price = price_performance(cache, ts_code)
    q = quality_score(cache, ts_code, date)
    name = prof.get("name") or ts_code
    latest = prof.get("latest") or {}
    annual = fin.get("annual") or []
    cur = annual[0] if annual else {}

    dims = {}
    if cur:
        dims = {
            "ROE": _clamp01((cur.get("roe") or 0) / 30),
            "净利率": _clamp01((cur.get("net_margin") or 0) / 50),
            "毛利率": _clamp01((cur.get("gross_margin") or 0) / 100),
            "低杠杆": _clamp01((100 - (cur.get("debt_ratio") or 0)) / 100),
            "综合质量": q.get("quality_score") or 0.0,
        }
    radar = radar_svg(dims, title=f"{name} 财务画像") if dims else None

    qs = q.get("quality_score")
    scores = {
        "综合质量分": f"{qs}（{q.get('percentile')} 分位）" if qs is not None else "—",
        "pe_ttm": latest.get("pe_ttm") if latest.get("pe_ttm") is not None else "—",
        "pb": latest.get("pb") if latest.get("pb") is not None else "—",
        "近1年涨跌": _pct(price.get("past_year")),
        "总市值(亿)": latest.get("total_mv_yi") if latest.get("total_mv_yi") is not None else "—",
    }

    rev = " → ".join(f"{a['year']} {a.get('revenue_yi')}亿" for a in reversed(annual)) if annual else "数据缺失"
    ni = " → ".join(f"{a['year']} {a.get('net_profit_yi')}亿" for a in reversed(annual)) if annual else "数据缺失"
    sections = {
        "公司概况": f"{name},{prof.get('market')},上市日 {prof.get('list_date')},状态 {prof.get('list_status')}。",
        "财务历史": f"营收:{rev}\n\n净利:{ni}\n\n最新年报 ROE {cur.get('roe')}%、毛利率 {cur.get('gross_margin')}%、"
                    f"净利率 {cur.get('net_margin')}%、资产负债率 {cur.get('debt_ratio')}%。",
        "估值与股价": f"最新 pe_ttm {latest.get('pe_ttm')}、pb {latest.get('pb')};"
                      f"复权涨跌:上市来 {_pct(price.get('since_listing'))}、近1年 {_pct(price.get('past_year'))}。",
    }
    sections["估值与股价"] += _valuation_chart(cache, ts_code) + _divergence_chart(cache, ts_code)
    if annual:
        yrs2 = [a["year"] for a in reversed(annual)]
        fin_chart = line_svg(
            {"营收(亿)": [a.get("revenue_yi") for a in reversed(annual)],
             "净利(亿)": [a.get("net_profit_yi") for a in reversed(annual)]},
            yrs2, title="营收 vs 净利趋势")
        sections["财务历史"] += f'\n\n<div class="chart">{fin_chart}</div>'
    inv = investment_trend(cache, ts_code, date=date)
    if inv.get("verdict") not in (None, "数据不足"):
        lt = inv.get("latest", {})
        sec = inv.get("series", [])
        inv_svg = line_svg(
            {"在建工程(亿)": [s.get("cip_yi") for s in sec],
             "固定资产(亿)": [s.get("fix_yi") for s in sec]},
            [s.get("year") for s in sec], title="扩张投入趋势") if sec else ""
        inv_chart = f'<div class="chart">{inv_svg}</div>' if inv_svg else ""
        sections["扩张 / 投入信号"] = (
            f"**{inv['verdict']}** — {inv.get('note')}\n\n"
            f"最新在建工程 {lt.get('cip_yi')} 亿、固定资产 {lt.get('fix_yi')} 亿;"
            f"固定资产增速 {inv.get('fix_assets_growth')}、营收增速 {inv.get('revenue_growth')}、"
            f"研发增速 {inv.get('rd_growth')}、毛利率变化 {inv.get('gross_margin_change')} pct。\n\n{inv_chart}")
    if peers:
        pc = peer_comparison(cache, [ts_code] + list(peers), date)
        rows = ["| 代码 | 名称 | 质量分 | pe_ttm | pb | ROE | 净利率 |", "|---|---|---|---|---|---|---|"]
        for p in pc["peers"]:
            rows.append(f"| {p['ts_code']} | {p.get('name')} | {p.get('quality_score')} | "
                        f"{p.get('pe_ttm')} | {p.get('pb')} | {p.get('latest_roe')} | {p.get('net_margin')} |")
        names = [p.get("name") or p["ts_code"] for p in pc["peers"]]
        bar = grouped_bar_svg(
            {"ROE": [p.get("latest_roe") for p in pc["peers"]],
             "净利率": [p.get("net_margin") for p in pc["peers"]]},
            names, title="对标:ROE vs 净利率(%)")
        sections["同业对标"] = "\n".join(rows) + f'\n\n<div class="chart">{bar}</div>'

    note = ("\n\n*(确定性模板版:数字均来自本地数据工具;配 LLM key 走 agent 分析长报告。)*\n\n"
            + DISCLAIMER)
    return assemble_report(ts_code, name, scores, sections, q.get("date") or "", radar) + note
