# Permission-guard mechanics: the adjudicated verb forms and the fail-closed classes

Evidence member of
`.claude/specs/2026-08-20-release-lifecycle-seams-research.md`, which is the root of
this document package and holds the provenance, the coverage table, the seam roster,
and every synthesis and conclusion. This member carries records only — two
enumerations read out of `home/common/claude-code/default.nix` on 2026-09-02 — and
nothing here is reasoned from beyond what the root already states. Unqualified `:N`
line references below are lines of `home/common/claude-code/default.nix` at the
worktree `HEAD` the root's `## Observation basis` records.

## The four adjudicated verbs and the exact form each is validated into

`GUARDED_LITERALS` and `GUARDED_TOKEN_LITERALS` (`:92-105`) declare exactly four,
ordered so the first match at a token wins and no sequence is a prefix of another.

| Verb | The only form that validates | Source lines |
|---|---|---|
| `git push` | `git push origin <branch>` or `git push -u origin <branch>`, nothing else — argv of exactly 4 or 5 tokens. `<branch>` must pass `git check-ref-format --branch`, not begin with `-`, contain no `:` or `+` (refspecs and force-pushes are named as such), none of `;&|<>$`, backtick, backslash, newline, CR, `*?[]{}()#~`, and no path component in `refs`/`heads`/`tags`/`remotes` — so `refs/heads/main` and `heads/main` are refused as namespaced refs, never compared as plain names. And it must not be the default branch. | `:664-687`; `branch_name_problem` `:564-590`; `REF_NAMESPACE_COMPONENTS` `:130`; `UNSAFE_BRANCH_CHARS` `:132` |
| `gh pr create` | Exactly 13 argv tokens — `gh pr create --repo <repo> --base <base> --head <head> --title <title> --body <body>` — those five flags in that order. `--repo` must equal the detected `origin` slug; `--base` must be in the authorized base set; the head must pass the branch rules and differ from the base; the title rejects newlines, the body allows them, both reject `"`, `$`, backtick, backslash, NUL, CR and unpaired surrogates. | `:690-730`; `PR_CREATE_FLAGS` `:123`; `free_text_problem` `:593-604` |
| `git branch -d <branch>` | Exactly that, 4 argv tokens, judged on the **whole command** so it tolerates no chaining at all — and guarded in **every** repository regardless of owner. The one verb whose guard consults no forge state. | `:636-661`; dispatched `:891-896`; the ownership carve-out is stated at `:31-32` |
| `gh pr merge` | `gh pr merge <positive integer> --repo <detected slug> --merge --delete-branch`, optionally with `--subject "<text>"` between `--merge` and `--delete-branch`. Matched twice and both must agree: as a raw string grammar and as an exact argv list. One literal prefix is tolerated and no other — `unset GITHUB_TOKEN && `, exactly that spelling — after which the remainder is still judged as the whole command, so nothing else can chain. | `:733-862`; `parse_merge_raw` `:607-633`; `UNSET_GITHUB_TOKEN_PREFIX` `:89` applied `:742-743`; argv equality `:752-759` |

## Fail-closed classes of the permission guard

`guarded_operations` (`:420-463`) splits the command into shell segments
(`split_segments`, `:237-319`), tokenises each (`tokenize_segment`, `:321-379`) and
marks where a simple command starts (`command_position_flags`, `:386-409`). It then
refuses:

- **an unparseable command** — an unterminated quote or heredoc makes
  `split_segments` return `None`, and every guarded literal appearing anywhere in
  the string is refused (`:430-432`, via `unvalidatable` `:411-418`);
- **a segment that cannot be tokenised** — the same treatment (`:435-438`);
- **shell source handed to an evaluator** — a segment whose command position holds
  `eval`, `sh`, `bash`, `zsh`, `dash` or `ksh` (`SHELL_EVALUATORS`, `:119`), because
  arbitrary shell cannot be parsed here (`:441-448`);
