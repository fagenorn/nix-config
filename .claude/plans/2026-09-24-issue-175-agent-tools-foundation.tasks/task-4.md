# Task 4: agent-evidence ships as an isolated launcher

Decisions: D1, D2, D3, D4, D5, D7, D10, D11, D13; parent D2, D10, D13, D14, D15.
Spec sections "How each file moves (D2)", "The package and its build (D4)",
"Wiring into the home (D5)", "Test re-points (D7)" and "Living documents
(D10)". Work from the worktree root. `PK` = `python/agent_tools`,
`AS` = `home/common/agent-skills`,
`CC` = `home/common/claude-code/skills/codex-collaboration`.

**Files:**
- Move: `AS/scripts/agent-evidence.py` → `PK/agent_evidence.py`, using `git mv`
  (the mode is already 100644)
- Create: `lib/agent-tools.nix`
- Modify: `AS/default.nix`
- Modify: `AS/tests/test_agent_evidence.py`
- Modify: `AS/tests/test_workflow_skill_contracts.py` (one comment, L1774)
- Modify: `CC/DIFF-REVIEW.md` (L184, L193)
- Modify: `CC/evals/evals.json` (two strings)

**Interfaces:**
- Consumes: `agent_tools.canonical.reject_duplicate_keys` and
  `python/pyproject.toml`'s `project.name` and `project.version` (Task 1).
  `agent-workflow-tests` already assigns `PYTHONPATH`.
- Produces:
  - The module `agent_tools.agent_evidence`. It keeps every existing name except
    `_reject_duplicate_keys`, which it no longer defines.
  - `lib/agent-tools.nix`, a function of `{ pkgs }` that returns exactly
    `{ launchers }`, an attribute set from command name to launcher store path.
  - The built `~/.agents/bin/agent-evidence`, whose bytes are exactly the three
    lines below, followed by the trailing blank line that `writeShellScript`
    appends. Task 5's test matches this shape:
    ```
    #!<store bash>
    unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE
    exec <env store path>/bin/python3 -I -m agent_tools.agent_evidence "$@"
    ```

**Invariants:**
- The moved file differs from the original by exactly these edits (D2), and by
  nothing else:
  1. Line 1 (`#!/usr/bin/env python3`) is deleted.
  2. `from agent_tools.canonical import reject_duplicate_keys` is added as its
     own import group, one blank line after `from typing import Any, Sequence`.
     `Any` stays imported, because it has other uses.
  3. `def _reject_duplicate_keys` (L627–633) is deleted. Two blank lines still
     separate the neighbouring definitions.
  4. `_load_artifact` passes `object_pairs_hook=reject_duplicate_keys`, and still
     passes no `parse_constant`. This is D3's evidence row: NaN and Infinity
     stay accepted.
  5. `main` builds `argparse.ArgumentParser(prog="agent-evidence", description=__doc__)`.
- Installed `agent-evidence --help` and its no-argument usage error are
  byte-identical to the pre-move script run under the name `agent-evidence`
  (parent D15).
- `home.file` receives the launchers as a separate `lib.mkMerge` definition. A
  leftover hand-written `.agents/bin/agent-evidence` entry must fail evaluation
  as a conflicting definition (D5).
- `home.sessionPath` and `home.packages = [ pkgs.python3 ]` stay unchanged.
- Rename detection pairs the two paths, reported as `R` with a similarity of 95
  or more.

- [ ] **Step 0: Record the starting commit**

Run: `START=$(git rev-parse HEAD); B=$(mktemp -d); echo "$START $B"`. Keep both
values for Step 5.

- [ ] **Step 1: Re-point the tests and add the composition pins**

In `AS/tests/test_agent_evidence.py`:

- Replace `SCRIPT = Path(__file__).parents[1] / "scripts" / "agent-evidence.py"`
  with `MODULE = "agent_tools.agent_evidence"`.
- In `run_validator` and `run_document`, change each argv from
  `[sys.executable, str(SCRIPT), …]` to `[sys.executable, "-m", MODULE, …]`.
  The child inherits the recipe's `PYTHONPATH`.
- Add this method to `AgentEvidenceTest`, after `run_document`:

```python
    def run_text(self, kind: str, text: str) -> subprocess.CompletedProcess[str]:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json"
        ) as artifact:
            artifact.write(text)
            artifact.flush()
            return subprocess.run(
                [sys.executable, "-m", MODULE, kind, artifact.name],
                text=True,
                capture_output=True,
                check=False,
            )
```

- Add these two tests after `test_malformed_document_reports_sorted_diagnostics_without_traceback`:

