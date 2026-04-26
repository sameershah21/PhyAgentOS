"""Robot camera capture plus vision-model observation tool."""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import mimetypes
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PhyAgentOS.agent.tools.base import Tool
from PhyAgentOS.embodiment_registry import EmbodimentRegistry
from PhyAgentOS.providers.base import LLMProvider
from PhyAgentOS.providers.providers_manager import ProvidersManager
from PhyAgentOS.utils.action_queue import (
    append_action,
    dump_action_document,
    empty_action_document,
    normalize_action_document,
    parse_action_markdown,
)
from PhyAgentOS.utils.helpers import detect_image_mime
from hal.simulation.scene_io import load_environment_doc, merge_environment_doc, save_environment_doc


_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "canceled"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class CaptureAndDescribeSceneTool(Tool):
    """Capture a robot camera frame and ask a vision model to describe it."""

    def __init__(
        self,
        *,
        workspace: Path,
        provider: LLMProvider | ProvidersManager,
        model: str,
        registry: EmbodimentRegistry | None = None,
    ) -> None:
        self.workspace = workspace
        self.provider = provider
        self.model = model
        self.registry = registry

    @property
    def name(self) -> str:
        return "capture_and_describe_scene"

    @property
    def description(self) -> str:
        return (
            "Capture one camera frame from a robot HAL, pass it to a vision-capable model, "
            "and write the structured observation back into ENVIRONMENT.md. Use this when "
            "the next robot action depends on current visual context."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "robot_id": {
                    "type": "string",
                    "description": "Robot id to capture from. Required in fleet mode.",
                },
                "prompt": {
                    "type": "string",
                    "description": "Vision question/task for the model.",
                },
                "output_path": {
                    "type": "string",
                    "description": "Optional image output path. Defaults under workspace/artifacts/vision.",
                },
                "vision_model": {
                    "type": "string",
                    "description": "Optional model override for the vision call.",
                },
                "vision_mode": {
                    "type": "string",
                    "description": "Provider mode to use when ProvidersManager is active.",
                    "enum": ["multimodal", "main", "auto"],
                },
                "observation_key": {
                    "type": "string",
                    "description": "Object key to update in ENVIRONMENT.md.",
                },
                "timeout_s": {
                    "type": "number",
                    "description": "Maximum time to wait for frame capture.",
                    "minimum": 0.1,
                    "maximum": 3600,
                },
                "poll_interval_s": {
                    "type": "number",
                    "description": "Polling interval while waiting for HAL completion.",
                    "minimum": 0.05,
                    "maximum": 10,
                },
                "write_environment": {
                    "type": "boolean",
                    "description": "Whether to write the vision observation into ENVIRONMENT.md.",
                },
            },
            "required": [],
        }

    async def execute(
        self,
        robot_id: str | None = None,
        prompt: str | None = None,
        output_path: str | None = None,
        vision_model: str | None = None,
        vision_mode: str = "multimodal",
        observation_key: str | None = None,
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.5,
        write_environment: bool = True,
    ) -> str:
        rid = str(robot_id or "").strip() or None
        try:
            action_file = self._resolve_action_file(rid)
            env_file = self._resolve_environment_file(rid)
        except KeyError as exc:
            return f"Error: {exc}"

        if self._has_pending_action(action_file):
            return (
                f"Error: {action_file} already contains a pending action. "
                "Wait for it before capturing a new frame."
            )

        image_path = self._resolve_output_path(output_path, rid)
        image_path.parent.mkdir(parents=True, exist_ok=True)
        action_id = self._dispatch_capture(action_file, image_path, rid)

        wait_result = await self._wait_for_action(
            action_file=action_file,
            action_id=action_id,
            timeout_s=float(timeout_s),
            poll_interval_s=float(poll_interval_s),
        )
        if wait_result.get("status") != "completed":
            return "Robot frame capture did not complete: " + json.dumps(wait_result, ensure_ascii=False)
        if not image_path.exists():
            return f"Error: capture completed but image file was not found: {image_path}"

        vision_prompt = (prompt or "").strip() or (
            "Describe the scene for robot planning. Return concise JSON with "
            "customer_present, mock_id_visible, safety_risks, and summary."
        )
        observation = await self._describe_image(
            image_path=image_path,
            prompt=vision_prompt,
            vision_model=str(vision_model or "").strip() or None,
            vision_mode=vision_mode or "multimodal",
        )

        key = str(observation_key or "").strip() or self._default_observation_key(rid)
        if write_environment:
            self._write_observation(
                env_file=env_file,
                observation_key=key,
                robot_id=rid,
                image_path=image_path,
                prompt=vision_prompt,
                model=vision_model or self.model,
                observation=observation,
            )

        payload = {
            "robot_id": rid,
            "action_id": action_id,
            "frame_path": str(image_path),
            "environment_path": str(env_file) if write_environment else None,
            "observation_key": key if write_environment else None,
            "observation": observation,
        }
        return "Vision observation complete: " + json.dumps(payload, ensure_ascii=False)

    def _resolve_action_file(self, robot_id: str | None) -> Path:
        if self.registry:
            if self.registry.is_fleet and not robot_id:
                raise KeyError("robot_id is required in fleet mode.")
            if robot_id:
                return self.registry.resolve_action_path(robot_id=robot_id, default_workspace=self.workspace)
        return self.workspace / "ACTION.md"

    def _resolve_environment_file(self, robot_id: str | None) -> Path:
        if self.registry and robot_id:
            return self.registry.resolve_environment_path(robot_id=robot_id)
        return self.workspace / "ENVIRONMENT.md"

    def _resolve_output_path(self, output_path: str | None, robot_id: str | None) -> Path:
        if output_path:
            path = Path(output_path).expanduser()
            return path if path.is_absolute() else self.workspace / path
        stem = robot_id or "robot_camera"
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return self.workspace / "artifacts" / "vision" / f"{stem}_{ts}.jpg"

    @staticmethod
    def _load_action_document(action_file: Path) -> dict[str, Any]:
        if not action_file.exists():
            return empty_action_document()
        content = action_file.read_text(encoding="utf-8").strip()
        if not content:
            return empty_action_document()
        payload = parse_action_markdown(content)
        return normalize_action_document(payload) if payload is not None else empty_action_document()

    def _has_pending_action(self, action_file: Path) -> bool:
        document = self._load_action_document(action_file)
        return any(str(item.get("status") or "pending").lower() == "pending" for item in document["actions"])

    def _dispatch_capture(self, action_file: Path, image_path: Path, robot_id: str | None) -> str:
        document = self._load_action_document(action_file)
        params: dict[str, Any] = {"output_path": str(image_path)}
        if robot_id:
            params["robot_id"] = robot_id
        document = append_action(document, action_type="capture_frame", parameters=params)
        action_id = str(document["actions"][-1]["id"])
        action_file.parent.mkdir(parents=True, exist_ok=True)
        action_file.write_text(dump_action_document(document), encoding="utf-8")
        return action_id

    async def _wait_for_action(
        self,
        *,
        action_file: Path,
        action_id: str,
        timeout_s: float,
        poll_interval_s: float,
    ) -> dict[str, Any]:
        timeout_s = max(0.1, timeout_s)
        poll_interval_s = max(0.05, min(poll_interval_s, timeout_s))
        deadline = time.monotonic() + timeout_s
        last_seen: dict[str, Any] | None = None

        while True:
            for item in self._load_action_document(action_file).get("actions", []):
                if str(item.get("id") or "") == action_id:
                    last_seen = item
                    status = str(item.get("status") or "pending").lower()
                    if status in _TERMINAL_STATUSES:
                        return {
                            "action_id": action_id,
                            "action_type": item.get("action_type"),
                            "status": status,
                            "result": item.get("result", ""),
                        }
            now = time.monotonic()
            if now >= deadline:
                return {
                    "action_id": action_id,
                    "status": (last_seen or {}).get("status", "missing"),
                    "result": (last_seen or {}).get("result", ""),
                }
            await asyncio.sleep(min(poll_interval_s, max(0.0, deadline - now)))

    async def _describe_image(
        self,
        *,
        image_path: Path,
        prompt: str,
        vision_model: str | None,
        vision_mode: str,
    ) -> dict[str, Any]:
        raw = image_path.read_bytes()
        mime = detect_image_mime(raw) or mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
        b64 = base64.b64encode(raw).decode("ascii")
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a robot perception assistant. Return only JSON. "
                    "Use null for uncertain fields and include a short summary."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            },
        ]
        kwargs = {
            "messages": messages,
            "tools": None,
            "model": vision_model or self.model,
            "max_tokens": 800,
            "temperature": 0.1,
        }
        if isinstance(self.provider, ProvidersManager):
            kwargs["mode"] = vision_mode

        call = self.provider.chat_with_retry(**kwargs)
        response = await call if inspect.isawaitable(call) else call
        content = response.content or ""
        parsed = self._parse_json(content)
        if parsed is not None:
            return parsed
        return {"summary": content.strip(), "raw_response": content}

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any] | None:
        text = content.strip()
        if not text:
            return None
        if "```json" in text:
            try:
                _, block = text.split("```json", 1)
                block, _ = block.split("```", 1)
                text = block.strip()
            except ValueError:
                pass
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _default_observation_key(robot_id: str | None) -> str:
        if robot_id and "reachy" in robot_id:
            return f"{robot_id}_camera"
        return "robot_camera_observation"

    @staticmethod
    def _write_observation(
        *,
        env_file: Path,
        observation_key: str,
        robot_id: str | None,
        image_path: Path,
        prompt: str,
        model: str,
        observation: dict[str, Any],
    ) -> None:
        existing = load_environment_doc(env_file)
        objects = dict(existing.get("objects", {}))
        previous = objects.get(observation_key, {})
        if not isinstance(previous, dict):
            previous = {}
        previous.update(
            {
                "type": "vision_observation",
                "robot_id": robot_id,
                "latest_frame_path": str(image_path),
                "captured_at": _utc_now(),
                "prompt": prompt,
                "model": model,
                "observation": observation,
            }
        )
        objects[observation_key] = previous
        updated = merge_environment_doc(existing, objects=objects, updated_at=_utc_now())
        save_environment_doc(env_file, updated)
