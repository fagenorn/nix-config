# Task 4: Migrate nix-config's review bindings and fixtures; final gate

**Files:**
- Modify: `.agents/project.json` (`bindings.commands` and `bindings.workflow.review` only)
- Modify: `home/common/agent-skills/tests/test_resolve_project.py`
- Modify: `home/common/agent-skills/tests/conformance_test_support.py`
- Modify: `home/common/agent-skills/tests/test_conformance_checks.py`

**Interfaces:**
- Consumes: Tasks 1–3 (the skill, callers and evals accept only the companion shape). In `test_resolve_project.py`: `SnapshotShapeTest`, `ResolverTestCase.resolve(root) -> (code, payload, err)` and `make_root()`, which writes a copy of the committed contract into a temporary project and resolves it under the suite's hermetic installed home; `make_stub_bin(names)`. In `conformance_test_support.py`: `STUB_TOOLS`.
- Produces: the committed command ids `codex-plan-review` and `codex-diff-review`, which `workflow.review.plan` and `workflow.review.code` name (per D14).

**Invariants:**
- `codex-review` no longer exists as a command id or a review binding (per D14).
- Each review entry is `["codex-companion","task","--fresh","--reviewer",<op>]` with cwd `.` and env `[]`, `<op>` matching its operation (per D13, D14).
- The resolver schema, the projections (`AGENTS.md`, the `CLAUDE.md` import line) and every other contract member are unchanged (per D14). `.agents/project.json` is edited as the authored contract; nothing in this task reads policy from it except through `resolve-project` (bootstrap).
- Fixtures that stub the review executable stub `codex-companion` wherever they stubbed `codex`, and no fixture names `codex-review` (per D16).
- The committed-bindings case asserts bindings, never capability state (per D18).

- [ ] **Step 1: Write the failing test.** Add to `SnapshotShapeTest` in `test_resolve_project.py`:

```python
    def test_committed_review_bindings_have_the_companion_shape(self):
        # Through the resolver (D16): bindings only, because capability state
        # follows the host's PATH, which lacks `codex-companion` in CI (D18).
        code, snap, err = self.resolve(self.make_root())
        self.assertEqual(code, 0, err)
        bindings = snap["bindings"]
        self.assertEqual(bindings["workflow"]["review"],
                         {"plan": "codex-plan-review", "code": "codex-diff-review"})
        self.assertNotIn("codex-review", bindings["commands"])
        for review_id, operation in (("codex-plan-review", "plan-review"),
                                     ("codex-diff-review", "diff-review")):
            with self.subTest(review_id=review_id):
                self.assertEqual(bindings["commands"][review_id], {
                    "argv": ["codex-companion", "task", "--fresh",
                             "--reviewer", operation],
                    "cwd": snap["project"]["root"],
                    "env": [],
                })
```

- [ ] **Step 2: Run and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py -k companion_shape 2>&1 | tail -5`
Expected: FAIL — `workflow.review` is `{"plan": "codex-review", "code": "codex-review"}`.

- [ ] **Step 3: Migrate the contract.** In `.agents/project.json`, replace the `"codex-review": { ... }` member of `bindings.commands` with these two members, in the same position and the file's 2-space, one-item-per-line style:

```json
      "codex-plan-review": {
        "argv": [
          "codex-companion",
          "task",
          "--fresh",
          "--reviewer",
          "plan-review"
        ],
        "cwd": ".",
        "env": []
      },
      "codex-diff-review": {
        "argv": [
          "codex-companion",
          "task",
          "--fresh",
          "--reviewer",
          "diff-review"
        ],
        "cwd": ".",
        "env": []
      }
