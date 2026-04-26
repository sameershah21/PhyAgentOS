# SKILL: Verified Greeting Wave

## Successful Workflow

1. Reachy greets the customer.
2. Reachy asks for a mock ID.
3. Identity checker verifies synthetic patient profile and age requirement.
4. If verification passes, SO-101 performs a friendly wave.
5. Reachy announces that the verified demo workflow is complete.

## Preconditions

- The customer is using a synthetic demo ID.
- No real government ID is scanned.
- Workspace around SO-101 is clear.
- Emergency stop is not active.
- SO-101 wave trajectory has been tested.

## Safety Rules

- SO-101 cannot wave until `IDENTITY.status == verified_mock`.
- SO-101 cannot move if `ENVIRONMENT.objects.pharmacy_demo.workspace_clear == false`.
- Reachy cannot announce completion until `ENVIRONMENT.objects.so101_counter_arm.wave_completed == true`.
