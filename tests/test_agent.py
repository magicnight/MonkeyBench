"""LLM agent 框架测试 —— MockLLM 验证循环,不依赖真 LLM/网络/openai 包。
运行:.venv/bin/python tests/test_agent.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from insight.agent import Agent, LLM
from insight.tools import ToolRegistry


class MockLLM(LLM):
    """按脚本逐轮返回响应。"""
    def __init__(self, script):
        self.script = script
        self.i = 0
        self.seen_tools = None

    def chat(self, messages, tools=None):
        self.seen_tools = tools
        r = self.script[self.i]
        self.i += 1
        return r


_NUM = {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
        "required": ["a", "b"]}


def test_registry_schema_and_call():
    reg = ToolRegistry()

    @reg.register("add", "两数相加", _NUM)
    def add(a, b):
        return a + b

    assert reg.openai_tools()[0]["function"]["name"] == "add"
    assert reg.call("add", {"a": 2, "b": 3}) == 5
    assert reg.call("add", '{"a": 1, "b": 1}') == 2     # JSON 字符串参数


def test_agent_tool_loop():
    reg = ToolRegistry()

    @reg.register("get_score", "取公司评分",
                  {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]})
    def get_score(code):
        return {"f_score": 8, "code": code}

    llm = MockLLM([
        {"content": None, "tool_calls": [{"id": "1", "name": "get_score", "arguments": {"code": "600519.SH"}}]},
        {"content": "贵州茅台 F-Score 8,财务健康。", "tool_calls": []},
    ])
    out = Agent(reg, llm, system="你是分析师").run("分析 600519.SH")
    assert "F-Score 8" in out
    assert llm.seen_tools[0]["function"]["name"] == "get_score"   # 工具 schema 确实传给了 LLM


def test_agent_no_tool():
    assert Agent(ToolRegistry(), MockLLM([{"content": "直接回答。", "tool_calls": []}])).run("hi") == "直接回答。"


def test_tool_error_fed_back():
    reg = ToolRegistry()

    @reg.register("boom", "会抛错", {"type": "object", "properties": {}})
    def boom():
        raise ValueError("炸了")

    # 第1轮调 boom(抛错→回填 error),第2轮 LLM 看到 error 后收尾
    llm = MockLLM([
        {"content": None, "tool_calls": [{"id": "1", "name": "boom", "arguments": {}}]},
        {"content": "工具出错,已知悉。", "tool_calls": []},
    ])
    assert "已知悉" in Agent(reg, llm).run("test")


if __name__ == "__main__":
    for fn in [test_registry_schema_and_call, test_agent_tool_loop,
               test_agent_no_tool, test_tool_error_fed_back]:
        fn()
        print(f"  ✓ {fn.__name__}")
    print("✅ LLM agent 框架 全部通过")
