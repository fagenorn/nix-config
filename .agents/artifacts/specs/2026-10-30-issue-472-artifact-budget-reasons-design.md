# artifact-budget refusals name their reason; over-budget results report limit and overage — issue 472

Design for https://github.com/fagenorn/nix-config/issues/472. Base: `8212d8fb`
(`origin/main`, the merge of #467). Approval source: autonomous (`--auto`), decision
ledger. A bare "Dn" cites this spec's ledger; "budget Dn" cites
`2026-08-19-artifact-budget-policy-design.md`, the design that set the current contract.

## Triage

```
Input: {"signals": {"contract_change": {"value": "hit", "evidence": "artifact-budget check's JSON result gains per-violation limit/overage data; python/agent_tools/review_budget.py pins the exact key set of that result"}, "concurrency_or_persistence": {"value": "no", "evidence": "stateless CLI validation and measurement; no locking or persisted state touched"}, "open_design_questions": {"value": "doubt", "evidence": "the field name and shape of the per-dimension limit/overage data and the stderr reason format are not fixed by the issue"}, "criteria_shape": {"value": "no", "evidence": "four acceptance criteria, each verified by a named test case or just agent-workflow-tests"}}, "paths": ["home/common/agent-skills/scripts/artifact_budget.py", "home/common/agent-skills/tests/test_artifact_budget.py", "python/agent_tools/review_budget.py", "tests/test_review_budget.py"]}
Verdict: {"hits":["contract_change","open_design_questions"],"lane":"full","mode":"shadow"}
ran: full (shadow)
```

The triage input names `tests/test_review_budget.py`, which does not exist. The
consumer seams this design actually uses are named under Test seams.

## Problem

An agent that hands `artifact-budget` a report or a detail input it refuses learns only
that it was refused. On base `8212d8fb`, a producer report whose `notes` run to 501
characters gives:

```
$ artifact-budget validate-report --boundary producer --input r.json
artifact-budget: invalid report            (exit 2)
```

The validator raised a specific `ArtifactBudgetError`, and the CLI caught it and wrote
the class line alone. That is true at all three refusal sites of `validate-report` and
`validate-detail-input`: a policy that fails to load or match, input that cannot be
read, and a parse or schema failure. Even where a reason was raised, several validators
raise one message for different failures. The producer validator, for one, says
`invalid producer report` both for a wrong key set and for over-long `notes`. In the
Oct 21–30 retro the bare line appeared 61 times. In three sessions an agent grepped the
helper's source in `/nix/store` to find out which member or bound had failed.

A measurement that comes back over budget names the dimension and nothing else:

```
$ artifact-budget check --kind handoff --root h.md --format json      (exit 3)
{"interface_version":1,"kind":"handoff","metrics":{"file_count":1,"largest_member_bytes":0,
 "root_bytes":8193,"total_bytes":8193},"status":"over_budget","violations":["root_bytes","aggregate_bytes"]}
```

The limit is not in the result, so the agent cannot tell how much to cut. One session
needed four trim-and-recheck rounds and a store grep to land under budget.

The issue asks for three things. Each refusal keeps its exit code and machine-readable
stdout and adds one human-readable reason naming the failing member or bound. An
over-budget result reports each violated dimension's limit and how far over it the
artifact is. Existing consumers of `violations` keep parsing it unchanged.

## Solution

Every refusal stays one stderr line and keeps its class. The line now ends in a reason:
`artifact-budget: <class>: <reason>` (D1). A single writer renders that reason from the
raised error. Wherever the failing rule has a member or a bound, the validators now
raise a message that names it (D2, D3). The v2 delivery boundaries surface the
delivery model's own cause (D4). Policy failures keep their class and also gain the
reason (D5).

`check` adds one member, `overages`, next to the unchanged `violations`. It is keyed by
violation code, and each entry carries the limit and the amount over it (D6). The
result's `interface_version` stays 1 (D7). The one strict consumer of the result, the
review budget authority, accepts and validates the new member in the same change (D8).
Relays that already drop `artifact-budget`'s stderr stay as they are, and so does the
helper's flat-script layout (D9). The changes are tested at the CLI seam and at the
existing consumer seams (D10). No skill text changes (D11).

## Decisions

### The refusal line (D1, D2, D5)

Every refusal from `validate-report` and `validate-detail-input` is still exactly one
line on stderr. Stdout stays empty and the exit code stays 2:

```
artifact-budget: <class>: <reason>\n
```

- `<class>` stays one of the five strings in use today: `invalid report`,
  `cannot read report`, `invalid detail input`, `cannot read detail input`, and
  `invalid input`. The last is the handler that `check`, `describe` and argument errors
  already use, and its format is unchanged. A consumer that matches a refusal matches
  this prefix and nothing more. This narrows budget D14's "one stable class diagnostic"
  to the stable prefix of a line that now continues.
- `<reason>` is written for a human, and its wording is not part of the contract. One
  writer renders every refusal line, those of `check` and `describe` included. It
  collapses the error message's whitespace onto one line, so the single-line guarantee
  holds whatever raised the error. Every `ArtifactBudgetError` raise carries a non-empty
  message.
- A reason names what failed in wire spelling. A member is named by its path, for
  example `notes`, `artifact.budget_status` or `findings[2].ruling`. A bound is named
  with its value and its unit, together with the measured value when there is one.
  Member names taken from the input, such as an unexpected key or a duplicate key, are
  quoted JSON-escaped. A reason never echoes a value from the report or the detail
  input (notes text, a path, a URL) and never echoes a path the CLI opened. Argument
  errors keep argparse's own message about the caller's argv. Callers relay this line
  into their own diagnostics (`ship-delivery`'s `exited N: <stderr>`,
  `orchestrate-control`'s 120-character stderr tail), and budget D6 keeps artifact
  contents out of those channels. A reason is not truncated. Only the input-supplied
  member names have no fixed length, and the input's wire bound already limits them.
- When an input fails more than one rule, the reason belongs to the first rule that
  fails, in the validator's fixed order. One input always gives the same line.
- A policy that cannot be read or parsed, or whose identity disagrees with
  `--expected-policy-sha256`, keeps the class it has today (`invalid report` or
  `invalid detail input`) and gains its reason, for example
  `policy identity disagreement`.

The reasons below illustrate the contract. Their wording is not normative:

| Failure | Line |
|---|---|
| Producer `notes` too long | `artifact-budget: invalid report: notes has 501 characters; the bound is 500` |
| Wrong key set | `artifact-budget: invalid report: producer report members: missing "notes"; unexpected "decisions"` |
| Artifact does not fit its state | `artifact-budget: invalid report: artifact.budget_status must be over_budget for state decompose_required` |
| Over the wire bound | `artifact-budget: invalid report: input exceeds the 8192-byte wire bound` |
| Duplicate key | `artifact-budget: invalid report: invalid JSON: duplicate key "state"` |
| Detail finding | `artifact-budget: invalid detail input: findings[0].ruling is required for a parked finding` |
| Symlinked input | `artifact-budget: cannot read report: Too many levels of symbolic links` |
| v2 boundary | `artifact-budget: invalid report: ship-handoff: acceptance_state does not pair with review_state` |

### Which messages are sharpened (D3, D4)

1. **Every refusal carries its reason.** This covers policy load and identity, input
   read, wire bound, JSON decoding, the canonical-output bound and schema validation.
   The three catch sites in the CLI that drop the error today go through the one writer.
2. **Conflated messages are split.** These checks are shared by every report boundary
   and by detail input:
   - **Required members.** One check compares a mapping with its closed key set and
     names the missing members and the unexpected ones, each list sorted. It replaces
     the bare key-set test at the top of each report validator and in detail input and
     its findings.
   - **Notes bound.** One check names `notes`, its length in characters and
     `notes_max_characters`. It replaces the boolean notes test in every report
     validator.
   - **Wire bounds.** The input bound and the canonical-output bound each name the
     byte bound they apply.
   - **JSON decoding.** `invalid JSON` is followed by the decoder's cause: a duplicate
     key (quoted), a non-standard constant, or the decode or UTF-8 error with its
     position and without its text.
   - **Input read.** A read failure gives the OS error string, and never the path.
   - **Detail findings.** A finding's reason is prefixed with its index, as in
     `findings[2].…`.
3. **The producer boundary names the failing artifact member.** Agents write producer
   reports by hand, so this is where precision pays. Its state check turns into a
   raising check. It names `state` when the value is outside the closed set, and names
   `artifact.kind` when the kind is not allowed for the state. Otherwise it names the
   member of the artifact that broke the state's shape: `kind`, `path`, `metrics`,
   `budget_status`, `violations`, or the key set for a root-only or null artifact.
4. **Other state matrices name their matrix.** The SDD, legacy ship-handoff,
   ship-summary and ledger-result validators keep the reason they raise today, such as
   `invalid SDD state`, once their key set and notes have passed. Each row is a
   conjunction across many members, so a reason per cell would mean rewriting every
   matrix. Agents do write some of these rows by hand, such as ship-issue's legacy
   `stopped` row, and the shared member and notes checks above already name the
   commonest mistakes in them.
5. **The v2 boundaries** are ship-handoff v2, ship-checkpoint, ship-summary v2 and
   workflow-response. Their reason is `<boundary>: <cause message>`, where the cause is
   whatever the wrapped validation raised: the delivery model's message, or one of
   `artifact-budget`'s own pairing or legacy-slot reasons. The delivery model's bare
   `invalid` rejections are not sharpened in this issue, so for those the line names
   only the boundary that refused.

### The over-budget data (D6, D7)

The result of `check` gains one top-level member. Every other member stays
byte-for-byte as it is:

```json
{"interface_version":1,"kind":"handoff","metrics":{"file_count":1,"largest_member_bytes":0,"root_bytes":8193,"total_bytes":8193},"overages":{"aggregate_bytes":{"limit":8192,"over_by":1},"root_bytes":{"limit":8192,"over_by":1}},"status":"over_budget","violations":["root_bytes","aggregate_bytes"]}
```

- `overages` is always present, as `{}` in a `within_budget` result, so the result keeps
  one fixed key set, as `violations: []` does today. Its keys are exactly the codes in
  `violations`. The order of the codes stays with `violations`, and the canonical
  output sorts the object's keys.
- Each entry is `{"limit": <int>, "over_by": <int>}`, where `over_by` is at least 1 and
  `limit + over_by` is the measured value. Each code is measured against one limit:

  | Code | Measured value | Limit |
  |---|---|---|
  | `root_bytes` | `metrics.root_bytes` | `root_max_bytes` |
  | `member_bytes` | `metrics.largest_member_bytes` | `member_max_bytes` |
  | `member_count` | `metrics.file_count − 1` | `max_members` |
  | `aggregate_bytes` | `metrics.total_bytes` | `aggregate_max_bytes` |

  `member_bytes` describes the largest member, the same quantity the violation is
  decided on. No entry is added per member: budget D1 and budget D6 keep the result's
  size independent of the package's shape.
- The checker holds this code-to-quantity-to-limit pairing in one table, and both
  `violations` and `overages` derive from it. The existing comparisons become rows of
  that table rather than a second copy of them.
- `interface_version` stays 1 (D7). Exit codes are unchanged: 0 within budget, 3 over
  budget, 2 for a failed measurement.
- Producer-report schemas do not change. A producer still quotes `violations` alone.
  `overages` is something the agent reads in order to trim, and it is not carried
  forward.

### The strict consumer (D8)

The review budget authority's `check` adds `overages` to the exact key set it pins. It
checks `overages` as strictly as the other members. The value must be an object whose
keys equal the set of `violations`. Each entry must have exactly `limit` and `over_by`,
both non-boolean integers, with `limit ≥ 0` and `over_by ≥ 1`. A result that breaks any
of these is refused as `invalid budget check`. The value it returns, `BudgetCheck`, is
unchanged, because no caller reads limits: review publication builds producer reports
from `violations` alone. Its `validate_report` and `validate_detail` already refuse on
any non-zero exit, and those paths are unchanged. The `workflow-state` durable-detail
check reads `kind` and `status` and ignores other members, so it needs no change. The
sdd-gate test shim, the only fake of the checker's wire form, adds `overages` in the
same change.

## Test seams

All of these are existing seams, extended (D10):

- **The CLI seam** in `test_artifact_budget.py`: the script runs as a subprocess
  through the suite's existing `run_validate` and `run_check` helpers.
  - Criterion 1. A new case sends a producer report whose `notes` are one character
    over the bound. It asserts exit 2 and empty stdout, and that stderr is one line that
    starts with `artifact-budget: invalid report: ` and contains `notes` and `500`.
    A second new case covers a key-set refusal, and asserts the unexpected member's name
    appears in the line.
  - Criterion 2. A new case sends detail input with a parked finding that has no
    ruling. It asserts the `invalid detail input: ` prefix and that the line contains
    `findings[0]` and `ruling`.
  - Criterion 3. A new case checks a handoff one byte over its bound and asserts the
    exact `overages` object above, with `violations` unchanged. The descriptor fixtures
    (`small-issue.json` and `oversized-issue.json`) add `overages` to every case's
    `expected`. The data-driven descriptor test then asserts it for each case, so every
    row of the table is pinned with values shaped like production: the fixtures' ninth
    plan member and oversized task member exercise `member_count` and `member_bytes`.
    The test that pins the result's key set adds `overages`.
  - Existing tests. The exact-stderr assertions (`b"artifact-budget: invalid report\n"`
    and its siblings) move to one shared refusal assertion: exit 2, empty stdout, one
    line, the exact class prefix and a non-empty reason. Their failure inputs do not
    change.
- **Consumer seams.**
  - The real checker's over-budget result already passes through the review budget
    authority when the review-package producer meets an oversized range. The sdd-gate
    `decompose_required` case and the review-feasibility full-range case cover this, so
    a consumer that refused `overages` would turn them red.
  - The sdd-gate budget-check case runs through the shim. It adds `overages`, and it
    now also asserts the over-budget refusal detail, `package is over_budget`. Without
    that assertion, a shim that drifted from the wire form would fail closed through the
    same gate and the case would stay green.
  - The installed-launcher test that asserts the
    `artifact-budget exited 2: artifact-budget: invalid report` substring keeps passing
    as written, because the class prefix is unchanged.
- **The suite** is criterion 4, `just agent-workflow-tests`. The plan names the
  focused tests to run first.

## Out of scope

- Sharpening the delivery model's bare `invalid` rejections, about 200 sites under a
  light-lane risk path (D4).
- Splitting the SDD, legacy ship-handoff, ship-summary and ledger-result state matrices
  into per-cell reasons (D3).
- Passing reasons through the wrappers that drop `artifact-budget`'s stderr:
  `workflow-state`'s validation helper, and the review budget authority's
  `validate_report` and `validate_detail` (D9).
- Changing exit codes, the stdout of a successful validation, the `describe` output,
  producer-report schemas or the policy file.
- Reasons for `check`'s package-shape errors, which already reach stderr through the
  `invalid input` handler.
- The review packer's own violation measurement and its retained replay outputs.
- Moving `artifact_budget.py` into the `agent_tools` package (D9).
- Skill and README text (D11).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Each refusal stays one stderr line, `artifact-budget: <class>: <reason>`. The class is one of today's five strings and is the only part a consumer may match. Exit code and empty stdout are unchanged. | Issue: keep exit code and stdout, add one reason. Budget D14's "one stable class diagnostic" survives as a stable prefix. The `invalid input: {exc}` handler already has this form, and so do the lifecycle guard's refusals (`lifecycle guard: unsafe push: …`), whose tests match only the prefix. Prefix-matching relays (`ship-delivery`, the launcher test) keep working. | A second stderr line or a JSON error object on stdout. Either breaks the one-line refusal and the empty refusal stdout that every caller depends on. |
| D2 | One writer renders every refusal. It collapses the reason onto one line. Reasons name members by wire path and bounds by value and unit. Input-supplied member names are quoted JSON-escaped. Values from the report or detail input, and paths the CLI opened, are never echoed. With several failures, the first rule in fixed validation order gives the reason. | The bar, "the log stream is the debugger": name the failing field. Budget D6 keeps artifact contents out of relayed channels. `orchestrate-control` and `ship-delivery` relay this stderr. | Write `str(exc)` as it comes, including raw `OSError` text and values. That can carry newlines, file paths or report text into relayed logs. |
| D3 | Every validate refusal carries its reason. Shared checks name the members (missing or unexpected), the notes bound, the wire bounds, the JSON cause, the read error and the finding index. The producer boundary names the failing artifact member for its state. The SDD, legacy ship-handoff, ship-summary and ledger matrices keep naming their matrix. | Issue demo: producer `notes` and its bound. Every artifact-producing skill writes a producer report by hand. The shared checks name the commonest hand-written faults on every boundary. The bar: YAGNI. | Break every state-matrix cell into its own reason. That rewrites every matrix validator, for a gain the shared checks mostly cover already. |
| D4 | The v2 boundaries raise `<boundary>: <cause>`. The delivery model's bare `invalid` rejections are left as they are. | `delivery_model/*` is a light-lane risk path with about 200 bare rejections. CLAUDE.md: delivery objects are built and never composed by hand. | Sharpen the delivery model's messages in this issue. That is a broad change under a risk path, for objects agents do not write. |
| D5 | Policy load and identity failures under the validate commands keep their current class and gain the reason. | Issue: every refusal keeps its exit code. This is the smallest change to the prefix consumers see. | Reclassify them as `invalid input`, as `check` does. The class would be more accurate, but it would change the prefix consumers see for the same failure. |
| D6 | `check` adds `overages`, keyed by violation code. Each entry is `{limit, over_by}` with `over_by ≥ 1`, and the keys equal `violations`. It is always present, `{}` within budget. Measured values: `member_bytes` uses the largest member, `member_count` uses `file_count − 1`. No per-member entries. One table derives both `violations` and `overages`. | Issue criterion 3. The result's fixed key set (`violations: []` is always present). Budget D1/D6: the result never grows with package shape. The bar: DRY, token economy. | Make `violations` entries objects, which breaks its consumers and the producer schemas. A parallel list, which repeats the codes and their order. Report only the limits record, which leaves the arithmetic to the agent. |
| D7 | `interface_version` stays 1. Every strict consumer is updated in the same change. | Check results are transient stdout and are never persisted raw. #467 pins one agent-tools build per system closure. | Bump to 2. No persisted or out-of-build reader needs to tell the versions apart, and reading both would be a YAGNI compatibility shim. |
| D8 | The review budget authority pins `overages` as strictly as its other members (exact keys, typed entries, keys equal to `violations`) and leaves it out of `BudgetCheck`. | The consumer already pins exact keys and the closed order. Review publication reads only `violations`. YAGNI. | Accept unknown members, which drops the wire-contract check. Carry `overages` in `BudgetCheck`, which has no reader. |
| D9 | Wrappers that drop `artifact-budget`'s stderr (`workflow-state`'s helper and the authority's validate calls) keep their messages, and `artifact_budget.py` stays a flat script. | The issue targets the helper's own refusals. `workflow-state.py` is a risk path. agent-helpers.md: a legacy script moves with its cluster. | Pass reasons through every wrapper, or move the script into the package now. Both widen the change to other surfaces and risk paths. |
| D10 | Tests live at the CLI seam. The new cases pin the exact class prefix, a single line, and the member and bound tokens, not the prose. Existing exact-stderr assertions become one shared refusal assertion. Descriptor fixtures add `overages`. The sdd-gate shim adds `overages`, and its case asserts the over-budget detail. | The bar, "tests that can fail". Prior art: the `run_validate`/`run_check` helpers and the executable descriptors (budget D13). agent-helpers rule 6 restricts phrase pins to skill text. | Pin whole reason strings, which ties tests to prose. Test the validators only in-process, which misses the CLI catch sites that dropped the reason. |
| D11 | No skill or README text changes. The check result describes itself, and this spec records the contract. | Instruction Budget is a required context on `main`. Brief scope boundary. | Add a one-line SKILL.md note telling producers to trim by `overages`. It costs instruction budget for something the JSON already shows. |
