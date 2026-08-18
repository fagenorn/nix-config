# Design: the agent-lifecycle permission surface, declared in Nix

Issue: https://github.com/fagenorn/nix-config/issues/30

Grounding (cited, not re-litigated): `CLAUDE.md` — `~/.claude/settings.json` is generated from the
`settings` attrset in `home/common/claude-code/default.nix` and materialised as a writable copy by an
activation script, so the module is the only supported edit site; `just build` (a successful Nix
evaluation + build) is the **local** verification step and there is no unit-test suite for the Nix
configs, while `Nix Eval` in `.github/workflows/ci.yaml` "is the context `.github/branch-protection.json`
makes required on `main`" and CI does not evaluate `darwinConfigurations.mbp`; "All workflows go through
the `justfile`", which is where `protect-main` / `unprotect-main` / `show-protection` already live.
`~/.agents/standards/the-bar.md` — *Production-grade by default*, *DRY*, *YAGNI*, *Fail loud*,
*Truthful terminal states*, *Defense in depth*, *Verify before claiming done*.
`.out-of-scope/ungated-agent-merges.md` — the standing rejection this issue is the positive half of.
`.claude/specs/2026-08-17-ci-required-check-design.md` — the gate that rejection demanded, its
`enforce_admins: true` decision (its D8), its `show-protection` recipe precedent (its D7), and its
rule that plan gates must be runnable on this host while live checks are ship-time evidence (its
D18). Claude Code 2.1.233 and its current permission/hook reference — permission precedence is
deny → ask → allow, Bash wildcards span arguments, and a blocking `PreToolUse` hook runs before and
overrides an allow rule. Live `git branch -h` — `-f` / `--force` forces deletion when combined with
`-d`. Live `gh pr merge --help` — the target may be a number, URL, or branch and inherited
`-R` / `--repo` selects another repository. This repo has no context map, no ADR tree, and no `docs/` directory; the `docs/areas/*/adr/`
trees under `home/common/agent-skills/evals/fixture-repo/` are eval fixtures, not this project's docs.

## Problem

The Nix-managed global settings declare `permissions.allow = [ ]` alongside `defaultMode = "auto"`.
An empty allow list is not a neutral default here — it is the instruction that *nothing* resolves by
rule. In auto mode a tool call is decided in three steps: an action matching an allow, ask or deny
rule resolves immediately; an unmatched read-only action or in-cwd file edit auto-approves; everything
else goes to a risk classifier. With no rules at all, every lifecycle command an agent runs takes the
third road.

A classifier is a reasonable last resort for an interactive session, where a wrong guess costs one
keystroke. It is the wrong mechanism for the runs this repo actually does. A background agent started
with `claude -p` and no `--permission-prompt-tool` has no prompt to fall back to; and auto mode stops
consulting the classifier and starts prompting after it blocks three times consecutively or twenty
times in a session, neither of which is configurable. Past that threshold, a background agent's
command does not run and cannot be made to run. That is not a permission decision, it is a stall.

The 2026-08-16 orchestration run is the evidence. It lost `gh pr merge`, `git worktree remove`, and
`Agent` dispatch to the classifier, and after escalation it lost read-only `git status` — the same
command, denied on one attempt and allowed on the next, which is the signature of a probabilistic
gate standing in for a policy.

The workaround that accumulated in the meantime does not work either, and the reason is worth
recording because it is the reason this belongs in the Nix module rather than in the project. The
machine-local `.claude/settings.local.json` carries `Bash(gh issue *)` and `Agent`. Project-scope
**allow** rules apply only after workspace trust and are **never** applied under `claude -p` — so the
file is inert for precisely the unattended runs that needed it. It is also untracked and globally
ignored on this machine, so it is not a repo artifact at all: it cannot be reviewed, cannot be
reproduced on a fresh machine, and cannot be the durable home for a policy.

The policy has a home already. The module's own comment invites it: "Add durable global allows here
if wanted." Nothing has taken it up.

## Solution

Populate the Nix-managed global `permissions.allow` with sixteen entries — fifteen narrow Bash rules
plus bare `Agent` — covering the lifecycle surface the issue names. Keep the issue-mandated
`Bash(gh pr merge:*)` spelling, but do not treat that entry as a safety boundary: add one Nix-built,
fail-closed `PreToolUse` guard for Bash that mediates the two argument-sensitive commands before the
permission engine sees them. The guard is the inner policy boundary; the allow entries remove prompts
only after that boundary accepts the exact call.

The guard admits only `git branch -d <valid-single-branch>` and two repository-bound raw merge
grammars: the fixed command without a subject, or the same command with one double-quoted literal
subject. The literal may contain spaces and safe punctuation (including `#()[]{}*?~`) but no double
quote, dollar, backtick, backslash, CR, LF, or NUL.
It rejects force flags, multiple branches, shell expansion/control syntax, omitted/URL/branch PR
targets, alternate repositories, and all other merge flags. Before admitting the merge it also reads
the named PR and live branch protection through absolute Nix-store `gh`/`jq` dependencies and fails
closed unless the PR belongs to `fagenorn/nix-config`, targets `main`, and live protection reports
`Nix Eval` required with `enforce_admins.enabled = true`. The shared `ship-issue` command shape gains
the already-resolved `repoSlug` as explicit `--repo`; no wrapper or second merge authority is added.

Replace the stale permission comment with one that names the guard/allow relationship. Add a
`show-claude-settings` recipe that builds first and prints the generated artifact, failing unless the
system closure contains exactly one generated settings file.

Four properties do the work:

1. **Bash rules resolve before the classifier**, including in auto mode. Bash is not among the
   documented exceptions to immediate rule resolution (those are writes to protected paths and
   organization-`ask` / `requiresUserInteraction` MCP tools). So every Bash entry here converts a
   probabilistic outcome into a deterministic one.
