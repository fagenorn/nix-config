# ADR-delivery-011 — A test never pins a module docstring's wording

- **Status:** accepted
- **Decided in:** issue 1311

## Context

Issue 1285's audit found about 27 tests whose assertions were that a module's docstring contained given words. They failed on a rewording of the docstring and stayed green when the documented behaviour broke, so they cost edits and caught nothing. The owner approved removing them on 18 Nov, keeping the lifecycle guard's tests and every test about a token or credential.

## Decision

- No test asserts that a module docstring contains, equals, starts or ends with given words, or omits them, directly or through a saved or normalised copy of the docstring.
- A check that a docstring exists, and a check of a command's `--help` usage output, are allowed.
- `tests/test_module_docstring_wording.py` scans the same sources as ADR-delivery-010: every member of the `agent-workflow-tests` recipe plus `tests/*.py` and `home/common/agent-skills/tests/*.py`. It fails on such an assertion, and a member of any kind other than `.py` and `.sh` fails the scan. The two guard test files are never scanned.
- The docstring tests whose source names a token, credential, secret, password or keychain, and that were on main when the scan landed, are kept unchanged and listed by name. A listed test that is gone, no longer names one of those words, or no longer pins a docstring fails the scan. Adding a test to the list is a new decision with its own record.

## Considered options

- **Remove the tests with no gate.** Rejected: nothing then stops the next one.
- **Exempt any docstring test that mentions a credential word.** Rejected: a new docstring test would pass by naming a secret.

## Consequences

- Rewording a docstring needs no test edit.
- A shell member may name a docstring for an existence check, but not for a phrase test.
- The scan does not see: docstring text set in `setUp` or `setUpClass` or returned by a helper method; a docstring compared with a value computed from code; a walrus binding; a module's source file read as plain text; a shell phrase test split across lines or without one of the tokens the scan looks for.
