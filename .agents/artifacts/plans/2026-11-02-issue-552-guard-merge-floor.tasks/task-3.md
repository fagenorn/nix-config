# Task 3: The plan-gated merge floor

Spec § The merge floor, § Refusals, § Documentation (`## Adjudicated verbs`, `## Guard/core decision`), § Test seams seam 1. Rests on D2, D3, D6, D7, D9, D10, D11, D12 and D13. After this task, a feature merge into the default branch whose protection read gets the plan-gated answer, in a repository whose confirmed derived row declares checks, is judged on the PR's own rollup. Every other path keeps its verdict and text.

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py` (new constants, `Context.__init__`, `validate_merge`, new functions after `mergeability_problem`, `validate_release_merge`)
- Test: `tests/test_claude_permission_guard.py` (`FAKE_GH_SCRIPT`, a new section)
- Modify: `home/common/claude-code/README.md` (`## Adjudicated verbs`, `## Guard/core decision`)

**Interfaces:**
- Consumes: Task 2's confirmed `row["required_checks"]` (a sorted `list[str]`). Unchanged guard helpers: `refuse(operation, problem, forms=())`, `block_child_failure`, `shown_value`, `mergeability_problem`, and `validate_merge`'s locals `pr_facts`, `base`, `head_commit` and `protection_lookup`. Test helpers: `write_policy`, `write_base`, `rows_env`, `run_guard`, `make_repo`, `refusal_line`, `release_env`, `HEAD_SHA`, `ABSENT`.
- Produces, in the guard: `Context.required_checks`, a `tuple[str, ...]`; the constants `PLAN_GATED_STATUS`, `PLAN_GATED_MESSAGE`, `GREEN_CHECK_RUN_STATUS`, `GREEN_CHECK_RUN_CONCLUSIONS`, `GREEN_STATUS_CONTEXT_STATE` and `RELEASE_ROLLUP_PREDICATE`; and the functions `plan_gated_answer(stdout) -> bool`, `rollup_entry_name(entry) -> str | None`, `rollup_entry_green(entry) -> bool`, `observed_state(entry) -> str` and `merge_floor_problem(pr_facts, base, head_commit, required_checks) -> str | None`.
- Produces, in the tests (Task 4 uses them): the fake `gh` mode `http_error`, and the class members `PLAN_GATED_MESSAGE`, `UNPROTECTED`, `LOOKUP_FAILED` and `check_run(name, status="COMPLETED", conclusion="SUCCESS")`.

**Invariants:**
- The guard still imports nothing new and starts no new child. `FORM_TABLE`, the PR lookup argv and the order of the feature arm up to the protection read are unchanged.
- `Context.required_checks` is the confirmed row's list as a tuple when `derived_row is not None and row_problem is None`, and `()` otherwise: a row with a problem, a literal `integration_bases` row and no row all declare none.
- Protection read: a timeout keeps `protection lookup timed out`, and exit 0 runs today's jq predicate with the checks unread. A non-zero exit goes to the floor only when `context.required_checks` is non-empty and `plan_gated_answer(protection_lookup.stdout)` holds. `plan_gated_answer` is true only when stdout parses as a JSON object whose `status` is the string `PLAN_GATED_STATUS` (`"403"`) and whose `message` equals `PLAN_GATED_MESSAGE` exactly; stderr is never parsed. Every other non-zero exit keeps `block_child_failure("protection lookup failed", protection_lookup)` unchanged.
- `merge_floor_problem` starts no child, and the first failure is the verdict (D3, D11):
  1. `head_commit is None` gives `<base> cannot be protected on this repository's plan, so the merge must carry --match-head-commit with the reviewed PR head`.
  2. `statusCheckRollup` must be a list with no entry for which `rollup_entry_name` is `None`, or the verdict is `cannot read the PR check rollup`.
  3. For each declared check in row order, the entries naming it are those whose `rollup_entry_name` equals it exactly. None gives `<base> cannot be protected on this repository's plan, and the declared required check <name> is missing from the PR's check rollup`. A naming entry that is not green gives `<base> cannot be protected on this repository's plan, and the declared required check <name> is not green (<observed>)`, from the first such entry.
  4. Otherwise `None`, and `validate_merge` returns 0.