2. **Prefixes are literal**, which forces the rule shapes to be derived from the invocations the
   skills actually type rather than from the tidiest way to write them down.
3. **A blocking `PreToolUse` hook precedes and overrides allow rules.** This is the mechanism that
   makes an argument-sensitive restriction enforceable despite the two mandatory broad prefixes.
4. **The guard fails closed.** A parse error, unsupported shape, missing `gh` response, wrong repo or
   base, API failure, or protection mismatch blocks before Bash. Prose and a later ship-time check are
   evidence, not enforcement.

## Decisions

### Words used precisely

- **Rule** — one string in `permissions.allow`, e.g. `Bash(git status:*)`.
- **Prefix** — the part of a Bash rule before the trailing wildcard. It is matched literally, from
  position 0 of the command line, byte for byte.
- **Shape** — the form of a command line as some caller actually types it, including where its
  arguments sit relative to its flags. `gh pr merge <n> --merge` and `gh pr merge --merge <n>` are two
  shapes of one command, and a prefix matches at most one of them.
- **Reach** — a rule *reaches* a shape when the shape's leading bytes are the rule's prefix. Reach is
  the property the design optimises; presence in the file is not.
- **Guard** — the Nix-built `PreToolUse` policy executable. It receives Claude Code's Bash tool JSON
  on stdin and exits 2 with a reason when the raw command uses either guarded prefix without meeting
  its exact contract. Exit 0 with no decision leaves accepted calls to normal permission evaluation.
- **Residual** — a lifecycle command this list deliberately does not reach, named here so that its
  continued classifier-dependence is a recorded choice rather than an oversight.

### The matcher this list is written against

These are established facts about the permission engine, verified against the current permission
reference and against Claude Code 2.1.233. They are design constraints, not open questions.

- `Bash(<prefix>:*)` and `Bash(<prefix> *)` are the same rule: a trailing wildcard. A trailing `*`
  with a preceding space enforces a word boundary — `Bash(ls *)` reaches `ls -la` but not `lsof`.
  Consequently `Bash(gh pr view:*)` reaches bare `gh pr view` and `gh pr view 123`, and not
  `gh pr viewfoo`.
- Without the wildcard a rule is an **exact** match. `Bash(gh pr view)` does not reach
  `gh pr view 123`. Every entry in this list therefore carries the wildcard.
- `*` may appear at any position and **matches across spaces**. This is what makes mid-position
  wildcards unsafe here rather than merely imprecise — see *What this list deliberately does not
  reach*.
- Matching is **case-sensitive** and performs **no flag normalisation**. That excludes the spelling
  `git branch -D`, but it does **not** make `Bash(git branch -d:*)` safe: Git also accepts
  `git branch -d -f <branch>` and `git branch -d --force <branch>`. The guard, not case, closes that
  path.
- Evaluation order across the merged rule set is deny → ask → allow, first match wins; specificity
  does not reorder anything. Arrays **union** across settings scopes rather than override, so a deny
  at any scope beats an allow at any other.
- `timeout`, `time`, `nice`, `nohup`, `stdbuf`, `command`, `builtin`, `noglob` and bare `xargs` are
  stripped before matching; environment-runner wrappers are not. No rule here has the shape
  `Bash(<runner> *)`, which would grant whatever the runner runs.
- There is **no rule-string linter**, and a malformed *allow* rule produces no startup warning — it
  silently never matches. This is the failure mode the design and the verification are built around.

### The allow list

Sixteen entries, in three groups plus the tool entry. Every Bash entry is a one-subcommand prefix
terminated by `:*`.

Read-only git and tracker queries:

| Rule | Shapes it reaches (evidence from the skills) |
|---|---|
| `Bash(git fetch:*)` | `git fetch origin` |
| `Bash(git status:*)` | `git status`, `git status --porcelain`, `git status --short` |
| `Bash(git log:*)` | `git log --oneline <range>`, `git log --no-merges BASE..HEAD ^origin/<b>`, `git log --format=…` |
| `Bash(git diff:*)` | `git diff --stat`, `git diff -U0`, `git diff --numstat -z -M`, `git diff --check <range>` |
| `Bash(gh pr view:*)` | `gh pr view`, `gh pr view <n> --json …` |
| `Bash(gh pr list:*)` | `gh pr list --state …` |
| `Bash(gh pr checks:*)` | `gh pr checks <n>`, `gh pr checks <n> --watch` |
| `Bash(gh issue view:*)` | `gh issue view <n> --json …` |
| `Bash(gh issue list:*)` | `gh issue list …` |

Worktree lifecycle:

| Rule | Shapes it reaches |
|---|---|
| `Bash(git worktree add:*)` | `git worktree add -b <branch> <path> origin/<integration-branch>` |
| `Bash(git worktree list:*)` | `git worktree list`, `git worktree list --porcelain` |
| `Bash(git worktree remove:*)` | `git worktree remove <path>`, `git worktree remove --force <path>` |
| `Bash(git worktree prune:*)` | `git worktree prune` |
| `Bash(git branch -d:*)` | `git branch -d <branch>` |

Merge, admissible only behind the CI gate:

| Rule | Shapes it reaches |
|---|---|
| `Bash(gh pr merge:*)` | Guarded shape only: `gh pr merge <n> --repo fagenorn/nix-config --merge [--subject "…"] --delete-branch` |

Tool dispatch:

| Rule | Note |
|---|---|
| `Agent` | Inert under `defaultMode = "auto"`. See *The `Agent` entry*. |

The `:*` spelling is used throughout rather than the equivalent ` *`: it is the form the issue's own
acceptance criterion names verbatim, and it makes the rule's two parts — prefix and wildcard —
visually separate.

### Why each risky member is admissible