```python
    def test_a_duplicate_key_is_a_parse_error(self):
        # Evidence composes the shared duplicate-key hook (#175 D3).
        text = json.dumps(self.fixture("research-corroborated.json"))
        duplicated = text[:-1] + ', "kind": "research-observations"}'

        completed = self.run_text("research", duplicated)

        self.assert_diagnostic(completed, "JSON_INVALID")
        self.assertIn("JSON_INVALID $: duplicate JSON key 'kind'", completed.stderr)

    def test_a_nan_literal_parses_and_is_left_to_the_validator(self):
        # Evidence does not compose the non-finite hook (#175 D3): NaN parses,
        # and the validator judges it like any other wrong-typed value.
        document = self.fixture("research-corroborated.json")
        document["schema_version"] = float("nan")

        completed = self.run_document("research", document)

        self.assert_diagnostic(completed, "FIELD_TYPE")
        self.assertIn("FIELD_TYPE $.schema_version: expected an integer", completed.stderr)
        self.assertNotIn("JSON_INVALID", completed.stderr)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_agent_evidence.py 2>&1 | tail -3`
Expected: `FAILED`, and every subprocess child exits 1 with
`No module named agent_tools.agent_evidence`.

- [ ] **Step 3: Move and edit the module; re-point the living documents**

```bash
git mv home/common/agent-skills/scripts/agent-evidence.py python/agent_tools/agent_evidence.py
```

Apply the five edits listed under Invariants, and nothing else. In the same
commit, re-point the living documents (the-bar, Moves keep their history):

- `CC/DIFF-REVIEW.md`: at L184 and L193, `` `agent-evidence.py` `` becomes
  `` `agent-evidence` ``. Do not reflow the paragraphs.
- `CC/evals/evals.json`: change both occurrences of `agent-evidence.py` to
  `agent-evidence`. One is in the scoped `expected_output`, and one is in the
  failures list.
- `AS/tests/test_workflow_skill_contracts.py` L1774: the comment's
  `` `agent-evidence.py` `` becomes `` `agent-evidence` ``.

- [ ] **Step 4: Build the package and wire the launcher**

Create `lib/agent-tools.nix`. The launcher bytes are a contract with Task 5, so
the file is given in full:

```nix
# The agent_tools package (python/): one interpreter environment, a build-time
# import of every module, and one isolated launcher per command-table row.
# `commands` is the only command-to-module mapping (#175 D4, D11; parent D2,
# D10, D13).
{ pkgs }:
let
  inherit (pkgs) lib;
  python = pkgs.python3;
  source = ../python;
  sourceRoot = toString source;
  project = (lib.importTOML (source + "/pyproject.toml")).project;

  # Every .py file under agent_tools as a dotted module name; an __init__.py
  # names its package. Walking the tree means a new module is import-checked
  # without anyone editing a list.
  moduleOf =
    file:
    lib.removeSuffix ".__init__" (
      lib.replaceStrings [ "/" ] [ "." ] (lib.removeSuffix ".py" (lib.removePrefix "${sourceRoot}/" file))
    );
  modules = map moduleOf (
    lib.filter (lib.hasSuffix ".py") (
      map toString (lib.filesystem.listFilesRecursive (source + "/agent_tools"))
    )
  );

  package = python.pkgs.buildPythonPackage {
    pname = project.name;
    inherit (project) version;
    pyproject = true;
    src = source;
    build-system = [ python.pkgs.setuptools ];
    pythonImportsCheck = modules;
  };

  env = python.withPackages (_: [ package ]);

  # A command's module is its name with each "-" replaced by "_".
  commands = [ "agent-evidence" ];

  # -I drops every PYTHON* variable, the working directory and the user site.
  # nixpkgs' sitecustomize still reads the NIX_PYTHON* variables under -I, and
  # this environment's python3 sets none of them, so the launcher clears them.
  launcher =
    name:
    pkgs.writeShellScript "agent-tools-${name}" ''
      unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE
      exec ${env}/bin/python3 -I -m agent_tools.${lib.replaceStrings [ "-" ] [ "_" ] name} "$@"
    '';
in
{
  launchers = lib.genAttrs commands launcher;
}
```

In `AS/default.nix`, make only these three edits:

1. In the `let` block, directly after the `localSkillFiles` binding (before
   `in`), add:

```nix

  # Each command-table row of lib/agent-tools.nix becomes ~/.agents/bin/<name>.
  # It enters home.file as a separate definition, so a leftover hand-written
  # entry for the same command is a conflicting definition, not a silent win.
  agentTools = import ../../../lib/agent-tools.nix { inherit pkgs; };
  agentToolFiles = lib.mapAttrs' (
    name: launcher: lib.nameValuePair ".agents/bin/${name}" { source = launcher; }
  ) agentTools.launchers;
```

