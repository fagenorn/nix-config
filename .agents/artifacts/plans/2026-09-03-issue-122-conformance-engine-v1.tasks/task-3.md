# Task 3: Host installation checks — store-symlinked policy path and missing helper

**Files:**
- Modify: `home/common/agent-skills/scripts/conformance.py`
- Modify: `home/common/agent-skills/tests/test_conformance.py`

**Interfaces:**
- Consumes from Task 2: `Check`, `Outcome`, `Context`, `REGISTRY`, `REGISTRY_BY_ID`, `REPAIRS`, `select`, `bound_fact`/`bound_facts`, and `context.bindings` / `context.capabilities` (populated by `check_contract_resolvable` when the contract validated, `None` otherwise — unreachable here, because both checks depend on `repository.contract.valid`).
- Produces two evaluators, `check_policy_path_no_follow_readable(context)` and `check_executor_helper_on_path(context)`, and the two registry entries and two repairs below.

**Invariants:**
- The symlink walk is **bounded at the project root**: it inspects the declared path's own components under the root and never a component at or above it (D18). On macOS `/tmp` is a symlink to `private/tmp`; an unbounded walk would fail every fixture and every checkout beneath it.
- Neither evaluator performs a `PATH` search of its own. `host.executor.helper_on_path` projects the resolver's already-computed capability states (DRY with `resolves_on_path`).
- Neither evaluator opens a file, follows a link to read its target's contents, or starts a process.
- `facts` carry repository-relative paths and small integers, never absolute paths — an absolute path leaks the caller's home directory. Every one of them goes through `bound_facts` (D30): a repository-relative path has no length ceiling either, and an unbounded one would make the engine's own report fail `validate_report` and turn a host finding into `resolver_failure`.

## Registry entries this task adds

Append to `REGISTRY` after `host.capability.required` (dependency order holds: both depend on `repository.contract.valid`, which precedes them).

| Id | Domain | Subject kind | Req. | Depends on | `findings`: reason code → repair id |
|---|---|---|---|---|---|
| `host.policy_path.no_follow_readable` | host | path | required | `repository.contract.valid` | `policy_path_symlinked` → `host.policy_path.materialize` |
| `host.executor.helper_on_path` | host | host_tool | required | `repository.contract.valid` | `helper_missing` → `host.helper.install` |

Both repairs: `{"module": "conformance", "safety_class": "user_action", "operation": None}` — no command materialises a store-linked policy file or installs a helper, so the operation is null (D25).

## `host.policy_path.no_follow_readable`

**Subject set.** Every repository-relative path the contract declares as a knowledge or projection source, read from the *authored* contract (`context.contract["bindings"]["paths"]` and `context.contract["projections"]`), not from `context.bindings` — the normalized bindings are already absolute and the check needs the relative form for its facts. Collect, deduplicated and sorted: every entry of `paths.context`, `paths.standards`, `paths.architecture`, `paths.operations`, `paths.hints`, `paths.rejections`, plus every projection entry's `source`.

Projection *targets* are excluded: they are generated files the project owns and rewrites, not policy a reader opens with `O_NOFOLLOW`.

**The walk.** For each relative path, accumulate `current = root`, then `current = current / part` for each of `Path(relative).parts`. At each accumulated `current`, test `current.is_symlink()` (an `lstat`, which does not follow). Stop at the first symlinked component, or when the path is consumed. Never test `root` itself and never any of its parents (D18). A component that does not exist at all is **not** this check's finding — a missing knowledge path is the resolver's `knowledge_path_missing`, surfaced by `host.executor.helper_on_path` — so skip a path whose walk hits a non-existent component with no symlink found.

**The finding.** With no symlinked component, `Outcome("passed")`. Otherwise:

```python
Outcome("failed", "policy_path_symlinked", "host.policy_path.materialize", {
    "paths": bound_facts(offending),     # ≤ 8 repository-relative paths, sorted
    "count": len(offending),
    "link_depth": <component index of the first symlink in the first offender, 1-based>,
    "in_nix_store": <bool: os.readlink of that component, resolved against its parent,
                     starts with "/nix/store/">,
})
```

`in_nix_store` records *where the link points* as a boolean only — never the store path itself, which would be an absolute path in the facts.

## `host.executor.helper_on_path`

Reads `context.capabilities` and reports what the resolver already computed as `blocked` for a tool-shaped reason:

```python
TOOL_REASON_CODES = ("command_missing", "tracker_cli_missing")
```

Collect `[name for name, entry in sorted(context.capabilities.items()) if entry["state"] == "blocked" and entry["reason_code"] in TOOL_REASON_CODES]`. Empty → `Outcome("passed")`. Otherwise `Outcome("failed", "helper_missing", "host.helper.install", {"capabilities": bound_facts(offending), "count": len(offending), "reason_codes": bound_facts(distinct_codes)})`.

