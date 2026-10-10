# Issue 350 — adopt-project carries path-scoped tooling references across the moves

Issue: https://github.com/fagenorn/nix-config/issues/350 (blocks
https://github.com/fagenorn/nix-config/issues/210). Lineage, cited below as
"issue 148", "issue 340" and "issue 345" with their ledger rows: the adoption design
(`2026-09-24-issue-148-adoption-plan-apply-verify-design.md`), the candidate
questions (`2026-10-09-issue-340-adopt-classify-agent-records-design.md`) and the
Markdown link rewrite (`2026-10-10-issue-345-adopt-rewrite-markdown-links-design.md`).

## Triage

Input: `{"signals":{"contract_change":{"value":"hit","evidence":"adopt plan gains a new question kind with closed answers covered by the plan id, and the evidence record gains a field"},"concurrency_or_persistence":{"value":"no","evidence":"edits ride the existing atomic adopt commit; no new locking or persisted state"},"open_design_questions":{"value":"hit","evidence":"issue says the spec chooses between a plan inventory with questions and/or a gate extension"},"criteria_shape":{"value":"hit","evidence":"five acceptance criteria"}},"paths":["python/agent_tools/adopt_planning.py","python/agent_tools/adopt_inspection.py","python/agent_tools/adopt_apply.py","python/agent_tools/adopt_links.py","python/agent_tools/adopt_verify.py","python/agent_tools/adopt_project.py","home/common/agent-skills/tests/test_adopt_apply.py","python/README.md"]}`
Verdict: `{"hits":["contract_change","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

`adopt-project apply` moves whole trees and rewrites the Markdown links across
them, but a tracked script or config that names a moved tree by path keeps naming
the old place. A link linter that exempts `.claude/` stops exempting the records
that moved to `.agents/artifacts/`, so links that were already broken and exempt
become failures: the repository's own check is green on the base and red on the
adopt commit. The operator learns this from CI, after `apply`. `.claude/` itself
survives the adoption, so replacing the literal would be as wrong as leaving it.

## Solution

One new module, `agent_tools.adopt_references`, owns "a path literal in a tracked
non-Markdown text file that names something the plan moves, and the forms it can
be carried in". Planning derives every such **path reference** from the base
revision's tree and the plan's moves, and opens one `path-reference` question per
occurrence. The operator answers each with `extend`, `rewrite` or `retain`;
nothing is edited without an answer, and the existing `no-open-decisions` gate
keeps the plan `draft` until every occurrence is answered. An `extend` or
`rewrite` answer becomes part of an ordinary `write-file` operation in the same
atomic commit. Every occurrence, with its answer and the exact text it adds, is
published in the plan document and the evidence record and enters `plan_id`.

No gate is added (per D1): the commit gate `workflow-verification-commands`
already runs the project's own checks on the adopted tree.

## Decisions

### Scanned files (per D2, D10)

A scanned file is a regular blob (mode `100644` or `100755`) in the base tree that

- is not Markdown by `adopt_links.is_markdown_path`, and is not secret-shaped;
- git does not judge binary, and that decodes as strict UTF-8;
- is not a move source, and is not under `.agents/artifacts/` or
  `.agents/knowledge/archive/`, the homes of point-in-time records;
- is not a path adoption itself may write, whether or not this plan writes it:
  the contract, `.gitignore`, the runtime sentinel, a legacy binding config, or a
  `generated_file` projection target (the set the link rewriter already skips).

Candidates are found with one `git grep -I -l -z -F` at `plan.base_revision` for
the first path segment of every move source; a secret-shaped name is dropped
from that list before the module reads any blob. Bytes come from the base tree,
never the working tree (issue 345 D6), and `composed.overlap` does not grow.

### Occurrences (per D3)

Lines split at `\n` only. A **token** is a maximal run of characters other than
whitespace and `"`, `'`, `` ` ``, `,`, `;`, `:`, `=`, `(`, `)`, `<`, `>`, `|`, `&`,
`#`, `!`. A token is read as

- an optional **prefix**, one leading `./` or `/`;
- the **path** `P`: the following `/`-separated segments up to, not including, the
  first segment that holds `*`, `?`, `[` or `{`, without a trailing slash;
- the **tail**: everything after `P` (a trailing slash, a glob, or nothing).

