"""工具注册 —— 一份 Python 实现,多协议暴露(OpenAI function-calling + 可选 MCP)。

领域工具(查行情/算评分/同业对标…)注册到 ToolRegistry,LLM agent 只能调注册过的、
确定性的工具 —— LLM 不碰 SQL、不自己算数(项目铁律)。工具内部查 DuckDB/算评分,
数字全来自工具,LLM 只解读。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Dict, List


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]   # JSON schema(object)
    fn: Callable


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, name: str, description: str, parameters: Dict[str, Any]):
        """装饰器:把函数注册为工具。parameters 为 JSON schema(object)。"""
        def deco(fn: Callable) -> Callable:
            self._tools[name] = Tool(name, description, parameters, fn)
            return fn
        return deco

    def names(self) -> List[str]:
        return list(self._tools)

    def openai_tools(self) -> List[dict]:
        """OpenAI / DeepSeek function-calling 的 tools schema。"""
        return [{"type": "function",
                 "function": {"name": t.name, "description": t.description,
                              "parameters": t.parameters}}
                for t in self._tools.values()]

    def call(self, name: str, arguments) -> Any:
        """执行工具。arguments 为 dict 或 JSON 字符串。未注册 → KeyError。"""
        if name not in self._tools:
            raise KeyError(f"未注册的工具:{name}")
        if isinstance(arguments, str):
            arguments = json.loads(arguments or "{}")
        return self._tools[name].fn(**(arguments or {}))
