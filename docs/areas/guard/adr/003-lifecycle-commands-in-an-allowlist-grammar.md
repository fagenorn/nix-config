# ADR-guard-003 — A lifecycle command is admitted only in one allowlist grammar

- **Status:** accepted
- **Decided in:** issue 418

## Context

A lifecycle verb that sits in a larger command can run after, before or inside something the guard did not judge: a second segment, a redirection, an expansion, a wrapper or an assignment. Judging each such shape, and the directory a verb runs in, grows with every new way a shell lets one command change another.

## Decision

Once a lifecycle verb is found, the command is admitted only in one grammar, checked before any other judgement: `[unset GITHUB_TOKEN && ][cd <dir> && ]<verb> <args>`, each word plain, single-quoted or double-quoted without an expansion. Anything else refuses that verb with its accepted forms. The only directory change left is the leading `cd`, and only an absolute directory without `..` is followed.

A pull request creation or merge that names a repository other than its directory's is judged from that repository's compiled row, with no checkout read: the context is built from the slug, runs no `git` child and takes the row's default branch once the row check confirms the row. A row the check does not confirm refuses and never falls back to the directory. This lets a session in one repository act on a registered sibling without the guard trusting a checkout it has not read.

## Consequences

- An alias or function defined in an earlier call or a startup file, and zsh `AUTO_CD`, can still move the directory unseen.
- The guarantee is only as wide as the segment tokeniser, which approximates bash rather than being bash; this is why the guard refuses whatever it cannot parse, and why the adversarial table in `tests/test_claude_permission_guard.py` is part of every change to the guard.
- The `--body-file` check is a placement check that refuses obvious in-tree paths and is not a guarantee about the file's content, which any earlier command or concurrent process can still have written.
- There is no defer path: a verb the guard adjudicates is validated-and-allowed or blocked, never handed back to the allow list, and every uncertainty blocks.
