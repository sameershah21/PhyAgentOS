#!/usr/bin/env python3
"""Low-amplitude smoke test for the PhyAgentOS Reachy Mini HAL driver.

Run from the repo root with a Python environment that has `reachy-mini`
installed:

    PYTHONPATH=. python scripts/reachy_mini_smoke_test.py

The script tries to connect to an existing daemon first. If that fails and
`--spawn-daemon` is passed, it asks the SDK to start a daemon and retries.
Motions are intentionally small.
"""

from __future__ import annotations

import argparse
import socket
import sys
import time
from pathlib import Path

from hal.drivers.reachy_mini_driver import ReachyMiniDriver


HEAD_AMPL_DEG = 8.0
BODY_AMPL_DEG = 8.0
ANTENNA_AMPL_DEG = 10.0
DURATION_S = 2.0
SETTLE_S = 0.5


def _wait_for_port(host: str, port: int, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _connect(args: argparse.Namespace) -> ReachyMiniDriver:
    driver = ReachyMiniDriver(
        host=args.host,
        port=args.port,
        connection_mode=args.connection_mode,
        timeout=args.timeout,
        spawn_daemon=False,
        media_backend=args.media_backend,
    )
    if driver.connect():
        print("connected to existing Reachy Mini daemon", flush=True)
        return driver

    if not args.spawn_daemon:
        raise RuntimeError(driver._connection_error())

    print("existing daemon unavailable; trying SDK daemon spawn", flush=True)
    spawner = ReachyMiniDriver(
        host=args.host,
        port=args.port,
        connection_mode=args.connection_mode,
        timeout=args.timeout,
        spawn_daemon=True,
        use_sim=args.use_sim,
        media_backend=args.media_backend,
    )
    try:
        spawner.connect()
        return spawner
    except Exception:
        spawner.disconnect()

    if not _wait_for_port("127.0.0.1", args.port, timeout_s=60.0):
        raise RuntimeError(f"daemon did not become ready on port {args.port}")

    retry = ReachyMiniDriver(
        host=args.host,
        port=args.port,
        connection_mode=args.connection_mode,
        timeout=10.0,
        spawn_daemon=False,
        media_backend=args.media_backend,
    )
    if not retry.connect():
        raise RuntimeError(retry._connection_error())
    return retry


def _run(args: argparse.Namespace) -> int:
    driver = _connect(args)
    frame_path = Path(args.frame_output).expanduser().resolve()
    try:
        for action_type, params in [
            ("get_state", {}),
            ("set_head_pose", {"pitch": HEAD_AMPL_DEG, "degrees": True}),
            ("set_head_pose", {"pitch": 0.0, "degrees": True}),
            ("set_body_yaw", {"body_yaw": BODY_AMPL_DEG, "degrees": True, "duration_s": DURATION_S}),
            ("set_body_yaw", {"body_yaw": 0.0, "degrees": True, "duration_s": DURATION_S}),
            (
                "set_antennas",
                {
                    "left": ANTENNA_AMPL_DEG,
                    "right": -ANTENNA_AMPL_DEG,
                    "degrees": True,
                    "duration_s": DURATION_S,
                },
            ),
            ("set_antennas", {"left": 0.0, "right": 0.0, "degrees": True, "duration_s": DURATION_S}),
        ]:
            print(f"{action_type}: {params}", flush=True)
            result = driver.execute_action(action_type, params)
            print(result, flush=True)
            if result.startswith("Error:"):
                return 1
            time.sleep(SETTLE_S)

        print(f"capture_frame: {frame_path}", flush=True)
        result = driver.execute_action("capture_frame", {"output_path": str(frame_path)})
        print(result, flush=True)
        return 0 if not result.startswith("Error:") else 1
    finally:
        driver.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(description="Reachy Mini HAL smoke test")
    parser.add_argument("--host", default="reachy-mini.local")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--connection-mode", default="auto", choices=["auto", "localhost_only", "network"])
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--media-backend", default="default")
    parser.add_argument("--spawn-daemon", action="store_true")
    parser.add_argument("--use-sim", action="store_true")
    parser.add_argument("--frame-output", default="/tmp/reachy_mini_smoke_frame.npy")
    return _run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