```

and set `bindings.workflow.review` to `{"plan": "codex-plan-review", "code": "codex-diff-review"}` (same multi-line style).

- [ ] **Step 4: Migrate the fixtures.**
  - `test_resolve_project.py`: in every `make_stub_bin((...))` tuple, replace `"codex"` with `"codex-companion"`. `test_available_when_every_prerequisite_is_present` needs it for `review.plan`/`review.code` to be `available`; keep the others consistent.
  - `conformance_test_support.py`: `STUB_TOOLS = ("codex-companion", "gh", "git", "just")`.
  - `test_conformance_checks.py`, `test_a_declared_release_command_is_unsupported_not_absent`: replace both `"codex-review"` literals (the assigned release id and the expected `release_command` fact) with `"nix-activate"`, an id that remains in the contract.

- [ ] **Step 5: Verify the task**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py home/common/agent-skills/tests/test_conformance.py home/common/agent-skills/tests/test_conformance_checks.py home/common/agent-skills/tests/test_conformance_registry.py 2>&1 | tail -3`
Expected: `OK`.
Run: `if rg -n 'make_stub_bin\(\(.*"codex"\)|codex-review' home/common/agent-skills/tests/test_resolve_project.py home/common/agent-skills/tests/conformance_test_support.py home/common/agent-skills/tests/test_conformance_checks.py; then exit 1; fi; if rg -n '"codex",' home/common/agent-skills/tests/conformance_test_support.py; then exit 1; fi`
Expected: no output, exit 0 (both match at the start commit).
Run: `resolve-project resolve --repo-root "$PWD" | jq -c '.bindings.workflow.review, .bindings.commands["codex-plan-review"].argv, .capabilities["review.plan"].state'`
Expected: `{"code":"codex-diff-review","plan":"codex-plan-review"}`, `["codex-companion","task","--fresh","--reviewer","plan-review"]`, `"available"` (this host has `codex-companion` on PATH). A resolver refusal here, including projection drift, fails the task.

- [ ] **Step 6: Commit**

```bash
git add .agents/project.json home/common/agent-skills/tests/test_resolve_project.py home/common/agent-skills/tests/conformance_test_support.py home/common/agent-skills/tests/test_conformance_checks.py
git commit -m "feat(project): bind plan and diff review to the codex-companion reviewer (#236)"
```

- [ ] **Step 7: Final gate for the whole plan**, from the worktree:

```bash
just agent-workflow-tests 2>&1 | tail -3
just build 2>&1 | tail -3
```

Expected: the test run ends `OK`; `just build` succeeds and leaves `./result`. Then confirm the installed skill is this build's companion-only text. The path comes from this build's closure, with exactly one match:

```bash
set -euo pipefail
matches="$(nix-store -qR "$(readlink -f result)" | while read -r p; do
  f="$p/.claude/skills/codex-collaboration/SKILL.md"; if [ -e "$f" ]; then echo "$f"; fi
done)"
if [ "$(printf '%s\n' "$matches" | grep -c .)" -ne 1 ]; then echo "want one match: $matches"; exit 1; fi
grep -qF 'bare `["codex"]` included' "$matches"
if grep -qE 'exec --sandbox|output-last-message' "$matches"; then exit 1; fi
```

Expected: exit 0. At the start commit the built SKILL.md still carries `exec --sandbox`, so this gate can fail. Commit nothing in this step; record in the task report that the live Codex demo (root `## Acceptance evidence`) is still owed.

- [ ] **Step 8: Live companion demo (acceptance evidence)**, from the worktree, after Step 7. It uses this build's closure companion, not the PATH one, and makes two real read-only Codex calls:

```bash
set -euo pipefail
cc="$(nix-store -qR "$(readlink -f result)" | while read -r p; do
  f="$p/bin/codex-companion"; if [ -x "$f" ]; then echo "$f"; fi
done | sort -u)"
if [ "$(printf '%s\n' "$cc" | grep -c .)" -ne 1 ]; then echo "want one companion: $cc"; exit 1; fi
for op in plan-review diff-review; do
  out="$(mktemp)"; trap 'rm -f "$out"' EXIT
  printf '%s\n' "Read-only demo for issue 236 ($op). Do not edit anything. Return exactly three top-level sections for $op headings (plan-review: Blocking / Should fix / Discussion; diff-review: Critical / Important / Minor), each containing None." \
    | "$cc" task --fresh --reviewer "$op" --model gpt-6-astra --effort xhigh --cwd "$PWD" --json > "$out"
  python3 - "$out" "$op" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); op = sys.argv[2]
assert d["status"] == 0 and d["touchedFiles"] == [], d
assert (d["runtime"]["model"], d["runtime"]["reasoningEffort"]) == ("gpt-6-astra", "xhigh"), d["runtime"]
heads = ("Blocking", "Should fix", "Discussion") if op == "plan-review" else ("Critical", "Important", "Minor")
assert isinstance(d["rawOutput"], str) and all(h in d["rawOutput"] for h in heads), d["rawOutput"][:400]
print(op, "ok", d["runtime"])
PY
done
```

Expected: `plan-review ok …` and `diff-review ok …`. A failure here is a real acceptance failure, not a flake: report it with the payload's `status`, `runtime` and first 400 bytes of `rawOutput`. If the Codex call itself is refused for capacity or authentication, record the demo as not run (attestation unverified) instead of retrying. Commit nothing.
