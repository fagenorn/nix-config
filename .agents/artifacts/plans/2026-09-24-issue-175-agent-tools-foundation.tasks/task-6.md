# Task 6: Project standards shard and the architecture note

Decisions: D9, D10, D12; parent D6. Spec sections "Project standards shard
(D9)" and "Living documents (D10)". Work from the worktree root.

**Files:**
- Create: `docs/standards/README.md`
- Create: `docs/standards/agent-helpers.md`
- Modify: `.agents/project.json` (one array, `bindings.paths.standards`)
- Modify: `home/common/agent-skills/tests/test_resolve_project.py` (one added
  line, D12)
- Modify: `CLAUDE.md` (one paragraph at the end of `## Architecture`)

**Interfaces:**
- Consumes: the layout Tasks 1–5 built. The package is `python/agent_tools`,
  the command table lives in `lib/agent-tools.nix`, the launchers run `-I -m`
  after the `unset` line, the recipes set `PYTHONPATH`, and the installed test is
  `tests/test_agent_tools_launchers.py`.
- Produces: `resolve-project resolve` lists `<root>/docs/standards` after
  `<root>/home/common/agent-skills/standards` in `bindings.paths.standards`. The
  shard loads for any touched path under its `governs` globs.

**Invariants:**
- `docs/standards/README.md` has at most 40 lines. It opens with one paragraph
  (Layer 2 of the three-layer contract, deltas only, a shard loads when a
  touched path matches its globs), followed by a `| Shard | governs | Gist |`
  table with exactly one row.
- That row governs exactly `python/**`, `scripts/**`,
  `home/common/agent-skills/scripts/**` and
  `home/common/agent-skills/skills/*/scripts/**`. There is no guard glob, which
  arrives with #176 (D9).
- `agent-helpers.md` holds the five parent-D6 rules, refined as D9 says. Each
  rule is written rule-first, in at most two sentences, followed by one link to
  the parent spec. Nothing restates Layer 0 or Layer 1.
- `docs/standards` is a real directory, not a symlink. The policy entry is
  appended after the existing one, and the rest of `project.json` is
  byte-identical.
- Policy is checked only through `resolve-project resolve`.

- [ ] **Step 1: Watch the registration check fail**

Run: `~/.agents/bin/resolve-project resolve --repo-root "$PWD" | python3 -c 'import json,sys; print("\n".join(json.load(sys.stdin)["bindings"]["paths"]["standards"]))'`
Expected at the starting commit: one line, ending in
`/home/common/agent-skills/standards`, with no `docs/standards` line.

- [ ] **Step 2: Register the path and watch the resolver suite fail (D12)**

In `.agents/project.json`, change
`"standards": ["home/common/agent-skills/standards"],` to
`"standards": ["home/common/agent-skills/standards", "docs/standards"],`.

Run: `python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py 2>&1 | grep -E "^FAIL|'blocked' != 'available'|^FAILED"`
Expected:
`FAIL: test_available_when_every_prerequisite_is_present … (capability='knowledge.standards')`,
then `'blocked' != 'available'` and `FAILED (failures=1)`. The suite's fixture
root copies the live contract, but it creates only the old directory.

- [ ] **Step 3: Add the fixture directory**

In `make_project_root` in `home/common/agent-skills/tests/test_resolve_project.py`,
insert one line directly after
`    (root / "home" / "common" / "agent-skills" / "standards").mkdir(parents=True)`:

```python
    (root / "docs" / "standards").mkdir(parents=True)
```

Change nothing else in that file.

- [ ] **Step 4: Write the shard**

`docs/standards/README.md`:

