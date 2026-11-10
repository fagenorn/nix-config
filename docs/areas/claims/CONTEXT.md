---
area: Claims
budget: 200 lines
---

# Claims

Claims keeps concurrent deliveries from colliding. It holds the race-safe state written as comments on forge issues: who is delivering an issue, who may land, what the owner is asked, and which issues block which.

## Language

**Blocking edge**:
A recorded dependency between two issues, stored through the forge's native dependency endpoints instead of prose. An issue with an open blocker is not grabbable.
_Avoid_: dependency note

**Claim**:
A marker saying one holder is delivering one issue on one branch. It stays live while the holder renews it and ends when released or landed.
_Avoid_: lock, reservation

**Decision prompt**:
An owner-action marker that carries questions a batch needs the owner to answer, each with tick boxes. A fully ticked prompt waits for a run to read it.

**Land lock**:
The single claim-like lease a delivery must hold to merge into the integration branch, so that two deliveries do not land at once. It is acquired with a wait and released after the merge.
_Avoid_: merge lock

**Marker**:
Race-safe machine state held in an issue comment whose first line is an HTML comment naming an `agent:` kind and its key-value fields. Among live markers of one kind the smallest comment id wins.
_Avoid_: bot comment

**Owner-action marker**:
A marker that asks the owner to do something and carries a reason and tick boxes. The owner answers by ticking, and the next call honours the tick.
_Avoid_: owner ask

**Stale claim**:
A claim whose holder stopped renewing it. It is never taken over: the status call posts an owner-action marker asking the owner to release it.
_Avoid_: dead claim
