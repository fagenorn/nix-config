# Issue 380 — adopt-project surfaces and rewrites depth-relative paths in moved trees

Issue: https://github.com/fagenorn/nix-config/issues/380 (blocks
https://github.com/fagenorn/nix-config/issues/371, follows
https://github.com/fagenorn/nix-config/issues/372 and
https://github.com/fagenorn/nix-config/issues/376). Lineage, cited as "issue
350", "issue 372" and "issue 376" with their ledger rows: the specs
`2026-10-10-issue-350-adopt-path-references-design.md`,
`2026-10-12-issue-372-adopt-moved-file-references-design.md` and
`2026-10-12-issue-376-adopt-format-step-and-variable-paths-design.md`, whose
terms (token, occurrence, reading, successor, target, tree, class, policy,
effective answer) are used unchanged.

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "adds a new <tree>:<class>/depth policy class to plan output, the evidence record and plan_id inputs"}, "concurrency_or_persistence": {"value": "doubt", "evidence": "no concurrency; changes the persisted evidence-record and stored-plan content, not storage mechanics"}, "open_design_questions": {"value": "hit", "evidence": "issue says 'the spec chooses the design' (lock-file class vs manifest answer, detection grammar)"}, "criteria_shape": {"value": "hit", "evidence": "six acceptance criteria"}}, "paths": ["python/agent_tools/adopt_references.py", "python/agent_tools/adopt_planning.py", "python/agent_tools/adopt_project.py", "python/README.md", "home/common/agent-skills/tests/test_adopt_references.py", "home/common/agent-skills/tests/test_adopt_project.py", "home/common/agent-skills/tests/test_adopt_apply.py", "home/common/agent-skills/tests/test_adopt_verify.py"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

An operator adopts a repository whose `.claude/notes` tree holds tooling that
finds the repository root by counting levels up from its own file:
`ROOT = HERE.parents[2]`, or a `pyproject.toml` source
`path = "../../../vendor/lib"` and the `uv.lock` that records it. The plan moves
the tree to `.agents/artifacts/notes`, one level deeper. Every gate passes,
`verify` reports `adopted`, and every one of those references now resolves
inside `.agents/` instead of the root. Nothing told the operator: the
references name no moved path, so no reading of issues 350, 372 or 376 sees
them, and most of the files are not even read, because the scan only reads
files that hold the first segment of a move source. The adopt commit may not
be fixed by hand.

## Solution

A fourth reading, the **depth reading**, applies to the files the plan moves
and to nothing else. It finds two kinds of **climb**: a token that starts with
`../` segments, in any scanned text file, and a Python parent-count idiom
anchored at the file's own location. A climb whose landing point lies outside
the moved tree and changes when the file moves becomes an occurrence of the
policy `<tree>:<class>/depth`, with the closed answers `rewrite` and `retain`
and no recommendation. `rewrite` shifts the climb by the file's depth delta, so
it lands where it landed on base; `retain` leaves the bytes as they are.
Everything after detection — questions, answers, precedence, rows, edits,
`plan_id`, evidence record, apply, verify — is the existing mechanism,
unchanged.

## Decisions

### Climbs and their landing point (per D1, D3)

Paths are `/`-joined, the repository root is the empty path, and the depth of a
directory is its segment count. For a moved file at base path `p`, destination
`q`:

- `P` is `p`'s directory and `Q` is `q`'s; the **depth delta** is
  `depth(Q) - depth(P)`.
- The **tree root** `R` is the file's tree when the tree is a classification
  group (a directory), and `P` when the tree is the file itself (an
  `archive-history` answer). Every member of a group moves with the same
  prefix substitution, so a path inside `R` keeps its relation to the file.
- A climb has an **anchor** `P` and a **height** `k`: its **landing point** is
  the directory `k` levels above `P`, a position above the root counted by how
  far above it is.

A climb is an occurrence when its landing point is a proper ancestor of `R`
(or above the root) and the same climb taken from `Q` lands elsewhere. So a
climb that stays inside the moved tree is never surfaced, and a move that keeps
the depth surfaces nothing whose landing point is a common ancestor of `P` and
`Q`. A landing point that is an ancestor of `P` but not of `Q` (`.claude`, for
a file moved from `.claude/notes` to `.agents/artifacts/notes`) changes at any
delta, and is surfaced.

### The text climb (per D3)

A token, as issue 350 defines tokens, is a **text climb** when, after an
optional `./`, it starts with `..` segments (`k ≥ 1` of them) and holds at
least one `/`: `../x`, `../../`, `../..`, `./../x`. The rest of the token after
the last leading `..` is kept verbatim. The anchor is the file's directory: a
manifest, a lock file and a relative-path argument are read as relative to
their own directory, which is the only reading a text scan can make; the
operator decides when it is wrong. A token that is `..` alone, quoted or not,
is no climb: joined segments (`HERE / ".." / ".."`) are not added up.

When the landing point is at or below the root, the token's **base target** is
the normalised join of the landing point and the rest. A text climb whose base
target lies inside `R` (`../../notes/x` from `.claude/notes/tool`) re-enters
the tree, moves with the file and is not surfaced. A base target outside `R`
that names a path the moves relocate (the issue 350 condition, another moved
tree) offers `retain` only: the rewrite would land on a path that no longer
exists, and issue 350's successors are not combined with a climb.

### The Python climb (per D2)

In a file whose base path has class `.py`, the depth reading also scans each
line, by standard-library regular expression, for an **anchored chain**: an
anchor followed by zero or more `.parent` and then at most one
`.parents[N]`, `N` a decimal literal, with at least one of them. Anchors:

- **direct**: `Path(__file__)` or `pathlib.Path(__file__)`, not preceded by an
  identifier character or `.`, optionally followed by one `.resolve()` or
  `.absolute()`; its offset is −1 (the file itself);
- **bound name**: a name bound exactly once at column 0 of the file, by
  `NAME = <direct anchor>` or `NAME = <direct anchor>.parent` (an optional
  `: Path` annotation, a trailing comment and a `\r\n` line end allowed), and
  rebound nowhere else in the file, at any indentation (no other plain,
  annotated, augmented or `:=` assignment, and no `for`, `as`, `del`, `global`
  or `nonlocal` naming it; a keyword argument of that name also counts, which
  errs towards not following); its offset is −1 or 0. A use is the name
  preceded by neither an identifier character nor `.`, anywhere in the file.

The height is the offset plus one per `.parent` plus `N + 1` for
`.parents[N]`. The occurrence's span is the chain after the anchor (from its
first `.parent`), its `literal` that text, and its `line` and `column` those of
the span's first character, so subjects never collide with a token occurrence.
A binding's own chain has height −1 or 0 and so never climbs out; a binding
that climbs further is a direct chain occurrence and its name is not tracked,
so no use is adjusted twice. A chain whose span overlaps a text climb of the
same file, or an occurrence another reading made there, is dropped, so one
span never carries two edits. Matches inside strings and comments count, as
they do for tokens. Not read: `os.path.dirname`, `os.path.join(..., "..")`,
`Path.cwd()`, chains through other names (`ROOT = HERE.parents[2]` makes `ROOT`
nothing), function-local bindings, whitespace inside a chain, and a non-literal
index.

