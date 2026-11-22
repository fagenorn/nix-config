# ADR-console-102 — A manager's merge takes the guard's credential prefix and its settings allow the permitted forms

- **Status:** accepted
- **Decided in:** #1592

## Context

The guidance of a project such as jarbird prefixes `gh` with `env -u GITHUB_TOKEN -u GH_TOKEN`. The lifecycle guard admitted that spelling, but the permit read `env` as a wrapper and refused with `ALONE`, which names no form. The auto-mode classifier then refused the exact form (the second part of this record).

## Decision

**D1. The permit takes the guard's prefix set.** A merge or rerun may follow one credential-scrub prefix, exactly a spelling the lifecycle guard accepts, stripped once. The release run takes none (PD2, PD3).

**D2. A spelling refusal names the cure.** `ALONE` and `NOT_GRANTED` for a merge or rerun carry the missing flags whenever the words are readable, the accepted form filled with the project's slug and strategy, and the prefix clause the guard prints. State refusals name only their problem (PD4).

**D3. A leading release run the permit cannot read is denied.** The release allow rule (D4) matches any text after `release transaction run `, so a spelling that got no decision would run unjudged by both the permit and the classifier. A command that runs `release transaction run` at a command position (the text start, after a chain or pipe operator, or behind a wrapper the client strips before matching) and that is neither the plain run nor an abandon or dispose is denied with `RELEASE_SPELLING` (PD9). The client matches each subcommand of a chain on its own, so a chain such as an allowed `git status` followed by the release run matches every rule, and only the permit's judgement of the whole text stops it.

**D4. The settings allow the permitted forms per verb.** `manager.allow_rules(slug, strategy, delete_branch)` writes a merge rule only for a valid slug and the strategy `merge` (the one the guard spells), ending `--delete-branch` as the binding says, a rerun rule only for a valid slug, and always `release transaction run *`. The merge and rerun rules come bare and behind each `env -u` credential spelling. There is no `unset` rule: a compound command needs every subcommand allowed, and the client matches no wrapper `env` (PD6, PD7).

**D5. The admin deny sits at an argument boundary and follows each env spelling.** The deny rules are `gh pr merge --admin*` and `gh pr merge * --admin*`, bare and behind each `env -u` spelling, because a deny rule does not match past `env`, and a slug such as `o/service--admin` must not be denied. This amends ADR-console-098 D4 (PD10).

**D6. The hook decides every text a rule matches.** A rule's `*` admits an extra argument, a short head, another `--repo` and a deploy run by id, and the `PreToolUse` hook, with matcher `Bash` and no `if`, denies each (PD8).

## Consequences

- The permit and the guard agree on the prefix, and a test holds them equal.
- `permit.landed` records a prefixed merge too.
- The spellings ADR-console-098 let fall to the classifier now get `RELEASE_SPELLING`, while those that do not begin with the run (a wrapper, `xargs`, a shell variable) still fall to it.
- The auto-mode classifier no longer judges a permitted merge, rerun or release run.
- A settings file gains the rules at the next launch or wake, read again each time.
- `unset N && gh ...` spellings still go to the classifier. Closing a pull request, an `--admin` merge, other repositories and deploy workflows match no allow rule.
- Related: ADR-console-094, ADR-console-098, ADR-console-100.
