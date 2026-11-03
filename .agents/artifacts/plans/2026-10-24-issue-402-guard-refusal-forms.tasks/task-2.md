# Task 2: The accepted-forms clause on every text refusal; forms are true

Spec § Refusal message (all bullets), § Shape fixture (third bullet), § Test seams (Forms are true, Shape table, state refusals), § README; per D3, D6, D7, D8, D9, D12, D13. After this task every refusal of the five operations that lies in the command's text ends `; accepted: <form>[; or <form>…]` and, for the four operations that take a scrub prefix, `; optional prefix: unset GITHUB_TOKEN && | env -u GITHUB_TOKEN`; a refusal of the repository or forge state prints only its problem. Problems keep Task 1's texts (Task 3 renames them), so every existing assertion still holds.

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py`
- Modify: `tests/test_claude_permission_guard.py`
- Modify: `tests/fixtures/guarded-command-shapes.json`
- Modify: `home/common/claude-code/README.md`

**Interfaces:**
- Consumes: Task 1's `FORM_TABLE`, `CompiledOperation`, `compile_form_table`, `match_form`, `form_problem(operation, compiled, text)`, the validators' `compiled` parameter, and the suite's `HEAD_SHA`; base `GH_ENV_TOKEN_NAMES`, `SCRUB_PREFIXES`, `authorized_bases`, `OPERATION_LABELS`, `DEADLINE_REFUSAL`, `block`, `block_child_failure`; in the suite `SHAPES`, `assert_shape_verdict`, `make_repo`, `tagged_repo(slug, tag=…, annotated=…)`, `run_guard`, `release_env(**overrides)`, `NODO`.
- Produces:
  - `BRANCH_VALIDATION_TIMEOUT = "branch validation timed out"`, returned by `branch_name_problem` and refused by `validate_branch_delete` on a `git check-ref-format` timeout.
  - `prefix_clause() -> str`, `declared_integration(context) -> str | None`, `accepted_forms(compiled, context, form_ids=None) -> list[str]`, `refuse(operation, problem, forms=()) -> int` (code in Step 3a).
  - `validate_tag_push(tag, context, compiled)` and `validate_release_merge(pr_facts, base, integration_base, context, compiled)`.
  - Fixture member `form_values`; suite attributes `FORM_VALUES`, `PREFIX_CLAUSE` and helpers `refusal_line(result)`, `accepted_clause(line)`, `form_spellings(form)`, `assert_forms_pass(line, cwd, label)`.

**Invariants:**
- Message shape (D3, D8): `lifecycle guard: unsafe <label>: <problem>`, then for a text refusal `; accepted: ` and the forms joined by `; or `, then `; optional prefix: unset GITHUB_TOKEN && | env -u GITHUB_TOKEN` when the operation's `scrub_prefix` property is true. The clause spellings derive from `SCRUB_PREFIXES` and `GH_ENV_TOKEN_NAMES[0]`, never from a new literal.
- Forms (D6): table order; before any PR lookup every form of the operation, except a noted form (the merge's release form), listed only where `declared_integration(context)` names a branch; after the lookup exactly the arm the PR admits, or none.
- Fills (D7): `<slug>` → `context.repository`; `<base>` → one form per member of `sorted(authorized_bases(…))` once `context.base_branch` resolved; the note's `<integration>`/`<default>` → the declared and default branches; every other slot stays a placeholder; a recognition refusal (no `Context`) fills nothing.
- Recognition refusals keep their problem (`NOT_COMMAND_POSITION`'s quoting advice, the `INVOCATION_FORM_HINT` ending) and gain the clause; `-C` appears in no form (D9). No `Context` is built for them.
- Every `unsafe <operation>` refusal goes through `refuse`, except the raise-label refusal (no form table) and `block_child_failure`'s rollup refusal (a state refusal). Verdicts and problem texts are Task 1's.

- [ ] **Step 1: Write the failing tests**

1. In `tests/fixtures/guarded-command-shapes.json`, add as the last top-level member (after `invocation_shapes`):

```json
  "form_values": {
    "<n>": "402",
    "<slug>": "fagenorn/nix-config",
    "<base>": "main",
    "<branch>": "issue-402-topic",
    "<sha>": "d4d9acc0505c73305b3e0ced029db43100bc0e8a",
    "<subject>": "feature (#402)",
    "<title>": "v1.2.3",
    "<body>": "Closes #402",
    "<vX.Y.Z>": "v1.2.3",
    "<path>": "/tmp/notes.md"
  }
