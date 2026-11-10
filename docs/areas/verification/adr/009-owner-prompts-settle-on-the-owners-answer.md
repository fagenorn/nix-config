# ADR-verification-009 — An owner prompt settles only on the owner's recorded answer or a final state

- **Status:** accepted
- **Decided in:** issue 631 D1-D6, D10

## Context

Some held checks need a person: a question (`ask`), an action (`act`), approval of a live or paid command, a decision about a failed or expired check, or a look at a host that went silent. A prompt that settled on anything but the owner's answer would let the runner decide for the owner, and a prompt posted twice would nag.

## Decision

Each prompt is an `owner-action` marker with check boxes, posted once per identity ever, ended prompts included (D1). Only the owner's recorded answer or a final state settles a prompt, and the outcomes, `rejected` included, are fixed (D6). An approve prompt is bound to its command by the `run` digest and consumed once, by the named host only, through a `verify-run consumed=<id>` marker; a changed command ends the prompt `changed` and asks again (D2, D3). Approval lifts only the effects gate (D4). The tick only permits a run: the runner still checks the digest on the named host. `act` is D10.

## Consequences

- An ended prompt is never posted again, so a changed command is a new identity that asks again.
- `verify-pending approve --repo OWNER/NAME --all-live` ticks only `live` prompts; a `paid` prompt is never bulk-approved.
- The sweep ends only the prompts the freshly read held block no longer needs, and a decision whose post was lost is posted by the next pass.
