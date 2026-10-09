# Task 2: Move the guard, plugins and patch procedure to `home/common/claude-code/README.md`

**Files:**
- Create: `home/common/claude-code/README.md`
- Modify: `CLAUDE.md` (the **Claude Code is declaratively managed** bullets that hold base lines L64, L65, L66, L68 and L73 only)

**Interfaces:**
- Consumes: `CLAUDE.md` as at base `8e2bfb72` for those lines (`L<n>` = line `n` of `git show 8e2bfb72:CLAUDE.md`). Earlier tasks may have edited other paragraphs; touch nothing else. In L68 remove only the three "Plugins" sentences (F32–F34): the rest of L68 belongs to another task and stays as it is.
- Produces: `home/common/claude-code/README.md` with the sections named below; the dictated guard and patch bullets in `CLAUDE.md`.

**Invariants:**
- Every moved sentence is copied verbatim (D2). Allowed edits only: name the subject where the sentence leaned on `CLAUDE.md` context (for example "here" in F26 means the guard), split into the sections below, and rebase markdown links to `home/common/claude-code/` (D7): `.agents/artifacts/specs/…` becomes `../../../.agents/artifacts/specs/…`. Code-span paths stay repo-root-relative as written.
- Sentences kept in `CLAUDE.md` are not copied into the README (D7).
- No `.nix`, `.py` or test file changes. The `@.agents/instructions/bootstrap.md` line is untouched.
- A moved sentence that contradicts the code beside it is not corrected; list it in your report (file, line, sentence) for the owner to file.

## Fact-to-home rows (B5)

Destination for every row: `home/common/claude-code/README.md`, under the heading named. All rows are `moved`.

