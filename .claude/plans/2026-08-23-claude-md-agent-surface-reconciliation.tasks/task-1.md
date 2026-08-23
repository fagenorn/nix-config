# Task 1: Correct the CLAUDE.md agent-surface bullets

**Files:**
- Modify: `CLAUDE.md` — line 61 only, the single bullet beginning
  ``  - Global guidance has one source at `home/common/agent-guidance/AGENTS.md` ``. It is
  replaced by two bullets; every other line of the file stays byte-identical.
- Test: none, and none is added. No test in this repo pins `CLAUDE.md` prose (per D7). The
  falsifiable gate for this task is the content-assertion script in Step 1.

**Interfaces:**
- Consumes: nothing from an earlier task. This is the first task.
- Produces: the corrected prose Task 2 must stay consistent with. Task 2 deletes the skill
  count from the `skillsDir` comment in `home/common/claude-code/default.nix`; this task
  must therefore state **no** skill count in `CLAUDE.md` (per D5). The one count this task
  does state — "two plugins" — is named alongside both plugin keys and is cross-checked
  against `enabledPlugins` by the gate.

**Invariants:**
- Every factual claim in the new prose is checkable against a named file in this repo or
  against the live `~/.codex/config.toml`. No claim rests on the design spec alone; the
  defect this issue exists to fix is exactly a claim that was carried forward unchecked.
- The correction never says which of `~/.codex/skills/` and `~/.agents/skills/` wins a name
  collision. "Duplicates" is supportable; "overrides", "shadows" and "takes precedence" are
  not (per D10).
- The `.superpowers/` clause reads as a present-tense fact about what that directory is,
  never as a changelog entry about what was removed and when (per D6).
- `CLAUDE.md` keeps exactly one bullet list under **Claude Code is declaratively managed**;
  the change adds one sibling bullet to it and adds no heading and no section (per D4).
- Nothing under `~/.codex/` is deleted, moved or created by this task (per D3). The one-time
  removal is recorded in the commit body and never gates anything.

- [ ] **Step 1: Install the content-assertion gate and watch it fail**

The gate lives outside the working tree so it is never committed and never collides with a
parallel run.

