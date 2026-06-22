"""LLM 洞见层 —— agent + skill 工具链(**非 NL2SQL**)。

LLM 只编排调用**确定性工具** + 解读撰写,数字一律来自工具(不碰 SQL、不自己算数)。
工具核心一份实现,多协议暴露(OpenAI function-calling;MCP 后续)。模型走 OpenAI
兼容 API,可换(DeepSeek V4 / GLM-5.2 / MiniMax-3)。真跑需配 key;逻辑用 MockLLM 测。
"""
from .agent import Agent, LLM, OpenAICompatLLM
from .tools import Tool, ToolRegistry

__all__ = ["ToolRegistry", "Tool", "Agent", "LLM", "OpenAICompatLLM"]
