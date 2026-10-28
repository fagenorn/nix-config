# One agent_tools build per generation, pinned by an installed check — issue 467

Design for https://github.com/fagenorn/nix-config/issues/467. Base: `00ec4e65`
(`origin/main`, the merge of #466). Approval source: autonomous (`--auto`), decision
ledger. A bare "Dn" cites this spec's ledger; "465 Dn" cites
`2026-10-27-issue-465-github-actions-health-deploy-adapter-design.md`.

## Triage

```
Input: {"signals": {"contract_change": {"value": "doubt", "evidence": "the agent_tools instantiation moves to one shared source and the registered hook wiring may change; no schema or CLI interface changes"}, "concurrency_or_persistence": {"value": "no", "evidence": "build-time Nix wiring and a static check; no locking or persisted state touched"}, "open_design_questions": {"value": "hit", "evidence": "one generation already shares the derivation; whether the observed split is a stale per-session hook snapshot, and whether to harden against it, is open"}, "criteria_shape": {"value": "hit", "evidence": "criteria 1 and 3 name elevenyellow/jarbird on the reporting host, which no deterministic check in this repo verifies"}}, "paths": ["lib/agent-tools.nix", "home/common/claude-code/default.nix", "home/common/agent-skills/default.nix", "home/common/claude-code/README.md", "tests/test_agent_tools_single_derivation.py"]}
Verdict: {"hits":["contract_change","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)
```

## Problem

After #466 added the `github-actions-health` deploy adapter, the reporter's host ran
two agent_tools versions at once. `resolve-project` (environment `nnffgdn…`) resolved
elevenyellow/jarbird with deploy available, while the lifecycle guard's row check,
`claude-guard-row-check` running `guard-policy derive` (environment `7hkig4…`), ran the
pre-466 resolver and refused with `branch_unresolved`. The guard then refused every
`gh pr create` and `gh pr merge` on that repository, including the dev-to-main release
PR. The issue asks that every agent_tools consumer come from the same build as
`resolve-project`, and that a check fail when two wrappers reference different
agent_tools store paths.

What this repository shows (2026-10-27, host anis-desktop):

- The agent-tools Nix builder makes one package, one interpreter environment, one
  launcher per command-table row and the `workflow-state` script launcher. Two home
  modules each apply it. The agent-skills module installs the launchers as
  `~/.agents/bin/<command>`. The claude-code module takes `guard-policy` (for the
  activation compile and the row check), `cache-proxy` (for the service) and
  `context-meter` (for the second hook) from its own copy. Both pass the same `pkgs`, so
  today the two copies are the same derivations: the current system closure holds one
  `python3.13-agent-tools-0.1.0` and one copy of each launcher. Nothing pins this. If
  one site changed its arguments, the generation would gain a second build and no check
  would notice. The only existing interpreter check covers `~/.agents/bin`, and misses
  the row check, the compile wrapper, the hook and the service.
- The current source derives a row for a JarBird-shaped project: integration branch
  `dev`, release profile `forge-main`, deploy bound to `github-actions-health` and
  `capabilities.deploy` supported. A probe over a hermetic fleet returned
  `outcome: derived` with row `main`/`dev`. There is no resolver bug to fix on `main`.
- So one generation of this configuration cannot produce the reported split. Two causes
  fit, and neither can be checked from here. The first is a process that started before
  the switch and kept its store paths. For example, a Claude Code session whose hook
  still names the previous `claude-bash-lifecycle-guard` store path runs the previous
  row check. The account profiles reach `~/.claude/settings.json` through a symlink, and
  Claude Code only documents that hook edits are "normally picked up automatically by
  the file watcher" (code.claude.com/docs/en/hooks, "Disable or remove hooks"). The
  second is that the two commands were taken from different generations.

## Solution

1. Apply the agent-tools builder once per home configuration, in one dedicated home
   module that publishes the result as the `agentTools` module argument. The
   agent-skills and claude-code modules take `agentTools` as an argument and stop
   applying the builder themselves (D2).
2. Replace the `~/.agents/bin`-only interpreter test with a check over the built
   system's closure. The closure must hold exactly one agent_tools package build, and
   every agent_tools launcher in it must exec the one environment that holds that build
   (D3, D4).
3. Add a source-level regression test that `guard-policy derive` derives a row for the
   JarBird shape (D5).
4. Document the single application and the pin where the package build is described,
   and add a pre-switch note after the guard's residual list (D6).

The guard, its policy files, its trust rules, the registered hook command and every
command's interface stay unchanged.

## Decisions

### What the fix guarantees (D1)

Guaranteed after this change:

- One home-manager generation holds one agent_tools build. Every consumer in it execs
  one interpreter environment: the `~/.agents/bin` launchers, `workflow-state`,
  `claude-guard-policy`, the guard's row check, the context-meter hook and the
  cache-proxy service.
- The installed tier fails on a built closure that holds a second agent_tools build, or
  a launcher that execs another environment (D3).
- The workflow suite fails if the source stops deriving a row for the JarBird shape
  (D5).

Not guaranteed. These items go in a paragraph after the residual list in the Claude Code
module README's guard-policy section (D6). That list names what stays user-writable,
and these items are not of that kind:

- A process started before a switch keeps its store paths until it ends or reloads them.
  For example, a Claude Code session whose loaded hook names the previous guard store
  path judges with the previous row check. The remedy is to start a new session after a
  switch that changes agent_tools. `/hooks` lists the hook command a session has
  loaded, and `just show-claude-settings` shows the path the current generation
  registers.
- A host that has not switched to a generation containing #466 runs pre-466 code in
  every consumer.
- Criteria 1 and 3 on the reporter's host are host evidence. No check in this
  repository can prove them (D5).

### One application of the builder (D2)

- A new home module in the common tree is the only place that applies the builder. It
  sets `_module.args.agentTools` to the result, using the module `pkgs`. The value keeps
  its current shape, `{ launchers; scriptLauncher; }`, and the interpreter environment
  stays private to the builder (YAGNI).
- The agent-skills module (the `~/.agents/bin` launchers and `workflow-state`) and the
  claude-code module (`guard-policy`, `cache-proxy`, `context-meter`) list `agentTools`
  among their module arguments and drop their `let`-bound applications. The comments
  that explain each use stay with the use. `agentTools` is never read to compute
  `imports`, so the module system can supply it lazily.
- Both sites already produced the same derivations, so the change is a refactor with no
  effect on the build. The evidence is that the agent_tools package and every launcher
  have the same store paths before and after. Any difference is investigated, never
  accepted.

### The pin check (D3, D4)

- It lives in the installed-layout launcher test module, the only test that touches
  built launchers (agent-helpers rule 5). It does not get a new module of its own.
- Its input is the built system result's closure. Both recipes that run that module hand
  it over, next to the installed home they already find in it. The retained recipe
  refuses a skipped test, so it must receive the closure too. The check skips only
  under the module's existing condition, an unset installed home. When the home is
  given and the closure is not, the check fails rather than skips (D4).
- The invariant has three parts, and each failure names the store paths involved:
  1. The closure holds exactly one agent_tools package build. Its store name comes from
     the package's own `name` and `version`, behind the interpreter prefix.
  2. Every launcher in the closure execs `<env>/bin/python3` for a single `<env>`. A
     launcher is a store file of the builder's `agent-tools-<command>` family, read with
     the module's existing launcher and script-launcher grammars. A family member that
     matches neither grammar fails the check, because it is a launcher shape the check
     cannot read.
  3. In that environment, `agent_tools` resolves into the one package build.
- It replaces the `~/.agents/bin`-only interpreter test. Those launchers and
  `workflow-state` are in the closure, so the new check covers that test's case and
  more.
- Before the check is relied on, the plan shows it failing on a closure that holds a
  second agent_tools build. That closure comes from a throwaway, uncommitted second
  application over another interpreter. This proves the check fails for the reason it
  exists (the bar, "Tests that can fail").

### Acceptance (D5)

| Criterion | Proven here | Left to the reporter's host |
|---|---|---|
| 1. The row check derives jarbird | A source-level derive test over a hermetic fleet: the JarBird shape derives a row with default `main` and integration `dev` | After the switch, run the current generation's row check on jarbird |
| 2. One agent_tools store path, pinned | The closure check (D3) | — |
| 3. `gh pr create … --base main --head dev` passes the guard | The derive test, plus the unchanged guard's existing coverage: PR creation against the default branch, and the arcwave-shaped test's feature PR and release merge arm for a derived row with integration branch `dev` | Run it from a session started after the switch |

The acceptance record states that the reporter's host verifies criteria 1 and 3, and
that this repository only proves their hermetic equivalent.

### Documentation (D6)

- The package README, where the build is described, says the builder is applied once
  per home configuration as `agentTools`. It also describes the closure check and the
  two recipes that run it.
- In the Claude Code module README, the guard-policy section says the row check and the
  compile wrapper take their launcher from the shared `agentTools`. A paragraph after
  the residual list carries D1's not-guaranteed items.

## Test seams

1. **Installed layout.** `just agent-installed-skill-tests` and
   `just agent-retained-tests` run `tests/test_agent_tools_launchers.py`, which holds
   the closure check (D3). Prior art: the interpreter test it replaces, and the recipes'
   `nix-store --query --requisites ./result` discovery.
2. **Source.** `just agent-workflow-tests` runs `tests/test_guard_policy.py` over
   `tests/guard_policy_world.py`, which holds the JarBird-shape derive (D5). Prior art:
   the suite's derive tests, and 465's contract shape in `tests/test_release_command.py`
   `DeployInspectTest`.
3. **Build.** `just build` on anis-desktop, and on a darwin host where one is at hand.
   The single application evaluates and builds, and the package and launcher store paths
   match the base's (D2).

## Out of scope

- Any change to the lifecycle guard: its base or compiled policy, its trust rules, the
  registered hook command or the row check's wiring (D6).
- Detecting, warning about or repairing a stale session, profile or host.
- artifact-budget (D7).
- Exporting the interpreter environment from the builder, or adding any configuration.
- Adding the installed tier to CI or to the contract's verification list (D4).
- The reporter's host state: switching, starting new sessions, rerunning
  `claude-guard-policy`.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Scope: this issue makes one generation internally consistent and pinned. It does not repair a host or a process started before a switch, and it records the reporter-host cause as unconfirmed | The two applications are the same derivations on anis-desktop; the source derives the JarBird shape (probe 2026-10-27); Claude Code hooks doc: edits "normally picked up automatically by the file watcher"; the bar, "Root causes" | Claiming the fix resolves the reported split: one generation of this code cannot produce it, so here the claim cannot be tested either way |
| D2 | The builder is applied once per home configuration, as the `agentTools` module argument set by one dedicated common home module. Every consumer takes it as an argument, and no other module applies the builder | The bar, "DRY" (copies that must change together get one home); scanPaths auto-imports a new common module | Threading it through `extraSpecialArgs`: helpers.nix has no module `pkgs`, so it would build against another package set. Keeping two applications: they drift silently when one site changes its arguments |
| D3 | The pin is an installed-tier check over the built system closure: one agent_tools package build, and every agent_tools launcher (`workflow-state` included) execs the one environment that holds it. It replaces the `~/.agents/bin`-only interpreter test, and is proven red on a throwaway second build | agent-helpers rule 5; the existing interpreter test is prior art; issue criterion 2 | Walking consumers from settings and `~/.agents/bin`: misses `claude-guard-policy`, the service unit and every future consumer. A Nix assertion: always true once D2 holds, and blind to a second application |
| D4 | Both recipes that run the launcher module (installed and retained) pass it the system closure. A given installed home without a closure fails rather than skips. The check is added neither to CI nor to the contract's verification list | The retained recipe refuses a skipped test; CI only evaluates and builds nothing (CLAUDE.md) | A CI or verification-list gate: needs a build that CI does not run, plus a contract change outside the issue |
| D5 | Criteria 1 and 3 get a hermetic equivalent: a source-level derive test on the JarBird shape. The reporter-host runs stay host evidence and no check here claims them | `GuardPolicyWorld` precedent; investigation open question 6; 465's JarBird contract shape | A guard-level test: that suite runs only by hand against built paths, and the guard is unchanged. Driving the built row check over the hermetic fleet: its store git and gh come first on PATH and bypass the fleet's shims |
| D6 | No hardening against a pre-switch session. The hook stays an argument-free store path and the row check a store `--derive-bin`. The residual and its remedy go in a paragraph after the guard's residual list | agent-helpers guard clause (the row check is reached by store path); the bar: known limitations go in docs; task brief: weaken no guard trust rule | Registering the hook through a stable profile link: puts a user-writable link in front of the store wrapper, so a mid-session change can swap the running guard. A staleness hint on refusal: a guard change that reads a user-writable file, for a cause nobody has confirmed |
| D7 | artifact-budget stays out. It imports no agent_tools and runs the PATH `python3` on its home script copy, so it is no agent_tools wrapper. review-package is a launcher and D3 covers it | Its installed script; agent-helpers rule 1 (a legacy script moves with its cluster) | Moving it into the package here: the #178-style migration, outside this issue |
| D8 | The pin reads the closure itself. Both recipes pass `AGENT_TOOLS_SYSTEM_RESULT` (the justfile's `system_result`, `<justfile dir>/result`), and the launcher module runs `nix-store --query --requisites` on it, names the package build from `python/pyproject.toml`, and splits D3's invariant into three tests. Part 2 also requires every `~/.agents/bin` entry that names the package to be one of the closure's launchers | The recipes' `nix-store --query --requisites ./result` discovery; the bar, "Tests that can fail"; planning trial 2026-10-27: green on the base closure, and red on a closure with a Python 3.12 build, naming both builds and both environments | Passing the requisites in a variable (1,238 paths here, near Linux's 128 KiB string limit) or a temp file (mktemp and trap in two recipes, for nothing). Dropping the `~/.agents/bin` part: an installed entry that left the launcher family would escape both checks |
| D9 | The JarBird derive is two `DeriveTest` cases: the adapter on `dev` only, `main`'s contract predating it (the reported release-pending state), and on both branches (after the release merges). Each is shown red by deriving under the pre-466 source (`5ae1b9dc`), which refuses `branch_unresolved` and `contract_unresolved` respectively | Issue body: the row check refused `branch_unresolved` because origin/dev's contract hit `binding_incomplete`; planning probe 2026-10-27 over `GuardPolicyWorld` | The single-commit shape alone: under the pre-466 source it refuses `contract_unresolved`, so it never reproduces the reported refusal |
| D10 | Criteria 1 and 3 are classified `human`: the reporter attests the host runs, and the acceptance map names the hermetic equivalents. The README paragraph after the guard's residual list carries D1's two system limits only, a process started before a switch and a host that has not switched (narrows D1, D6) | D5; sdd final review: an `evidence` row is `met` only inside the criterion's literal threshold, a `human` row is `human_pending`; the bar: known limitations go in docs | `evidence`: nobody here can measure the reporter's host, so both rows would end `unverified`, a finding that cannot be parked. Issue acceptance prose in the README goes stale once the issue closes |
