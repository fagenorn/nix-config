# Issue 372 — adopt-project rewrites path literals inside moved files, by class

Issue: https://github.com/fagenorn/nix-config/issues/372 (blocks
https://github.com/fagenorn/nix-config/issues/371). Lineage, cited below as
"issue 345" and "issue 350" with their ledger rows: the Markdown link rewrite
(`2026-10-10-issue-345-adopt-rewrite-markdown-links-design.md`) and the path
references (`2026-10-10-issue-350-adopt-path-references-design.md`), whose terms
(token, occurrence, successor, carried form, shape) are used unchanged.

## Triage

Input: `contract_change=hit` (plan document, evidence record, `plan_id` inputs and `--answer` forms change), `concurrency_or_persistence=doubt` (stored plan document shape changes; no locking change), `open_design_questions=hit` (the spec chooses the design), `criteria_shape=hit` (seven criteria); paths: `python/agent_tools/adopt_references.py`, `adopt_planning.py`, `adopt_inspection.py`, `adopt_project.py`, `adopt_apply.py`, `python/README.md`, `home/common/agent-skills/tests/test_adopt_project.py`, `test_adopt_apply.py`. Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}`. `ran: full (shadow)`.

## Problem

An operator adopting a repository whose legacy tree holds working code (scripts
CI runs, modules a config imports, JSON the scripts read) gets a plan that moves
the tree and leaves every path literal inside it naming the old place: issue 350
reads only files outside the moved trees. The moved code breaks on the adopt
commit and nothing in the plan said it would. Where the operator can answer, the
answers do not scale: one `--answer` per occurrence across some two hundred
files. An exclusion written as a regular expression (`"^\\.claude/"`) is not
seen at all, and a tracked `.claude/settings.json` that the agent host reads in
place is offered only the archive, which would silently disable its hooks.

## Solution

Four extensions of issue 350's mechanism, all in the central tool:

1. Move sources are read for references. An occurrence in a moved file is edited
   on the base bytes and written at the file's destination, as a `write-file`
   after its `git-mv`, in the same commit (the route issue 345 gives a moved
   Markdown file).
2. Every occurrence in a moved file belongs to exactly one **reference policy**,
   keyed by the moved tree and the file's class. One `reference-policy` answer
   (`rewrite` or `retain`) decides the class; a `path-reference` answer on one
   occurrence overrides it. Nothing is edited without one of the two.
3. A token that is no occurrence as written is read once more as a **pattern
   spelling** (a leading `^`, dots escaped as `\.` or `\\.`), and its carried
   forms are emitted in the same spelling.
4. `.claude/settings.json` gains a classification row and is retained in place.

The plan reports what it will change before `ready` in three places: every
occurrence row carries its replacement, where the file is written and what
decided it; a `reference_policies` member counts each class; and the human view
prints one line per class.

## Decisions

### Moved files are scanned (per D1)

Issue 350's scanned-file rule loses one clause: "is not a move source". Every
other clause stands (regular, non-Markdown, non-secret, text, strict UTF-8, not
under the two record homes, not in adoption's own write set). The record-home
clause tests the base path, so a file is edited only by the adoption that moves
it and never again once it lives under `.agents/artifacts/` (per D8). The grep, the base
revision as the only source of bytes and the occurrence conditions are unchanged.

An occurrence's `path`, and so its `subject` `<path>:<line>:<column>`, stays the
file's path in the base tree. Each occurrence gains a **target**: the file's
destination when the plan moves it, else its own path.

`adopt_references.rewritten` keeps editing base text by base offsets. Planning
keys each edited file by its target and emits one `write-file` with
`sources == targets == [target]`, `before` the hash of the base bytes and `after`
the hash of the edited bytes, in the place issue 350 D9 gave reference writes.
`check_reference_writes` then allows a target exactly one in-place `write-file`
plus, when the target is a move destination, the one `git-mv` whose target it
is; anything else still raises. `apply` needs no change: its status expectation
already treats a write onto a move target as that move's content, and the split
rename fold already covers a moved file edited past rename similarity.

### Reference policies (per D2, D3, D4)

The **tree** of a moved file is the relocating group that holds it: the
classification row's path (`.claude/notes`), or the candidate's own path for an
`archive-history` answer. Its **class** is the lowercased final suffix of its
file name, dot included (`.py`), or `-` when the name has none. A file the plan
does not move has no tree and no policy: its occurrences are issue 350's,
answered one by one, unchanged.

The policy **subject** is `<tree>:<class>` (`.claude/notes:.py`). Subjects are
derived, never authored: every moved-file occurrence has exactly one, so two
policies cannot overlap. The closed answers are `rewrite` and `retain`.
`extend` is not a policy answer: it is shape-dependent and stays ratified per
occurrence.

`QUESTION_IDS` gains `reference-policy` after `path-reference`. An open entry is
`{"id", "subject", "answers", "value", "basis", "impact", "recommendation"}`:
`answers` is `["rewrite", "retain"]` and `value` is the recommended answer, from
one closed table in `adopt_references`:

| Class | `value` |
|---|---|
| `.py` `.sh` `.bash` `.zsh` `.nix` `.yaml` `.yml` `.toml` `.js` `.mjs` `.cjs` `.ts` | `rewrite` |
| `.json` `.jsonl` `.ndjson` `.csv` `.tsv` `.txt` `.log` | `retain` |
| any other class, `-` included | `null` |

A recommendation is never applied: an unanswered policy keeps the plan `draft`
through `no-open-decisions`, whatever its `value`. This is how `rewrite` is
bounded for data: a record class is rewritten only on an answer that names that
class and contradicts the printed recommendation, the edit is a whole-token
replacement by the row's published `replacement` and nothing else in the file,
and a policy never extends.

**Effective answer** of an occurrence, in order: its own `path-reference`
answer; else its policy's answer when the occurrence offers that value; else
none. So a per-occurrence answer always wins, and a `rewrite` policy leaves an
occurrence that offers no `rewrite` (an ancestor such as `".claude"`) undecided
rather than silently retained.

**Open questions.** A `reference-policy` question is open while it is unanswered
and at least one of its occurrences has no answer of its own. While it is open,
its occurrences open no `path-reference` question; they stay listed in
`path_references` with their subjects, so any of them can still be answered
individually. Once the policy is answered, each occurrence still without an
effective answer opens the ordinary `path-reference` question. Open questions
are ordered by id as in `QUESTION_IDS`, policies sorted by subject.

**Answering.** `plan --answer reference-policy <subject> <value>` rides the
existing flag and the one sorted pass of `apply_answers`; the id sorts after the
other two, so the candidate moves are settled and the references derived before
a policy is validated. Refusals are the existing codes:
`adopt.decisions.unmatched_answer` for a subject that is no policy of this
inspection, `adopt.decisions.invalid_answer` for a value outside the two or a
subject answered twice. A policy whose occurrences are all individually
answered is still a policy of the inspection and may be answered. Answers stay
`{id, subject, value}` in `decisions.answered`, so `stored_answers` and the
replay in `apply` are unchanged, and `rewritten` receives the effective answers.

### What the plan reports (per D5)

Each `path_references` row gains three members after `replacement`:
`"target"` (above), `"policy"` (the policy subject, or null outside a moved
tree) and `"decided_by"` (`"occurrence"`, `"policy"` or null); `answer` is the
effective answer. The plan document and the evidence record gain
`reference_policies`, one row per policy sorted by subject:

```json
{"subject": ".claude/notes:.py", "tree": ".claude/notes", "class": ".py",
 "recommended": "rewrite", "answer": null, "files": 2, "occurrences": 3,
 "rewritable": 3, "rewritten": 0, "retained": 0, "extended": 0, "open": 3,
 "overridden": 0}
