# gh Authenticates by Keyring Only Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Stop exporting `GITHUB_TOKEN` into every zsh and delete the `github_token` sops secret, so `gh` on every host authenticates only through its `gh auth login` credential, and restate the scrubs' rationale wherever the repository still blames a shell or harness token.

**Architecture:** The sops home module loses its `github_token` declaration and its `export GITHUB_TOKEN=` line in the same commit that `sops unset` removes the encrypted value (spec § Solution: sops-nix validates every declared secret against the store at build time). Task 2 rewords the four sites that state the old cause; every scrub, the sanctioned prefix and the binding stay in code (D4, D6). Verification is one-shot evidence at existing seams plus the guard suite (D5, D7).

**Tech stack:** Nix (nix-darwin + home-manager, sops-nix), sops 3.12.1 with age, Python 3 `unittest` (guard suite against the build, `test_shell_example_contracts.py` from source).

Spec: `.agents/artifacts/specs/2026-10-22-gh-token-keyring-only-design.md`; its `## Decision ledger` rows D1–D7 are cited by ID. Issue: https://github.com/fagenorn/nix-config/issues/399.

## Global Constraints

- Base: `336d9e05` (`origin/main` at planning). Tasks land in index order; Task 2 assumes Task 1's acceptance record exists.
- Unchanged in code: `GH_ENV_TOKEN_NAMES`, `UNSET_GITHUB_TOKEN_PREFIX`, `gh_lookup_env`, everything under `python/agent_tools/`, `python/README.md`, every test assertion, loop and fixture value, `.sops.yaml`, `vars/default.nix`, `hosts/darwin/eleven-m5/omlx.nix`, the `credential_env` binding and the skills (D4).
- The `HF_TOKEN` export line stays byte-identical: `    export HF_TOKEN="$(cat ${config.sops.secrets.hf_token.path})"`.
- Secret hygiene (D3): never print, log or write to disk a decrypted value. Every `sops` call sets `SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"`. A `sops -d` runs only inside the plan's check scripts, which reduce its output to key names and set differences. No `sops edit`, no hand edit of `secrets/secrets.yaml`.
- No new text may contain `shell exports`, `harness exports`, or `exports` followed by one character and `GITHUB_TOKEN`, not even in negated form (D4).
- Never run `just switch`, `gh auth login`/`logout`, or anything that writes `~/.config/sops-nix`, the keychain or gh's config. The per-host checks and the PAT revocation are the user's (AC6, AC7).
- Do not run a local `nix eval` of `nixosConfigurations.anis-desktop`: on this darwin host it fails at the base too (it needs an `x86_64-linux` build during evaluation). The PR's CI `Nix Eval` is the `anis-desktop` check.
- Every long command runs in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>` with an explicit timeout above its duration; a multi-line gate is saved as a file under the `launch-scope scratch` root and run as `… -- bash <file> <args>`. Commits go through `launch-commit … -- <git commit args>`, signed, ending with the session's trailers.
- Timeouts: `nix eval` checks 900 s; `just build` 3600 s; the guard-suite invocation 1200 s (3600 s cold); `just agent-workflow-tests` 3600 s.
- Final gate (sdd's final verification, once on the final head): `just build` and `just agent-workflow-tests`.

## Test seams

- Build seam: `just build` for `mbp`; `nix eval --raw .#darwinConfigurations.eleven-m5.config.system.build.toplevel.drvPath` (D5); the PR's CI `Nix Eval` of `anis-desktop`.
- Evaluated-config seam: `nix eval` of `mbp`'s home-manager `programs.zsh.initContent` and of `sops.secrets` names, plus `git grep` over `*.nix` and `data` (D5).
- Store seam: the base commit's encrypted store and the edited one, both decrypted inside one check script that prints key names and set differences only (D3).
- Doc seam: `git grep -n -e 'shell exports' -e 'harness exports' -e 'exports .GITHUB_TOKEN' -- CLAUDE.md home python`, plus a comment-only diff check on the guard and its suite (D4, D6).
- Existing suites: the guard-suite invocation (Task 2) and `just agent-workflow-tests` (final gate) (D7). No new test (D5).
- Host seam (human): per host, after `just switch`, in a fresh login shell.

## Delivery estimate and boundaries

Estimate: 6 changed files plus the acceptance record. `home/common/sops/default.nix` −2 lines. `secrets/secrets.yaml` −1 key line and 2 rewritten metadata lines (`lastmodified`, `mac`); a scratch trial of `sops unset` with sops 3.12.1 left every other ciphertext unchanged. `CLAUDE.md` and `home/common/claude-code/README.md` one line each, `lifecycle_guard.py` 6 comment lines become 8, the guard suite 3 comment lines become 4. One review package, no aggregate-growth risk. Task 1 is the security change and is deliverable alone; Task 2 is the rationale text.

