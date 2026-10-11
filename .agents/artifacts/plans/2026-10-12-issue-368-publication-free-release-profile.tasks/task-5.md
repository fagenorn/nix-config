# Task 5: Documented contract and the nix-config byte-identity evidence

Spec section 7 and requirement R4 (per D9, D12). `python/README.md` § Release profiles states the new form as the code now behaves, and the AC4 evidence is measured on the final head.

**Files:**
- Modify: `python/README.md` (section `## Release profiles` only)

**Interfaces:**
- Consumes (Tasks 1–4, all merged before this task): the grammar form `"publication": "none"` and its rules in `release_profile._Profile`; `release_profile.phase_nodes`, `release_targets`, `bind_candidate`; `resolve_project.release_capability`, `build_snapshot`; `release._graphs`.
- Produces: documentation and the measured values for acceptance-record rows `AC4` and `AC5` (handed to the caller in the task report; this task writes no acceptance file).

**Invariants:**
- Every sentence added to the README is true of the code at this task's commit: read each function named below before writing about it, and cite decisions as `#368 D<n>` the way the section cites `#124 D<n>`.
- The README gains no sentence about the lifecycle guard reading the contract, about Nodo, or about any behaviour issue 126 or 367 owns.
- No file outside `python/README.md` is changed by this task.

- [ ] **Step 1: Confirm the gate fails first**

Run:

```bash
if ! grep -q '"publication": "none"' python/README.md; then echo MISSING-FORM; fi
if ! grep -q 'release\.targets' python/README.md; then echo MISSING-MEMBER; fi
```

Expected at this task's starting commit: both `MISSING-FORM` and `MISSING-MEMBER` are printed.

- [ ] **Step 2: Write the documentation**

In `python/README.md`, section `## Release profiles`, state these facts in the section's existing style (prose paragraphs, no new heading), each written from the implemented code:

1. In the first paragraph, where the grammar is described: a profile's `publication` is `"none"` or `{"actions": [...]}` with at least one action; a profile with `"publication": "none"` is a publication-free profile that declares its target, requirements and bindings like any other and passes the same same-repository rule.
2. The rules the grammar holds a publication-free profile to, with the repair id each violation actually carries in `release_profile` (activation other than `"none"`; a non-empty `proof.obligations`; a recovery unit).
3. Where `capabilities.release` is described: it is also `unsupported` when no profile declares a publication, and otherwise the listed logic runs over all profiles.
4. `compile_profile` returns such a profile with an empty graph, and `bind_candidate` refuses it, so it never reaches `TransactionStore.create`; `core_binding` refuses every request for it because it has no compiled node.
5. A new sentence or short paragraph on the resolved snapshot's `release` member: `{"targets": [...]}`, one entry per bound target of every profile with `profile`, `adapter`, `target` (the normalized target) and `operations`, the ordering, `[]` for `"unsupported"`, and an empty `operations` for every target of a publication-free profile; built by `release_profile.release_targets`.
6. In the `release profile inspect` paragraph: a publication-free profile is reported with exit 0, empty graphs and an empty `handoffs` list.

- [ ] **Step 3: Verify the documentation gate**

Run:

```bash
if ! grep -q '"publication": "none"' python/README.md; then exit 1; fi
if ! grep -q 'release\.targets' python/README.md; then exit 1; fi
git diff --stat 40fa1f82c5a5 -- python/README.md
```

Expected: exit 0 and one changed file in the stat.

- [ ] **Step 4: Commit**

```bash
git add python/README.md
```

Commit through `launch-commit` with the message `docs(agent-tools): the publication-free release profile and release.targets (#368)`.

- [ ] **Step 5: Measure AC4 on the committed head (per D9, D12)**

The installed `resolve-project` is neither the base nor the head code, and `project.root` is an absolute path, so both runs use this worktree as `--repo-root` and differ only in the `agent_tools` they import. With `SCRATCH` the directory `launch-scope scratch` prints:

```bash
mkdir -p "$SCRATCH/base"
git archive 40fa1f82c5a50ab8da32d15f9bf7c1d71e82e76b python | tar -x -C "$SCRATCH/base"
env PYTHONPATH="$SCRATCH/base/python" python3 -m agent_tools.resolve_project resolve --repo-root "$PWD" > "$SCRATCH/before.json"
env PYTHONPATH="$PWD/python" python3 -m agent_tools.resolve_project resolve --repo-root "$PWD" > "$SCRATCH/after.json"
python3 - "$SCRATCH/before.json" "$SCRATCH/after.json" <<'PY'
import json, sys
before, after = (json.load(open(path, encoding="utf-8")) for path in sys.argv[1:3])
release = after.pop("release")
dump = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"))
assert sorted(before) == ["bindings", "capabilities", "project", "schema_version"], sorted(before)
assert dump(before) == dump(after), "the four existing members differ"
assert release == {"targets": [{"profile": "github-release", "adapter": "github-forge",
    "target": {"handle": "repository", "kind": "github_repository",
               "repository": "fagenorn/nix-config", "branch": "main"},
    "operations": ["release", "tag"]}]}, release
print("AC4 identical; release =", dump(release))
PY
git diff --quiet 40fa1f82c5a5 -- .agents/project.json tests/fixtures/release/github-release-profile.json
git diff --numstat 40fa1f82c5a5 -- 'tests/test_release_*.py'
```

Expected: both resolver runs exit 0; the script prints `AC4 identical; release = ...` (an `AssertionError` shows the criterion unmet); `git diff --quiet` exits 0; every numstat row has `0` in its second column. Run with a clean tree (`git status --porcelain` empty). Report for acceptance-record row `AC4`: the printed line, the head commit, the OS and the clean-tree condition.

AC5 is measured by sdd's final gate on the final head, not here: `just agent-workflow-tests`, threshold exit code `0`, recorded in acceptance-record row `AC5` with the commit and conditions.