- `rollup_entry_name`: an `entry` that is a `dict` whose `__typename` is `"CheckRun"` gives its `name` when that is a `str`. One whose `__typename` is `"StatusContext"` gives its `context` when that is a `str`. Anything else gives `None`.
- `rollup_entry_green` (D6): a `CheckRun` with `status == GREEN_CHECK_RUN_STATUS` and `conclusion in GREEN_CHECK_RUN_CONCLUSIONS`, or a `StatusContext` with `state == GREEN_STATUS_CONTEXT_STATE`.
- `observed_state` (D12): `CheckRun <status>/<conclusion>` or `StatusContext <state>`. Each fact is `shown_value(fact)` when it is a `str`, and `none` otherwise. `<name>` is `shown_value(check)`, and `<base>` is the read-back base.
- Every floor refusal goes through `refuse("merge", problem)` with no forms (D7).
- `RELEASE_ROLLUP_PREDICATE` is rendered from the three green constants and equals the base program byte for byte (D6, D13). `validate_release_merge` passes it as jq's `-e` program, so its verdicts and its refusal are unchanged.

- [ ] **Step 1: Write the failing tests**

All edits are in `tests/test_claude_permission_guard.py`.

1. Replace the four comment lines above `FAKE_GH_SCRIPT` with:

```python
# Stand-in for `gh`. Answers the two lookups the guard makes for any slug and
# any protected branch, so the merge path can be exercised in every fixture
# repository. FAKE_<STAGE>_MODE injects failures; FAKE_<STAGE>_JSON overrides
# the payload. Mode `http_error` replays a failed `gh api` read as gh reports
# it (issue 552): exit 1, the response body on stdout (FAKE_<STAGE>_JSON, else
# GitHub's plan-gated protection answer) and `gh: <message> (HTTP <status>)` on
# stderr, or `gh: HTTP 403` when the body holds no string message and status.
```

2. In `FAKE_GH_SCRIPT`, add `import json` above `import os`. Directly after the imports, add the body the live read of `fagenorn/argus` returned on 2026-11-02:

```python
PLAN_GATED_BODY = (
    '{"message":"Upgrade to GitHub Pro or make this repository public to enable this '
    'feature.","documentation_url":"https://docs.github.com/rest/branches/'
    'branch-protection#get-branch-protection","status":"403"}'
)
```

3. In `FAKE_GH_SCRIPT`, directly after the `if mode == "invalid":` block and before `if stage == "pr":`, add:

```python
if mode == "http_error":
    body = os.environ.get("FAKE_" + stage.upper() + "_JSON", PLAN_GATED_BODY)
    try:
        answer = json.loads(body)
        line = "gh: " + answer["message"] + " (HTTP " + answer["status"] + ")"
    except (ValueError, KeyError, TypeError):
        line = "gh: HTTP 403"
    print(body)
    print(line, file=sys.stderr)
    raise SystemExit(1)
```

4. Insert this section directly before the section header whose second line is `# Forge adapter arms (#124): the tag push and the release creation the`:

```python
    # ------------------------------------------------------------------
    # The plan-gated merge floor (issue 552): a feature merge into the default
    # branch of a repository whose forge cannot protect it is judged on the PR's
    # own rollup against the checks its confirmed derived row declares.
    # ------------------------------------------------------------------

    PLAN_GATED_MESSAGE = ("Upgrade to GitHub Pro or make this repository public to enable "
                          "this feature.")
    FLOOR = "acme/floor"
    STAGED = "acme/staged"
    BUILD = "CI / build (unit + forced)"
    LINT = "lint"
    FLOOR_ROWS = {
        FLOOR: {"default_branch": "main", "integration_branch": "main",
                "required_checks": [BUILD, LINT], "evidence": {}},
        STAGED: {"default_branch": "main", "integration_branch": "dev",
                 "required_checks": [BUILD, LINT], "evidence": {}},
    }
    UNPROTECTED = ("lifecycle guard: unsafe merge: main cannot be protected on this "
                   "repository's plan")
    LOOKUP_FAILED = "lifecycle guard: protection lookup failed: stderr="

    @staticmethod
    def check_run(name, status="COMPLETED", conclusion="SUCCESS"):
        return {"__typename": "CheckRun", "name": name, "status": status,
                "conclusion": conclusion}

    @staticmethod
    def status_context(context, state="SUCCESS"):
        return {"__typename": "StatusContext", "context": context, "state": state}

    def floor_merge(self, rollup, slug=None, base="main", pin=True, rows=None, env=None,
                    guard_args=()):
        """A feature merge of PR 9 into `base` of `slug` (FLOOR) whose rollup is `rollup`
        (ABSENT drops the member), judged by the rows of `rows` (FLOOR_ROWS) as compiled and
        confirmed, against the plan-gated protection answer unless `env` replaces it."""
        slug = slug or self.FLOOR
        rows = self.FLOOR_ROWS if rows is None else rows
        policy = self.write_policy(derivation={}, derived_repositories=rows)
        facts = {"state": "OPEN", "baseRefName": base, "headRefName": "issue-9-topic",
                 "headRefOid": self.HEAD_SHA, "mergeStateStatus": "CLEAN",
                 "url": f"https://github.com/{slug}/pull/9", "statusCheckRollup": rollup}
        if rollup is ABSENT:
            del facts["statusCheckRollup"]
        pinned = f" --match-head-commit {self.HEAD_SHA}" if pin else ""
        return self.run_guard(
            f"gh pr merge 9 --repo {slug} --merge{pinned} --delete-branch",
            cwd=self.make_repo(f"git@github.com:{slug}.git"),
            guard_args=("--gh-bin", str(self.fake_gh), "--policy", str(policy), *guard_args),
            env={**self.rows_env(rows), "FAKE_PROTECTION_MODE": "http_error",
                 "FAKE_PR_JSON": json.dumps(facts), **(env or {})})

    def test_the_floor_allows_a_merge_whose_declared_checks_are_green(self):
        """Issue 552 D2, D3: every declared check named and green allows the merge;
        SKIPPED and NEUTRAL count, so does a green StatusContext, and an entry naming no
        declared check is ignored."""
        for rollup in (
            [self.check_run(self.BUILD), self.check_run(self.LINT)],
            [self.check_run(self.BUILD, conclusion="SKIPPED"), self.status_context(self.LINT)],
            [self.check_run("optional", conclusion="FAILURE"),
             self.check_run(self.BUILD, conclusion="NEUTRAL"),
             self.status_context("deploy", state="PENDING"), self.check_run(self.LINT)],
        ):
            with self.subTest(rollup=rollup):
                result = self.floor_merge(rollup)
                self.assertEqual(0, result.returncode, result.stderr)

    def test_the_floor_refuses_naming_its_first_failure(self):
        """Issue 552 D3, D7, D11, D12: the head flag, then a readable rollup, then each
        declared check in row order; each refusal names only its problem."""
        build, lint = self.check_run(self.BUILD), self.status_context(self.LINT)
        missing = f"{self.UNPROTECTED}, and the declared required check {self.BUILD} is missing "
        not_green = f"{self.UNPROTECTED}, and the declared required check {{}} is not green ({{}})"
        unreadable = "lifecycle guard: unsafe merge: cannot read the PR check rollup"
        cases = (
            ("no head flag", [build, lint], False, f"{self.UNPROTECTED}, so the merge must "
             "carry --match-head-commit with the reviewed PR head"),
            ("missing", [lint], True, missing + "from the PR's check rollup"),
            ("empty", [], True, missing + "from the PR's check rollup"),
            ("pending", [self.check_run(self.BUILD, "IN_PROGRESS", None), lint], True,
             not_green.format(self.BUILD, "CheckRun IN_PROGRESS/none")),
            ("no conclusion", [{"__typename": "CheckRun", "name": self.BUILD,
                                "status": "QUEUED"}, lint], True,
             not_green.format(self.BUILD, "CheckRun QUEUED/none")),
            ("failed", [self.check_run(self.BUILD, conclusion="FAILURE"), lint], True,
             not_green.format(self.BUILD, "CheckRun COMPLETED/FAILURE")),
            ("pending status", [build, self.status_context(self.LINT, "PENDING")], True,
             not_green.format(self.LINT, "StatusContext PENDING")),
            ("red duplicate", [build, self.check_run(self.BUILD, conclusion="CANCELLED"), lint],
             True, not_green.format(self.BUILD, "CheckRun COMPLETED/CANCELLED")),
            ("row order", [self.status_context(self.LINT, "FAILURE"),
                           self.check_run(self.BUILD, conclusion="FAILURE")], True,
             not_green.format(self.BUILD, "CheckRun COMPLETED/FAILURE")),
            ("escaped", [self.check_run(self.BUILD, "IN\nPROGRESS", None), lint], True,
             not_green.format(self.BUILD, "CheckRun IN\\nPROGRESS/none")),
            ("absent", ABSENT, True, unreadable),
            ("null", None, True, unreadable),
            ("a string", "green", True, unreadable),
            ("an entry that is not an object", [build, self.LINT], True, unreadable),
            ("a CheckRun without a name", [build, lint, {"__typename": "CheckRun",
                                                         "status": "COMPLETED",
                                                         "conclusion": "SUCCESS"}], True,
             unreadable),
            ("a StatusContext without a context", [build, lint, {
                "__typename": "StatusContext", "state": "SUCCESS"}], True, unreadable),
            ("a name that is not a string", [build, lint, self.check_run(7)], True, unreadable),
            ("another typename", [build, lint, {"__typename": "Commit", "name": self.LINT}],
             True, unreadable),
        )
        for name, rollup, pin, line in cases:
            with self.subTest(case=name):
                self.assertEqual(line, self.refusal_line(self.floor_merge(rollup, pin=pin)))

    def test_readable_protection_governs_a_repository_with_declared_checks(self):
        """Issue 552 D2: a protection read that exits 0 runs today's predicate, and the
        declared checks are not consulted."""
        allowed = self.floor_merge([], env={"FAKE_PROTECTION_MODE": "ok"})
        self.assertEqual(0, allowed.returncode, allowed.stderr)
        refused = self.floor_merge(
            [self.check_run(self.BUILD), self.check_run(self.LINT)],
            env={"FAKE_PROTECTION_MODE": "ok", "FAKE_PROTECTION_JSON": (
                '{"required_status_checks":{"contexts":[]},"enforce_admins":{"enabled":true}}')})
        self.assertTrue(self.refusal_line(refused).startswith(
            "lifecycle guard: protection predicate failed"), refused.stderr)

    def test_every_other_protection_answer_keeps_its_refusal(self):
        """Issue 552 D2, AC2: with declared checks and a green rollup, every answer but the
        plan-gated one keeps the refusal it gets without the floor."""
        green = [self.check_run(self.BUILD), self.check_run(self.LINT)]
        docs = "https://docs.github.com/rest/branches/branch-protection#get-branch-protection"

        def body(message, status):
            return json.dumps({"message": message, "documentation_url": docs,
                               "status": status}, separators=(",", ":"))

        for name, env, prefix in (
            ("nonzero", {"FAKE_PROTECTION_MODE": "nonzero"}, "fake protection failure"),
            ("404", {"FAKE_PROTECTION_JSON": body("Branch not protected", "404")},
             "gh: Branch not protected (HTTP 404); stdout="),
            ("admin 403", {"FAKE_PROTECTION_JSON": body("Must have admin rights to "
                                                         "Repository.", "403")},
             "gh: Must have admin rights to Repository. (HTTP 403); stdout="),
            ("rate limit 403", {"FAKE_PROTECTION_JSON": body("API rate limit exceeded for "
                                                              "user ID 1.", "403")},
             "gh: API rate limit exceeded for user ID 1. (HTTP 403); stdout="),
            ("numeric status", {"FAKE_PROTECTION_JSON": body(self.PLAN_GATED_MESSAGE, 403)},
             "gh: HTTP 403; stdout="),
            ("not JSON", {"FAKE_PROTECTION_JSON": self.PLAN_GATED_MESSAGE},
             "gh: HTTP 403; stdout=Upgrade to GitHub Pro"),
        ):
            with self.subTest(answer=name):
                line = self.refusal_line(self.floor_merge(green, env=env))
                self.assertTrue(line.startswith(self.LOOKUP_FAILED + prefix), line)
        timed_out = self.floor_merge(green, env={"FAKE_PROTECTION_MODE": "timeout"},
                                     guard_args=("--child-timeout-seconds", "0.5"))
        self.assertEqual("lifecycle guard: protection lookup timed out",
                         self.refusal_line(timed_out))

    def test_the_plan_gated_answer_without_declared_checks_keeps_its_refusal(self):
        """Issue 552 D2, D7: a row declaring no check, a literal integration row and a
        repository with no row keep today's refusal of the plan-gated answer."""
        gated = (f"{self.LOOKUP_FAILED}gh: {self.PLAN_GATED_MESSAGE} (HTTP 403); "
                 f'stdout={{"message":"{self.PLAN_GATED_MESSAGE}"')
        green = [self.check_run(self.BUILD), self.check_run(self.LINT)]
        literal = "fagenorn/literal-floor"
        base = self.write_base(integration_bases={literal: "dev"})
        for name, slug, rows, args in (
            ("no declared check", self.FLOOR,
             {self.FLOOR: {**self.FLOOR_ROWS[self.FLOOR], "required_checks": []}}, ()),
            ("a literal integration row", literal, {}, ("--base-policy", str(base))),
            ("no row", "fagenorn/tool", {}, ()),
        ):
            with self.subTest(case=name):
                line = self.refusal_line(
                    self.floor_merge(green, slug=slug, rows=rows, guard_args=args))
                self.assertTrue(line.startswith(gated), line)

    def test_declared_checks_leave_the_integration_base_and_the_release_arm_alone(self):
        """Issue 552 D2, AC2: with checks declared, a feature merge into the declared
        integration base stays exempt, and the release arm keeps its own rollup gate."""
        exempt = self.floor_merge([], slug=self.STAGED, base="dev")
        self.assertEqual(0, exempt.returncode, exempt.stderr)
        policy = self.write_policy(derivation={}, derived_repositories=self.FLOOR_ROWS)
        release = self.run_guard(
            f"gh pr merge 1 --repo {self.STAGED} --merge",
            cwd=self.make_repo(f"git@github.com:{self.STAGED}.git"),
            guard_args=("--gh-bin", str(self.fake_gh), "--policy", str(policy)),
            env={**self.rows_env(self.FLOOR_ROWS), **self.release_env(
                url=f"https://github.com/{self.STAGED}/pull/1",
                statusCheckRollup=[self.check_run("unrelated")])})
        self.assertEqual(0, release.returncode, release.stderr)

```

