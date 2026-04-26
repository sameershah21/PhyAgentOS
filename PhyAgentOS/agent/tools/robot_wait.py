"""Robot action polling tools."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from PhyAgentOS.agent.tools.base import Tool
from PhyAgentOS.embodiment_registry import EmbodimentRegistry
from PhyAgentOS.utils.action_queue import normalize_action_document, parse_action_markdown


_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "canceled"})


class WaitForRobotActionTool(Tool):
    """Wait until a HAL watchdog marks a robot action terminal."""

    def __init__(self, workspace: Path, registry: EmbodimentRegistry | None = None):
        self.workspace = workspace
        self.registry = registry

    @property
    def name(self) -> str:
        return "wait_for_robot_action"

    @property
    def description(self) -> str:
        return (
            "Poll a robot ACTION.md until an action reaches a terminal status. "
            "Use after execute_robot_action when the next planning step depends on "
            "hardware completion. In fleet mode, robot_id is required. If action_id "
            "is omitted, the newest action in that robot's queue is selected."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "robot_id": {
                    "type": "string",
                    "description": "Target robot id. Required in fleet mode.",
                },
                "action_id": {
                    "type": "string",
                    "description": "Specific action id to wait for. If omitted, waits for the newest action.",
                },
                "timeout_s": {
                    "type": "number",
                    "description": "Maximum time to wait in seconds.",
                    "minimum": 0.1,
                    "maximum": 3600,
                },
                "poll_interval_s": {
                    "type": "number",
                    "description": "Polling interval in seconds.",
                    "minimum": 0.05,
                    "maximum": 10,
                },
            },
            "required": [],
        }

    async def execute(
        self,
        robot_id: str | None = None,
        action_id: str | None = None,
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.5,
    ) -> str:
        try:
            action_file = self._resolve_action_file(robot_id)
        except KeyError as exc:
            return f"Error: {exc}"

        timeout_s = max(0.1, float(timeout_s))
        poll_interval_s = max(0.05, min(float(poll_interval_s), timeout_s))
        selected_id = str(action_id or "").strip() or None
        deadline = time.monotonic() + timeout_s
        last_seen: dict[str, Any] | None = None

        while True:
            document = self._load_action_document(action_file)
            if document is None:
                return f"Error: ACTION.md contains unreadable content: {action_file}"

            actions = document.get("actions", [])
            if actions:
                if selected_id is None:
                    selected_id = str(actions[-1].get("id") or "").strip() or None
                last_seen = self._find_action(actions, selected_id) if selected_id else actions[-1]
                if last_seen is not None:
                    status = str(last_seen.get("status") or "pending").lower()
                    if status in _TERMINAL_STATUSES:
                        result = last_seen.get("result", "")
                        payload = {
                            "robot_id": robot_id,
                            "action_id": last_seen.get("id"),
                            "action_type": last_seen.get("action_type"),
                            "status": status,
                            "result": result,
                        }
                        return "Robot action terminal: " + json.dumps(payload, ensure_ascii=False)

            now = time.monotonic()
            if now >= deadline:
                if last_seen is None:
                    target = selected_id or "newest action"
                    return f"Timeout waiting for {target}; no matching action found in {action_file}."
                payload = {
                    "robot_id": robot_id,
                    "action_id": last_seen.get("id"),
                    "action_type": last_seen.get("action_type"),
                    "status": last_seen.get("status", "pending"),
                    "result": last_seen.get("result", ""),
                }
                return "Timeout waiting for robot action: " + json.dumps(payload, ensure_ascii=False)

            await asyncio.sleep(min(poll_interval_s, max(0.0, deadline - now)))

    def _resolve_action_file(self, robot_id: str | None) -> Path:
        rid = str(robot_id or "").strip() or None
        if self.registry:
            if self.registry.is_fleet and not rid:
                raise KeyError("robot_id is required in fleet mode.")
            if rid:
                return self.registry.resolve_action_path(robot_id=rid, default_workspace=self.workspace)
        return self.workspace / "ACTION.md"

    @staticmethod
    def _load_action_document(action_file: Path) -> dict[str, Any] | None:
        if not action_file.exists():
            return {"schema_version": "PhyAgentOS.action_queue.v1", "actions": []}
        content = action_file.read_text(encoding="utf-8").strip()
        if not content:
            return {"schema_version": "PhyAgentOS.action_queue.v1", "actions": []}
        payload = parse_action_markdown(content)
        if payload is None:
            return None
        return normalize_action_document(payload)

    @staticmethod
    def _find_action(actions: list[dict[str, Any]], action_id: str | None) -> dict[str, Any] | None:
        if not action_id:
            return actions[-1] if actions else None
        for item in actions:
            if str(item.get("id") or "") == action_id:
                return item
        return None