```markdown
# Project standards: nix-config

Layer 2 of the three-layer standards contract (`~/.agents/standards/README.md`).
It holds deltas only, on top of the bar (Layer 0) and the stack shards
(Layer 1). A shard loads when a touched path matches one of its `governs` globs.

| Shard | governs | Gist |
|---|---|---|
| [agent-helpers.md](agent-helpers.md) | `python/**`, `scripts/**`, `home/common/agent-skills/scripts/**`, `home/common/agent-skills/skills/*/scripts/**` | Agent-workflow Python lives in the `agent_tools` package, runs only through `-m`, and shares one canonical-JSON home. |
```

`docs/standards/agent-helpers.md`:

```markdown
# Agent helpers

Deltas for agent-workflow Python in this repository. They bind new code now;
a legacy flat script meets them when its cluster moves into the package.

1. **Helpers live in the package.** Agent-workflow Python is a module of `agent_tools` under `python/`, and a command is that module plus one row in the command table in `lib/agent-tools.nix`, never a new top-level script. Each legacy script moves in with its cluster's PR. ([design](../../.claude/specs/2026-09-24-agent-tools-package-design.md))

2. **A command module is a thin shell.** It parses argv with a parser whose `prog` is the command name, reads input, calls importable functions, writes output and maps errors to exit codes; policy lives in functions that other modules and tests import. ([design](../../.claude/specs/2026-09-24-agent-tools-package-design.md))

3. **No import machinery and no path-derived calls.** Nothing edits `sys.path`, loads a module through `importlib` or by file path, checks a module version handshake, or locates another module or command from `__file__`. A packaged sibling runs as `sys.executable`, with `-I` only when the caller itself runs isolated, then `-m agent_tools.<module>`, through one shared package helper, while an executable outside the package runs by its command name on `PATH`. ([design](../../.claude/specs/2026-09-24-agent-tools-package-design.md))

4. **One canonical-JSON home.** A digest uses `agent_tools.canonical.telemetry_digest` (sorted, compact, ASCII-escaped JSON with a `sha256:` prefix) or the delivery model's own format, never a local copy. A strict JSON load composes the `reject_duplicate_keys` and `reject_nonfinite_literal` hooks from `agent_tools.canonical` that its command needs, never a local hook. ([design](../../.claude/specs/2026-09-24-agent-tools-package-design.md))

5. **Tests drive commands from source.** A test runs a command as `python -m agent_tools.<module>` under the recipe's `PYTHONPATH` and imports modules normally. Only the installed-layout test, `tests/test_agent_tools_launchers.py`, touches the built launchers. ([design](../../.claude/specs/2026-09-24-agent-tools-package-design.md))
```

- [ ] **Step 5: Add the architecture paragraph (D10)**

In `CLAUDE.md`, append this paragraph at the end of `## Architecture`, after the
`myvars` paragraph and before `## Key conventions & gotchas`, with one blank
line on each side:

```markdown
**Agent helper package.** Agent-workflow Python is moving into one standard-library package, `agent_tools`, under `python/` (with its `pyproject.toml`). `lib/agent-tools.nix` builds it into one Python environment, import-checks every module so that a broken import fails `just build`, and holds the command table. Each row becomes a `~/.agents/bin/<command>` launcher, which unsets the `NIX_PYTHON*` variables and runs `python3 -I -m agent_tools.<module>` from that environment, so nothing on `PYTHONPATH` or in the working directory can shadow the store copy; `just agent-installed-skill-tests` proves it. The `just` recipes that run package code set `PYTHONPATH` to `python/`, and tests run commands as `python -m agent_tools.<module>`. The other helpers are still flat scripts under `scripts/` and `home/common/agent-skills/scripts/` and move in cluster by cluster, while `docs/standards/agent-helpers.md` sends all new helper code to the package.
```

- [ ] **Step 6: Verify**

Run: `~/.agents/bin/resolve-project resolve --repo-root "$PWD" | python3 -c 'import json,sys; d=json.load(sys.stdin); print("\n".join(d["bindings"]["paths"]["standards"])); print(d["capabilities"]["knowledge.standards"]["state"])'`
Expected: two paths, the second being `<worktree>/docs/standards`, and then
`available`. This is AC5, shown once.

Run: `test "$(wc -l < docs/standards/README.md)" -le 40 && test ! -L docs/standards && echo shard-ok`
Expected: `shard-ok`.

Run: `python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py home/common/agent-skills/tests/test_conformance.py home/common/agent-skills/tests/test_conformance_checks.py home/common/agent-skills/tests/test_conformance_registry.py 2>&1 | tail -3`
Expected: `OK`. That covers the resolver's capability test and the conformance
roots, which create every declared directory.

Run: `git diff -- .agents/project.json | grep -c '^[-+] '`
Expected: `2`, one removed line and one added line.

Run: `just agent-workflow-tests 2>&1 | tail -3`
Expected: `OK (skipped=1)`, with the same count as after Task 5.

- [ ] **Step 7: Commit**

```bash
git add docs/standards/README.md docs/standards/agent-helpers.md .agents/project.json \
  home/common/agent-skills/tests/test_resolve_project.py CLAUDE.md
git commit -m "docs(standards): add the agent-helpers shard and register project standards"
```

The message ends with the trailer lines named in the plan's Global Constraints.