**`Bash(gh pr merge:*)` — mandatory, broad, and never trusted alone.** The issue requires this exact
entry, and `ship-issue` puts the PR argument before its flags, so a superficially narrower prefix such
as `Bash(gh pr merge --merge:*)` would be inert. Live help proves the mandatory entry also reaches
`--admin`, `-R` / `--repo`, URL targets, branch targets, and PRs whose base is not protected `main`.
The old claim that `main`'s server gate makes every command under the prefix safe is therefore false.

The `PreToolUse` guard closes the gap before permission evaluation. It accepts one positive decimal
PR number, the explicit repository binding, merge-commit strategy, optional literal subject, and
branch cleanup; every other token blocks before Bash. It then resolves that number explicitly in
`fagenorn/nix-config` and requires `baseRefName == "main"`. Finally it reads the **live** protection,
not merely the committed desired-state JSON, and requires both `Nix Eval` and
`enforce_admins.enabled == true`. Only then may the direct allow resolve the call. The server remains
the enforcement for CI completion; the guard enforces that the command actually targets the server
boundary the sibling issue established.

There is intentionally no wrapper around `gh pr merge`. A wrapper plus the mandatory direct allow
would leave the unsafe direct route open; denying the direct route would make the mandatory allow
dead and fail the issue's intent. One guard around the real command gives the required entry a usable,
enforceable subset without creating a second merge interface.

### The guard contract

The guard is one store-backed executable referenced by one `PreToolUse` matcher for `Bash`. Running
it for all Bash calls avoids a blind spot in an argument filter: Claude Code can split compound
commands for permission matching, while the hook receives the original raw command. Its contract is:

1. Read exactly one hook JSON object from stdin and require `tool_name == "Bash"` plus a string
   `tool_input.command`; malformed input blocks rather than falling through.
2. If the raw command contains neither literal guarded prefix, return no decision. The guard does
   not become a second classifier for unrelated Bash calls.