A token is an occurrence when all of these hold:

1. it contains a `/`, or it is the whole content of a string quoted with one of
   `"` or `'` on that line;
2. `P` is non-empty and names a tracked file or a directory of the base tree
   (`adopt_links.Tree`, never the filesystem);
3. at least one move source is `P` or lies under it.

So `.claude/`, `/.claude/specs/**`, `".claude"` and `.claude/specs/x.json` are
occurrences when the plan moves something under them, and the bare word `docs`
in a comment, a URL, `$ROOT/.claude/specs` and `os.path.join(".claude", "specs")`
are not: a path that is not written whole and repository-relative is out of scope.

### Successors (per D4)

`P` has a **single successor** when it is a moved file (its destination) or a
directory that no longer exists after the moves and whose base members all moved
by the same relative tails under one new directory. This is the rule
`adopt_links` already applies to a link's directory target, exported from there
rather than restated. Otherwise `P` survives or dissolves, and its successors
are the distinct successors, sorted, of the maximal subtrees under it that each
have a single successor: moved files and wholly moved directories.

A **carried form** of the token for successor `S` is `prefix + S + tail`. When
`P` has no single successor, carried forms exist only for a tail that is empty,
`/` or `/**`, and a file successor is emitted without the tail. A carried form
that would not read back as one token with path `S` (a destination holding a
delimiter) does not exist.

### Answers and edits (per D5, D6)

Each occurrence offers a subset of the closed set, in this order:

- **`extend`**, offered when every successor has a carried form and the token sits
  in one of two shapes. *Quoted element*: the token is the whole content of a
  quoted string whose preceding non-blank character on the line is `[`, `{`, `,`,
  nothing, or a `(` not directly preceded by an identifier character, `)` or `]`
  (a call), and whose following non-blank character is `,`, `]`, `)`, `}` or
  nothing; the edit inserts `, <q><form><q>` per successor directly after the
  closing quote. *Line element*: the line is indentation, an optional `- `
  marker, the token (optionally quoted) and optional trailing blanks, and is not
  a quoted element; the edit inserts after it one copy of the line per successor
  with the token replaced, each with the line's own terminator (a final
  unterminated line gains `\n` before the copy).
- **`rewrite`**, offered when `P` has a single successor with a carried form; the
  edit replaces the token with it.
- **`retain`**, always offered; no edit.

Edits in one file are applied from the last offset to the first. The shapes are
proposals, not proofs: the tool cannot tell a prefix list from a call's argument
list, so the operator ratifies the exact `additions` the plan prints. When
neither edit is derivable, `retain` is the only answer and records that the
operator has seen the reference.

### The question (per D7)

