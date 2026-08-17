# Design: a pull request cannot merge until Nix still evaluates

Issue: https://github.com/fagenorn/nix-config/issues/29

Grounding (cited, not re-litigated): `CLAUDE.md` — the repo has no test/lint suite and CI "only runs
DeterminateSystems flake-checker on push/daily"; `home/common/agent-skills/standards/the-bar.md` —
*Tests that can fail*, *Fail loud*, *DRY*, *YAGNI*, *Verify before claiming done*.
`.out-of-scope/ungated-agent-merges.md` (written as local commit `c560008`; it has since reached
`origin/main` as `d5b0d84` — see D23) records the rejection this issue is the positive half of. This repo has no context map and no ADR tree; the
`docs/areas/*/adr/` trees under `home/common/agent-skills/evals/fixture-repo/` are eval fixtures, not
this project's docs.

## Problem

Nothing stands between an open pull request and `main`.

`.github/workflows/flake-checker.yaml` is the repo's only workflow and it triggers on `push` to `main`,
a daily cron, and `workflow_dispatch`. None of those fire for a pull request, so a PR head commit
carries zero check runs — `gh pr checks` prints "no checks reported" — and `gh pr merge` succeeds
unconditionally. The only thing that has ever stopped a broken `.nix` change from reaching `main` is
the author remembering to run `just build` on their own machine first.