### The rewrite (per D1, D4)

A depth occurrence offers `rewrite` when shifting its height by the depth
delta lands on the same point from `Q`: that is, when its landing point is an
ancestor of `Q` or above the root, and its base target (text climb) names no
moved path. The new height is `k + delta`, and the replacement must still be a
valid form:

- text climb: `k + delta ≥ 1` `..` segments, joined by `/`, with the `./`
  prefix and the rest kept (`../../../vendor` → `../../../../vendor`);
- Python chain: the trailing `.parents[N]` becomes `.parents[N + delta]`
  (`N + delta ≥ 0`); a chain of `.parent` only gains or loses `delta` of them,
  keeping at least one.

Otherwise it offers `retain` only. Every depth occurrence offers `retain`,
never `extend`. Negative and positive deltas are one rule; at zero delta a
climb is an occurrence only when its landing point is not an ancestor of `Q`,
so it offers `retain` only.

### Policy and class (per D5, D6)

An occurrence records that the depth reading made it, and its class is
`<file class>/depth` (`.py/depth`, `.toml/depth`, `.lock/depth`), so its
policy is `<tree>:<file class>/depth`. A file class holds no `/`, so it cannot
collide with a file class or a `/variable` class. The class is outside both
recommendation tables, so the `reference-policy` question's `value` and the
row's `recommended` are null, and nothing is edited without an answer. An
answer to `<tree>:.py` or `<tree>:.py/variable` never decides it.

