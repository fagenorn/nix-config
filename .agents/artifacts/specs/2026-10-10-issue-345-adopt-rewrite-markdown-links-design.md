# Issue #345 — adopt-project rewrites relative Markdown links across the moves

Issue: https://github.com/fagenorn/nix-config/issues/345 (blocks #210). Lineage: the
#148 adoption design (`2026-09-24-issue-148-adoption-plan-apply-verify-design.md`,
where `D15`, `D30` and `D33` resolve) and the #340 design
(`2026-10-09-issue-340-adopt-classify-agent-records-design.md`, whose `D6` this
issue supersedes).

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "plan document and evidence record gain a link-rewrite summary that enters plan_id, and a new commit gate joins the published COMMIT_GATES/READY_GATES sets"}, "concurrency_or_persistence": {"value": "hit", "evidence": "the stored plan document and the committed evidence record are persisted state whose shape changes"}, "open_design_questions": {"value": "hit", "evidence": "which files count as text/Markdown, how base-broken links are detected and reported, and whether the gate is ready-time, commit-time or both are open"}, "criteria_shape": {"value": "hit", "evidence": "five acceptance criteria, over the four-criterion bound"}}, "paths": ["python/agent_tools/adopt_apply.py", "python/agent_tools/adopt_planning.py", "python/agent_tools/adopt_inspection.py", "python/agent_tools/adopt_project.py", "python/agent_tools/adopt_links.py", "home/common/agent-skills/tests/test_adopt_apply.py", "home/common/agent-skills/tests/test_adopt_project.py", "python/README.md"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

`adopt-project apply` relocates whole trees with `git mv` (`.claude/specs`,
`.claude/plans`, `.claude/{handoffs,notes,research}`, archived candidates) and
changes nothing else that points at them. Every relative Markdown link into a moved
tree from a file that stayed put, and every relative link out of a moved file (now
at another depth), stops resolving. Nodo's adoption commit broke 1237 links in 555
files, and a repository that lints links cannot merge it. The operator has no way
to know before `apply`, and no record afterwards of what moved under which link.

## Solution

One new module, `agent_tools.adopt_links`, owns the whole notion of "a relative
Markdown link and what it resolves to" over a tree of tracked paths. Two callers
use it:

1. **Planning** derives, from the base revision's tree and the plan's moves, the
   rewritten bytes of every Markdown file whose links must change. Each becomes an
   ordinary `write-file` operation, and a `link_rewrites` summary enters the plan
   document, the evidence record and `plan_id`. A link that cannot be made to
   resolve to the same target fails a new ready gate, so the plan stays `draft`.
2. **Apply** runs a new commit gate that re-reads the worktree's `HEAD` tree (the
   base) and its index (the result) through the same module and fails when any file
   carries more broken relative links than its pre-move counterpart did, and proves
   the same count over the commit against its parent once the commit exists.

Already-broken links, URLs, prose mentions and non-Markdown files are left
byte-identical.

## Decisions

### What is rewritten (per D1, D2)

Link *targets* only, in two directions keyed by the containing file:

- **outbound**: every Markdown file a `git-mv` operation moves (classified
  relocations and `archive-history` answers alike);
- **inbound**: every other tracked Markdown file, `.claude/` files that adoption
  retains included.

A scanned file is a regular blob (mode `100644` or `100755`) in the base tree whose
path ends in `.md` or `.markdown` (ASCII case-insensitive), that decodes as strict
UTF-8, and that is not secret-shaped. The target of a `generated_file` projection is
not rewritten (per D10); a `managed_import` target is an ordinary file.

### Link grammar and resolution (per D3)

`adopt_links` recognises, line by line, outside fenced code blocks (a line of three
or more backticks or tildes, indented at most three spaces, closed by a fence of the
same character at least as long) and outside inline code spans:

- inline links and images, `[text](target)` / `![alt](target)`, on one line, with
  balanced brackets in the text and either a bare target (balanced parentheses, no
  whitespace) or an angle-bracket target `<...>`, optionally followed by a title;
- reference definitions, `[label]: target` with up to three leading spaces and an
  optional title.

A target is **relative** unless it is empty, starts with `#`, `/` or `//`, carries a
URL scheme (`^[A-Za-z][A-Za-z0-9+.-]*:`), or contains a backslash. Only relative
targets are ever resolved, counted or rewritten.

