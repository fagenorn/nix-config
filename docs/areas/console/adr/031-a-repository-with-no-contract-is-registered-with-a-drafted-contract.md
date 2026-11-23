# ADR-console-031 — A repository with no contract is registered with a drafted contract

- **Status:** accepted; amended by ADR-console-033, ADR-console-070, ADR-console-082; amended in place by #1449 (D2); D2 amended in #1445; D2, D4 and D7 amended in place by #1485 (the draft is project schema 3)
- **Decided in:** #1067

## Context

ADR-console-028 plans a repository's adoption from the page, and ADR-console-029 lets the owner answer the plan's questions there. Both stop at a repository with no `.agents/project.json`: the plan amends that file, so without one it could never reach `ready`, and the owner had to write a contract by hand in a terminal first. #1067 has the console draft the contract from what the repository says, ask only what it cannot read, and hand the result to the plan as a file the adoption writes (ADR-project-contract-004). Project policy is never silently defaulted: every value the console set is shown and can be changed before the plan is applied.

## Decision

**D1. When drafting starts.** A registration of a checkout with no `.agents/project.json` drafts a contract instead of planning at once. The console reads, never writing, the remote's authored URL (before `insteadOf`), the remote's default branch (`git ls-remote --symref`, only when the repository has exactly one remote, bounded at 10 seconds, with no prompt) and the tracked files.

**D2. The fields and the facts.** The draft is a project-schema-3 contract (ADR-project-contract-010), so it authors only what the platform does not decide: five fields, `integration-branch` (the branch finished work merges into), `lint-command`, `test-command`, `release` and `production`. Each is shown with a Change control, or asked as a card when it is open. The integration branch is read from the remote's default branch, the lint and test commands from the tracked files; both commands are required, so a typed `none` is refused with `Every project has a <lint|test> command: type the command that runs it.` A value the console read carries its source (`read from its remote`, `found in its files`, `set by you`); every other value reads `the console's starting value`. A structured value (a release profile, the production rules) is typed as JSON, and the resolver judges it. Beside the fields the draft holds five facts, the values the platform derives and the adoption writes from the repository: the project id and issue tracker (the origin remote's slug), the checks a pull request must pass, the platform versions it runs on, the minutes per delivery attempt and the agent knowledge files it holds. A fact is computed from the bytes the adoption writes (its conformance edits included, and a tree's own platform manifest first), never from a tracked file alone, so what the card shows is what the resolver derives. It is never asked, answered or changed; when the repository cannot state it, the fact says which file is missing (`cannot be derived until .github/branch-protection.json is in the repository`). The drafted capabilities follow the rule: a knowledge capability is supported exactly when its platform home is tracked, every other authored capability is supported. A draft saved with an earlier table (27 fields, the retired light lane and co-author setting included) reads back onto the five fields: the integration branch from its saved value, else its saved default branch; a test command unless it was `none`; the release; the lint command is asked again, and the plan is made again.

**D3. The cards.** An open field is a question card titled `Register <name>` with the question id `contract-draft` and the field as its subject. It counts in what needs the owner (ADR-console-029 D10), and has a text field where a value is typed. Each card's question is fixed when the draft is read, so it reads the same in every later row.

**D4. The project id.** The draft has no project-id field: the project id and the issue tracker are the origin remote's slug, derived, shown as a fact and never typed. `adopt-project plan` is the one check of it: it refuses an id the fleet registry holds for another root as `adopt.draft.id_taken`, and the console shows that refusal as D7 says. The console keeps no project-id rule or registry check of its own.

**D5. The answers.** Answers and changes travel through `POST /api/plan-answer` with the question id `contract-draft` and the field as subject: no new page write (ADR-console-008). A command that cannot be split is refused with `the command could not be read: close every quote and do not end it with a backslash`, and JSON that cannot be parsed with `type it as JSON, or choose one of the offered answers`, each as a `409` with its plain text that appends nothing and runs nothing.

**D6. The plan.** Once no field is open, the console writes the draft to a file in its own state directory, outside the checkout, runs `adopt-project plan --contract-draft` (ADR-project-contract-004) and removes the file. The plan's change lines then include `writes the project contract`, and the plan's id covers the draft.

**D7. A refusal.** When the plan's resolver refuses the draft, the field it concerns reopens as a card with `The plan refused the <label>: <message>`, never a code, a pointer or a repair id (#1057). A refusal that concerns only a derived value or the project id (`adopt.draft.id_taken`, or a violation at the pointers a fact stands for) reopens no card: the registration is a failed row with its retry card, on the registration run and on the answer of the last question alike, and the failure is logged.

**D8. Nothing before apply.** Nothing is written into the checkout before `adopt-project apply`, which writes the contract in its own worktree. No host check is added: the drafting path adds only what ADR-console-028's check already removes.

## Consequences

- The owner takes a repository with no contract from nothing to a `ready` plan with no terminal; approving a ready plan is ADR-console-030.
- Tests sandbox HOME, every repository and the remote: a throwaway bare remote reached through `insteadOf`, with `GIT_ALLOW_PROTOCOL=file` so a missed rewrite fails instead of reaching a network host.
- The page's two new controls (a Change control and a text field on a card) belong to the desk page's rules.
- Related: ADR-console-008, ADR-console-028, ADR-console-029, ADR-console-030, ADR-project-contract-004, ADR-project-contract-005.