- [ ] **Step 2: Run the tests and watch them fail**

Run the Guard suite (root § Global Constraints, timeout 3600 s) with `-k floor -k plan_gated -k protection -k declared_checks` after the test file.
Expected: FAIL in `test_the_floor_allows_a_merge_whose_declared_checks_are_green` (each subtest exits 2 with `protection lookup failed`) and in `test_the_floor_refuses_naming_its_first_failure` (each line is `protection lookup failed: …`). The other four new tests pin unchanged verdicts and already pass, and so does every existing `protection` test.

- [ ] **Step 3: Write the minimal implementation**

In `home/common/claude-code/lifecycle_guard.py`:

1. Directly after the `HEAD_COMMIT` assignment, add the constants with these comments. The predicate must be rendered from the green constants: no other line of the file spells the green conclusions or states.

```python
# GitHub's answer to a branch-protection read on a plan that cannot protect the
# branch (issue 552 D2): `gh api` exits non-zero and writes this body to stdout.
PLAN_GATED_STATUS = "403"
PLAN_GATED_MESSAGE = (
    "Upgrade to GitHub Pro or make this repository public to enable this feature."
)
# The one home of a green check-rollup entry (issue 552 D6): the plan-gated floor
# reads it, and the release arm's jq predicate is rendered from it.
GREEN_CHECK_RUN_STATUS = "COMPLETED"
GREEN_CHECK_RUN_CONCLUSIONS = ("SUCCESS", "SKIPPED", "NEUTRAL")
GREEN_STATUS_CONTEXT_STATE = "SUCCESS"
```

   `RELEASE_ROLLUP_PREDICATE` follows, built by concatenation: `'(.statusCheckRollup | type) == "array" '`, `"and (.statusCheckRollup | length) > 0 "`, `"and all(.statusCheckRollup[]; "`, then `f'(.__typename == "CheckRun" and .status == "{GREEN_CHECK_RUN_STATUS}" and ('`, then `" or ".join(f'.conclusion == "{conclusion}"' for conclusion in GREEN_CHECK_RUN_CONCLUSIONS)`, then `")) "`, then `f'or (.__typename == "StatusContext" and .state == "{GREEN_STATUS_CONTEXT_STATE}"))'`.

