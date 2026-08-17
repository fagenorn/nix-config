# Design: the agent-lifecycle permission surface, declared in Nix

Issue: https://github.com/fagenorn/nix-config/issues/30

Grounding (cited, not re-litigated): `CLAUDE.md` — `~/.claude/settings.json` is generated from the
`settings` attrset in `home/common/claude-code/default.nix` and materialised as a writable copy by an
activation script, so the module is the only supported edit site; verification for this repo is
`just build` (exit 0); "All workflows go through the `justfile`".
`~/.agents/standards/the-bar.md` — *Production-grade by default*, *DRY*, *YAGNI*, *Fail loud*,
*Truthful terminal states*, *Defense in depth*, *Verify before claiming done*.
`.out-of-scope/ungated-agent-merges.md` — the standing rejection this issue is the positive half of.
`.claude/specs/2026-08-17-ci-required-check-design.md` — the gate that rejection demanded, its
`enforce_admins: true` decision (its D8), its `show-protection` recipe precedent (its D7), and its
rule that plan gates must be runnable on this host while live checks are ship-time evidence (its
D18). This repo has no context map, no ADR tree, and no `docs/` directory; the `docs/areas/*/adr/`
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

Populate `permissions.allow` in `home/common/claude-code/default.nix` with sixteen entries — fifteen
narrow Bash rules plus the `Agent` tool entry — covering exactly the lifecycle surface the issue names — read-only git and tracker queries, worktree
lifecycle, `git branch -d`, the `Agent` tool, and `gh pr merge` — replace the stale comment above
`permissions` with one that explains what the list is and why each risky member is admissible, and add
a `just show-claude-settings` recipe that prints the generated artifact so the acceptance criteria are
checkable by a named command rather than by an incantation.

Three properties do the work, and each is a consequence of how the matcher behaves rather than of how
carefully the list was written:

1. **Bash rules resolve before the classifier**, including in auto mode. Bash is not among the
   documented exceptions to immediate rule resolution (those are writes to protected paths and
   organization-`ask` / `requiresUserInteraction` MCP tools). So every Bash entry here converts a
   probabilistic outcome into a deterministic one.
2. **Prefixes are literal**, which forces the rule shapes to be derived from the invocations the
   skills actually type rather than from the tidiest way to write them down.
3. **Prefixes are case-sensitive with no flag normalisation**, which is what makes the issue's
   negative criteria hold by construction instead of by review vigilance.

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
- Matching is **case-sensitive** and performs **no flag normalisation**: with `Bash(git branch -d:*)`
  allowed, `git branch -D` is denied; with `Bash(mkdir -p:*)` allowed, `MKDIR -p` is denied.
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
| `Bash(gh pr merge:*)` | `gh pr merge <n> --merge --subject "…" --delete-branch` |

Tool dispatch:

| Rule | Note |
|---|---|
| `Agent` | Inert under `defaultMode = "auto"`. See *The `Agent` entry*. |

The `:*` spelling is used throughout rather than the equivalent ` *`: it is the form the issue's own
acceptance criterion names verbatim, and it makes the rule's two parts — prefix and wildcard —
visually separate.

### Why each risky member is admissible

**`Bash(gh pr merge:*)` — prefix-only, and that is forced.** `ship-issue` types
`gh pr merge <pr-num> --merge --subject "…" --delete-branch`: the argument precedes every flag.
Because prefixes are literal from position 0, a rule written `Bash(gh pr merge --merge:*)` would never
reach that shape — it would be a rule that looks safer and does nothing, which is worse than the
broader rule because it also removes the pressure to think about what actually gates the merge.

The consequence is that `--admin` is reachable. That is admissible, and only because of a fact
established elsewhere and verified there: `.github/branch-protection.json` sets `enforce_admins: true`
with `Nix Eval` as a required context, and under that setting `gh pr merge` **including `--admin`** is
refused by GitHub until the check is green. So the merge is gated by the server, not by the
classifier — which is exactly the disposition `.out-of-scope/ungated-agent-merges.md` recorded:
"Merge safety must come from a required status check on the PR, not from the permission classifier or
skill-internal gates alone."

This entry is therefore coupled to that gate, and the coupling is one-directional and load-bearing:
**if `main`'s branch protection is ever removed or `enforce_admins` is set to `false`, this entry must
be removed in the same change.** The module comment says so at the entry.

**`Bash(git worktree remove:*)` — reaches `--force`, and is still bounded.** `git worktree remove`
deletes a worktree directory and its administrative entry. It does not delete the branch, and it does
not touch commits: anything committed on the branch survives and remains reachable. Branch deletion is
a separate command with its own, much narrower rule. `--force` widens what the command tolerates
(a dirty tree), not what it destroys beyond the working copy.