That was tolerable while every merge was a human pressing the button. It is not tolerable now: the
2026-08-17 orchestration retro decided that unattended agent merges become safe through a required
status check rather than through a permission prompt, and the companion permission surface
(https://github.com/fagenorn/nix-config/issues/30) is explicitly blocked on this landing. An agent
holding the owner's token can merge anything today.

There is a second, quieter problem. The obvious gate — putting `flake-checker-action` on
`pull_request` — does not actually gate anything. That action reads `flake.lock` and reports on the
nixpkgs branch, its age, and disallowed refs. It never evaluates `flake.nix`. And its `fail-mode`
input defaults to `false`, so it annotates and exits zero even when it finds problems. A PR that
deletes a module, mistypes an option, or breaks `lib/helpers.nix` sails through it green. Issue 29's
third acceptance criterion — "a PR that breaks flake evaluation fails the check" — needs a step that
evaluates.

## Solution

Two moving parts, plus the ordering between them.

**One CI workflow that also runs on pull requests.** `.github/workflows/flake-checker.yaml` becomes
`.github/workflows/ci.yaml` (`git mv`) and grows a second job. `Flake Checker` keeps its existing
steps and its existing daily/push behavior, now also reporting on PRs as an advisory annotation.
`Nix Eval` is new: on Linux it evaluates the NixOS host all the way to a derivation path, which forces
the whole module system — `lib/`, `home/default.nix`, `home/common/**`, `hosts/common/**` — through
the evaluator. Breaking any of them turns the job red.

**One required status check on `main`, applied from a committed payload.** The context string
`Nix Eval` is required via classic branch protection with `enforce_admins: true`, so the merge button,
`gh pr merge`, and `gh pr merge --admin` all refuse until the job is green. The payload lives in
`.github/branch-protection.json` and is applied, inspected, and removed by three `just` recipes, so
the outward-facing repo-settings change is version-controlled, agent-runnable, and reversible with one
command.

The failure mode that matters is not "the gate is too weak" — it is "the gate is on a context that
never reports", which blocks every merge to `main` forever with no error message pointing at the
cause. The required context string and the job's reported name are the same string held in two files
that GitHub will never reconcile for us, so a unit test pins them together.

## Decisions

### Words used precisely

Three things are called "check" in casual speech and they are not the same, which matters because the
gate is exactly the join between them:

- A **check run** is what GitHub Actions creates for a job. Its name is the job's `name:` — not the
  workflow's name, and not the job's key. For a matrix job it is `name (matrix-value)`, and for a
  reusable workflow it is `caller-job / callee-job`.
- A **context** is the string branch protection matches against. Classic protection's
  `required_status_checks.contexts` matches check-run names as well as legacy commit-status contexts,
  so `"Nix Eval"` in the payload must equal `Nix Eval` in `ci.yaml` byte for byte.
- **Required** is a property of the context, not of the job. A job can run and report without being
  required, which is exactly what `Flake Checker` does here.

One consequence is a design constraint, not a style preference: **the job backing a required context
must stay a plain job** — no `strategy.matrix`, no `workflow_call` — because either one silently
renames the check run and the required context then never reports.

A second is an API asymmetry worth writing down before someone hits it: `enforce_admins` is a plain
boolean in the `PUT` body but comes back from `GET` as an object, `{"enabled": true}`.

### What runs on a pull request

One workflow file, honestly named for what it now is, with two jobs:

- **`Flake Checker`** — unchanged steps (`checkout` with full depth, `nix-installer-action`,
  `flake-checker-action`), minus the dead cache action. Runs on every trigger. Advisory: with the
  action's default `fail-mode: false` it reports lock staleness and disallowed refs without failing.
- **`Nix Eval`** — checkout at full depth, `nix-installer-action`, then evaluate
  `nixosConfigurations.anis-desktop` down to `config.system.build.toplevel.drvPath`. Skipped on the
  `schedule` trigger only.

Triggers: `pull_request` on `main`, `push` on `main`, the existing daily cron, `workflow_dispatch`.
A `concurrency` group keyed on the PR number — falling back, for every non-PR trigger, to the event
name and the commit SHA together (D25, D28) — with `cancel-in-progress` scoped to pull requests, so
pushing a PR again supersedes only that PR's own in-flight run.

Evaluating to `drvPath` rather than `nix flake check` is deliberate: `nix flake check` would try to
reach `darwinConfigurations.mbp` too, which cannot be evaluated without an aarch64-darwin builder and
would drag in the large `homebrew-core`/`homebrew-cask` inputs. Evaluation of the NixOS host also
triggers import-from-derivation (catppuccin's starship module builds `catppuccin-starship` during
evaluation), which is why the job needs a real `x86_64-linux` Nix builder and not just an evaluator —
an `ubuntu-24.04` runner is one natively.

### What branch protection says

`.github/branch-protection.json` is the whole `PUT` body. The API rejects a payload missing any of
the four top-level keys, so all four are present and two are explicitly `null`:

```json
{
  "required_status_checks": { "strict": false, "contexts": ["Nix Eval"] },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null
}
```

`strict: false` — a PR does not have to be rebased onto the tip of `main` before merging. `strict:
true` would serialize the five concurrent issue branches of the live orchestration run: every merge
would invalidate every other open PR and force a rebase-and-rerun cycle.

`enforce_admins: true` — this is the load-bearing field. The account is the repo admin and the agent
runs with the owner's token, so with `enforce_admins: false` an admin `gh pr merge` would still walk
straight past the check and the issue's second acceptance criterion would be false for exactly the
actor the gate exists to constrain.

### The recipes, and the undo

Three recipes in the `justfile`, using `gh api`'s `{owner}`/`{repo}` placeholders so no repo slug is
hardcoded. `{branch}` is deliberately **not** used — `gh` expands it to the *current* branch, which
would point the call at whatever branch the operator happens to be standing on; `main` is written
literally, which makes the recipes safe to run from any checkout.

- `just protect-main` — `PUT`s the committed payload. Idempotent: `PUT` replaces the whole protection
  object, so re-running after a job rename converges rather than accumulating.
- `just unprotect-main` — `DELETE`s protection entirely. This is the documented undo, and the escape
  hatch if the required context is ever wrong.
- `just show-protection` — `GET`s the live protection, for verifying what is actually applied.

### The rollout, in order

Enabling a required check whose context has never reported blocks every already-open PR immediately,
and the orchestration run spanning issues 29-33 is live right now. The order is therefore part of the
design, not an implementation detail:

1. This branch's PR merges to `main`, putting `ci.yaml` there. The PR itself demonstrates that checks
   now appear on a PR head.
2. **Reconcile and push any pending direct-to-`main` commits — unconditionally, before step 3.**
   Measure this at rollout time; do not carry a SHA forward from the design. When this section was
   first written, local `main` held one unpushed commit (`c560008`, the out-of-scope record) that had
   to be merged and pushed before the switch was flipped. That commit's content has since reached
   `origin/main` under a *different* SHA (`d5b0d84`), so `c560008` is no longer an ancestor of `main`
   at all and any gate naming it can never pass — which is exactly why the step is now written as a
   measurement rather than a fact (D23). Fetch, then read `git log origin/main..main`: if it is empty
   there is nothing to reconcile and the step is satisfied. If it is not empty, merge `origin/main`
   into local `main` (never rebase, never force — `main` is shared), verify the PR merge commit is
   contained, then push and confirm the remote tip. Required status checks apply to
   direct pushes as well as to merges, and `enforce_admins: true` removes the owner's bypass, so a
   commit carrying no `Nix Eval` status is expected to be refused at `git push origin main` once
   protection is on. That expectation is not something to test the hard way with an unpushed commit
   sitting on the branch: push first, then flip the switch. If protection turns out to be laxer than
   this, nothing was lost.
3. `just protect-main`, then `just show-protection` to confirm what landed.
4. Demo: open a throwaway PR, watch `Nix Eval` report, confirm `gh pr merge` is refused while it is
   pending or red, and confirm it goes green on a clean change.
5. Unblock the siblings. Every PR open at step 3 now shows `Expected — Waiting for status to be
   reported` and cannot merge until `Nix Eval` reports on its head. GitHub does not retroactively
   trigger workflows, and a `pull_request` run cannot be started with `workflow_dispatch`, so each
   sibling needs one new event: `gh pr close <n> && gh pr reopen <n>` re-fires `pull_request` with
   zero commits (`reopened` is in the default type set), or an empty commit does the same. Siblings do
   **not** need `ci.yaml` on their own branch — `pull_request` runs execute the workflow from the
   base/head merge commit.

### The `CLAUDE.md` sentence

Line 22 currently ends: "CI (`.github/workflows/flake-checker.yaml`) only runs DeterminateSystems
flake-checker on push/daily — it does not build or deploy." That becomes false the moment `ci.yaml`
lands. The replacement is a correction of that clause plus the new gate, and it must land in the
implementation commit rather than this design commit — a docs edit describing behavior not yet in the
tree is false at `HEAD`. The plan owns it as a task; the wording to apply:

> There is **no unit-test suite for the Nix configs** — `just build` (a successful Nix evaluation +
> build) is the local verification step. After editing any `.nix`, run `just build` before claiming
> success; switch only when asked. CI (`.github/workflows/ci.yaml`) runs on pull requests and on push
> to `main`, plus daily (where only `Flake Checker` runs): `Flake Checker` annotates `flake.lock`
> health without failing, and **`Nix Eval` evaluates `nixosConfigurations.anis-desktop` on Linux and
> is the context `.github/branch-protection.json` makes required on `main`** — once
> `just protect-main` has been applied, with `enforce_admins` on, `gh pr merge` (including `--admin`)
> is refused until `Nix Eval` is green, and direct pushes to `main` are refused outright (a commit
> that has never reached the remote can carry no status). CI does not build or deploy, does not evaluate
> `darwinConfigurations.mbp`, and does not run `just agent-workflow-tests`; the mac and the Python
> suites are still the author's local responsibility. `just protect-main` / `just unprotect-main` /
> `just show-protection` manage that protection from `.github/branch-protection.json`.

Note the first clause also changes: the blanket "no test/lint suite" claim was already stale —
`just agent-workflow-tests` runs seven Python suites — and this change adds an eighth.

## Test seams

The gate spans two systems, and only one of them can be tested offline. Both seams are existing ones.

**`just agent-workflow-tests` — `tests/test_branch_protection.py` (new file, stdlib only).** This is
the repo's established way of pinning a config or prose contract that no runtime exercises (this
change makes it the eighth suite wired into that recipe). Seven assertions, each able to fail for one
reason:

1. The job-name extractor finds something at all, and finds both `Nix Eval` and `Flake Checker`. This
   guards the rest: an indentation-based extractor that matches nothing would make every string
   comparison below pass vacuously (D19).
2. Every string in `required_status_checks.contexts` matches a job `name:` in `ci.yaml`. This is the
   brick-the-branch failure, and the one that most needs a test: a rename on either side turns it
   red. Job names are the four-space-indented `name:` lines (workflow name is at column 0, step names
   at six or more), which the test also pins as the file's convention.
3. `ci.yaml`'s `on:` block includes `pull_request` scoped to `main`, and that trigger carries no
   `paths:`, `paths-ignore:` or `types:` narrowing — the "PRs get no checks at all" regression, plus
   the three narrowings that would stop the required check reaching a PR while leaving its name
   correct (D27). Dropping the default `types:` set would also break the rollout's close+reopen
   unblock, which depends on `reopened`.
4. The job backing a required context carries no unreviewed job-level `if:` — the fourth way it can
   silently stop reporting on a pull request (D27).
5. That job also carries no `needs:`, no `continue-on-error:`, and no step-level `if:` — the inverse
   and worse failure, where the context keeps reporting *success* while the evaluation it exists to
   run was skipped (D29).
6. The payload carries all four top-level keys the API requires, with `enforce_admins` true — a
   hand-edit that drops `restrictions` would otherwise only surface as a 422 at apply time.
7. No job backing a required context declares `strategy:` or `uses:` — the two ways GitHub silently
   renames a check run out from under its required context (see *Words used precisely*). Assertion 2
   compares strings and would still pass while `main` bricked.

The test deliberately does **not** assert that `Nix Eval` passes, or that GitHub honours the
protection. It asserts the two files agree; that is all a unittest over YAML and JSON can observe, and
naming it for more would overstate its coverage.

**The live GitHub API, exercised once by the demo PR.** `gh pr checks`, `gh pr merge`,
`gh pr view --json mergeStateStatus`, and `gh api .../branches/main/protection`. This is the only seam
that observes the actual gate, it needs a real PR against a real repo, and its output is recorded as
evidence rather than automated.

## Acceptance criteria

1. On a PR targeting `main`, `gh pr checks <n>` lists `Nix Eval` and `Flake Checker` against the PR
   head. At the base commit `b59ff22` the same command prints "no checks reported".
2. `gh api repos/fagenorn/nix-config/branches/main/protection --jq '[.required_status_checks.contexts,
   .required_status_checks.strict, .enforce_admins.enabled]'` returns `[["Nix Eval"], false, true]`.
3. With `Nix Eval` pending or failing on a PR, `gh pr view <n> --json mergeStateStatus` reports
   `BLOCKED` and `gh pr merge <n>` exits non-zero with GitHub's refusal. `gh pr merge <n> --admin` is
   refused too.
4. A commit that breaks evaluation of a shared module turns `Nix Eval` red, and reverting it turns it
   green — demonstrated on the throwaway PR, with both run URLs recorded.
