# Task 1: skill_lint foundation — snapshot seam, matcher move, frontmatter, reflow, classification

Per D3, D11, D12, D15, D17.

**Files:**
- Create: `python/agent_tools/skill_lint.py`
- Modify: `python/agent_tools/instruction_load.py` (import the moved names; delete their local definitions)
- Create: `home/common/agent-skills/tests/test_skill_lint.py`
- Modify: `justfile` (add `home/common/agent-skills/tests/test_skill_lint.py \` to `agent-workflow-tests`, on the line after `test_instruction_load.py`)

**Interfaces:**
- Consumes: `agent_tools.agent_model_matrix.AGENTS_PATH`, `MATRIX_PATH`, `parse_matrix(text, source)`. Also the private names in `instruction_load.py` that move: `tree_reader`, `_BOUNDARY_BEFORE`, `_BOUNDARY_AFTER`, `_BASENAME_BEFORE`, `_MD_TOKEN`, `_split`, `_names`, `SHARED_TREE`, `CLAUDE_TREE`, `AGENTS_DIR`, `Reader`.
- Produces, in `agent_tools.skill_lint` (Tasks 2–4 rely on these exact names):
  - `SHARED_TREE = "home/common/agent-skills/skills"`, `CLAUDE_TREE = "home/common/claude-code/skills"`, `CODEX_TREE = "home/common/codex/skills"`, and `TREE_ROOTS = (SHARED_TREE, CLAUDE_TREE, CODEX_TREE)`.
  - `AGENTS_DIR = AGENTS_PATH.as_posix()`, `EXCLUDED_DIRS = ("evals", "scripts")`.
  - `Reader = Callable[[str], Optional[bytes]]` and `Lister = Callable[[str], list[str]]`.
  - `@dataclass(frozen=True) class Snapshot: read: Reader; list_files: Lister`.
  - `tree_reader(root: Path) -> Reader`, moved unchanged.
  - `tree_lister(root: Path) -> Lister`.
  - `working_tree(root: Path) -> Snapshot`.
  - `BOUNDARY_BEFORE`, `BOUNDARY_AFTER`, `BASENAME_BEFORE`, `MD_TOKEN`: the moved regexes, made public.
  - `split_member(member: object) -> Optional[tuple[str, str]]`, the moved `_split`.
  - `names(source: str, text: str, target: str) -> bool`, the moved `_names`.
  - `reflowed_lines(text: str) -> int`.
  - `parse_frontmatter(text: str) -> tuple[dict[str, str], str]`.
  - `@dataclass(frozen=True) class SkillDir: tree: str; name: str; path: str; skill_md: Optional[str]; references: tuple[str, ...]; payloads: tuple[str, ...]`.
  - `skill_dirs(snapshot: Snapshot) -> list[SkillDir]`.
  - `instruction_load` keeps `instruction_load.tree_reader` and `instruction_load.Reader` importable (they are the same objects as in `skill_lint`).

**Invariants:**
- `instruction_load`'s behavior is byte-identical. The whole existing `test_instruction_load.py` passes unedited.
- `skill_lint` imports nothing from `instruction_load` (no cycle).
- A `Lister` returns the sorted repo-relative POSIX paths of every regular file under `<prefix>/`, recursively. It returns `[]` for an absent prefix, and it never descends a symlinked directory.
- `reflowed_lines` counts each line of `text.splitlines()` as `max(1, ceil(len(line) / 100))`, with `len` in decoded characters (per D17).
- `skill_dirs` order: by tree in `TREE_ROOTS` order, then by skill name. `references` and `payloads` are sorted repo-relative paths. Neither ever contains `SKILL.md` or a file under `<skill>/evals/` or `<skill>/scripts/`.

- [ ] **Step 1: Write the failing test**

Create `home/common/agent-skills/tests/test_skill_lint.py`:

```python
"""skill_lint: the snapshot seam, frontmatter, reflowed lines and skill classification (#292)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from agent_tools import instruction_load, skill_lint


REPO_ROOT = Path(__file__).parents[4]
SHARED = "home/common/agent-skills/skills"
CLAUDE = "home/common/claude-code/skills"
CODEX = "home/common/codex/skills"
ALPHA = f"{SHARED}/alpha"
MATRIX = {
    "roles": {},
    "dispatch_sites": [
        {"id": "alpha-review", "path": f"{ALPHA}/SKILL.md",
         "call": 'Agent(subagent_type="reviewer", model="opus", effort="high") '
                 'reviews against `CONTRACT.md`.'},
    ],
    "scenarios": {},
}


def skill(name, description="Does things. Use when testing.", body="body\n"):
    return f"---\nname: {name}\ndescription: {description}\n---\n{body}".encode()


def clean_files():
    """A lint-clean three-tree repository: one reference, two payloads, excluded dirs."""
    return {
        "home/common/agent-skills/model-matrix.json": json.dumps(MATRIX).encode(),
        f"{ALPHA}/SKILL.md": skill(
            "alpha", "Alphas things. Use when testing.",
            "Read GUIDE.md first.\nHand alpha-prompt.md and CONTRACT.md to the reviewer.\n"),
        f"{ALPHA}/GUIDE.md": b"# Guide\nshort guide naming SKILL.md and CONTRACT.md\n",
        f"{ALPHA}/alpha-prompt.md": b"Prompt naming GUIDE.md\n",
        f"{ALPHA}/CONTRACT.md": b"contract\n",
        f"{ALPHA}/evals/notes.md": b"NOT.md is mentioned here\n",
        f"{ALPHA}/scripts/README.md": b"script docs\n",
        f"{CLAUDE}/beta/SKILL.md": skill("beta"),
        f"{CODEX}/gamma/SKILL.md": skill("gamma"),
        "home/common/claude-code/agents/reviewer.md": b"reviewer body\n",
        "home/common/agent-guidance/AGENTS.md": b"frame text\n",
        "home/common/agent-skills/skill-lint-debt.json": b'{"debt": []}\n',
    }


def dict_snapshot(files):
    return skill_lint.Snapshot(
        read=files.get,
        list_files=lambda prefix: sorted(p for p in files if p.startswith(prefix + "/")),
    )


class FoundationTest(unittest.TestCase):
    def test_reflowed_lines_count_long_lines_by_the_hundred(self):
        for text, expected in (("", 0), ("a\n", 1), ("\n", 1), ("a\nb", 2),
                               ("x" * 100, 1), ("x" * 101, 2), ("x" * 1229, 13),
                               ("é" * 100 + "\n", 1)):
            with self.subTest(text=text[:12]):
                self.assertEqual(skill_lint.reflowed_lines(text), expected)

    def test_frontmatter_parses_single_line_scalars(self):
        fields, body = skill_lint.parse_frontmatter(
            '---\nname: alpha\ndescription: "Quoted. Use when x."\nflag: true\n'
            "hint: 'single'\nempty:\n---\n# Body\n")
        self.assertEqual(fields, {"name": "alpha", "description": "Quoted. Use when x.",
                                  "flag": "true", "hint": "single", "empty": ""})
        self.assertEqual(body, "# Body\n")

    def test_frontmatter_rejects_every_shape_it_cannot_vouch_for(self):
        for text in ("name: alpha\n---\n",                       # no leading fence
                     "---\nname: alpha\n",                       # never closed
                     "---\nname: a\nname: b\n---\n",             # duplicate key
                     "---\ndescription: >\n  folded\n---\n",     # block scalar
                     "---\ndescription: |\n---\n",               # block scalar
                     "---\nname: a\n  continued\n---\n",         # continuation line
                     "---\nnot a mapping line\n---\n"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    skill_lint.parse_frontmatter(text)

    def test_skill_dirs_classify_references_and_payloads(self):
        dirs = skill_lint.skill_dirs(dict_snapshot(clean_files()))
        self.assertEqual([(d.tree, d.name) for d in dirs],
                         [(SHARED, "alpha"), (CLAUDE, "beta"), (CODEX, "gamma")])
        alpha = dirs[0]
        self.assertEqual(alpha.path, ALPHA)
        self.assertEqual(alpha.skill_md, f"{ALPHA}/SKILL.md")
        self.assertEqual(alpha.references, (f"{ALPHA}/GUIDE.md",))
        self.assertEqual(alpha.payloads, (f"{ALPHA}/CONTRACT.md", f"{ALPHA}/alpha-prompt.md"))

    def test_a_skill_directory_without_skill_md_is_still_listed(self):
        files = clean_files()
        files[f"{SHARED}/orphan/NOTES.md"] = b"notes\n"
        orphan = next(d for d in skill_lint.skill_dirs(dict_snapshot(files)) if d.name == "orphan")
        self.assertIsNone(orphan.skill_md)
        self.assertEqual(orphan.references, (f"{SHARED}/orphan/NOTES.md",))

    def test_a_tree_root_without_any_skill_cannot_be_classified(self):
        files = {p: d for p, d in clean_files().items() if not p.startswith(CODEX)}
        with self.assertRaisesRegex(ValueError, CODEX):
            skill_lint.skill_dirs(dict_snapshot(files))

    def test_an_unreadable_matrix_cannot_be_classified(self):
        for raw in (None, b'{"roles": {}, "roles": {}}', b'{"dispatch_sites": 1}'):
            with self.subTest(raw=raw):
                files = clean_files()
                if raw is None:
                    del files["home/common/agent-skills/model-matrix.json"]
                else:
                    files["home/common/agent-skills/model-matrix.json"] = raw
                with self.assertRaises(ValueError):
                    skill_lint.skill_dirs(dict_snapshot(files))

    def test_the_tree_lister_lists_files_recursively_and_sorted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative in ("a/x/SKILL.md", "a/x/sub/deep.md", "a/y.md", "b/z.md"):
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_bytes(b"x\n")
            os.symlink(root / "b", root / "a/link")
            listing = skill_lint.tree_lister(root)
            self.assertEqual(listing("a"), ["a/x/SKILL.md", "a/x/sub/deep.md", "a/y.md"])
            self.assertEqual(listing("absent"), [])
            snapshot = skill_lint.working_tree(root)
            self.assertEqual(snapshot.read("a/y.md"), b"x\n")
            self.assertEqual(snapshot.list_files("b"), ["b/z.md"])

    def test_instruction_load_uses_the_moved_seam_and_matcher(self):
        self.assertIs(instruction_load.tree_reader, skill_lint.tree_reader)
        self.assertTrue(skill_lint.names("demo/SKILL.md", "see EXTRA.md", "demo/EXTRA.md"))
        self.assertFalse(skill_lint.names("demo/SKILL.md", "see other/EXTRA.md", "demo/EXTRA.md"))
        self.assertTrue(skill_lint.names("x/SKILL.md", "use `demo`", "demo/SKILL.md"))
        self.assertEqual(skill_lint.split_member("demo/EXTRA.md"), ("demo", "EXTRA.md"))
        self.assertIsNone(skill_lint.split_member("demo/sub/EXTRA.md"))


if __name__ == "__main__":
    unittest.main()
```

The unused imports (`subprocess`, `sys`) are for Task 2's `CommandTest` in this file. Keep them.

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest home/common/agent-skills/tests/test_skill_lint.py`
Expected: ERROR. `ImportError: cannot import name 'skill_lint'`.

- [ ] **Step 3: Write the minimal implementation**

Create `python/agent_tools/skill_lint.py`. Its module docstring is `"""Lint the authored skill trees against rules L1–L5, and own the skill-tree knowledge instruction_load shares."""`. Contents:

1. **Move, don't copy.** Cut `tree_reader`, the four regex constants, `_split` and `_names` out of `instruction_load.py` and paste them into `skill_lint.py`. Rename them to the public names under Interfaces. Inside `names`, call `split_member`. In `instruction_load.py`, add `from agent_tools.skill_lint import AGENTS_DIR, CLAUDE_TREE, MD_TOKEN, SHARED_TREE, Reader, names, split_member, tree_reader`. Rename the call sites: `_split` → `split_member`, `_names` → `names`, `_MD_TOKEN` → `MD_TOKEN`. Then delete the local definitions. Keep `instruction_load`'s own `import os` only if something still uses it.
2. **`tree_lister(root)`**: `os.walk(Path(root) / prefix)` with `followlinks=False`. For each file name, keep it only when `os.path.isfile` is true for the joined path. Return `sorted` POSIX paths relative to `root`. A prefix that is not a directory returns `[]`.
3. **`working_tree(root)`** returns `Snapshot(tree_reader(root), tree_lister(root))`.
4. **`parse_frontmatter(text)`**:
   - The first line must be exactly `---`. Otherwise raise `ValueError("frontmatter: no opening --- line")`.
   - The block ends at the next line that is exactly `---`. Otherwise raise `ValueError("frontmatter: no closing --- line")`.
   - Each line in between must fullmatch `([A-Za-z][A-Za-z0-9_-]*):(?: (.*))?`. Otherwise raise `ValueError(f"frontmatter: cannot read line {line!r}")`. That rule also rejects indented continuation lines.
   - The value is stripped. A value of `>`, `|`, `>-`, `|-`, `>+` or `|+` raises `ValueError(f"frontmatter: {key} is a block scalar")`.
   - A value of length ≥ 2 that starts and ends with the same `"` or `'` has that quote pair removed.
   - A repeated key raises `ValueError(f"frontmatter: duplicate key {key}")`.
   - The body is everything after the closing fence line.
5. **`skill_dirs(snapshot)`**:
   - Read `MATRIX_PATH.as_posix()`. If it is absent, raise `ValueError`. Decode it as UTF-8 and parse it with `parse_matrix`; let its `ValueError` pass. `dispatch_sites` must be a list, or raise `ValueError`. Sites whose `path` or `call` is not a `str` are ignored.
   - For each root in `TREE_ROOTS`: `files = snapshot.list_files(root)`. Skill names are the distinct first path components below `root/` that have at least one further component. If no `f"{root}/<name>/SKILL.md"` is in `files`, raise `ValueError(f"{root}: no skill found")`.
   - For each skill: `docs` are its `.md` files whose first component relative to the skill directory is not in `EXCLUDED_DIRS`.
   - `skill_md` is `f"{path}/SKILL.md"` when present, else `None`.
   - `call_names = set(MD_TOKEN.findall(call))` over every site whose `path` starts with `path + "/"`.
   - A payload is a doc other than `SKILL.md` whose basename ends in `-prompt.md` or is in `call_names`. The references are the remaining docs other than `SKILL.md`.

Add the `justfile` line.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest home/common/agent-skills/tests/test_skill_lint.py home/common/agent-skills/tests/test_instruction_load.py`
Expected: PASS. 9 new tests, plus every existing instruction-load test unchanged.

Run: `if grep -nE '^def (_names|_split|tree_reader)\b|^_MD_TOKEN' python/agent_tools/instruction_load.py; then exit 1; fi`
Expected: no output, exit 0 (the definitions moved rather than being copied).

Run: `grep -c 'test_skill_lint.py' justfile`
Expected: `1`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/skill_lint.py python/agent_tools/instruction_load.py home/common/agent-skills/tests/test_skill_lint.py justfile
git commit -m "feat(agent-tools): add the skill_lint snapshot seam and skill classification (#292)"
```
