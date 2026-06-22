"""LLM agent —— OpenAI 兼容 tool-use 循环。LLM 编排调用确定性工具 + 解读撰写。

模型可换(DeepSeek V4 / GLM / MiniMax),走 OpenAI 兼容 API。真跑需配 api_key;
单元测试用 MockLLM(实现 LLM 抽象)验证循环逻辑,不依赖真 LLM / 网络 / openai 包。
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import List, Optional

from .tools import ToolRegistry


class LLM(ABC):
    @abstractmethod
    def chat(self, messages: List[dict], tools: Optional[List[dict]] = None) -> dict:
        """统一返回:{"content": str|None, "tool_calls": [{"id","name","arguments"}]}。"""


class OpenAICompatLLM(LLM):
    """DeepSeek / GLM / MiniMax 等 OpenAI 兼容 endpoint(openai SDK 仅在此惰性导入)。"""

    def __init__(self, model: str, base_url: str, api_key: str, temperature: float = 0.3):
        from openai import OpenAI
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.temperature = temperature

    def chat(self, messages, tools=None):
        resp = self.client.chat.completions.create(
            model=self.model, messages=messages,
            tools=tools or None, temperature=self.temperature)
        m = resp.choices[0].message
        tcs = [{"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
               for tc in (m.tool_calls or [])]
        return {"content": m.content, "tool_calls": tcs}


class Agent:
    """tool-use 循环:LLM ↔ 工具,直到 LLM 不再调工具,返回最终文本。"""

    def __init__(self, registry: ToolRegistry, llm: LLM, system: str = ""):
        self.registry = registry
        self.llm = llm
        self.system = system

    def run(self, user_msg: str, max_turns: int = 8) -> str:
        messages: List[dict] = []
        if self.system:
            messages.append({"role": "system", "content": self.system})
        messages.append({"role": "user", "content": user_msg})

        for _ in range(max_turns):
            resp = self.llm.chat(messages, tools=self.registry.openai_tools())
            tool_calls = resp.get("tool_calls") or []
            messages.append({"role": "assistant", "content": resp.get("content"),
                             "tool_calls": tool_calls})
            if not tool_calls:
                return resp.get("content") or ""
            for tc in tool_calls:
                try:
                    result = self.registry.call(tc["name"], tc.get("arguments", {}))
                    content = json.dumps(result, ensure_ascii=False, default=str)
                except Exception as e:                       # 工具出错回填给 LLM,让它自处理
                    content = json.dumps({"error": str(e)}, ensure_ascii=False)
                messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                                 "name": tc["name"], "content": content})
        return "(达到最大工具调用轮次,未收敛)"
