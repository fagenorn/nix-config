# Task 4: Neutrality checker test and the CLAUDE.md sentence

**Files:**
- Modify: `tests/test_transaction_core_sweep.py` (add imports, the checker and
  `NeutralityTest` above the `if __name__ == "__main__":` block)
- Modify: `CLAUDE.md` ("Agent helper package" paragraph, one sentence)

**Interfaces:**
- Consumes: the module object `agent_tools.transaction_core` (Tasks 1–2), read through
  `inspect.getsource`. Nothing else from it.
- Produces: `neutrality_findings(source: str) -> list[tuple[int, str]]` — `(line, word)`
  pairs in source order; lives in the test file only (per D11, D14).

**Invariants:**
- Comments (by `tokenize`) and module/class/function docstrings (located by `ast`) never
  produce findings; every other token — identifiers and string literal contents alike —
  is split into lowercase alphanumeric words and matched whole against the three D11
  lists (per D11).
- The shipped module yields no findings; a provider verb planted in code yields exactly
  that word; the same word planted only in a comment or docstring yields nothing.
- `CLAUDE.md` gains one sentence and no other change (per D12).

- [ ] **Step 1: Write the checker and its failing-capable tests** — in
`tests/test_transaction_core_sweep.py`, extend the imports with
`import ast`, `import inspect`, `import io`, `import re`, `import tokenize` and
`from agent_tools import transaction_core`, then add above the `__main__` block:

```python
PROJECT_NAMES = frozenset({"nix", "nixos", "darwin", "fagenorn", "palmier", "nodo", "argus"})
PROVIDER_NAMES = frozenset({
    "github", "gitlab", "gh", "git", "ghcr", "docker", "oci", "railway", "launchd",
    "launchctl", "plist", "homebrew", "brew", "cachix", "sops", "anthropic", "claude",
    "codex"})
PROVIDER_VERBS = frozenset({
    "push", "merge", "tag", "deploy", "switch", "restart", "rebuild", "upload", "rebase",
    "checkout"})
FORBIDDEN_WORDS = PROJECT_NAMES | PROVIDER_NAMES | PROVIDER_VERBS
_NOT_CODE = frozenset({tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT,
                       tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER})


def _docstring_starts(source):
    starts = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                starts.add((first.value.lineno, first.value.col_offset))
    return starts


def neutrality_findings(source):
    """Every forbidden whole word in `source`'s code, comments and docstrings excluded."""
    docstrings = _docstring_starts(source)
    findings = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in _NOT_CODE:
            continue
        if token.type == tokenize.STRING and token.start in docstrings:
            continue
        for word in re.split(r"[^0-9a-z]+", token.string.lower()):
            if word in FORBIDDEN_WORDS:
                findings.append((token.start[0], word))
    return findings


class NeutralityTest(unittest.TestCase):
    def setUp(self):
        self.source = inspect.getsource(transaction_core)

    def test_the_shipped_module_names_no_project_provider_or_provider_verb(self):
        self.assertEqual(neutrality_findings(self.source), [])

    def test_a_provider_verb_planted_in_code_is_found(self):
        planted = self.source + "\n\ndef deploy_everything():\n    return None\n"
        self.assertEqual([word for _, word in neutrality_findings(planted)], ["deploy"])

    def test_the_same_word_in_a_comment_or_docstring_is_not_code(self):
        for planted in ("\n# deploy the candidate\n",
                        '\n\ndef neutral():\n    """Deploy nothing."""\n    return None\n'):
            with self.subTest(planted=planted):
                self.assertEqual(neutrality_findings(self.source + planted), [])

    def test_matching_is_by_whole_word_and_covers_string_literals(self):
        self.assertEqual(neutrality_findings("associated = 'pushed'\n"), [])
        self.assertEqual(neutrality_findings("where = 'git-tag'\n"), [(1, "git"), (1, "tag")])
```

- [ ] **Step 2: Run the tests**

Run: `PYTHONPATH=python python3 -m unittest -v tests/test_transaction_core_sweep.py 2>&1 | tail -4`
Expected: `OK` (7 tests). If
`test_the_shipped_module_names_no_project_provider_or_provider_verb` fails, the finding
names a line of `python/agent_tools/transaction_core.py`: rename that identifier or
reword that message in the module (the Global Constraints forbid it) — never widen the
checker's exemptions or shrink the lists.

Falsifiability check (do not commit): temporarily append `deploy_marker = None` to
`python/agent_tools/transaction_core.py`, rerun, confirm the shipped-module test FAILS
naming `deploy`, then remove the line and confirm `git diff --quiet -- python/` exits 0.

- [ ] **Step 3: Add the CLAUDE.md sentence** — append to the end of the
"**Agent helper package.**" paragraph (after "…sends all new helper code to the
package."), on the same line, exactly:

`` `agent_tools.transaction_core` is the transaction core's first slice (#204): a library module with no command-table row and no caller until #125's cutover, holding caller-rooted transaction state under a closed schema and lifecycle.``

- [ ] **Step 4: Verify**

Run: `grep -c 'agent_tools.transaction_core' CLAUDE.md` — Expected: `1` (base prints `0`).

Run: `git diff --stat -- CLAUDE.md` — Expected: `1 file changed, 1 insertion(+), 1 deletion(-)`.

Run: `just agent-workflow-tests 2>&1 | tail -3` — Expected: `OK`.

Run: `just build 2>&1 | tail -5` — Expected: success.

- [ ] **Step 5: Commit**

```bash
git add tests/test_transaction_core_sweep.py CLAUDE.md
git commit -m "test(transaction-core): check the core names no project or provider (#204)"
```
