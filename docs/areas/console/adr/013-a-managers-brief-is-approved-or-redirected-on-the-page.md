# ADR-console-013 — A manager's brief is approved or redirected on the page

Context: the manager answers a goal with a brief that the owner approves (#834, #835). Decision: briefs live in the console's store. A manager sends one with the sprint's secret in place of the page token, any Origin refused, and the owner approves or replies on the page, bound to the version shown. Rejected: briefs on the tracker, because a brief is not a piece of work; and the page's token for the manager, because the manager is never a browser page.