```

2. In `tests/test_claude_permission_guard.py`, add `import re` to the imports (alphabetical, after `from pathlib import Path`), and in `assert_shape_verdict` add after the reason assertion, inside `if verdict["exit"] == 2:`:

```python
            self.assertIn("; accepted: ", result.stderr)
```

3. Add directly after `test_every_invocation_shape_gets_its_verdict`:

```python
    # ------------------------------------------------------------------
    # Accepted forms (issue 402 D3, D6, D7, D8, D13): a refusal that lies in the
    # command's text prints the forms that would pass where it was printed.
    # ------------------------------------------------------------------

    FORM_VALUES = SHAPES["form_values"]
    PREFIX_CLAUSE = "; optional prefix: unset GITHUB_TOKEN && | env -u GITHUB_TOKEN"

    def refusal_line(self, result):
        """The guard's one refusal line; the call must have exited 2."""
        self.assertEqual(2, result.returncode, result.stderr)
        lines = [line for line in result.stderr.splitlines()
                 if line.startswith("lifecycle guard: ")]
        self.assertEqual(1, len(lines), result.stderr)
        return lines[0]

    def accepted_clause(self, line):
        """(forms, prefixes) a refusal line prints: the forms split at `; or `, each
        trailing note dropped; each prefix with the space that joins it to a command."""
        self.assertIn("; accepted: ", line)
        clause = line.split("; accepted: ", 1)[1]
        forms_text, _, prefix_text = clause.partition("; optional prefix: ")
        forms = [re.sub(r" \([^()]*\)$", "", form) for form in forms_text.split("; or ")]
        prefixes = [spelling + " " for spelling in prefix_text.split(" | ")] if prefix_text else []
        return forms, prefixes

    def form_spellings(self, form):
        """Every spelling of `form`, one per subset of its `[...]` groups, filled from
        form_values; no placeholder may survive the fill."""
        parts = re.split(r"(\[[^\[\]]*\])", form)
        groups = [index for index, part in enumerate(parts) if part.startswith("[")]
        spellings = []
        for mask in range(1 << len(groups)):
            kept = "".join(
                (part[1:-1] if (mask >> groups.index(index)) & 1 else "")
                if index in groups else part
                for index, part in enumerate(parts)
            )
            spelling = " ".join(kept.split())
            for placeholder, value in self.FORM_VALUES.items():
                spelling = spelling.replace(placeholder, value)
            self.assertNotRegex(spelling, r"<[^<>\s]+>")
            spellings.append(spelling)
        return spellings

    def assert_forms_pass(self, line, cwd, label):
        """Every spelling of every form `line` prints exits 0 in `cwd`, bare and behind
        each printed prefix, with PR facts that fit the form's merge arm."""
        forms, prefixes = self.accepted_clause(line)
        for form in forms:
            for spelling in self.form_spellings(form):
                release_arm = (spelling.startswith("gh pr merge ")
                               and not spelling.endswith(" --delete-branch"))
                env = self.release_env() if release_arm else None
                for text in [spelling] + [prefix + spelling for prefix in prefixes]:
                    with self.subTest(label=label, form=text):
                        result = self.run_guard(text, cwd=cwd, env=env)
                        self.assertEqual(0, result.returncode, (text, result.stderr))

    def test_every_printed_form_is_allowed_where_printed(self):
        """Issue 402 AC3, D13: each operation's whole table, printed in the fixture
        repository, in a Nodo-row repository and with no context, and the forms the
        AC2 refusals print, filled from form_values, pass where they were printed."""
        fixture_slug = self.FORM_VALUES["<slug>"]
        fixture = self.tagged_repo(fixture_slug)
        nodo = self.tagged_repo(NODO)

        def provoking(slug):
            return {
                "push": "git push --force origin issue-402-topic",
                "PR creation": f"gh pr create --repo {slug} --draft",
                "merge": f"gh pr merge 402 --repo {slug} --squash",
                "release creation": f"gh release create v1.2.3 --repo {slug} --draft",
                "branch deletion": "git branch -d --force issue-402-topic",
            }

        recognition = {label: "xargs " + command
                       for label, command in provoking(fixture_slug).items()}
        one_each = {"push": 2, "PR creation": 1, "merge": 1, "release creation": 1,
                    "branch deletion": 1}
        covered = set()
        for name, cwd, commands, counts in (
            ("fixture", fixture, provoking(fixture_slug), one_each),
            ("nodo", nodo, provoking(NODO), {**one_each, "PR creation": 2, "merge": 2}),
            ("no context", fixture, recognition, one_each),
        ):
            for label, command in commands.items():
                with self.subTest(context=name, label=label):
                    line = self.refusal_line(self.run_guard(command, cwd=cwd))
                    self.assertTrue(line.startswith(f"lifecycle guard: unsafe {label}: "), line)
                    forms, _ = self.accepted_clause(line)
                    self.assertEqual(counts[label], len(forms), line)
                    self.assert_forms_pass(line, cwd, label)
                    covered.add(label)
        self.assertEqual({"push", "PR creation", "merge", "release creation",
                          "branch deletion"}, covered)
        feature_into_dev = {"FAKE_PR_JSON": json.dumps({
            "state": "OPEN", "baseRefName": "dev", "headRefName": "issue-2342-topic",
            "url": f"https://github.com/{NODO}/pull/2342", "statusCheckRollup": []})}
        for label, cwd, command, env, count in (
            ("merge", nodo,
             f"gh pr merge 2342 --repo {NODO} --merge --match-head-commit {self.HEAD_SHA}",
             feature_into_dev, 1),
            ("push", fixture,
             "unset GITHUB_TOKEN; git push -q origin HEAD:issue-402-topic 2>&1 | tail -2",
             None, 2),
        ):
            with self.subTest(context="AC2", label=label):
                line = self.refusal_line(self.run_guard(command, cwd=cwd, env=env))
                forms, _ = self.accepted_clause(line)
                self.assertEqual(count, len(forms), line)
                self.assert_forms_pass(line, cwd, label)

    def test_text_refusals_list_the_forms_their_facts_admit(self):
        """Issue 402 D6, D7, D8, D9: the forms follow the context and, after the PR
        lookup, the arm the PR admits; branch deletion prints no prefix clause."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        feature = ('gh pr merge <n> --repo {slug} --merge [--subject "<subject>"] '
                   "[--match-head-commit <sha>] --delete-branch")
        release = ('gh pr merge <n> --repo {slug} --merge [--subject "<subject>"] '
                   "[--match-head-commit <sha>] (only dev into main)")
        create = ("gh pr create --repo {slug} --base {base} --head <branch> "
                  '--title "<title>" --body "<body>"')
        push = "git push origin refs/tags/<vX.Y.Z>; or git push [-u] origin <branch>"

        def pr(head, base):
            return {"FAKE_PR_JSON": json.dumps({
                "state": "OPEN", "baseRefName": base, "headRefName": head,
                "url": f"https://github.com/{NODO}/pull/7", "statusCheckRollup": []}),
                "FAKE_PROTECTION_MODE": "nonzero"}

        for command, cwd, env, forms in (
            ("gh pr merge 7 --repo fagenorn/nix-config --squash", repo, None,
             feature.format(slug="fagenorn/nix-config")),
            (f"gh pr merge 7 --repo {NODO} --squash", nodo, None,
             feature.format(slug=NODO) + "; or " + release.format(slug=NODO)),
            ("xargs gh pr merge 7", repo, None, feature.format(slug="<slug>")),
            ("gh pr create --repo fagenorn/nix-config --draft", repo, None,
             create.format(slug="fagenorn/nix-config", base="main")),
            (f"gh pr create --repo {NODO} --draft", nodo, None,
             create.format(slug=NODO, base="dev") + "; or "
             + create.format(slug=NODO, base="main")),
            ("xargs gh pr create", repo, None, create.format(slug="<slug>", base="<base>")),
            ("/usr/bin/git push origin issue-402-topic", repo, None, push),
            # After the lookup the release form on a feature PR lists the feature arm,
            (f"gh pr merge 7 --repo {NODO} --merge", nodo, pr("issue-7-topic", "dev"),
             feature.format(slug=NODO)),
            # and --delete-branch on the integration-into-default PR the release arm.
            (f"gh pr merge 7 --repo {NODO} --merge --delete-branch", nodo, pr("dev", "main"),
             release.format(slug=NODO)),
        ):
            with self.subTest(command=command):
                line = self.refusal_line(self.run_guard(command, cwd=cwd, env=env))
                self.assertTrue(line.endswith("; accepted: " + forms + self.PREFIX_CLAUSE), line)
        # D9: an invocation-form refusal keeps its hint, then the clause.
        line = self.refusal_line(self.run_guard("/usr/bin/git push origin x", cwd=repo))
        self.assertIn("carry a directory only as git -C <dir>; accepted: ", line)
        # No arm remains for a permanent head that neither arm admits.
        for command in (f"gh pr merge 7 --repo {NODO} --merge --delete-branch",
                        f"gh pr merge 7 --repo {NODO} --merge"):
            with self.subTest(command=command, head="main", base="dev"):
                line = self.refusal_line(self.run_guard(command, cwd=nodo, env=pr("main", "dev")))
                self.assertNotIn("accepted:", line)
        line = self.refusal_line(self.run_guard("git branch -d --force issue-402-topic"))
        self.assertTrue(line.endswith("; accepted: git branch -d <branch>"), line)

    def test_state_refusals_print_no_accepted_forms(self):
        """Issue 402 D3: a refusal of the repository or forge state names only its
        problem, since no spelling would pass there."""
        repo = self.make_repo("git@github.com:fagenorn/nix-config.git")
        foreign = self.make_repo("git@github.com:someoneelse/tool.git")
        lightweight = self.tagged_repo("fagenorn/nix-config", tag="v2.0.0", annotated=False)
        nodo = self.make_repo(f"git@github.com:{NODO}.git")
        merge = "gh pr merge 2342 --repo fagenorn/nix-config --merge --delete-branch"
        for command, cwd, env, problem in (
            ("git push origin issue-402-topic", foreign, None,
             "unsafe push: repository someoneelse/tool is outside standing authorization"),
            ("git push origin main", repo, None,
             "unsafe push: refusing to push the default branch main"),
            ("git push origin refs/tags/v2.0.0", lightweight, None,
             "unsafe push: v2.0.0 is not an existing annotated tag"),
            ('gh pr create --repo fagenorn/nix-config --base main --head main --title "x" '
             '--body "y"', repo, None, "unsafe PR creation: head and base must differ"),
            (merge, repo, {"FAKE_PR_MODE": "nonzero"}, "PR lookup failed"),
            (merge, repo, {"FAKE_PROTECTION_MODE": "nonzero"}, "protection lookup failed"),
            (f"gh pr merge 1484 --repo {NODO} --merge", nodo,
             self.release_env(statusCheckRollup=[]),
             "unsafe merge: the PR's check rollup is not entirely green"),
        ):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=cwd, env=env)
                self.assertEqual(2, result.returncode, command)
                self.assertIn(f"lifecycle guard: {problem}", result.stderr)
                self.assertNotIn("accepted:", result.stderr)
                self.assertNotIn("optional prefix:", result.stderr)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the guard-suite invocation with `-k test_every_printed_form_is_allowed_where_printed -k test_text_refusals_list_the_forms_their_facts_admit -k test_every_guarded_command_shape_gets_its_verdict -k test_every_invocation_shape_gets_its_verdict -k test_state_refusals_print_no_accepted_forms`.
Expected: FAIL in the first four — no refusal yet contains `; accepted: `. `test_state_refusals_print_no_accepted_forms` passes already: it pins what must not change.

- [ ] **Step 3: Write the minimal implementation**

**3a. The formatter** (exact wire format; write it as given), after `form_problem`:

```python
def prefix_clause():
    """`optional prefix: …`: the one-name scrub spellings of the first credential
    name, in SCRUB_PREFIXES order (issue 402 D8)."""
    name = GH_ENV_TOKEN_NAMES[0]
    spellings = [
        spelling.rstrip() for spelling in SCRUB_PREFIXES
        if spelling.split() in (["unset", name, "&&"], ["env", "-u", name])
    ]
    return "optional prefix: " + " | ".join(spellings)


def declared_integration(context):
    """The context's integration branch when it declares one distinct from its
    resolved default branch, else None (also with no context)."""
    if context is None or context.base_branch is None:
        return None
    integration = context.integration_bases.get(context.repository)
    if integration is None or integration == context.base_branch:
        return None
    return integration


def accepted_forms(compiled, context, form_ids=None):
    """The accepted forms a text refusal prints, in table order (issue 402 D6, D7).

    `form_ids` names the forms the refusal's facts admit; None means before any
    PR lookup: every form, a noted form only where `declared_integration` names
    a branch. `context` fills `<slug>`, `<base>` (one form per authorized base)
    and the note; None fills nothing.
    """
    integration = declared_integration(context)
    printed = []
    for form in compiled.forms:
        if form_ids is None:
            if form.note is not None and integration is None:
                continue
        elif form.id not in form_ids:
            continue
        text = form.template
        if context is not None and context.repository is not None:
            text = text.replace("<slug>", context.repository)
        texts = [text]
        if "<base>" in text and context is not None and context.base_branch is not None:
            texts = [
                text.replace("<base>", base)
                for base in sorted(authorized_bases(
                    context.repository, context.base_branch, context.integration_bases))
            ]
        note = ""
        if form.note is not None:
            note = " (" + form.note.replace("<integration>", integration).replace(
                "<default>", context.base_branch) + ")"
        printed.extend(text + note for text in texts)
    return printed


def refuse(operation, problem, forms=()):
    """Print `operation`'s refusal and return 2 (issue 402 D3).

    With `forms` (a text refusal) the message continues `; accepted: ` and the
    forms joined by `; or `, then the prefix clause for an operation that takes
    a scrub prefix; without them (a refusal of the repository or forge state)
    it names only the problem.
    """
    message = f"unsafe {OPERATION_LABELS[operation]}: {problem}"
    if forms:
        message += "; accepted: " + "; or ".join(forms)
        if FORM_TABLE[operation]["scrub_prefix"]:
            message += "; " + prefix_clause()
    return block(message)
```

**3b. Route every refusal.** Text = `refuse(op, problem, accepted_forms(compiled, context))` unless a column says otherwise; state = `refuse(op, problem)`; problem texts unchanged.

| Function | Text refusals | State refusals |
|---|---|---|
| `validate_branch_delete` | form miss, dash-led, invalid name — forms `accepted_forms(compiled, None)` | `BRANCH_VALIDATION_TIMEOUT` |
| `validate_tag_push(tag, context, compiled)` | not a vMAJOR.MINOR.PATCH tag | tag lookup timed out; not an existing annotated tag |
| `validate_push` | form miss; `branch_name_problem` other than the timeout | ownership; the timeout; unresolvable default branch; default-branch push |
| `validate_pr_create` | form miss; `--repo` mismatch; head name other than the timeout; title or body; base outside the authorized ones | ownership; the timeout; unresolvable default branch; head equals base |
| `validate_release` | form miss; every slot check | ownership |
| `validate_merge` | form miss; `<n>`, `<slug>`, `<subject>`, `<sha>`; the release form where no integration branch is declared — forms `accepted_forms(compiled, context, ["feature"])`; feature arm with a permanent head when `head == integration_base`, `base == context.base_branch` and `declared_integration(context)` is set — forms `accepted_forms(compiled, context, ["release"])` | ownership; unresolvable default branch; unreadable PR base or head; PR base not authorized; a permanent head otherwise. Unlabelled lookup and predicate refusals stay `block`/`block_child_failure` as at base |
| `validate_release_merge(…, compiled)` | head/base mismatch while the head is not permanent (`head not in (context.base_branch, integration_base)`) — forms `accepted_forms(compiled, context, ["feature"])` | unreadable head; mismatch with a permanent head; the rollup (`block_child_failure`, unchanged) |
| `main` | a recognition `problem` for an operation in `FORM_TABLE` — `refuse(operation, problem, accepted_forms(table[operation], None))` | `DEADLINE_REFUSAL` (both sites) via `refuse(operation, DEADLINE_REFUSAL)`; the raise-label refusal stays `block` |

Pass `compiled` into `validate_tag_push` and `validate_release_merge`. In `branch_name_problem` return `BRANCH_VALIDATION_TIMEOUT` for the timeout, and use it in `validate_branch_delete`'s timeout refusal.

**3c. README** (`home/common/claude-code/README.md`):
- In `## Allow surface and lifecycle guard`, the sentence "Such an invocation is refused before any repository lookup, the reason ending `run git and gh by name, and carry a directory only as git -C <dir>`, …": change "the reason ending" to "its problem ending" and add, after that code span, "and followed by the accepted-forms clause (`## Adjudicated verbs`)".
- In `## Adjudicated verbs`, add a paragraph after the one beginning "The forge adapter's two mutations": a refusal that lies in the command's text (each recognition refusal, a form the matcher refuses, a slot value, a merge arm while another arm remains) reads `lifecycle guard: unsafe <operation>: <problem>; accepted: <form>[; or <form>…]; optional prefix: unset GITHUB_TOKEN && | env -u GITHUB_TOKEN`, and branch deletion, which takes no prefix, omits the last clause; the forms come from `FORM_TABLE` in table order — before any PR lookup the whole table, except that the merge's release form, noted `(only <integration> into <default>)`, is listed only where the repository declares an integration branch distinct from its resolved default branch, and after the lookup only the arm the PR admits, none when its head is a permanent branch no arm fits; with a repository context `<slug>` becomes the detected slug and, once the default branch resolved, `<base>` one alternative per authorized base and the note names both branches (`only dev into main`), every other slot stays a placeholder, and a recognition refusal, which builds no context, fills nothing and lists the merge's feature form alone; the clause's two spellings stand for the whole accepted prefix set (`unset N && `, `unset N M && `, `env -u N `, `env -u N -u M `, `N` and `M` distinct members of `GITHUB_TOKEN`, `GH_TOKEN`); a refusal of the repository or the forge state (authorization and row problems, an unresolvable default branch, a default-branch push, head equal to base, a tag that is not an existing annotated tag, every PR, protection and rollup lookup or predicate failure, timeouts, the invocation deadline) names only its problem, since no spelling would pass there.
- At the end of the shape-fixture sentence ("…holds the guard-only rows the `ship-issue` check never reads."), add that `form_values` (issue 402) is guard-only too: one value per guard placeholder, from which the guard suite fills and runs every form a refusal prints.

- [ ] **Step 4: Verify**

1. Run the full guard-suite invocation. Expected: `OK`, every test green.
2. One route for every operation refusal, multi-line calls included (the one `block` left is the raise-label refusal in `main`):

```bash
python3 - <<'EOF'
import re, sys
text = open("home/common/claude-code/lifecycle_guard.py", encoding="utf-8").read()
sites = len(re.findall(r'\bblock\(\s*f?"unsafe ', text))
sys.exit(0 if sites == 1 else f'{sites} block("unsafe ...") sites; only the raise-label refusal may remain')
EOF
```
3. README: `grep -qF 'optional prefix: unset GITHUB_TOKEN && | env -u GITHUB_TOKEN' home/common/claude-code/README.md && grep -qF 'form_values' home/common/claude-code/README.md || exit 1`
4. The shell-example run (it reads the fixture this task edited). Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/lifecycle_guard.py tests/test_claude_permission_guard.py tests/fixtures/guarded-command-shapes.json home/common/claude-code/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "feat(guard): text refusals print the accepted forms (issue 402)" \
  -m "<session trailers>"
```
