# Task 4: Move the local-model detail to `home/linux/claude-local/README.md`

**Files:**
- Create: `home/linux/claude-local/README.md`
- Modify: `CLAUDE.md` (the **Local-model Claude Code (Linux only)** section: base lines L76–L84 only)

**Interfaces:**
- Consumes: `CLAUDE.md` as at base `8e2bfb72` for L76–L84 (`L<n>` = line `n` of `git show 8e2bfb72:CLAUDE.md`); the comments in `home/linux/claude-local/default.nix` and the docstring of `home/linux/claude-local/anthropic-shim.py`, which already hold several facts (rows marked `present`). Touch no other paragraph and no code file.
- Produces: `home/linux/claude-local/README.md`; a short local-model paragraph in `CLAUDE.md`.

**Invariants:**
- Moved sentences are copied verbatim (D2); allowed edits only: name the subject, split into the sections below. Rows marked `present` are deleted from `CLAUDE.md` and not copied (D2).
- If a `present` row's anchor is not in its cited file at your starting commit, move that sentence to the README instead and change the row's mark to `moved` in this task member in the same commit (D8).
- `default.nix` and `anthropic-shim.py` are not edited. The `@.agents/instructions/bootstrap.md` line is untouched.
- A sentence that contradicts the code beside it is not corrected; list it in your report (file, line, sentence) for the owner to file.

## Fact-to-home rows (B8)

| Row | Base | Sentence opening | Home | Mark | Anchor (in the home, absent from `CLAUDE.md`) |
|---|---|---|---|---|---|
| F78 | L76 | "The wrapper pre-flights `/health`" | README § The wrapper | moved | `a dead server is a one-line error` |
| F79 | L76 | "Three env choices are load-bearing, not taste" | `home/linux/claude-local/default.nix` comments, lines 14–22, 61–63, 74–75 | present | `Every alias has to be pinned`, `outranks ANTHROPIC_AUTH_TOKEN`, `prefill -- not decode -- is the` |
| F80 | L76 | "A smaller declared window makes auto-compaction fire" | `default.nix` lines 20–21 | present | `makes auto-compaction fire` |
| F81 | L78 | "It is a wrapper rather than an entry in the claude-code module's `settings` attrset" | `default.nix` lines 78–84 | present | `There is no settings.json equivalent` |
| F82 | L80 | "**Two request shapes must both work, and the second is the one that bites.** Beyond the agent loop" | README § Two request shapes | moved | `before each Bash command, as a separate request with its own shape` |
| F83 | L80 | "A backend that serves the agent loop perfectly can still fail the classifier" | README § Two request shapes | moved | `is temporarily unavailable` |
| F84 | L80 | "Diagnose this class of problem with a logging proxy" | README § Two request shapes | moved | `with a logging proxy between the CLI and the server` |
| F85 | L80 | "Two concrete mismatches have appeared" | README § Two request shapes | moved | `both are *deliberate* NInfer semantics` |
| F86 | L81 | "`cache_control` on a non-final content block" | README § Two request shapes | moved | ``upstream `9e163eee` `` |
| F87 | L82 | "`thinking.display:\"omitted\"` is rejected outright" | `home/linux/claude-local/anthropic-shim.py` docstring, lines 3–5 | present | `encrypted hidden-reasoning restore semantics` |
| F88 | L82 | "Claude Code emits exactly that object at **every** non-zero thinking budget" | `anthropic-shim.py` docstring, lines 6–8 | present | `MAX_THINKING_TOKENS=0` |
| F89 | L82 | "Instead the wrapper starts `anthropic-shim.py`, a per-session localhost proxy" | `default.nix` lines 43–46 and 56–57; `anthropic-shim.py` line 10 | present | `The shim rewrites that one field`, `` `summarized` is the nearest value NInfer accepts `` |
| F90 | L82 | "It streams responses unbuffered" (including the `coproc SHIM { exec … }` clause) | `anthropic-shim.py` line 14; `default.nix` lines 52–53 | present | `Responses stream through unbuffered`, `` `exec` matters `` |
| F91 | L84 | "**Fan-out is the real mismatch, not prompt size.** `--max-concurrency 2`" | README § Fan-out | moved | `` `--max-concurrency 2` `` |
| F92 | L84 | "Admission is graceful" | README § Fan-out | moved | `` `--pending-timeout-ms` defaults to 30s `` |
| F93 | L84 | "Single-session work is what this is for." | README § Fan-out | moved | `Single-session work is what this is for` |
| F94 | L84 | "The `[claude-code:unrecognized_model]` line on stderr is cosmetic" | README § Fan-out | moved | `` `[claude-code:unrecognized_model]` `` |

