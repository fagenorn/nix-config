# ADR-console-031 — A repository with no contract is registered with a drafted contract

- **Status:** accepted; amended by ADR-console-033, ADR-console-070, ADR-console-075
- **Decided in:** #1067

## Context

ADR-console-028 plans a repository's adoption from the page, and ADR-console-029 lets the owner answer the plan's questions there. Both stop at a repository with no `.agents/project.json`: the plan amends that file, so without one it could never reach `ready`, and the owner had to write a contract by hand in a terminal first. #1067 has the console draft the contract from what the repository says, ask only what it cannot read, and hand the result to the plan as a file the adoption writes (ADR-project-contract-006). Project policy is never silently defaulted: every value the console set is shown and can be changed before the plan is applied.

## Decision

**D1. When drafting starts.** A registration of a checkout with no `.agents/project.json` drafts a contract instead of planning at once. The console reads, never writing, the remote's authored URL (before `insteadOf`), the remote's default branch (`git ls-remote --symref`, only when the repository has exactly one remote, bounded at 10 seconds, with no prompt) and the tracked files.

**D2. The fields.** The draft is a closed table of 29 fields: every contract member the console sets is a field. Each is shown with a Change control, or asked as a card when it is open. The release profile, the review commands, the generated agent files, the light lane and every path list are fields like the rest. A value the console read carries its source (`read from its remote`, `found in its files`, `taken from its folder name`, `set by you`); every other value reads `the console's starting value`. A structured value (a release profile, a projection list, a light lane) is typed as JSON, and the resolver judges it.

**D3. The cards.** An open field is a question card titled `Register <name>` with the question id `contract-draft` and the field as its subject. It counts in what needs the owner (ADR-console-029 D10), and has a text field where a value is typed. Each card's question is fixed when the draft is read, so it reads the same in every later row.

**D4. The project id.** A project id is two names joined by one slash, like owner/name, with no spaces. A typed id that breaks the rule is refused with `a project id is two names joined by one slash, like owner/name, with no spaces`. An id the fleet registry holds for another root is refused with `<id> is already registered for another checkout`. Both are checked on a typed id, on the id read from the remote (its card opens with the registry reason) and again just before the plan runs. `adopt-project plan` itself refuses such an id as `adopt.draft.id_taken`.

**D5. The answers.** Answers and changes travel through `POST /api/plan-answer` with the question id `contract-draft` and the field as subject: no new page write (ADR-console-008). A command that cannot be split is refused with `the command could not be read: close every quote and do not end it with a backslash`, and JSON that cannot be parsed with `type it as JSON, or choose one of the offered answers`, each as a `409` with its plain text that appends nothing and runs nothing.

**D6. The plan.** Once no field is open, the console writes the draft to a file in its own state directory, outside the checkout, runs `adopt-project plan --contract-draft` (ADR-project-contract-006) and removes the file. The plan's change lines then include `writes the project contract`, and the plan's id covers the draft.

**D7. A refusal.** When the plan's resolver refuses the draft, the field it concerns reopens as a card with `The plan refused the <label>: <message>`, never a code, a pointer or a repair id (#1057).

**D8. Nothing before apply.** Nothing is written into the checkout before `adopt-project apply`, which writes the contract in its own worktree. No host check is added: the drafting path adds only what ADR-console-028's check already removes.

## Consequences

- The owner takes a repository with no contract from nothing to a `ready` plan with no terminal; approving a ready plan is ADR-console-030.
- Tests sandbox HOME, every repository and the remote: a throwaway bare remote reached through `insteadOf`, with `GIT_ALLOW_PROTOCOL=file` so a missed rewrite fails instead of reaching a network host.
- The page's two new controls (a Change control and a text field on a card) belong to ADR-console-002's desk rules.
- Related: ADR-console-002, ADR-console-008, ADR-console-028, ADR-console-029, ADR-console-030, ADR-project-contract-004, ADR-project-contract-005, ADR-project-contract-006.
