# ADR-delivery-010 — A test never pins a decision record's wording

- **Status:** accepted
- **Decided in:** issue 1309

## Context

Issue 1285's audit found about 64 tests whose assertions were that a record under `docs/areas/*/adr/` contained given words. They failed on a rewording of a record and stayed green when the recorded behaviour broke, so they cost edits and caught nothing. The owner approved removing them on 18 Nov, keeping the lifecycle guard's tests and every test about a token or credential.

## Decision

- No test asserts that text read from a decision record contains, equals, starts or ends with given words, directly or through a comparison's saved result.
- A record's file name, header, number and citations are checked by `context_map_lint` and `tests/test_docs_tree.py`, so no record's structure depends on a wording test.
- `tests/test_decision_record_wording.py` scans every member of the `agent-workflow-tests` recipe plus `tests/*.py` and `home/common/agent-skills/tests/*.py`, and fails on such an assertion. A shell member may not name a record at all, and a member of any other kind fails the scan. The two guard test files are never scanned.
- Wording tests whose source names a token, credential, secret, password or keychain, and that were on main when the scan landed, are kept unchanged and listed by name. A listed test that is gone, no longer names one of those words, or no longer pins wording fails the scan. Adding a test to the list is a new decision with its own record.

## Considered options

- **Remove the tests with no gate.** Rejected: nothing then stops the next one.
- **Exempt any wording test that mentions a credential word.** Rejected: a new wording test would pass by naming a token.

## Consequences

- Rewording a record needs no test edit.
- The scan sees only literal phrases compared with text read through a call on a record path, so a comparison of record text with a value computed from code is not caught.
