# Shadow lane triage after investigation — design (issue #279)

Slice 1 of the light-lane parent design,
`2026-10-06-light-lane-budgets-design.md`. Parent D1–D4, D7, D13 and D16 bind
this slice and are cited, not restated. Rows below are this slice's own; "parent
Dn" names a parent row.

## Problem

`from-issue` cannot take a cheaper route until there is evidence that the
triage rule picks the right lane. That evidence needs three things. A project
must be able to say whether it has a light lane at all. A deterministic
evaluator must turn an owner's per-signal judgment into a lane (parent D3, D4).
And every Phase 0 must leave a record that a later replay can score. None of
these exists, so the triage decision that the parent design rests on can be
neither made nor measured. In this slice the verdict is observed and never
acted on: every attempt still runs the full pipeline.

## Solution

1. `resolve-project` accepts an optional `bindings.workflow.light_lane` member
   with the closed shape of parent D13. Absent or `null` means the light lane is
   unsupported (D2).
2. A new package command, `lane-triage evaluate --repo-root <root> --input -`,
   validates a closed triage record. It reads `light_lane` through one new public
   resolver function (D1), derives `risk_path` from the authored globs (D4), and
   prints the verdict without writing anything (D5).
3. A triage step closes Phase 0 of `from-issue`. The owner judges each signal,
   runs `lane-triage`, and puts the record and verdict in the investigation note.
   The spec's `## Triage` section then commits them. Every attempt runs full (D6,
   D7).

## Decisions

**Resolver API.** `agent_tools.resolve_project` gains one public function,
`resolve(repo_root, required=None) -> dict`. It returns the `ResolvedProject`
snapshot or raises `ContractError`, and it is exactly the composition that
`command_resolve` runs today: manifest gate, root discovery, load, full
validation, platform range, projection drift, snapshot, and the required
capabilities check. It returns the snapshot only when that snapshot serializes as
standards JSON: a number that overflows to a non-finite float (`1e400` never
reaches `parse_constant`) raises the fixed `resolver_failure` /
`resolver.internal` refusal that the command's emit guard already printed, so
the API never hands a caller a project the command refuses (final-review
COR-002). `command_resolve` becomes `emit_json(resolve(...))`, and its
stdout stays byte-identical. `conformance_checks` keeps its own composition,
because it adds de-duplication and violation collection that `resolve` must not
take on.

**Policy member.** `validate_workflow` still requires its four current members.
It also accepts `light_lane` as the one optional member. Any other member is
still `member_unexpected`. A non-null `light_lane` must be an object with
exactly these members:

- `mode` must be `shadow` or `active`.
- `budget_minutes` must pass `check_positive_int`, so it is rejected if it is a
  boolean, zero or negative.
- `risk_paths` is a list, possibly empty. Each entry is a glob that satisfies the
  resolver's safe-relative-path rule: non-empty, not absolute, and with no `..`
  segment.

Violations use the existing `contract.workflow.*` repair-id kinds. A bad `mode`
gets the new kind `contract.workflow.light_lane_mode`. `normalize_bindings`
passes the member through as authored: an absent member stays absent, and
`null` stays `null`. The snapshot never adds a member the author did not write.
The platform manifest and `project_schema_versions` are unchanged (D2).

**`lane-triage` input.** The input is a strict JSON load from stdin, using
`canonical.reject_duplicate_keys` and `reject_nonfinite_literal` (agent-helpers
rule 4). It is a closed object:

```json
{"signals": {"contract_change": {"value": "no", "evidence": "..."},
             "concurrency_or_persistence": {...}, "open_design_questions": {...},
             "criteria_shape": {...}},
 "paths": ["python/agent_tools/x.py"]}
```

- Each `value` is one of `no`, `hit` or `doubt`.
- Each `evidence` is a non-empty string with no line break.
- `paths` is a non-empty list of safe relative paths (D4), each spelled
  canonically: `/`-separated, with no backslash, no empty or `.` segment and no
  trailing `/`, so `./a.py`, `a//b.py` and `a/` are refused at `/paths/<index>`
  (D11).
