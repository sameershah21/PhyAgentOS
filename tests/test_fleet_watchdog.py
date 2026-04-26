from __future__ import annotations

from pathlib import Path

from PhyAgentOS.config.schema import Config
from hal.hal_watchdog import _resolve_watchdog_topology, _save_scene
from hal.simulation.scene_io import load_environment_doc, save_environment_doc


def test_watchdog_resolves_robot_workspace_and_shared_environment(monkeypatch, tmp_path: Path) -> None:
    config = Config.model_validate(
        {
            "embodiments": {
                "mode": "fleet",
                "sharedWorkspace": str(tmp_path / "workspaces" / "shared"),
                "instances": [
                    {
                        "robotId": "go2_edu_001",
                        "driver": "go2_edu",
                        "workspace": str(tmp_path / "workspaces" / "go2_edu_001"),
                        "enabled": True,
                    }
                ],
            }
        }
    )
    monkeypatch.setattr("PhyAgentOS.config.loader.load_config", lambda: config)

    robot_workspace, env_file, driver_name, registry = _resolve_watchdog_topology(
        None,
        "simulation",
        "go2_edu_001",
    )

    assert robot_workspace == tmp_path / "workspaces" / "go2_edu_001"
    assert env_file == tmp_path / "workspaces" / "shared" / "ENVIRONMENT.md"
    assert driver_name == "go2_edu"
    assert registry is not None
    assert registry.is_fleet is True


def test_save_scene_preserves_side_loaded_object_observations(tmp_path: Path) -> None:
    env_path = tmp_path / "ENVIRONMENT.md"
    save_environment_doc(
        env_path,
        {
            "schema_version": "PhyAgentOS.environment.v1",
            "objects": {
                "reachy_mini_safety_observation": {
                    "type": "vision_observation",
                    "observation": {"summary": "safe"},
                },
                "reachy_mini_runtime": {"type": "old_runtime"},
            },
            "robots": {},
            "scene_graph": {"nodes": [], "edges": []},
        },
    )

    class Driver:
        def get_runtime_state(self):
            return {}

        def get_scene(self):
            return {
                "reachy_mini_runtime": {
                    "type": "runtime",
                    "last_action": "capture_frame",
                }
            }

    _save_scene(Driver(), env_path, Driver().get_scene())

    objects = load_environment_doc(env_path)["objects"]
    assert objects["reachy_mini_safety_observation"]["observation"]["summary"] == "safe"
    assert objects["reachy_mini_runtime"]["type"] == "runtime"
