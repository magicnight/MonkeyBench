"""append-only 事件日志 —— 所有成交/拒单/估值都落这里,事后才能做归因。

刻意只追加、不修改。MVP 用内存 list;给了 to_jsonl 方便落盘后用别的工具分析。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class EventLog:
    events: List[Dict[str, Any]] = field(default_factory=list)

    def append(self, **event: Any) -> None:
        self.events.append(event)

    def for_account(self, account_id: str) -> List[Dict[str, Any]]:
        return [e for e in self.events if e.get("account_id") == account_id]

    def to_jsonl(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for e in self.events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
