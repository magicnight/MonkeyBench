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
    charts = _charts_md(cache, ts_code, peers)        # LLM 只产文字,图表由代码确定性补上
    return body + (f"\n\n{charts}" if charts else "") + "\n\n" + DISCLAIMER


# --- 降级:无 LLM key 时,工具数据 + 确定性模板 → 结构化报告(含雷达图)---

def _pct(x):
    return f"{round(x * 100, 1)}%" if x is not None else "—"


def _clamp01(x):
    return max(0.0, min(1.0, x))


def _charts_md(cache, ts_code: str, peers: list | None = None, date: str | None = None) -> str:
    """确定性图表区(雷达/财务/投入/对标),markdown(各图 <div class=chart> 包裹)。
    LLM 版报告靠它补图表 —— LLM 只产文字,图表由代码确定性生成,保证每份都有。"""
    prof = company_profile(cache, ts_code)
    fin = financial_history(cache, ts_code)
    q = quality_score(cache, ts_code, date)
    annual = fin.get("annual") or []
    cur = annual[0] if annual else {}
    name = prof.get("name") or ts_code
    blocks = []
    if cur:
        dims = {"ROE": _clamp01((cur.get("roe") or 0) / 30),
                "净利率": _clamp01((cur.get("net_margin") or 0) / 50),
                "毛利率": _clamp01((cur.get("gross_margin") or 0) / 100),
                "低杠杆": _clamp01((100 - (cur.get("debt_ratio") or 0)) / 100),
                "综合质量": q.get("quality_score") or 0.0}
        blocks.append(f'<div class="chart">{radar_svg(dims, title=f"{name} 财务画像")}</div>')
    if annual:
        yrs = [a["year"] for a in reversed(annual)]
        blocks.append('<div class="chart">' + line_svg(
            {"营收(亿)": [a.get("revenue_yi") for a in reversed(annual)],
             "净利(亿)": [a.get("net_profit_yi") for a in reversed(annual)]},
            yrs, title="营收 vs 净利趋势") + '</div>')
    inv = investment_trend(cache, ts_code, date=date)
    sec = inv.get("series", [])
    if sec:
        blocks.append('<div class="chart">' + line_svg(
            {"在建工程(亿)": [s.get("cip_yi") for s in sec],
             "固定资产(亿)": [s.get("fix_yi") for s in sec]},
            [s.get("year") for s in sec], title="扩张投入趋势") + '</div>')
    if peers:
        pc = peer_comparison(cache, [ts_code] + list(peers), date)
        names = [p.get("name") or p["ts_code"] for p in pc["peers"]]
        blocks.append('<div class="chart">' + grouped_bar_svg(
            {"ROE": [p.get("latest_roe") for p in pc["peers"]],
             "净利率": [p.get("net_margin") for p in pc["peers"]]},
            names, title="对标:ROE vs 净利率(%)") + '</div>')
    return ("## 图表\n\n" + "\n\n".join(blocks)) if blocks else ""


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
