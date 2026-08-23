# Task 2: Drop the stale skill count from the skillsDir comment

**Files:**
- Modify: `home/common/claude-code/default.nix` — the first of the two comment lines above
  `skillsDir` (line 910 at the base commit). One line changes; the option binding and the
  second comment line stay byte-identical.
- Test: none, and none is added. Adding a contract test that asserts the skill count would
  re-create the second authoritative home this task exists to remove (per D5, D7).

**Interfaces:**
- Consumes: from Task 1, a `CLAUDE.md` that states no skill count. After this task the
  repository states the number of global skills in exactly one place — the directory
  `home/common/agent-skills/skills/` itself.
- Produces: nothing a later task depends on. This is the final task.

**Invariants:**
- The comment states no skill count at all. The count is deleted, not corrected to today's
  value: a restated count is a second home for a fact the directory already owns, and it has
  drifted once already (per D5).
- The edit is comment-only. `skillsDir = ../agent-skills/skills;` is unchanged, so the
  evaluated configuration is identical before and after; `just build` proves that the file
  still evaluates and the system still builds, and proves nothing else.
- The comment's remaining content stays true: `prototype/` is still the multi-file example,
  and `~/.claude/skills` is still a real directory rather than a link.
- `just switch` is never run. Activation is the author's call, not this pipeline's.

- [ ] **Step 1: Install the content-assertion gate and watch it fail**

```bash
cd "$(git rev-parse --show-toplevel)"
mkdir -p "$(git rev-parse --show-toplevel)/.superpowers/gates"
cat > "$(git rev-parse --show-toplevel)/.superpowers/gates/task-2.sh" <<'GATE'
#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
M=home/common/claude-code/default.nix
fail() { echo "FAIL: $1" >&2; exit 1; }

# A - the stale count is gone from the module (it is present at the base commit)
if grep -qE '[0-9]+ global skills' "$M"; then fail 'the skillsDir comment still states a skill count'; fi

# B - the corrected comment is present, and only its first line moved
grep -qF '# ~/.claude/skills/<name>/ — the global skills, recursively symlinked (multi-file skills' "$M" \
  || fail 'the corrected skillsDir comment line is absent'
grep -qF '# like prototype/ keep SKILL.md + UI.md + LOGIC.md). ~/.claude/skills stays a real dir.' "$M" \
  || fail 'the second comment line changed; this edit is one line only'

# C - comment-only: the option binding is untouched
# anchored past leading whitespace so a `#`-commented copy of the binding cannot satisfy it
grep -qE '^[[:space:]]*skillsDir = \.\./agent-skills/skills;' "$M" || fail 'the skillsDir binding changed'

# D - no skill count restated anywhere in the live configuration or the context doc (D5)
# status 1 is "no matches" and is the expected clean result; anything above 1 is a broken search
# (bad pathspec, not a repo) and must not be flattened into an empty, PASS-looking $stray
gs=0
stray=$(git grep -InE '[0-9]+ global skills' -- ':!.claude/plans' ':!.claude/specs') || gs=$?
[ "$gs" -le 1 ] || fail "the skill-count sweep's git grep failed with status $gs"
if [ -n "$stray" ]; then fail "a skill count is restated: $stray"; fi

# E - the comment's surviving example is still true
for f in SKILL.md UI.md LOGIC.md; do
  [ -f "home/common/agent-skills/skills/prototype/$f" ] \
    || fail "prototype/$f is gone; the comment's multi-file example is stale"
done

echo "task-2 gate: PASS"
GATE
bash "$(git rev-parse --show-toplevel)/.superpowers/gates/task-2.sh"
```

Expected at this task's starting commit: **FAIL** with
`FAIL: the skillsDir comment still states a skill count`. Check A is the falsifying one —
the module reads `the 8 global skills` while `home/common/agent-skills/skills/` holds 16
directories. The gate is fail-fast, so A is the only failure you will observe.

At the base commit: **A and D both fail** — they are keyed to the same stale count, A in the
module and D repo-wide — and **B fails**, because it asserts the corrected comment Step 2 has
not written yet. Only **C and E** pass beforehand and are true regression guards.

If check A does not fail here, the comment is not in the state this task assumes — stop and
read `sed -n '908,913p' home/common/claude-code/default.nix` before editing.

- [ ] **Step 2: Delete the count**

Replace this line in `home/common/claude-code/default.nix`:

```text
    # ~/.claude/skills/<name>/ — the 8 global skills, recursively symlinked (multi-file skills
```

with:

```text
    # ~/.claude/skills/<name>/ — the global skills, recursively symlinked (multi-file skills
```

The only change is deleting `8 `. Keep the em dash, the indentation and the line's role as
the first of a two-line comment; leave the following line
(``    # like prototype/ keep SKILL.md + UI.md + LOGIC.md). ~/.claude/skills stays a real dir.``)
and the `skillsDir` binding untouched. Do not replace `8` with `16` — the directory is the
one authoritative home for its own size (per D5).

- [ ] **Step 3: Verify**

Run: `bash "$(git rev-parse --show-toplevel)/.superpowers/gates/task-2.sh"`
Expected: `task-2 gate: PASS`, exit 0, no `FAIL:` line.

Run: `git diff HEAD --numstat -- home/common/claude-code/default.nix && git diff HEAD --name-only`
Expected: `1	1	home/common/claude-code/default.nix`, and that path as the only name printed.

Run: `just build && test -L result && echo BUILD_OK`
Expected: the `Building nix-darwin config...` banner, then `BUILD_OK`. This is slow (minutes,
longer on a cold store) and it is the repo's unconditional rule after editing any `.nix`
file, comment-only or not (per D7). It proves the flake still evaluates and
`darwinConfigurations.mbp.system` still builds. It proves nothing about the comment's
wording or about `CLAUDE.md`. `result` is already in `.gitignore`; leave it uncommitted.

Do **not** run `just switch`.

- [ ] **Step 4: Commit**

```bash
git add home/common/claude-code/default.nix
git commit -m "docs(claude-code): drop the drifted skill count from the skillsDir comment" \
  -m "The comment claimed 8 global skills; home/common/agent-skills/skills/ holds 16. The
count is deleted rather than corrected - the directory is the one authoritative home for
its own size, and a restated count is a second home that has already drifted once (D5).
Comment-only: the skillsDir binding is unchanged and just build is green." \
  -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

Then append the `Claude-Session:` trailer for the session that actually ran this task, as the
repo's commit convention requires (see `8a4baae` for the shape); it is the executing
session's own `claude.ai/code` URL, which this plan cannot know in advance.

Leave GPG signing alone. If the commit fails to sign, report the signing error; do not pass
`-c commit.gpgsign=false` or `--no-gpg-sign`.
