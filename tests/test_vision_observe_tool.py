from __future__ import annotations

import asyncio
import json
from pathlib import Path

from PhyAgentOS.agent.tools.vision_observe import CaptureAndDescribeSceneTool
from PhyAgentOS.config.schema import Config
from PhyAgentOS.embodiment_registry import EmbodimentRegistry
from PhyAgentOS.providers.base import LLMResponse
from PhyAgentOS.utils.action_queue import dump_action_document, normalize_action_document, parse_action_markdown
from hal.simulation.scene_io import load_environment_doc, save_environment_doc


_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?"
    b"\x00\x05\xfe\x02\xfeA\xe2!\xbc\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FakeVisionProvider:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def chat_with_retry(self, **kwargs):
        self.calls.append(kwargs)
        return LLMResponse(
            content=json.dumps(
                {
                    "customer_present": True,
                    "mock_id_visible": True,
                    "summary": "A customer is holding up a mock ID card.",
                }
            )
        )


def _write_action(path: Path, document: dict) -> None:
    path.write_text(dump_action_document(document), encoding="utf-8")


async def _complete_capture(action_file: Path) -> None:
    for _ in range(40):
        if action_file.exists():
            payload = parse_action_markdown(action_file.read_text(encoding="utf-8"))
            document = normalize_action_document(payload or {})
            if document and document["actions"]:
                action = document["actions"][-1]
                output_path = Path(action["parameters"]["output_path"])
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(_PNG_1X1)
                action["status"] = "completed"
                action["result"] = f"Reachy Mini camera frame saved to {output_path}"
                _write_action(action_file, document)
                return
        await asyncio.sleep(0.01)
    raise AssertionError("capture action was not dispatched")


def test_capture_and_describe_scene_writes_observation(tmp_path: Path) -> None:
    env_path = tmp_path / "ENVIRONMENT.md"
    save_environment_doc(
        env_path,
        {
            "schema_version": "PhyAgentOS.environment.v1",
            "objects": {},
            "robots": {},
            "scene_graph": {"nodes": [], "edges": []},
        },
    )
    provider = FakeVisionProvider()
    tool = CaptureAndDescribeSceneTool(workspace=tmp_path, provider=provider, model="vision-test")

    async def run_tool() -> str:
        worker = asyncio.create_task(_complete_capture(tmp_path / "ACTION.md"))
        result = await tool.execute(
            robot_id="reachy_frontdesk",
            prompt="Is a mock ID visible?",
            timeout_s=1.0,
            poll_interval_s=0.01,
        )
        await worker
        return result

    result = asyncio.run(run_tool())

    assert result.startswith("Vision observation complete: ")
    payload = json.loads(result.split(": ", 1)[1])
    assert payload["robot_id"] == "reachy_frontdesk"
    assert payload["observation"]["mock_id_visible"] is True
    assert provider.calls
    content = provider.calls[0]["messages"][1]["content"]
    assert content[0]["type"] == "image_url"
    assert content[1]["text"] == "Is a mock ID visible?"

    env = load_environment_doc(env_path)
    camera = env["objects"]["reachy_frontdesk_camera"]
    assert camera["type"] == "vision_observation"
    assert camera["robot_id"] == "reachy_frontdesk"
    assert camera["observation"]["customer_present"] is True
    assert Path(camera["latest_frame_path"]).exists()


def test_capture_and_describe_scene_requires_robot_id_in_fleet_mode(tmp_path: Path) -> None:
    config = Config.model_validate(
        {
            "embodiments": {
                "mode": "fleet",
                "sharedWorkspace": str(tmp_path / "shared"),
                "instances": [
                    {
                        "robotId": "reachy_frontdesk",
                        "driver": "reachy_mini",
                        "workspace": str(tmp_path / "reachy_frontdesk"),
                        "enabled": True,
                    }
                ],
            }
        }
    )
    registry = EmbodimentRegistry(config)
    registry.sync_layout()
    tool = CaptureAndDescribeSceneTool(
        workspace=registry.resolve_agent_workspace(),
        provider=FakeVisionProvider(),
        model="vision-test",
        registry=registry,
    )

    result = asyncio.run(tool.execute(timeout_s=0.1, poll_interval_s=0.01))

    assert "robot_id is required in fleet mode" in result