Resolution splits off the first `?` or `#` and everything after it (the suffix),
percent-decodes the path, joins it to the containing file's directory and
normalises it. The target **resolves** when the result stays inside the root and
names a tracked path, the root itself, or a directory that is a proper prefix of a
tracked path; a path written
with a trailing slash resolves only as such a directory. Resolution reads a set of
tracked paths, never the filesystem, so planning and the commit gate judge
identical trees identically.

### Rewriting (per D4, D5)

For each relative link that resolves at base: the containing file `F` maps to `F'`
(its move destination, else itself), and the target `T` maps to `T'`:

- a moved file maps to its destination; an unmoved file to itself, unless a
  `delete-file` operation removes it, which makes the link **unrewritable**;
- a directory that still contains a tracked path after the moves maps to itself;
- a directory every one of whose base members moved to `N + <member suffix>` for
  one `N` maps to `N`;
- any other directory that no longer exists (it dissolves into several
  destinations) is **unrewritable**.

The new target is the POSIX relative path from `dirname(F')` to `T'`, re-emitted in
the original's form: a leading `./` and a trailing slash are kept, the suffix and
title are kept verbatim, an angle-bracket target stays angle-bracketed with only `%`,
`#`, `?`, `<`, `>`, CR and LF percent-encoded (per D18), and a bare target is
percent-encoded with `urllib.parse.quote(path, safe="/")`. A link whose
re-emitted text equals the original is untouched, so links between files that moved
together stay byte-identical. A link that does not resolve at base is **already
broken** and is never touched. Rewriting replaces only the target's bytes, so a file's
link count and order never change.

### Bytes come from the base tree (per D6)

Planning reads every scanned blob from the commit `plan.base_revision` names (one
`git ls-tree -r` and one `git cat-file --batch`), never from the working tree. The
rewritten bytes are therefore a pure function of inputs `plan_id` already
authenticates, and `apply`, whose worktree is checked out at that revision, writes
exactly them. `composed.overlap` does not grow.

### Operations (per D7)

Each changed file is one `write-file` with `sources == targets == [F']`, `before`
the `sha256:` of its base bytes and `after` the `sha256:` of the rewritten bytes,
whose bytes go into the composition's `contents`. They are appended to the tail
after the legacy-binding rewrites and before the projection regenerations (so a
`generated_file` target renders its already-rewritten source), sorted by target. No
operation kind is added. A Markdown file named by any other `write-file` or
`delete-file` is a derivation bug and raises `ValueError`.

`expected_status` learns one fold: a `write-file` whose target is a `git-mv`
target contributes no record of its own, and that move is satisfied by its `R `
record or by the `D ` / `A ` pair Git reports when the edit drops similarity below
its rename threshold. `expected_commit_paths` and `prove_commit_content` need no
change: the paths are the ones the operations already declare.

### The summary (per D8)

The plan document gains a top-level `link_rewrites` member, and the evidence record a
member of the same name and value:

```json
{"inbound":  {"links": 0, "files": ["<path>"]},
 "outbound": {"links": 0, "files": ["<new path>"]},
 "unrewritable": [{"path": "<containing file at base>", "target": "<original target>"}],
 "already_broken": 0}
```

`links` counts rewritten links, `files` lists the rewritten files sorted,
`unrewritable` is sorted by `(path, target)`, and `already_broken` counts relative
links in scanned files that did not resolve at base. `link_rewrites` becomes the
seventh input of `compute_plan_id`, so the derivation runs before the id is taken.
`EVIDENCE_RECORD_MEMBERS` does not grow, so records committed by earlier adoptions
are still discovered (#148 D34). `--format human` prints one line,
`links: inbound <n> in <m> files, outbound <n> in <m> files, unrewritable <k>, already broken <b>`.

### Gates (per D9)

- **Ready gate `no-unrewritable-link`** (repair `adopt.link.unrewritable`), after
  `no-secret-path-in-moves` in `READY_GATES`: fails when `unrewritable` is non-empty.
  Message: "a relative Markdown link into or out of a moved path cannot be rewritten
  to resolve to the same target".
- **Commit gate `no-new-broken-link`** (repair `adopt.gate.no-new-broken-link`),
  before `cold-clone-resolves` in `COMMIT_GATES`: for every scanned file in the
  index, its count of non-resolving relative links must not exceed that of its
  base counterpart (the `git-mv` source when it moved, else the same path; zero when
  it is new), each counted against its own tree's tracked paths. The worktree's
  `HEAD` is the base revision until the commit, so the gate needs no new `GateRun`
  member.
- **Commit proof `prove_commit_links`** (repair `adopt.commit.new_broken_link`, per
  D17), beside `prove_commit_content`: the same per-file count over the commit's tree
  against its parent's. The verification commands run after the gate and a
  `pre-commit` hook after every gate; either can stage a broken link into a file the
  plan already writes, which changes no path `prove_commit_content` reads. Its
  refusal retains the worktree and branch like the content proof.

`verify` gains no check: it has no base to compare against.

### Documentation

`python/README.md`'s `adopt-project` section states the rewrite contract (directions,
grammar boundary, the summary and its place in `plan_id`) and the two gates.