3. If the branch prefix occurs, reject shell control, expansion, redirection, globbing, comments,
   newlines, wrappers, or a second command before tokenising. If the merge prefix occurs, require one
   of these two complete raw grammars before tokenising (spaces shown are single ASCII spaces):

   ```text
   PR            = [1-9][0-9]*
   SUBJECT_CHAR  = any Unicode scalar except U+0022 (") U+0024 ($) U+0060 (`)
                   U+005C (backslash) U+0000 (NUL) U+000A (LF) U+000D (CR)
   NO_SUBJECT    = gh pr merge PR --repo fagenorn/nix-config --merge --delete-branch
   WITH_SUBJECT  = gh pr merge PR --repo fagenorn/nix-config --merge --subject
                   U+0022 SUBJECT_CHAR+ U+0022 --delete-branch
   ```

   This full-command grammar permits literal punctuation inside the quoted subject without letting
   it become shell syntax. After the raw match, tokenise with `shlex` without evaluation and validate
   the resulting vector again; never pass the raw string to a shell.
4. For branch deletion, require the exact token vector `[git, branch, -d, <branch>]`, reject a value
   beginning with `-`, and validate the value with `git check-ref-format --branch` invoked by argv.
5. For merge, require the fixed ordered vector `gh pr merge <positive-decimal> --repo
   fagenorn/nix-config --merge`, then either `--delete-branch` or `--subject <one-token-literal>
   --delete-branch`. Resolve the PR by number with explicit `--repo`, require an open PR whose base is
   `main`, then require the live protection predicates above. Invoke every child command by argv from
   an absolute Nix-store path.
6. Register the command hook with an explicit 30-second timeout and give every child subprocess a
   5-second timeout. Claude's hook contract makes **only exit 2 blocking**; any other exit, including
   the framework killing a timed-out hook, proceeds to permission evaluation. Therefore child
   timeout, child nonzero, invalid JSON, a false predicate, and every ordinary rejection all print
   one actionable reason and return 2. One outer `except Exception` is the final fail-safe: it prints
   an actionable unexpected-failure reason and returns 2. The 30-second hook budget leaves headroom
   above the bounded child calls; it is not itself the safety mechanism. On acceptance, exit 0 with
   no permission decision so the mandatory allow rule, rather than the hook, grants the call.

The blocking semantics above are the current official Claude Code contract: a blocking
`PreToolUse` command hook runs before an allow, but only process exit 2 blocks; other exits and hook
timeouts are non-blocking ([hooks reference](https://code.claude.com/docs/en/hooks),
[permissions reference](https://code.claude.com/docs/en/permissions)).

This is deliberately a strict language, not an attempted shell parser. The one emitted branch shape
and one emitted merge shape are small enough to enumerate; rejecting any other spelling is both
safer and more maintainable than trying to prove arbitrary shell text equivalent.

Three options were evaluated:

- **Chosen — guard the real commands.** `PreToolUse` is the framework-provided seam that can narrow a
  direct allow, including argument and live-state checks, before execution.
- **Rejected — deny-pattern overlays.** Deny wins over allow, but a finite set for `-f`, `--force`,
  option order, URL/branch targets, and `-R` variants still cannot express “this PR's base is main”;
  Bash wildcard argument filters are explicitly documented as fragile.
- **Rejected — wrapper-only commands.** A wrapper can validate well, but the mandatory
  `Bash(gh pr merge:*)` remains a direct bypass unless a guard or deny also mediates it. A wrapper
  therefore adds an interface without removing the hard part.

**`Bash(git worktree remove:*)` — reaches `--force`, and is still bounded.** `git worktree remove`
deletes a worktree directory and its administrative entry. It does not delete the branch, and it does
not touch commits: anything committed on the branch survives and remains reachable. Branch deletion is
a separate command with its own, much narrower rule. `--force` widens what the command tolerates
(a dirty tree), not what it destroys beyond the working copy.

**`Bash(git branch -d:*)` — the prefix is broader than the safe Git operation.** `-d` refuses an
unmerged branch only in the absence of force. Live help documents `-f` / `--force` as forcing
creation, move, rename, **and deletion**, and Git accepts `git branch -d -f <branch>`. The guard admits
exactly four shell words — `git`, `branch`, `-d`, and one value accepted by
`git check-ref-format --branch` that does not begin with `-` — with no expansion, redirection,
operator, wrapper, second branch, or extra flag. `-D`, `-d -f`, `-d --force`, and rearrangements stay
outside the pre-authorized subset.

**`Bash(git fetch:*)` — one honest residual.** `git fetch` is read-only with respect to the working
tree and to every remote, but a forced refspec (`git fetch origin +main:main`) can force-update a
*local* ref. That is a real widening and it is accepted: the issue names `git fetch` in the read-only
group, the shape the skills use is `git fetch origin`, and the damage is bounded by what is absent —
there is no `push` rule, so nothing pre-authorized can propagate a rewritten local ref to a remote.

**`Bash(git diff:*)` and `Bash(git log:*)` — bounded by the negative criteria, which is the point.**
Both accept `--ext-diff`, which runs whatever `diff.external` names. No entry in this list
pre-authorizes writing git configuration or editing under `.git/**`, so no *pre-authorized* path sets
`diff.external`. This is defense in depth working as intended rather than a proof of impossibility: a
classifier-approved write remains possible, and the claim is precisely that the allow list adds no
shortcut to it. `git diff --output=<file>` can also write a file, which is a bounded side effect, not
a privilege escalation.

### What this list deliberately does not reach

Naming these is not throat-clearing. Each is a lifecycle command that will keep meeting the
classifier after this change lands, and a reader who expects "the allow list fixed the denials" needs
to know which denials it did not fix.

- **R1 — `git -C <path> <subcommand>`.** This is the dominant shape in the review, diff-scope and
  Codex scratch-clone helpers: eighteen `git -C "$WORKTREE" diff`, four `git -C "$WORKTREE" status`,
  and many `git -C "$SCRATCH" add|apply|reset|checkout|clean`. A literal prefix starting at position 0
  cannot reach any of them. The only rule form that could is a mid-position wildcard, and it is not
  merely imprecise — it is unsafe: because `*` matches across spaces, `Bash(git -C * status:*)` also
  reaches `git -C /repo push origin status`, which breaks the issue's negative criterion outright.
  The shape stays unreached, deliberately. Most of those calls are writes far outside this issue's
  surface anyway.
- **R2 — compound invocations.** A rule matches one command line. `git diff --numstat "$(git
  merge-base HEAD origin/main)"` and `git worktree list | grep …` decompose, and every constituent
  needs its own resolution; `git merge-base` and `grep` are outside the surface the issue names, so
  those calls still reach the classifier even though their outer command is allowed.
- **R3 — `git branch -D`.** `from-issue`'s provably-disposable-worktree deletion uses it. It stays
  classifier-gated by the issue's explicit negative criterion, and independently by
  `skills/worktrees/SKILL.md`, which forbids `git branch -D` as a repair alongside `git reset --hard`
  and `git clean -fdx`. Excluding it is consistent with an invariant this repo already holds, not just
  with this issue's wording.
- **R4 — `git push`, `gh pr create`, `gh issue close`.** All are part of `ship-issue`'s authorized
  chain and none is named by this issue.
- **R5 — `Agent`.** See below.
- **R6 — an unquantified risk that some Bash entries are dropped too.** The auto-mode drop is
  specified by *category*, not by enumeration: blanket `Bash(*)`, wildcarded interpreters such as
  `Bash(python*)`, package-manager run commands, and `Agent` rules, with "narrow rules like
  `Bash(npm test)` carry over". None of the fifteen Bash entries here is in a named category — each is
  a one-subcommand prefix over `git` or `gh`, neither of which is an interpreter or a package manager.
  But "grants arbitrary code execution" is a description a future engine version could read more
  widely than today's, and `git diff --ext-diff` is a live example of a nominally read-only command
  that runs a configured program. This cannot be settled by reading the file, only by watching a real
  run — which is why the live demo is a required seam rather than a courtesy.

### The `Agent` entry

On entering auto mode, allow rules that grant arbitrary code execution are dropped: blanket `Bash(*)`
or `PowerShell(*)`, wildcarded interpreters such as `Bash(python*)`, package-manager run commands, and
**`Agent` allow rules**. They are restored on leaving auto mode. The documentation does not
distinguish bare `Agent` from `Agent(<type>)`.

This repo runs `defaultMode = "auto"`. The `Agent` entry is therefore **inert as shipped**, and the
issue's expectation that it fixes the denied delegate dispatches is not met by this change.

It is still included, and it is written bare.

Included, because the alternatives are worse. Omitting it silently would drop a bullet the issue names
without saying so. Omitting it loudly would still leave the entry absent when the mode changes or when
a session runs in plan or default mode, where the rule is correct and does resolve. It costs one line
and no risk. What is not acceptable is shipping it *quietly* — so the module comment records the drop
at the entry, and the gap is raised as a discussion item on the issue rather than left for the author
to discover from behaviour.

Bare rather than `Agent(<type>)`, because the spelling of a plugin-namespaced agent type inside an
`Agent(...)` rule — this repo has `codex:codex-rescue` and `codex:codex-reviewer` — is not addressed
by the documentation, and an unspellable rule silently never matches. Bare sidesteps an unknown that
would otherwise be resolved by guessing, and it is the form the machine-local workaround already used.

Changing `defaultMode` is the real fix and is a different decision with a much larger blast radius
than this issue's. It stays out.

### Inspecting the generated artifact

`settingsFile` is a `let`-bound store path inside the module, not a flake output, so "inspect the
generated settings artifact" needs a route. The obvious one does not work, and it fails in the way
that matters most — silently plausible until the content changes:

```
nix eval --raw '.#darwinConfigurations.mbp.config.home-manager.users.anis.home.activation.claudeCodeSettings.data'
```

prints the activation script, which contains the `/nix/store/…-claude-code-settings.json` path. But
`nix eval` does not register a deriver for it, so once the settings content changes, that path is not
buildable by name: `nix-store --realise` on it answers `don't know how to build these paths`. This was
reproduced in this worktree by editing `allow` and re-evaluating. An eval-then-realise recipe would
work on every machine where the file happened to be built already and fail on every other one, which
is precisely the class of verification this design is trying to avoid.

The route that works reuses the build the repo already requires. `just build` produces `./result` on
both platforms, and the settings file is a requisite of the system closure:

```
just build
nix-store --query --requisites ./result | grep -- '-claude-code-settings\.json$'
```

Verified in this worktree: the grep returns exactly one path, and it is byte-identical to the path the
activation script names.

This is packaged as a `just` recipe, because `CLAUDE.md` says all workflows go through the justfile and
because the sibling CI work established the pattern one issue earlier with `show-protection` — a
read-only "print the live thing" recipe added alongside the change it verifies. The recipe **depends on
`build`**, which is not tidiness: a `./result` left over from an earlier build would make the recipe
print stale settings and report them as current, which is a false success (*Truthful terminal states*).
Because the dependency resolves through `just`'s platform gating to whichever `build` recipe is enabled,
one ungated recipe serves both hosts — no `[macos]`/`[linux]` pair, no username in an attribute path,
and nothing that breaks when `vars/default.nix` changes the username.

```
# Print the Nix-generated ~/.claude/settings.json exactly as the next switch will write it.
show-claude-settings: build
  @set -- $$(nix-store --query --requisites ./result \
    | grep -- '-claude-code-settings\.json$' || true); \
    if [ "$$#" -ne 1 ]; then \
      echo "expected exactly one generated Claude settings artifact; found $$#" >&2; \
      exit 1; \
    fi; \
    cat "$$1"
```

Store paths cannot contain shell whitespace, so positional parameters are a portable exact-count
check on both supported hosts. Zero and multiple matches fail loudly; only one path reaches `cat`.

### The comment block, and what `CLAUDE.md` gains

The comment above `permissions` currently explains why the allow list is *empty* ("the large
project-specific allow-list from the old settings.json was accumulated state, not a durable global
baseline, so it is deliberately dropped. Add durable global allows here if wanted."). That sentence
becomes false the moment this change lands, and it is the first thing the next editor reads.

It is replaced by a comment that states what the list is (the agent-lifecycle surface, one narrow rule
per subcommand), that the two argument-sensitive prefixes are safe only through the adjacent
`PreToolUse` guard, and that malformed rules or hooks can fail silently. The `Agent` entry retains its
auto-mode note. Rationale lives next to the line it explains; the analysis lives here.

`CLAUDE.md` gains two small things, both in places that already carry this kind of note: `just
show-claude-settings` in the Commands block, and one sentence in the existing claude-code bullet list
recording that `permissions.allow` plus its guard form the declared agent-lifecycle surface, that the
merge subset is repo/base/protection-bound, and that changes are checked through the built artifact
rather than by reading the diff.

## Test seams

Four seams, at the highest observable boundaries available:

1. **The generated settings artifact** — `just show-claude-settings` must emit one JSON document and
   fail unless the closure contains exactly one candidate. Assert the sixteen allow strings, the
   `Bash` `PreToolUse` matcher, and the store-backed guard command from this artifact, not Nix source.
2. **The guard executable named by that artifact** — feed hook JSON fixtures directly. Exact safe
   branch deletion returns 0; `-d -f`, `-d --force`, multiple branches, shell composition and malformed
   input exit 2. Wrong-repo, URL/branch/omitted PR targets, `--admin`, alternate strategies and shell
   expansion exit 2 before any network call. Explicit test-only argv overrides replace store-pinned
   child executables only when the test invokes the guard; the registered production command passes
   no overrides. Registration tests assert both that no args are present and that the command text
   contains no override flag. Deterministic fixtures cover PR/protection child nonzero and timeout, invalid JSON,
   wrong repo/base/state, missing `Nix Eval`, and `enforce_admins` false. These are table-driven
   contract cases, not source regexes. A positive fixture admits `feature (#30) [guarded]*?~`; quoted
   subjects containing dollar, backtick, backslash, embedded quote, or newline exit 2.
3. **`just build` exit 0** — the repository's required local verification. The settings and guard are
   both in the resulting closure, so the first two seams inspect what the next switch will install.
4. **Ship-time live evidence** — after a requested switch, a background subagent demonstrates the
   read-only/worktree calls without a prompt. A guarded merge dry-run is not available, so invoke the
   guard directly with a real open PR number and record that it admits only when the PR base and live
   protection predicates hold; the actual merge remains the ship workflow's server-gated operation.

The local contract fixtures prove the new safety boundary without mutating a branch or PR. The live
check proves the two external facts no offline fixture can: current PR metadata and applied protection.

## Acceptance criteria

Restated so each names the command that decides it.

1. **The generated settings contain the lifecycle allow rules, including `Bash(gh pr merge:*)`.**
   Decided by `just show-claude-settings | jq -r '.permissions.allow[]'` listing exactly the sixteen
   entries above. Baseline: at the base commit the list is empty, so the diff is unambiguous.
2. **The allow list contains no rule matching `git config`, `.git/` edits, `branch -D`, or `push`.**
   Decided by the same output: no entry contains `config`, `.git`, `branch -D`, or `push`, and no
   entry is `Bash(*)` or a wildcarded interpreter. Guard fixtures additionally prove that the
   `git branch -d` entry does not pre-authorize Git's force flags.
3. **Argument-sensitive direct allows are narrowed before execution.** The built settings contain
   the Bash `PreToolUse` guard; its fixtures prove unsafe branch and merge shapes exit 2, and the live
   merge fixture proves repo/base/protection validation fails closed.
4. **The flake still builds.** `just build`, exit 0.
5. **(Ship-time, evidence not gate.)** After a switch, a background subagent removes a scratch
   worktree and runs `gh pr view` with no permission denial.

## Out of scope

- **Changing `defaultMode`.** It is the only thing that would make the `Agent` entry live, and it
  changes the decision path for every tool call in every session. A different issue.
- **`ask` and `deny` entries.** Both stay empty. `.git/**` is already a protected path that
  `permissions.allow` cannot pre-approve writes to, so an `Edit(.git/**)` deny would be redundant; and
  the tempting `Bash(git config:*)` deny would be actively harmful — a deny at any scope beats an
  allow at any other, and `home/common/agent-skills/evals/run-eval.sh` runs `git -C "$REPO" config` to
  set up its sandboxed fixture repo, so the deny would break `just evals` while still missing
  `git -C <path> config` and `git config --global` from the other direction. A rule that blocks the
  legitimate call and misses the hazard is worse than no rule.
- **Cleaning up `.claude/settings.local.json`.** It is untracked and globally ignored on this machine,
  so it is not a repo file and no commit can remove it. It is also harmless once the global list
  lands: allow arrays union across scopes, so its two entries add nothing the global list does not
  already carry, and its project-scope allows were never applied under `claude -p` in the first place.
  Deleting it is a one-line local action for the operator, not a change this issue ships.
- **Any change to the CI gate**, whose design and rollout are the sibling issue's.
- **Widening to any command the issue does not name** — `git merge-base`, `grep`, `git -C …`,
  `git push`, `gh pr create`, `gh issue close`. R1–R4 record them as residuals; a follow-up issue can
  weigh them on evidence from the next orchestration run.
- **A source-text test that parses the Nix.** The built JSON and its referenced guard executable are
  the public seams. Parsing Nix source would add a second, fragile authority without exercising what
  Claude Code installs.

## Discussion items for the issue thread

- The `Agent` bullet in the issue is not satisfied by this change: `Agent` allow rules are dropped in
  auto mode. Delegate dispatch remains classifier-gated until `defaultMode` changes or the engine
  stops dropping the rule. Raising this is part of shipping the issue, not a footnote.
- R1 (`git -C <path> …`) is the largest remaining source of classifier non-determinism for the review
  and Codex helpers, and it has no safe rule form. If it keeps costing runs, the fix is to change the
  *callers* to `cd` into the worktree rather than to widen the rule.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Ship the `Agent` entry, written **bare**, with the auto-mode drop recorded in the module comment and raised as a discussion item on the issue — and do **not** change `defaultMode` | The engine drops `Agent` allow rules on entering auto mode and restores them on leaving, so the entry is inert as shipped but correct in plan/default mode; the issue names it explicitly. Bare avoids the one genuine unknown — how a plugin-namespaced type (`codex:codex-reviewer`) is spelled inside `Agent(...)` — where a wrong spelling would silently never match. *Truthful terminal states*: an inert entry must not be presented as a working one | Omit it silently (drops a named requirement with no record); ship it silently (the author reads a working entry into an inert one); change `defaultMode` to make it live (alters the decision path for every tool call in every session — a different issue's blast radius) |
| D2 | One narrow rule per subcommand, prefix terminated by `:*`, sixteen entries; no coarser `Bash(git worktree:*)` or `Bash(gh pr:*)` form | Multi-word prefixes scope tightly — with only `Bash(git worktree add:*)` allowed, `git worktree remove` is denied before git runs — so the narrow form is what makes the negative criteria enforceable at all. A coarse `Bash(git worktree:*)` would be one edit away from admitting anything git's worktree porcelain grows next; a coarse `Bash(gh pr:*)` would admit `gh pr close` and `gh pr create`, neither named by the issue. *YAGNI* | Group by command (`Bash(git worktree:*)`, `Bash(gh pr:*)`) — four fewer lines, and it silently pre-authorizes every present and future subcommand of two porcelains |
| D3 | `Bash(git branch -d:*)` only: no `--delete` long form, and no `--no-pager` or `-C` variants of the read-only commands | The one call site is `skills/ship-issue/SKILL.md`'s post-merge `git branch -d <branch>`; nothing in the tree types `--delete` or `git --no-pager`, and git disables its pager on a non-tty anyway, so both would be rules with no caller — dead weight that dilutes review of the ones that matter (*YAGNI*). The `-d`-only choice is also what makes the "no `branch -D`" criterion hold by construction: matching is case-sensitive with no flag normalisation, so `-d` **cannot** reach `-D` | Add `Bash(git branch --delete:*)` and pager-safe variants for symmetry (four entries no caller invokes); allow `git branch -D` for `from-issue`'s disposable-worktree path (contradicts the issue's negative criterion and `skills/worktrees/SKILL.md`, which forbids `-D` as a repair) |
| D4 | Verification runs `just build` then greps the **system closure** — `nix-store --query --requisites ./result \| grep -- '-claude-code-settings\.json$'` — rather than evaluating the activation script and realising the path it names | Verified in this worktree, both directions: the closure grep returns exactly one path identical to the one the activation script names, and the eval-then-realise route **fails** once the settings content changes (`nix eval` registers no deriver; `nix-store --realise` answers `don't know how to build these paths`, reproduced by editing `allow`). The failing route would have worked on any machine where the file was already built and failed on every other, which is the exact class of verification this change exists to eliminate. Reusing `./result` also costs nothing, since AC3 already requires the build | Eval the activation script's `data` and realise the extracted path (verified broken for changed content — the single most likely thing to be wrong at execute time); build `…home-manager.users.anis.home.activationPackage` instead (works, but hardcodes the username into an attribute path, contradicting `CLAUDE.md`'s "change the username in one place and it propagates") |
| D5 | Package that command as an ungated `just show-claude-settings` recipe that **depends on `build`** | `CLAUDE.md`: "All workflows go through the `justfile`", and the sibling CI spec's D7 set the precedent one issue earlier with `show-protection` — a read-only "print the live thing" recipe shipped alongside the change it verifies. The `build` dependency is correctness, not tidiness: a stale `./result` would make the recipe print superseded settings and report them as current (*Truthful terminal states*). Verified on this host that `just`'s platform gating resolves the dependency to the enabled `build` — the mechanism is the same attribute gating the existing `trace`/`switch` recipes already depend through — so one ungated recipe serves both hosts with no username and no `[macos]`/`[linux]` pair | Leave the command in the spec only (nobody editing the allow list later finds it; *DRY* — the inspection contract gets no home); write `[macos]`/`[linux]` variants against the home-manager attribute path (two recipes, a hardcoded username, and a linux variant unverifiable from this host) |
| D6 | `.claude/settings.local.json` is left alone, and the reason is recorded rather than assumed | It is untracked and globally ignored on this machine (`~/.config/git/ignore`), so it is not a repo file and no commit can remove it. It is also harmless: allow arrays **union** across scopes, so its `Bash(gh issue *)` and `Agent` add nothing the global list will not carry — and project-scope allows are never applied under `claude -p`, which is why it never fixed the background runs it was written for | Delete it as part of this issue (a commit cannot; the file is outside git); declare it obsolete in `CLAUDE.md` (documents a file the repo does not contain) |
| D7 | No new test file and no new entry in `just agent-workflow-tests`; the seams are the built artifact, `just build`, and the issue's live demo as ship-time evidence | The property that matters — that a rule *matches* — is not checkable offline: there is no rule linter and a malformed allow rule produces no warning, so any offline test would pin well-formedness while the real failure sailed past. A Python regex over Nix source would also create a second, fragile authority for rule shape (*DRY*) to catch negative criteria that are legible directly in a sixteen-line diff. The sibling CI spec added a test because its failure — a context/job-name mismatch — was invisible *and* mechanically checkable; here only the first half holds | Add `tests/test_claude_permissions.py` asserting the rule grammar and the four forbidden predicates (pins the checkable half of the invariant, at the cost of a fragile Nix-source parser and a false sense that the list is verified); assert on the `.nix` source instead of the built JSON (tests the input, not what Claude Code reads) |
| D8 | Rewrite the comment above `permissions` and add two notes to `CLAUDE.md`: the recipe in the Commands block, one sentence in the claude-code bullet list | The existing comment ("the allow-list … is deliberately dropped. Add durable global allows here if wanted") becomes false at the commit that lands the list, and it is the first thing the next editor reads — *Production-grade by default*. Per-entry conditions belong beside their entries (*comments say why*), and the durable operator-facing facts belong where `CLAUDE.md` already documents this module's conventions | Leave the comment (ships a knowingly false sentence in the file being edited); put the whole analysis in the comment (duplicates the spec into source, where it rots); skip `CLAUDE.md` (the recipe and the merge/gate coupling have no discoverable home) |
| D9 | `Bash(gh pr merge:*)` is prefix-only, accepting that `--admin` is reachable, and the module comment states that the entry must be removed if `main`'s protection or `enforce_admins` is | `ship-issue` types `gh pr merge <pr-num> --merge --subject "…" --delete-branch` — argument before flags — so a `--merge`-bearing prefix would never match; it would be a rule that reads safer and does nothing. `--admin` is defused by `enforce_admins: true` in `.github/branch-protection.json`, under which the sibling spec established and its plan verified that `gh pr merge --admin` is refused until `Nix Eval` is green. That is exactly the disposition `.out-of-scope/ungated-agent-merges.md` demanded: safety from a required check, not from the classifier | `Bash(gh pr merge --merge:*)` (never matches the shape ship-issue types — inert, and it hides the question of what really gates the merge); leave `gh pr merge` out until the coupling is machine-checked (the gate is live and the issue is unblocked; the coupling is what the comment and this row are for) |
| D10 | R1–R5 are named as residuals in the spec rather than closed by widening the list — in particular, no mid-position wildcard for the pervasive `git -C <path> <sub>` shape | `*` matches across spaces, so the only rule that would reach `git -C "$WORKTREE" status` — `Bash(git -C * status:*)` — also reaches `git -C /repo push origin status`, breaking the issue's negative criterion outright. A residual that is named is a recorded choice; an unnamed one reads as a fixed problem that quietly is not (*Production-grade by default*: known limitations belong in docs). The right fix for R1 is to change the callers to `cd`, not to widen the rule | Add `Bash(git -C * <sub>:*)` rules to cover the dominant real shape (demonstrably admits `git push`); say nothing and let the next orchestration run rediscover the denials (the issue's premise becomes untrue in a way nobody wrote down) |
| D11 | Move the two `build` recipes' progress banner to **stderr** (`@echo "…" >&2`, macos and linux) in the same commit that adds `show-claude-settings`; the recipe body itself lands exactly as *Inspecting the generated artifact* writes it | Verified at plan time against the **real** justfile rather than a scratch copy of the recipe alone: `@echo` writes to stdout, so `just show-claude-settings` emitted `Building nix-darwin config...` as its first line and this spec's own AC1 command — `just show-claude-settings \| jq -r '.permissions.allow[]'` — died with `jq: parse error: Invalid numeric literal at line 1, column 9`. With the redirect that command succeeds, the first byte of stdout is `{`, and the banner still reaches the terminal on stderr (`just build 2>&1 >/dev/null` still shows it). Nothing parses `just build`'s stdout, and `trace`/`switch` depend on `build` unchanged. An acceptance criterion whose named command cannot run is not a criterion | Leave `build` alone and strip the banner at every call site (`\| tail -n +2`, `\| sed -n '/^{/,$p'`) — bakes a workaround into the documented command and breaks the moment the banner changes; drop the `build` dependency and run `just build >&2` inside the recipe body (stdout stays clean, but it re-enters `just` from a recipe and hides the dependency from `--dry-run`, contradicting D5) |
| D12 | Keep the recipe body's `grep … \| xargs cat` shape with no fail-loud guard for the zero-match case | Verified on this host that with no matching requisite the pipeline exits 0 and prints nothing — so a future refactor that drops the settings file from the closure would make a bare `just show-claude-settings` succeed silently. Every assertion that consumes it nonetheless fails closed: `jq -e '.permissions.allow \| length == 16'` exits 4 on empty input and 1 on a false result (both verified). A portable guard would restructure a body this spec fixes, for a failure mode the gate already catches (*YAGNI*) | Add `set -o pipefail` or an explicit count check to the recipe (restructures the fixed body and depends on which `sh` `just` invokes on each platform); accept the silent empty print as the recipe's only signal (a false success — the exact class of verification D4 exists to eliminate) |
| D13 | **Reverses D3 and D9:** keep the two issue-mandated allow strings, but narrow them with one fail-closed Bash `PreToolUse` guard; branch deletion admits one validated branch and no extra flag, while merge admits only a numeric PR, explicit `repoSlug`, merge strategy, optional literal subject and delete-branch after verifying repo, `main` base, `Nix Eval`, and live `enforce_admins` | Live `git branch -h` proves `-d -f` forces deletion; live `gh pr merge --help` proves the broad entry reaches alternate repos and URL/branch targets; Claude Code 2.1.233 documents that a blocking `PreToolUse` hook runs before and overrides allow. `.out-of-scope/ungated-agent-merges.md` requires the accepted merge to terminate at the server gate, not merely resemble the intended command | Rely on case-sensitive `-d` and `main` protection (both reviewer-disproved); overlay finite deny globs (cannot express PR base/live state and argument filters are fragile); wrapper only (mandatory direct allow bypasses it); declare the issue inconsistent (unnecessary because the hook supplies an enforceable inner boundary) |
| D14 | **Reverses D7:** test the built guard as a table-driven stdin/exit contract in addition to inspecting the generated JSON; keep external PR/protection confirmation as ship-time evidence | *Defense in depth*, *Tests that can fail*, and *Verify before claiming done*: the guard is now executable policy, so presence in JSON is not evidence that force/repo/base cases block. Direct fixture invocation exercises the installed seam without destructive Git or GitHub actions | Retain artifact-only verification (would prove the unsafe allow and the guard are present, not which wins); parse Nix source (tests the input rather than installed behavior) |
| D15 | **Reverses D11's fixed body and D12:** `show-claude-settings` counts closure matches and exits nonzero unless there is exactly one before `cat` | Standards reviewer finding plus *Truthful terminal states* and *Fail loud*: `grep \| xargs cat` exits 0 and prints nothing on zero matches, so the named inspection command can falsely succeed. Store paths contain no shell whitespace, making positional-parameter counting portable here | Keep the old pipeline because downstream `jq` fails (the recipe itself still lies); add only `pipefail` (does not reject multiple matches and is shell-dependent) |
| D16 | Build the guard as one Nix-store Python executable using stdlib JSON/`shlex`/`subprocess`, with absolute store paths for `git`, `gh`, and `jq`; its stdlib contract test accepts the generated settings JSON path and invokes the command registered there | D13 requires tokenisation without evaluation and argv-only child execution, while D14 requires testing the built executable rather than Nix source. Python's stdlib provides both without adding a flake input, and resolving the executable through generated settings tests the hook registration and policy together | A shell parser (quote handling and token boundaries become security-sensitive); a separately named guard path in the test (could pass while the installed hook points elsewhere); wiring the built-artifact test into `agent-workflow-tests` (would make the otherwise fast suite implicitly build a host closure) |
| D17 | Make fail-closed behavior explicit at both timeout layers: register a 30-second command-hook timeout, cap every child at 5 seconds, and route every rejection, child failure/timeout, parse/predicate failure, and unexpected exception to exit 2; expose dependency paths and a shorter child timeout only as test argv overrides, while the installed hook passes no arguments | Official Claude hooks contract: only exit 2 blocks; non-2 exits and hook timeout continue to permission evaluation. *Defense in depth* and *Tests that can fail* require deterministic coverage of external-boundary failures without weakening the store-pinned production command | Rely on the framework timeout (it is non-blocking); catch only expected subprocess errors (an uncaught parser/runtime error exits non-2); PATH injection or environment-only dependency substitution (could affect production semantics and does not prove the registered command is store-pinned) |
| D18 | Replace the merge-wide metacharacter blacklist with two full raw grammars, allowing a nonempty double-quoted subject to contain spaces and literal safe punctuation while excluding quote/expansion/escape/newline bytes; `ship-issue` emits the quoted subject only when representable and otherwise omits `--subject` so the forge default stands | Final reviewer found the global blacklist rejected the normal rendered subject `feature (#30)`, conflicting with the required ship command. A full-command grammar fixes compatibility without making punctuation outside the quote executable, and post-match `shlex` plus vector validation retain defense in depth | Keep the blacklist (breaks common merge subjects); allow arbitrary quoted shell text (reopens expansion/escape paths); fail shipping on an unrepresentable title (the forge already has a safe default subject, so omission is the smaller reversible fallback) |
