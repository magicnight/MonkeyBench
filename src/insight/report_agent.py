"""DD 式公司分析报告 agent —— LLM 编排 insight 工具收集本地数据,撰写结构化长报告。

铁律:LLM 只调确定性工具拿数字、只负责解读与行文,**绝不自己算/编数**。
配 LLM key 后 `company_dd_report(...)` 端到端产出报告;无 key 时用 MockLLM 验证编排逻辑。

注:真 LLM 接入时需校验 agent.py 里 assistant.tool_calls 回传 messages 的格式是否符合
目标 endpoint(OpenAI 要求 {id,type,function:{name,arguments}} 嵌套)—— 见 [[insight-agent-notes]]。
"""
from __future__ import annotations

from .agent import Agent, LLM
from .skills import register_company_tools
from .tools import ToolRegistry

DD_SYSTEM = """你是严谨的 A 股尽职调查(DD)分析师。基于工具返回的本地数据,撰写一份客观的公司分析长报告。

硬性要求:
- 所有数字必须来自工具调用结果,严禁自行估算或编造;工具没返回的就明确写"数据缺失"。
- 先用工具收集:company_profile(概况估值)、financial_history(财务历史)、price_performance(股价)、quality_score(综合质量分);若用户给了对标股,调用 peer_comparison。
- 数据齐了再动笔,报告结构:
  ① 一句话定性  ② 公司与业务  ③ 财务质量(趋势 + 多空两面)  ④ 估值水平
  ⑤ 股价 vs 基本面(重点识别"背离")  ⑥ 同业对标(如有)  ⑦ 综合判断与主要风险
- 客观中立、多空都讲;质量分要结合趋势解读(高分位也可能掩盖盈利恶化)。全文中文。"""


def build_dd_agent(cache, llm: LLM) -> Agent:
    """组装 DD 报告 agent:注册本地数据工具 + DD system prompt。"""
    reg = ToolRegistry()
    register_company_tools(reg, cache)
    return Agent(reg, llm, system=DD_SYSTEM)


def company_dd_report(cache, llm: LLM, ts_code: str, peers: list | None = None,
                      max_turns: int = 8) -> str:
    """对 ts_code 产出 DD 长报告;peers 给定则做自定义对标。返回 Markdown 文本。"""
    agent = build_dd_agent(cache, llm)
    msg = f"请对 {ts_code} 撰写一份 DD 分析报告。"
    if peers:
        msg += f"并与以下标的对标:{', '.join(peers)}。"
    return agent.run(msg, max_turns=max_turns)