- **a guarded verb outside a command position** — an argument to `xargs`, `timeout`
  or any other program, refused with a message saying to quote it if only a mention
  was meant (`:455-461`);
- **an unresolvable repository or default branch** — `detect_repository` returning
  `None` is "outside standing authorization" (`:541-542`), and a `base_branch` of
  `None` blocks push, PR creation and merge alike (`:683-684`, `:720-721`,
  `:760-761`);
- **a child timeout** — the branch-format, PR-lookup, protection-lookup and both
  `jq` children each block on `TimeoutExpired` (`:657-658`, `:776-777`, `:801-802`,
  `:839-840`, `:858-859`); the default child budget is 5 s (`:870`), inside the
  hook's own 30 s timeout (`:954`);
- **non-zero or unparseable child output** — a failing `gh` or `jq` blocks with a
  bounded diagnostic (`:778-779`, `:803-804`, `:841-842`, `:860-861`), and a PR
  payload whose `baseRefName` will not parse blocks too (`:810-812`); and
- **any unexpected exception at all** — the top-level handler prints it and exits 2
  (`:911-919`).

A mention that is one quoted token, a heredoc body, and a comment are each not a
command and none triggers the guard: quoted interiors stay inside their own token
(`:322-345`), and comments and heredoc bodies are dropped during segmentation
(`:263-296`).

## Prototype reference verification, verbatim

Run 2026-09-02 in the worktree the root's `## Observation basis` names.

```
$ git cat-file -e dc98ba9b6bafaf7b5373cc7595ef79a5526846d1^{commit} && echo reachable
reachable
$ git cat-file -e b49c8771cbaf87eefc5f0d385100e205060538d9^{commit} && echo reachable
reachable
$ git ls-remote origin | grep prototype
b49c8771cbaf87eefc5f0d385100e205060538d9	refs/heads/worktree-prototype-nix-config-adoption-dry-run
dc98ba9b6bafaf7b5373cc7595ef79a5526846d1	refs/heads/worktree-prototype-release-transactions
$ git ls-tree --name-only dc98ba9b6bafaf7b5373cc7595ef79a5526846d1 | grep prototype
prototype-release-transactions
$ git ls-tree --name-only b49c8771cbaf87eefc5f0d385100e205060538d9 | grep prototype
prototype-agent-adoption-dry-run
```

## Issue #86 and #79 comment records

Read 2026-09-02 with `gh issue view <n> --repo fagenorn/nix-config --comments` and
`gh issue view <n> --repo fagenorn/nix-config --json comments`.

Read on 2026-09-02 with
`gh issue view 86 --repo fagenorn/nix-config --comments` and
`gh issue view 86 --repo fagenorn/nix-config --json comments`, #86 (`CLOSED`
2026-08-21T10:45:34Z) carries two comments, and the claim is split across them:

- the **"Prototype ready for human review"** comment
  ([`#issuecomment-5368826198`](https://github.com/fagenorn/nix-config/issues/86#issuecomment-5368826198),
  2026-08-21T10:43:44Z) writes "(commit `dc98ba9`, **not pushed** — it lives in the
  local worktree)";
- the **Resolution** comment
  ([`#issuecomment-5368847234`](https://github.com/fagenorn/nix-config/issues/86#issuecomment-5368847234),
  2026-08-21T10:45:32Z) writes "(commit `dc98ba9`, **local worktree**
  `worktree-prototype-release-transactions`)" — it repeats the local-worktree
  framing but, precisely, does not itself repeat the words "not pushed".

For contrast, and so the correction is not read as a pattern: #79's two comments
make no such claim. Neither contains "not pushed" nor "local worktree", tested with
`gh issue view 79 --repo fagenorn/nix-config --json comments --jq '.comments[] | {notpushed: (.body|test("not pushed")), localworktree: (.body|test("local worktree"))}'`,
which returns `false` for both fields on both comments. Only #86 needs correcting.
