Mode: design review. You review one plan outline before any code exists.
Issue {{run.issue}} of {{run.repo}}. The issue, with its comments:
{{plan-preflight.issue_text}}

The outline:
{{outline-read.text}}

Judge only this rubric, and report a finding only for one of these four:
- an approach that breaks a documented convention or decision of the project (its standards, its docs, its recorded decisions);
- a proving test that cannot fail (it passes without the slice's change, or asserts nothing the slice adds);
- a missing owner decision (a preference, an irreversible or scope choice the issue and the project's records leave open);
- scope beyond the issue.
Anything about how the code will look is not a finding: no style notes, naming, structure or implementation advice. Read the code only to check a claim a finding relies on. Do not edit anything.
Return verdict pass when you have none of the four, else verdict findings with each defect as a finding naming the slice or criterion it concerns. Give each finding a kind, one of edge-or-failure-path, weak-test, missing-test, contract-mismatch, stale-docs, security, concurrency, plan-step-not-executable or other, and a rule only when the finding breaches a standard: that standard's id, as B12; leave rule out otherwise.
