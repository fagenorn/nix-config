# Task 2: `~/.agents/bin` Guaranteed on the Reviewer Subprocess PATH

**Files:**
- Modify: `home/common/claude-code/default.nix` (the `codexCompanionBin` wrapper, ~L15–18)

No patch edit and no `patchRevision` bump: this defect's fix is entirely repo-owned (per D5). This task touches nothing in `patches/` or `lib/`.

**Interfaces:**
- Consumes: `codexCompanionBin = pkgs.writeShellScriptBin "codex-companion" ''…''`, whose body today is a single `exec ${pkgs.nodejs}/bin/node ${agentPlugins.codex}/plugins/codex/scripts/codex-companion.mjs "$@"`; it is added to `home.packages` (~L928–930). `home/common/agent-skills/default.nix` (~L144) separately sets `home.sessionPath = [ "$HOME/.agents/bin" ]` for login shells.
- Produces: the same wrapper with one added line, `export PATH="$HOME/.agents/bin:$PATH"`, ahead of the `exec`. Every descendant of `codex-companion` — the detached worker, `codex app-server`, and the reviewer's exec tool, which inherits PATH under Codex's default core environment policy — resolves `artifact-budget` and the other six helpers by bare name regardless of how the launching shell was constructed.

**Invariants:**
- The prepend is unconditional. On a machine whose login shell already exported the directory the entry appears twice, which is inert; a guard would trade a visible duplicate for a conditional. Reviewers of the diff should read the duplicate as deliberate (per D5).
- Prepending, not appending: it matches `home.sessionPath`'s own ordering, and no name in `~/.agents/bin` shadows a system binary (Step 1 proves this rather than asserting it).
- The wrapper stays the sole `codex-companion` on PATH — the built plugin tree ships no competing `bin/` directory — so every invocation passes through it and no call path can bypass the export.
- Nothing about the isolation model changes: the reviewer still runs fresh `CODEX_HOME`, approval `never`, sandbox `read-only`. This adds a PATH entry, not a permission.
- Delivered as a **guarantee, not a repair**: the spec's live probes show the reviewer already resolves `artifact-budget` and runs it to exit 0 today, by login-shell inheritance. This converts an inheritance into a construction (per D5); the issue's stated exit-127 mechanism does not reproduce and this task must not claim to have fixed one.

Cites: D5.

- [ ] **Step 1: Prove the prepend cannot shadow anything, and that the line is absent today**

```bash
for helper in "$HOME"/.agents/bin/*; do
  name=$(basename "$helper")
  if PATH=/usr/bin:/bin:/usr/sbin:/sbin command -v "$name" >/dev/null 2>&1; then
    echo "helper $name shadows a system binary; prepending is unsafe" >&2; exit 1
  fi
done
echo "no helper shadows a system binary"
if grep -q 'agents/bin' home/common/claude-code/default.nix; then
  echo "the wrapper already exports the helper directory" >&2; exit 1
fi
echo "wrapper does not export the helper directory yet"
```

Expected: `no helper shadows a system binary` then `wrapper does not export the helper directory yet`. The seven names (`agent-evidence`, `agent-model-matrix`, `artifact-budget`, `context-map-lint`, `diff-scope`, `resolve-bindings`, `workflow-state`) exist nowhere in the system directories, which is what makes an unconditional prepend safe. The second check is this task's base-state observation: `.agents/bin` does not occur in that file at the starting commit.

- [ ] **Step 2: Add the export to the wrapper**

In `home/common/claude-code/default.nix`, the `codexCompanionBin` body becomes exactly two lines — the export first, then the unchanged `exec`:

```nix
  # Bare `codex-companion` on PATH. The codex-collaboration bridge (and its
  # `command -v` pre-flight) invokes it by name; without this every spawned
  # session gets exit 127 (observed: nodo evidence run, 2026-08-09). The
  # runtime is self-contained (node built-ins + relative lib imports only).
  #
  # The agent helpers ride down the same wrapper. `~/.agents/bin` reaches a
  # reviewer today only because home.sessionPath put it in the launching login
  # shell and the whole chain inherited it; a scrubbed or non-login parent
  # silently loses it and the reviewer's bare-name `artifact-budget` call gets
  # exit 127. Exporting here makes the guarantee a construction rather than an
  # inheritance. Unconditional on purpose: on a machine whose shell already
  # exported it the entry appears twice, which is inert.
  codexCompanionBin = pkgs.writeShellScriptBin "codex-companion" ''
    export PATH="$HOME/.agents/bin:$PATH"
    exec ${pkgs.nodejs}/bin/node ${agentPlugins.codex}/plugins/codex/scripts/codex-companion.mjs "$@"
  '';
```

Note for the implementer: in a Nix indented string (`''…''`) only `${…}` interpolates. A bare `$HOME` or `$PATH` passes through to the generated shell script literally, exactly as the existing `"$@"` on the `exec` line already does — so both are written plainly, with no escaping. Never write `${HOME}` or `${PATH}` here: that is Nix interpolation and would either fail evaluation or bake this machine's literal path into the store. If a `${` ever needs to reach the shell verbatim, the escape is `''${`. Step 4 reads the built script and settles which form actually landed.

- [ ] **Step 3: Build**

Run: `just build`
Expected: the nix-darwin build succeeds and refreshes `./result`. An eval error here means the `$` escaping in Step 2 is wrong — fix the escaping, not the intent.

- [ ] **Step 4: Verify against the built wrapper**

```bash
set -- $(nix-store --query --requisites ./result | grep -- '-codex-companion$')
if [ "$#" -ne 1 ]; then echo "expected exactly one codex-companion store path; found $#" >&2; exit 1; fi
WRAPPER="$1/bin/codex-companion"
EXPORT_LINE=$(grep -n 'export PATH="$HOME/.agents/bin:$PATH"' "$WRAPPER" | cut -d: -f1)
EXEC_LINE=$(grep -n 'codex-companion.mjs "$@"' "$WRAPPER" | cut -d: -f1)
[ "$(printf '%s\n' "$EXPORT_LINE" | grep -c .)" = 1 ] || {
  echo "expected exactly one helper-directory export in the built wrapper" >&2; exit 1; }
[ "$(printf '%s\n' "$EXEC_LINE" | grep -c .)" = 1 ] || {
  echo "expected exactly one exec of the companion runtime" >&2; exit 1; }
[ "$EXPORT_LINE" -lt "$EXEC_LINE" ] || {
  echo "the export does not precede the exec, so no child ever inherits it" >&2; exit 1; }
env -i HOME="$HOME" PATH=/usr/bin:/bin sh -c '"$0" nonexistent-subcommand >/dev/null 2>&1; echo "wrapper exit (diagnostic only): $?"' "$WRAPPER"
```

Expected: the discovery finds exactly one store path; both `grep -q` checks pass; the last line prints a `wrapper exit:` status — any status is acceptable, the point is that the wrapper runs to completion from a scrubbed environment holding only `HOME`, which is the launch shape the export exists for. If the first grep fails, the `''$` escaping in Step 2 resolved at eval time and the script hardcodes a path or an empty string; re-read the built file and fix the escaping.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/default.nix
git commit -m "$(cat <<'MSG'
fix(claude-code): guarantee the agent helper directory on the companion's PATH

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Verification (falsifiable):** Step 1's second check establishes the base state — `grep -q 'agents/bin' home/common/claude-code/default.nix` finds nothing at the starting commit — and Step 4's first `grep -q` therefore cannot pass until this task lands, because the wrapper built from the base commit is a one-line `exec`. Scope any diff inspection to this task's file (`git diff --stat "$BASE_SHA"..HEAD -- home/common/claude-code/default.nix`); never grade the whole commit range.

**Out of scope for this task:** a live reviewer probe confirming bare-name resolution inside the sandbox needs an activated build (`just switch`), which this plan never runs. Record it as post-activation evidence for the issue, not as a gate here.
