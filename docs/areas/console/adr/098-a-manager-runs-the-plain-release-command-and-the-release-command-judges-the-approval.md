# ADR-console-098 — A manager runs the plain release command and the release command judges the approval

- **Status:** accepted; D4 and Consequences amended by ADR-console-102
- **Decided in:** #1401

## Context

ADR-console-094 removed the release from the manager permit (its D1 list names no release) because a permit that judges the text of a shell command cannot name every spelling that runs a release. ADR-console-097 and ADR-release-016 move the approval into the release command: `release transaction run` refuses a candidate with no release card the owner approved on the console, whoever calls it and however it is spelled. With that guarantee the permit no longer decides whether a release may run, so the owner's list of 094 D1 (the merge, the rerun) gains the plain release run, and D3 (exact shapes) gains the release shape.

## Decision

**D1. The plain run is granted, as a grant and not a check.** A manager may run, alone, `release transaction run` followed only by flag-value pairs: each flag is one of `--repo-root`, `--profile`, `--commit`, `--version`, `--title`, `--notes-file`, `--confirm`, spelled exactly; `--confirm` may repeat and every other flag appears at most once; every value is a word that does not begin with `-`. The verdict reads no forge and records `{"commit", "version"}` as its target. Whether the candidate is approved is the release command's to judge.

**D2. Abandon and dispose are denied from the parsed operation.** `release_operation` finds the release command under any program name (a bare `release`, a path whose basename is `release`, `python3 -m agent_tools.release.release`, behind `env`, inside a chain). `transaction abandon` is denied with `NO_ABANDON` and a `run` with a `--dispose` or `--dispose=` word with `NO_DISPOSE`. A literal command is judged on its words, so a value is never an option: `--notes-file /tmp/a--dispose.md` is an ordinary run.

**D3. The release parser takes no abbreviation.** ADR-release-016 sets `allow_abbrev=False`, so the permit and the parser agree on which words are `abandon` and `--dispose`: `--disp` is refused by the parser, never read as `--dispose`.

**D4. One deny rule is kept, as defence in depth.** `MANAGER_DENY` holds `Bash(gh pr merge *--admin*)` and `Bash(release transaction abandon*)`. The pre-#1377 `Bash(release transaction run *--dispose*)` glob is not restored: it matched an ordinary run whose notes path or title holds that text, and the permit judges dispose from the words.

## Consequences

- Any other run spelling (a preview, an abbreviated or `--flag=value` word, a repeated flag, a value beginning with `-`, a wrapper such as `env X=1`, `xargs`, a shell variable) gets no decision and falls to the session's `auto` classifier. That is safe because the release command judges the approval.
- An abandon or dispose spelling the scan cannot see (text built at run time and piped to a shell) also falls to that classifier, as a merge spelling does. The release command's own guarantee is that only the exact `abandon` and `--dispose` words reach those paths.
- The lifecycle guard is unchanged and gains no release rule; the plain run passes it in a production-declaring repository.
- Each decision is a `permit.judged` row with verb `release`, `release-abandon` or `release-dispose`; `permit.landed` stays merge only.
- Related: ADR-console-094, ADR-console-097, ADR-release-016.
