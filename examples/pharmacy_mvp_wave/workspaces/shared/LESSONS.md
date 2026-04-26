# LESSONS

## Lesson: Identity should gate physical movement

Failure:
SO-101 was able to wave before mock identity verification completed.

Correction:
The `wave` action now requires:

- `IDENTITY.status == verified_mock`
- `IDENTITY.age_verified == true`

Applies To:

- SO-101 wave
- all future physical arm actions

---

## Lesson: Keep first arm gesture small

Failure:
The initial wave gesture moved too close to the customer side of the counter.

Correction:
Use a smaller joint-space wave inside the calibrated safe workspace.

Applies To:

- `wave`
- `acknowledge`
