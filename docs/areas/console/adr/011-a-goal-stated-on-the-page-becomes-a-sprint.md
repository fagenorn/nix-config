# ADR-console-011 — A goal stated on the page becomes a sprint

- **Status:** accepted
- **Decided in:** #834, #837, #838, #886, #911

## Context

The owner starts work by saying what they want, and until now the only place to say it was a terminal session. #834 decided that a goal is stated once, on the page, and becomes a sprint that a manager will later carry through a brief, its issues and an outcome. #837 puts the goal field among the objects the first screen always shows. This slice builds the owner's half: stating a goal, seeing it, and taking it back. No manager exists yet to pick it up.

## Decision

The goal is recorded in the console's own log as one `goal.stated` event carrying the project, a sprint id and the goal text, and never on the tracker (#834): a goal is the owner's sentence, not a piece of work, and nothing else may read it as one. `POST /api/goal` states it and `POST /api/withdraw` takes it back; both are page writes under ADR-console-008, so each is guarded by the token and the console's own origin, and a withdrawal appends one `goal.withdrawn` event.

The console refuses a goal for a project that is not registered, an empty goal after stripping, and a goal over 2000 characters, each with its reason and without writing a row. The page keeps the text in the field when a goal is refused, so nothing the owner wrote is lost. The refusal line stays until the owner edits the goal text, the project filter or the chosen project, which removes the refusal (#911).

Each sprint has an id and its own secret, a random value in `sprint-secrets/` beside the event log, a directory and files readable by the owner only. The secret is never served to the page, written to a row or printed, and it is what a manager will later present to act on that sprint.

A goal may be withdrawn while its brief is not approved, which is every sprint in this slice. The withdrawal is reported in the digest. A sprint whose goal has been waiting for two minutes with nothing taking it up reads "no manager has picked this up".

Goal rows are kept indefinitely: the retention pass of ADR-console-009 never removes one, and the schema 3 delete trigger refuses a raw delete of a goal row whatever its age.

The goal field is a first-screen object (#837), opened by a visible "State a goal" button or by the `g` key.

## Consequences

- No manager exists yet, so every sprint reads drafting until it is withdrawn.
- A withdrawn goal's row is kept, and only its secret is removed.
- A sprint under a project that has left the registry is hidden from the page and stays in the log.
- A project with an open sprint is not quiet, so it is not folded into the group of quiet projects.
- The secret is the only thing that proves a manager owns a sprint, so the directory is as private as the event log.