A lock file is its own class: `uv.lock` is `.lock`, so its climbs form
`<tree>:.lock/depth`, beside the manifest's `<tree>:.toml/depth` in the same
plan. The tool holds no table pairing a lock with its manifest; the operator
answers both, and a mismatched pair is caught by the target's own
verification commands at `apply`, as any other inconsistent edit is.

### Which files are read (per D7)

The depth reading reads every moved file that passes the existing filters
(regular blob, not Markdown, not secret-shaped, not adoption-written, not under
a record home by base path, text by git's `-I` judgement, strict UTF-8) and
holds `..` or `__file__`, found by one more `git grep -I -l -F` over the base
revision, limited by literal pathspecs to the trees of the moves (a group's
directory, an archived file's own path) and then to the moved files. The three existing readings still run only over the files the
first-segment prefilter returns; a file both scans return gets all four. So
the prefilter's documented limit is unchanged, and no occurrence of issues
350, 372 or 376 appears, changes or disappears. Within one token the depth
reading is tried last; no token starting with `..` can name a tree path, so in
practice the readings are disjoint.

### What the plan publishes (per D6)

Nothing new in shape. A depth occurrence is a `path_references` row with the
same twelve members (`literal` is the climb, `replacement` the shifted form or
null, `answers` `["rewrite", "retain"]` or `["retain"]`), a policy has a
`reference_policies` row with the same thirteen members, its open question is
an ordinary `reference-policy` question, and a single unanswered occurrence an
ordinary `path-reference` question. A repository whose moved files hold a
depth occurrence therefore gets a `draft` plan through `no-open-decisions`
until the `/depth` policies are answered, even where every earlier answer is
given; that is the "no silent default". These rows are already inputs of
`plan_id` and members of the evidence record, and the answers appear in
`decisions_accepted`. A rewritten file is one `write-file` at its destination
after its `git-mv`, and enters `reference_formatting` under its file class. A
plan whose moved files hold no depth occurrence has the same document and
`plan_id` as before, so a stored plan of such a repository still re-derives
and applies. `verify` is unchanged; `adoption-commit-derived` judges the
commit that adds the evidence record, which a `rewrite` changes only by
planned writes.

### Documentation

`python/README.md`'s `adopt-project` section gains a paragraph after the
variable reading: the depth reading, its read set, the tree root and landing
point, the text-climb and Python-chain grammars with their limits, the rewrite
rule and when only `retain` is offered, and the `/depth` class beside
`/variable` (with the lock file as its own class). The sentence on the
`git grep` prefilter states that the depth reading has its own read set.

## Test seams

The seams of issues 350, 372 and 376, driven as `python -m
agent_tools.adopt_project` under the recipe's `PYTHONPATH`, plus the
`adopt_references` functions; no new seam.

- **`adopt_references` functions** (`test_adopt_references.py`), over
  `plan_references` with synthetic moves and trees, because the classification
  table has no same-depth or shallower move:
  - text climbs: surfaced above `R`; not surfaced inside the tree (AC2); not
    surfaced for a same-depth move to the root (AC3); surfaced `retain`-only
    for a landing point that is an ancestor of `P` only, and for a base target
    in another moved tree; a climb re-entering `R` is not surfaced; a shallower move rewrites with fewer `..`; `..` alone and
    `".."` are no climbs; the `./` prefix and the rest are kept.
  - Python chains: direct `parents[N]`, `.parent` chains, mixed chains; a
    `HERE` bound to `.resolve().parent` and used as `HERE.parents[N]`; a name
    bound twice, a function-local binding, `ROOT` chained from `HERE` and
    `os.path.dirname` produce nothing; a minimum-violating rewrite offers
    `retain` only.
  - class and policy `<tree>:<class>/depth`; an unmoved file yields no depth
    occurrence; `policy_summary` rows with `.py` and `.py/depth` answered
    differently; files reached only by the depth read set yield no plain,
    pattern or variable occurrence.
- **`plan`** (`test_adopt_project.py`). AC1 fixture: `.claude/notes/tool/`
  holds `run.py` (`HERE = Path(__file__).resolve().parent`,
  `ROOT = HERE.parents[2]`, plus an inside-tree `HERE.parent` and `"../data/x"`),
  `pyproject.toml` and `uv.lock` each with `"../../../vendor/lib"`, and a
  tracked `vendor/lib`. The plan is `draft` with open `reference-policy`
  questions `.claude/notes:.py/depth`, `.toml/depth` and `.lock/depth`, each
  `value` null, and the inside-tree climbs absent (AC2). Existing plan tests
  pass unchanged (AC4); the plan implementation inventories the existing
  fixtures' moved files for `..` and `__file__` and keeps them unchanged.
- **`apply` by plan id** (`test_adopt_apply.py`): with the three policies
  answered `rewrite`, each rewritten climb, joined to its file's destination
  directory and normalised, equals the base climb joined to the base directory
  (path arithmetic, AC1); with `retain`, each blob at its destination equals
  its base blob. The evidence record lists the answers and the depth rows.
- **`verify`** (`test_adopt_verify.py`): `adoption-commit-derived` is `passed`
  on the applied `rewrite` fixture (AC5).
- AC6 is `just agent-workflow-tests`.

## Out of scope

- Any Arcwave-specific case, and running the adoption on Arcwave
  (https://github.com/fagenorn/nix-config/issues/371).
- A new gate, operation kind, `verify` check, plan-document member or
  `plan_id` input, and a recommendation for `/depth`.
- Per-language parsers; `os.path` idioms; chains through second names; joined
  segments; climbs in non-Python code other than `../` tokens; same-directory
  references of an archived single file (`./x`, `Path(__file__).parent / "x"`).
- Climbs in Markdown files (left to issue 345's link rewrites) and in files the
  plan does not move.
- Rewriting a climb onto a moved base target, and a manifest-to-lock pairing
  table.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | A climb is surfaced when its landing point lies above the tree root `R` and changes when the file moves; `rewrite` shifts the height by the depth delta and is offered only when that lands on the same point (ancestor of `Q` or above the root) and the result is a valid form; one rule covers positive, negative and zero deltas | The issue's "adjusts the climb by the depth delta … so the reference resolves to the same target as on base" and its AC2/AC3; a delta shift is only correct for a landing point shared by `P` and `Q` | Surfacing by depth delta alone, which misses a same-depth move under a different parent and offers a wrong rewrite for a `.claude`-level landing point; recomputing a fresh relative path, which no parent-count form can express |
| D2 | Python chains: direct `Path(__file__)`/`pathlib.Path(__file__)` with optional `.resolve()`/`.absolute()`, `.parent` chains with at most one trailing `.parents[N]`, and a name bound once at column 0 to the file or its directory; nothing else | The issue's three named idioms; issue 350 D6 (no per-language parser); the bar's YAGNI; tracking only bindings of height −1/0 makes a double adjustment impossible | `os.path.dirname` nesting and transitive names (`ROOT` from `HERE`), which need data flow a regex cannot give |
| D3 | Text climbs are tokens starting with `..` segments that hold a `/`, anchored at the file's directory, in every scanned class of a moved file; a bare `..` is no climb; a base target that names a moved path offers `retain` only | The issue's "any text file the existing reference scanning covers"; joined `".."` segments would each be shifted and over-adjust; combining a climb with issue 350 successors is beyond the issue | Per-class allow lists, which presume where relative paths are meaningful; rewriting onto the successor, an unrequested reading |
| D4 | The tree root of an `archive-history` file is its own directory, so its `./x`-level references are not surfaced | The issue's "above the moved tree's root"; a group root is the group directory; keeps one rule for both kinds of tree | Treating the single file as its own root, which surfaces every `Path(__file__).parent` and needs a same-directory reading the issue does not ask for |
| D5 | `/depth` is its own class suffix, value null, answers `rewrite`/`retain`, never `extend`; `<tree>:<class>` and `<tree>:<class>/variable` answers never decide it | The issue's "policy class … closed answers rewrite \| retain, with no silent default"; issue 376 D8 and D13 (the reading is recorded on the occurrence, the class derived) | Folding into `<tree>:.py`, where a `rewrite` given for literals would silently shift climbs |
| D6 | A lock file is its own class (`uv.lock` → `<tree>:.lock/depth`), named in the plan beside its manifest; no new plan or record member; existing rows carry depth occurrences, so a repository without one keeps its plan id | The issue allows "a distinct class the plan names"; issue 372's class is the file suffix; the existing rows are already `plan_id` inputs and evidence-record members | A manifest-to-lock pairing table, per-ecosystem knowledge against issue 350 D6; a new `depth_references` member and `plan_id` input, which invalidates every stored plan for nothing |
| D7 | The depth reading has its own read set (moved files holding `..` or `__file__`, by a second `git grep -I` limited to the moves' trees); the three existing readings stay confined to the first-segment prefilter's files | Issue 376 D6's route for keeping every existing occurrence byte-identical; the README's documented prefilter limit (an escaped first segment is not found) would otherwise change silently | Widening the existing scan to every moved file, which would make new pattern occurrences appear in existing plans |
| D8 | Grill: a text climb whose base target lies back inside `R` is not surfaced; one whose base target is in another moved tree is surfaced `retain`-only | Probe: `../../notes/x` from `.claude/notes/tool` lands on `.claude` yet names a path that moves with the file, so it still resolves after the move; surfacing it would ask a question with no wrong answer | Surfacing every climb above `R`, which adds noise questions; resolving the target's successor, the reading rejected in D3 |
| D9 | Grill: a plan whose moved files hold a depth occurrence is `draft` until its `/depth` policies or occurrences are answered, even when it was `ready` before this change | The issue's "no silent default" and bootstrap's "no project policy is defaulted"; issue 372 D3 (a recommendation is never applied) | Defaulting `/depth` to `retain` so earlier ready plans stay ready, which is the silent breakage the issue reports |
| D10 | Plan: `plan_references` takes the depth read set as a keyword `depth_texts` beside the unchanged `texts`; `Occurrence` gains a last field `depth: bool = False` and `occurrence_class` derives `<file class>/depth` from it; `derive_references` reads each blob once for both scans and returns no references only when neither scan finds a file | Issue 376 D6/D13 (a defaulted last field and a derived class keep every caller and existing row byte-identical); D7 | A separate function or `References` member for depth occurrences, which would duplicate the answer, summary and edit paths the spec reuses |
| D11 | Plan: a text climb whose rest holds a `..` segment, and a Python chain directly continued by `.parent` (`.parents[1].parent`, `.parent.parents[i]`), are not read; a Python chain whose span overlaps an occurrence another reading made in that file is dropped | D1 needs one height per climb, and reading part of such a chain would surface a wrong landing point with a wrong `rewrite`; the spec tries the depth reading last | Summing mixed segments, outside D2/D3's grammar; keeping both overlapping occurrences, which would splice one span twice |
| D12 | Phase-5 review: a Python chain whose span overlaps a text climb the depth reading accepted in the same file is dropped, as one overlapping another reading's occurrence already was; regression pins the rewritten bytes of `S = "../../../HERE.parents[2]"` (Task 2) | Reviewer (B1): `taken` held only token occurrences, so the climb and the chain both edited one span and the splice in `rewritten` let the climb overwrite the chain's `.parents[3]`; D11's one-edit-per-span intent | Dropping the text climb instead (it spans the whole literal, so it is the edit that resolves the string as written) |
| D13 | Phase-5 review: a bound name is followed only when nothing else in the file rebinds it, at any indentation (plain, annotated, augmented, `:=`, `for`/`as`/`del`/`global`/`nonlocal`; a keyword argument of that name also excludes it), and `_BINDING` accepts a `\r\n` line end; negative case `HERE /= "/fixed/a/b/c"` and a CRLF regression (Task 2) | Reviewer (B2, B3): the column-0 `=` count missed `HERE /= ...`, proposing `.parents[3]` for a rebound name; `[ \t]*(?:#.*)?$` refused an uncommented binding ending in `\r`, which the strict-UTF-8 decode keeps, hiding AC1's chain; spec "assigned nowhere else" | Counting only column-0 assignments plus augmented ones (misses `for`/`with` rebinding); normalising line ends before matching (shifts offsets and the bytes `rewrite` splices) |
| D14 | Phase-6 review: a name that is a `def` or `lambda` parameter anywhere in the file counts as rebound and is not followed (widens D13); regression pins `def f(here)`, `def m(self, HERE)` and `lambda HERE:` (Task 2) | The task reviewer's probe: a shadowing parameter's chain shares the file's `/depth` policy answer and would be shifted wrongly; D13's own intent, "rebound nowhere else" | Keeping D13's binder list and accepting that a policy-wide rewrite shifts a parameter's chain |