5. `just agent-workflow-tests` passes with `tests/test_branch_protection.py` included, and fails if
   the required context or the job name is edited on one side only, or if a `strategy:` is added to
   the job backing a required context. Each is demonstrated by making the edit, seeing red, and
   reverting.
6. `just unprotect-main` leaves `GET .../branches/main/protection` returning 404 "Branch not
   protected", proving the undo path before it is ever needed in anger.
7. `CLAUDE.md` line 22 no longer claims CI runs only on push/daily.

## Out of scope

- The permission-classifier change (https://github.com/fagenorn/nix-config/issues/30). It is blocked
  on this and ships separately.
- **Building** either host system in CI. `Nix Eval` stops at the derivation path; realising it is what
  `just build` does on the author's machine.
- macOS runners and any evaluation of `darwinConfigurations.mbp`. A darwin-specific regression that
  does not touch shared code will still reach `main` — that gap is real and is named in `CLAUDE.md`.
- **Running `just agent-workflow-tests` in CI.** This is the gate's largest honest hole and it is
  worth naming plainly: most recent churn in this repo is Python and Markdown under
  `home/common/agent-skills/**`, and `Nix Eval` passes every such change without executing one
  assertion. The hole is a follow-up issue, not a redesign — once the required-context machinery
  exists, closing it is one job in `ci.yaml` plus one string in `branch-protection.json`. See D15.
- Required review counts, linear history, signed-commit enforcement, conversation resolution,
  force-push and deletion restrictions. The issue asks for a status-check gate; each of the others is
  its own policy decision with its own blast radius.
- Rulesets. Classic protection is what the issue names and it is one idempotent call.
- Nix store caching (FlakeHub Cache or `actions/cache`). A tuning knob, not a gate.
- Deploy or release automation.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The required check is a **Nix evaluation**, not `flake-checker-action`; flake-checker stays on the PR as an advisory annotation | Verified against the action's `action.yml`: it only parses `flake.lock` (branch, age, allowed refs) and its `fail-mode` defaults to `false`, so it exits zero on every problem it finds. Issue 29's AC3 ("a PR that breaks flake evaluation fails the check") has no referent without an evaluating step; the-bar's *Tests that can fail* | Set `fail-mode: true` and require flake-checker alone — turns nixpkgs staleness (a 30-day maintenance clock) into a merge blocker on every unrelated PR, and still never evaluates `flake.nix` |
| D2 | Exactly **one** required context, `Nix Eval`. `Flake Checker` runs on PRs but is not required | Every required context is another string that must match forever or `main` bricks; a context that cannot fail (D1) is a status bar, not a gate, and requiring it would be theatre. Smaller and more reversible where both options are defensible | Require both contexts — doubles the brick surface to buy a check that exits zero by design |
| D3 | CI evaluates `nixosConfigurations.anis-desktop` to `config.system.build.toplevel.drvPath` on `ubuntu-24.04`; darwin is not evaluated in CI | The NixOS host exercises every shared path (`lib/`, `home/default.nix`, `home/common/**`, `hosts/common/**`); evaluation triggers IFD (catppuccin's starship module builds during eval) so it needs a native `x86_64-linux` builder, which the runner is. Darwin would need a macOS runner plus the large `homebrew-*` inputs for one extra host | `nix flake check` (reaches `darwinConfigurations.mbp` and fails without an aarch64-darwin builder); add a macOS runner (buys one host at several times the cost and runtime, out of the issue's scope) |
| D4 | `git mv` the existing workflow to `.github/workflows/ci.yaml`, `name: CI`, and add `Nix Eval` as a second job in it rather than a second file | the-bar's *Name for intent* — a file called `flake-checker.yaml` containing an evaluation job is a lie — and *DRY*: two files both invoking `flake-checker-action` would be two homes for one step. One CI entry point, one place to look. The rename is staged with `git mv` and costs the Actions-UI run-history grouping; it also costs the `git log --follow` link, because the same commit rewrites the file's contents and drops the similarity index below Git's rename threshold — recovering that link would mean a separate content-identical move commit, which is not worth one commit here (amended after the final review's conformance axis, CNF-007, measured it) | A new `pr-checks.yaml` alongside the untouched original (duplicates the flake-checker step, or splits PR checks across two files); keep the old filename (misnames the file for its contents) |
| D5 | `Nix Eval` carries `if: github.event_name != 'schedule'`; `Flake Checker` keeps its daily cron | `flake.lock` is pinned, so `main` cannot spontaneously stop evaluating — a daily eval catches nothing the push run did not already catch, and the cron exists for nixpkgs staleness, which is flake-checker's job. Skipping on `schedule` never affects a PR, where the job always runs | Run both jobs on every trigger (spends several minutes of runner time daily to re-prove a pinned evaluation) |
| D6 | Drop `DeterminateSystems/magic-nix-cache-action@v2`; add no replacement cache | The Magic Nix Cache service was retired upstream in favour of FlakeHub Cache, so the step buys nothing in the existing job. `flakehub-cache-action` needs FlakeHub auth and `id-token: write` — credentials and a new failure surface for one eval on a public repo, which is YAGNI. `nix-installer-action` still configures `cache.nixos.org`, so cached IFD derivations substitute rather than build | Swap in `flakehub-cache-action` (auth setup, new failure surface, not asked for); keep the dead action (a step that no longer caches) |
| D7 | Classic branch protection via `PUT /repos/{owner}/{repo}/branches/main/protection`, with the body committed at `.github/branch-protection.json` and applied by `just protect-main` | The issue names branch protection and it is one idempotent call; committing the body makes the setting reviewable and diffable, and the justfile is this repo's documented entry point for every workflow (`CLAUDE.md`: "All workflows go through the `justfile`") | A repository ruleset (a second, richer mechanism for the same outcome, more JSON, and not what the issue asks for); an inline `gh api -f` recipe (the payload's nested nulls do not survive flag-encoding legibly) |
| D8 | `enforce_admins: true`, accepting that the human owner also loses the bypass on merges and on direct pushes to `main` | The agent merges with the owner's admin token, so `false` would leave AC2 ("`gh pr merge` … is refused by GitHub") false for exactly the actor the gate exists to constrain — and `.out-of-scope/ungated-agent-merges.md` rejected precisely the "trust the merging actor" model | `enforce_admins: false` (keeps direct pushes to `main` easy, and makes the gate advisory for the only actor that matters) |
| D9 | `strict: false` — a PR need not be up to date with `main` to merge | The orchestration run spanning issues 29-33 has five branches in flight; `strict: true` makes every merge invalidate every other open PR and forces a serialized rebase-and-rerun cycle. Staleness risk is low here — the branches touch disjoint areas and evaluation is the only gate | `strict: true` (safer against semantic conflicts, at the cost of serializing a live parallel run) |
| D10 | No `required_pull_request_reviews`; `restrictions` null. Both keys are still present as explicit `null` | The API rejects a payload missing either key, so presence is mandatory; requiring reviews would block solo and unattended merges outright, which is the opposite of what the issue asks for | Require one approving review (blocks every agent merge and every solo merge); omit the keys (422 at apply time) |
| D11 | Protection is applied as an explicit post-merge step, after any pending direct-to-`main` commit has been pushed, and the sibling-unblock procedure (`gh pr close && gh pr reopen`) is part of the rollout | Required checks apply to direct pushes as well as merges, and `enforce_admins: true` removes the bypass, so whatever is local-only on `main` must be pushed before the switch is flipped — measured at rollout time rather than named here (D23). GitHub never retroactively triggers workflows and a `pull_request` run cannot be `workflow_dispatch`ed, so each already-open sibling needs one new event | Apply protection in the same PR (impossible — the context cannot report until the workflow is on `main`); wait for the whole orchestration run to drain (issue 30 is blocked on this landing) |
| D12 | A stdlib `unittest` file, `tests/test_branch_protection.py`, wired into the existing `just agent-workflow-tests`, asserts that the required contexts equal `ci.yaml` job names, that `pull_request` on `main` is a trigger, that the payload has all four required keys, and (per D16) that no required job is a matrix or reusable-workflow job. The recipe's name is about agent workflows and this is CI config — accepted friction, because it is the repo's only test entry point and renaming it would touch every plan and skill that cites it | the-bar's *Tests that can fail*: the context-vs-job-name mismatch is the failure that silently blocks `main` forever with no error pointing at the cause, and it is mechanically checkable offline. The recipe is the repo's only test entry point and already pins prose and config contracts this way; job names are extracted by indentation depth rather than a YAML parser because no YAML module is guaranteed on this host | No test (leaves the highest-consequence, easiest-to-check invariant unpinned); a new `just` recipe for one file (a second test entry point to remember) |
| D13 | `gh api` uses the `{owner}`/`{repo}` placeholders but writes `main` literally, never `{branch}` | `gh` expands `{branch}` to the *current* branch, so a recipe run from a feature worktree would protect the wrong branch; the literal makes the recipes safe from any checkout, and matches the justfile's existing habit of naming hosts literally | Hardcode `fagenorn/nix-config` (breaks on a fork); use `{branch}` (silently targets whatever branch the operator is standing on) |
| D14 | The `CLAUDE.md` correction is specified here verbatim but applied in the implementation commit, not this design commit; its first clause ("no test/lint suite") is corrected at the same time | A docs edit describing a workflow that is not yet in the tree is false at `HEAD` — the-bar's *Production-grade by default*. The stale first clause is in the same sentence and would otherwise need a second edit to the same line later | Edit `CLAUDE.md` in the spec commit (documents behavior that does not exist yet); leave the "no test/lint suite" clause alone (a knowingly false sentence left in the line being edited) |
| D15 | `just agent-workflow-tests` is **not** run in CI by this slice; the gap is named in *Out of scope* and in `CLAUDE.md` rather than quietly left for a reader to discover | The issue's slice is the merge-gate *mechanism* (its demo is "a check appears and blocks merge"), and the eight Python suites are a second gate that this one makes cheap to add later — one job plus one context string. Widening now expands the blast radius of an already hard-to-reverse repo-settings change, and running the recipe on a runner needs `just`, which is not preinstalled, so it is not the two-line job it looks like | Add a `Tests` job and require it too (closes the hole where most churn lives, but doubles the required contexts and the brick surface in the same change that introduces both); inline `python3 -m unittest <seven paths>` into the workflow (a second authoritative home for the suite list — the-bar's DRY) |
| D16 | The job backing a required context is constrained to be a plain job — no `strategy.matrix`, no `workflow_call` — and the constraint is enforced by the test, not just documented | GitHub derives a check-run name from the job name, but suffixes it for a matrix (`name (value)`) and prefixes it for a reusable workflow (`caller / callee`); either silently decouples the reported name from the required context while a pure string comparison between the two files still passes, blocking `main` with no error that points at the cause | Document the constraint in prose only (the failure it prevents is invisible until every merge is blocked); assert the exact reported name against the live API (needs a network call from a unit test) |
| D17 | The rollout of D11 is written as **Task 5 of the committed plan**, explicitly fenced off from plan execution ("ship-time only, NOT Phase 6"), rather than as a new runbook file or as prose only in this spec | The plan is committed to the repo, so the procedure survives the session that wrote it without adding a fourth document for one ordered list — YAGNI, and `CLAUDE.md` already gains the durable half (the three recipes). The fence is load-bearing rather than tidy: an implementer that runs `just protect-main` during Phase 6 blocks all five in-flight branches of the live orchestration run | A `.github/branch-protection.md` runbook (a fourth home for a procedure run once); leave the ordering in the spec only (plan executors read the plan, not the spec, and would meet the sequencing constraint nowhere) |
| D18 | Every Phase-6 verification gate is offline: `python3 -m json.tool`, `ruby -ryaml -e 'YAML.load_file(…)'` (verified — PyYAML is absent on this host, ruby's is present), `just --dry-run <recipe>` (verified — prints the expanded command, executes nothing), and `just agent-workflow-tests`. The live gate is ship-time evidence, not a plan gate. The workflow's `nix eval --show-trace --raw '.#nixosConfigurations.anis-desktop.config.system.build.toplevel.drvPath'` and its `cancel-in-progress: ${{ github.event_name == 'pull_request' }}` are fixed here | No Nix evaluation of a NixOS host is possible on this darwin machine, so a plan gate naming `nix eval` would be unrunnable and silently skipped — the-bar's *Verify before claiming done* needs gates that actually run. Cancellation is scoped to PRs so that superseding a PR push never cancels a run on `main`, where a cancelled `Nix Eval` would leave a landed commit without its reported result | Gate on `nix build`/`nix flake check` in Phase 6 (unrunnable here); blanket `cancel-in-progress: true` (cancels `main`'s own runs when two pushes land close together) |
| D19 | The new suite is `tests/test_branch_protection.py` at the repo root, and its first test asserts the job-name extractor found anything at all before the other tests compare strings | `tests/` already holds `test_agent_costs.py` and the recipe already lists it there; CI config is not an agent skill, so `home/common/agent-skills/tests/` would be the wrong neighbourhood. The anti-vacuity test exists because the characteristic bug of an indentation-based extractor is matching nothing and passing green — a test that cannot fail is the-bar's *Tests that can fail* inverted | Put it under `home/common/agent-skills/tests/` (files that change together live together — this one changes with `.github/`, not with the skills); assert only the string comparisons (a regex that stops matching then reports OK) |
| D20 | `CLAUDE.md`'s new paragraph phrases the gate conditionally — `Nix Eval` is "the status check `main`'s branch protection requires", refusing merges and direct pushes **once `just protect-main` has been applied** — rather than flatly asserting the check is required | Protection is applied in the post-merge rollout (D11/D17), so at the commit that lands the paragraph the assertion would be false at `HEAD` — the same reason D14 moved the edit out of the design commit. The conditional is true both before and after the rollout, so no second edit is owed | Assert the flat "is a required status check" (false at the commit that ships it, and nothing later goes back to correct it); split the paragraph across two commits (a second doc edit for one clause) |
| D21 | The rollout is bound to `ship-issue` by an explicit Phase-7 handoff contract in the plan: the PR body references issue 29 by full URL with **no closing keyword**, Task 5 runs between merge verification and cleanup, and an incomplete rollout returns a failed/stopped state with the issue left open | `ship-issue` has no post-merge rollout hook — Phase 7 hands straight to Phase 8's `gh issue close` and worktree removal — and its default body carries `Closes #<num>`, which auto-closes at merge here because the base *is* the default branch. Without the contract the issue closes and the worktree disappears with the gate still off, and "merged" would be reported as "shipped" | Rely on `ship-issue`'s defaults (closes the issue before any rollout evidence exists); add a rollout phase to the `ship-issue` skill itself (a global skill change for one issue's ordering, outside this slice) |
| D22 | Every rollout step from protection onward has a defined failure transition, all of them ending in `just unprotect-main` + a verified 404 + a truthful failed/stopped report: on an unexpected readback, on any failure during the destructive demo, and on a sibling that cannot acquire `Nix Eval` within a bounded wait | Protection lands before a multi-run demo and before the siblings can report, so the interval between "gate on" and "gate proven" is exactly when a half-applied gate blocks four live PRs with no error pointing at the cause — the-bar's boundary handling and *Verify before claiming done*. The undo already exists (D7); the gap was that no step was required to reach for it | Leave recovery to operator judgement (the failure is invisible from inside the run, and the operator is an agent); roll forward with ad-hoc `gh api -f` flags (diverges the live setting from the committed payload) |
| D23 | Local `main` is integrated with the post-merge `origin/main` by a **merge** before the rollout push, and the rollout step is written as a *measurement* — `git log origin/main..main`, empty or not — rather than as a claim about a named commit. Protection stays off until the pushed tip matches. **Amended 2026-08-17:** the row originally gated on `git merge-base --is-ancestor c560008 main`; `c560008`'s content has since reached `origin/main` as `d5b0d84`, so `c560008` is no longer an ancestor of `main` and that gate can never pass | The hazard is real and unchanged: once protection is on, `enforce_admins: true` plus a required context means an unpushed direct-to-`main` commit can no longer be pushed at all, so reconciliation has exactly one safe window. What was wrong was pinning the window to a SHA measured at design time — a shared branch is exactly the thing that gets rewritten under you between design and rollout, and a gate naming a stale SHA fails closed on a divergence that does not exist. Raised by the final review's conformance axis (CNF-001) | `git push --force` (rewrites shared history to fix an ordering mistake); rebase local `main` onto `origin/main` (rewrites an already-published-by-merge commit); re-point the gate at `d5b0d84` (buys one rollout and breaks again the next time `main` advances) |
| D24 | AC4's red run is a named, deterministic edit: an undefined identifier appended inside `environment.systemPackages` in `hosts/common/common-packages.nix`, proven by reading the failing job's `conclusion` from `gh run view --json jobs` rather than the run's overall status, and reverted with the demo PR closed-never-merged | "A commit that breaks evaluation of a shared module" is not executable, and the plausible improvisations are worse: a change under `home/` may not be forced to a derivation path, and a syntax error can fail differently per evaluator. That file is imported by every host and its package list is forced by `toplevel.drvPath`, so the failure is an evaluation error in `Nix Eval` and nowhere else. Per-job conclusions also prove `Flake Checker` stayed green, which is D1/D2's whole claim | Break `flake.nix` itself (fails earlier, and risks a state where even the revert cannot be evaluated); leave the target to the executor (unreproducible evidence, and a real chance of a probe commit reaching `main`) |
| D25 | The `concurrency` group is `ci-${{ github.event.pull_request.number || github.sha }}`: pull requests are keyed by PR number and cancel in flight, every other trigger is keyed by commit SHA | `cancel-in-progress: false` stops GitHub cancelling an *in-progress* run but not a *pending* one, and every non-PR trigger resolves to the same `ci-refs/heads/main` group — so a queued `push` run is superseded by the next merge or by the 13:37 cron and its commit's `Nix Eval` reports *cancelled*, never a result. Once protection is on, required contexts apply to direct pushes to `main`, so that commit could never satisfy the gate. Raised by the Task-1 review against the plan's own dictated YAML | Key non-PR runs on `github.ref` and reword the comment to admit pending runs may be superseded (keeps a real hole in the gate to avoid editing one line); drop `concurrency` entirely (lets a PR's superseded runs race) |
| D26 | `test_required_jobs_are_plain_jobs` guards `required_contexts()` for non-emptiness and asserts `assertIn(context, names)` before indexing, rather than iterating and indexing straight into `job_names()` | The suite's stated invariant is that no list is iterated before it is asserted non-empty, and this was the one test that broke it: with `"contexts": []` the test passes in isolation while asserting nothing, and its red today is borrowed from two sibling assertions it does not name. The bare index also raised `KeyError` where the file's other assertions take care to explain the failure — an ERROR is the wrong signal in a suite whose product is a legible message. Raised by the Task-3 review against the plan's own dictated code | Leave it and rely on the siblings (a vacuous test inside the file that exists to prevent vacuous tests); delete the test as redundant (loses the matrix/reusable-workflow pin, which is the D16 hazard nothing else covers) |
| D27 | `tests/test_branch_protection.py` also pins the *reachability* of the required check, not only its name: the `pull_request:` trigger must carry no `paths:`/`paths-ignore:`/`types:` narrowing, and a job backing a required context may carry only a reviewed `if:` expression | The name pin closes a rename; it does not close the three edits that stop `Nix Eval` reporting on a PR at all — a `paths:` filter, a `types:` list that drops `reopened` (which the rollout's close+reopen unblock depends on), or an `if:` that excludes pull requests. Each leaves all five original assertions green while every PR blocks forever on a context that never reports, which is the failure the suite exists to surface. Raised by the final review's correctness axis (COR-001) | Pin the trigger shape in prose only, as the plan's Task-1 invariants already did (an invariant no test pins is the gap this file was written to close); assert the `if:` is merely absent (rejects the reviewed expression the workflow actually needs) |
| D28 | The `concurrency` group's non-PR fallback keys on the **event name and the commit SHA together** — `format('{0}-{1}', github.event_name, github.sha)` — not on the SHA alone | D25 moved the fallback off `github.ref` to stop a queued `push` run being superseded before its `Nix Eval` could report, but the SHA alone does not finish the job: the daily cron resolves `github.sha` to the tip of `main`, so a scheduled run joins the same group as that commit's own push run and can evict it while it is still queued — and `Nix Eval` is skipped on `schedule` (D5), so the commit ends up with no reported result at all. Adding the event name gives each commit's push run a group no other trigger can enter. Raised by the final review's correctness axis (Codex COR-001) | Key on the SHA alone (leaves D25's own failure mode open through the cron, on the one branch where a missing result matters most); drop the `schedule` trigger from the workflow (removes the collision by removing the feature flake-checker's cron exists for) |
| D29 | `tests/test_branch_protection.py` also pins that the job backing a required context carries no `needs:`, no `continue-on-error:`, and no step-level `if:` | Every other pin in the file catches a context that stops *reporting*. This catches the inverse, which is strictly worse: a context that keeps reporting **success** while the evaluation it exists to run was skipped. Moving the `if:` from the job to the evaluating step leaves all six prior assertions green, the job still runs on pull requests, still reports as `Nix Eval`, and still concludes `success` — having evaluated nothing. Verified by mutation: all three offender classes go red, the shipped file stays green. Raised independently by both axes of the final review (Codex COR-002, correctness COR-008) | Pin only the job-level `if:` as D27 did (leaves the green-but-empty path wide open); parse the YAML properly to reason about step structure (no YAML module is guaranteed on this host — D12's whole reason for an indentation parser) |
| D30 | `actions/checkout` is bumped `@v3` → `@v4` in both jobs; `fetch-depth: 0` is kept in both | A required status check that fails for a reason unrelated to the tree is the same brick as a check that never reports, and `@v3` is a deprecated Node-16 action on GitHub's retirement path — the one dependency in the required job whose failure would be entirely self-inflicted. Both jobs move together so the file has one checkout idiom rather than two. `fetch-depth` is left alone deliberately: `Flake Checker` documents a need for full history, and Nix refuses to evaluate a flake from a shallow git checkout, so trimming it would risk the gate to save a clone. Prompted by the final review's conformance axis (CNF-010, an unrecorded choice) | Leave `@v3` (a known-deprecated action on the highest-consequence path); also set `fetch-depth: 1` on `Nix Eval` (unverifiable from this host, and the failure mode is the required check erroring on a shallow clone) |
| D31 | `CLAUDE.md`, `ci.yaml`'s job comment, and the test's module docstring all phrase the gate as the context `.github/branch-protection.json` **makes** required once `just protect-main` has been applied — never as a check that *is* required — and `CLAUDE.md` now says direct pushes to `main` are refused **outright**, not "until it is green". **Amends D20**, which blessed the earlier `CLAUDE.md` wording | D20 got the principle right and applied it to one file out of three: `ci.yaml:35` and the test docstring both still asserted flatly that the check *was* required, which is false at every commit on this branch — `main` carries no protection at all (verified: `404 Branch not protected`) — and `ci.yaml` is the file a future editor opens first. The push clause was separately unsatisfiable: a status can only attach to a commit already on the remote, so "refused until it is green" describes a condition no direct push can ever meet and invites a retry loop. Raised by both axes (CNF-002/CNF-008/CNF-009, correctness COR-002/COR-009) | Leave `ci.yaml` and the docstring alone because D20 only named `CLAUDE.md` (keeps a false sentence in the most-read of the three files); assert the flat form everywhere and correct it after the rollout (a knowingly false claim shipped on the promise of a follow-up nobody is holding) |
| D32 | `tests/test_branch_protection.py` also pins that the job backing the required context still *performs* the evaluation: its body must match `nix eval` and must contain the literal attribute `.#nixosConfigurations.anis-desktop.config.system.build.toplevel.drvPath`, with YAML/shell comment lines stripped before either check | D29 closed the three structural roads to a green-but-empty check (`needs:`, `continue-on-error:`, a step-level `if:`) and left the plainest one open: edit the step's `run:` body. Replacing it with `run: true` keeps the job on pull requests, keeps it reporting as `Nix Eval`, keeps it concluding `success` — and all seven prior assertions stay green, which is exactly the mutation that found this. Pinning the attribute as well as the command closes the same hole one step in: evaluating some *other* flake attribute is as green, as fast, and as worthless as evaluating none. Verified by mutation: `run: true`, a swapped attribute, the whole step deleted, and the command surviving only inside a comment all go red; the shipped file stays green. Raised by the ship-time review's correctness axis (Codex COR-001) | Pin the command without the attribute (a one-word edit to the attribute path leaves the gate green on a tree it never evaluated); pin the step's whole `run:` body byte-for-byte (any reformatting of a line-continuation breaks the suite for no correctness gain); leave it to the first real CI run to notice (that run is green under this mutation — nothing notices, ever) |