`QUESTION_IDS` gains the literal `path-reference`, after `candidate-class`. An open
entry is `{"id", "subject", "answers", "basis", "impact", "recommendation"}`:
`subject` is `<path>:<line>:<column>` (1-based, the column counted in characters
to the token's first character), `answers` the offered subset, and the three
prose members fixed constants that never name a path. It has no `value` member:
no answer is recommended. `--format human` prints
`open path-reference <subject> (answers: <a>|<b>): <recommendation>`.

`plan --answer path-reference <subject> <value>` settles one. `apply_answers`
keeps its one sorted pass and its refusal order; `candidate-class` answers are
validated and applied first because they add moves, and the references are
derived from the settled moves before `path-reference` answers are validated.
The refusals are the existing ones: `adopt.decisions.invalid_answer` for an
unknown id, a `(id, subject)` answered twice or a value the occurrence does not
offer, and `adopt.decisions.unmatched_answer` for a subject that is not an
occurrence of this inspection. Answers stay `{id, subject, value}` in
`decisions.answered`, so `apply` re-applies them from the stored plan unchanged
(issue 340 D5, D9).

### The summary (per D8)

The plan document gains a top-level `path_references` member, and the evidence
record a member of the same name and value: one row per occurrence, sorted by
`(path, line, column)`:

```json
{"subject": "<path>:<line>:<column>", "path": "<path>", "line": 1, "column": 1,
 "literal": "<token>", "answers": ["extend", "retain"], "answer": null,
 "additions": ["<carried form>"], "replacement": null}
```

`answer` is the settled value or null, `additions` what `extend` inserts (empty
when not offered) and `replacement` what `rewrite` writes (null when not
offered). It is derived and published for every outcome (issue 345 D13) and is
the eighth input of `compute_plan_id`. `EVIDENCE_RECORD_MEMBERS` does not grow
(issue 148 D34). The record's `decisions_accepted` already lists the answers.
`--format human` prints `references: <n> occurrences, extended <e>, rewritten <r>,
retained <k>, open <o>`.

### Operations (per D9)

Each file with at least one `extend` or `rewrite` answer is one `write-file` with
`sources == targets == [path]`, `before` and `after` the `sha256:` of its base and
edited bytes, appended to the tail after the Markdown link rewrites and before
the projection regenerations, sorted by target. No operation kind, ready gate or
commit gate is added, and `verify` gains no check. A reference write naming a
path any other operation names is a derivation bug and raises `ValueError`, as
for Markdown writes. `apply` re-derives the list
through `compose_plan` and requires byte equality with the stored `changes`
(issue 148 D33), which is the inner check on these edits.

### Documentation

`python/README.md`'s `adopt-project` section gains the `path-reference` question,
its answers and shapes, the `path_references` member and its place in `plan_id`,
and no longer says non-Markdown files are never rewritten.

## Test seams

Existing seams, driven as `python -m agent_tools.adopt_project` under the recipe's
`PYTHONPATH`, plus one unit seam (issue 345's layout):

- **`adopt_references` functions** (new test module, imported normally): tables
  for tokenising, the occurrence conditions, successors and carried forms, the
  two shapes and the offered answers, and the edited text.
- **`plan` on a fixture repository** (`test_adopt_project.py`): the fixture holds
  a link-check script exempting `("docs/archive/", ".claude/")`, already-broken
  links inside `.claude/specs`, retained `.claude/` content and an unrelated
  script. `plan` is `draft` with `no-open-decisions` failed and one
  `path-reference` question whose subject is equal across two runs (AC1); with
  `--answer ... extend` it is `ready` (AC1); the `extend` and `retain` plans have
  different ids, and `compute_plan_id` over two summaries differing in one row
  yields two ids (AC4); the Markdown operations and `link_rewrites` equal those of
  the same fixture without the script (AC3). An unknown subject and an unoffered
  value refuse as above.
- **`apply` by plan id** (`test_adopt_apply.py`): the `extend` plan applies; the
  script in the commit holds the old literal and the additions, the unrelated
  script is byte-identical, and the fixture's own script, run with
  `sys.executable` on an export of the base and of the adopt commit, exits and
  prints the same (AC2, AC3); the evidence record carries the answer in
  `decisions_accepted` and the row in `path_references` (AC4).

Key-set pins on the plan document, the evidence record and `QUESTION_IDS` are
updated in the same commit. AC5 is `just agent-workflow-tests`.

## Out of scope

- Paths not written whole and repository-relative: variables, joined segments,
  URLs, bare unquoted single words, backslash paths, YAML flow sequences.
- `extend` shapes beyond the two (`CODEOWNERS` and `.gitattributes` field lines,
  mapping keys and values); those occurrences still offer `rewrite` or `retain`.
- Prose mentions in Markdown, and any change to issue 345's link rewriting.
- A gate that models a foreign check's scope, a `verify` check, a default answer,
  bulk answers, and dropping an addition the file already lists.
- Any Nodo-specific case, and running the adoption against Nodo.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Build the plan inventory with questions (the issue's first candidate) and no new gate | The issue's AC1 and AC2 are plan and answer behaviour; a central tool cannot know what a repository's check covers without running it, and `workflow-verification-commands` already runs it at commit time (the bar's defense in depth is met by that gate plus issue 148 D33) | A sibling of `no-new-broken-link` treating "exempt before, checked after" as new, which needs a model of each foreign linter's scope, the repository-specific knowledge the issue forbids |
| D2 | Scanned files are regular, non-Markdown, non-secret base-tree blobs that git judges text and that decode as strict UTF-8, excluding move sources, the two record homes and adoption's own write set (D10); found by one `git grep -I -l -F` at the base revision | Issue 345 D2 and D6 (base bytes, `plan_id` authenticates them); the bar's "moves keep their history" keeps point-in-time records unedited; one writer per path keeps `write-file` arity | Reading every non-Markdown blob through `cat-file`, which loads a repository's binaries; an extension allowlist, which misses `CODEOWNERS` and extensionless scripts |
| D3 | An occurrence is a delimiter-bounded token, read as prefix, path and tail, that contains `/` or is a whole quoted string, whose path names a base-tree file or directory with a move source at or under it; ancestors of moved trees count | The motivating literal `.claude/` is an ancestor of the moved trees, not one of them; tree lookup (issue 345 D3) keeps plan and apply deterministic; quoting admits `".claude"` in a directory-name set without admitting the word `docs` in prose | Substring search for old paths, which fires inside URLs and longer names; matching only exact moved roots, which misses the issue's own case |
| D4 | Successors reuse `adopt_links`' directory-successor rule; a surviving or dissolved path maps to the successors of its maximal wholly moved subtrees, with carried forms only for an empty, `/` or `/**` tail | DRY: one definition of where a directory went; "everything under" is the only tail whose meaning is unchanged when its base moves down to several roots | The common ancestor of the destinations (`.agents/`), which widens the scope to unrelated trees; carrying any glob tail, which changes its depth |
| D5 | Closed answers `extend`, `rewrite`, `retain`; each occurrence offers only those with a derivable edit, `retain` always, and none is recommended or defaulted | The issue's closed answers and AC1; issue 340 D4 and D7 (the entry names what it accepts, and an underivable answer is not offered); the bar's fail loud | Defaulting to `retain`, which reproduces today's silent breakage; defaulting to `extend`, which edits code no one approved |
| D6 | `extend` edits two shapes only, a quoted sequence element (insert after the closing quote) and a whole-line element (insert copied lines); a `(` that follows an identifier, `)` or `]` is a call and not a sequence | Covers Python, JS, JSON and TOML sequences inline or one per line, YAML block items and ignore-style pattern files without a parser, per the standard-library rule; the operator ratifies the printed additions | Per-language parsing, which the package cannot carry; duplicating any line that holds the literal, which turns an assignment or condition into a second, overriding statement |
| D7 | One literal id `path-reference` keyed by `subject` `<path>:<line>:<column>`, an `answers` list and no `value`; answers travel as `{id, subject, value}` through the existing `--answer` flag, validation order and stored-plan replay | Issue 148 D35 and issue 340 D3, D5, D9; base-tree bytes make the position stable across plans of one revision, the stability issue 340 gives `subject`; `stored_answers` already pins the shape | A content-hash subject, which the operator cannot map to a place; one question per file and literal, which cannot give two uses in one file different answers |
| D8 | A `path_references` row per occurrence (position, literal, offered answers, settled answer, additions, replacement) is a plan member, an evidence-record member and the eighth `compute_plan_id` input | AC4; issue 345 D8 (a derivation change changes the id, and earlier records stay discoverable because `EVIDENCE_RECORD_MEMBERS` does not grow); the write operation shows only hashes, so the row is where a reviewer sees what was added | Counts only, which hide what each answer wrote; detail on the open-question entry alone, which vanishes once answered |
| D9 | Edits are ordinary `write-file` operations in the tail after the link rewrites; amends issue 148 D30 and issue 340 D6: a reference outside the legacy sweep is now reported, and edited only on the operator's answer | Issue 345 D7 (the contents map, result check and commit-path proof already fit); the bar's "re-point every living document in the same commit"; issue 340 D6 named report-only as the direction, and an answered question is the decision D30 said could not be made mechanically | A new operation kind, which grows the published `OPERATION_KINDS`; a separate follow-up commit, which breaks the atomic adopt commit the issue asks for |
| D10 | Grill: the files adoption itself may write are excluded as a fixed set (contract, `.gitignore`, runtime sentinel, legacy binding configs, `generated_file` targets), not as "targets of this plan's other operations"; `candidate-class` answers settle the moves before references are derived | `path_references` is a `compute_plan_id` input and the operation list is built after the id, so an exclusion read from that list is circular (issue 345 D12); `generated_targets` is already computed before the id; a candidate answer adds a move, so the reverse order would miss its references | Deriving references after `plan_id`, which leaves the rows outside the id; chaining a reference edit onto the `.gitignore` or contract write, which gives one path two generators |