A capability blocked for `knowledge_path_missing` or `vcs_worktree_unsupported` is deliberately **not** this check's finding: neither is a helper missing from `PATH`, and misreporting them here would send a reader to the wrong repair.

- [ ] **Step 1: Write the failing test**

Append two classes to `home/common/agent-skills/tests/test_conformance.py`. Both inherit `ReportAssertions`, build their root with `make_root(tmp)` inside `with fixture() as tmp:`, and read the report through Task 1's `doctor(self, root)` helper — so every run is hermetic (D35): the clean-root cases pass because `HERMETIC_ENV` already points `PATH` at the stub bin, and the empty-`PATH` case passes `env=dict(HERMETIC_ENV, PATH="")` rather than mutating the caller's environment.

**`PolicyPathSymlinkTest`** — the check is `host.policy_path.no_follow_readable`.

| Case | Fixture mutation | Expected |
|---|---|---|
| symlinked standards dir | replace `home/common/agent-skills/standards` with a symlink to a sibling real directory | `domain`/`subject_kind`/`status`/`reason_code`/`repair_id` are `host`/`path`/`failed`/`policy_path_symlinked`/`host.policy_path.materialize`; `facts == {"paths": ["home/common/agent-skills/standards"], "count": 1, "link_depth": 4, "in_nix_store": False}`; that repair is `user_action` with `operation` null |
| symlinked projection source | replace `.agents/instructions/bootstrap.md` with a symlink to a copy | `failed`, `facts["paths"] == [".agents/instructions/bootstrap.md"]` |
| clean root | none | `passed`, `repair_id` null, `facts == {}` |
| symlinked ancestor **above** the root (D18) | build the root at `<tmp>/real/repo`, symlink `<tmp>/linked` → `<tmp>/real`, run against `<tmp>/linked/repo` | `passed` — the walk never inspects a component at or above the root |
| very long offending path (D30) | declare `paths.standards` as an eight-segment, 40-`d`-per-segment path under the root and symlink its last component | `failed`, and the single emitted path is exactly 200 characters, with the report still valid |

`link_depth == 4` because `home/common/agent-skills/standards` has four components and the fourth is the link. The last row is the one that fails without the bounding helper: an unbounded path makes the engine's own report fail `validate_report` and turns a host finding into `resolver_failure`.

**`HelperOnPathTest`** — the check is `host.executor.helper_on_path`.

| Case | Environment | Expected |
|---|---|---|
| empty `PATH` | `dict(HERMETIC_ENV, PATH="")` | `subject_kind`/`status`/`reason_code`/`repair_id` are `host_tool`/`failed`/`helper_missing`/`host.helper.install`; `"tracker"` is in `facts["capabilities"]`, that list holds at most 8 names, `facts["reason_codes"]` is sorted and duplicate-free; the repair is `user_action` with `operation` null |
| fixture stub `PATH` | `HERMETIC_ENV` | `passed` |

`make_root` must, from this task on, create the knowledge and standards directories the contract declares, so the clean-root cases genuinely pass; extend it once here and reuse it. Import `shutil` if it is not already imported.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py -k PolicyPath -k Helper`
Expected: `KeyError: 'host.policy_path.no_follow_readable'` and `KeyError: 'host.executor.helper_on_path'` — the ids are not in the registry, so no check by that id appears in the report.

- [ ] **Step 3: Write the minimal implementation**

Add the two evaluators and their registry entries and repairs exactly as specified above.

```python
def check_policy_path_no_follow_readable(context: "Context") -> "Outcome":
    """Contract: failed when any declared policy path reaches its target through
    a symlink at or below the project root, never above it (D18)."""


def check_executor_helper_on_path(context: "Context") -> "Outcome":
    """Contract: failed when the resolver computed a capability as blocked for a
    tool-shaped reason; performs no PATH search of its own."""
```

- [ ] **Step 4: Verify**

```bash
python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py
just agent-workflow-tests
python3 home/common/agent-skills/scripts/conformance.py run --purpose doctor --repo-root . \
  | python3 -c 'import json,sys; r=json.load(sys.stdin); print(sorted(c["id"] for c in r["checks"] if c["domain"]=="host"))'
```

Expected: unittest OK; `just agent-workflow-tests` passes; the last command prints exactly
`['host.capability.required', 'host.executor.helper_on_path', 'host.policy_path.no_follow_readable']`.

Falsifiability at the base commit: that last command prints `['host.capability.required']`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/conformance.py \
        home/common/agent-skills/tests/test_conformance.py
git commit -m "$(cat <<'MSG'
feat(conformance): register the two host installation checks

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0128oBTKhwUFwSefRhxX2PAy
MSG
)"
```
