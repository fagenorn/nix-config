# Shared verification blocker: pure module and observe adapter — issue 543 (228 c1)

Issue: https://github.com/fagenorn/nix-config/issues/543, boundary `c1` of
https://github.com/fagenorn/nix-config/issues/228. Its blocker
https://github.com/fagenorn/nix-config/issues/227 is closed. The parent spec (D1–D25) and
plan at `0361d66c` on `worktree-issue-228-orchestrated` are provenance only: every rule
below was re-decided for this child against the current tree. The parent's row IDs are
cited as "parent D<n>". Designed autonomously (`from-issue --auto`); every call made
without the user is a row in the Decision ledger.

## Triage

Input: `{"signals": {"contract_change": {"value": "hit", "evidence": "adds a new verification-observe command wired into lib/agent-tools.nix, the permission guard and python/README.md"}, "concurrency_or_persistence": {"value": "no", "evidence": "pure module plus a read-only observe adapter; ledger schema and persistence belong to later children"}, "open_design_questions": {"value": "doubt", "evidence": "parent spec D1-D25 is provenance only; child must re-decide its slice"}, "criteria_shape": {"value": "doubt", "evidence": "four criteria; 'nothing activates the host' and secret-shape rejection lack one deterministic check"}}, "paths": ["python/agent_tools/verification_blocker.py", "python/agent_tools/verification_observe.py", "tests/test_verification_blocker.py", "tests/test_verification_observe.py", "lib/agent-tools.nix", "home/common/claude-code/default.nix", "home/common/claude-code/README.md", "tests/test_claude_permission_guard.py", "python/README.md", "justfile"]}`
Verdict: `{"hits":["contract_change","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

When a declared verification command fails for a reason outside the change, such as a
pinned dependency, the declared environment, an external service or the command's own
declared input, several attempts can hit the same failure. Later children will park
those attempts on one shared blocker and resume them only when a fresh observation
proves that a selected fact changed. They all need two things that do not exist yet:

- one vocabulary and identity for such a failure, checked identically on both sides of
  every trust boundary;
- one component that reads the repository and states the facts, so that the lifecycle
  helper never does ambient Git, environment or command I/O itself.

Without them each child would invent its own object shapes, and a failed read could be
mistaken for a changed fact, which would trigger a blind resume.

## Solution

Three parts ship together. Nothing calls them yet; c2–c4 are the callers (D1).

**1. A pure blocker module**, `agent_tools.verification_blocker`. It is the one home of:

- the vocabulary and the closed failure classes;
- the three closed wire shapes and their validators;
- order normalization of a selection;
- the secret-shape rule;
- strict loading and canonical bytes;
- the content identity.

It touches no file, clock, process, network or environment variable.

**2. An observation adapter**, `verification-observe` (module
`agent_tools.verification_observe`). It is the only component that does I/O, and it
prints typed objects:

- `failure` turns an owner's declaration into a `verification-failure`;
- `observe` answers one `verification` requirement with a `verification-observation`.

A failed fetch or read prints nothing on stdout and exits 2. It never yields a value.

**3. Wiring.** The adapter gets:

- one row in the command table;
- the Claude permission allow list entries, with the list's comment, the allow-surface
  count in the Claude Code README, `EXPECTED_ALLOW` and one heredoc case in the guard
  suite's lifecycle-call table;
- a `python/README.md` section;
- its two test modules in `just agent-workflow-tests`.

The lifecycle guard's source is unchanged (D9).

**Demo.** A temporary project has a local bare `origin` and a second clone that publishes
to it:

1. `failure` over a clean worktree prints a failure that names the resolved command and
   holds the integration branch's entries. The same declaration with facts and paths in
   another order prints identical bytes, so it has the same identity.
2. `observe` of the matching requirement prints the same values. After an unrelated
   commit on `origin` the bytes are unchanged. After a commit that changes a selected path
   the value differs. After that path is deleted the value is `null`.
3. With `origin` unreachable, `observe` exits 2 with empty stdout.
4. A secret-shaped or unclassified declaration exits 2 before any fetch, so the tracking
   ref does not move.

### This delivery's own gates

- **Fixed base.** The immutable delivery base is
  `328f08daca0cd21e71a622f98c91c3f3a7a6728c`. Integration advances never move it.
- **Forecast.** The plan commits a complete forecast under the landed #227 gates. It
  charges this spec, the plan root, every task, a fix allowance per task, and every
  recording commit.
- **Reviews.** Each task gets a fresh independent review. Distinct final conformance and
  correctness reviews follow. Parent reviews do not count.
- **Verification.**
  - The focused tests;
  - the guard suite against the built settings;
  - `just agent-workflow-tests`;
  - `just build`.
  `just switch` never runs.
- **No instruction ceiling moves.** The delivery touches no skill or guidance document
  that an instruction-load profile measures.

## Decisions

### Wire objects (D2)

```json
{"kind": "verification-failure", "schema_version": 1,
 "repository": {"project_id": "fagenorn/nix-config", "integration_branch": "main"},
 "command": {"id": "nix-build", "argv": ["just", "build"], "cwd": ".", "env": []},
 "failure_class": "dependency",
 "facts": [{"name": "flake-lock", "source": {"paths": ["flake.lock"]},
            "value": {"objects": [{"path": "flake.lock", "object": "<40 or 64 hex>"}]}}]}