Kept in `CLAUDE.md`: L76's first sentence verbatim ("**Local-model Claude Code (Linux only).** `home/linux/claude-local/default.nix` puts a `claude-local` wrapper on PATH: …thinking."), and L78's `--bare` sentence with its subject named (D2): "Do **not** reach for `--bare` to shrink the ~24k system prompt this repo generates — it skips hooks, which disables the `PreToolUse` lifecycle guard; the prompt is cache-read anyway, so it is not the cost it looks like."

- [ ] **Step 1: Write the failing gate**

Save as `$SCRATCH/task4-gate.py` (`$SCRATCH` = the directory `launch-scope scratch …` prints; never commit it):

```python
import pathlib, sys

def norm(path):
    p = pathlib.Path(path)
    return " ".join(p.read_text(encoding="utf-8").split()) if p.exists() else ""

claude = norm("CLAUDE.md")
homes = {
    "readme": norm("home/linux/claude-local/README.md"),
    "nix": norm("home/linux/claude-local/default.nix"),
    "shim": norm("home/linux/claude-local/anthropic-shim.py"),
}
rows = [
    ("readme", "a dead server is a one-line error"),
    ("nix", "Every alias has to be pinned"), ("nix", "outranks ANTHROPIC_AUTH_TOKEN"),
    ("nix", "prefill -- not decode -- is the"), ("nix", "makes auto-compaction fire"),
    ("nix", "There is no settings.json equivalent"),
    ("readme", "before each Bash command, as a separate request with its own shape"),
    ("readme", "is temporarily unavailable"),
    ("readme", "with a logging proxy between the CLI and the server"),
    ("readme", "both are *deliberate* NInfer semantics"), ("readme", "upstream `9e163eee`"),
    ("shim", "encrypted hidden-reasoning restore semantics"), ("shim", "MAX_THINKING_TOKENS=0"),
    ("nix", "The shim rewrites that one field"), ("shim", "`summarized` is the nearest value NInfer accepts"),
    ("shim", "Responses stream through unbuffered"), ("nix", "`exec` matters"),
    ("readme", "`--max-concurrency 2`"), ("readme", "`--pending-timeout-ms` defaults to 30s"),
    ("readme", "Single-session work is what this is for"),
    ("readme", "`[claude-code:unrecognized_model]`"),
]
kept = [
    "**Local-model Claude Code (Linux only).** `home/linux/claude-local/default.nix` puts a `claude-local` wrapper on PATH",
    "Do **not** reach for `--bare` to shrink the ~24k system prompt this repo generates",
    "home/linux/claude-local/README.md",
]
bad = [f"missing from {h}: {a}" for h, a in rows if a not in homes[h]]
bad += [f"still in CLAUDE.md: {a}" for _, a in rows if a in claude]
bad += [f"kept text lost: {k}" for k in kept if k not in claude]
for stale in ("load-bearing, not taste", "Two request shapes must both work", "Fan-out is the real mismatch"):
    if stale in claude:
        bad.append(f"still in CLAUDE.md: {stale}")
print("\n".join(bad) or "task4 gate: pass")
sys.exit(1 if bad else 0)
```

- [ ] **Step 2: Run the gate and watch it fail**

Run: `python3 -I "$SCRATCH/task4-gate.py"`
Expected: exit 1, the `readme` anchors reported missing and the `stale` phrases reported still in `CLAUDE.md`. No `missing from nix` or `missing from shim` line: if one appears, apply the D8 fallback for that row before Step 3.

- [ ] **Step 3: Move the text**

1. Create `home/linux/claude-local/README.md`: a `# claude-local` title, then `## The wrapper` (F78), `## Two request shapes` (F82–F86, keeping the two-item list of F86 and the omitted-thinking item's pointer to `anthropic-shim.py` as one sentence: "The second, `thinking.display:\"omitted\"`, is handled by `anthropic-shim.py`; its docstring explains why."), `## Fan-out` (F91–F94). Copy each moved sentence from `git show 8e2bfb72:CLAUDE.md`, not from memory. The added list-item sentence is the only new README prose; it names where F87–F90 live.
2. In `CLAUDE.md`, replace base lines L76–L84 with: the kept L76 sentence, the kept `--bare` sentence, and this dictated pointer (D1, D7): "The env choices, the classifier's request shape, the shim and the fan-out limits are in `home/linux/claude-local/README.md` and the comments of its `default.nix` and `anthropic-shim.py`; new detail of that kind goes there, not here." Keep it as one paragraph under the bold lead-in.

- [ ] **Step 4: Verify**

Run: `python3 -I "$SCRATCH/task4-gate.py"` — Expected: `task4 gate: pass`, exit 0.
Run: `grep -c '^@.agents/instructions/bootstrap.md$' CLAUDE.md` — Expected: `1`.

- [ ] **Step 5: Commit**

```bash
git add home/linux/claude-local/README.md CLAUDE.md
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "docs(claude-md): move the local-model detail to the claude-local README (#330)"
```

Add this task member to the commit only if the D8 fallback changed a row. The identity values and the commit-message trailers come from your dispatch brief; commits stay signed.