- Every object is closed. A missing or extra member is refused.

**`lane-triage` behavior and output.** The command calls
`resolve_project.resolve(repo_root)` and reads
`bindings.workflow.light_lane`. When that member is absent or `null`, the
command refuses with `light_lane_unsupported`. Otherwise it computes these
values:

- `risk_path` is a hit when any input path matches any `risk_paths` glob under
  `fnmatch.fnmatchcase`.
- `hits` lists the names of the signals whose `value` is not `no`, in the fixed
  order `contract_change`, `concurrency_or_persistence`,
  `open_design_questions`, `criteria_shape`, `risk_path`.
- `lane` is `light` exactly when `hits` is empty, and `full` otherwise. This is
  the rule of parent D3.

It prints one compact, sorted JSON line, `{"hits":[...],"lane":...,"mode":...}`,
and exits 0. `mode` is echoed as authored. The command never rewrites `lane`
for shadow mode; the caller decides what to do with the verdict (D7).

**Refusals.** Every refusal exits 2 with empty stdout and one JSON line on
stderr, `{"error":{"code":...,"detail":...}}`. The codes form a closed set:

| Code | When | `detail` |
|------|------|----------|
| `invalid_input` | The record fails the input shape | The first violation's pointer and message |
| `resolver_refused` | `resolve` raised `ContractError` | The resolver's error object, unchanged |
| `light_lane_unsupported` | The member is absent or `null` | `null` |

argparse usage errors also exit 2. The command writes no file. It holds its
input, compute and emit steps in importable functions, and its `main` is a thin
shell (agent-helpers rule 2). Its command-table row is `lane-triage`.

**`from-issue` Phase 0.** Phase 0 gains a **Lane triage** step after the
investigation and before the checkpoint. That step sits in `SKILL.md`, which
already declares `bindings.workflow`, so no other file needs a new binding
declaration. The step runs in this order:

1. The owner judges each parent D2 signal, using parent D7 for
   `criteria_shape`, and writes one line of evidence for each. It lists the
   paths it predicts the change will touch.
2. It feeds that record to `lane-triage evaluate --repo-root <project.root>`
   on stdin through a quoted heredoc. No input file is written.
3. It handles the exit code:
   - With exit 0, it records the record, the verdict and
     `ran: full (shadow)` in the investigation note, under a new **Lane
     triage** note field that `investigate.md` lists.
   - With `light_lane_unsupported`, it skips triage and records "light lane
     unsupported".
   - With any other refusal, it treats the result as a resolver or input error
     and fixes the record, or stops through the terminal return procedure.
4. Phase 2 copies the record and verdict verbatim into the spec as a
   `## Triage` section, and that commit is what makes them durable. In
   `--auto`, the record travels inside the Phase-0 issue summary that
   `AUTO.md`'s design dispatch already carries. Its bullet names the record
   explicitly, so the design subagent can write the section.

`CLAUDE.md`'s "Agent helper package" paragraph names `lane-triage`, its
read-only verdict and the public `resolve` seam. This is the same commit
obligation as for every other package command.

Interactive mode shows the verdict at the Phase-0 checkpoint as information
only, because there is no lane to choose in this slice.

## Test seams

All of these are existing seams under `just agent-workflow-tests`. Nothing new
is invented.

- **`test_resolve_project.py`**, through the subprocess `resolve` on a temporary
  root.
  - A valid `light_lane` round-trips unchanged.
  - An absent member stays absent and `null` stays `null`.
  - An unknown key, a bad `mode`, a `budget_minutes` that is zero, negative or
    boolean, and an unsafe glob are each refused with their pointer.