2. `Context.__init__`: after the `integration_bases` block, set `self.required_checks` as the Invariants state. Comment: `# A confirmed row's declared checks are the plan-gated merge floor's input (issue 552 D2); a row with a problem, a literal row and no row declare none.`

3. `validate_merge`: replace `if protection_lookup.returncode != 0: return block_child_failure("protection lookup failed", protection_lookup)` with a block. When `context.required_checks` is non-empty and `plan_gated_answer(protection_lookup.stdout)` holds, it computes `problem = merge_floor_problem(pr_facts, base, head_commit, context.required_checks)` and returns `refuse("merge", problem)` when the problem is not None, else `0`. Otherwise it returns the unchanged `block_child_failure` call. Comment: `# Issue 552 D2: only the plan-gated answer, for a row that declares checks, is judged by the floor; every other failed read keeps its refusal.`

4. Directly after `mergeability_problem`, add `plan_gated_answer`, `rollup_entry_name`, `rollup_entry_green`, `observed_state` and `merge_floor_problem`, as the Invariants define. `plan_gated_answer` catches `ValueError` from `json.loads` and returns False. Docstrings:
   - `plan_gated_answer`: `Whether a failed protection read's stdout is GitHub's plan-gated answer (issue 552 D2): a JSON object whose status is PLAN_GATED_STATUS and whose message is PLAN_GATED_MESSAGE.`
   - `rollup_entry_name`: `The check a rollup entry names: a CheckRun's name or a StatusContext's context when it is a string, else None, which makes the rollup unreadable.`
   - `rollup_entry_green`: `Whether a rollup entry is green by the one rule the release arm's predicate is rendered from (issue 552 D6).`
   - `observed_state`: `A non-green entry as a refusal shows it: CheckRun <status>/<conclusion> or StatusContext <state>, each fact escaped when a string and none otherwise (issue 552 D12).`
   - `merge_floor_problem`: `Why the plan-gated floor refuses this feature merge, or None (issue 552 D3, D11).` A second paragraph says it runs only after the protection read of `base` gave the plan-gated answer for a confirmed row declaring `required_checks`, starts no child, and judges in order the `--match-head-commit` flag (`head_commit`, None without it, which `mergeability_problem` has already held to `headRefOid`), a readable rollup and each declared check in row order.

