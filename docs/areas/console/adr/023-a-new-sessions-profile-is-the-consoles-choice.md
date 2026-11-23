# ADR-console-023 — A new session's profile is the console's choice, on a route and in a file

Context: #839 and #842 decided that a new session runs under the profile with the most headroom and that the launcher asks the console. Decision: the console makes the one choice, with the owner's pin and exclusions and with duplicate sign-ins counted once. It answers the choice on `GET /api/profile` and writes it to the `chosen-profile` file, and the manager launch uses the same choice. Rejected: the per-project binding in `bindings.tsv`.
