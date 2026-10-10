# Task 4: The rewrite contract is documented

**Files:**
- Modify: `python/README.md` (`## adopt-project`)

**Interfaces:**
- Consumes: the behaviour Tasks 1–3 implemented — `agent_tools.adopt_links`, the `link_rewrites` plan and evidence-record member, the seventh `compute_plan_id` input, the ready gate `no-unrewritable-link`, the commit gate `no-new-broken-link` and the post-commit proof `adopt.commit.new_broken_link`.
- Produces: one new paragraph in `python/README.md` § `adopt-project`, after the existing paragraph.

**Invariants:**
- The paragraph states only what the code at this task's start does; where the implementation diverged from a sentence below (an implementer's documented deviation in Tasks 1–3), the sentence follows the code and the commit message names the divergence.
- No other section of `python/README.md` and no `CLAUDE.md` text changes.

- [ ] **Step 1: Confirm the gate fails at the start commit**

Run: `if grep -q 'no-new-broken-link' python/README.md; then exit 1; fi`
Expected: exit 0 (the contract is not yet documented).

- [ ] **Step 2: Write the paragraph**

Append to `## adopt-project`, as its own paragraph, text to this effect (adjust only where Step 1's invariant demands):

> `adopt-project plan` rewrites relative Markdown link targets across its moves (#345): outbound in every Markdown file a `git-mv` moves, inbound in every other tracked Markdown file (a regular `.md`/`.markdown` blob, strict UTF-8, not secret-shaped; a `generated_file` projection target is left to its regeneration). `agent_tools.adopt_links` owns the grammar — inline links and images on one line and reference definitions, outside fenced code and code spans — and resolves a target against the tracked paths of a tree, never the filesystem: a target is relative unless it is empty, starts with `#` or `/`, carries a URL scheme or holds a backslash, and it resolves when its percent-decoded path, joined to the containing directory, names a tracked file or a directory inside the root. The rewritten bytes come from the plan's base revision, each changed file is a `write-file` placed before the projection regenerations, and a rewritten target keeps its anchor or query, title, angle brackets and trailing slash, and its leading `./` unless the new path climbs out with `../`; a bare target is percent-encoded and an angle target encodes only `%`, `#`, `?`, `<`, `>` and line breaks, so the emitted path names the same file; a link that already fails to resolve, a URL and a link the moves leave correct stay byte-identical. The plan document and the adoption evidence record carry `link_rewrites` (`inbound` and `outbound` link counts and sorted files, `unrewritable` `(path, target)` entries and an `already_broken` count), which is the seventh input of `plan_id`. The ready gate `no-unrewritable-link` (`adopt.link.unrewritable`) keeps the plan `draft` when a link targets a file the plan deletes or a directory the moves dissolve into several destinations, and `apply`'s commit gate `no-new-broken-link` (`adopt.gate.no-new-broken-link`), before `cold-clone-resolves`, refuses when any Markdown file in the index has more non-resolving relative links than its pre-move counterpart at `HEAD`; because the verification commands and a `pre-commit` hook run after it, the same count over the commit against its parent is proved again once the commit exists, and a failure there refuses `adopt.commit.new_broken_link` with the worktree and branch retained. Prose mentions of moved paths, inline HTML, root-relative targets and non-Markdown files are never rewritten.

- [ ] **Step 3: Verify**

Run: `for term in no-new-broken-link no-unrewritable-link link_rewrites adopt_links adopt.commit.new_broken_link; do grep -q "$term" python/README.md || exit 1; done`
Expected: exit 0.
Run: `git diff --stat HEAD -- python/README.md CLAUDE.md`
Expected: only `python/README.md` changed.

- [ ] **Step 4: Commit**

```bash
git add python/README.md
launch-commit … -- -m "docs(adopt): document the Markdown link rewrite contract (#345)"
```