5. `validate_release_merge`: the jq argv's program becomes `RELEASE_ROLLUP_PREDICATE`. Its docstring and refusal text are unchanged.

In `home/common/claude-code/README.md`:

1. `## Adjudicated verbs`, first paragraph: replace `admin enforcement on the feature arm, while` with `admin enforcement on the feature arm (or, where the forge answers that the repository's plan cannot protect the branch, the plan-gated floor below), while`.
2. Insert this paragraph between the `**mergeability check**` paragraph and the paragraph that begins `A refusal that lies in the command's text`, with blank lines around it:

```markdown
The **plan-gated floor** (issue 552) replaces that protection demand for one answer only. When the feature arm's protection read of the default branch exits non-zero, the guard parses its stdout, gh's response body, and never its stderr: the **plan-gated answer** is a JSON object whose `status` is the string `403` and whose `message` is exactly `Upgrade to GitHub Pro or make this repository public to enable this feature.`. Only with that answer, and only when the repository's confirmed derived row declares at least one required check (a row with a problem, a literal `integration_bases` row and a repository without a row declare none), is the merge judged by the floor; every other non-zero answer (a 404 `Branch not protected`, a 403 for missing admin rights or a rate limit, a body that is not JSON, the plan-gated answer without declared checks) keeps `protection lookup failed: <diagnostic>`, and a timeout or a readable protection object keeps its verdict. The floor starts no child and reads only the PR lookup's facts, and the first failure is the verdict: the merge must carry `--match-head-commit`, which the mergeability check has held to the PR's `headRefOid`, so the rollup judged is the head GitHub merges (`unsafe merge: <base> cannot be protected on this repository's plan, so the merge must carry --match-head-commit with the reviewed PR head`); `statusCheckRollup` must be a list of objects, each a `CheckRun` with a string `name` or a `StatusContext` with a string `context` (`unsafe merge: cannot read the PR check rollup`); then each declared check, in row order, must be named exactly by at least one entry (`unsafe merge: <base> cannot be protected on this repository's plan, and the declared required check <name> is missing from the PR's check rollup`), and every entry naming it must be green (`unsafe merge: <base> cannot be protected on this repository's plan, and the declared required check <name> is not green (<observed>)`, the first non-green entry as `CheckRun <status>/<conclusion>` or `StatusContext <state>`, a fact that is not a string shown as `none`). Entries naming no declared check are ignored. Green has one home, from which the release arm's jq predicate is rendered: a `CheckRun` whose `status` is `COMPLETED` and whose `conclusion` is `SUCCESS`, `SKIPPED` or `NEUTRAL`, or a `StatusContext` whose `state` is `SUCCESS`. The floor is weaker than forge protection, because nothing stops a merge made outside the guard; a forge that later protects the branch answers the read with exit 0, and the protection demand governs again with no contract change.
```