2. Change `home.file = localSkillFiles // {` to
   `home.file = lib.mkMerge [ (localSkillFiles // {`. Change the set's closing
   `  };` (the line after the `.claude/skills/ui-ux-pro-max` entry's `};`) to
   `  }) agentToolFiles ];`. Leave every entry inside the set untouched and
   unindented except the next one, and do not run `nixfmt` on this file (D13).
3. Delete the hand-written `".agents/bin/agent-evidence" = { … };` entry (four
   lines) and one of its adjacent blank lines.

- [ ] **Step 5: Verify**

Run: `PYTHONPATH=python python3 -m unittest -v home/common/agent-skills/tests/test_agent_evidence.py 2>&1 | tail -3`
Expected: `OK`, with two more tests than at `$START`.

Run: `git add -A python/agent_tools home/common/agent-skills/scripts lib/agent-tools.nix && git diff --cached -M --name-status -- home/common/agent-skills/scripts/agent-evidence.py python/agent_tools/agent_evidence.py`
Expected: one line, `R<NN>	home/common/agent-skills/scripts/agent-evidence.py	python/agent_tools/agent_evidence.py`, with `NN` ≥ 95.

Run: `if git grep -n "agent-evidence\.py" -- ':!.claude/specs' ':!.claude/plans'; then exit 1; fi; if grep -nE "_reject_duplicate_keys|^#!" python/agent_tools/agent_evidence.py; then exit 1; fi; echo docs-clean`
Expected: `docs-clean`. This check fails at `$START`.

Run: `just build 2>&1 | tail -3`
Expected: success, with no `error:` line.

Then check the installed command. Take its interpreter from the launcher itself,
and compare its output with the pre-move script run under the same interpreter
and the same name:

```bash
H=$(nix-store --query --requisites ./result | grep -- '-home-manager-files$')
L="$H/.agents/bin/agent-evidence"; cat "$L"
PY=$(sed -n 's/^exec \([^ ]*\) -I -m .*/\1/p' "$L")
git show "${START}:home/common/agent-skills/scripts/agent-evidence.py" > "$B/agent-evidence"
COLUMNS=80 "$PY" "$B/agent-evidence" --help > "$B/help.before"
COLUMNS=80 "$L" --help | cmp - "$B/help.before" && echo help-identical
COLUMNS=80 "$PY" "$B/agent-evidence" 2> "$B/usage.before"; echo "before=$?"
COLUMNS=80 "$L" 2> "$B/usage.after"; echo "after=$?"
cmp "$B/usage.before" "$B/usage.after" && echo usage-identical
"$L" bridge home/common/agent-skills/tests/fixtures/evidence/bridge-fresh-end-to-end.json
```

Keep the braces in `${START}:`: in zsh, `$START:h…` applies the `:h` modifier.

Expected:
- `cat` prints the three-line template from Interfaces.
- `help-identical`.
- `before=2`, `after=2` and `usage-identical`.
- `VALID bridge-smoke bridge-fresh-e2e`.

Run: `just agent-workflow-tests 2>&1 | tail -3`
Expected: `OK (skipped=1)`, with two more tests than after Task 3.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/agent_evidence.py home/common/agent-skills/scripts/agent-evidence.py \
  lib/agent-tools.nix home/common/agent-skills/default.nix \
  home/common/agent-skills/tests/test_agent_evidence.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md \
  home/common/claude-code/skills/codex-collaboration/evals/evals.json
git commit -m "feat(agent-tools): ship agent-evidence as an isolated package launcher"
```

The message ends with the trailer lines named in the plan's Global Constraints.

- [ ] **Step 7: Show that each failure is loud, then restore**

These checks run on the committed tree. Each mutation is reverted with
`git checkout`, and neither is committed.

The imports check fails the build (AC3, parent D10). This is the one-time
demonstration the spec asks for:

```bash
printf 'import agent_tools_missing_probe\n' >> python/agent_tools/canonical.py
just build > "$B/imports.log" 2>&1; echo "build=$?"
grep -E "pythonImportsCheckPhase|No module named 'agent_tools_missing_probe'" "$B/imports.log" | head -3
git checkout -- python/agent_tools/canonical.py
```

Expected: a non-zero `build=`, with a line from the imports-check phase and
the `ModuleNotFoundError`.

A leftover hand-written entry fails evaluation (D5). Re-add this entry inside
the literal set in `AS/default.nix`:
`".agents/bin/agent-evidence" = { source = ./skills/sdd/scripts/sdd-workspace; executable = true; };`.
Then run the following:

```bash
just build > "$B/conflict.log" 2>&1; echo "build=$?"
grep -c "conflicting definition values" "$B/conflict.log"
git checkout -- home/common/agent-skills/default.nix
```

Expected: a non-zero `build=`, and a count of at least 1.

Run: `git status --porcelain`
Expected: no output.