| Row | Base | Sentence opening | Heading | Anchor (in the README, absent from `CLAUDE.md`) |
|---|---|---|---|---|
| F16 | L64 | "Its `env` sets `BASH_MAX_TIMEOUT_MS` to `3600000`" | Settings | `` `BASH_DEFAULT_TIMEOUT_MS` is left unset `` |
| F17 | L65 | "Use `just show-claude-settings` to build and print the settings JSON (failing unless discovery" | Allow surface and lifecycle guard | `22-entry allow surface` |
| F18 | L65 | "That hook's Python is `home/common/claude-code/lifecycle_guard.py`" | Allow surface and lifecycle guard | `` imports nothing from `agent_tools` `` |
| F19 | L65 | "The hook splits the command into shell segments" | Allow surface and lifecycle guard | `comparing *token values*` |
| F20 | L65 | "A mention that is one quoted token" | Allow surface and lifecycle guard | `a heredoc body, or a comment is not a command` |
| F21 | L65 | "Everything the tokeniser cannot vouch for is refused" | Allow surface and lifecycle guard | `Everything the tokeniser cannot vouch for` |
| F22 | L65 | "Before any of that, and before its policy loads" (#278) | Detaching words | `` `nohup` is no longer a wrapper `` |
| F23 | L65 | "The verbs it does adjudicate are validated against the live repository" (through "…wait-for-checks.") | Adjudicated verbs | `` `dev` for `elevenyellow/nodocom` `` |
| F24 | L65 | "The merge's own `gh` lookups run with" | Adjudicated verbs | `scrubbed from their environment` |
| F25 | L65 | "There is no defer path" | Adjudicated verbs | `There is no defer path` |
| F26 | L65 | "The guarantee is only as wide as that segment tokeniser" | Adjudicated verbs | `it approximates bash rather than being bash` |
| F27 | L65 | "The hook also refuses an agent adding the `instruction-budget-raise` label (#294)" | The raise label | `` `--remove-label` and quoted mentions pass `` |
| F28 | L65 | "This catches mistakes and is not enforcement" | The raise label | `` `gh api`, GraphQL and `curl` are outside the guard `` |
| F29 | L65 | "Bare `Agent` remains inert under `defaultMode = \"auto\"`" | Allow surface and lifecycle guard | `` Bare `Agent` remains inert `` |
| F30 | L66 | "The [guard/core decision](…) preserves the required-check floor" | Guard/core decision | `missing permanent-head deletion check` |
| F31 | L66 | "Core grants cannot override the final guard" | Guard/core decision | `Core grants cannot override the final guard` |
| F32 | L68 | "Plugins: `codex-plugin-cc` is the one plugin built from a pinned input" | Plugins | `the only patch in that directory` |
| F33 | L68 | "Claude enables two plugins from marketplaces of two different source types" | Plugins | `` `skill-creator@claude-plugins-official` `` |
| F34 | L68 | "Codex has no Nix-declared marketplace" | Plugins | `Codex has no Nix-declared marketplace` |
| F35 | L73 | "To edit `patches/agent-plugins/codex-plugin-cc.patch`: work in a scratch clone" | Editing the codex-plugin-cc patch | `` bump `patchRevision` in `lib/agent-plugins.nix` `` |
| F36 | L73 | "Run the plugin's suite as `env -u CLAUDE_PLUGIN_DATA …`" | Editing the codex-plugin-cc patch | `4 upstream tests fail spuriously` |
| F37 | L73 | "The six test files that write under the shared state root" | Editing the codex-plugin-cc patch | `` `pinHermeticStateRoot` `` |
| F38 | L73 | "That, plus a `teardownBrokerSession` that kills by default" | Editing the codex-plugin-cc patch | `` `teardownBrokerSession` `` |
| F39 | L73 | "When two branches both edit this patch, reconcile it" | Editing the codex-plugin-cc patch | `applies a textually-merged zero-context patch at lenient offsets` |
| F40 | L73 | "To assert anything *about* the patched plugin source" | Editing the codex-plugin-cc patch | `` a patch-wide `grep -c` counts hunk lines `` |

Kept in `CLAUDE.md`, verbatim: the **Claude Code is declaratively managed** lead-in (L62), the L63 bullet, L64's first two sentences (through "(it resets on rebuild).**"), and the `palmier-pro` bullet (L74). The base splitter mistake to avoid: F23 is one sentence that runs from "The verbs it does adjudicate" through "…its CI gate stays in the shipping flow's wait-for-checks." despite the "e.g." inside it.

- [ ] **Step 1: Write the failing gate**

Save as `$SCRATCH/task2-gate.py` (`$SCRATCH` = the directory `launch-scope scratch …` prints; never commit it):

```python
import pathlib, sys

def norm(path):
    p = pathlib.Path(path)
    return " ".join(p.read_text(encoding="utf-8").split()) if p.exists() else ""

claude, home = norm("CLAUDE.md"), norm("home/common/claude-code/README.md")
anchors = [
    "`BASH_DEFAULT_TIMEOUT_MS` is left unset", "22-entry allow surface",
    "imports nothing from `agent_tools`", "comparing *token values*",
    "a heredoc body, or a comment is not a command", "Everything the tokeniser cannot vouch for",
    "`nohup` is no longer a wrapper", "`dev` for `elevenyellow/nodocom`",
    "scrubbed from their environment", "There is no defer path",
    "it approximates bash rather than being bash", "`--remove-label` and quoted mentions pass",
    "`gh api`, GraphQL and `curl` are outside the guard", "Bare `Agent` remains inert",
    "missing permanent-head deletion check", "Core grants cannot override the final guard",
    "the only patch in that directory", "`skill-creator@claude-plugins-official`",
    "Codex has no Nix-declared marketplace", "bump `patchRevision` in `lib/agent-plugins.nix`",
    "4 upstream tests fail spuriously", "`pinHermeticStateRoot`", "`teardownBrokerSession`",
    "applies a textually-merged zero-context patch at lenient offsets",
    "a patch-wide `grep -c` counts hunk lines",
]
kept = [
    "**Claude Code is declaratively managed** by `home/common/claude-code/default.nix`",
    "The binary is pinned to the `claude-code` flake input",
    "**materialized as a writable copy** via a home-manager activation script",
    "**Edit settings in `default.nix`; do not edit `~/.claude/settings.json` directly (it resets on rebuild).**",
    "New MCP servers should follow that same jq-merge pattern, never overwriting `~/.claude.json` wholesale.",
    "`git apply --unidiff-zero`", "adversarial table in `tests/test_claude_permission_guard.py`",
    "](home/common/claude-code/README.md)",
]
bad = [f"missing from README: {a}" for a in anchors if a not in home]
bad += [f"still in CLAUDE.md: {a}" for a in anchors if a in claude]
bad += [f"kept text lost: {k}" for k in kept if k not in claude]
if "](../../../.agents/artifacts/specs/2026-09-20-issue-116-permission-guard-core-design.md)" not in home:
    bad.append("guard/core link not rebased")
print("\n".join(bad) or "task2 gate: pass")
sys.exit(1 if bad else 0)
```

- [ ] **Step 2: Run the gate and watch it fail**

Run: `python3 -I "$SCRATCH/task2-gate.py"`
Expected: exit 1, every anchor reported `missing from README`.

- [ ] **Step 3: Move the text**

1. Create `home/common/claude-code/README.md`: a `# Claude Code module` title, then `## Settings` (F16), `## Allow surface and lifecycle guard` (F17–F21, F29), `## Detaching words` (F22), `## Adjudicated verbs` (F23–F26), `## The raise label` (F27, F28), `## Guard/core decision` (F30, F31, link rebased), `## Plugins` (F32–F34), `## Editing the codex-plugin-cc patch` (F35–F40). Copy each sentence from `git show 8e2bfb72:CLAUDE.md`, not from memory. F17 starts "Use `just show-claude-settings`…"; keep it whole.
2. In `CLAUDE.md`:
   - L64 bullet: delete F16, keeping the first two sentences.
   - Replace the L65 and L66 bullets with this one dictated bullet (D1, D7):
     "- `just show-claude-settings` builds and prints the settings JSON. Four lifecycle verbs (`git push`, `gh pr create`, `git branch -d`, `gh pr merge`) and adding the `instruction-budget-raise` label are adjudicated by a fail-closed `PreToolUse` hook, `home/common/claude-code/lifecycle_guard.py`; it also refuses `nohup`, `setsid` and `disown` in every repository, so run long or detached work with the Bash tool's `run_in_background: true` or `launch-scope exec`. Any change to the guard must keep the adversarial table in `tests/test_claude_permission_guard.py` green. The guard's full semantics, the guard/core decision and the plugin wiring are in [`home/common/claude-code/README.md`](home/common/claude-code/README.md); new detail of that kind goes there, not here."
   - L68 bullet: delete the three sentences F32–F34 only.
   - Replace the L73 bullet with this dictated bullet:
     "- `patches/agent-plugins/codex-plugin-cc.patch` is zero-context: apply it with `git apply --unidiff-zero`, reconcile two branches' edits by merging the patched source trees and regenerating (never by merging the patch text), and read the scratch clone or the built store path, never the patch text, to assert anything about the patched source. The full editing and test procedure is in `home/common/claude-code/README.md`; new detail of that kind goes there, not here."

- [ ] **Step 4: Verify**

Run: `python3 -I "$SCRATCH/task2-gate.py"` — Expected: `task2 gate: pass`, exit 0.
Run: `grep -c '^@.agents/instructions/bootstrap.md$' CLAUDE.md` — Expected: `1`.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/README.md CLAUDE.md
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "docs(claude-md): move the guard and plugin detail to the claude-code README (#330)"
```

The identity values and the commit-message trailers come from your dispatch brief; commits stay signed.
