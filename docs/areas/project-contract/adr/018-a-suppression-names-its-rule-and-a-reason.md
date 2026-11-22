# ADR-project-contract-018 — A suppression names its rule and a reason

- **Status:** accepted
- **Decided in:** #1459 (per #1414, #1412)

## Context

A lint rule held by the never-rise check (ADR-project-contract-017) has no exception path other than weakening the lint itself, and a line that must break a rule, such as a generated table in a source file, then forces the rule to be loosened for every file. The decision of #1414 allows one way out: a suppression that names the rule and says why. The link from a rule to its enforcer (#1412) is the rule id, so the suppression names that id.

## Decision

**D1. The form.** A suppression is the marker `suppress-standard:` not glued to a word (the character before it is not a letter, a digit, `_` or `-`), then a run of non-space characters that is the id only when it is a whole rule id, then the reason: the rest of the line, stripped, less one trailing `-->` or `*/`. A marker is reasoned when it has an id and a reason holding a letter or a digit. The form sits inside any comment syntax, and the `-` before `standard:` keeps it from being read as a citation.

**D2. The line.** A marker covers the finding on its own line only. The reason runs to the end of the line, so a line holds one marker.

**D3. Counting.** A reasoned marker drops the findings of the rule it names on its line. A marker that is not reasoned adds one violation `(rule, path, marker line)`: of the rule it names, wherever it is, or, with no id, of each enforcer whose finding is on its line. An id-less marker on a line with no finding counts nothing.

**D4. Per-file rules.** The findings of a per-file rule are compared per file, as ADR-project-contract-017 D3 says; its marker violations are compared as a count, so a bare marker on a held size violation still rises. D3 and D4 amend the count of ADR-project-contract-017 D3.

**D5. New suppressions.** The listed ones are the branch's reasoned markers minus the base's, a multiset keyed by rule, path matched through git renames, and reason, so a moved or unchanged suppression is not new. A bare marker is never listed, because it is a violation.

**D6. The lint's files.** The cited-id check reads every tracked file of the working tree (`git ls-files -z`) that is a regular file with no NUL in its first 8,000 bytes. A root with no `.git` entry has no tracked file, and a failed listing is a usage error (exit 2).

**D7. The index line.** The rule index prints `reasoned suppressions: <n>` after a rule's enforcer lines only when `n` is above 0, crediting the layer the id resolves to.

**D8. The report.** The never-rise check adds `suppressions` (sorted, at most 8, each with rule, path, line and reason) and `suppression_count` (the true total) to its facts, passed or failed, only when the branch added a suppression. A listed suppression never fails the check.

**D9. `size-lint`.** The command prints the counted violations, the findings left after suppressions plus the marker violations, sorted by path and line.

## Consequences

- A marker naming an id no applicable layer defines fails the standards lint, so a deleted rule cannot keep a suppression.
- An existing reasoned suppression keeps covering its line, so a reasoned size suppression on a file's last line lets that file grow. Only a new one is listed for the reviewer.
- The report lists at most 8 suppressions and states the true count.
- Off-the-shelf tools keep their native suppression syntax.
- Rejected: one marker per stack syntax, because the lints are the platform's own and one form is read by all of them.
- Rejected: failing a run on a new reasoned suppression, because the decision of #1414 allows a reasoned one and leaves the judgement to the reviewer.
