# ADR-delivery-009 — A placed program set is never changed

- **Status:** accepted
- **Decided in:** issue 981

## Context

ADR-delivery-008 placed the delivery programs under one directory per checkout and replaced a file there when the installed program changed. Several sessions now launch batches from one checkout, and each places the programs before its launch. The Workflow runtime holds the batch program from its launch, but reads the child program from its path at every child launch (`workflow({scriptPath})` loads the file per call; issue 912 saw a child fail to load mid-batch for the same reason). A placement after a host switch therefore gave a running batch, still the old `deliver-batch.js`, children from the new `deliver-standard.js`. Six switches happened on one day while batches ran.

## Decision

- `program-copies` places the programs in `<checkout>/.program-copies/<skill dir name>/<set>/`, where `<set>` is 12 hex digits of a hash over every program's name and bytes, and prints those paths in the same JSON as before.
- A set that exists is never written to. Placing the same programs writes no file, prints the same paths and stamps the set directory's modification time as its last use.
- A lead takes `scriptPath` and `child_script` from one output, so both lie in one set. The batch launches every child from the `child_script` it was given, as it already did.
- After a placement, a set last used more than 24 hours ago is removed. The set just placed is never removed.
- A relaunch is a new run and starts from fresh copies, `child_script` included.

## Considered options

- **Keep the newest few sets.** Rejected: the count that is safe depends on how many switches fall inside one batch, and six in a day has happened; a last-use age needs no such guess, since a batch runs about four hours and stamps its set at launch.
- **Age by creation time.** Rejected: a set created days ago can be the one a batch launched from a minute ago.
- **The batch derives the child path from its own location.** Rejected: `child_script` already carries the path, and the relaunch args name it in any case.
- **No pruning.** Rejected: ADR-delivery-008 refused per-run copies for growing without bound.

## Consequences

- The sets kept in a checkout are bounded by the program versions placed there within a day.
- A batch that outlives 24 hours with no placement of its version in that time can lose its child program; its row then names the load failure and the path.
- The `*.js` files the earlier layout placed directly in `<skill dir name>/` are no longer written or removed: a batch launched from them before this change keeps both programs unchanged, and the files stay until deleted by hand.
- This replaces the ADR-delivery-008 consequence that a running batch reads the newer child.
