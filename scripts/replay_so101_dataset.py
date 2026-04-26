"""Replay a recorded LeRobot dataset directly through PhyAgentOS's SO-101 HAL driver.

Bypasses solo-cli/lerobot's record/replay flow — drives the follower arm via
the same HAL driver brain agents would use, validating that recorded motion
plays back faithfully through the PhyAgentOS stack.

Usage:
    python scripts/replay_so101_dataset.py \
        --port /dev/tty.usbmodem5B3E1216631 \
        --dataset /Users/test/.cache/huggingface/lerobot/pilarclark/s0101-pharmacy1 \
        --episode 0
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hal.drivers.so101_driver import JOINT_NAMES, SO101Driver


def linear_interpolate(start: list[float], end: list[float], steps: int) -> list[list[float]]:
    return [
        [s + (e - s) * (i + 1) / steps for s, e in zip(start, end)]
        for i in range(steps)
    ]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", required=True)
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--episode", type=int, default=0)
    p.add_argument("--ramp-seconds", type=float, default=1.0,
                   help="Smoothly interpolate from current pose to first frame")
    args = p.parse_args()

    df = pd.read_parquet(args.dataset / "data" / "chunk-000" / "file-000.parquet")
    ep = df[df["episode_index"] == args.episode].sort_values("frame_index")
    if ep.empty:
        print(f"episode {args.episode} not found")
        return 2

    actions = [list(map(float, a)) for a in ep["action"].to_numpy()]
    fps = 30
    period = 1.0 / fps
    print(f"replaying episode {args.episode}: {len(actions)} frames at {fps} fps "
          f"({len(actions) / fps:.1f}s)")

    d = SO101Driver(port=args.port, mock=False)
    try:
        current = list(d._joint_angles)
        print("current:", dict(zip(JOINT_NAMES, [f"{v:+.2f}" for v in current])))
        print("frame[0]:", dict(zip(JOINT_NAMES, [f"{v:+.2f}" for v in actions[0]])))

        ramp_steps = max(1, int(args.ramp_seconds * fps))
        print(f"ramping in over {ramp_steps} frames...")
        for target in linear_interpolate(current, actions[0], ramp_steps):
            d.execute_action("move_to_joints", {"joints": target})
            time.sleep(period)

        print("playing back recorded trajectory...")
        t_start = time.monotonic()
        for i, target in enumerate(actions):
            d.execute_action("move_to_joints", {"joints": target})
            next_t = t_start + (i + 1) * period
            sleep = next_t - time.monotonic()
            if sleep > 0:
                time.sleep(sleep)
        elapsed = time.monotonic() - t_start
        print(f"done in {elapsed:.2f}s ({len(actions) / elapsed:.1f} fps actual)")

        final = d.get_runtime_state()["robots"]["so101_001"]["arm"]["joint_angles_rad"]
        print("final:", dict(zip(JOINT_NAMES, [f"{v:+.2f}" for v in final])))
    finally:
        d.close()
        print("disconnected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
