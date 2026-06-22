"""DD 报告 agent 编排测试 —— MockLLM 驱动,验证「调本地工具 → 收敛成报告」链路。

不需真 LLM / key / 网络;复用 test_skills 的内存库样本。重点验证:agent 确实调到了
确定性工具拿数据(铁律:数字来自工具),且最终收敛产出文本。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from insight.agent import LLM
from insight.report_agent import build_dd_agent, company_dd_report, dd_report_from_data
from test_skills import make_cache


class MockLLM(LLM):
    """两轮:先调工具(profile + quality + peer),拿到结果后产出报告文本。记录工具是否被调。"""

    def __init__(self, peers=False):
        self.turn = 0
        self.peers = peers
        self.saw_tool_results = False

    def chat(self, messages, tools=None):
        self.turn += 1
        if self.turn == 1:
            calls = [
                {"id": "a", "name": "company_profile", "arguments": '{"ts_code":"688205.SH"}'},
                {"id": "b", "name": "quality_score", "arguments": '{"ts_code":"688205.SH"}'},
                {"id": "c", "name": "financial_history", "arguments": '{"ts_code":"688205.SH"}'},
            ]
            if self.peers:
                calls.append({"id": "d", "name": "peer_comparison",
                              "arguments": '{"ts_codes":["688205.SH","600519.SH"]}'})
            return {"content": None, "tool_calls": calls}
        # 第二轮:确认收到了工具结果(tool 消息),产出报告
        self.saw_tool_results = any(m.get("role") == "tool" for m in messages)
        return {"content": "# 德科立(688205.SH) DD 报告\n基于工具数据:质量中等、估值偏高。",
                "tool_calls": []}


def test_dd_agent_calls_tools_then_writes():
    cache = make_cache()
    llm = MockLLM()
    report = company_dd_report(cache, llm, "688205.SH")
    assert llm.saw_tool_results, "agent 应把工具结果回填给 LLM"
    assert "德科立" in report and "DD" in report
    assert llm.turn == 2
    cache.close()


def test_dd_agent_with_peers():
    cache = make_cache()
    llm = MockLLM(peers=True)
    report = company_dd_report(cache, llm, "688205.SH", peers=["600519.SH"])
    assert llm.saw_tool_results
    assert report.strip()
    cache.close()


def test_build_dd_agent_has_tools():
    cache = make_cache()
    agent = build_dd_agent(cache, MockLLM())
    assert len(agent.registry.openai_tools()) == 5
    assert "peer_comparison" in agent.registry.names()
    assert "DD" in agent.system                          # system 已注入
    cache.close()


def test_dd_report_from_data_fallback():
    """无 LLM 降级报告:工具数据 + 模板 → Markdown(含雷达图 + 对标表)。"""
    cache = make_cache()
    md = dd_report_from_data(cache, "688205.SH", peers=["600519.SH"])
    assert "德科立" in md
    assert "营收" in md and "9.34" in md                 # 财务数据进表
    assert "<svg" in md                                  # 财务画像雷达图
    assert "同业对标" in md and "贵州茅台" in md          # 自定义对标表
    assert "综合质量分" in md
    assert dd_report_from_data(cache, "000000.SZ").startswith("# 000000.SZ")  # 不存在兜底
    cache.close()


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ✓ {name}")
    print("✅ DD 报告 agent 编排全部通过")