**`Bash(git branch -d:*)` — the negative criterion holds by construction.** `-d` refuses to delete a
branch that is not merged into its upstream or into `HEAD`; deleting an unmerged branch requires `-D`.
Because matching is case-sensitive and performs no flag normalisation, `Bash(git branch -d:*)`
**cannot** reach `git branch -D` — not "should not", cannot. The issue's "no `branch -D`" criterion is
thus satisfied by the shape of the rule rather than by anyone remembering to check, and this is worth
stating explicitly because the reverse assumption — that a permission engine would normalise a flag's
case — is the assumption a reviewer would reasonably start from.

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
  @nix-store --query --requisites ./result \
    | grep -- '-claude-code-settings\.json$' \
    | xargs cat
```

Verified: appended to a scratch copy of the justfile and run in this worktree, it built and printed the
current settings JSON, with the platform-gated `build` dependency resolving correctly.

### The comment block, and what `CLAUDE.md` gains

The comment above `permissions` currently explains why the allow list is *empty* ("the large
project-specific allow-list from the old settings.json was accumulated state, not a durable global
baseline, so it is deliberately dropped. Add durable global allows here if wanted."). That sentence
becomes false the moment this change lands, and it is the first thing the next editor reads.

It is replaced by a comment that states what the list is (the agent-lifecycle surface, one narrow rule
per subcommand), the two engine facts a future editor must not rediscover the hard way (prefixes are
literal and case-sensitive; a malformed allow rule never warns and never matches), and an inline note
at each of the two entries that carries a condition: `gh pr merge` is admissible only while `main`'s
required check and `enforce_admins` are in place, and `Agent` is dropped in auto mode. Rationale lives
next to the line it explains; the analysis lives here.

`CLAUDE.md` gains two small things, both in places that already carry this kind of note: `just
show-claude-settings` in the Commands block, and one sentence in the existing claude-code bullet list
recording that `permissions.allow` is the declared agent-lifecycle surface, that it is coupled to
`main`'s required check, and that a malformed rule fails silently so changes are checked with the
recipe rather than by reading the diff.

## Test seams

Three seams, all of them existing or named by the issue. No new test file, no new test runner.

1. **The generated settings artifact** — the store JSON, reached by `just show-claude-settings`. This
   is the seam both of the issue's inspection criteria are asserted at, positively (the sixteen
   entries are present verbatim) and negatively (no entry matches `git config`, `.git`, `branch -D`,
   `push`, or a blanket/wildcarded-interpreter shape). Asserting on the built artifact rather than on
   the `.nix` source is the point: it is what Claude Code actually reads, and it survives any
   refactor of how the attrset is assembled. Prior art: the sibling CI spec's `show-protection`.
2. **`just build` exit 0** — the repo's only verification step, per `CLAUDE.md`. Both seams 1 and 2
   are satisfied by one build, since seam 1 depends on it.
3. **The live demo, as ship-time evidence** — the issue's own demo: after a rebuild, a background
   subagent removes a scratch worktree and runs `gh pr view` without a permission denial. This is the
   only seam that can prove a rule *matches* rather than merely *exists*, and it cannot be a plan gate
   because it requires `just switch` (sudo, and this repo switches only when asked). It is recorded as
   evidence at ship time, following the sibling CI spec's rule that plan gates must be runnable on
   this host while live checks are ship-time evidence, and this repo's existing `*-evidence.md`
   companion convention.

Seams 1 and 2 prove the rules are present and well-formed. Neither can prove they match, because no
offline check can: there is no rule linter, and a malformed allow rule produces no warning. That
asymmetry is why seam 3 is mandatory rather than nice-to-have, and why the rule shapes in this design
were derived from grepped invocation evidence rather than from what reads well.

## Acceptance criteria

Restated so each names the command that decides it.

1. **The generated settings contain the lifecycle allow rules, including `Bash(gh pr merge:*)`.**
   Decided by `just show-claude-settings | jq -r '.permissions.allow[]'` listing exactly the sixteen
   entries above. Baseline: at the base commit the list is empty, so the diff is unambiguous.
2. **The allow list contains no rule matching `git config`, `.git/` edits, `branch -D`, or `push`.**
   Decided by the same output: no entry contains `config`, `.git`, `branch -D`, or `push`, and no
   entry is `Bash(*)` or a wildcarded interpreter. `git branch -D` additionally cannot be reached by
   any entry as a matter of case-sensitive matching, not only as a matter of absence.
3. **The flake still builds.** `just build`, exit 0.
4. **(Ship-time, evidence not gate.)** After a switch, a background subagent removes a scratch
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
- **A test that asserts the rule list.** No offline test can check the property that matters (that a
  rule matches), and a Python regex over Nix source would add a second, fragile authority for rule
  shape while catching only the negative criteria a reviewer reads directly off a sixteen-line diff.

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
