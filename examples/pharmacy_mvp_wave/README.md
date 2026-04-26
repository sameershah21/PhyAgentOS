# Pharmacy MVP: Verified Greeting Wave

This example replaces the high-risk "SO-101 picks bottle" milestone with a
gesture-only milestone:

> Customer arrives -> Reachy greets -> mock identity is verified -> SO-101 waves
> to acknowledge successful verification -> Reachy announces completion.

The demo proves the full PhyAgentOS state/action chain without requiring object
detection, grasp calibration, bottle physics, or medication handling.

## Bodies

- `reachy_frontdesk`: greets, explains, and announces workflow state.
- `identity_checker`: mock state transition into `IDENTITY.md`.
- `so101_counter_arm`: performs a visible gesture only after identity passes.

## Safety Story

SO-101 is not allowed to wave until:

- `IDENTITY.status == verified_mock`
- `IDENTITY.age_verified == true`
- `ENVIRONMENT.objects.pharmacy_demo.workspace_clear == true`
- `ENVIRONMENT.objects.pharmacy_demo.human_hand_in_workspace == false`
- `ENVIRONMENT.objects.so101_counter_arm.emergency_stop == false`

The first implementation uses `backend: "dry_run"` for SO-101, so it validates
the gate and updates state before real arm motion is wired in.

## Run Shape

Create the runtime copy under `/tmp` so the example config paths resolve:

```bash
rm -rf /tmp/pharmacy_mvp_wave
cp -R examples/pharmacy_mvp_wave /tmp/pharmacy_mvp_wave
```

Start one watchdog for each physical body:

```bash
PYTHONPATH=. .venv-reachy-mini/bin/python hal/hal_watchdog.py \
  --robot-id reachy_frontdesk \
  --config /tmp/pharmacy_mvp_wave/config.json \
  --driver-config /tmp/pharmacy_mvp_wave/reachy_frontdesk_driver.json \
  --interval 0.5
```

```bash
PYTHONPATH=. .venv-reachy-mini/bin/python hal/hal_watchdog.py \
  --robot-id so101_counter_arm \
  --config /tmp/pharmacy_mvp_wave/config.json \
  --driver-config /tmp/pharmacy_mvp_wave/so101_counter_arm_driver.json \
  --interval 0.5
```

Then run the agent in fleet mode with the shared workspace/config.

```bash
PYTHONPATH=. .venv-reachy-mini/bin/paos agent \
  --config /tmp/pharmacy_mvp_wave/config.json \
  --workspace /tmp/pharmacy_mvp_wave/workspaces/shared \
  --message "Run the verified greeting wave MVP. Greet the customer, verify the mock ID for P-1042, only then have SO-101 wave, wait for completion, and have Reachy announce completion." \
  --no-markdown --logs
```