```bash
cd "$(git rev-parse --show-toplevel)"
mkdir -p "$(git rev-parse --git-dir)/gates"
cat > "$(git rev-parse --git-dir)/gates/task-1.sh" <<'GATE'
#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
M=home/common/claude-code/default.nix
fail() { echo "FAIL: $1" >&2; exit 1; }
need() { grep -qF -- "$1" CLAUDE.md || fail "missing from CLAUDE.md: $1"; }
gone() { if grep -qF -- "$1" CLAUDE.md; then fail "stale clause still present: $1"; fi; }

# A - the three stale assertions are gone (all three are present at the base commit)
gone 'Superpowers and `codex-plugin-cc` are built from pinned inputs plus repo-owned patches'
gone 'Claude installs both through local marketplaces'
gone 'native `superpowers:*` plugin from its Nix-declared personal marketplace'

# B - the overloaded bullet is now two bullets, each appearing exactly once (D4)
need 'Global guidance has one source at'
need 'Two skills stay out of the shared tree'
[ "$(grep -c 'Global guidance has one source at' CLAUDE.md)" -eq 1 ] || fail 'shared-surface bullet is not unique'
[ "$(grep -c 'Two skills stay out of the shared tree' CLAUDE.md)" -eq 1 ] || fail 'Claude-only bullet is not unique'

# C - every plugin and marketplace claim matches the live modules (D2)
n=$(sed -n '/enabledPlugins = {/,/};/p' "$M" | grep -c '= true;')
[ "$n" -eq 2 ] || fail "enabledPlugins holds $n entries; the prose says two plugins"
for p in 'skill-creator@claude-plugins-official' 'codex@nix-codex'; do
  grep -qF -- "\"$p\" = true;" "$M" || fail "$p is not an enabled plugin in $M"
  need "\`$p\`"
done
grep -qF 'source = "github";' "$M" || fail "no github marketplace source in $M"
grep -qF 'source = "directory";' "$M" || fail "no directory marketplace source in $M"
need 'a `github` marketplace'
need 'a `directory` marketplace'
grep -qF 'marketplaceName = "nix-codex";' lib/agent-plugins.nix || fail 'nix-codex is not the marketplace name in lib/agent-plugins.nix'
need '`nix-codex`'
n=$(ls -1 patches/agent-plugins | wc -l | tr -d ' ')
[ "$n" -eq 1 ] || fail "patches/agent-plugins holds $n files; the prose says one patch"
need 'the only patch in that directory'

# D - the Claude-only pair matches the module's two ~/.claude/skills links (D1)
for s in codex-collaboration orchestrate-issues; do
  grep -qF -- "home.file.\".claude/skills/$s\"" "$M" || fail "$s is not a Claude-only link in $M"
  need "\`$s\`"
done
need '/from-issue'

# E - Nix's writes under ~/.codex/ are exactly what the prose claims (D2, D3)
decls=$(git grep -l 'home.file.".codex/' -- '*.nix' | tr '\n' ' ')
[ "$decls" = "home/common/agent-guidance/default.nix " ] || fail "unexpected ~/.codex home.file declarations: $decls"
grep -qF 'model_reasoning_effort' home/common/codex/default.nix || fail 'the codex module no longer splices model_reasoning_effort'
need '`~/.codex/skills/` is Codex'
need 'duplicates the managed `~/.agents/skills/` link of the same name'
cfg="$HOME/.codex/config.toml"
if [ -f "$cfg" ]; then
  if grep -A3 -E '^\[marketplaces\.' "$cfg" | grep -q '/nix/store'; then
    fail 'a live Codex marketplace points into the nix store; the no-Nix-declared-marketplace claim is stale'
  fi
else
  echo "note: $cfg absent, skipping the live-marketplace cross-check" >&2
fi

# F - no precedence claim between the two skill roots (D10)
for word in overrides shadows 'takes precedence'; do
  if grep -qF -- "$word" CLAUDE.md; then fail "unhedged precedence word in CLAUDE.md: $word"; fi
done

# G - no skill count restated in the context doc (D5)
if grep -qE '[0-9]+ global skills' CLAUDE.md; then fail 'CLAUDE.md restates a skill count'; fi

# H - scoped Superpowers sweep (D11)
stray=$(git grep -In -i superpower -- ':!.claude/plans' ':!.claude/specs' ':!CLAUDE.md' ':!home/common/codex/default.nix' | grep -v '\.superpowers' || true)
if [ -n "$stray" ]; then fail "live Superpowers reference outside the state paths: $stray"; fi

echo "task-1 gate: PASS"
GATE
bash "$(git rev-parse --git-dir)/gates/task-1.sh"
```

Expected at the base commit: **FAIL**, on check A's first line —
`FAIL: stale clause still present: Superpowers and `codex-plugin-cc` are built from pinned
inputs plus repo-owned patches`. Checks A (all three) and B (`Two skills stay out of the
shared tree`) are all failing at this point; C through H already pass and are regression
guards. If check A does *not* fail here, `CLAUDE.md` is not at the state this task assumes —
stop and re-read line 61 before editing.

- [ ] **Step 2: Replace line 61 with the two corrected bullets**

Delete `CLAUDE.md` line 61 in full and put these two lines in its place, in this order, at
the same two-space indent, still inside the bullet list under **Claude Code is
declaratively managed**. Both are single unwrapped lines, matching the file's existing
style. The text below is verified against `home/common/agent-guidance/default.nix`,
`home/common/agent-skills/default.nix`, `home/common/claude-code/default.nix`,
`home/common/codex/default.nix`, `lib/agent-plugins.nix`, `patches/agent-plugins/`, and the
live `~/.codex/config.toml`; dictate it verbatim unless the gate shows a claim has since
gone stale, in which case fix the sentence and say so in the commit body.

First bullet — the shared surface:

```text
  - Global guidance has one source at `home/common/agent-guidance/AGENTS.md`, exposed as `~/.claude/CLAUDE.md` (via `programs.claude-code.memory`) and `~/.codex/AGENTS.md` (via `home/common/agent-guidance/default.nix`). Global skills likewise have one source at `home/common/agent-skills/skills/`, reaching Claude through `skillsDir` and Codex through the whole-directory links at `~/.agents/skills/` — whole-directory because Codex ignores a skill whose `SKILL.md` is itself a symlink. `~/.codex/skills/` is Codex's own runtime state: Nix's only writes under `~/.codex/` are `AGENTS.md` and the `model_reasoning_effort` key spliced into `config.toml`, so it neither populates nor prunes that directory — a skill hand-copied there duplicates the managed `~/.agents/skills/` link of the same name and has to be removed by hand. UI/UX Pro Max is generated once in `home/common/agent-skills/default.nix` and handed to both agents.
```