- **New `tests/test_lane_triage.py`**, driving `python -m agent_tools.lane_triage`
  against a fixture project under a temporary `HOME` holding the committed
  platform manifest (agent-helpers rule 5). The fixture is built locally from
  the eval fixture repo and does not import across test directories. The file
  is added to the recipe's list.
  - An all-`no` record gives `light`.
  - Each single `hit` or `doubt` gives `full`, with that signal named in `hits`.
  - A path matching a glob adds `risk_path`.
  - An absent or `null` member, and also a malformed contract, exit 2 with
    their codes and empty stdout.
  - An invalid record exits 2 with `invalid_input`.
  - The run leaves the tree unchanged.
- **`tests/test_agent_tools_launchers.py`**: the command list gains
  `lane-triage`.
- **`test_workflow_skill_contracts.py`**: the `from-issue` Phase 0 section
  names `lane-triage evaluate`, the triage record, the shadow rule that every
  attempt runs full, and the unsupported skip. Phase 2 names the `## Triage`
  section.

## Out of scope

- Authoring `light_lane` in this repo's `.agents/project.json` (D3). The D16
  seed for that follow-up is the list `home/common/claude-code/lifecycle_guard.py`,
  `home/common/claude-code/default.nix`, `home/common/agent-skills/scripts/workflow*`,
  `python/agent_tools/transaction_*.py`, `python/agent_tools/resolve_project.py`,
  `python/agent_tools/agent_platform.py`, `home/common/agent-skills/platform-manifest.json`,
  `.agents/project.json`.
- The ledger and the `declare-lane` command (slice 2), the light route,
  escalation and the actual-diff re-check (slice 4), lane budgets and
  `blocked_on=deadline` (slices 2–3), replay (slice 5), and enablement (slice 6).
- Making `light_lane` a capability, and migrating `conformance_checks` onto
  `resolve`.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | `lane-triage` reads policy through a new public `resolve_project.resolve(repo_root, required=None)`, which is `command_resolve`'s exact composition, so a malformed contract is `resolver_refused` and never "unsupported" | The Bar: DRY; agent-helpers rules 2–3; parent D4 settles the `--repo-root` interface. Re-resolving inside the command is a validated read that persists nothing, so it keeps bootstrap's "never persist a snapshot", following the `build-delivery` precedent | Re-composing the internals in `lane_triage` (as `conformance_checks` does) would give a second composition home that drifts. A subprocess to `resolve-project` would mean parsing the same snapshot across a process for no isolation gain |
