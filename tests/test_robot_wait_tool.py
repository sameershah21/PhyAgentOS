from __future__ import annotations

import asyncio
import json
from pathlib import Path

from PhyAgentOS.agent.tools.robot_wait import WaitForRobotActionTool
from PhyAgentOS.config.schema import Config
from PhyAgentOS.embodiment_registry import EmbodimentRegistry
from PhyAgentOS.utils.action_queue import dump_action_document


def _write_action_doc(path: Path, actions: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        dump_action_document(
            {
                "schema_version": "PhyAgentOS.action_queue.v1",
                "actions": actions,
            }
        ),
        encoding="utf-8",
    )


def _fleet_registry(tmp_path: Path) -> EmbodimentRegistry:
    config = Config.model_validate(
        {
            "embodiments": {
                "mode": "fleet",
                "sharedWorkspace": str(tmp_path / "shared"),
                "instances": [
                    {
                        "robotId": "reachy_mini_001",
                        "driver": "reachy_mini",
                        "workspace": str(tmp_path / "reachy_mini_001"),
                        "enabled": True,
                    }
                ],
            }
        }
    )
    registry = EmbodimentRegistry(config)
    registry.sync_layout()
    return registry


def test_wait_for_specific_completed_action_single_workspace(tmp_path: Path) -> None:
    action_file = tmp_path / "ACTION.md"
    _write_action_doc(
        action_file,
        [
            {
                "id": "act1",
                "action_type": "set_antennas",
                "parameters": {},
                "status": "completed",
                "result": "done",
            }
        ],
    )
    tool = WaitForRobotActionTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(action_id="act1", timeout_s=0.2, poll_interval_s=0.05))

    assert result.startswith("Robot action terminal: ")
    payload = json.loads(result.split(": ", 1)[1])
    assert payload["action_id"] == "act1"
    assert payload["status"] == "completed"
    assert payload["result"] == "done"


def test_wait_for_newest_action_when_action_id_omitted(tmp_path: Path) -> None:
    _write_action_doc(
        tmp_path / "ACTION.md",
        [
            {"id": "old", "action_type": "wake_up", "parameters": {}, "status": "completed"},
            {
                "id": "new",
                "action_type": "goto_sleep",
                "parameters": {},
                "status": "failed",
                "result": "Error: nope",
            },
        ],
    )
    tool = WaitForRobotActionTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(timeout_s=0.2, poll_interval_s=0.05))

    payload = json.loads(result.split(": ", 1)[1])
    assert payload["action_id"] == "new"
    assert payload["status"] == "failed"


def test_wait_timeout_reports_pending_action(tmp_path: Path) -> None:
    _write_action_doc(
        tmp_path / "ACTION.md",
        [{"id": "act1", "action_type": "wake_up", "parameters": {}, "status": "pending"}],
    )
    tool = WaitForRobotActionTool(workspace=tmp_path)

    result = asyncio.run(tool.execute(action_id="act1", timeout_s=0.1, poll_interval_s=0.05))

    assert result.startswith("Timeout waiting for robot action: ")
    payload = json.loads(result.split(": ", 1)[1])
    assert payload["action_id"] == "act1"
    assert payload["status"] == "pending"


def test_wait_requires_robot_id_in_fleet_mode(tmp_path: Path) -> None:
    registry = _fleet_registry(tmp_path)
    tool = WaitForRobotActionTool(workspace=registry.resolve_agent_workspace(), registry=registry)

    result = asyncio.run(tool.execute(timeout_s=0.1, poll_interval_s=0.05))

    assert "robot_id is required in fleet mode" in result


def test_wait_uses_robot_workspace_in_fleet_mode(tmp_path: Path) -> None:
    registry = _fleet_registry(tmp_path)
    action_file = tmp_path / "reachy_mini_001" / "ACTION.md"
    _write_action_doc(
        action_file,
        [{"id": "act1", "action_type": "wake_up", "parameters": {}, "status": "completed"}],
    )
    tool = WaitForRobotActionTool(workspace=registry.resolve_agent_workspace(), registry=registry)

    result = asyncio.run(
        tool.execute(robot_id="reachy_mini_001", action_id="act1", timeout_s=0.2, poll_interval_s=0.05)
    )

    payload = json.loads(result.split(": ", 1)[1])
    assert payload["robot_id"] == "reachy_mini_001"
    assert payload["action_id"] == "act1"
