# Skill prose fixes behind four recurring agent-error classes

Issue: [#99](https://github.com/fagenorn/nix-config/issues/99) — "Fix the shared skill prose behind 417 recurring agent errors"

## Problem

Four recurring agent failure classes, measured over a 7-day window across three consuming repos,
trace to wrong prose in the shared skills rather than to wrong agent behaviour:

1. **Dead named launches from leaf agents** — 119 launches, 11.5% of all launches, every one made from
   inside a subagent. A subagent cannot spawn a named teammate; the launch returns an error instead of
   work. No skill instructs this — orchestrator-flavoured guidance is being read by leaf agents. The
   equivalent restriction already exists for *result delivery* in one dispatch template and nowhere else.
2. **Writing a file before reading it** — 64 errors. No dispatch template carries any read-before-write
   rule today.
3. **Unconditional bindings-config probes** — 37 errors. The adapter contract says the config carries
   the bindings a project chooses to declare; two of the three consuming repos have no such file, yet
   several skills instruct an unguarded read.
4. **Shell forms the worktree isolation checker refuses** — 197 errors, the largest single class
   (71 chained or piped, 68 redirects or heredocs, 57 other). The skills teach heredoc-to-stdin and
   multi-clause chains as the normal way to run work; a static checker cannot verify those stay inside
   the worktree, so it refuses them. The `worktrees` skill carries an evidence note for the smaller
   redundant-entry class and nothing for this one.

The consequence is uniform: an agent following the shared prose exactly still produces an error turn.
Fixing prose alone is not enough — every fix has to be held in place by the skill-contract suite, so a
later edit cannot quietly reopen the class.

## Solution

Four prose changes plus one test seam.

**A. Leaf-agent clause in every dispatch-prompt template.** Six files are dispatch-prompt templates:
the implementer, task-reviewer, scoped re-review, correctness-reviewer and conformance-reviewer prompts
under the `sdd` skill, and the Phase-7 ship-owner prompt under `from-issue`. Each contains exactly one
fenced block, and that block *is* the prompt pasted into the subagent. Two canonical sentences go
**inside that fence**, in the template's output/report section next to where delivery is already
discussed:

- a *launch* sentence — a leaf agent launches subagents by type only, never by name, because a
  subagent cannot spawn a named teammate and the launch returns an error instead of work;
- a *delivery* sentence — the result is the final message, never `SendMessage`, because no recipient
  name was given and agent-type names are not addressable recipients.

The delivery sentence already exists in the implementer template. Only its **portable** half is the
canonical string reused in the other five — the clause about `SendMessage`, the absent recipient name
and agent-type names not being addressable recipients. The implementer's surrounding sentence naming
*the controller* as the reader stays template-local, because the ship-owner template's caller is not a
controller and a copied sentence would be false there. The launch sentence is new and identical in all
six.

The launch sentence restricts **naming**, not launching. Two of the six templates legitimately dispatch
subagents — the implementer and the ship owner, whose prompt already states that nested `Agent` calls
are supported. Wording that reads as "do not orchestrate" would break both, so the clause must say
by-type-only and stop there.

**B. Read-before-write clause in every dispatch-prompt template.** One canonical sentence, placed with
the clauses from A: read a file before writing to it, because overwriting unread content destroys work
the agent cannot see. In the read-only reviewer templates the clause is an inert guard; it is carried
anyway so the contract has one rule and no exception set.

**C. Every bindings-config read guarded on presence.** Every place the skills name
`.claude/skills.config.json` states the presence guard in the same sentence or the paragraph around it, in the register the
already-correct sites use (`if it exists` / `when present`). This covers both the two unguarded reads
and the sites currently guarded only on the *resolver helper* being absent — that guard makes the
config read conditional on the helper, not on the file, which is exactly the 37-error case.

**D. Isolation-checker shell guidance, and the offending examples removed.** A new section in the
`worktrees` skill, a structural sibling of the existing `Already positioned? Skip the call` note: same
shape, an evidence line stating this class is roughly four times the redundant-entry class above, then
the rules. The guidance is derived from what a static checker can verify — the checker itself is
harness-level with no source in this repo — and is stated so it stays true if the checker's details
shift: **the checker can confirm a command stays inside the worktree only when the target is a literal
argument of a single invocation; shell control flow and redirection hide the target, so they are
refused.** The alternative that works, and which the section names:

- one command per call, and a second call for a dependent step rather than a chain;
- create and truncate files with the file-writing tool, never a redirect or heredoc — the tool takes an
  explicit path the checker can check;
- hand a long body to a CLI by path (`--body-file`, `--notes-file`, `-F <file>`, `@<file>`) after the
  file-writing tool has written it;
- carry paths inside a single invocation — absolute paths under the worktree root, or the tool's own
  directory flag such as `git -C <path>` — because a `cd <path> && …` prelude is itself the refused chain;
- when the checker refuses, change the shell form, never the isolation.

Then the skills' own example commands stop demonstrating the refused forms. The sweep is defined by a
rule, not a list: **no shell command shown in any skill document contains a chain operator, a pipe into
a command, a redirect, or a heredoc.** It reaches the `worktrees` isolation-detection snippet (which
becomes a single `git rev-parse` invocation asking for the git dir, the common dir and the superproject
working tree at once — verified locally: the flag for the superproject prints *no line at all* outside a
submodule, so the replacement prose must say "compare the first two lines; a third line means
submodule" rather than implying three fixed lines), the two PR/release-body
heredocs (which become a written file passed by path), the `unset GITHUB_TOKEN &&` tracker-call prefix
in four documents (which becomes a single-command `env -u GITHUB_TOKEN` form), and the remaining
chained, piped and redirected examples in the `ship-issue`, `ship-release` and `from-issue` skills.

Two sites need judgement rather than mechanical rewriting, and the plan must treat them as such: the
release pre-flight's `|| true` exists to keep a no-tags repository alive under `set -e`, and the
`gh pr checks … | grep` in the CI-merge document appears inside a prohibition as an anti-example. Both
keep their meaning — the first by describing how to treat a non-zero exit, the second by naming the
filter in prose instead of showing the pipe.

**E. Contract assertions.** All four criteria and the example sweep become assertions in the
skill-contract suite. Because criterion 6 requires the suite rather than review to hold each criterion,
the assertions must be blanket rules over discovered files, not spot checks on today's text.

## Decisions

**Canonical strings, repeated physically.** The clauses from A and B are byte-identical across the six
templates rather than factored into a shared document the templates link to. A dispatch template is
pasted wholesale into a subagent's starting context; a link is not in that context, so the text must
physically be there. The single authoritative home the bar's DRY rule asks for is the *assertion*: one
string constant in the suite, asserted against all six templates, so the copies cannot drift.

**The clause lives inside the fence.** Assertions check the clause is inside each template's single
fenced block, not merely somewhere in the file. Prose outside the fence is dispatcher-facing and never
reaches the subagent, so a clause placed there would satisfy a naive test and fix nothing.

**Presence-guard register.** `if it exists` and `when present` are the two accepted phrasings, both
already in use. Sites that merely *describe* the config rather than instruct a read also gain the
phrase; the uniformity is worth more than the few redundant words, and it keeps the assertion a single
paragraph-scoped rule with no exception list.

**The shell rule is blanket, not an allowlist.** Every skill document is in scope for the example
sweep, including skills that run outside a worktree, because an allowlist of tolerated sites rots the
moment a skill is edited and because a skill that teaches a refused form anywhere re-teaches it
everywhere. The cost is a wider mechanical diff across roughly eight documents.

**Pipes are only detectable inside extracted shell text.** `|` is overwhelmingly an alternation
separator in skill prose and in report shapes (`clean | residuals | unknown`), so no assertion may scan
raw document text for it. The suite therefore extracts shell text first (below) and applies the four
forbidden-form checks only to that.

**Command substitution is left alone.** `$(…)` is not one of the measured refusal classes and cannot be
attributed to the checker from available evidence. Existing uses stay; this design makes no claim about
whether the checker accepts them.

**No ADR.** The ADR gate is hard-to-reverse **and** surprising **and** carrying a real trade-off. These
are prose edits held by tests — reversible in one commit. This repository also has no ADR home at all;
the adapter contract would place one under `docs/areas/system/adr/`, and founding that tree for
reversible prose fixes would be the wrong first entry. No ADR is written and no `docs/` tree is created.

## Test seams

One seam: **the skill-contract suite** (`test_workflow_skill_contracts.py`, run by
`just agent-workflow-tests`). No new test file, no new runner, no CI change — CI evaluates the NixOS
configuration only, and the Python suites remain a local gate, as the project's guidance states. No
`.nix` file changes, so `just build` is a sanity check rather than a gate here.

Five additions inside that suite, all following its existing style — module-level `Path` constants, a
discovery generator, and per-file `subTest` loops:

1. **Dispatch-template enrolment.** An explicit tuple of the six template paths (the suite's prevailing
   style, and it yields a precise failure message naming the template) **plus** a guard test asserting
   that the set of documents under the two skill directories containing exactly one fenced block equals
   that tuple. Neither half alone is a contract: a glob-only test silently covers nothing when a future
   template carries two fences, and a constants-only test silently ignores a new template. Together, a
   new template fails the guard until it is enrolled — the bar's fail-loud rule applied to a test. The
   guard's reach is stated honestly: it walks the two skill directories where dispatch templates live
   today, so a template introduced in a third skill would escape it. That residual gap is accepted; the
   tuple, not the walk, is the contract.
2. **Clause assertions.** For each enrolled template, the launch clause, the delivery clause and the
   read-before-write clause each appear inside its single fenced block. The issue's demo falls out of
   this directly: removing the clause from one template fails exactly this test and nothing else.
3. **Shell-form extraction helper.** One new module-level helper extracts shell text from a skill
   document — the lines of `bash`/`sh` fenced blocks, plus inline code spans whose first word is a known
   command — and four checks assert the extracted text carries no chain operator, no pipe into a
   command, no redirect and no heredoc. The heredoc check additionally runs over whole documents, where
   it has no false positives, so a heredoc outside a shell fence is still caught. This helper is the
   only genuinely new machinery.
4. **Presence-guard assertion.** For every occurrence of the config's literal path in a skill document,
   the *containing paragraph* — the blank-line-delimited block — carries a guard phrase. The window is a
   paragraph rather than a line because at least one existing occurrence already wraps across a line
   break, and a line-scoped assertion would demand an unnatural rewrap to pass.
5. **Worktrees guidance assertion.** Criterion 4 needs its own check, since the sweep assertions only
   prove the bad examples are gone, not that the guidance exists. It asserts the new section is present
   in the `worktrees` skill and that it names all three refused forms — redirects, heredoc-to-stdin, and
   multi-clause chains — together with the alternative, using the suite's existing ordered-anchor helper
   so the section's shape is checked rather than only its vocabulary.

Each assertion fails for exactly one reason, per the bar's testing rule: enrolment drift, a missing
clause in a named template, an unguarded config mention in a named paragraph, a refused shell form at a
named location, or missing isolation-checker guidance.

## Out of scope

- The worktree isolation checker and the harness. Not in this repository; the guidance is derived from
  what a static checker can verify and must not encode a guessed rule table.
- `scripts/resolve-bindings` and any change to how bindings resolve. Only the prose describing the read
  changes.
- The eval fixture repository and every `evals/evals.json` prompt. The fixture's ADR- and
  CONTEXT-shaped files are fixtures, not this project's documentation.
- Any behavioural change to `workflow-state`.
- Executable scripts under the skills (for example the task-brief script). Criterion 5 is about skill
  prose; a script's own shell is not an example an agent copies.
- Command substitution, per the decision above.
- Founding `docs/`, `docs/areas/`, a context map, or an ADR tree.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The launch, delivery and read-before-write clauses are byte-identical text repeated inside all six dispatch templates; the single authoritative home is one string constant in the contract suite | the-bar "DRY — knowledge, not keystrokes"; a dispatch template is pasted wholesale into the subagent, so a link is not in its context | Factor the clauses into a shared document the templates link to — the link never reaches the subagent, so the fix would not fix anything |
| D2 | Clause assertions require the clause inside each template's single fenced block, not merely in the file | The fenced block is the prompt; prose outside it is dispatcher-facing | Assert file-wide containment — passes on a clause placed where no subagent ever reads it |
| D3 | Criterion 3 is read as its plain words: every mention of the bindings config carries an `if it exists` / `when present` guard, including the six sites guarded only on the resolver helper being absent, and including descriptive mentions | Issue criterion 3 ("every"); helper-conditional phrasing makes the read conditional on the helper, not the file, which is the measured failure; register copied from the already-correct sites | Fix only the two unguarded reads — leaves the majority of the 37-error surface intact and forces the assertion to carry an exception list |
| D4 | Criterion 5's sweep is a blanket rule — no chain operator, pipe into a command, redirect or heredoc in any shell command shown in any skill document — covering skills that run outside a worktree, at the cost of a wider mechanical diff | the-bar "Tests that can fail" (one reason, no rotting allowlist); criterion 6 requires the suite to hold the criterion | Restrict the sweep to the worktree-resident skills with a tolerated-site allowlist — the allowlist rots on the next edit and the contract stops meaning anything |
| D5 | The named alternative is derived from one stated invariant — the checker can verify only a target that is a literal argument of a single invocation — expressed as one command per call, the file-writing tool instead of redirects and heredocs, bodies passed by path, and per-invocation path carrying rather than a `cd &&` prelude | The checker is harness-level with no source here; guidance must stay true if its details shift | Enumerate the checker's presumed accept/reject rules — unverifiable, and stale the first time the harness changes |
| D6 | Dispatch templates are enrolled as an explicit six-path tuple **and** guarded by a discovery test asserting the single-fence document set equals that tuple | the-bar "Fail loud" at a closed-set site; the suite's existing constant style plus its existing glob-walk precedent | Glob-only discovery (silently covers nothing once a template gains a second fence) or constants-only (silently ignores a new template) |
| D7 | Pipe, chain and redirect checks run over shell text extracted from `bash`/`sh` fences and command-leading inline spans; only the heredoc check runs over whole documents | `\|` is an alternation separator throughout skill prose and report shapes, so a raw-text scan cannot fail for one reason | Scan raw document text for the four forms — unusable false-positive rate, and the exception list needed to silence it destroys the contract |
| D8 | Command substitution is out of scope and no claim is made about the checker accepting it | Not among the measured refusal classes; nothing in reach can establish the checker's treatment of it | Rewrite substitutions too — speculative work against an unverified rule (YAGNI) |
| D9 | No ADR and no `docs/` tree; the design records the reasoning here instead | ADR gate is hard-to-reverse AND surprising AND real trade-off; adapter contract would place one under `docs/areas/system/adr/`, and this repo has no ADR home | Found the ADR tree for this change — a reversible prose fix is the wrong first entry, and the tree would arrive unmaintained |
| D10 | The release pre-flight's `\|\| true`, the `2>/dev/null` stderr suppressions, and the CI-merge document's `gh pr checks \| grep` anti-example are rewritten for meaning, not mechanically stripped | the-bar "Root causes"; the first carries a `set -e` rationale, the suppressions hide a failure the prose relies on, the last is a prohibition whose subject is the pipe | Apply the blanket rule mechanically — would delete a documented `set -e` guard and mangle a prohibition into nonsense |
| D11 | Only the *portable* half of the existing delivery clause becomes the canonical asserted string; the sentence naming "the controller" as the reader stays template-local | Prose discipline: the ship-owner template's caller is not a controller, so the copied sentence would be false there | Copy the implementer's whole delivery paragraph into all six — plants a false statement in at least one template to satisfy a test |
| D12 | The launch clause restricts naming only, never launching | The implementer and ship-owner templates legitimately dispatch subagents, and the ship-owner prompt already states nested `Agent` calls are supported | Word it as "leaf agents do not launch subagents" — contradicts two templates' documented behaviour and would break working flows |
| D13 | The read-before-write clause goes in all six templates, inert in the read-only reviewer ones, rather than only in the templates whose agent writes files | Criterion 2 says "dispatch-prompt templates" without restriction; one rule with no exception set is the cheaper contract, and the cost is one sentence | Restrict it to the writing templates — a defensible reading, but it buys a few tokens with an exception set the suite then has to encode and maintain |
| D14 | The presence-guard assertion's window is the containing paragraph, not the line | An existing occurrence already wraps across a line break | Line-scoped assertion — forces an unnatural rewrap purely to satisfy the test |
| D15 | The blanket assertions (shell sweep and presence guard) discover `*.md` under **both** skill trees — `home/common/agent-skills/skills/` and `home/common/claude-code/skills/` — excluding any path with an `evals` component | The second tree holds live skills (`orchestrate-issues`, `codex-collaboration`); measured to contain zero shell offenders today, so widening the contract costs no edit while closing part of the third-skill gap D6 leaves open | Scope to the agent-skills tree only — leaves a live skill tree free to re-teach a refused form with nothing to catch it |
| D16 | The shell-text extractor normalizes a command's first token — stripping a leading `${VAR}` expansion and a leading `VAR=` / `VAR=$(` assignment — before the known-command lookup | `${GH_PREFIX}gh pr list …` and `PREV=$(git describe … \|\| true)` are real offenders whose raw first token is not a command name | Match the raw first token — silently misses the two largest offender families in `ship-release/SKILL.md`, leaving the contract green over broken examples |
| D17 | All four forbidden-form checks run over placeholder-stripped text (`<[^<>\n]+>` removed), and the heredoc pattern requires `<<` followed by an optional `-`, an optional quote and an identifier | Skill prose is dense with `<pr-num>`-style placeholders, so a bare `>`/`<` scan fires on nearly every `gh` example; `ship-issue/SYNC.md` shows `<<<<` conflict markers in prose | Raw character scans — an unusable false-positive rate, and the exception list needed to silence it is exactly what D4 forbids |
| D18 | `if grep -q <forbidden> <file>; then exit 1; fi` in `writing-plans/SKILL.md` is left unchanged and needs no exception: `if` is not a known command, so the extractor never reaches it | D7's command-leading extraction rule already excludes shell keywords | Sweep it too — destroys the gate-writing instruction the sentence exists to teach, or forces the exception list D4 forbids |
| D19 | The canonical delivery clause is the implementer template's existing sentences from "Never deliver it via SendMessage" onward, reused byte-for-byte, so that template's own text is unchanged | D11's portable half already exists verbatim there | Author a fresh canonical sentence — a gratuitous edit to a working template, and a second string to keep in sync |
| D20 | The `unset GITHUB_TOKEN &&` prefix becomes `env -u GITHUB_TOKEN` in all four documents | The prefix's job is a per-invocation environment change, which `env -u` expresses as the single invocation the checker can verify | Split it into two calls (loses the effect entirely) or `GITHUB_TOKEN= gh …` (sets an empty token, which `gh` reads as a credential) |
| D21 | The enrolment predicate is "exactly one **unlabeled** fenced block", refining D6, **and an unlabeled fence alone is not sufficient** — see D23 | `skills/from-issue/decision-ledger.md` carries a single fence whose info string is `markdown` and is not a dispatch template; all six templates use unlabeled fences. This row's original grounding was incomplete: it excluded the labeled-fence false positive but missed the unlabeled one D23 names | "Exactly one fenced block" — enrols documents that are not prompts, so the guard fails for a reason that is not enrolment drift |
| D22 | Clause assertions compare against a whitespace-normalized fenced block, so each template may wrap the canonical clause to its own width and indentation | The five `sdd` templates indent their fence bodies four spaces and wrap near 78 columns; `ship-handoff.md` does neither | Require the clause on one physical line — forces a 140-column line into five templates that wrap, or an indentation-sensitive constant per template |
| D23 | Enrolment excludes non-prompt documents through a named `NON_TEMPLATE_SINGLE_FENCE_DOCS` set, whose sole member is `skills/from-issue/SKILL.md` | Phase-5 review, verified live: seven documents under `from-issue/` and `sdd/` carry exactly one unlabeled fence, the six templates plus `from-issue/SKILL.md`, whose `## The flow` ASCII diagram sits in a bare fence — so D21's predicate left the guard red at the starting commit, against the-bar's rule that a gate must be green before the work it gates | Widening the predicate to sniff prompt-shaped prose — it makes the failure vanish without a reviewable record, and a future false positive would be silently absorbed rather than declared |
| D24 | The two heredoc sites are documented as asymmetric: `ship-release`'s is caught by both the shell-example and whole-document checks, `ship-issue`'s only by the whole-document check | Phase-5 review, verified live: `ship-release/SKILL.md:117` sits inside a ```bash fence opened at line 112 and so is reached by extraction, while `ship-issue/SKILL.md:119` sits inside a bare fence opened at line 117 | Stating that both heredocs escape extraction — factually wrong, and it would have sent the implementer into an unexplained extra failure at a gating step |
