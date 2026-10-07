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
4. No instruction-load ceiling is raised: the added skill text is paid for by
   compressing it and cutting existing always-loaded text, so the PR passes the
   `Instruction Budget` check without the `instruction-budget-raise` label
   (D12–D15).

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
  segment. It must also be spelled canonically, by the same
  `resolve_project.is_canonical_path` rule `lane-triage` applies to record
  paths: no backslash, no empty or `.` segment, and no trailing `/` (D18).

Violations use the existing `contract.workflow.*` repair-id kinds. A bad `mode`
gets the new kind `contract.workflow.light_lane_mode`, and a safe but
non-canonical `risk_paths` entry gets the new kind
`contract.workflow.noncanonical_path`. `normalize_bindings`
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
2. It feeds that record to `lane-triage evaluate --repo-root <project.root>
   --input -` on stdin through a quoted heredoc. No input file is written.
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

The checkpoint gains no sentence: the posted note already shows the verdict,
and there is no lane to choose in this slice (D12).

## Instruction budget

The user decided on 2026-10-07 that no ceiling is raised. The branch therefore
drops ec089c67, and `home/common/agent-skills/instruction-load.json` ends
byte-identical to `origin/main`'s (D15). The corpus counts every skill file, so
moving text between skill files never pays for it; only a net cut does. The
binding constraint is therefore: the summed byte delta of `from-issue/SKILL.md`,
`AUTO.md` and `investigate.md` against `origin/main` is at most 0, with every cut
made in `SKILL.md` or `AUTO.md`, which are hot in all three affected profiles.
That one inequality clears the corpus and every hot profile at once (D12).

The budget is met in two moves, both measured in a scratch probe (net −38
bytes, `instruction_load check --base origin/main` passing on `origin/main`'s
model):