| D2 | `light_lane` is the one optional `workflow` member, passed through as authored (absent stays absent), with no schema bump and no new capability | Bootstrap "no project policy is defaulted" and "returned exactly as authored"; parent D13; the manifest gates schema, not members | A required-nullable member like `release` would break every onboarded contract and need a migration. Resolver-inserted `null` would be resolver-authored policy. A new capability would change the closed capability table and every contract's `capabilities` block |
| D3 | This slice does **not** author `light_lane` in `.agents/project.json`. The demo is proven on the fixture project, and authoring is a follow-up merged after this resolver is switched in | `workflow-state build-delivery` resolves the worktree through the installed `~/.agents/bin/resolve-project`, which predates this slice and rejects `light_lane` as `member_unexpected`. That would refuse this very delivery, and after merge main would be unresolvable on any host that has not switched, including the concurrent orchestrated runs. The sealed-policy comparison itself would not refuse, because `workflow` is unsealed | Authoring it now: the demo would be real, but delivery and every concurrent run would break until the switch |
| D4 | `risk_paths` globs match with `fnmatch.fnmatchcase` against the POSIX path string, so `*` also crosses `/`. Globs and input paths reuse the resolver's safe-relative rule. The `risk_paths` list may be empty, while `paths` must be non-empty | Parent D3: when in doubt, `full`, so over-matching errs safe. Python 3.13 is the runtime, but `fnmatch` does not depend on the version | `PurePosixPath.full_match` with `**`: stricter, so a near-miss glob would silently under-match. Allowing empty `paths` would let a `light` verdict skip the risk check vacuously |
| D5 | The output is closed to `{hits, lane, mode}`, with `hits` in fixed signal order and no distinction between hit and doubt. Every refusal exits 2 with empty stdout and one stderr error line from the closed code set | Parent spec output shape; the `build-delivery` refusal convention (exit 2, empty stdout, the resolver document unchanged on stderr); The Bar: Fail loud | Matched globs or hit/doubt in the output: the record already holds that, and no consumer exists (YAGNI). Exit 0 for unsupported: callers would have to parse the output to know whether to skip triage |
| D6 | The triage step lives in `SKILL.md` Phase 0. `investigate.md` only gains the **Lane triage** note field, which names no binding. Phase 2 copies the record into the spec's `## Triage` section, which is the committed home | `SKILL.md` already declares `bindings.workflow` (a skill-contract table); Phase 0 writes no files; in `--auto` only the Phase-0 summary reaches the design subagent (`AUTO.md`); the parent D5 light note also has a Triage section | Putting the step in `investigate.md` would widen its binding declaration. A separate triage file would be a second record next to the spec |
| D7 | In this slice every attempt runs full, whatever `mode` is: shadow by design, and an `active` verdict is recorded with `ran: full (active route not yet available)` until slice 4 adds the route | Parent slice 1 ("the lane is always run as full"); The Bar: Truthful terminal states | Refusing `active` in the resolver: the parent D13 shape accepts it, and slice 6 sets it. Taking a light route now: that route does not exist yet |
| D8 | `lane-triage evaluate` reads stdin whole, then resolves (`resolver_refused`), then checks support (`light_lane_unsupported`), and only then validates the record (`invalid_input`), stopping at the first violation in a fixed walk: top-level members, then `signals` in signal order, then `paths`. `--input` accepts only `-`. `resolve(repo_root: str \| None, required: list[str] \| None = None)` keeps `--repo-root`'s optional discovery | The unsupported skip must not depend on record quality, since Phase 0 skips triage there anyway; spec "no input file is written"; The Bar: Fail loud, one error per refusal | Validating the record first: an unsupported project would make the owner fix a record it then discards. Accepting a file path: a second input route nothing uses (YAGNI) |
| D9 | `from-issue` names the call only as the inline span `lane-triage evaluate --repo-root <project.root> --input -` and describes the heredoc in prose. No shell fence, no `COMMAND_VOCABULARY` entry and no permission allowlist change | `test_shell_example_contracts.py` refuses a heredoc example unless its helper is allowlisted whole in `home/common/claude-code/default.nix`, and the allowlist is out of scope; precedent: `verified-tree` and `launch-scope` are not in the vocabulary either | A heredoc fence: the shell-example contract refuses it. Allowlisting `lane-triage`: it widens the guard's permission surface in a slice that only observes |
| D10 | Phase-5 review edits: `from-issue` names `lane-triage evaluate` beside `build-delivery` as a helper that resolves on its own; the Phase-0 paragraph sends any non-zero exit outside the closed refusal set (traceback, missing command) to the terminal return procedure; the final gate also runs `just agent-installed-skill-tests` | Plan reviewer (Claude fallback): SKILL.md's "only sanctioned exception" sentence would become false; skill text must cover every exit; `LAUNCHER_FLOOR` is otherwise never exercised | Leave the sentence (stale prose pinned by a test); map every resolver fault to a refusal code inside lane-triage (hides internal faults behind a closed code) |
| D11 | `validate_record` refuses a non-canonical `paths` entry (a backslash, an empty or `.` segment, a trailing `/`) as `invalid_input` at `/paths/<index>`, inside D8's fixed walk; `evaluate` matches the recorded string unchanged | Final-review correctness finding COR-001: the safe-relative rule admits `./tinytask/store.py` and `tinytask//store.py`, and `fnmatchcase` on the raw string misses the `risk_paths` glob, so an all-`no` record naming a risky file came back `light` | Normalizing paths before matching: it hides the record's error and diverges from the predicted-path list the owner records |