3. In the refusal paragraph's list of state refusals, replace `` a `--match-head-commit` that is not the PR head, an unreadable `` with `` a `--match-head-commit` that is not the PR head, every plan-gated floor refusal, an unreadable ``.
4. `## Guard/core decision`: after `future core admission waits for the named enforcement and conformance work.`, add ` The plan-gated floor (issue 552) is a native-guard exception of the kind issue 116 D6 lists as a gap, accepted by the owner for a repository whose forge cannot protect its default branch; it is not core-admission evidence.`

- [ ] **Step 4: Verify**

Write this script to `release_predicate_gate.py` under the directory `launch-scope scratch` prints (D13), then run `python3 -I <that path> home/common/claude-code/lifecycle_guard.py` (timeout 60 s).

```python
import importlib.util
import sys

BASE = ('(.statusCheckRollup | type) == "array" and (.statusCheckRollup | length) > 0 '
        'and all(.statusCheckRollup[]; (.__typename == "CheckRun" and .status == "COMPLETED" '
        'and (.conclusion == "SUCCESS" or .conclusion == "SKIPPED" or .conclusion == "NEUTRAL")) '
        'or (.__typename == "StatusContext" and .state == "SUCCESS"))')
spec = importlib.util.spec_from_file_location("lifecycle_guard_gate", sys.argv[1])
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
print("identical" if guard.RELEASE_ROLLUP_PREDICATE == BASE else "differs")
sys.exit(0 if guard.RELEASE_ROLLUP_PREDICATE == BASE else 1)
```

Expected: `identical`, exit 0. At the base commit the module has no `RELEASE_ROLLUP_PREDICATE`, so the script exits 1 with an `AttributeError`.

Run: `if grep -q '.conclusion == "SKIPPED"' home/common/claude-code/lifecycle_guard.py; then exit 1; fi`
Expected: exit 0, because the release program is no longer spelled out.

After `git add` of the three files, run the full Guard suite (root § Global Constraints, timeout 3600 s). It builds first.
Expected: PASS, `OK`, Task 2's count plus six tests.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/lifecycle_guard.py tests/test_claude_permission_guard.py home/common/claude-code/README.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "feat(issue-552/T3): judge an unprotectable default branch by its declared checks" \
  -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64,64],"id":3,"records":[{"bounds":[{"added_lines":200,"boundary":"all","deleted_lines":25,"record_bytes":32768,"support":{"covers":["r2b","r3a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3a","last_task":3,"owner":3,"path":"home/common/claude-code/lifecycle_guard.py"},{"bounds":[{"added_lines":300,"boundary":"all","deleted_lines":18,"record_bytes":40960,"support":{"covers":["r2d","r3b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3b","last_task":4,"owner":3,"path":"tests/test_claude_permission_guard.py"},{"bounds":[{"added_lines":12,"boundary":"all","deleted_lines":8,"record_bytes":59392,"support":{"covers":["r2e","r3c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3c","last_task":4,"owner":3,"path":"home/common/claude-code/README.md"}]}}
```