1. **Compress the additions** (about −1,000 bytes against ec089c67's text):
   the **Lane triage** paragraph keeps every rule — the four signal names with
   one-line meanings, the record shape, the inline `lane-triage evaluate` span,
   the quoted heredoc and no input file, the `ran:` lines for shadow and
   active, "every attempt runs full", the unsupported skip, and the exits
   routed to the terminal return procedure — but drops restated prose. The
   resolve-exception clause is appended inside the existing sentence, which
   keeps the four-file pinned clause "only sanctioned exception is
   `workflow-state build-delivery`, which performs its own sealed, read-only
   resolution" verbatim. Phase 2, the `AUTO.md` bullet and the
   `investigate.md` field shrink to one short clause each, and the checkpoint
   sentence is dropped.
2. **Cut existing text** (about −1,400 bytes): `SKILL.md`'s deadline-rejected
   `progress` paragraph loses its expiry rationale (wall-clock expiry, the
   unconsulted `last_progress_at`, consuming no attempt and the reserved fresh
   retry), which restates the suspension procedure and the reaper, and its
   remaining rule is rewritten tighter (D13). The rewrite keeps both helper
   rejection strings, the suspension route, the no-`finish` rule, the
   `stopped(stalled)` outcome, and the progress-marker test's anchor
   "without a phase advance or a newly recorded progress marker" verbatim.

The gate is the required `Instruction Budget` CI check on the PR. Its local
proxy is `PYTHONPATH=python python3 -m agent_tools.instruction_load check --base
origin/main`, which must exit 0 after the final merge of `origin/main`. If main
grows `from-issue` text under its own raise before shipping, that changes
nothing here, because main's raise brings its text with it.

## Test seams

All of these are existing seams under `just agent-workflow-tests`. Nothing new
is invented.

- **`test_resolve_project.py`**, through the subprocess `resolve` on a temporary
  root.
  - A valid `light_lane` round-trips unchanged.
  - An absent member stays absent and `null` stays `null`.
  - An unknown key, a bad `mode`, a `budget_minutes` that is zero, negative or
    boolean, an unsafe glob, and a non-canonical glob (`./a.py`, `a//b.py`,
    `a/`, a backslash) are each refused with their pointer, while canonical
    glob patterns such as `src/**/*.py` and `*.nix` are accepted.
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
- **`test_workflow_skill_contracts.py`** gains one lane-triage test,
  `LaneTriageRecordKeysTest`, a key-set test that keeps AC4 measured (D16).
  The branch's `LaneTriageContractsTest` is deleted, because all five of its
  tests, the `CLAUDE.md` one included, pin English phrases. The two
  existing expiry phrase-pin tests,
  `test_expiry_prose_describes_the_wall_clock_the_reaper_actually_reads` and
  `test_from_issue_routes_a_deadline_rejected_progress_to_the_suspension_procedure`,
  are deleted together with the prose they pin (D14). The skill text is then
  guarded by `test_lane_triage.py` for behavior and by the instruction-budget
  check for size.

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
| D12 | The no-raise budget is met by a net cut: the summed delta of `from-issue/{SKILL,AUTO,investigate}.md` is at most 0 against `origin/main`, and every cut lands in `SKILL.md` or `AUTO.md`. The triage paragraph stays in `SKILL.md` Phase 0 (D6 stands), compressed, and the checkpoint sentence is dropped | User decision 2026-10-07 (issue AC: no raise); `instruction_load.measure_corpus` counts every skill file; the check refuses any model change except lowering, so a new conditional file cannot be listed; `SKILL.md` and `AUTO.md` are hot in all three breached profiles | Moving the paragraph to `investigate.md`, or to a new conditional file, which only shifts hot bytes, still breaches the corpus, and a new file needs a refused model edit. Putting the signal definitions in `lane-triage --help`, which would redesign the command's surface (out of scope) |
| D13 | The existing cut is the expiry rationale in `SKILL.md`'s deadline-rejected `progress` paragraph; the rewritten paragraph keeps every owner action and both helper rejection strings | That rationale restates the suspension procedure ("consumes no attempt", "re-entry resumes it in place") and the reaper's internals, and the owner's action is the same on either reading. The Bar: minimal, no restatement | Trimming the flow diagram, the Notes or the leaf-agent clauses: those are an overview, policy rules or a pinned carrier clause. Spreading small cuts over many sections: more pins touched for the same bytes |
| D14 | Under agent-helpers rule 6 the branch's `LaneTriageContractsTest` is deleted outright, with no replacement pin, and the two expiry phrase-pin tests are deleted in the same slice that slims that prose. The pins kept verbatim are the cross-file build-delivery exception clause and the progress-marker anchor | Rule 6: no new English phrase pin, and existing phrase pins are deleted in the slice that slims their skill; the `lane-triage` argv is not on rule 6's allowed list; this resolves the prior attempt's unapplied Should-fix | Rewriting those pins to the new wording, which rule 6 forbids. Adding `lane-triage` to `COMMAND_VOCABULARY` to vet the span, which D9 rejects |
| D15 | No ceiling is lowered: `instruction-load.json` ends byte-identical to `origin/main`'s (ec089c67 is reverted) | The roughly 38 bytes of slack sit far inside the check's 5% tightness band; lowering adds a gate-file edit that conflicts with concurrent PRs' ceiling notes, for no enforcement gain | Running `tighten` to the new measures: allowed, but it is churn on a contended file and leaves zero slack for the final merge with main |
| D16 | Reverses D14's "no replacement pin": AC4 stays measured in `test_workflow_skill_contracts.py` by one key-set test. Phase 0's backticked spans must name every record key `lane-triage evaluate` reads (`SIGNALS`, `SIGNAL_MEMBERS` and `TOP_MEMBERS`, read from `lane_triage.py` with `ast.literal_eval`), the closed verdict keys `hits`, `lane` and `mode`, and every `LIGHT_LANE_MODES` value from `resolve_project.py`. The modes are the narrowest consumed anchor for "shadow". The Phase-0 text names the verdict as `{hits, lane, mode}`. The two expiry pins are still deleted | Issue AC4 names this file as its measure; rule 6 allows lifecycle-contract JSON key sets; `agent-installed-skill-tests` runs this file without `PYTHONPATH`, so importing `agent_tools` would break that tier, while parsing the source does not; the verdict set mirrors `tests/test_lane_triage.py`'s closed-key assertion | Deleting every pin, which leaves AC4 unmeasured. Phrase pins such as "every attempt runs full", which rule 6 forbids. Importing `agent_tools.lane_triage`, which breaks the installed tier. Adding an output-key constant to `lane_triage.py`, which changes code for a test |
| D17 | Amends D15's mechanism: after the merge, `instruction-load.json` is restored whole from `origin/main` (`git checkout origin/main -- <file>`), because reverting ec089c67 removes only the corpus raise while ffbc16e0 also raised three profile ceilings and appended their notes | Phase-5 Codex B-001, verified at `home/common/agent-skills/instruction-load.json:36,113,228` against `origin/main`; the gate refuses any model change except lowering | Reverting the hunks of ffbc16e0 value by value: same end state, more chances to leave a note or ceiling behind |
| D18 | `resolve-project` refuses a safe but non-canonical `risk_paths` glob (a backslash, an empty or `.` segment, a trailing `/`) as `contract.workflow.noncanonical_path` at `/bindings/workflow/light_lane/risk_paths/<index>`. The canonical rule and its message live once in `resolve_project` (`is_canonical_path`, `CANONICAL_PATH_MESSAGE`), and `lane_triage` reuses both for D11's record-path check | Final-review correctness finding COR-003: D11 makes record paths canonical and `evaluate` matches globs unchanged, so an accepted `./tinytask/store.py` glob could never match and an all-`no` record came back a false `light` | Normalizing globs before matching: it hides the authoring error and makes the matched policy differ from the authored one. A second copy of the predicate in `resolve_project`: two homes for one rule would drift |