## Test seams

All existing seams, driven as `python -m agent_tools.adopt_project` under the
recipe's `PYTHONPATH`, plus one unit seam for the module:

- **`adopt_links` functions** (new test module, imported normally): parsing,
  resolution and re-emission tables — fences, code spans, titles, angle targets,
  reference definitions, anchors and queries, percent-encoding, URLs, and directory
  mapping (AC2's boundary cases).
- **`plan` on a fixture repository** (`test_adopt_project.py`): a fixture with
  inbound and outbound links, an already-broken link, a URL and an unrelated link
  plans to `ready` with the expected `write-file` operations and `link_rewrites`
  summary (AC1, AC2, AC3). `compute_plan_id` over two summaries that differ only in
  the rewrite set yields two ids (AC3). A fixture linking `.claude/` while its
  contents dissolve into two destinations plans to `draft` with
  `no-unrewritable-link` failed and the link in `unrewritable` (AC4).
- **`apply` by plan id** (`test_adopt_apply.py`): the AC1 fixture applies; in the
  commit every previously resolving link resolves to the same file, every file keeps
  its link count, and already-broken links, URLs and untouched files are
  byte-identical; the evidence record carries the summary (AC1, AC3). The AC4
  fixture's stored plan with `plan.state` forced to `ready` refuses
  `verification_failed` / `adopt.gate.no-new-broken-link` and retains the worktree
  (AC4, the inner check of D9). A verification command and a `pre-commit` hook that
  each append a broken link to the planned `README.md` rewrite refuse
  `adopt.commit.new_broken_link` with the gate recorded passed (D17).

Existing key-set pins on `READY_GATES`, `COMMIT_GATES` and the evidence record are
updated in the same commit. AC5 is `just agent-workflow-tests`.

## Out of scope

- Prose (non-link) mentions of moved paths, inline HTML (`<a href>`, `<img src>`),
  root-relative (`/path`) targets, links whose text or target spans lines, and
  non-Markdown files.
- Fixing links already broken at base, and any `verify` check of link health.
- Wiki links, Nodo-specific link-lint integration and any Markdown dependency.
- Recomputing `plan.state` in `apply` from the re-derivation.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | `apply` rewrites relative Markdown link *targets* in every moved Markdown file (outbound) and every other tracked Markdown file (inbound), point-in-time records, archived candidates and retained `.claude/` files included; prose is never touched. Supersedes #340 D6 and amends #148 D30 (the living-reference sweep stays closed for non-link text) | The issue's explicit ask; the bar's "moves keep their history" protects a record's referent, which a link that resolves to the same file preserves and a dead link destroys; prose mentions keep the record's original text | Living documents only, which leaves Nodo's broken links in specs and plans that link each other and to code; rewriting prose mentions, which edits point-in-time text and is not mechanically decidable (#148 D30) |
| D2 | Scanned files are regular base-tree blobs ending `.md`/`.markdown` (case-insensitive), strict UTF-8, not secret-shaped; symlinks, undecodable and secret-shaped files are neither rewritten nor counted | The issue's "leave non-Markdown files alone"; `is_secret_path` is never read; the bar's YAGNI | All tracked text files, which needs a per-format link grammar no consumer asked for; `.mdx` and other dialects, which carry JSX the grammar does not model |
| D3 | One line-based grammar (inline links, images, reference definitions; fences and code spans excluded; backslash, scheme, `/`, `//` and `#` targets excluded) and tree-based resolution (relative to the containing directory, percent-decoded, suffix stripped, trailing slash means directory, outside-root never resolves), shared by planning and the commit gate | DRY: one authoritative definition of "resolves" so the prediction and the measurement cannot disagree; tracked-path sets keep plan and apply deterministic | A CommonMark dependency, which breaks the standard-library rule; filesystem resolution, which lets untracked files and case-insensitive volumes answer differently on another machine |
| D4 | The new target is the relative path from the moved containing directory to the mapped target, re-emitted in the original form (`./`, trailing slash, suffix, title, angle brackets kept; bare targets `quote(path, safe="/")`); an unchanged result is not a rewrite | Anchors kept per the issue; minimal byte change; links between co-moved files stay byte-identical | Repo-root-relative or absolute targets, which change every link's style; normalising every link in a touched file, which edits links that never broke |
| D5 | A dissolved directory target maps to `N` only when every base member moved to `N + suffix`; it and a file target a `delete-file` removes (a superseded evidence record) are the only unrewritable cases | A directory the moves split has no single successor that "resolves to the same" thing; AC4 needs a real impossible case | Picking the most common destination, which silently changes what the link points at; leaving it to break at commit time, rejected per D9 |
| D6 | Planning reads Markdown bytes from the base revision's tree, not the working tree, and `composed.overlap` does not grow | `plan_id` covers `base_revision` (#148 D15), so the rewrite bytes are authenticated by the id; `apply`'s worktree is checked out at that revision | Reading the working tree and adding 555 files to the dirty-overlap check, which refuses `apply` over any unrelated edit in an inbound file and writes bytes no id covers |
| D7 | Rewrites are ordinary `write-file` operations in the tail before projection regeneration; the status gate folds a write onto a `git-mv` target into that move's `R ` record or its `D `/`A ` pair | `write-file`'s contents map, result check, arity and commit-path proof already fit; #148 D33 re-derives and compares the list unchanged | A new `rewrite-links` kind, which grows the published `OPERATION_KINDS` and still needs the same status fold; one aggregate operation, which breaks per-path arity and the commit-path proof |
| D8 | A `link_rewrites` summary (per-direction link count and sorted files, `unrewritable` entries, `already_broken` count) is a top-level plan member, an evidence-record member and the seventh `compute_plan_id` input, amending #148 D15; `EVIDENCE_RECORD_MEMBERS` does not grow | AC3; a derivation change with the same repository changes the id, not only the stored `changes`; #148 D34 discovers records by member superset, so earlier records stay valid | Per-link lists, which run to thousands of rows for Nodo; adding the member to `EVIDENCE_RECORD_MEMBERS`, which makes every earlier adoption's record undiscoverable to `verify` |
| D9 | Both a ready gate `no-unrewritable-link` (prediction) and a commit gate `no-new-broken-link` (per-file non-resolving count in the index never exceeds the base counterpart's, mapped through the moves) | #340 D10/D14 reject leaving a predictable failure to `apply`; the bar's defense in depth (outer check for experience, inner for correctness); per-file counts need no link identity across rewrites | A commit gate alone, which approves an id that cannot apply; a ready gate alone, which trusts a stored plan and cannot see what regeneration or a verification command did |
| D10 | `generated_file` projection targets are not rewritten (the resolver owns their bytes and renders them from the rewritten source); the commit gate measures them | `render_projection` writes header plus source bytes verbatim; a rewrite would be overwritten and break the status gate's `M ` record | Rewriting them too, which the regeneration reverts; predicting rendered bytes at plan time, which duplicates the resolver's renderer |
| D11 | AC4's apply-level test forces the stored plan's `state` to `ready` on the unrewritable fixture and expects the commit gate's refusal with the worktree retained | The only way a plan with a failed ready gate reaches the commit gates; it exercises the inner check D9 exists for | A unit test of the gate function alone, which cannot show `apply` failing as AC4 asks |
| D12 | The link derivation runs before `plan_id` exists, so it treats every evidence record the inspection found as deleted (the superseded set without the exclusion of this plan's own record name) and judges directory survival against the base paths minus move sources and those deletions plus move destinations, never against adoption's own new writes | The plan's own record name and the records' paths depend on `plan_id`, which now depends on `link_rewrites` (D8); a pre-existing record named by a digest over its own summary is a SHA-256 fixed point; leaving new writes out can only turn a rewrite into `unrewritable`, never into a wrong target | A second pass after `plan_id`, which makes the id an input to its own derivation; counting the sentinel and the records as survivors, which needs `plan_id` first |
| D13 | `link_rewrites` is derived and published for every outcome, `not_applicable` included, like `evidence`; only an appliable outcome emits its `write-file` operations. `generated_file` targets are dropped from the scan before anything is counted, so the summary never mentions them | One member shape per document, not one per outcome; per D10 the resolver owns those bytes and only the commit gate measures them | A null or absent summary for `not_applicable`, which makes the member's type and the plan-id input depend on routing |
| D14 | Refines D4: a link is untouched when its decoded original path, joined to the new containing directory, already normalises to the mapped target (a path comparison, not a text comparison); a kept leading `./` is dropped when the new path climbs (`../`) | Co-moved links stay byte-identical even when a bare target holds characters `quote` would re-encode; `./../x` is not a form any author writes | Comparing re-emitted text, which rewrites a co-moved `ü.md` link to `%C3%BC.md`; keeping `./` unconditionally |
| D15 | Grammar refinements of D3: lines split at `\n` only (a `\r` stays on its line and never enters a target); a `[^label]:` footnote definition is not a reference definition; an unclosed fence runs to the end of the file; a backtick fence's info string carries no backtick; scanning resumes after each opening `[`, so an image inside link text is a link of its own | Footnote bodies are prose, not targets; `str.splitlines` splits on characters a Markdown line does not end at, which would shift offsets; one rule per case keeps plan and gate identical | Counting footnote bodies as broken links; CommonMark's full precedence rules, which need a parser the standard library lacks |
| D16 | The status gate folds a reported `D <source>` plus `A <target>` pair onto any planned `R <target> <source>` record, not only onto moves a link rewrite edits; the commit gate reads each tree's Markdown through one `git cat-file --batch`, for which `adopt_inspection.run_git` gains an optional `input` | A planned move reported as a split pair still changes exactly the planned paths, and `prove_commit_content` proves them; an unedited move is 100% similar and never splits, so the wider fold changes no current outcome | Threading the set of rewritten moves into the gate, which adds state for no observable difference; a subprocess call outside `run_git`, which duplicates its refusal contract |
| D17 | Refines D9: besides the commit gate, `apply` proves link health on the commit itself — `prove_commit_links` compares the commit's tree with its parent's under the gate's per-file count rule, runs directly after `prove_commit_content`, and refuses `verification_failed` / `adopt.commit.new_broken_link` with the worktree and branch retained (#148 D17); the gate stays | Plan review (PR-B1): `gate_workflow_verification_commands` runs project commands after the gate and a `pre-commit` hook runs after every gate, and `prove_commit_content` checks only the changed path set, so a broken link staged into an already-planned Markdown file lands while `apply` succeeds; the gate keeps the earlier, commit-free refusal (defense in depth) | The gate alone, which certifies an index the commit no longer matches; moving the gate after the verification commands, which still misses the hook; the proof alone, which leaves a commit behind for a failure the index already showed |
| D18 | Refines D4/D14: an angle-bracket target is re-emitted with `%`, `#`, `?`, `<`, `>`, CR and LF percent-encoded and every other character raw; bare targets keep `quote(path, safe="/")`, which already encodes the first three; both are tested to resolve back to the mapped target | Plan review (PR-B2): resolution splits the suffix at the first raw `?` or `#` and percent-decodes the rest, so a raw re-emission of tracked `a#b.md` reads as `a` plus a fragment and `100%.md` decodes differently; `<`, `>` and line breaks end or invalidate the angle target (D3) | Raw emission, which changes the referent; `quote` for angle targets too, which re-encodes spaces and non-ASCII the author wrote raw |
| D19 | Refines D15 and D18 (final review): the inline scan treats the whole `(destination "title")` region of a recorded link as covered and rejects a candidate whose region overlaps a recorded one, so a title is never scanned as a link; an angle target whose emitted relative path would open with a URL scheme (`urn:x.md`) gains a leading `./` | Final-review correctness findings COR-01 (a title rewrite changes literal title text and miscounts links) and COR-02 (`<urn:reference.md>` reads as a URI, so `is_relative` and both link gates miss the corruption) | Percent-encoding the colon in angle targets, which changes bytes D18 keeps raw; leaving titles scanned, which the issue's "preserve" contract forbids |
