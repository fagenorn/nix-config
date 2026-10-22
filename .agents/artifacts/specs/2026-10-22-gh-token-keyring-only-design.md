# gh authenticates by keyring only — issue 399

Design for https://github.com/fagenorn/nix-config/issues/399 (retro finding #1
on nodocom session `bacdf125`). The issue body is the authority. Its inlined
decisions come from an earlier spec that was only ever committed locally, and
this spec reuses that spec's reasoning where it still holds (per D1). A bare
"Dn" cites this spec's ledger.

## Triage

Input: {"signals": {"contract_change": {"value": "no", "evidence": "Removes one zsh export and one sops secret; guard grammar, credential_env binding schema and forge-adapter scrubs stay unchanged"}, "concurrency_or_persistence": {"value": "hit", "evidence": "Deletes the github_token key from the encrypted persisted store secrets/secrets.yaml via sops unset"}, "open_design_questions": {"value": "no", "evidence": "Issue body carries settled decisions: fix at source, delete secret, keep scrubs, no new regression test"}, "criteria_shape": {"value": "hit", "evidence": "Seven acceptance criteria, two of them human per-host checks no deterministic code check verifies"}}, "paths": ["home/common/sops/default.nix", "secrets/secrets.yaml", "CLAUDE.md", "home/common/claude-code/lifecycle_guard.py", "home/common/claude-code/README.md"]}
Verdict: {"hits":["concurrency_or_persistence","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

Every interactive zsh on `mbp`, `eleven-m5` and `anis-desktop` carries a
fine-grained `GITHUB_TOKEN` (`github_pat_…`, no expiry). So does every Claude
Code session started from one of those shells. `gh` prefers an environment
token over its keyring login, and this PAT cannot see the `elevenyellow` org.
As a result, `gh repo view`, `gh pr create` and `gh pr merge` against
`elevenyellow/nodocom` fail with `Could not resolve to a Repository`, even
while `gh auth status` reports "Logged in". In session `bacdf125`, 136 of 486
Bash calls carried an `unset GITHUB_TOKEN` workaround. The user's own hand-run
`gh pr merge 2342 --merge` failed the same way.

The repository's own docs also state the wrong cause. The `CLAUDE.md` secrets
paragraph says the sops module exports the token. The guard's comment says
"the harness exports" it, and the claude-code README says "the shell exports"
it. These statements teach readers that the token is a fixture of the
environment, when it is really a leftover from commit `c924a2bd` ("Setup gh
and token", April 2025).

## Solution

Remove the token at its single source, the sops home module, and stop storing
it. After the change, `gh` on every host authenticates only through the
credential that `gh auth login` stored. That is the macOS keychain on `mbp` and
`eleven-m5`, and gh's own store on `anis-desktop`. A host without a stored login
fails loud with gh's "not logged in", and the fix there is a one-time
`gh auth login` (per D2).

Facts that hold the design up (verified at base `336d9e05`):

- The sops home module's `programs.zsh.initContent` is the only place that
  writes the token: `export GITHUB_TOKEN="$(cat <secret path>)"`. Nothing in
  `data/zshrc`, `hosts`, `lib`, `vars`, the `justfile`, `flake.nix` or `.github`
  names `GITHUB_TOKEN`, `GH_TOKEN` or `github_token`. The issue's consumer sweep
  covered the out-of-repo places: MCP entries, devenv/`.envrc`, `~/.config` and
  nix `access-tokens`.
- The encrypted store holds five keys: `my_ssh_private_key`,
  `my_ssh_public_key`, `github_token`, `hf_token` and `omlx_api_key`. The last
  one is not declared in the sops module. `eleven-m5`'s oMLX unit reads it
  directly from the same file with `sops -d --extract` (per D3).
- When sops-nix's home-manager module builds its secrets manifest, it checks
  that every declared secret exists in the store (`validateSopsFiles`, default
  true). Removing the value while the declaration remains would fail
  `just build`, so the declaration and the value go in the same commit.
- sops-nix links `~/.config/sops-nix/secrets` to the current generation of
  decrypted secrets and prunes older generations (`keepGenerations`, default
  1). After the switch, the decrypted `github_token` file goes away with its
  generation (per D2).
- `python/README.md` and the forge adapter's docstring already justify the scrub
  as "so the keyring credential answers". Only three living sites carry the
  wrong cause (per D4).

## Decisions

**Shell environment.** The sops module's zsh init keeps its `HF_TOKEN` line
exactly as it is and loses its `GITHUB_TOKEN` line. No home-manager option
exports `GITHUB_TOKEN` or `GH_TOKEN`, whether through `initContent`,
`sessionVariables` or `home.sessionVariables`.

**Secret store.** The module stops declaring `github_token`. The value leaves
the encrypted store through
`sops unset secrets/secrets.yaml '["github_token"]'`, run with
`SOPS_AGE_KEY_FILE` pointing at `~/.config/sops/age/keys.txt`, as the
`.sops.yaml` header documents. Without that variable, `sops -d` on `mbp` fails
with "Failed to get the data key" (checked at the base). The edit is accepted only when the decrypted
store's key set is the old key set minus `github_token`, and every remaining
key's plaintext is unchanged. Both conditions are proven by names and digests,
never by printing a value (per D3). sops rewrites its own `mac` and
`lastmodified` fields, and the ciphertexts may change; both are expected.

**gh authentication.** Nothing wraps `gh`, sets `GH_TOKEN`, or checks for a
login at activation. The stored login is the only credential (per D2).

**Defensive scrubs and generic mechanism stay.** The guard's forge lookups,
the forge adapter and the guard-policy compiler keep removing
`GITHUB_TOKEN`/`GH_TOKEN` from every `gh` child, and their tests keep failing
when a token reaches a child. `GH_ENV_TOKEN_NAMES`, `UNSET_GITHUB_TOKEN_PREFIX`,
the `credential_env.unset_before_invocation` binding and the skills that derive
a prefix from it are all unchanged in code (per D4).

**Corrected rationale, three sites.** The new reason is that the keyring
credential is the authority, and an ambient environment token, if present, may
be narrower. That token could come from CI, a one-off export or another tool.
None of the new text may contain `shell exports`, `harness exports` or
`exports` followed by `GITHUB_TOKEN`, not even in negated form (per D4). The
plan carries this wording forward; small edits are fine if they keep the
meaning and the ban:

- *`CLAUDE.md` secrets paragraph.* The clause "declares which secrets get
  decrypted and exports `GITHUB_TOKEN`/`HF_TOKEN` into the shell" becomes
  "declares which secrets get decrypted and exports `HF_TOKEN` into the shell.
  The sops store holds no GitHub token and the shell receives none: `gh`
  authenticates only through its `gh auth login` credential (the macOS
  keychain, gh's own store on `anis-desktop`), and a host without one needs a
  one-time `gh auth login`."
- *Guard comment above `GH_ENV_TOKEN_NAMES` (comment only).* "The gh keyring
  credential is the authority for these lookups. gh prefers an ambient
  GITHUB_TOKEN/GH_TOKEN over it, and such a token, when one is present (CI, a
  one-off export, another tool), may be narrower: it may not see every
  authorized owner's org. The guard's forge lookups drop the env tokens, so
  validation observes GitHub with the keyring credential. That is the same auth
  the guarded command uses when no env token is set or when it runs behind the
  `unset GITHUB_TOKEN && ` prefix. A machine with no keyring auth still fails
  closed at the lookup."
- *claude-code README merge-lookup sentence.* "rather than the narrower
  fine-grained PAT the shell exports" becomes "rather than any ambient
  environment token, which gh would prefer and which may be narrower".

**Rollout.** A running shell or Claude Code session keeps its inherited token
until it restarts. The two human criteria (a per-host switch and fresh-shell
check, then PAT revocation once every host is switched) close the issue. The
nodocom cleanup is a separate, blocked issue that lands only after every host is
switched (per D1).

## Test seams

The change is tested at existing outer seams only. No new permanent test is
added (per D5).

- **Build seam.** `just build` for `mbp` passes, and the PR's CI `Nix Eval` of
  `anis-desktop` is green. Because the edited store is also an input to
  `eleven-m5`'s oMLX unit, `nix eval --raw
  .#darwinConfigurations.eleven-m5.config.system.build.toplevel.drvPath` must
  also succeed (per D5).
- **Evaluated-config seam.** `nix eval --raw` of `mbp`'s home-manager
  `programs.zsh.initContent` has zero `GITHUB_TOKEN`/`GH_TOKEN` matches. At the
  base it prints the `export GITHUB_TOKEN=` line, so this check can fail.
  `nix eval --json` of `mbp`'s home-manager `sops.secrets` names, using
  `--apply builtins.attrNames`, lacks `github_token`. The zsh eval reads only
  `initContent`, so `git grep -n -e GITHUB_TOKEN -e GH_TOKEN -e github_token --
  '*.nix' data` must also return nothing. This covers the "no option exports
  it" decision for `sessionVariables`, launchd and system environments. At the
  base it returns only the sops module's two lines (per D5).
- **Store seam.** The decrypted store's key list, read with `sops -d
  --output-type json … | jq -r 'keys[]'`, lacks `github_token`. A per-key
  sha256 of the plaintext of the four remaining keys matches the same digest
  taken before the edit (per D3).
- **Doc seam.** `git grep -n -e 'shell exports' -e 'harness exports' -e
  'exports .GITHUB_TOKEN' -- CLAUDE.md home python` returns zero matches. Today
  it returns exactly the three sites above.
- **Existing suites.** `just agent-workflow-tests` stays green. That covers the
  guard's adversarial table, `tests/test_guard_policy.py`, the forge-adapter
  suite and `test_shell_example_contracts.py`. Those suites inject their own
  fake token, so they do not depend on the shell's environment. No test pins the
  rewritten English, so no test text changes.
- **Host seam (human).** On each host, after `just switch` and in a fresh login
  shell: `printenv GITHUB_TOKEN` prints nothing, `gh auth status` shows the
  keyring account as active, and `gh repo view elevenyellow/nodocom --json
  nameWithOwner` and `gh repo view fagenorn/nix-config --json nameWithOwner`
  both succeed with no unset. Then the PAT is revoked on GitHub.

## Out of scope

- The guard's `env -u VAR` prefix grammar and its error messages (retro finding
  #2, tracked separately). This change makes an env prefix less necessary but
  does not remove the need.
- Removing the `credential_env` binding schema, the resolver field, the
  sanctioned `unset GITHUB_TOKEN && ` literal or any token scrub (per D4).
- nodocom's data cleanup: emptying its `unset_before_invocation` list and
  rewriting its git guide's "Always `unset GITHUB_TOKEN`" section (blocked
  issue, per D1).
- Revoking the PAT and switching each host. These are the user's human
  criteria, not repository changes.
- Rewriting git history to purge the old ciphertext. Revoking the PAT makes the
  ciphertext worthless (per D2).
- Nix `access-tokens`, re-scoping `HF_TOKEN`, and any new regression test (per
  D5).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Write a fresh spec scoped to nix-config, reusing the local-only spec's reasoning; nodocom cleanup and rollout gating stay in their blocked issue | Issue 399 "Not in scope" and "Rollout"; the bar, "Root causes" (fix the source, here) | Adopting the prior spec as is: it also changes nodocom's binding and guide, which #399 excludes and which must wait until every host is switched |
| D2 | Fix at the source: drop the export and delete the secret from module and store; gh uses only its stored login (no wrapper, no activation check, no cleanup step); the leftover decrypted file is left to sops-nix generation pruning; the user revokes the PAT | Issue Decisions (keyring reaches `elevenyellow/nodocom`; consumer sweep found no reader); sops-nix `keepGenerations` = 1; the bar, "YAGNI" | An org-approved PAT (needs org-admin approval, keeps gh's env-over-keyring trap, two credentials to rotate); an activation `rm` of the old file or a history purge (pruning and revocation already cover both) |
| D3 | Accept the `sops unset` edit only when the decrypted key set loses exactly `github_token` and the other four keys' plaintext digests are unchanged, proven without printing any value; the issue's "`sops -d` has no `github_token`" criterion is measured by key names only | `eleven-m5`'s oMLX unit reads `omlx_api_key` from the same store with `sops -d --extract`; the bar, "Verify before claiming done" | A bare `sops -d` dump or a diff of two (prints every secret into an agent transcript); an interactive `sops edit` (no reproducible evidence) |
| D4 | Keep every scrub, `GH_ENV_TOKEN_NAMES`, the sanctioned prefix and the binding in code; reword only the three wrong-cause sites (`python/README.md` and the forge adapter already say it right), and ban `shell exports`/`harness exports`/`exports … GITHUB_TOKEN` even in negated form | Issue "Keep these unchanged"; the bar, "Defense in depth"; acceptance grep `exports .GITHUB_TOKEN` matches "no longer exports `GITHUB_TOKEN`" too | Deleting the scrubs as dead (a token from CI or a one-off export brings the failure back); also editing `python/README.md` as the local spec planned (its text is already right) |
| D5 | Verify with one-shot evidence at existing seams (mbp build, CI Nix Eval, an extra `eleven-m5` drvPath eval, `nix eval` of the zsh init and secret names, a `*.nix`/`data` token grep, store key/digest check, doc grep, existing suites) and add no permanent test | `CLAUDE.md`: no Nix unit suite and CI skips darwin; `docs/standards/agent-helpers.md` rule 6 (no new English-phrase pins); the bar, "Tests that can fail" | A repo-scan test for `export GITHUB_TOKEN` (pins a spelling, misses `sessionVariables` or a rename); skipping the `eleven-m5` eval (the store edit reaches its oMLX unit and CI never evaluates it) |