## Task index

Task 1 — Remove the GitHub token from the shell and the secret store — `home/common/sops/default.nix`, `secrets/secrets.yaml`, `.agents/artifacts/plans/2026-10-22-gh-token-keyring-only.acceptance.md` — full — [task-1.md](2026-10-22-gh-token-keyring-only.tasks/task-1.md)
Task 2 — Restate the scrub rationale at the four wrong-cause sites — `CLAUDE.md`, `home/common/claude-code/lifecycle_guard.py`, `home/common/claude-code/README.md`, `tests/test_claude_permission_guard.py`, `.agents/artifacts/plans/2026-10-22-gh-token-keyring-only.acceptance.md` — full — [task-2.md](2026-10-22-gh-token-keyring-only.tasks/task-2.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 1 | `just build` on `mbp` (Task 1 step 6, then sdd's final verification on the final head); the PR's CI `Nix Eval` of `anis-desktop` at ship time. Task 1 also runs the `eleven-m5` drvPath eval (D5). |
| AC2 | evidence | Task 1 | `task1-check.sh` at Task 1's code commit: `nix eval --raw .#darwinConfigurations.mbp.config.home-manager.users.anis.programs.zsh.initContent` exits 0 with zero lines matching `GITHUB_TOKEN` or `GH_TOKEN` and exactly one `^export HF_TOKEN="$(cat /…/hf_token)"$` line, and `git grep -n -e GITHUB_TOKEN -e GH_TOKEN -e github_token -- '*.nix' data` matches nothing (D5). Acceptance-record row `AC2`. |
| AC3 | evidence | Task 1 | `task1-check.sh` at Task 1's code commit: `nix eval --json .#darwinConfigurations.mbp.config.home-manager.users.anis.sops.secrets --apply builtins.attrNames` prints exactly `["hf_token","my_ssh_private_key","my_ssh_public_key"]`, and the store check against `336d9e05:secrets/secrets.yaml` prints `removed` `["github_token"]`, `added` `[]`, `changed` `[]`, so the decrypted key names lack `github_token` (D3). Acceptance-record row `AC3`. |
| AC4 | code | Task 2 | The guard-suite invocation against the build of Task 2's code commit prints `OK` (adversarial table included), cited in acceptance-record row `AC4`; `just agent-workflow-tests` (forge-adapter suite, `tests/test_guard_policy.py`, `test_shell_example_contracts.py`) in sdd's final verification (D7). |
| AC5 | evidence | Task 2 | `git grep -n -e 'shell exports' -e 'harness exports' -e 'exports .GITHUB_TOKEN' -- CLAUDE.md home python` at Task 2's code commit; threshold: zero matches (git grep exit 1). Acceptance-record row `AC5`. |
| AC6 | human | Task 1 | The user, on `mbp`, `eleven-m5` and `anis-desktop`: after `just switch`, in a fresh login shell, `printenv GITHUB_TOKEN` prints nothing, `gh auth status` shows the keyring account active, and `gh repo view elevenyellow/nodocom --json nameWithOwner` and `gh repo view fagenorn/nix-config --json nameWithOwner` succeed with no unset (one `gh auth login` where a host has no stored login). |
| AC7 | human | Task 1 | The user revokes the old fine-grained PAT in GitHub Settings → Developer settings → Fine-grained tokens, once every host is switched (D2). |

## Decisions

- Fix at the source, nodocom cleanup out of scope: per D1, D2.
- Store edit accepted on names and set differences only, against the base commit's encrypted file: per D3.
- Scrubs, prefix and binding unchanged; three doc sites reworded under the phrase ban: per D4. The fourth site, the fake `gh`'s rationale comment in the guard suite: per D6 (added by planning).
- One-shot evidence at existing seams, no new test: per D5. The guard suite run and cited for the suites criterion: per D7 (added by planning).

## Standards review provenance

- Reviewer: Codex (`codex-companion task --fresh --reviewer plan-review`, gpt-6-astra, xhigh), isolated read-only mode, no fallback.
- Base SHA: 336d9e05820d31923e093cbc998b0ccd46439f22; no focus beyond the issue, spec and plan.
- Findings: 0 blocking, 2 should-fix, 0 discussion. Accepted 2, rejected 0, deferred 0.
  - S1 (accepted): the gates now accept only `git grep` exit 1 as zero matches and abort on any other non-zero exit (`grep_none` in both gate scripts), and Task 2 runs its `git diff` on its own so a git error aborts under `set -e`.
  - S2 (accepted): Task 2 Step 6 keeps full build and suite logs under `<scratch>/i399/logs/` and prints a failing step's whole log instead of piping into `tail`.
- Neither finding is a non-obvious decision, so the spec's ledger gained no row.