Second bullet — the Claude-only surface and the plugins:

```text
  - Two skills stay out of the shared tree and are linked only into `~/.claude/skills/` from `home/common/claude-code/skills/`: `codex-collaboration`, because a Codex session able to load the Claude→Codex bridge would recursively delegate to itself, and `orchestrate-issues`, because it fans issues out to background agents and correlates host task notifications — Claude-harness features Codex lacks, so a Codex session runs `/from-issue` per issue instead. Plugins: `codex-plugin-cc` is the one plugin built from a pinned input plus a repo-owned patch (`patches/agent-plugins/codex-plugin-cc.patch`, the only patch in that directory); `lib/agent-plugins.nix` patches it into a store path and names its marketplace `nix-codex`. Claude enables two plugins from marketplaces of two different source types — `skill-creator@claude-plugins-official` from a `github` marketplace and `codex@nix-codex` from a `directory` marketplace pointed at that store path. Codex has no Nix-declared marketplace: its marketplaces and plugins are runtime-managed inside `~/.codex/config.toml`, which Nix does not own. The `.superpowers/` paths throughout `home/common/agent-skills/` name the workflow-state directory the pipeline scripts create in whichever repo they run in; the name is historical and there is no Superpowers input, patch, marketplace or plugin in this repo.
```

Touch nothing else. In particular, leave line 62 (the `codex-plugin-cc.patch` editing
bullet) and line 63 (the `palmier-pro` MCP bullet) exactly as they are; the `codex-plugin-cc`
sentence in the new second bullet is the plugin's *install* surface and does not duplicate
line 62's *patch-editing* procedure.

- [ ] **Step 3: Verify**

Run: `bash "$(git rev-parse --git-dir)/gates/task-1.sh"`
Expected: `task-1 gate: PASS`, exit 0, no `FAIL:` line.

Then confirm the edit is exactly one line out and two lines in, and touches no other file:

Run: `git diff HEAD --numstat -- CLAUDE.md && git diff HEAD --name-only`
Expected: `2	1	CLAUDE.md`, and `CLAUDE.md` as the only name printed.

Then read the two new lines back once, in place, and confirm they render as two sibling
bullets in the existing list:

Run: `sed -n '58,64p' CLAUDE.md | cut -c1-80`
Expected: seven lines, of which the two new ones begin `  - Global guidance has one source`
and `  - Two skills stay out of the shared tree`, at the same indent as their neighbours.

What this gate proves: that the prose agrees with the live modules and with
`~/.codex/config.toml`, and that nothing outside line 61 moved. What it does not prove: that
the wording reads well, or that no *other* claim in `CLAUDE.md` has drifted. It runs no Nix
evaluation — this task touches no `.nix` file, so `just build` is Task 2's gate, not this
one's (per D7).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): reconcile the agent-surface bullets with the live modules" \
  -m "Splits the overloaded \"Global guidance\" bullet into a shared-surface bullet and a
Claude-only-surface-and-plugins bullet, and replaces the Superpowers clause - whose
plugin, marketplace, Codex personal marketplace and patch all went in 8a4baae - with the
install surface that exists: codex-plugin-cc as the one patched plugin,
skill-creator@claude-plugins-official from a github marketplace, codex@nix-codex from a
directory marketplace, and no Nix-declared Codex marketplace at all. Records
orchestrate-issues as deliberately Claude-only (D1) and ~/.codex/skills/ as Codex-owned
runtime state Nix neither populates nor prunes (D3)." \
  -m "Post-switch cleanup (one-time, manual): rm -rf ~/.codex/skills/codebase-design \\
  ~/.codex/skills/improve-codebase-architecture - unmanaged copies that duplicate
  the ~/.agents/skills links; leave ~/.codex/skills/.system alone." \
  -m "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

Then append the `Claude-Session:` trailer for the session that actually ran this task, as the
repo's commit convention requires (see `8a4baae` for the shape); it is the executing
session's own `claude.ai/code` URL, which this plan cannot know in advance.

The cleanup paragraph is required and is the whole of this plan's response to issue 105's
third acceptance criterion beyond the prose (per D3): it is offered to the owner, it is not
a gate, the ship phase must not wait on it, and the issue is closable without it. Do **not**
run that `rm` — this pipeline deletes nothing under `~/.codex/`.

Leave GPG signing alone. If the commit fails to sign, report the signing error; do not pass
`-c commit.gpgsign=false` or `--no-gpg-sign`.