```

```json
{"kind": "verification-observation", "schema_version": 1,
 "blocker_id": "sha256:<64 hex>",
 "repository": {"project_id": "fagenorn/nix-config", "integration_branch": "main"},
 "facts": [{"name": "flake-lock", "source": {"paths": ["flake.lock"]},
            "value": {"objects": [{"path": "flake.lock", "object": null}]}}]}
```

```json
{"kind": "verification", "blocker_id": "sha256:<64 hex>",
 "sources": [{"name": "flake-lock", "paths": ["flake.lock"]}]}
```

Every object is closed. These are refused:

- an unknown, missing or duplicate member;
- a `bool` where an `int` is required, and a non-finite number;
- a `kind` or `schema_version` other than the ones shown.

Rules:

- **`repository`.** The resolved `project.id` and `bindings.vcs.integration_branch`, each
  a non-empty string of at most 255 bytes without control characters or whitespace.
- **`command`.** The resolved `bindings.commands` entry of the failing command:
  - `id` is the command id;
  - `argv` and the variable names in `env` are copied unchanged, since the contract
    carries no values;
  - `cwd` is made relative to `project.root` (`.` for the root), so no absolute path
    appears.
  The module checks shape only, because `resolve-project` already validated the entry:
  `argv` is a non-empty list of non-empty strings, `cwd` is `.` or a canonical relative
  path, and `env` is a list of unique variable names, so a `NAME=value` word is refused.
- **`failure_class`.** One of `command_input`, `dependency`, `environment` and
  `external_service`. Anything else, absence included, is unclassified and refused.
- **`facts`.** 1–4 facts, sorted by `name` and unique. `name` matches
  `[a-z0-9][a-z0-9-]{0,63}`. Every fact is selected: there are no unselected facts and no
  selector list.
- **`source.paths`.** 1–8 sorted, unique repository-relative paths per fact, and no path
  appears in two facts. A path is refused when it:
  - is empty or longer than 255 UTF-8 bytes;
  - starts or ends with `/`, or holds a backslash;
  - has an empty, `.` or `..` segment;
  - has a component equal to `.git`, compared case-insensitively;
  - holds a control character;
  - is secret-shaped (D4).
- **`value.objects`.** The fact's paths in the same order. Each `object` is the 40- or
  64-hex lowercase id of that path's entry at the integration branch, or `null` when the
  branch has no entry there (D6).
- **Requirement.** The selection without values: `sources` holds `{name, paths}` under the
  same rules, and `blocker_id` is `sha256:` plus 64 lowercase hex characters.
- **Size.** A failure's canonical bytes are at most 2,048. Only the failure carries a byte
  bound. A requirement or observation derived from a valid failure is bounded by its
  structure, so it can always be produced.

None of these objects has a member for logs, stdout, stderr, environment values,
transcripts, timestamps, prose, the worktree path or a resolved-policy snapshot. So
nothing of that kind can be carried, and later children cannot persist it either.

### Secret-shape rule (D4)

A fact name or a path component is secret-shaped when, compared case-insensitively, it:

- starts with `.env`;
- equals `private`;
- contains `secret`, `token`, `password`, `passwd`, `credential`, `private-key`,
  `private_key`, `api-key`, `api_key` or `apikey`;
- ends with `.pem`, `.key`, `.p12` or `.pfx`;
- or starts with `id_rsa`, `id_ecdsa` or `id_ed25519`.

The rule applies to every fact name and every path, in declarations, failures,
observations and requirements, and it applies before any I/O. It does not apply to the
`command` entry. That entry is copied from the committed contract, so it adds nothing the
repository does not already hold, and an `env` name such as `GITHUB_TOKEN` carries no
value. The rule matches every path that adoption's `is_secret_path` matches, and more.

### Normalization and identity (D3, D5)

**Normalization.** A declaration (the `failure` input) is a selection in any order:

- its facts are sorted by `name`, and each fact's paths are sorted;
- a repeated name, a path repeated within a fact or across facts, and a path spelled
  non-canonically are refused, never rewritten.

The wire objects are the normalized form. A failure, observation or requirement that is
not already sorted is refused.

**Identity.** The blocker id is `agent_tools.canonical.telemetry_digest` over the closed
object `{repository, command, failure_class, facts}` of a validated failure. So
`kind`, `schema_version`, time, host, attempt and worktree are not part of it. Equal
normalized failures therefore get the same id in every run and on every host, and a
change to any member changes the id. The id names a failure; it is never evidence that
anything changed.

### Adapter `verification-observe` (D6, D7, D8)

```text
verification-observe failure --repo-root <absolute> --input -
verification-observe observe --repo-root <absolute> --input -
```

**Inputs.** Stdin is loaded strictly: duplicate keys and non-finite literals are refused.

- `failure` reads the closed `{"command_id", "failure_class", "worktree", "facts":
  [{"name", "paths"}]}`. `worktree` is the absolute path of the checkout where the command
  failed. It is adapter input only and appears in no output.
- `observe` reads one requirement.

**Order.** Each mode runs these steps in order and stops at the first refusal:

1. Validate and normalize the input with the pure module. A malformed, unclassified or
   secret-shaped input is refused here, before any process starts.
2. Resolve the project at `--repo-root` in process with `verification` required. A
   resolver refusal is `resolve-project refused: <code> <repair_id>`.
3. `failure` only: `command_id` must be in `bindings.workflow.verification`.
4. Fetch only the integration branch from `origin` into
   `refs/remotes/origin/<integration_branch>`, with no tags, no `FETCH_HEAD`, no
   submodules and no automatic maintenance.
5. Read each selected path's exact entry at that ref. A nested directory yields its own
   tree id, not its members' entries. A missing entry is `null`.

**Failure guard (D7).** Before printing, `failure` also requires:

- the worktree's Git common directory to be the same as that of `--repo-root`;
- the project resolved at the worktree to hold the same `command_id` entry (`argv`,
  `env`, project-relative `cwd`) as `--repo-root`;
- the worktree's `HEAD` to hold, for every selected path, the same entry as the fetched
  ref (both absent counts as equal);
- no staged, unstaged or untracked change at a selected path.

The command entry and `repository` come from `--repo-root`, so every attempt of a run
names one command. The failure class remains the caller's declaration. The guard proves
only that the attempt did not change a selected input or the command itself.

**Git children.** Every child runs with:

- `GIT_TERMINAL_PROMPT=0`;
- the repository-routing variables (`GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`,
  `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY`, `GIT_ALTERNATE_OBJECT_DIRECTORIES`) removed,
  so `--repo-root` and the worktree name the repository;
- literal pathspecs;
- a 60-second timeout.

**Outputs.**

- **Exit 0** prints the object's canonical bytes (sorted keys, compact, ASCII) and one
  newline. The pure module validates the object before it is printed.
- **Exit 2** prints nothing on stdout and one line `verification-observe: <reason>` on
  stderr. A Git failure names its subcommand and Git's last stderr line. Exit 2 covers:
  - an invalid invocation or input;
  - a resolver refusal;
  - a command that is not a verification command;
  - a failed or timed-out Git child, the fetch included;
  - a guard violation.

A refusal is never an observation. There is no `null` for a read that failed, and no
value read from a tracking ref the fetch did not just update.

**Writes.** The adapter's only write is Git's update of that one remote-tracking ref and
the objects it fetches. It runs no declared command.

**Interface.** The command module is a thin shell (agent-helpers rule 2) over two
importable functions, `build_failure(repo_root, declaration)` and
`observe(repo_root, requirement)`. Each returns a validated object or raises one
refusal type. `observe` answers one requirement per call. The observation's `repository`
is resolved at observe time, not copied from the requirement.

## Test seams

Assertions read exit codes, stdout bytes, stderr lines and the repository's refs. They
never read helper call counts (D10).

- **Pure module**, in `tests/test_verification_blocker.py`, by import. Tables over the
  three shapes and declarations:
  - unknown, missing and duplicate members; booleans as integers;
  - unsorted, duplicate and cross-fact paths; count and size limits;
  - traversal, absolute, `.git`, control-character and over-long paths;
  - every secret-shape clause, and `command.env` names that the rule leaves alone;
  - unclassified classes; `NAME=value` in `env`;
  - normalization: a declaration in another order yields the same sources;
  - identity: one pinned literal id for a fixed failure, equality across key order and
    deep copies, and a different id per changed member;
  - strict load: duplicate keys, `NaN` and invalid UTF-8 refused.
- **Adapter**, in `tests/test_verification_observe.py`, as `python -m
  agent_tools.verification_observe`. The harness is the `tests/test_verified_tree.py`
  style: the eval fixture project in a temporary repository, a temporary `HOME` holding
  the platform manifest, and a hermetic Git environment. To that it adds a local bare
  `origin` and a publishing clone. Cases:
  - a clean failure, and the worktree path absent from stdout;
  - order-independent declaration bytes;
  - an unrelated commit observed as equal, a selected change as different, a deletion
    as `null`, and a nested directory observed as its tree id;
  - refusals before any fetch, with the tracking ref unmoved: secret-shaped,
    unclassified, a non-verification command, an unknown member, a relative root;
  - guard refusals: dirty, untracked, committed own edit, a diverged command entry, a
    foreign repository;
  - an unreachable `origin` and a missing integration branch printing nothing, exit 2;
  - the only ref that changes is `refs/remotes/origin/<integration_branch>`, with no
    `FETCH_HEAD` and the working tree unchanged.
- **Guard suite**, `tests/test_claude_permission_guard.py`, against the built settings:
  `EXPECTED_ALLOW` gains the two entries, and the single-command lifecycle-call table
  gains one `verification-observe observe … --input - <<'JSON'` case that must pass.
- **Integration**: `just agent-workflow-tests` (both new modules listed) and `just build`
  (the command row's module check and the allow entries evaluate).

## Out of scope

- Blocker records, attempt backreferences, ledger schema 11, the `verification` cause and
  migration: c2 (https://github.com/fagenorn/nix-config/issues/544).
- Value comparison, rendering a requirement from a record, resolution and resume, control
  interface 4 and direct-owner request 3: c3
  (https://github.com/fagenorn/nix-config/issues/545).
- `orchestrate-control` gathering, batched observation with one fetch per step, skill
  procedures and examples, instruction ceilings, and the agent-skills README protocol:
  c4 (https://github.com/fagenorn/nix-config/issues/546).
- Declared-probe facts, or any fact kind other than repository paths.
- Deciding whether a failure is infrastructure. The class is the caller's declaration.
- Any change to `lifecycle_guard.py` or to adoption's `is_secret_path`.
- Host activation (`just switch`), live ledgers and retained attempts.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | c1's pure module holds the vocabulary, the three closed shapes and their validators, selection normalization, the secret-shape rule, strict load, canonical bytes and the identity. Record and state rules and the migration (c2), comparison and requirement rendering (c3), and batched observing (c4) stay with their children. | Issue: "normalization, classification and identity rules over typed observations"; "Ledger schema, control and caller changes belong to later children"; The Bar YAGNI. | Parent Task 1's full surface (`park`, `resolve`, `validate_blockers`, `upgrade_ten`, `changed_names`, `requirement`): it would settle schema-11 and resolution semantics before those children's own specs and reviews. |
| D2 | Adopt parent D2's two closed v1 objects plus the requirement shape, with bounds of 1–4 facts and 1–8 paths of at most 255 bytes. A path may appear in only one fact. Only the failure carries the 2,048-byte canonical bound. | AC1; parent D2 (requirements ride replies capped at 65,536 bytes, c3); the later children cite parent shapes. | A byte bound on observations as well: a valid failure's observation could exceed it, and its blocker could then never be observed. A new, flatter value shape: it diverges from the provenance for no gain. |
| D3 | The identity is `telemetry_digest` over `{repository, command, failure_class, facts}`, with the command copied from the contract resolved at `--repo-root` and `cwd` made project-relative. No kind, version, time, host, attempt or worktree enters it. | agent-helpers rule 4; issue 228 Decisions (stable across runs for equal facts, no global store); parent D3. | Including the worktree or the host: not stable across attempts. Including `schema_version`: a new version changes shape and so the digest anyway. |
| D4 | The secret-shape rule is the module's own case-insensitive rule over fact names and path components: parent D2's list plus a whole `private` component, so it is never weaker than adoption's `is_secret_path`. It applies to selections only, not to the contract's command entry. | AC1; The Bar DRY (look-alike is not duplication): adoption avoids over-refusing paths it must move, while a refusal here only keeps a failure on its existing route; the contract is committed, so copying it discloses nothing. | Reusing `is_secret_path`, which misses `secrets.yaml`, `*.pem` and `id_ed25519`; widening it, which changes adoption outside this scope; checking `env` names, which refuses value-free names such as `GITHUB_TOKEN`. |
| D5 | A declaration is order-normalized: facts by name, paths sorted, duplicates refused. Path spelling is never rewritten. Wire objects must already be canonical. | The Bar token economy (prefer forms a model emits reliably); `resolve_project.is_canonical_path` refuses rather than rewrites spelling. | Refusing an unsorted declaration (parent): it turns an ordering slip into a refusal with no safety gain. Rewriting `./a` or `a/../b`, which makes spelling ambiguous. |
| D6 | The one fact kind is repository paths. Each is read as the exact entry at `refs/remotes/origin/<integration_branch>` after a fetch of that one branch: a file, symlink, directory or submodule entry id, or `null` when absent. A failed or timed-out fetch or read is exit 2 with nothing printed. | AC2 ("a failed probe is reported as failed, never as changed"); parent D4; `git ls-tree` with a nested directory pathspec lists the directory's members, not its entry. | Declared probes, which run declared commands when no contract marks one read-only. Falling back to the local tracking ref after a failed fetch: stale values hide a change. Encoding a failed read as `null`, which reads as changed. |
| D7 | `failure` requires all of: the worktree shares `--repo-root`'s Git common directory; its resolved entry for the command equals the root's; its `HEAD` holds the ref's entry for each selected path; and no selected path has a staged, unstaged or untracked change. The class stays caller-declared. | Parent D4 and D24; issue 228 Decisions ("product/test failures do not become infrastructure blockers by relabeling"); AC2 "one declared failing command". | A fully clean worktree, which refuses on state no fact reads. Trusting the root entry alone, which relabels an attempt's own edit of its command. Resolving the command only at the worktree, which lets each attempt's contract copy split the identity. |
| D8 | Two stdin-only modes with an absolute `--repo-root`. The order is input validation, then resolution, then Git. Every Git child runs with no prompt, without the repository-routing variables, with literal pathspecs and a 60 s timeout. Exit 0 prints one validated canonical line. Exit 2 prints no stdout and one stderr line naming Git's last stderr line. The importable `build_failure` and `observe` take one input each. | agent-helpers rule 2; `verified-tree` (stderr line, exit 2) and adoption's `fetch_pinned` (no prompt, timeout, one ref) precedents; The Bar "the log stream is the debugger". | A JSON refusal object on stdout, which no caller reads yet. A batch `observe_all`: c4's step owns batching and its one-fetch bound. Inheriting `GIT_DIR`, which could observe another repository. |
| D9 | Wiring: one command-table row; `Bash(verification-observe:*)` and `Bash(~/.agents/bin/verification-observe:*)` after the `orchestrate-control` pair, with the allow list's comment naming the adapter's one write; the README's allow surface goes from 26 to 28 entries; the guard suite's `EXPECTED_ALLOW` and lifecycle-call table. `lifecycle_guard.py` and skill text are untouched. | Issue: "Wire it as a command in `lib/agent-tools.nix`, the Claude Code permission guard and its adversarial table"; `git fetch` is already allowed; agent-helpers rule 1. | Leaving it to the auto classifier until c4, which the issue rules out. Adding skill examples or `test_shell_example_contracts` sanctions now, which belong to c4's procedures. |
| D10 | Test seams: pure tables by import; the adapter from source over a `test_verified_tree`-style harness (eval fixture project, temporary `HOME` manifest, hermetic Git) plus a local bare `origin` and a publishing clone; the guard suite against the build. | agent-helpers rule 5; The Bar "Tests that can fail"; the `test_verified_tree` precedent (Git reads plus in-process resolution). | `OrchestrateWorld` (parent): its `workflow-state` and `gh` shims serve control rounds the adapter never makes. |