```

`rewritable` counts the occurrences that offer `rewrite`, so a draft plan
already says what a `rewrite` answer would change; `overridden` counts those
decided by their own answer; the three outcome counts and `open` partition
`occurrences` by effective answer. `reference_policies` is the ninth input of
`compute_plan_id` and, like `path_references`, is derived and published for
every outcome; `EVIDENCE_RECORD_MEMBERS` does not grow. `decisions_accepted`
already lists the policy answers beside the others.

`--format human` keeps its `references:` line and adds, per policy row,
`policy <subject>: <files> files, <occurrences> occurrences, rewritable <n>,
rewritten <n>, retained <n>, extended <n>, open <n>`, and for an open one
`open reference-policy <subject> (answers: rewrite|retain, recommended:
<value or none>): <recommendation>`. The per-occurrence detail is read from the
stored plan document, which is what an approval of the plan id covers.

A plan stored before this change no longer equals its re-derivation, so `apply`
refuses it as it refuses any stale plan; the operator plans again.

### Pattern spellings (per D6)

The plain reading of issue 350 is tried first and decides alone when it yields an
occurrence. Only otherwise, and only for a token that starts with `^` or holds
`\.`, the **pattern reading** applies:

- the **anchor** is one leading `^`, or nothing;
- the **escape** is `\\.` when the token holds it, else `\.` when it holds
  that, else nothing;
- after the anchor comes an optional `/` prefix, then `/`-separated segments,
  each decoded by replacing the escape with `.`; the path is the longest
  leading run of decoded segments that are non-empty and hold neither a glob
  character nor a backslash; the tail is the rest of the token, verbatim.

The three occurrence conditions, the successors and the shapes then apply to the
decoded path as they do to a plain one. A carried form is anchor, prefix, the
successor with every `.` written as the escape (bare when there is none) and the
tail; it exists only when the successor holds nothing but letters, digits, `_`,
`-`, `.` and `/`, and reads back through the pattern reading to that successor.
`extend` therefore adds, beside `"^\\.claude/"`, one `"^\\.agents/artifacts/…/"`
element per wholly moved subtree, and `rewrite` and `retain` behave as for a
plain token. Rows and answers are otherwise those of any occurrence.

### The native settings file (per D7)

`CLASSIFICATION_RULES` gains
`(".claude/settings.json", "exact", "legacy-native-store", "retain-product", None)`
beside the `settings.local.json` row. A tracked settings file is then no
candidate: it opens no question, no operation names it, and the plan's
`evidence` carries its entry (`lifecycle_class` `legacy-native-store`, `action`
`retain-product`, `target` null), which the evidence record repeats as a
`sources` row with `after` null. Path literals inside it remain issue 350
occurrences, since the plan does not move it.

### Documentation

`python/README.md`'s `adopt-project` section gains the moved-file scan, the
policy question with its subject, answers, table and precedence, the three new
row members, `reference_policies` as the ninth `plan_id` input, the pattern
reading, and the settings row; the sentence that leaves move sources out goes.

## Test seams

The three seams of issue 350, driven as `python -m agent_tools.adopt_project`
under the recipe's `PYTHONPATH`. No new seam.

- **`adopt_references` functions** (`test_adopt_references.py`): tables for the
  pattern reading and its carried forms, including a token the plain reading
  already takes and a successor with no pattern form; the class of a file name;
  targets and policy subjects of moved and unmoved files; effective answers and
  `reference_policies` rows for policy only, override only and both; edits of a
  moved file's text.
- **`plan` on a fixture repository** (`test_adopt_project.py`): `.claude/notes`
  holds two Python scripts, a Nix module and a JSON record that each name a path
  under a moved tree; a script outside it runs one of them by path; a TOML file
  lists `"^\\.claude/"` among excludes; `.claude/settings.json` is tracked.
  - AC1: the plan is `draft` with three open `reference-policy` questions and no
    `path-reference` question for their occurrences; answering every policy and
    the outside occurrences makes it `ready`; the one `.py` answer sets
    `decided_by: "policy"` on the rows of both scripts.
  - AC3: the exclude's row offers `extend` with pattern-spelled additions.
  - AC4: no question names the settings file and its `evidence` entry is the
    retained row.
  - AC5: with `.py` answered `rewrite`, an override `retain` on one script
    occurrence and `.json` answered `retain`, only the other script occurrences
    carry `rewrite`; `link_rewrites` and the Markdown operations equal those of
    the same fixture without the non-Markdown files; issue 350's existing plan
    tests pass with only their row key-set pin updated.
  - AC6: the `rewrite` and `retain` policy plans have different ids, and
    `compute_plan_id` over two `reference_policies` values differing in one
    count yields two ids. Unknown subject, unoffered value and repeated subject
    refuse as above.
- **`apply` by plan id** (`test_adopt_apply.py`): the answered plan applies in
  one commit.
  - AC2: each rewritten file at its destination holds the new literal and no
    old one; the outside script, run with `sys.executable` on an export of the
    base and of the adopt commit, exits zero and prints the same on both.
  - AC3: the TOML file holds the old element and the additions.
  - AC4: the settings file is byte-identical at its path, and the evidence
    record's `sources` row for it has `after` null.
  - AC5: the JSON record at its destination and an unrelated file are
    byte-identical to their base blobs.
  - AC6: the evidence record carries the policy answers in `decisions_accepted`
    and equals the plan's `reference_policies` and `path_references`.

Key-set pins on the plan document, the evidence record, the row and
`QUESTION_IDS` move in the same commit. AC7 is `just agent-workflow-tests`.

## Out of scope

- Any Arcwave-specific case, and running the adoption on Arcwave (issue 371).
- Variables, joined segments and paths relative to the file's own directory;
  issue 350's occurrence conditions and shapes are not widened.
- Operator-authored globs as policy subjects, policies for files the plan does
  not move, `extend` as a policy answer, and a default applied without an answer.
- Pattern spellings beyond a leading `^` and escaped dots: an end anchor `$`,
  character classes, groups, alternation, and a `./` prefix inside a pattern.
- A candidate question offering both answers for a native settings file, and
  rows for other native files.
- Markdown link rewriting, record homes, a new gate, operation kind or `verify`
  check.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Move sources are scanned; an occurrence keeps its base path as subject, gains a `target`, and its file is one `write-file` at the destination after the `git-mv`, with `check_reference_writes` admitting that one move | Issue 345 writes a moved Markdown file the same way and `apply`'s status expectation and rename fold already carry it; issue 350 D7 (base-tree positions are the stable subject); the bar's "re-point every living document in the same commit" | A subject at the destination path, which names a file the operator cannot open before `apply`; a second commit for the edits, which breaks the atomic adopt commit |
| D2 | One derived policy per (relocating group, file-name suffix), id `reference-policy`, subject `<tree>:<class>`, answers `rewrite` and `retain`; only moved files have one | The issue's "policy answer per (moved tree, file class or glob) with closed values"; issue 350 D7 (answers are `{id, subject, value}` matched by equality against derived subjects); derived subjects partition the occurrences, so the bar's fail-loud closed set holds | Operator-authored globs, which overlap, need a precedence order among themselves and cannot be listed as open questions; a fixed code/data taxonomy as the subject, which cannot separate `.nix` from `.py` in one tree |
| D3 | A policy question carries a recommended `value` from one closed suffix table (code and config `rewrite`, records `retain`, anything else null) and is never applied without an answer | The issue asks which classes default to which answer and names AC1 (not `ready` until decided); issue 350 D5 forbids an unanswered edit, which a recommendation respects; the bar keeps point-in-time records at their original paths, hence `retain` for record classes | An applied default, which edits code no one approved or reproduces the silent breakage; no recommendation at all, which leaves the operator to rediscover the record risk the issue names |
| D4 | A per-occurrence answer overrides the policy; a policy value the occurrence does not offer leaves it open; occurrences under an open policy open no question of their own | The issue's "per-occurrence answers still possible as overrides"; the specific answer is the later, narrower ratification; fail loud rather than coerce `rewrite` into `retain`; the bar's token economy at two hundred files | Policy over occurrence, which makes an override impossible; a `rewrite` policy silently retaining what it cannot rewrite; listing every occurrence as an open question beside its policy |
| D5 | Rows gain `target`, `policy` and `decided_by`; a `reference_policies` count row per policy is a plan member, an evidence-record member and the ninth `plan_id` input; the human view prints one line per policy | The issue's "how the plan reports what it will change before `ready`" and AC6; issue 350 D8 (the row is where a reviewer sees the edit, and each published summary is an id input so a derivation change changes the id) | Counts only, which hide the replacements; printing every row in the human view, which buries the plan at this volume; leaving the summary out of the id because rows imply it, which lets the recommendation table drift under one id |
| D6 | A token the plain reading rejects is read as a pattern: leading `^`, dots escaped `\.` or `\\.`; carried forms keep anchor, escape and tail, and exist only for successors of letters, digits, `_`, `-`, `.`, `/` | The issue's example `"^\\.claude/"`, which is a TOML or JSON string holding a regex; trying the plain reading first keeps every issue 350 occurrence byte-identical (AC5); the standard-library, no-parser rule of issue 350 D6 | A regex parser, which the package cannot carry and the example does not need; decoding escapes for every token, which changes what existing tokens match |
| D7 | `.claude/settings.json` gets a `legacy-native-store` / `retain-product` classification row; retention is the classification, not an answer | Every other native store the host reads in place (`settings.local.json`, `.mcp.json`, `.codex`, skills, rules, hints) is a row of that shape; the issue says archiving "would silently disable the hook" and suggests retain as the default; the evidence entry is where the plan says so (AC4) | A two-answer candidate question recommending retain, which adds an answer form and a prompt for a file no adoption should move; leaving it a candidate, which offers only the archive |
| D8 | Grill: the record-home exclusion keeps testing the base path, so a moved file is editable once, on an answer, by the adoption that moves it, and a later adoption never re-reads it at its destination | The bar's "point-in-time records keep their original paths" against the owner's 2026-10-12 decision that the moved tree must keep working; issue 350 D2 already skips the record homes, and D3's `retain` recommendation covers the record classes at the one moment they are editable | Testing the destination, which would exclude every moved file and undo the issue; dropping the exclusion, which lets a re-adoption rewrite accepted records |
