"""Claude Code's PreToolUse lifecycle guard for Bash, file edits and MCP tools.

The claude-code module's store wrapper clears NIX_PYTHON* and runs this file
under `python3 -I` with `--base-policy` naming the store base policy, the only
source of the trusted members, and `--policy` naming the compiled policy at
`~/.agents/state/guard/policy.json`, which supplies derived rows alone. The
wrapper also passes `--derive-bin`, the row check the guard runs for a
repository with a compiled row before it relies on that row. Any of the three
flags given after the wrapper's own replaces it, which is how a test loads
fixtures.
Standard library only: it imports nothing from the repository's helper package,
`agent_tools`.

The decisions behind the rules below are the records in `docs/areas/guard/adr/`
(ADR-guard-001 to ADR-guard-012), and the compiler that writes the compiled
policy is documented in `python/agent_tools/guard/guard_policy.py`.

Segments, tokens and verbs
--------------------------

The hook splits the command into shell segments, tokenises each one, and
adjudicates a verb wherever a simple command starts: after `(`/`{`/`` ` ``/`$(`/a
`case` arm, after `!`/`time`/`then`/`do`, and behind `command`/`env`/`sudo`-style
wrappers, stepping over their option arguments (`env -u NAME`, `sudo -u user`,
attached and long forms included). It compares token values, so `git  push`,
`git<TAB>push` and `"git" push` all count. A word whose basename is `git` starts
a git invocation (a git word that is not a `push` or `branch -d` is judged by
Transmitting git invocations below): with no global option, or one `-C <dir>`,
the word after them is its subcommand (`push`, or `branch` then `-d`), and with
any other global option a `push` or `branch -d` anywhere among its words counts.
A word whose basename is `gh` counts when its first two words are `pr merge`,
`pr create`, `release create` or `release new`, or when a flag comes before the
path's second word and both path words occur in order, so `gh --repo a/b pr
merge 1` counts and `gh pr view 1 --json mergeable` does not (issue 400).

Such an invocation is refused before any repository lookup, its problem ending
`run git and gh by name, and carry a directory only as git -C <dir>` and followed
by the accepted-forms clause (see Adjudicated verbs below), when its program is
named by a path, or it carries a git global option other than one `-C`, a
repeated `-C`, or a `-C` directory holding whitespace, a quote or a
shell-active character, or when its run reaches a shell substitution, expansion
or grouping before its verb is certain: a git run still inside its global
options or carrying a global option other than `-C`, whose value the walk cannot
bound (`git -c k=$(…) push …`), or a gh run carrying a flag or ending before its
third word (`gh pr --repo $(…) merge …`). Then the verb's words among the rest
of the command's words count, across segment boundaries, so `git -C $(pwd |
cat) push …` blocks, also when a segment it crosses is judged on its whole text
as evaluator source or an `env -S` payload (`git -C $(sh -c pwd | cat) push
…`), and the reason names that invocation continuing past the substitution
(issue 400 D15, D18, D19). A word taken as a `-C` value is an argument of git,
never a program; a gh flag between the path words is left to the verb's
grammar.

A mention that is one quoted token (`echo "gh pr merge …"`), a comment, or a
heredoc body the guard reads exactly is not a command and never triggers it.
The guard reads a heredoc exactly only when its delimiter is a bare word
without quotes, backslashes, `$` or backticks, one single-quoted span, or one
double-quoted span without a shell-active character, and, under a bare-word
delimiter, the body holds no `$`, backtick or backslash (the shell runs
substitutions there). Any other heredoc (ANSI-C `$'EOF'`, locale `$"EOF"`,
mixed quoting, escapes, an expanding body) makes the command unparseable, so a
verb anywhere in its text, body included, is refused (issue 651).

Everything the tokeniser cannot vouch for is refused rather than waved
through: an unparseable command, shell source handed to an evaluator
(`eval`/`sh -c`, matched by basename, so `/bin/sh -c` too), a segment in which
`env` takes `-S`/`--split-string` (judged on its whole text, since env appends
the remaining words to the split command), and a guarded verb sitting in a
non-command position (an argument to `xargs`, `timeout`, …) all block. In such
raw text a verb counts when its words occur in order, the first by basename,
with the text read twice (words split at whitespace, quotes and shell-active
characters; and again with quotes and backslashes deleted, since the shell
glues the pieces into one word) and an attached `-S` payload read as a word,
and it also counts when its words joined by one space occur as a substring of
the text or of the text with quotes and backslashes deleted, so `sh -c 'git -C
x push …'`, `sh -c "g''it push …"`, `env -Sgit push …`, `eval "${CMD:-git push
…}"` and `sh -c "git branch -df x"` block too.

The tokeniser approximates bash rather than being bash, which is why it
refuses whatever it cannot parse. `tests/test_claude_permission_guard.py`
carries an adversarial table, one case per class of "the parser and the shell
might disagree", that any change to the guard must keep green.

Detaching words
---------------

Before any of the rest, and before its policy loads, the hook refuses the
detaching words `nohup`, `setsid` and `disown` in every repository (#278),
naming the Bash tool's `run_in_background: true` as the route. Since issue 656
it reads no shell syntax for this. A command is refused when one of the words
appears as a whole word in its raw text, in any case. A whole word has no ASCII
letter, digit, `_` or `-` after it, and none before it except `c` or `s`, which
covers env's attached `-S` and `su -c`; a `$` and one digit, `!`, `@` or `*`
before it also bound it (`$1nohup`), and a `-` default-value operator does too
(`${x:-nohup}`, `${x-nohup}`, whatever the parameter, `${@:-nohup}` and
`${a[0]:-nohup}` included, and with the word rebuilt as the deletion copy below
rebuilds it, `${x:-no''hup}` and `${x:-'n'ohup}`). The same test runs on a copy
of the text with backslash-newlines deleted, then every `$` before a quote and
every `\\`, `'`, `"`, `{`, `}` and `,` (`no''hup`, `no$''hup`, `no{,}hup`). The
refusal names the earliest hit.

Only two read-only forms are admitted, each read in the issue-418 word grammar
with every option enumerated. One is a single plain `grep` or `rg` call that
holds the word only in its search pattern. An option outside the table refuses
the admission, such as `-f`, `--files`, or rg's `--pre`, `--hostname-bin` and
`-z`. The other is one `gh issue|pr create|comment` call, optionally after the
`unset GITHUB_TOKEN && ` scrub, that holds the word only in a quoted
`--title`/`-t`/`--body`/`-b` value, with no other options than `--repo`,
`--base` and `--head`. Any other mention, a heredoc body, a comment,
`nohup.out` and a word handed to `xargs` or `timeout` are refused; a trailing
`&` passes, and so does a slugged branch or worktree name such as
`issue-7-refuse-nohup`. A commit message that names a word is refused; reword it
or use `git commit -F`.

Transmitting git invocations
----------------------------

A git invocation that could transmit refs and is not an admitted lifecycle form
is refused as a push (issue 655). `push` and `branch -d` keep the recognition
above and its messages; every other `git` word, and every word whose basename
starts with `git-`, is judged by `git_transmit_problem` and refused as
`lifecycle guard: unsafe push: <problem>; accepted: <push forms>; optional
prefix: …`. The guard never reads git configuration, so an alias is refused by
its name, not by what it resolves to. The refusal comes after the
lifecycle-grammar check (a command that also holds a lifecycle verb keeps its
grammar refusal) and before any repository context is built, so no git, gh or
row-check child runs.

What is refused:

- A global option outside `GIT_GLOBAL_OPTIONS`, a closed table of each option
  and the number of words it takes (an attached `=value` counts only for the
  one-word long options). `-c`, `--config-env`, `--exec-path=<dir>` and any
  unknown option are refused for every subcommand, because a `-c` value such as
  `core.pager`, `core.fsmonitor` or `core.sshCommand` runs a command from any
  of them.
- A subcommand outside `GIT_LOCAL_SUBCOMMANDS`, a closed list of the
  subcommands that cannot transmit refs: an alias (repository, global or `-c`
  config), an external `git-<name>` program, a transport (`send-pack`,
  `http-push`, `subtree`) and the subcommands that run a caller-supplied command
  (`submodule`, `bisect`, `filter-branch`, `difftool`, `mergetool`).
- A `git-<name>` program in any spelling (`git-push`,
  `/usr/libexec/git-core/git-send-pack`, `git-lfs`), since one on `PATH` is an
  alias by another spelling. An argument such as a branch or path named
  `git-<x>` is refused too, inside an otherwise admitted lifecycle command as
  well, once its grammar check has passed; this workflow's branches start with
  `issue-`.
- A git run cut by an opening operator (`(`, `{`, or a backtick with an even
  number of backtick tokens before the git word in its segment) before its
  subcommand is certain: no subcommand word remains, or the subcommand is the
  last word and may be glued to the substitution (`` git add`echo -x` `` runs
  the alias `add-x`). `git $(printf p) origin x` and `git -C $(pwd) status` are
  refused; `(git status)`, `` `git status` ``, `echo $(which git)` and `git log
  $(printf HEAD) -1` pass.
- A bare git word (no subcommand after its global options) whose subcommand the
  shell supplies from elsewhere: at an argument position in a command where a
  pipe comes before it or a redirection (`<`, `<<`, `<<<`) appears anywhere,
  whichever segment or grouping the pipe or redirection belongs to (`echo p
  origin t | xargs git`, `echo p | { true; xargs git; }`, `{ xargs git; } <<<
  'push …'`, `exec <f; xargs git`, a pipe followed by a newline, also inside
  evaluator text), whether the git word is plain, the last word `"$(which
  git)"` or `${G:-git}` (the brace forms `${G-git}` and `${G:=git}` too), and a
  git word that is the output of an unglued `$(…)` or backtick substitution that
  words follow (`$(echo git) p origin t`, `xargs $(echo git) p`, a substitution
  that ends the segment before it closes, and the quoted `"$(which git)" push
  …`). `which git`, `brew install git`, `echo $(which git)` and `xargs git
  status` pass; so does `x="$(which git)" y`, whose output is assigned.
  `ps aux | grep git`, `echo $(which git) status` and a `which git` that follows
  a pipe or shares a command with a redirection are refused; write `grep
  '[g]it'`.
- A command option hidden from the option scan: the scan also reads a word that
  holds an expansion and does not start with `-` (`"${X:---exec=sh p.sh}"`, a
  `-` after one of `:=+?-` starts a candidate), and the words that follow the
  operator which cut the run (`git rebase $(x) --exec …`).
- `git config` naming `core.hooksPath` (issue 672 D8): any later word of the
  invocation, the words after an operator in the same segment included, that
  equals `core.hookspath` or starts with `core.hookspath=`, compared lowercase,
  so the get, set and unset spellings, `--global`, `--local`, `--file` and `git
  config set`/`unset` all refuse as `git config naming core.hooksPath would
  change which hook judges a push; read it with git rev-parse --git-path
  hooks`. Any other key passes, `git config --get core.hooksPathX` included.
  `--no-verify` and `-n` on `git push` stay refused as an unsafe push form.
- Clearing the agent session marker (issue 672 D3), in every repository: a
  segment refuses with `clearing or unsetting CLAUDECODE would hide the agent
  session from the pre-push hook` when a non-operator token assigns
  `CLAUDECODE` in any position (a prefix, a standalone assignment, an
  `export`/`declare`/`typeset`/`local`/`readonly` argument), when a token is
  exactly `CLAUDECODE`, `-uCLAUDECODE` or `--unset=CLAUDECODE` (`unset [-v]`,
  `export -n`, `declare +x`, `env -u`), when an `env` word has `-`, `-i`,
  `--ignore-environment` (or a prefix of it) or a short cluster holding `i`
  among its options, when an `env` unset option names it in any spelling (`-u
  CLAUDECODE`, `-vuCLAUDECODE`, `--unset CLAUDECODE`, an abbreviation such as
  `--unse=CLAUDECODE`), or when an `exec` word has a cluster holding `c`; the
  same tests apply to evaluator text, so `sh -c 'unset CLAUDECODE; …'` and `sh
  -c 'env -i ./push.sh'` refuse. A read (`$CLAUDECODE`) never refuses. A
  bare-word mention such as `printenv CLAUDECODE` refuses too; write `echo
  $CLAUDECODE` instead.

The same rule judges a git word at a command position, at an argument position
and in raw text. At an argument position it is `git_argument_problem`, whatever
runs the word (`xargs git p`, `timeout 5 git p`, `find -exec git p`); the guard
keeps no list of runners. Evaluator text (`eval`, `sh -c`), `env -S` text and
unparseable or untokenisable text is split at `;`, `&`, `|` and newlines, and
each piece's raw words, in both quote readings, are walked from every raw git
word: one whose text ends in `git` after nothing or after `/`, `:`, `=`, `+`,
`?` or `-`, so `${X:-git} p` is caught. The reason such a refusal reports is the
evaluator's or the `env -S` one. A mention is judged like a command: `rg -n git
README.md`, `echo git p` and `nix-shell -p git jq` are refused. Write a mention
so that no word is a bare `git` followed by a non-local word (`rg -n '[g]it'
README.md`, `echo 'git p'`); a `git` followed by nothing (`which git`, `brew
install git`) passes.

Spellings of a git word that the shell resolves are read too: the word after
`$` (`$'git' p`, which tokenises to `$git`), a line continuation (`git\\<newline>
p` is `git p`, in tokenised and raw text alike), a variable the command itself
assigns a git word (`G=git; $G p`, `export G=/usr/bin/git; "$G" p`, `${G} p`)
or the output of a substitution that holds one (`G=$(which git); $G p`), a name
that `hash` or `alias` binds to git (`hash g=/usr/bin/git; g p`, `alias g=git; g
p`), zsh's `=git p` expansion of the command's path (one leading `=` is
stripped), the braced default `${G:-git} p` at any position, and a git word
inside a double-quoted `$(…)` or backtick substitution, refused as `a command
substitution inside a quoted word cannot be validated` when its text would be
refused as raw text. A command that has an evaluator at a command position is
also scanned as a whole, heredoc bodies included, because that evaluator may
read its source from stdin (`echo 'git p origin t' | sh`, `sh <<'EOF'`).
Evaluator text carries the same spellings: names it assigns itself or inherits
from the command (`sh -c 'G=git; $G p'`, `G=git; sh -c '$G p'`), and a third,
quote-aware reading of each piece in which a quoted global-option operand is one
word (`sh -c 'git -C "/tmp status" p origin t'`) and a word holding several
words is read again as text.

Command-running options. An allowlisted subcommand is still refused when it
carries an option whose value git runs as a command, from
`GIT_COMMAND_OPTIONS`: `archive --exec`, `clone
--upload-pack`/`-u`/`--config`/`-c`/`--template`, `fetch`/`pull --upload-pack`,
`grep --open-files-in-pager`/`-O`, `init --template`, `ls-remote
--upload-pack`/`-u` and `rebase --exec`/`-x`. `git_command_option` matches a
`--` word by its part before any `=` when that part has three or more
characters and a spelling of the subcommand starts with it (git accepts `--exe`
and `--upload`), and a short word when any letter of its cluster is a short
spelling (`-ix`, `-Osh`). Every word after the subcommand is scanned, an option
value or an operand after `--` included, so a lookalike can only refuse more.
The check runs inside `git_transmit_problem`, so it applies at a command
position, an argument position and in raw text alike.

Environment assignments. An assignment that hands git a command or other
configuration is refused as a push in two places. (a) Every assignment before a
git word, up to the last operator (`X=1 git …`, `env X=1 git …`, `timeout 5 env
X=1 git …`), must name a variable in `GIT_ASSIGNMENT_ALLOWED` (tracing, author
and committer identity, pathspec switches, locale, `TZ`, `TERM` and similar);
`PATH`, `HOME`, `GIT_SEQUENCE_EDITOR`, `GIT_SSH_COMMAND`, `GIT_EXEC_PATH` and
every `GIT_CONFIG_*` name are not in it. (b) Anywhere in the command, including
`export` and `declare` arguments, a standalone assignment, and the raw text of
an evaluator or quoted substitution, a name starting with `GIT_` that is not
allowlisted, or one of `GIT_COMMAND_VARIABLES` (`EDITOR`, `VISUAL`, `PAGER`), is
refused.

Adjudicated verbs
-----------------

The verbs the guard adjudicates are validated against the live repository:

- `git push` only as `git push [-u] origin <branch>` onto a non-default branch
  with no force/delete/mirror flags, no refspecs and no namespaced refs
  (`refs/heads/main` and `heads/main` name the default branch too; the two
  exceptions are the tag-push and remote-deletion arms below).
- `gh pr create` only as the exact `--repo/[--draft]/--base/--head/--title/--body`
  form (issue 671: `--draft` stands right after `--repo <slug>`, in both body
  spellings, and nowhere else), with no shell-active character outside quotes
  (issue 386, so an unquoted title cannot redirect or brace-expand) (or, issue
  386, with `--body-file <path>` in place of `--body`, only when that PR
  creation is the whole command after any scrub prefix, the path absolute, free
  of whitespace, shell-active characters and `..`, outside `/dev/` and `/proc/`
  (case-folded) before and after resolution, and resolving, case-folded,
  outside the working tree, which fails closed when the tree cannot be read;
  this is a placement check that refuses obvious in-tree paths) whose repo is
  the target repository's slug and whose base is `origin/HEAD`'s branch.
- `git branch -d <branch>` (guarded globally, in every repo).
- `gh pr merge <n> --repo <target repository slug> --merge [--subject
  "<subject>"] [--match-head-commit <sha>] --delete-branch`, flags in that
  order, `<sha>` one separate word of exactly 40 lowercase hex characters
  (issue 402) that must also be the PR's head commit (the mergeability check
  below, issue 476), or, in a repository with a declared integration branch,
  the release arm: the same form without `--delete-branch`, only the
  integration branch merged into the default branch, gated on a fully green
  check rollup instead of forge protection; and, for a pull request whose
  issues carry a look marker, the owner's look approval of its head (the look
  gate below, issue 1138).

Each may sit behind a credential-scrub prefix (issue 400), spelled exactly
`unset N && `, `unset N M && `, `env -u N ` or `env -u N -u M ` with single
spaces and `N`, `M` distinct members of the credential-name set `GITHUB_TOKEN`,
`GH_TOKEN` (`unset GITHUB_TOKEN && ` is the spelling derived from
`bindings.tracker.credential_env.unset_before_invocation`'s exhaustive
credential-name list), stripped from the start of the whole command so the
remainder is still judged whole and nothing else can chain. `git push` and `gh
pr create` take the `env -u` spellings at the start of their own segment (the
`unset` spelling is an earlier segment there), `git branch -d` takes none, and
any other `env` option or assignment, `--`, `--unset=` or attached `-uN`
spelling, repeated name or doubled space leaves the text whole for the grammar
to refuse.

The four repository-bound verbs (every one but `git branch -d`) additionally
require the repository to be inside standing authorization, which means its
owner is in the base policy's `authorized_owners` or the repository itself has
a derived row that the row check confirmed in this invocation, and merging
further requires an open PR based on the default branch (or the repository's
declared integration branch, which comes from a literal base-policy
`integration_bases` row or from a confirmed derived row whose two branches
differ). A default-branch base additionally demands live protection with at
least one required status check and admin enforcement on the feature arm (or,
where the forge answers that the repository's plan cannot protect the branch,
the plan-gated floor below), while a declared integration base is deliberately
exempt from the protection demand: it is the development-pace branch, and its
CI gate stays in the shipping flow's wait-for-checks.

`git push` and `git branch -d` also take one `git -C <dir>` directly after
`git` (issue 400), `<dir>` one unquoted word without whitespace, quotes or
shell-active characters, a relative one joined to the payload `cwd` without
normalisation: the guard strips it to the canonical command and builds a push's
repository context (origin slug, `origin/HEAD`, the derived-row lookup and row
check, and the tag lookup) from that directory, one context per distinct
directory in a command under the one invocation deadline, while branch deletion
checks only its spelling; an unresolvable directory is an unknown repository,
refused as outside standing authorization. The merge's own `gh` lookups run
with `GITHUB_TOKEN`/`GH_TOKEN` scrubbed from their environment, so they
authenticate via the gh keyring credential (whose reach covers every
authorized owner) rather than any ambient environment token, which gh would
prefer and which may be narrower; a machine with no keyring auth fails closed
at the lookup.

There is no defer path: once the hook adjudicates a verb it is
validated-and-allowed or blocked, never handed back to the allowlist
unexamined, and every uncertainty (unknown repo, unresolvable default branch,
child timeout, non-zero or unparseable output) blocks.

Every accepted spelling has one home, `FORM_TABLE` in this file (issue 402),
each operation's forms in its template notation (`<slot>` one word, `"<slot>"`
one free-text word that may begin with `-`, a slot closing a literal word,
`[…]` an optional group led by its flag, a parenthesised note never matched)
with three properties: whole-text characters (push and branch deletion), exact
spelling (merge and release creation: single spaces, double-quoted free text)
and scrub prefix (every operation but branch deletion). The table is compiled
first on every invocation inside the unexpected-failure handler, so a template
that does not compile refuses every Bash call with exit 2 and fails `just
build`; one shared matcher judges each canonical command against its
operation's forms in table order, and `canonical_text` reads the scrub-prefix
property.

The remote-deletion arm (issue 458) is the push verb's third form, judged after
the tag and branch arms: exactly `git push origin --delete refs/heads/<branch>`,
with the push verb's whole-text character rule, credential-scrub prefixes and
one `git -C <dir>`. The `refs/heads/` literal is the point: git resolves a bare
`--delete <name>` against the remote's refs and deletes a tag when only a tag
matches, while the qualified name can only be a branch, so the bare spelling
stays refused (`missing refs/heads/<branch>`). After standing authorization the
value takes the branch arm's name rule (so `refs/heads/refs/heads/x` is a
namespaced ref), then needs a resolvable `origin/HEAD`, and the default branch
and the repository's declared integration branch are refused as `unsafe push:
refusing to delete the permanent branch <branch>`. The arm reads no forge
state: GitHub itself refuses to delete a protected branch, and the delivery's
ship stage runs the deletion only after verifying the merge and seeing `git
ls-remote --heads origin <branch>` non-empty.

The effective push URL (issue 655) is checked on every push arm, after
`ownership_problem` and after the form matches, before the tag, branch or
remote-deletion arm runs. The guard runs `git -C <dir> remote get-url --push
--all origin` (`PUSH_URL_LOOKUP`) in the judged directory and in the hook's own
environment, so the git configuration that applies to the push is the one the
lookup reads (D13). git applies `remote.origin.pushurl`, `url.<base>.insteadOf`
and `url.<base>.pushInsteadOf` itself; the guard never reimplements the
rewriting. Every URL the lookup prints (`--all` lists each `pushurl` entry, and
git pushes to all of them) must parse as a GitHub URL (`git@github.com:`,
`ssh://git@github.com/`, `https://github.com/` or `http://github.com/`, one
optional trailing `.git`) whose owner/name slug equals the repository the guard
judged; a URL that is not GitHub, or names another repository, is refused as
`unsafe push: origin's push URL <url> does not name <owner/name>`. A lookup that
times out is refused as `unsafe push: push URL lookup timed out`, and one that
cannot start, exits non-zero or prints nothing as `unsafe push: cannot resolve
origin's push URL`. Each is a state refusal with no accepted-forms clause,
since no rewording of the command changes it; a push whose text matches no form
keeps its text refusal with accepted forms, whatever the push URL. PR creation,
merge, release creation and branch deletion never run the lookup.

The forge adapter's two mutations are adjudicated too (#124, D9/D10). The
tag-push arm sits inside the push verb and is judged before the branch arm:
argv exactly `git push origin refs/tags/<tag>` with `<tag>` a SemVer
`vMAJOR.MINOR.PATCH` (no leading zeros), standing authorization, and `git
cat-file -t refs/tags/<tag>` (the base policy `git`, in the push's target
directory: its `git -C` directory, else the payload `cwd`) printing exactly
`tag`, so only an existing annotated tag is pushed; any other namespaced push
keeps its refusal, except the remote-deletion arm's qualified
`refs/heads/<branch>`, and the branch arm, including the legacy `git push
origin <tag>`, is unchanged. Release creation (`gh release create`, operation
`release`, label "release creation") is judged on the whole command like the
merge, behind the same optional credential-scrub prefix: exactly `gh release
create <tag> --repo <detected slug> --verify-tag --title "<title>" --notes-file
<path>`, flags in that order and nothing before or after, a SemVer `<tag>`,
standing authorization, a title that passes the same free-text check as
`--subject`, and an absolute `<path>` without whitespace or any shell-active
character. `--target`, `--draft`, `--prerelease` and every other flag are
refused, and so is gh's alias `gh release new` (it routes to the same arm,
whose grammar spells `create`). The feature arm of `gh pr merge` also refuses
`--delete-branch` when the PR's head is the default branch or the repository's
declared integration branch (`unsafe merge: --delete-branch would delete the
permanent branch <head>`), judged after the PR lookup and before any protection
lookup, and a head that is missing, null, empty or not a string is refused as
`cannot read the PR head branch` (#116 D5). The guard is on `PATH` as
`claude-bash-lifecycle-guard` (`home.packages`) so the adapter and the resolver
find it by name; the registered hook path is unchanged. The spelling fixture
`tests/fixtures/forge-adapter-spellings.json` drives both the adapter suite and
the guard's allowed-row table; the guard never reads it at run time. The shape fixture `tests/fixtures/guarded-command-shapes.json` (#351) lists the push (remote deletion included), merge and branch-delete forms the delivery's ship stage spells and the dressed shapes agents reach for, each with the guard's verdict bare, behind `unset GITHUB_TOKEN && ` and behind `env -u GITHUB_TOKEN `; only the guard suite's shape table in `tests/test_claude_permission_guard.py` reads it (no skill-text check reads it any more, so a ship-stage spelling is not checked against it), and the guard never reads it either; its `invocation_shapes` section (issue 400) holds the guard-only rows. `form_values` (issue 402) is guard-only too: one value per guard placeholder, from which the guard suite fills and runs every form a refusal prints.

The mergeability check (issue 476) reads two more facts from the same PR
lookup, whose `--json` field list is
`state,baseRefName,headRefName,headRefOid,mergeStateStatus,url,statusCheckRollup`.
Each merge arm runs it after its own shape judgment (the feature arm's
permanent-head refusal, the release arm's integration-into-default check) and
before its first gate (the feature arm's integration-base exemption and
protection lookup, the release arm's rollup predicate), so a PR merged onto a
declared integration base meets it before the exemption. A `mergeStateStatus`
of exactly `BEHIND` is refused first, as `unsafe merge: the PR is behind its
base <base>; repair: sync the branch with <base>, push it and wait for its
required checks before merging`; then, only when the command carries
`--match-head-commit`, a value other than the PR's `headRefOid` is refused as
`unsafe merge: --match-head-commit <given> is not the PR head commit
<headRefOid>; merge only a head you reviewed`. Any other non-empty merge state
passes, `UNKNOWN`, `BLOCKED`, `DIRTY` and `UNSTABLE` included, and the check
reads no protection setting. A `mergeStateStatus` that is missing, not a string
or empty is refused as `cannot read the PR merge state`, and, with the flag, a
`headRefOid` that is not 40 lowercase hex characters as `cannot read the PR
head commit`; without the flag `headRefOid` is neither read nor demanded.
GitHub stays the authority: it still compares `--match-head-commit` atomically
with the merge and enforces its own up-to-date rule, which closes the window
between this check and the merge.

The look gate (issue 1138) holds a merge whose issues await the owner's look.
Each merge arm runs it right after the mergeability check, so before the
feature arm's integration-base exemption and protection lookup and before the
release arm's rollup predicate, with the matched PR number (the release arm
receives it as `validate_release_merge`'s last parameter).
1. The guard reads the PR's title, body, commits and linked issues, `gh pr view <n>
   --repo <slug> --json title,body,commits,closingIssuesReferences`.
2. The PR's issues are the number in an `issue-<n>-` head branch, every issue
   of this repository in `closingIssuesReferences` (the Development sidebar and
   `gh issue develop` links), plus every closing keyword GitHub honours
   (`close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`, `resolves`,
   `resolved`) or `Refs` (any case, an optional colon) in the PR title or body, in a
   commit message (headline and body), in the head branch name or in the merge's
   `--subject` (GitHub closes on the merge commit too, whose default body is the PR
   title) followed by `#<n>`, `<slug>#<n>` or
   `https://github.com/<slug>/issues/<n>` for this repository's slug; a
   reference naming another repository is ignored. A PR of
   `LOOK_COMMIT_LIMIT` (100) commits or more is refused as unreadable, since
   the lookup returns no more than that many. No issue: the merge is
   judged exactly as before, with no further child.
3. For each issue it reads `gh api repos/<slug>/issues/<n>` and
   `gh api --paginate --slurp repos/<slug>/issues/<n>/comments?per_page=100`
   (pages flattened in order), and takes the PR's `headRefOid` when it is 40
   lowercase hex characters, else none.
4. It runs the look check, the store script `--look-bin` names
   (`look-approval judge`), with `{"pr", "head", "issues": [{"number", "body",
   "comments"}]}` on stdin and the row check's scrubbed environment. Exit 0 with
   verdict `admit` and a `marked` array of integers passes, except that when
   `marked` is not empty the merge must carry `--match-head-commit` (held equal to
   the PR head by the mergeability check, so GitHub's atomic head match decides
   the head that merges): without it the merge is refused as `unsafe merge: issue
   <n> awaits the owner's look, so the merge must carry --match-head-commit
   <head>, the head the owner approved`. Exit 1 with verdict `refuse` and an integer `issue`
   refuses as `unsafe merge: issue <n> needs the owner's look before merge, and
   head <first seven characters> has no recorded approval; ask the owner and
   record the answer`, or, with no readable head, as `unsafe merge: cannot read
   the PR head commit`. Anything else (another exit, output that is not that
   verdict) is `look check failed: <child diagnostic>`; a missing `--look-bin` is
   `look check failed: no --look-bin was given`; a timeout is `look check timed
   out`.
5. A kept approval (issue 1211). When run one refuses with an integer `issue`, a readable
   head and a non-empty `candidates` list of objects (each an integer `issue`, a 40
   lowercase hex `head` and an `answer` of `approved` or `fix`), the guard reads the
   base branch's tip once, `gh api repos/<slug>/branches/<baseRefName>` and its
   `commit.sha` B (40 lowercase hex; a PR with no string `baseRefName` or a base it
   cannot read has no carry). It then runs the look check up to `LOOK_CARRY_RUNS` (3)
   more times with run one's payload plus `"carry": {"base": B, "reads": {<path>:
   <JSON>}}`, `reads` empty at first. An admit passes under step 4's pinning rule. An exit 1
   `refuse` whose `need` is a non-empty list of paths proceeds when this is not the last
   run, no path was read already, every path is `compare/<sha>...<sha>` (full
   lowercase shas, matched in full) or exactly `contents/.github/look-files.json?ref=<B>`,
   and the reads so far plus `need` stay within `LOOK_READ_LIMIT` (48); the guard
   reads each as `gh api repos/<slug>/<path>`, in order, and the next run gets the
   answers. A path outside that grammar, a repeated path, a failed, timed-out or
   unreadable read (a `404` included), any other refusal and a run left asking
   after the last run refuse as step 4 does, `issue <n> needs the owner's look
   before merge`, with the `<n>` of run one. Any other output of a carry run is
   `look check failed: <child diagnostic>`. Nothing is read at a branch name after
   B nor at the head.
Every lookup runs with the token variables scrubbed and the child timeout; a
timed-out lookup is `PR body lookup timed out`, `issue <n> lookup timed out` or
`issue <n> comment lookup timed out`, a non-zero one `PR body lookup failed`,
`issue <n> lookup failed` or `issue <n> comment lookup failed` with the child's
diagnostic, and output that is not the expected shape is refused as `unsafe
merge: cannot read the PR body`, `cannot read issue <n>` or `cannot read the
comments of issue <n>`; an issue or PR object with no `body` key, a PR object
with no string `title`, no `commits` or `closingIssuesReferences` list, or an entry of either that
is not readable, is unreadable, never an empty body or an empty list. Which issues are marked, and which approvals count
(the owner's or a member's, naming this issue, this PR and this head, the
latest answer deciding), is `look-approval`'s contract; `--admin` is in no merge
form, so it is refused by the grammar before any lookup.

The plan-gated floor (issue 552) replaces that protection demand for one answer
only. When the feature arm's protection read of the default branch exits
non-zero, the guard parses its stdout, gh's response body, and never its
stderr: the plan-gated answer is a JSON object whose `status` is the string
`403` and whose `message` is exactly `Upgrade to GitHub Pro or make this
repository public to enable this feature.`. Only with that answer, and only
when the repository's confirmed derived row declares at least one required
check (a row with a problem, a literal `integration_bases` row and a repository
without a row declare none), is the merge judged by the floor; every other
non-zero answer (a 404 `Branch not protected`, a 403 for missing admin rights
or a rate limit, a body that is not JSON, the plan-gated answer without
declared checks) keeps `protection lookup failed: <diagnostic>`, and a timeout
or a readable protection object keeps its verdict. The floor starts no child
and reads only the PR lookup's facts, and the first failure is the verdict: the
merge must carry `--match-head-commit`, which the mergeability check has held
to the PR's `headRefOid`, so the rollup judged is the head GitHub merges
(`unsafe merge: <base> cannot be protected on this repository's plan, so the
merge must carry --match-head-commit with the reviewed PR head`);
`statusCheckRollup` must be a list of objects, each a `CheckRun` with a string
`name` or a `StatusContext` with a string `context` (`unsafe merge: cannot read
the PR check rollup`); then each declared check, in row order, must be named
exactly by at least one entry (`unsafe merge: <base> cannot be protected on
this repository's plan, and the declared required check <name> is missing from
the PR's check rollup`), and every entry naming it must be green (`unsafe
merge: <base> cannot be protected on this repository's plan, and the declared
required check <name> is not green (<observed>)`, the first non-green entry as
`CheckRun <status>/<conclusion>` or `StatusContext <state>`, a fact that is not
a string shown as `none`). Entries naming no declared check are ignored. Green
has one home, from which the release arm's jq predicate is rendered: a
`CheckRun` whose `status` is `COMPLETED` and whose `conclusion` is `SUCCESS`,
`SKIPPED` or `NEUTRAL`, or a `StatusContext` whose `state` is `SUCCESS`. A forge
that later protects the branch answers the read with exit 0, and the protection
demand governs again with no contract change. A guard-suite test drives the
floor end to end, with `guard-policy derive` run from source as the row check
over a fixture fleet.

A refusal that lies in the command's text (each recognition refusal, a form the
matcher refuses, a slot value, a merge arm while another arm remains) reads
`lifecycle guard: unsafe <operation>: <problem>; accepted: <form>[; or
<form>…]; optional prefix: unset GITHUB_TOKEN && | env -u GITHUB_TOKEN`, and
branch deletion, which takes no prefix, omits the last clause. The forms come
from `FORM_TABLE` in table order: before any PR lookup the whole table, except
that the merge's release form, noted `(only <integration> into <default>)`, is
listed only where the repository declares an integration branch distinct from
its resolved default branch, and after the lookup only the arm the PR admits,
none when its head is a permanent branch no arm fits. With a repository context
`<slug>` becomes the detected slug and, once the default branch resolved,
`<base>` one alternative per authorized base, and the note names both branches
(`only dev into main`); every other slot stays a placeholder, and a recognition
refusal, which builds no context, fills nothing and lists the merge's feature
form alone. The clause's two spellings stand for the whole accepted prefix set
(`unset N && `, `unset N M && `, `env -u N `, `env -u N -u M `, `N` and `M`
distinct members of `GITHUB_TOKEN`, `GH_TOKEN`). A refusal of the repository or
the forge state (authorization and row problems, an unresolvable default
branch, a default-branch push, a permanent-branch deletion, head equal to base,
a tag that is not an existing annotated tag, every PR, protection and rollup
lookup or predicate failure, every look-gate lookup or unreadable answer and a
merge awaiting the owner's look, a PR behind its base, a `--match-head-commit` that
is not the PR head, every plan-gated floor refusal, an unreadable PR merge
state or head commit, timeouts, the invocation deadline) names only its
problem, since no spelling would pass there.

A lifecycle command (issue 418) is admitted only in an allowlist grammar,
checked before any other judgement once a lifecycle verb is found: `[unset
GITHUB_TOKEN && ][cd <dir> && ]<verb> <args>`, where the scrub is one `unset`
or `env -u` spelling of the credential names (its exact spelling is left to the
verb's grammar), `<verb>` is `git push`, `git branch -d`, `gh pr create`, `gh pr
merge` or `gh release create` (`git -C <dir>` before `push` or `branch -d`),
and every word is plain (`[A-Za-z0-9_./:@%+=,-]`, not beginning with `=`,
zsh's `=cmd` expansion), single-quoted, or double-quoted without `$`, a
backtick, a backslash or `!` (so an owner's ship stage and the forge adapter's
double-quoted text still passes), separated by spaces or tabs. Anything else
(another segment or operator, a redirection, an expansion, a glob, a comment, a
newline outside quotes, a quote glued to a word, a wrapper or assignment)
refuses that verb as `unsafe <operation>: <first thing outside the grammar>; a
lifecycle verb runs only alone, as ...` with its accepted forms. So the only
directory change left is that leading `cd`: push and PR creation run in the
directory it names when it is spelled `cd <dir> && ` with single spaces and
`<dir>` is absolute with no `..` component (relative names follow `CDPATH`, and
`..` is logical for `cd`), else they refuse with the `CD_PRELUDE_PROBLEM` text
(`the directory the verb runs in cannot be resolved: ...`); a `git -C`
directory joins onto it, and an absolute one stands alone. Merge, release
creation and branch deletion are judged on the whole command and so still take
no prelude.

A named repository (issue 418): a PR creation or merge whose `--repo` names a
repository other than its directory's, and which has a derived row in the
compiled policy, is judged against that repository from its row, with no
checkout read: the context is built from the slug, runs no `git` child, and
takes the row's `default_branch` as the base once the row check confirms the
row. A row the check does not confirm refuses with that row problem and never
falls back to the directory. Without a row for the slug, the directory's
refusal (`--repo ... is not the current repository ...`) stands. `--body-file`
there fails closed (`cannot resolve the working tree to check --body-file
against`), because there is no working tree to place the file against. Release
creation and pushes stay judged against their directory.

Pre-push hook
-------------

`lifecycle_guard.py --mode pre-push -- <remote> <url>` is the guard's second
entry mode (issue 672), run by git itself as a `pre-push` hook, so the judgement
does not depend on how a push is spelled: an alias, an `xargs` feed or a `git`
reached through a wrapper all arrive at the hook as the same facts, the real
push URL git resolved and one line per ref update on stdin. The hook reads
those facts only as the text mode's push forms (`PRE_PUSH_FORMS`, pinned equal
to the ids of `FORM_TABLE["push"]`) and judges them through the predicates the
text mode shares (`push_url_slug_problem`, `push_arm_problem`,
`branch_target_problem`, `annotated_tag_problem`), over the same base policy,
compiled policy and row check, so no push rule is written twice: a branch
deleted is `delete`, a branch created or fast-forwarded is `branch`, a tag
created is `tag` (its tag object is the pushed sha), and a forced update, a
moved or deleted tag and any other ref namespace match no form and are refused.
The order is standing authorization, then the push URL, then each ref line in
the order git handed them, and the first refusal wins; empty stdin admits once
the repository checks pass, and a line that is not four space-separated fields,
whose two shas are not hex of equal length 40 or 64, or that lacks its newline
is refused as `cannot read the refs git handed the pre-push hook`.

The hook judges only an agent session, one whose environment holds a non-empty
`CLAUDECODE` (Claude Code exports it to every Bash child); outside one it
judges nothing and no compiled policy or row check is read. git exports
repository-local variables to hooks (`GIT_DIR`, `GIT_WORK_TREE`,
`GIT_INDEX_FILE` and the rest of `git rev-parse --local-env-vars`), which would
make the row check's own `git` read the pushing repository in every registered
root, so `pre_push_main` reads that list with the base policy's `git` and
removes the names from the row check's environment only, in every session.
Every other `git` query the judgement makes (the repository's origin and
default branch, the fast-forward and tag checks) keeps the original
environment, so the repository git was told to push from, by `GIT_DIR` or
`--git-dir`, is the one judged wherever the hook's cwd is, including a work
tree without a `.git` and another checkout; the chained hook gets the original
environment too. A lookup that fails, times out or prints nothing refuses. A
refused ref prints `lifecycle guard pre-push: unsafe push: <problem>` on
stderr, with the text mode's problem wording, and exits 1, which aborts the
push; a malformed invocation, a bad base policy or an unreadable variable list
prints `lifecycle guard pre-push: <reason>` and exits 1, and the base policy
loads first in both modes, so an invalid store policy refuses every push just
as it blocks every Bash call. This hook is the authoritative check and the text
guard stays the first line (O1): it refuses early, with accepted forms, what
the hook would refuse late. `tests/test_git_pre_push_hook.py` runs real `git
push` through the hook against `agent_tools.guard.push_fixture`, a hermetic fixture
whose fake ssh carries `git@github.com:<slug>.git` to a local bare repository
and whose environment drops every inherited `GIT_*` variable, so no rewrite in
the host's own git configuration can reach a network.

Chaining and git-lfs (D5). A global `core.hooksPath` disables every
per-repository hook, so the hook judges first and then chains: after an
admitted agent judgement, and always outside an agent session, `chain_pre_push`
runs `<git-common-dir>/hooks/pre-push` when it is a regular, executable file
whose `realpath` differs from that of the hook git is running (a repository
hook linking to the managed one cannot recurse). The common directory is used,
not the per-worktree one, so a linked worktree runs the main repository's hook.
The chained hook gets git's argv, the identical stdin bytes, the original
environment from before the D10 scrub and the hook's own stdout, stderr and
cwd, and its exit status becomes the push's (a signal death is 1); a refused
agent push runs no repository hook and no git-lfs. When git cannot answer the
two `rev-parse` queries (non-zero, timed out or empty) the hook prints
`lifecycle guard pre-push: cannot locate the repository's own hooks` and exits
1. The other managed hooks are the POSIX shim `git-hooks/chain-hook`, one copy
per hook name with `@git@` and `@gitlfs@` filled in at build time, which
applies the same rule from `basename "$0"` and starts no process but `git` and
`realpath` before it execs. git-lfs installs its hooks into `git rev-parse
--git-path hooks`, which is now the read-only store directory, so when no
repository hook runs, `pre-push`, `post-checkout`, `post-commit` and
`post-merge` run `<git-lfs> <name> <args>` with the same stdin for an LFS
repository (a repository hook takes precedence, as git-lfs never overwrites
one), and the fallback is off when the LFS binary is empty. A repository counts
as an LFS repository when `<git-common-dir>/lfs` is a directory or `git config
--get lfs.storage` prints a value, since `lfs.storage` keeps the objects
elsewhere (the shim and `chain_pre_push` apply the same rule). A repository
`pre-push` hook that is executable text with no `#!` line runs through
`/bin/sh`, as git retries it on an exec format error. Four hook names get no
shim, so a repository's own hook of that name does not run: `push-to-checkout`
(when present it replaces git's built-in check), `fsmonitor-watchman` (invoked
by path through `core.fsmonitor`), and `reference-transaction` and
`post-index-change` (git fires them on routine ref and index writes, a cost
every repository on every host would pay). `git lfs install` inside a
repository cannot write the store directory, and no longer needs to.

Installation. `default.nix` builds the store directory `agent-git-hooks`
(`agentGitHooks`): the `pre-push` wrapper and one chain shim for each name in
`agentGitHookNames`, and sets `programs.git.settings.core.hooksPath` to it in
the shared `home/common` module, so every host, darwin and Linux, carries the
setting with no host or platform condition (O4). The wrapper is the
`claude-bash-lifecycle-guard` exec line with `--mode pre-push`, the LFS binary
(when `programs.git.lfs` is enabled) and git's `--` arguments appended, so it
shares the guard's interpreter, source and three policy arguments
(`--base-policy`, `--policy`, `--derive-bin`); `tests/test_claude_code_installed.py`
pins that equality. The derivation's build check fails `just build` on a shim
that fails the shell dry run, on a `pre-push` that exits non-zero in a scratch
repository outside an agent session with empty stdin, or on a missing hook
name. git re-reads its configuration on every invocation, so a session's next
push after a switch already uses the new path. Test fixtures that push to a
local remote run git with `GIT_CONFIG_GLOBAL=/dev/null`, because on a switched
host the managed hook judges every push an agent session's test makes.

The raise label
---------------

The hook also refuses an agent adding the `instruction-budget-raise` label
(#294): in a command that mentions that label, case-insensitively, a `gh`
invocation in any position whose `--add-label` value contains it is blocked, in
every repository and before any other verb is judged, and an unparseable
command, `eval`/`sh -c` source or a quoted `$(…)`/backtick substitution that
mentions the label blocks too, while other labels, `--remove-label` and quoted
mentions pass.

Production rules
----------------

A project's declared production commands are refused outside its release path
(issue 1149, ADR-guard-011). The rules are a derived row's optional `production`
member, which the compiler copies from the project's contract: `changes`, the
commands that change its production, `read_only`, the routes that only read it,
and `release_profile`. A command `{id, argv}` is matched as the verb
`[basename(argv[0]), *argv[1:]]`, so `/usr/local/bin/kubectl` is the word
`kubectl`. The rules are read from the compiled policy unconfirmed: they only
refuse, so the row check never confirms them (and never compares them), and a
compiled policy that does not load, a row without `production` and a row with
an empty `changes` refuse nothing.

The check runs on every call after the detaching check and the base policy
load, before any lifecycle verb is judged. It reuses the segment and token
readings of the lifecycle verbs, and reads a leading redirection out of the way
(`>/dev/null ./scripts/deploy.sh` runs the script) and an ANSI-C quoted word as
its text (`$'just' switch`). The guard reads the command as raw text when
it cannot be parsed or a segment cannot be tokenised, and reads the text of a
segment as raw text when a command word is an evaluator (`sh`, `bash`, `eval`,
...) or an `env -S`, or the program at a command position is in
`PRODUCTION_RUNNERS` and a later word of its run is an evaluator or `env -S`
(`timeout 600 sh -c 'just switch'`, `devenv shell -- bash -c ...`). The whole command is
read as raw text instead when such a segment may take its text from somewhere the
segments do not show: a pipeline, a shell with no `-c` (it reads a file or stdin), a
`$` or backtick outside single quotes, a `$`, backtick or `<` in the shell's own text,
a `<`, `{` or `(` outside every quote, or a file a segment redirects to that the
shell's text names (`cmd='just switch'; eval "$cmd"`, `echo 'just switch' | { true;
sh; }`, `echo 'just switch' > f && bash f`). Any other segment is read as a command
(issue 1192, ADR-guard-011 D10), so words in one quoted argument, a comment or an
exactly-read heredoc body beside an evaluator are a mention and pass. In raw text a verb counts when
its words occur in order in either raw reading, or its words joined by one
space are a substring of the command or of the command with its quotes and
backslashes deleted, and nothing is lifted. Otherwise a verb of two or more
words counts at any word whose basename is its first word, when its remaining
words occur in order in that word's run (up to the next operator), or, when an
operator cut the run, in the rest of the segment and both raw readings of the
later segments. A one-word verb has no later words to tell a run of it from a
mention of it (`git add scripts/deploy.sh`, `--title kubectl`), so it counts
only at a command position, or at a later word of a run whose command-position
program is in `PRODUCTION_RUNNERS` (`xargs`, `timeout`, `nice`, `find`, `devenv`
and the other programs that run a later word as a command). A quoted token that
holds `$(` or a backtick, or whitespace behind a runner that runs it as shell text
(`PRODUCTION_SHELL_RUNNERS`: `watch 'just switch'`, `nix-shell --run '...'`,
`flock f -c '...'`, `parallel`, wherever in the run: `timeout 5 flock f -c '...'`; and the
first word after `devenv shell`, which splices it unescaped), is also read as raw text alone, with no
lift, since a substitution runs its text. A quoted word behind any other runner
(`timeout 5 echo 'just switch'`, `devenv shell -- git commit -m '...'`) is its
argument, a mention. A parsed match is lifted when its run begins with a
read-only verb that properly extends the production verb (`kubectl get pods`
against `kubectl`, not `just build switch` against `just switch`); raw text
lifts nothing. The release path, `release transaction preview` and
`release transaction run`, needs no special case: its arguments are inert for a
one-word verb because they are not at a command position, and a chained or
substituted production command in them still counts.

Which project's rules refuse depends on the checkout: the payload cwd's
repository (its `origin` slug). A command that hits a rule while that lookup
times out or cannot start is refused, since an unreadable checkout is not an
unregistered one. A command with a word, in either raw reading,
whose basename is `cd`, `pushd`, `popd` or `chdir` may run elsewhere, so every
declaring row judges it, the cwd repository first and then by sorted slug. That
reading is by raw words, not command positions, because a leading redirection
(`>/dev/null cd dir`) is read as the command word and a double-quoted
substitution is one token. Inside a row the first rule in `changes` order that
hits names the refusal, which is one line:

    lifecycle guard: `<argv>` changes the production of <slug> (production rule
    <id>), so it runs only through the release profile <release_profile> with
    release transaction preview and release transaction run.

The rule a row's `console_activation` names (issue 1193) is approved through the
console's Activate instead, and its refusal is the second form:

    lifecycle guard: `<argv>` changes the production of <slug> (production rule
    <id>), so it runs only through the console's Activate, on the line that says
    a console change is not active on this host.

A `gh` run that names its repository with `--repo`, `--repo=...`, `-R`, `-R...`, `-R=...` or
`-R` inside a group of short flags (`-dR`), read as gh reads them (the word after a
value-taking option is its value, a redirection is not a word, the last flag wins;
`HOST/OWNER/REPO` and a trailing `.git` are read, case is ignored) is a command
on that repository alone (issue 1375): a verb of two or more words that the run itself
spells out (`gh run rerun 9 --failed --repo fagenorn/nix-config`) is judged only against
the rules of the project whose repository the run names, from any directory and with no
repository lookup, so another project's `gh run rerun` rule never refuses a rerun of a
pull-request check of this repository, and the named project's rule refuses it wherever
the call runs, with the same refusal line. A run that names no repository, a value with
`$` or a backtick, a hit read as raw text (`sh -c`, a pipeline, an unparseable command)
and a verb matched only across an operator keep the checkout judgement above. When several
runs hit the same rule, the repositories they name are joined and the checkout is judged as
well when any of them is not narrowed, so an unnamed rerun never erases a named one. A
read the guard cannot be sure of (`-R` behind another letter of its group, a value cut at a
glued redirection) names its repository and is judged by the checkout too.

Known limits: a production command reached by another name (a bare `just` that
runs the default recipe, a script or alias), words fed on stdin, a program's own
directory option (`env -C`, `make -C`) and a one-word command handed to a program
outside `PRODUCTION_RUNNERS` (`ssh host kubectl apply`) are not seen. Where the
text is read raw or behind a runner, a one-word command's name anywhere refuses,
file arguments included. A command that mentions a directory-changing word
anywhere is judged against every declaring project. Rewriting the compiled policy
can remove a project's production refusals, though it still gains no authorization.

Key files and MCP tools
-----------------------

The guard also serves the PreToolUse matchers `Edit|Write|MultiEdit|NotebookEdit`
and `^mcp__` (issue 1150). A file tool names its file in `tool_input.file_path`
(`tool_input.notebook_path` for NotebookEdit), a non-empty string, else the call is
refused as invalid hook input. An MCP call's input is not read. The base and the
detaching checks of the Bash path do not run for these tools.

An MCP call is refused by exact tool name, in any cwd and with none, when a
project's `production.mcp_tools` lists it: the first declaring project by sorted
slug names the refusal, and no child process runs. The sentence is

    `<tool>` changes the production of <slug> (production MCP tool), so it runs
    only through the release profile <release_profile> with release transaction
    preview and release transaction run.

A write's path is resolved against `cwd` (a relative path with no absolute `cwd` is
not judged). Three spellings are checked, each in
the file system's own case: the path as named with `..` collapsed, the path with
its directories resolved and the final component kept as named, and its full
realpath (the file the write reaches). Each spelling is judged in its own checkout,
the git toplevel of its nearest existing ancestor directory, and that checkout's
`origin` slug names the project; the spelling is taken relative to the deepest
ancestor that is that checkout's directory. A write is refused when any spelling
matches. Globs are matched with `fnmatchcase` on the strings unchanged, as the
contract matches them (`*` crosses `/`, no casefolding), the first glob in declared
order naming the refusal. Git runs only after a glob matches a component suffix of
a spelling, and the base policy is read only then, so an ordinary edit starts no
child process and a bad base policy refuses only a key-file candidate. A repository
lookup that fails (times out or cannot start) for a candidate refuses; a compiled
policy that does not load refuses nothing. The sentence is

    `<relative>` is a key file of <slug> (key file glob <glob>), so it changes only
    through the release profile <release_profile> with release transaction preview
    and release transaction run.

Known limits: a key file written by a Bash command, a hard link to a key file under
another name, and an MCP tool reached under another name are not seen.

Guard policy
------------

The guard reads two policy files with disjoint closed schemas, and a loader
refuses a file with any other key set (issue 377 D1). The base policy is a
store file, `claude-bash-lifecycle-guard-base-policy.json`, built from
`lifecycleGuardBasePolicy` in `default.nix`: an object with exactly
`authorized_owners`, `integration_bases`, `git_bin`, `gh_bin` and `jq_bin`,
which are the literal `authorizedOwners` and `integrationBases` rows (an
`integration_bases` row exists only for a repository that is not a registered
project) and the store paths of `git`, `gh` and `jq`. The compiled policy is
the user state file `~/.agents/state/guard/policy.json`: an object with exactly
`derived_repositories` and `derivation`. A derived row is an entry of the
compiled policy's `derived_repositories`, keyed by the exact repository slug,
`{default_branch, integration_branch, required_checks, evidence}` with an
optional `production` member (issue 1149: `{changes, read_only, release_profile}`,
the project's declared production rules as command `{id, argv}` lists, plus, from
issue 1150, the changing `key_files` globs and `mcp_tools` names), where
`required_checks` is the sorted list of check names the project's contract
declares in `bindings.vcs.merge.required_checks`, `[]` when it declares none.
The row check is the store script `claude-guard-row-check`, which the wrapper
passes as `--derive-bin` (`python/agent_tools/guard/guard_policy.py` documents the
script, the compiler and the activation step that writes the compiled policy).
No member exists in both files, so neither file is a valid instance of the
other, and each member has one trust rule:

    authorized_owners          base policy      Store value only.
    integration_bases          base policy      Store value only; the compiled
                                                policy never removes or changes a
                                                literal row.
    git_bin, gh_bin, jq_bin    base policy      Store value only; the only
                                                programs the guard runs besides
                                                the row check.
    derived_repositories       compiled policy  A candidate row per slug, used
                                                only after the row check
                                                confirms it in this invocation.
    production                 compiled policy  A row's declared production rules
                                                (commands, key_files, mcp_tools),
                                                read unconfirmed: they only
                                                refuse (issues 1149, 1150).
    derivation                 compiled policy  Recorded for the reader; null or
                                                an object; the guard does not
                                                interpret it.

The guard loads the base policy on every call, after the detaching-word check.
It reads the compiled policy on every call that passes the detaching check and
the base-policy load, for the production rules (issue 1149 D4), and runs the row
check only for a repository-bound verb (push, PR creation, merge or release
creation), when it builds the repository context. The compiled policy supplies no value the guard executes, and the guard
runs only the base policy's three tools, the row check and the look check,
which it finds by the absolute paths `--derive-bin` and `--look-bin` name. The compiled policy is a user-writable
state file, because compiling at activation cannot write the store. Since issue
377 the guard takes no trusted member from it and treats each derived row as a
claim to be confirmed before it is relied on (issue 377 D1, D2).

A derived row exists for each registered project whose proof held at that
compile and whose slug and two branch names `load_compiled_policy` accepts; a
name it refuses, such as the branch `dev+ci`, costs that project its row
(`name_unsupported`) instead of making the guard drop the whole compiled
policy. A row authorizes its own repository and no other of its owner, and its
`integration_branch` is the repository's integration base when it differs from
the default branch.

Row check. The guard runs the row check as `<derive-bin> --repository <slug>`,
and it re-derives that one repository's row from the fleet registry and the
contract on `origin` with the compiler's own proof. For a repository that has a
row, the guard checks in this order, and the first failure is the verdict: (1)
the slug is also a key of the base `integration_bases`, which refuses; (2)
`origin/HEAD` must name the row's `default_branch` (skipped for a named
repository, which has no checkout: the row check itself proves the contract's
default branch against `origin`'s listed default, and the named repository's
base is the confirmed row's `default_branch`); (3) the row check runs; (4) it
must have exited 0 with an `outcome` of `derived` whose `row` has the compiled
row's `default_branch` and `integration_branch`, and then its
`required_checks`, equal as lists, order included (a report whose
`row.required_checks` is not a list of strings is unreadable). `evidence` is not
compared, because its commit moves with every push to the branch. A refusal at
step 1, 3 or 4 names the repository, the reason (the row check's reason code,
the differing branches, or `it derives required checks <derived>, the row names
<compiled>` with each list as compact JSON) and `claude-guard-policy` as the
repair, except that a row check that timed out at step 3 ends `timed out;
transient: rerun the command` instead, because a plain rerun clears it and
recompiling the policy cannot speed it up (issue 476), and that a row check
refused only for `fetch_failed` or `provider_unproven` names each reason code
with the failed read's detail (as a message shows a value, cut to 240
characters) and ends the same way, because the read failed and the policy did
not (issue 844); step 2's names the live and recorded branch. The check runs
once per repository context, when that context is built (a command whose pushes name several `git -C` directories
builds one context per distinct `git -C` directory and one per named
repository, all under the one invocation deadline), and only for a repository
that has a row: a repository with no row is judged by the base policy with no
check and no network read. A repository with a row is judged by the row and
never falls back to its owner literal when the check fails. Rows are rechecked
at use, so a registry or contract change that moves a row's branches refuses
until the next compile (issue 126 D6, narrowed by issue 377 D2); a project
registered after the last compile has no row until the next one.

The row check runs with stdin at `/dev/null`, its output captured, its own
process group and the guard's environment without `BASH_ENV`, `ENV` and every
`BASH_FUNC_` variable, so no shell startup file or exported function can print
a report the check never derived. It is bounded by the smaller of
`--derive-timeout-seconds` (15 s) and the time left in the guard's 27-second
invocation deadline, which every child it starts shares and which keeps the
verdict ahead of the hook's 30-second timeout (issue 377 D6). It is not started
when no time is left, and on its bound the guard kills the whole group with
`SIGKILL`, so the `git`, `ssh` and `gh` grandchildren do not outlive the
verdict. Once the context exists, no other child starts unless its whole
`--child-timeout-seconds` bound (5 s) fits before the deadline; `main` also
checks the deadline at the top of each operation. When it does not fit, the
guard refuses with its fixed message, that the 27-second invocation deadline
leaves too little time for the next check so it was not started, and judges no
later operation of a chained command (issue 377 D12). A child that reaches its
own bound refuses, so the guard answers without relying on what the harness
does with a timed-out hook.

Cost and offline behaviour. On every repository-bound verb in a repository that
has a row, nix-config included (issue 377 D3), the row check costs one remote
listing, one fetch only for a branch whose listed commit the checkout lacks, a
sparse export of the contract and its projection files for each branch read,
the resolver and one provider read (issue 385). An unreachable `origin` or
provider fails the check (`fetch_failed` or `provider_unproven`) and refuses
the verb: there is no fallback to a ref already present or to the unchecked
row, and no availability is lost, because push, PR creation, merge and release
creation each need the same remote or provider to succeed. Only a fetch writes
a ref, so two sessions judged at once contend for a ref lock only when both
fetch a missing commit into the same registered root; a fetch that loses the
lock fails `fetch_failed` and refuses, a rerun clears it, and the guard takes
no lock of its own.

A bad file. The guard opens either policy file without blocking and reads it
only when the open descriptor is a regular file of at most 1 MiB
(`POLICY_MAX_BYTES`), so a FIFO, a device such as `/dev/zero` behind a symlink,
a directory or a file already larger at the open is refused before a byte is
read, and a file that grows past the cap while read is refused too. A compiled
policy that is missing, unreadable, not a regular file, over that size, not
JSON or outside its schema (a #375 seven-member file included, until the next
compile replaces it) contributes no row, whole file, and blocks nothing the
base policy allows (issue 377 D4). When a repository-bound verb is then refused
for standing authorization, the refusal adds the reason and names
`claude-guard-policy`. This grants nothing: rows only add, a derived-only
repository loses authorization, and an owner-literal repository is judged as an
unregistered one, with no row to check `origin/HEAD` against. A base policy
that is missing, unreadable, not a regular file, over that size or outside its
schema still blocks every Bash call with `invalid policy`, because it is a
store file the build check loaded and a bad one is an installation defect.

Required checks and the schema transition (issues 552, 1149). The loader demands
that a row's `required_checks` be a list of distinct non-empty strings, the
resolver's own rule for the contract member, so a contract that resolves always
yields a row the guard loads; any other value is a malformed row, and the whole
compiled policy contributes no row. The same holds for the optional
`production` member: an object with `changes`, `read_only` and
`release_profile` and optionally `key_files` (a list of non-empty strings),
`mcp_tools` (a list of `mcp__<server>__<tool>` names) and `console_activation` (a
non-empty string equal to the `id` of one `changes` entry), the two lists holding `{id, argv}` objects with a non-empty
`id` and a non-empty `argv` of non-empty strings, and a non-empty
`release_profile`; any other value drops the whole file. The compiler writes
`derivation.schema_version` 6, whose `production` also carries `key_files` and
`mcp_tools` (issue 1150) and, when the contract names one, `console_activation`
(issue 1193); this guard reads schema 3, 4 and 5 rows as before
(`production`, `key_files`, `mcp_tools` and `console_activation` are each
optional). A guard from before issue 1150 reads a schema-5 row as malformed, and
one from before issue 1193 reads a row carrying `console_activation` as malformed
and drops the file until its session restarts. A guard
from before issue 1149, in a session started before the switch, reads a row
carrying `production` as malformed and drops the whole file, so a repository
that relies on a derived row is refused until that session restarts; a
repository authorized by an owner literal keeps its authorization.

Literal and derived rows. `guard-policy compile` refuses a project whose slug is
a key of the base `integration_bases` as `literal_conflict`: the project gets no
row and the literal row stays, and each compile reports the conflict. The
compiled policy cannot subtract from the base, so a repository can carry both
only when the compiled policy was edited or a literal row was added after the
last compile, and the guard refuses it at step 1 above (issue 377 D5). What the
guard authorizes is the base `authorized_owners` and `integration_bases` plus
the derived rows the row check confirms.

Tests
-----

`tests/test_claude_permission_guard.py` takes the built settings through
`CLAUDE_SETTINGS_PATH` and the built base policy through
`CLAUDE_GUARD_BASE_POLICY_PATH`, runs under `python3 -m unittest` with `python/`
on `PYTHONPATH`, and passes a fixture compiled policy and a stub row check on
every invocation, so it never reads this host's compiled policy or fleet
registry, and a look check fixture that runs `look-approval judge` from source as
`--look-bin`. Three tests, `test_a_compiled_policy_round_trips_through_the_guard`,
`test_a_compiled_policy_loads_whatever_branch_names_the_fleet_carries` and
`test_an_arcwave_shaped_project_is_judged_by_its_compiled_row`, run
`guard-policy derive` from source as the row check over a fixture fleet, and
`test_the_row_check_never_sees_a_hostile_shell_environment` runs the built
`claude-guard-row-check` with `HOME` at an empty fixture fleet.
"""

import argparse
from collections import namedtuple
import errno
import fnmatch
import json
import os
import re
import shlex
import signal
import stat
import subprocess
import sys
import time


BASE_POLICY_KEYS = frozenset(
    {"authorized_owners", "integration_bases", "git_bin", "gh_bin", "jq_bin"}
)
COMPILED_POLICY_KEYS = frozenset({"derived_repositories", "derivation"})
DERIVED_ROW_KEYS = frozenset(
    {"default_branch", "integration_branch", "required_checks", "evidence"}
)
# A row may also carry the project's declared production rules (issue 1149).
DERIVED_ROW_OPTIONAL_KEYS = frozenset({"production"})
PRODUCTION_KEYS = frozenset({"changes", "read_only", "release_profile"})
# Schema 5 rows also carry the changing key-file globs and MCP tool names (issue 1150).
# Schema 6 rows may also name the changing rule the console's Activate approves (issue 1193).
PRODUCTION_OPTIONAL_KEYS = frozenset({"key_files", "mcp_tools", "console_activation"})
CONSOLE_ACTIVATION_ROUTE = (
    "the console's Activate, on the line that says a console change is not active on this host"
)
MCP_TOOL_NAME = re.compile(r"mcp__[A-Za-z0-9_-]+__[A-Za-z0-9_-]+")
PRODUCTION_COMMAND_KEYS = frozenset({"id", "argv"})
# A policy file larger than this is refused unread. Either file is a few kilobytes,
# so the cap only bounds the read of a file that is not what it claims to be.
POLICY_MAX_BYTES = 1 << 20
# Variables a shell reads its startup file from (`BASH_ENV`, `ENV`) or imports
# functions from (`BASH_FUNC_<name>%%`), which never reach the row check.
ROW_CHECK_ENV_DROPPED = frozenset({"BASH_ENV", "ENV"})
ROW_CHECK_ENV_DROPPED_PREFIX = "BASH_FUNC_"
CHILD_DIAGNOSTIC_LIMIT = 240
# One invocation, the row check included, answers inside this many seconds, which
# keeps the verdict ahead of the hook's 30-second timeout.
INVOCATION_DEADLINE_SECONDS = 27
DEADLINE_REFUSAL = (
    f"the {INVOCATION_DEADLINE_SECONDS}-second invocation deadline leaves too "
    "little time for the next check, so it was not started"
)
ROW_CHECK_EXIT_STATUSES = {"derived": 0, "refused": 1, "unavailable": 2}
# The row check's reason codes for a failed read of `origin` or the provider: a
# rerun clears a dropped route, and recompiling the policy cannot (issue 844).
ROW_CHECK_TRANSIENT_REASONS = frozenset({"fetch_failed", "provider_unproven"})
ROW_CHECK_TRANSIENT_REMEDY = "transient: rerun the command"
ROW_CHECK_DETAIL_LIMIT = 240
# The gh keyring credential is the authority for these lookups. gh prefers an
# ambient GITHUB_TOKEN/GH_TOKEN over it, and such a token, when one is present
# (CI, a one-off export, another tool), may be narrower: it may not see every
# authorized owner's org. The guard's forge lookups drop the env tokens, so
# validation observes GitHub with the keyring credential: the auth the guarded
# command uses when it sees neither env token (none is set, or an accepted
# scrub prefix in SCRUB_PREFIXES below removed every one that was set). A
# machine with no keyring auth still fails closed at the lookup.
GH_ENV_TOKEN_NAMES = ("GITHUB_TOKEN", "GH_TOKEN")
# The scrub-prefix spelling a resolved exhaustive credential-name list yields
# (`unset GITHUB_TOKEN && gh ...`), and the one the skill-contract checks read
# from this single assignment. SCRUB_PREFIXES below includes it.
UNSET_GITHUB_TOKEN_PREFIX = "unset GITHUB_TOKEN && "
# Every accepted credential-scrub prefix (issue 400 D1): `unset N && `,
# `unset N M && `, `env -u N ` and `env -u N -u M `, single spaces, with N and M
# distinct members of GH_ENV_TOKEN_NAMES. Unsetting any other name could change
# the repository or config the command sees. Longest first, so a two-name
# spelling is tried before the one-name spelling it begins with.
SCRUB_PREFIXES = tuple(sorted(
    {
        spelling
        for names in [(name,) for name in GH_ENV_TOKEN_NAMES] + [
            (first, second)
            for first in GH_ENV_TOKEN_NAMES for second in GH_ENV_TOKEN_NAMES
            if first != second
        ]
        for spelling in (
            "unset " + " ".join(names) + " && ",
            "env " + " ".join(f"-u {name}" for name in names) + " ",
        )
    },
    key=lambda spelling: (-len(spelling), spelling),
))
# The guarded verbs as word sequences: the program, then its subcommand path.
# Order matters: the first match at a token wins, and no sequence is a prefix
# of another.
GUARDED_VERBS = (
    (("gh", "pr", "merge"), "merge"),
    (("gh", "pr", "create"), "pr-create"),
    (("git", "branch", "-d"), "branch"),
    (("git", "push"), "push"),
    (("gh", "release", "create"), "release"),
    # `new` is gh's alias of `create`; it routes to the same grammar, which
    # refuses it because the grammar spells `create`.
    (("gh", "release", "new"), "release"),
)
# The raise label is the user's Instruction Budget raise decision. The refusal
# is a mistake-catcher for agents, not enforcement (#294).
RAISE_LABEL = "instruction-budget-raise"
RAISE_LABEL_REFUSAL = (
    "only the user applies this label (Instruction Budget raise control)"
)
OPERATION_LABELS = {
    "merge": "merge",
    "pr-create": "PR creation",
    "branch": "branch deletion",
    "push": "push",
    "release": "release creation",
    "label": "instruction-budget-raise label edit",
}
# Words that keep the command position open: shell keywords that introduce a
# command, and wrappers that hand the rest of the words to another command.
COMMAND_KEYWORDS = frozenset({
    "!", "time", "if", "then", "elif", "else", "while", "until", "do", "done",
    "in", "coproc",
})
COMMAND_WRAPPERS = frozenset({"command", "builtin", "exec", "env", "sudo"})
# Programs whose argument is shell source, matched by basename (`/bin/sh -c`).
# Arbitrary shell cannot be parsed here, so a guarded verb anywhere in such a
# segment is refused outright.
SHELL_EVALUATORS = frozenset({"eval", "sh", "bash", "zsh", "dash", "ksh"})
EVALUATOR_REASON = "shell source passed to an evaluator cannot be validated"
SPLIT_STRING_REASON = "command text handed to env -S cannot be validated"
NOT_COMMAND_POSITION = (
    "the verb is not in a command position the guard can validate; quote it "
    "if you only mean to mention it"
)
# What a branch-name check that timed out reports; a refusal of the state, not
# of the command's text, so it prints no accepted forms (issue 402 D3).
BRANCH_VALIDATION_TIMEOUT = "branch validation timed out"
# Ends every refusal of an invocation form at recognition (issue 400 D6).
INVOCATION_FORM_HINT = "run git and gh by name, and carry a directory only as git -C <dir>"
# Words that detach a process from the task that started it (#278). Refused
# in every repository, before the policy loads.
DETACHING_WORDS = ("nohup", "setsid", "disown")
# A whole word, matched in the raw text with no shell parsing (issue 656 D2).
# Case-insensitive because a case-insensitive file system runs `NOHUP`; `re.ASCII`
# so a Unicode case fold (KELVIN SIGN, dotted capital I) is no letter. `-` is a
# word character because branch slugs use it and a `-` before a word is rarely
# a command word. A `c` or `s` before still bounds the word, for env's attached
# `-S` and the attached `-c` of `su` and `script`; so does a `$` and one digit,
# `!`, `@` or `*` (`$1nohup`: the parameter is empty in the Bash tool).
DETACHING_PATTERN = re.compile(
    r"(?:(?<![A-Za-z0-9_-])|(?<=[cs])|(?<=\$[0-9!@*]))(" + "|".join(DETACHING_WORDS)
    + r")(?![A-Za-z0-9_-])",
    re.IGNORECASE | re.ASCII,
)
# The one place a `-` is an operator, not a word character: `${x:-nohup}` and
# `${x-nohup}` expand to the literal word when `x` is unset. Any
# parameter counts, since it may be a special one or carry a subscript
# (`${@:-nohup}`, `${a[0]:-nohup}`, `${a[i-1]:-nohup}`), and the word may be
# rebuilt by the characters `DETACHING_JUNK` matches, before the first letter
# and between letters (`${x:-'n'ohup}`, `${x:-no''hup}`, `${x-no\hup}`,
# `${x:-no{,}hup}`), which the deletion copy cannot recover
# here because it also deletes the brace that opens the expansion.
DETACHING_JUNK = r"(?:\\\n|\$(?=['\"])|[\\'\"{},])*"
DETACHING_DEFAULT_PATTERN = re.compile(
    r"\$\{(?:[^}:\-\[]|\[[^\]]*\])*:?-(" + "|".join(
        DETACHING_JUNK + DETACHING_JUNK.join(word) for word in DETACHING_WORDS
    ) + r")(?![A-Za-z0-9_-])",
    re.IGNORECASE | re.ASCII,
)
# What the deletion copy of the command drops (issue 656 D3): a `$` before a
# quote (`no$''hup`), then every backslash, quote, brace and comma, which
# rebuilds `no''hup`, `no\hup` and `no{,}hup`.
DETACHING_DELETED = re.compile(r"\$(?=['\"])|[\\'\"{},]")
CD_PRELUDE_PROBLEM = (
    "the directory the verb runs in cannot be resolved: a directory change is "
    "accepted only as one leading cd <absolute directory> && before a single "
    "push or PR creation; or carry the directory as git -C <dir>"
)
# The allowlist a command holding a lifecycle verb must match as a whole, before
# any other judgement (issue 418). A plain word takes only these characters and
# never begins with `=` (zsh's `=cmd` expansion); a single-quoted string is
# literal; a double-quoted one is literal while it holds none of
# `DOUBLE_QUOTE_ACTIVE`, the characters the shell still reads there (`!` for
# history expansion).
PLAIN_WORD = re.compile(r"[A-Za-z0-9_./:@%+=,-]+")
DOUBLE_QUOTE_ACTIVE = frozenset('"$`\\!')
LIFECYCLE_VERBS = (
    ("git", "push"), ("git", "branch", "-d"), ("gh", "pr", "create"),
    ("gh", "pr", "merge"), ("gh", "release", "create"),
)
LIFECYCLE_GRAMMAR = (
    "a lifecycle verb runs only alone, as [unset GITHUB_TOKEN && ][cd <dir> && ]"
    "<verb> <args> (git -C <dir> before push or branch -d), every word plain "
    "([A-Za-z0-9_./:@%+=,-]) or quoted ('...', or \"...\" without $, `, \\ or !)"
)
DETACHING_ROUTES = (
    "a detached process outlives the task stop; run it with the Bash tool's "
    "background mode (run_in_background: true)"
)
# Characters that end a word and re-open the command position: subshells,
# groups, `case` arms and command substitution all start a command after one.
OPERATOR_CHARS = "(){}`"
# `NAME=` and the append form `NAME+=`, which bash also treats as an
# assignment (and which equals `NAME=` when NAME is unset); `name` is the bare
# variable name.
ASSIGNMENT_PREFIX = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\+?=")
SLUG_PATTERN = re.compile(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+")
REF_NAME_PATTERN = re.compile(r"[A-Za-z0-9._/-]+")
# Path components that make a token a namespaced ref rather than a branch
# name: `git push origin refs/heads/main` and `heads/main` both update the
# branch `main`, so they must never be compared as plain names.
REF_NAMESPACE_COMPONENTS = frozenset({"refs", "heads", "tags", "remotes"})
# The release tag the forge adapter pushes and publishes: vMAJOR.MINOR.PATCH,
# no leading zeros, nothing else (D9).
SEMVER_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
TAG_REF_PREFIX = "refs/tags/"
SEGMENT_SEPARATORS = frozenset(";&|\n")
UNSAFE_BRANCH_CHARS = set(";&|<>$`\\\n\r*?[]{}()#~")
UNSAFE_TEXT_CHARS = frozenset('"$`\\\0\r')
# Where the guard reads raw text (issue 400 D5, D12, D16) it reads it twice: a
# word ends at whitespace, a quote or any shell-active character; and, because
# the shell glues quoted or escaped pieces into one word (`g''it`, `g\it`), with
# the quotes and backslashes deleted, a word ends at whitespace or any other
# shell-active character.
RAW_WORD_BREAKS = frozenset("'\"") | frozenset(UNSAFE_BRANCH_CHARS)
RAW_GLUE_CHARS = frozenset("'\"\\")


# Every accepted spelling, one table per operation (issue 402 D1). A form is
# (id, template, note): words separated by single spaces; `<name>` is a slot
# taking one word, `"<name>"` a free-text slot whose value may begin with `-`;
# a slot may close a literal word (`refs/tags/<vX.Y.Z>`); `[...]` is an
# optional group whose first word is its flag, never nested; the note is
# printed after the form and never matched. Forms are tried in order. `main`
# compiles this literal first on every invocation (D14).
FORM_SLOTS = ("n", "slug", "base", "branch", "sha", "subject", "title", "body", "vX.Y.Z", "path")
FORM_TABLE = {
    "push": {
        "forms": (
            ("tag", "git push origin refs/tags/<vX.Y.Z>", None),
            ("branch", "git push [-u] origin <branch>", None),
            ("delete", "git push origin --delete refs/heads/<branch>", None),
        ),
        "whole_text_characters": True,
        "exact_spelling": False,
        "scrub_prefix": True,
    },
    "pr-create": {
        "forms": (
            ("pr-create", 'gh pr create --repo <slug> [--draft] --base <base> --head <branch> '
                          '--title "<title>" --body "<body>"', None),
            ("pr-create-file", 'gh pr create --repo <slug> [--draft] --base <base> --head <branch> '
                               '--title "<title>" --body-file <path>', None),
        ),
        "whole_text_characters": False,
        "exact_spelling": False,
        "scrub_prefix": True,
    },
    "merge": {
        "forms": (
            ("feature", 'gh pr merge <n> --repo <slug> --merge [--subject "<subject>"] '
                        "[--match-head-commit <sha>] --delete-branch", None),
            ("release", 'gh pr merge <n> --repo <slug> --merge [--subject "<subject>"] '
                        "[--match-head-commit <sha>]", "only <integration> into <default>"),
        ),
        "whole_text_characters": False,
        "exact_spelling": True,
        "scrub_prefix": True,
    },
    "release": {
        "forms": (
            ("release", 'gh release create <vX.Y.Z> --repo <slug> --verify-tag '
                        '--title "<title>" --notes-file <path>', None),
        ),
        "whole_text_characters": False,
        "exact_spelling": True,
        "scrub_prefix": True,
    },
    "branch": {
        "forms": (("branch", "git branch -d <branch>", None),),
        "whole_text_characters": True,
        "exact_spelling": False,
        "scrub_prefix": False,
    },
}
# The value `--match-head-commit` takes: a full commit SHA (issue 402 D10), which
# must also be the PR's head commit (issue 476 D3).
HEAD_COMMIT = re.compile(r"[0-9a-f]{40}")
# The words that tie a pull request to an issue it settles (issue 1138): every
# keyword GitHub closes an issue on (close, closes, closed, fix, fixes, fixed,
# resolve, resolves, resolved) and `refs`, an optional colon, then `#<n>`,
# `<owner>/<name>#<n>` or a `https://github.com/<owner>/<name>/issues/<n>` URL;
# the look gate reads only the repository's own references. Each match is
# `(url slug, qualified slug, number)`, the slug groups empty when not spelled.
LOOK_REFERENCE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs)\b[ \t]*:?[ \t]*"
    r"(?:https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/"
    r"|([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#|#)([1-9][0-9]*)\b",
    re.IGNORECASE)
# `gh pr view --json commits` returns at most this many commits; a PR with this
# many or more may hold a closing keyword the lookup did not return, so the look
# gate refuses it (issue 1138).
LOOK_COMMIT_LIMIT = 100
# The look file set the kept-approval rule reads (issue 1211) and the bounds the carry
# keeps; they equal `look_marker`'s `LOOK_FILES_PATH`, `CARRY_RUNS` and `READ_LIMIT`
# (a test pins the equality, since the guard imports nothing from `agent_tools`).
LOOK_FILES_PATH = ".github/look-files.json"
LOOK_CARRY_RUNS = 3
LOOK_READ_LIMIT = 48
# The one shape of read besides the set file at the pinned base: a compare of two
# full commit shas.
LOOK_READ_PATH = re.compile(r"compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}")
# A linked issue's URL as `closingIssuesReferences` gives it: `(slug, number)`.
LOOK_ISSUE_URL = re.compile(
    r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)")
# GitHub's answer to a branch-protection read on a plan that cannot protect the
# branch (issue 552 D2): `gh api` exits non-zero and writes this body to stdout.
PLAN_GATED_STATUS = "403"
PLAN_GATED_MESSAGE = (
    "Upgrade to GitHub Pro or make this repository public to enable this feature."
)
# The one home of a green check-rollup entry (issue 552 D6): the plan-gated floor
# reads it, and the release arm's jq predicate is rendered from it.
GREEN_CHECK_RUN_STATUS = "COMPLETED"
GREEN_CHECK_RUN_CONCLUSIONS = ("SUCCESS", "SKIPPED", "NEUTRAL")
GREEN_STATUS_CONTEXT_STATE = "SUCCESS"
RELEASE_ROLLUP_PREDICATE = (
    '(.statusCheckRollup | type) == "array" '
    "and (.statusCheckRollup | length) > 0 "
    "and all(.statusCheckRollup[]; "
    f'(.__typename == "CheckRun" and .status == "{GREEN_CHECK_RUN_STATUS}" and ('
    + " or ".join(
        f'.conclusion == "{conclusion}"' for conclusion in GREEN_CHECK_RUN_CONCLUSIONS
    )
    + ")) "
    f'or (.__typename == "StatusContext" and .state == "{GREEN_STATUS_CONTEXT_STATE}"))'
)

Literal = namedtuple("Literal", "word")
Slot = namedtuple("Slot", "name quoted prefix")
Group = namedtuple("Group", "elements")
CompiledForm = namedtuple("CompiledForm", "id template note elements")
CompiledOperation = namedtuple(
    "CompiledOperation",
    "operation forms whole_text_characters exact_spelling scrub_prefix program flags "
    "quoted_value_flags",
)
FormWalk = namedtuple("FormWalk", "position expected values quoted")
FormMatch = namedtuple("FormMatch", "form values")

FORM_TABLE_OPERATIONS = frozenset({"push", "pr-create", "merge", "release", "branch"})
FORM_TABLE_PROPERTIES = ("whole_text_characters", "exact_spelling", "scrub_prefix")
NOTE_PLACEHOLDERS = frozenset({"<integration>", "<default>"})
SLOT_WORD = re.compile(r'([^<>"]*)<([^<>"]+)>')
QUOTED_SLOT_WORD = re.compile(r'([^<>"]*)"<([^<>"]+)>"')
LITERAL_WORD = re.compile(r'[^<>"]+')


class FormTableError(ValueError):
    """A form-table entry that does not compile; `main` lets it reach the
    unexpected-failure handler, which refuses with exit 2 (issue 402 D14)."""


class DeadlineExhausted(Exception):
    """The invocation deadline leaves too little time to start the next child.

    A plain `Exception`, so the validators' `except (subprocess.TimeoutExpired,
    OSError)` clauses and the module's unexpected-failure handler never see it;
    `main` alone turns it into a refusal.
    """


def block(reason):
    print(f"lifecycle guard: {reason}", file=sys.stderr)
    return 2


def bounded_child_diagnostic(child):
    parts = []
    for name, output in (("stderr", child.stderr), ("stdout", child.stdout)):
        if not output:
            continue
        normalized = "".join(
            character if character.isprintable() else " "
            for character in output
        )
        normalized = " ".join(normalized.split())
        if normalized:
            parts.append(f"{name}={normalized}")
    if not parts:
        return "no child output"
    diagnostic = "; ".join(parts)
    if len(diagnostic) > CHILD_DIAGNOSTIC_LIMIT:
        return diagnostic[:CHILD_DIAGNOSTIC_LIMIT - 3] + "..."
    return diagnostic


def block_child_failure(reason, child):
    return block(f"{reason}: {bounded_child_diagnostic(child)}")


def gh_lookup_env():
    """os.environ with the gh-recognised token variables removed."""
    environment = dict(os.environ)
    for name in GH_ENV_TOKEN_NAMES:
        environment.pop(name, None)
    return environment


def read_heredoc_delimiter(command, index):
    """Consume the `<<`/`<<-` redirection starting at `index`.

    Returns (next_index, delimiter, strip_tabs, expands). `expands` says whether
    the shell expands the body (a bare-word delimiter). The delimiter is None
    when the redirection is malformed or when its word is not one of the three
    spellings the guard reads exactly as the shell does: a bare word without
    quotes, backslashes, `$` or backticks, one single-quoted span, or one
    double-quoted span without a shell-active character. `split_segments` then
    refuses to parse the command, so a lifecycle verb anywhere
    in it is refused on its raw text (issue 651).
    """
    length = len(command)
    cursor = index + 2
    strip_tabs = False
    if cursor < length and command[cursor] == "-":
        strip_tabs = True
        cursor += 1
    while cursor < length and command[cursor] in " \t":
        cursor += 1
    start = cursor
    quote = None
    while cursor < length:
        character = command[cursor]
        if quote is not None:
            if character == quote:
                quote = None
            cursor += 1
            continue
        if character in "'\"":
            quote = character
            cursor += 1
            continue
        if character == "\\" and cursor + 1 < length:
            cursor += 2
            continue
        if character in " \t\n;&|<>()":
            break
        cursor += 1
    if quote is not None:
        return cursor, None, False, False
    raw = command[start:cursor]
    if not raw:
        return cursor, None, False, False
    if raw[0] == "'":
        if len(raw) >= 3 and raw[-1] == "'" and "'" not in raw[1:-1]:
            return cursor, raw[1:-1], strip_tabs, False
        return cursor, None, False, False
    if raw[0] == '"':
        if (len(raw) >= 3 and raw[-1] == '"'
                and not any(c in DOUBLE_QUOTE_ACTIVE for c in raw[1:-1])):
            return cursor, raw[1:-1], strip_tabs, False
        return cursor, None, False, False
    if any(c in "'\"\\$`" for c in raw):
        return cursor, None, False, False
    return cursor, raw, strip_tabs, True


def skip_heredoc_bodies(command, index, pending):
    """Skip `pending` heredoc bodies.

    Returns None when one is unterminated, or when a body the shell expands
    (bare-word delimiter) holds `$`, a backtick or a backslash: the shell runs
    substitutions there and joins a backslash-newline before matching the
    closing line (issue 651).
    """
    length = len(command)
    for delimiter, strip_tabs, expands in pending:
        closed = False
        while index < length:
            end = command.find("\n", index)
            if end == -1:
                line = command[index:]
                index = length
            else:
                line = command[index:end]
                index = end + 1
            candidate = line.lstrip("\t") if strip_tabs else line
            if candidate == delimiter:
                closed = True
                break
            if expands and any(c in line for c in "$`\\"):
                return None
        if not closed:
            return None
    return index


def split_segments(command):
    """The top-level segments of `command` (`split_segments_with_runs` without
    the separator runs), or None when it cannot be parsed."""
    parsed = split_segments_with_runs(command)
    return None if parsed is None else parsed[0]


def split_segments_with_runs(command):
    """Split a shell command into its top-level segments and the separator run
    that follows each (`"|"`, `"&&"`, `"\n"`, `""` after the last), so a caller
    can tell that a segment reads a pipe (issue 655 D7).

    Quoted interiors stay inside their segment; comments and heredoc bodies are
    dropped. Neither can therefore open a command position. Returns None when
    the string cannot be parsed (unterminated quote or heredoc, or a heredoc the
    guard cannot read exactly), which the caller treats as a fail-closed
    signal.
    """
    segments = []
    runs = []
    current = []
    pending = []
    quote = None
    index = 0
    length = len(command)
    while index < length:
        character = command[index]
        if quote == "'":
            current.append(character)
            if character == "'":
                quote = None
            index += 1
            continue
        if character == "\\" and index + 1 < length:
            # One element for the escaped pair, so an escaped blank is not the
            # blank that opens a comment: `echo \ #; just switch` runs `just switch`.
            current.append(command[index:index + 2])
            index += 2
            continue
        if quote == '"':
            current.append(character)
            if character == '"':
                quote = None
            index += 1
            continue
        if character in "'\"":
            quote = character
            current.append(character)
            index += 1
            continue
        if character == "#" and (not current or current[-1] in " \t"):
            while index < length and command[index] != "\n":
                index += 1
            continue
        if character == "<" and command.startswith("<<", index):
            if command.startswith("<<<", index):
                current.append("<<<")
                index += 3
                continue
            cursor, delimiter, strip_tabs, expands = read_heredoc_delimiter(command, index)
            if delimiter is None:
                return None
            current.append(command[index:cursor])
            pending.append((delimiter, strip_tabs, expands))
            index = cursor
            continue
        if character == "\n":
            # Heredoc bodies begin after the newline that ends the line which
            # declared them — never at an earlier `;`/`&`/`|` on that line.
            segments.append("".join(current))
            runs.append("\n")
            current = []
            index += 1
            if pending:
                index = skip_heredoc_bodies(command, index, pending)
                if index is None:
                    return None
                pending = []
            continue
        if character in SEGMENT_SEPARATORS:
            segments.append("".join(current))
            current = []
            run_start = index
            while (
                index < length
                and command[index] in SEGMENT_SEPARATORS
                and command[index] != "\n"
            ):
                index += 1
            runs.append(command[run_start:index])
            continue
        current.append(character)
        index += 1
    if quote is not None or pending:
        return None
    segments.append("".join(current))
    runs.append("")
    return segments, runs


def tokenize_segment(segment):
    """Split one segment into (value, is_operator) tokens.

    Values are unquoted, so `"git" push` and `git  push` both tokenise to
    ["git", "push"] while a quoted `'git push origin main'` stays one token and
    can never match a multi-token verb. Returns None when the segment cannot be
    tokenised, which the caller treats as fail-closed.
    """
    tokens = []
    value = []
    started = False
    quote = None
    index = 0
    length = len(segment)
    while index < length:
        character = segment[index]
        if quote == "'":
            if character == "'":
                quote = None
            else:
                value.append(character)
            index += 1
            continue
        if character == "\\" and segment[index + 1:index + 2] == "\n":
            # A line continuation joins the lines: `git\<newline> push` is
            # `git push` (issue 655 D2).
            index += 2
            continue
        if character == "\\" and index + 1 < length:
            value.append(segment[index + 1])
            started = True
            index += 2
            continue
        if quote == '"':
            if character == '"':
                quote = None
            else:
                value.append(character)
            index += 1
            continue
        if character in "'\"":
            quote = character
            started = True
            index += 1
            continue
        if character in " \t":
            if started:
                tokens.append(("".join(value), False))
                value = []
                started = False
            index += 1
            continue
        if character in OPERATOR_CHARS:
            if started:
                tokens.append(("".join(value), False))
                value = []
                started = False
            tokens.append((character, True))
            index += 1
            continue
        value.append(character)
        started = True
        index += 1
    if quote is not None:
        return None
    if started:
        tokens.append(("".join(value), False))
    return tokens


def command_position_flags(tokens):
    """(flags, split_string): per token, does a simple command start here; and
    does an `env` at a command position take `-S`/`--split-string`?

    Keywords, assignments and wrappers keep the position open. A wrapper option
    that takes an argument (`env -u NAME`, `sudo -u user`, per the wrapper option
    tables) also consumes the next word, unless the argument is attached
    (`-uNAME`, `--user=anis`), so the wrapped program is the command word. An
    operator token ends any pending option argument.
    """
    flags = [False] * len(tokens)
    split_string = False
    open_position = True
    wrapper = None
    pending = 0
    for index, (value, operator) in enumerate(tokens):
        if operator:
            open_position, wrapper, pending = True, None, 0
            continue
        if not open_position:
            continue
        if pending:
            pending -= 1
            continue
        if ASSIGNMENT_PREFIX.match(value) is not None:
            continue
        if value in COMMAND_KEYWORDS or value in COMMAND_WRAPPERS:
            wrapper = value
            continue
        if wrapper is not None and value.startswith("-"):
            kind, attached = wrapper_option(wrapper, value)
            if kind == "payload":
                split_string = True
            if kind is not None and attached is None:
                pending += 1
            continue
        flags[index] = True
        open_position = False
    return flags, split_string


def program_name(word):
    """The basename of `word`: `/usr/bin/git` -> `git`."""
    return word.rsplit("/", 1)[-1]


def raw_words(text, glued=False):
    """The words of raw `text`, split at whitespace and RAW_WORD_BREAKS.

    With `glued`, quotes and backslashes are deleted first, as the shell joins
    the pieces around them into one word (issue 400 D16).

    A word that env's option table reads as a split-string option with attached
    command text (`-Sgit`, `--split-string=git`) is followed by that text as a
    word of its own, since env runs it (issue 400 D12).
    """
    words = []
    current = []
    for character in text + " ":
        if glued and character in RAW_GLUE_CHARS:
            continue
        if character.isspace() or character in RAW_WORD_BREAKS:
            if current:
                words.append("".join(current))
                current = []
        else:
            current.append(character)
    expanded = []
    for word in words:
        expanded.append(word)
        if word.startswith("-"):
            kind, attached = wrapper_option("env", word)
            if kind == "payload" and attached:
                expanded.append(attached)
    return expanded


def verb_occurs_in_order(words, verb_words):
    """True when `verb_words` occur in `words` in order, not necessarily
    adjacent, the program word matched by basename."""
    position = 0
    for word in words:
        candidate = program_name(word) if position == 0 else word
        if candidate == verb_words[position]:
            position += 1
            if position == len(verb_words):
                return True
    return False


def mentions_raise_label(texts):
    """True when any of `texts` contains the raise label, ignoring case."""
    return any(RAISE_LABEL in text.lower() for text in texts)


def adds_raise_label(tokens):
    """True when a `gh` invocation in `tokens` adds the raise label.

    Looks at every `gh` word, in any position: its words run to the end of
    `tokens` (the whole command's tokenised segments), skipping operator
    tokens, so a substitution, group or pipeline before the label
    (`gh pr edit $(… | …) --add-label …`) cannot hide it. A label value is
    the word after `--add-label` or the rest of a `--add-label=` word. No
    subcommand parsing and no comma splitting: a value that contains the label
    anywhere counts.
    """
    for index, (value, is_operator) in enumerate(tokens):
        if is_operator or os.path.basename(value) != "gh":
            continue
        words = [
            word for word, word_is_operator in tokens[index + 1:]
            if not word_is_operator
        ]
        labels = [
            words[position + 1]
            for position, word in enumerate(words[:-1])
            if word == "--add-label"
        ]
        labels.extend(
            word[len("--add-label="):]
            for word in words
            if word.startswith("--add-label=")
        )
        if any(RAISE_LABEL in label.lower() for label in labels):
            return True
    return False


def git_directory_problem(directory):
    """True when a `git -C` directory is not one plain word: empty, or holding
    whitespace, a quote or a shell-active character (issue 400 D7)."""
    return not directory or any(
        character.isspace() or character in "'\"" or character in UNSAFE_BRANCH_CHARS
        for character in directory
    )


def git_invocation(program, words):
    """(operation, problem, directory) for a guarded git invocation, else None
    (issue 400 D3).

    `words` follow the `git` word up to the end of its simple command. Leading
    words that begin with `-` are global options, each `-C` taking the next word
    as its directory. With no other option and at most one `-C`, the next word is
    the subcommand; otherwise `push`, or `branch` then `-d`, anywhere among
    `words` counts, since the walk cannot know which options take a value.
    `problem` is None for a plain `git` with no global option or one plain
    `-C <dir>`, else the recognition refusal (D6). `directory` is that `-C` value
    when `problem` is None, else None.
    """
    options = []
    directories = []
    index = 0
    while index < len(words) and words[index].startswith("-"):
        if words[index] == "-C" and index + 1 < len(words):
            directories.append(words[index + 1])
            index += 2
        else:
            options.append(words[index])
            index += 1
    if not options and len(directories) <= 1:
        candidates = [words[index:index + 2]]
    else:
        candidates = [words[position:position + 2] for position in range(len(words))]
    operation = None
    for candidate in candidates:
        if candidate[:1] == ["push"]:
            operation = "push"
        elif candidate == ["branch", "-d"]:
            operation = "branch"
        if operation is not None:
            break
    if operation is None:
        return None
    if program != "git":
        problem = "git named by a path"
    elif options:
        problem = f"git global option {options[0]} is not accepted"
    elif len(directories) > 1:
        problem = "git -C given more than once"
    elif directories and git_directory_problem(directories[0]):
        problem = (
            "the git -C directory must be one word without whitespace, quotes "
            "or shell-active characters"
        )
    else:
        return operation, None, (directories[0] if directories else None)
    return operation, f"{problem}; {INVOCATION_FORM_HINT}", None

# Issue 655 D5: the git global options the guard walks, each with the number of
# words it takes. `-c`, `--config-env` and `--exec-path=<dir>` are absent on
# purpose: their value can run a command from any subcommand.
GIT_GLOBAL_OPTIONS = {
    "-C": 1, "--git-dir": 1, "--work-tree": 1, "--namespace": 1,
    "-p": 0, "--paginate": 0, "-P": 0, "--no-pager": 0, "--bare": 0,
    "--no-replace-objects": 0, "--literal-pathspecs": 0, "--glob-pathspecs": 0,
    "--noglob-pathspecs": 0, "--icase-pathspecs": 0, "--no-optional-locks": 0,
    "--no-advice": 0, "--no-lazy-fetch": 0, "--exec-path": 0, "--html-path": 0,
    "--man-path": 0, "--info-path": 0, "--version": 0, "-v": 0, "--help": 0,
    "-h": 0,
}
# Issue 655 D4: the closed list of git subcommands that cannot transmit refs.
# `push` is absent: it is recognised earlier (D6). Every other word is an alias,
# an external git-<name> program or a transport, and is refused.
GIT_LOCAL_SUBCOMMANDS = frozenset({
    "add",
    "am",
    "annotate",
    "apply",
    "archive",
    "blame",
    "branch",
    "bundle",
    "cat-file",
    "check-attr",
    "check-ignore",
    "check-mailmap",
    "check-ref-format",
    "checkout",
    "checkout-index",
    "cherry",
    "cherry-pick",
    "clean",
    "clone",
    "column",
    "commit",
    "commit-graph",
    "commit-tree",
    "config",
    "count-objects",
    "describe",
    "diff",
    "diff-files",
    "diff-index",
    "diff-tree",
    "fetch",
    "fmt-merge-msg",
    "for-each-ref",
    "format-patch",
    "fsck",
    "gc",
    "get-tar-commit-id",
    "grep",
    "hash-object",
    "help",
    "index-pack",
    "init",
    "interpret-trailers",
    "log",
    "ls-files",
    "ls-remote",
    "ls-tree",
    "mailinfo",
    "mailsplit",
    "maintenance",
    "merge",
    "merge-base",
    "merge-file",
    "merge-tree",
    "mktag",
    "mktree",
    "multi-pack-index",
    "mv",
    "name-rev",
    "notes",
    "pack-objects",
    "pack-refs",
    "patch-id",
    "prune",
    "prune-packed",
    "pull",
    "range-diff",
    "read-tree",
    "rebase",
    "reflog",
    "remote",
    "repack",
    "replace",
    "rerere",
    "reset",
    "restore",
    "rev-list",
    "rev-parse",
    "revert",
    "rm",
    "shortlog",
    "show",
    "show-branch",
    "show-index",
    "show-ref",
    "sparse-checkout",
    "stash",
    "status",
    "stripspace",
    "switch",
    "symbolic-ref",
    "tag",
    "unpack-file",
    "unpack-objects",
    "update-index",
    "update-ref",
    "var",
    "verify-commit",
    "verify-pack",
    "verify-tag",
    "version",
    "whatchanged",
    "worktree",
    "write-tree",
})
GIT_UNCERTAIN_PROBLEM = (
    "the git invocation continues past a shell substitution or grouping; "
    f"{INVOCATION_FORM_HINT}"
)
# Issue 672 D8: the pre-push hook is authoritative only while git runs the
# managed hook, so the text guard refuses naming the key that repoints it.
HOOKS_PATH_PROBLEM = (
    "git config naming core.hooksPath would change which hook judges a push; "
    "read it with git rev-parse --git-path hooks"
)
# Issue 672 D3: the pre-push hook judges a push only in an agent session, which
# it recognises by this variable, so the text guard refuses clearing it.
AGENT_SESSION_VARIABLE = "CLAUDECODE"
SESSION_MARKER_PROBLEM = (
    f"clearing or unsetting {AGENT_SESSION_VARIABLE} would hide the agent "
    "session from the pre-push hook"
)
GIT_FED_PROBLEM = (
    "a git word with no subcommand reads its subcommand from a pipe or "
    f"redirection; {INVOCATION_FORM_HINT}"
)
# A raw word that ends in `git` after nothing or after one of `/:=+?-`, so
# `${X:-git}` and `/usr/bin/git` count (issue 655 D7); used with fullmatch.
GIT_RAW_WORD = re.compile(r"(?:.*[/:=+?-])?git")


def dashed_git_program(name):
    """True when program `name` is a `git-<name>` program, an alias by another
    spelling (issue 655 D8)."""
    return name.startswith("git-")


def opening_operator(tokens, index, operator):
    """True when `operator`, the operator token that cuts the run after the git
    word at `index`, opens a substitution or grouping (issue 655 D9): `(` and
    `{` always, a backtick when an even number of backtick operator tokens
    precede `index` (an odd number means it closes one)."""
    if operator in ("(", "{"):
        return True
    if operator != "`":
        return False
    before = sum(1 for value, is_operator in tokens[:index] if is_operator and value == "`")
    return before % 2 == 0


def open_substitutions(tokens, index):
    """Positions of the substitutions still open before `index`: the position of
    the `$` word of an unglued `$(`, or of an opening backtick (issue 655 D9
    review). A glued `x=$(` is not one, since its output is assigned."""
    stack = []
    for position in range(index):
        value, is_operator = tokens[position]
        if not is_operator:
            continue
        if value == "(":
            before = tokens[position - 1] if position else None
            substitution = before is not None and before == ("$", False)
            stack.append(("(", position - 1 if substitution else None))
        elif value == ")":
            if stack and stack[-1][0] == "(":
                stack.pop()
        elif value == "`":
            if stack and stack[-1][0] == "`":
                stack.pop()
            else:
                stack.append(("`", position))
    return [position for _kind, position in stack if position is not None]


def bare_git_supplies_command(tokens, index, cut_at, run):
    """True when the git word at `index`, followed by no subcommand in `run`, may
    be the output of a command substitution whose following words run as its
    arguments (`$(echo git) p origin t`, a backtick likewise): the run is cut by
    the substitution's closing `)` or backtick with a word after it, or the
    segment ends inside the substitution (`$(echo git; true) p`) (issue 655
    D7 review). `cut_at` is the position of the operator that cut the run, else
    None."""
    if git_names_subcommand(run) or not open_substitutions(tokens, index):
        return False
    if cut_at is None:
        return True
    if tokens[cut_at][0] not in (")", "`"):
        return False
    following = cut_at + 1
    while following < len(tokens) and tokens[following][0] in (")", "`") and tokens[following][1]:
        following += 1
    return following < len(tokens) and not tokens[following][1]


def quoted_substitution_runs_git(tokens, index, fed=False):
    """True when the word at `index` is a quoted command substitution whose last
    word is git and that a word follows (`"$(which git)" push …`): the output
    runs with those words as its arguments (issue 655 D7 review). `fed` is set
    at an argument position that reads a pipe or redirection, where the words
    come from there and none need follow (`echo p origin t | xargs "$(which
    git)"`)."""
    value, is_operator = tokens[index]
    if (
        is_operator or ("$(" not in value and "`" not in value)
        or ASSIGNMENT_PREFIX.match(value) is not None
        or (not fed and (index + 1 >= len(tokens) or tokens[index + 1][1]))
    ):
        return False
    pieces = [value]
    for separator in SEGMENT_SEPARATORS:
        pieces = [part for piece in pieces for part in piece.split(separator)]
    return any(
        reading and GIT_RAW_WORD.fullmatch(reading[-1]) is not None
        for piece in pieces
        for reading in (raw_words(piece), raw_words(piece, glued=True))
    )


ASSIGNED_VARIABLE = re.compile(r"\$(\w+)")
# A whole-word `${...}` (a double-quoted `"${G}"`, `"${G:-x}"`, `"${X:-git}"`
# tokenises to one word); its group is the text between the braces.
WORD_BRACED_VARIABLE = re.compile(r"\$\{(.*)\}", re.DOTALL)
BRACED_VARIABLE = re.compile(r"(\w+)(?::?[-=+?].*)?", re.DOTALL)


def git_assigned_names(token_lists):
    """The names assigned a git word anywhere in the command (`G=git`,
    `export G=/usr/bin/git`), so `$G` and `${G}` can be read as git (issue 655
    D2). A value is a git word when its basename is `git` or `git-<name>`, or
    its raw text satisfies GIT_RAW_WORD."""
    names = set()
    for tokens in token_lists:
        for position, (value, is_operator) in enumerate(tokens):
            match = None if is_operator else ASSIGNMENT_PREFIX.match(value)
            if match is None:
                continue
            assigned = value[match.end():]
            if (
                GIT_RAW_WORD.fullmatch(assigned) is not None
                or dashed_git_program(program_name(assigned))
                or substitution_yields_git(tokens, position, assigned)
            ):
                names.add(match.group("name"))
    return names


def raw_has_git_word(text):
    """True when raw `text` holds a word that is git by `GIT_RAW_WORD` or a
    `git-<name>` program (the word of `$(which git)` is `git`)."""
    return any(
        GIT_RAW_WORD.fullmatch(word) is not None or dashed_git_program(program_name(word))
        for reading in (raw_words(text), raw_words(text, glued=True))
        for word in reading
    )


def substitution_yields_git(tokens, position, assigned):
    """True when the assignment word at `position`, whose value text is
    `assigned`, takes a command substitution whose text holds a git word
    (`G=$(which git)`, `G="$(command -v git)"`, `` G=`which git` ``): `$G` may
    then be git, which the guard cannot resolve (issue 655 D2 review)."""
    if "$(" in assigned or "`" in assigned:
        return raw_has_git_word(assigned)
    if assigned not in ("", "$"):
        return False
    following = tokens[position + 1:position + 2]
    if not following or not following[0][1] or following[0][0] not in ("(", "`"):
        return False
    if assigned == "" and following[0][0] == "(":
        return False
    body = []
    for word, word_is_operator in tokens[position + 2:]:
        if word_is_operator and word in (")", "`"):
            break
        if not word_is_operator:
            body.append(word)
    return raw_has_git_word(" ".join(body))


def git_command_names(token_lists):
    """The names `hash` or `alias` binds to a git word (`hash g=/usr/bin/git`,
    `alias g=git`), so the bare command word `g` is read as git (issue 655 D2
    review). `hash -p /usr/bin/git g` is refused as a mention of git."""
    names = set()
    for tokens in token_lists:
        for position, (value, is_operator) in enumerate(tokens):
            if is_operator or program_name(value) not in ("hash", "alias"):
                continue
            words = []
            for word, word_is_operator in tokens[position + 1:]:
                if word_is_operator:
                    break
                words.append(word)
            for word in words:
                bound, equals, target = word.partition("=")
                if equals and bound and not bound.startswith("-"):
                    first = target.split()[0] if target.split() else ""
                    if (
                        GIT_RAW_WORD.fullmatch(first) is not None
                        or dashed_git_program(program_name(first))
                    ):
                        names.add(bound)
    return names


def git_spelling(tokens, index, assigned, hashed=frozenset()):
    """(program, run_start) when the non-operator token at `index` is a git word
    in some spelling, else None (issue 655 D2, D7). `run_start` is where the
    words that follow it begin.

    Covers a plain `git` or `git-<name>` word by basename, the same word after
    `$` (`$'git'` tokenises to `$git`), a variable assigned a git word
    (`$G`, `${G}`, and the same inside one word, `"${G}"`) and the braced
    default `${G:-git}`, whose run starts after its closing `}`. A leading `=`
    is zsh's `=git` expansion of the command's path, and a bare word `hashed`
    to git (`hash g=/usr/bin/git`) runs git too.
    """
    value = tokens[index][0]
    if value in hashed:
        return "git", index + 1
    if value.startswith("="):
        value = value[1:]
    name = program_name(value)
    if name == "git" or dashed_git_program(name):
        return name, index + 1
    stripped = program_name(value.lstrip("$"))
    if value.startswith("$") and (stripped == "git" or dashed_git_program(stripped)):
        return stripped, index + 1
    variable = ASSIGNED_VARIABLE.fullmatch(value)
    if variable is not None and variable.group(1) in assigned:
        return "git", index + 1
    word_braced = WORD_BRACED_VARIABLE.fullmatch(value)
    if word_braced is not None:
        inner = word_braced.group(1)
        braced = BRACED_VARIABLE.fullmatch(inner)
        if GIT_RAW_WORD.fullmatch(inner) is not None or (
            braced is not None and braced.group(1) in assigned
        ):
            return "git", index + 1
    if (
        index >= 2 and tokens[index - 1] == ("{", True)
        and tokens[index - 2] == ("$", False)
    ):
        braced = BRACED_VARIABLE.fullmatch(value)
        if GIT_RAW_WORD.fullmatch(value) is not None or (
            braced is not None and braced.group(1) in assigned
        ):
            start = index + 1
            if tokens[start:start + 1] == [("}", True)]:
                start += 1
            return "git", start
    return None


# Issue 655 D11: per allowlisted git subcommand, the options whose value git
# runs as a command (a transport program, a hook-like exec, a config entry such
# as `core.fsmonitor`, a template carrying hooks). The subcommand allowlist
# alone cannot see them, because the subcommand itself cannot transmit refs.
GIT_COMMAND_OPTIONS = {
    "archive": frozenset({"--exec"}),
    "clone": frozenset({"--upload-pack", "-u", "--config", "-c", "--template"}),
    "fetch": frozenset({"--upload-pack"}),
    "grep": frozenset({"--open-files-in-pager", "-O"}),
    "init": frozenset({"--template"}),
    "ls-remote": frozenset({"--upload-pack", "-u"}),
    "pull": frozenset({"--upload-pack"}),
    "rebase": frozenset({"--exec", "-x"}),
}


def git_command_option(subcommand, words):
    """The first word of `words` that is a command option of `subcommand`
    (GIT_COMMAND_OPTIONS), else None (issue 655 D11).

    A `--` word matches by its part before any `=` when that part is at least
    three characters and a `--` spelling of the subcommand starts with it, since
    git accepts any unambiguous abbreviation (`--exe`, `--upload`). A `-` word
    of two or more characters matches when any letter of its cluster is a short
    spelling (`-ix`, `-Osh`). Every word is scanned, an option value or an
    operand after `--` included: a word that only looks like an option can only
    refuse more.
    """
    options = GIT_COMMAND_OPTIONS.get(subcommand, frozenset())
    for word in words:
        # An option can hide inside a word that carries an expansion
        # (`"${X:---exec=sh p.sh}"`): in a word that does not start with `-`,
        # every `-` that follows one of `:=+?-` starts a candidate too.
        candidates = [word] + ([] if word.startswith("-") else [
            word[position:] for position in range(1, len(word))
            if word[position] == "-" and word[position - 1] in ":=+?-"
        ])
        for candidate in candidates:
            if candidate.startswith("--"):
                name = candidate.partition("=")[0]
                if len(name) >= 3 and any(
                    spelling.startswith(name)
                    for spelling in options if spelling.startswith("--")
                ):
                    return word
            elif candidate.startswith("-") and len(candidate) >= 2:
                if any("-" + letter in options for letter in candidate[1:]):
                    return word
    return None


# Issue 655 D12: the environment names a git invocation may be given. Anything
# else under GIT_ can hand git a command or other configuration
# (`GIT_SEQUENCE_EDITOR`, `GIT_CONFIG_COUNT`, `GIT_SSH_COMMAND`, `GIT_EXEC_PATH`).
GIT_ASSIGNMENT_ALLOWED = frozenset({
    "GIT_TRACE", "GIT_TRACE2", "GIT_TRACE2_EVENT", "GIT_TRACE2_PERF",
    "GIT_TRACE_CURL", "GIT_TRACE_PACKET", "GIT_TRACE_PERFORMANCE",
    "GIT_TRACE_SETUP", "GIT_CURL_VERBOSE", "GIT_TERMINAL_PROMPT",
    "GIT_OPTIONAL_LOCKS", "GIT_ADVICE", "GIT_FLUSH", "GIT_MERGE_VERBOSITY",
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE",
    "GIT_LITERAL_PATHSPECS", "GIT_GLOB_PATHSPECS", "GIT_NOGLOB_PATHSPECS",
    "GIT_ICASE_PATHSPECS", "LANG", "LC_ALL", "LC_MESSAGES", "TZ", "NO_COLOR",
    "TERM", "COLUMNS",
})
# Issue 655 D12 (b): variables git runs as a program though they carry no `GIT_`
# prefix; refused wherever they are assigned.
GIT_COMMAND_VARIABLES = frozenset({"EDITOR", "VISUAL", "PAGER"})


def git_assignment_problem(names, strict):
    """The refusal for the first assigned name in `names` that can make git run
    a command or read other configuration, else None (issue 655 D12).

    `strict` judges the prefix of a git word, where only GIT_ASSIGNMENT_ALLOWED
    passes. Otherwise (an assignment anywhere in the command) a name is refused
    when it starts with `GIT_` and is not allowlisted, or is in
    GIT_COMMAND_VARIABLES.
    """
    for name in names:
        if strict:
            refused = name not in GIT_ASSIGNMENT_ALLOWED
        else:
            refused = (
                name.startswith("GIT_") and name not in GIT_ASSIGNMENT_ALLOWED
            ) or name in GIT_COMMAND_VARIABLES
        if refused:
            return (
                f"the assignment {shown_value(name)}= can make git run a "
                f"command or read other configuration; {INVOCATION_FORM_HINT}"
            )
    return None


def git_prefix_assignments(tokens, index):
    """The names assigned by the non-operator tokens between the last operator
    token before `index` (the segment start when none) and `index`, in order
    (issue 655 D12 a). This covers `X=1 git …`, `env X=1 git …` and
    `timeout 5 env X=1 git …`."""
    start = 0
    for position in range(index - 1, -1, -1):
        if tokens[position][1]:
            start = position + 1
            break
    names = []
    for value, is_operator in tokens[start:index]:
        match = None if is_operator else ASSIGNMENT_PREFIX.match(value)
        if match is not None:
            names.append(match.group("name"))
    return names


def git_names_subcommand(words):
    """True when a word remains in `words` after git's leading global options
    (an option the table does not know counts as one: it is refused elsewhere)."""
    index = 0
    while index < len(words) and words[index].startswith("-"):
        word = words[index]
        if word in GIT_GLOBAL_OPTIONS:
            index += 1 + GIT_GLOBAL_OPTIONS[word]
            continue
        option, equals, _value = word.partition("=")
        if equals and option.startswith("--") and GIT_GLOBAL_OPTIONS.get(option) == 1:
            index += 1
            continue
        return True
    return index < len(words)


def git_transmit_problem(program, words, truncation, tail=(), fed=False):
    """The refusal for a git word that could transmit refs and is not a
    lifecycle form, else None (issue 655 D4, D5, D8, D9).

    `program` is the word, `words` follow it to the end of its run, `truncation`
    is the operator that cut the run, else None, and `tail` holds the words that
    follow that operator in the same segment, which still belong to the git
    invocation and so are scanned for command options (`git rebase $(x) --exec
    …`). `fed` is set at an argument position that reads a pipe or redirection
    (`echo p origin t | xargs git`): a run that names no subcommand then takes
    it from stdin and is refused. A
    `git-<name>` program is refused outright. Git itself is walked through
    GIT_GLOBAL_OPTIONS and must name a subcommand in GIT_LOCAL_SUBCOMMANDS; a
    run cut by an opening operator before its subcommand is certain is refused.
    """
    name = program_name(program)
    if name != "git":
        if dashed_git_program(name):
            return (
                f"the git program {shown_value(name)} runs a git subcommand "
                f"directly; {INVOCATION_FORM_HINT}"
            )
        return None
    index = 0
    while index < len(words) and words[index].startswith("-"):
        word = words[index]
        if word in GIT_GLOBAL_OPTIONS:
            index += 1 + GIT_GLOBAL_OPTIONS[word]
            continue
        option, equals, _value = word.partition("=")
        if equals and option.startswith("--") and GIT_GLOBAL_OPTIONS.get(option) == 1:
            index += 1
            continue
        return (
            f"git global option {shown_value(word)} is not accepted; "
            f"{INVOCATION_FORM_HINT}"
        )
    if index >= len(words):
        if truncation is not None:
            return GIT_UNCERTAIN_PROBLEM
        if fed:
            return GIT_FED_PROBLEM
        return None
    subcommand = words[index]
    if index == len(words) - 1 and truncation is not None:
        return GIT_UNCERTAIN_PROBLEM
    if subcommand not in GIT_LOCAL_SUBCOMMANDS:
        return (
            f"git {shown_value(subcommand)} is not a known local git subcommand; "
            f"an alias, a git-* program or a transport could transmit refs; "
            f"{INVOCATION_FORM_HINT}"
        )
    if subcommand == "config" and any(
        word.lower() == "core.hookspath" or word.lower().startswith("core.hookspath=")
        for word in list(words[index + 1:]) + list(tail)
    ):
        return HOOKS_PATH_PROBLEM
    option = git_command_option(subcommand, list(words[index + 1:]) + list(tail))
    if option is not None:
        return (
            f"git {shown_value(subcommand)} {shown_value(option)} can run a "
            f"command the guard cannot judge; {INVOCATION_FORM_HINT}"
        )
    return None


def git_argument_problem(program, words, truncation, tail=(), fed=False):
    """The transmit refusal for a git word at an argument position (`xargs git
    …`, `timeout 5 git …`, `find -exec git …`): exactly the command-position
    rule (issue 655 D7). This is the argument-position call site's own seam."""
    return git_transmit_problem(program, words, truncation, tail, fed)


SEPARATOR_RUN = re.compile("([" + re.escape("".join(sorted(SEGMENT_SEPARATORS))) + "]+)")


def raw_git_names(pieces):
    """The names the raw `pieces` bind to a git word: an assignment, `hash` or
    `alias` target that is a git word (`G=git`, `hash g=/usr/bin/git`), or an
    empty assignment followed by a substitution holding one (`G=$(which git)`),
    so `$G`, `${G}` and a bare `g` can be read as git (issue 655 D2 review)."""
    names = set()
    for piece in pieces:
        for reading in (raw_words(piece), raw_words(piece, glued=True)):
            for position, word in enumerate(reading):
                match = ASSIGNMENT_PREFIX.match(word)
                if match is None:
                    continue
                value = word[match.end():]
                if (
                    GIT_RAW_WORD.fullmatch(value) is not None
                    or dashed_git_program(program_name(value))
                    or (value == "" and any(
                        GIT_RAW_WORD.fullmatch(later) is not None
                        for later in reading[position + 1:]))
                ):
                    names.add(match.group("name"))
    return names


def names_session_marker(word):
    """True when `word` assigns, unsets or names the agent session variable
    (issue 672 D3): `CLAUDECODE=…`, or exactly `CLAUDECODE`, `-uCLAUDECODE` or
    `--unset=CLAUDECODE`. A read such as `$CLAUDECODE` never matches."""
    match = ASSIGNMENT_PREFIX.match(word)
    if match is not None and match.group("name") == AGENT_SESSION_VARIABLE:
        return True
    return word in (
        AGENT_SESSION_VARIABLE, f"-u{AGENT_SESSION_VARIABLE}",
        f"--unset={AGENT_SESSION_VARIABLE}",
    )


def wrapper_clears_session(wrapper, options):
    """True when the option words of an `env` or `exec` (`options`, the words
    after its name) clear the agent session variable (issue 672 D3): `env`
    options that empty the environment (`-`, `-i`, a short cluster holding `i`,
    `--ignore-environment` or an unambiguous prefix of it), `env`'s unset
    option naming it in any spelling (`-u X`, `-uX`, a cluster such as `-vuX`,
    `--unset X`, `--unset=X` or an abbreviation such as `--unse=X`), or an
    `exec` option cluster holding `c`. The walk stops at `--` and at the first
    word that is not an option; the caller cuts `options` at an operator."""
    pending = None
    for option in options:
        if pending is not None:
            if pending == "unset" and option == AGENT_SESSION_VARIABLE:
                return True
            pending = None
            continue
        if option == "--" or not option.startswith("-"):
            break
        if option == "-":
            return True
        kind, attached = wrapper_option(wrapper, option)
        unsets = False
        if option.startswith("--"):
            name, equals, value = option.partition("=")
            if wrapper == "env" and len(name) >= 3:
                if "--ignore-environment".startswith(name):
                    return True
                if "--unset".startswith(name):
                    # getopt_long takes any unambiguous prefix, which
                    # `wrapper_option` does not list for this option
                    unsets = True
                    kind, attached = "argument", value if equals else None
        else:
            letters = WRAPPER_SHORT_OPTIONS_WITH_ARGUMENT[wrapper]
            for letter in option[1:]:
                if letter in letters:
                    unsets = wrapper == "env" and letter == "u"
                    break
                if letter == ("i" if wrapper == "env" else "c"):
                    return True
        if unsets and attached == AGENT_SESSION_VARIABLE:
            return True
        if kind is not None and attached is None:
            pending = "unset" if unsets else "skip"
    return False


def session_marker_problem(tokens):
    """SESSION_MARKER_PROBLEM when a segment's `tokens` clear the agent session
    variable (issue 672 D3), else None: a word naming it (`names_session_marker`)
    or an `env` or `exec` whose options clear it (`wrapper_clears_session`)."""
    for index, (value, is_operator) in enumerate(tokens):
        if is_operator:
            continue
        if names_session_marker(value):
            return SESSION_MARKER_PROBLEM
        wrapper = program_name(value)
        if wrapper not in ("env", "exec"):
            continue
        options = []
        for option, option_is_operator in tokens[index + 1:]:
            if option_is_operator:
                break
            options.append(option)
        if wrapper_clears_session(wrapper, options):
            return SESSION_MARKER_PROBLEM
    return None


def raw_reading_transmits(reading, names, fed):
    """True when a word of `reading` is a git word (or an assigned name, see
    `raw_git_names`) that could transmit refs, or an assignment that hands git a
    command. `fed` is set when the piece may read a pipe or redirection, so a git
    word after the first word that names no subcommand takes it from stdin."""
    for position, word in enumerate(reading):
        if dashed_git_program(program_name(word)) or names_session_marker(word):
            return True
        wrapper = program_name(word)
        if wrapper in ("env", "exec") and wrapper_clears_session(
                wrapper, reading[position + 1:]):
            return True
        match = ASSIGNMENT_PREFIX.match(word)
        if match is not None and git_assignment_problem(
                [match.group("name")], False) is not None:
            return True
        variable = None if match is not None else BRACED_VARIABLE.fullmatch(word)
        if (
            GIT_RAW_WORD.fullmatch(word) is not None
            or (variable is not None and variable.group(1) in names)
        ) and git_transmit_problem(
                "git", reading[position + 1:], None,
                fed=fed and position > 0) is not None:
            return True
    return False


def pipe_in(run):
    """True when the separator `run` holds a pipe (`|` or `|&`, not `||`)."""
    return "|" in run.replace("||", "")


def transmit_in_raw_text(text, names=frozenset(), depth=0, fed=False):
    """True when the raw `text` of an evaluator, `env -S` or unparseable segment
    holds a git word that could transmit refs (issue 655 D7).

    The text is split at every segment separator, and each piece's raw words, in
    both quote readings, are walked from every git word with
    `git_transmit_problem`; a `git-<name>` word counts on its own. A third
    reading splits the piece the way the shell does, so a quoted global-option
    operand (`git -C "/tmp status" p`) is one word, and a word that holds
    several words (`sh -c '…'`) is read again as text. `names` are the names
    already bound to git by the surrounding command; the text binds more
    (`G=git; $G p`). A piece is fed when `fed` says the text as a whole is
    (it follows a pipe, or the command holds a redirection), when a `|`
    comes before it anywhere in the text, so a compound command that follows a
    pipe is fed (`echo p | { true; xargs git; }`), or when the text holds a
    `<` (a redirection of a compound command, `exec <file`).
    """
    text = text.replace("\\\n", "")
    parts = SEPARATOR_RUN.split(text)
    fed = fed or "<" in text
    pieces = [
        (piece, fed or any(pipe_in(run) for run in parts[1:position:2]))
        for position, piece in enumerate(parts) if position % 2 == 0
    ]
    names = set(names) | raw_git_names([piece for piece, _ in pieces])
    for piece, fed in pieces:
        readings = [raw_words(piece), raw_words(piece, glued=True)]
        tokens = tokenize_segment(piece)
        if tokens is not None:
            readings.append([value for value, is_operator in tokens if not is_operator])
            if depth < 3:
                for value, is_operator in tokens:
                    if not is_operator and len(value.split()) > 1 and transmit_in_raw_text(
                            value, names, depth + 1, fed):
                        return True
        if any(raw_reading_transmits(reading, names, fed) for reading in readings):
            return True
    return False


def gh_invocation(program, words):
    """(operation, problem, None) for a guarded gh invocation, else None (issue 400 D4).

    Guarded when `words` begin with a guarded path (`pr merge`, `pr create`,
    `release create`, `release new`), or when a flag word comes before an
    occurrence of the path's second word that follows its first. Flags after
    the path never matter. A gh named by a path is refused (D6); a flag between
    the path words is left to the verb's grammar.
    """
    paths = [
        (list(verb_words[1:]), operation)
        for verb_words, operation in GUARDED_VERBS
        if verb_words[0] == "gh"
    ]
    found = next((operation for path, operation in paths if words[:2] == path), None)
    for (first, second), operation in paths:
        if found is not None:
            break
        if first not in words:
            continue
        start = words.index(first) + 1
        if any(
            words[position] == second
            and any(word.startswith("-") for word in words[:position])
            for position in range(start, len(words))
        ):
            found = operation
    if found is None:
        return None
    if program != "gh":
        return found, f"gh named by a path; {INVOCATION_FORM_HINT}", None
    return found, None, None


def guarded_invocation(tokens, index, later=""):
    """(operation, problem, directory) when the word at `index` starts a guarded
    git or gh invocation, matched by basename, else None.

    Its words run to the next operator token. `problem` is a recognition refusal
    or None; the caller still judges the command position. `later` is the raw
    text of the command's segments after this one. A run that ends at an
    operator (a substitution, expansion or grouping) before its verb is
    certain reads on through the rest of this segment and then `later`, in
    both raw readings, because a separator inside a substitution
    (`git -C $(pwd | cat) push …`) splits the invocation across segments
    (issue 400 D15, D17). A git verb is uncertain when the run ends inside the
    global options or carries an option other than `-C`, whose value the walk
    cannot bound (`git -c k=$(…) push …`); a gh verb is uncertain when the run
    carries a flag or ends before a third word (`gh pr --repo $(…) merge …`,
    issue 400 D18).
    """
    value, operator = tokens[index]
    if operator:
        return None
    words = []
    truncated = False
    for word, word_is_operator in tokens[index + 1:]:
        if word_is_operator:
            truncated = True
            break
        words.append(word)
    name = program_name(value)
    if name == "git":
        reader, uncertain = git_invocation, git_verb_uncertain(words)
    elif name == "gh":
        reader = gh_invocation
        uncertain = len(words) < 3 or any(word.startswith("-") for word in words)
    else:
        return None
    found = reader(value, words)
    if found is None and truncated and uncertain:
        rest = [word for word, is_operator in tokens[index + 1:] if not is_operator]
        loose = next(
            (
                reading for reading in (
                    reader(value, ["--"] + rest + raw_words(later, glued))
                    for glued in (False, True)
                )
                if reading is not None
            ),
            None,
        )
        if loose is not None:
            found = loose[0], (
                f"the {name} invocation continues past a shell substitution or "
                f"grouping; {INVOCATION_FORM_HINT}"
            ), None
    return found


def git_verb_uncertain(words):
    """True when the leading git global options in `words` leave the subcommand
    unknown: they run to the end of `words`, or one of them is not `-C`, so
    the walk cannot know how many words it takes (issue 400 D15, D18)."""
    index = 0
    while index < len(words) and words[index].startswith("-"):
        if words[index] != "-C" or index + 1 == len(words):
            return True
        index += 2
    return index >= len(words)


def git_option_operands(tokens, index):
    """Indices of the `-C` values in the leading global-option run of the word
    at `index` (issue 400 D15): arguments of git, never programs."""
    operands = []
    position = index + 1
    while (position < len(tokens) and not tokens[position][1]
           and tokens[position][0].startswith("-")):
        if (tokens[position][0] == "-C" and position + 1 < len(tokens)
                and not tokens[position + 1][1]):
            operands.append(position + 1)
            position += 2
        else:
            position += 1
    return operands


def unvalidatable(
    segment, reason, mentions_label=False, assigned=frozenset(), fed=False,
):
    """Every guarded verb found in `segment`'s raw text, all refused for `reason`.

    A verb is found when its words occur in order in either reading of the
    text's quotes and backslashes (issue 400 D16), or when its words joined by
    one space are a substring of the text or of the text with its quotes and
    backslashes deleted (issue 400 D17, the base `336d9e05` check): a word such
    as `${CMD:-git` or `-df` has no word equal to the verb's, yet the shell runs
    the verb. When `mentions_label` is set, the raise-label edit is refused too.
    `fed` is set when the segment may read a pipe or redirection (see
    `guarded_operations`).
    """
    readings = [raw_words(segment), raw_words(segment, glued=True)]
    texts = [segment, "".join(c for c in segment if c not in RAW_GLUE_CHARS)]
    found = [
        (operation, segment, reason, None)
        for verb_words, operation in GUARDED_VERBS
        if any(verb_occurs_in_order(words, verb_words) for words in readings)
        or any(" ".join(verb_words) in text for text in texts)
    ]
    if transmit_in_raw_text(segment, assigned, fed=fed):
        found.append(("transmit", segment, reason, None))
    if mentions_label:
        found.append(("label", segment, reason, None))
    return found


def guarded_operations(command):
    """(operation, segment, problem, directory) for every guarded verb the shell
    would run. `directory` is the accepted `git -C` value, else None.

    `problem` is None when the segment can be handed to that verb's grammar,
    and a reason when the verb sits where the guard cannot validate it: an
    unparseable command or untokenisable segment, shell source passed to an
    evaluator (`eval`, `sh -c`, matched by basename), or a position that is not
    a command position (an argument to some other program). Those are refused
    rather than waved through — the parser and the shell have to agree, and
    where they cannot the guard fails closed. A segment in which env takes
    `-S`/`--split-string` is judged like an evaluator segment, on its whole
    text, because env appends the remaining words to the split payload.

    Recognition refuses an invocation form before any lookup (issue 400 D6,
    D15, D18): git or gh named by a path, a git global option other than one
    `-C`, a repeated `-C` or a `-C` directory that is not one plain word, and a
    git or gh run that ends at an operator before its verb is certain and so
    continues past a substitution or grouping, read on through the rest of the
    command.

    The `label` operation is mention-gated: it is considered only when the
    command's tokens mention the raise label, always carries a problem, and is
    refused for any `gh` invocation, in any position, whose `--add-label` value
    contains it. That check runs over every tokenised segment at once, because
    a separator inside a substitution splits a `gh` word from its label. A
    word that mentions the label inside a `$(…)` or backtick substitution is
    refused too, because a quoted substitution still runs.
    """
    parsed = split_segments_with_runs(command)
    if parsed is None:
        return unvalidatable(
            command, "the command could not be parsed",
            mentions_raise_label([command]),
        )
    segments, runs = parsed
    found = []
    stream = []
    token_lists = [
        tokens for tokens in map(tokenize_segment, segments) if tokens is not None
    ]
    assigned = git_assigned_names(token_lists)
    hashed = git_command_names(token_lists)
    # A redirection anywhere in the command may feed a compound command that
    # holds a later segment (`{ xargs git; } <<< 'push …'`, `exec <f; xargs
    # git`), and a pipe before a segment may feed it through a grouping, a loop
    # or a conditional (`echo p | { true; xargs git; }`): a segment is fed by
    # either, not only by the pipe or redirection of its own piece (issue 655
    # final review).
    redirected = any(
        not is_operator and value.startswith("<")
        for tokens in token_lists for value, is_operator in tokens
    ) or len(token_lists) < len(segments) and "<" in command
    for position, segment in enumerate(segments):
        tokens = tokenize_segment(segment)
        if tokens is None:
            found.extend(unvalidatable(
                segment, "the segment could not be tokenised",
                mentions_raise_label([segment]), assigned | hashed,
                redirected or any(pipe_in(run) for run in runs[:position]),
            ))
            continue
        # A segment may read a pipe when a `|` comes before it anywhere, or
        # the command holds a redirection (`<f`, `<<<x`, `<<EOF`).
        fed = redirected or any(pipe_in(run) for run in runs[:position])
        # Every tokenised segment joins the label stream, evaluator segments
        # included: `gh pr edit $(sh -c '…'; true) --add-label …` puts the
        # `gh` word in an evaluator segment and its label in the next one.
        stream.extend(tokens)
        stream.append((";", True))
        flags, split_string = command_position_flags(tokens)
        values = [value for value, _ in tokens]
        mentions = mentions_raise_label(values)
        # An env -S or evaluator segment is judged on its whole text, and its
        # words are still recognised below with that reason as their problem:
        # a git or gh run in it may continue into a later segment
        # (`git -C $(sh -c pwd | cat) push …`, issue 400 D15, D19), which the
        # segment's own raw text never shows.
        raw_reason = None
        if split_string:
            raw_reason = SPLIT_STRING_REASON
        elif any(
            flag and program_name(value) in SHELL_EVALUATORS
            for flag, value in zip(flags, values)
        ):
            raw_reason = EVALUATOR_REASON
        if raw_reason is not None:
            found.extend(unvalidatable(
                segment, raw_reason, mentions, assigned | hashed, fed))
        if raw_reason == EVALUATOR_REASON and transmit_in_raw_text(
                command, assigned | hashed):
            # An evaluator with no command text of its own reads its source
            # from stdin (`echo 'git p' | sh`, `sh <<EOF`), which is another
            # segment or a heredoc body the segments drop (issue 655 D7).
            found.append(("transmit", segment, raw_reason, None))
        # Issue 655 D12 (b): an assignment that hands git a command or other
        # configuration, in any position of the command.
        for value, is_operator in tokens:
            match = None if is_operator else ASSIGNMENT_PREFIX.match(value)
            if match is None:
                continue
            problem = git_assignment_problem([match.group("name")], False)
            if problem is not None:
                found.append((
                    "transmit", segment,
                    raw_reason if raw_reason is not None else problem, None,
                ))
        # Issue 672 D3: a segment that clears the agent session variable, in
        # every repository, so the pre-push hook cannot be made to stand down.
        marker_problem = session_marker_problem(tokens)
        if marker_problem is not None:
            found.append((
                "transmit", segment,
                raw_reason if raw_reason is not None else marker_problem, None,
            ))
        operands = set()
        for index in range(len(tokens)):
            if index in operands:
                continue
            if not tokens[index][1] and program_name(tokens[index][0]) == "git":
                operands.update(git_option_operands(tokens, index))
            invocation = guarded_invocation(
                tokens, index, "\n".join(segments[position + 1:]))
            if invocation is None:
                # Issue 655: a git word the recognition above did not classify
                # is refused unless it is a local subcommand (D4-D9), in every
                # position (D7).
                spelling = (
                    None if tokens[index][1]
                    else git_spelling(tokens, index, assigned, hashed)
                )
                if quoted_substitution_runs_git(tokens, index, fed and not flags[index]):
                    found.append((
                        "transmit", segment,
                        raw_reason if raw_reason is not None else GIT_UNCERTAIN_PROBLEM,
                        None,
                    ))
                if spelling is not None:
                    value, run_start = spelling
                    run = []
                    cut = None
                    cut_at = None
                    for offset in range(run_start, len(tokens)):
                        word, word_is_operator = tokens[offset]
                        if word_is_operator:
                            cut, cut_at = word, offset
                            break
                        run.append(word)
                    tail = [
                        word for word, word_is_operator in tokens[cut_at + 1:]
                        if not word_is_operator
                    ] if cut_at is not None else []
                    truncation = (
                        cut if cut is not None and opening_operator(tokens, index, cut)
                        else None
                    )
                    if truncation is None and bare_git_supplies_command(
                            tokens, index, cut_at, run):
                        truncation = cut if cut is not None else ")"
                    # A braced default `${G:-git}` tokenises as `$`, `{`, the
                    # word and `}`: its position is the `$` word's.
                    word_start = (
                        index - 2
                        if index >= 2 and tokens[index - 1] == ("{", True)
                        and tokens[index - 2] == ("$", False)
                        else index
                    )
                    reader = git_transmit_problem if flags[index] else git_argument_problem
                    problem = git_assignment_problem(
                        git_prefix_assignments(tokens, index), True)
                    if problem is None:
                        problem = reader(
                            value, run, truncation, tail=tail,
                            fed=fed and not flags[word_start])
                    if problem is not None:
                        found.append((
                            "transmit", segment,
                            raw_reason if raw_reason is not None else problem, None,
                        ))
                continue
            operation, problem, directory = invocation
            if not flags[index]:
                problem, directory = NOT_COMMAND_POSITION, None
            if problem is None and raw_reason is not None:
                problem, directory = raw_reason, None
            found.append((operation, segment, problem, directory))
    # Judged over every tokenised segment at once: a separator inside a
    # substitution (`gh pr edit $(gh pr view | jq …) --add-label …`) splits
    # the `gh` word from its label, so a per-segment check would miss it.
    if mentions_raise_label([value for value, _ in stream]) and adds_raise_label(stream):
        found.append(("label", command, RAISE_LABEL_REFUSAL, None))
    # A substitution inside a double-quoted word (`x="$(gh pr edit … )"`) runs,
    # but the tokeniser keeps it as one word, so the guard cannot see its `gh`.
    # A word that mentions the label and carries a substitution fails closed.
    if any(
        not is_operator and mentions_raise_label([value])
        and ("$(" in value or "`" in value)
        for value, is_operator in stream
    ):
        found.append((
            "label", command,
            "a command substitution inside a quoted word cannot be validated",
            None,
        ))
    # The same holds for a git word the quoted substitution runs (issue 655 D2):
    # `echo "$(git p origin t)"` reaches the remote with `alias.p=push`.
    if any(
        not is_operator and ("$(" in value or "`" in value)
        and transmit_in_raw_text(value, assigned | hashed)
        for value, is_operator in stream
    ):
        found.append((
            "transmit", command,
            "a command substitution inside a quoted word cannot be validated",
            None,
        ))
    return found


# Wrapper options that consume an argument, so the word holding it is not the
# wrapped command. Used by the verb pass. Short options
# may be clustered (`env -iu FOO`), and an argument may be attached (`-uanis`,
# `--user=anis`). An option not listed here is treated as a flag, so the word
# after it is taken as the command word.
WRAPPER_SHORT_OPTIONS_WITH_ARGUMENT = {
    "sudo": frozenset("ugCDhprtTU"),
    "exec": frozenset("a"),
    "env": frozenset("uCS"),
}
WRAPPER_OPTIONS_WITH_ARGUMENT = {
    "sudo": frozenset({
        "--user", "--group", "--close-from", "--chdir", "--host", "--prompt",
        "--role", "--type", "--command-timeout", "--other-user",
    }),
    "exec": frozenset(),
    "env": frozenset({"--unset", "--chdir", "--split-string"}),
}
# `env -S`/`--split-string` hands its argument to env, which splits it into a
# command line and runs it. That argument is command text, not a name.
ENV_SPLIT_STRING = "--split-string"
def wrapper_option(wrapper, option):
    """(kind, attached) for a wrapper option word.

    `kind` is None for a flag, "argument" for an option that consumes an
    argument and "payload" for env's split-string, whose argument is command
    text. `attached` is the argument carried in the same word, or None when the
    option takes the next word.
    """
    payload_letters = "S" if wrapper == "env" else ""
    if option.startswith("--"):
        name, equals, attached = option.partition("=")
        if wrapper == "env" and len(name) >= 3 and ENV_SPLIT_STRING.startswith(name):
            # getopt_long accepts any unambiguous prefix (`--split`); reading
            # more as command text only ever refuses more.
            return "payload", attached if equals else None
        if name in WRAPPER_OPTIONS_WITH_ARGUMENT.get(wrapper, ()):
            return "argument", attached if equals else None
        return None, None
    letters = WRAPPER_SHORT_OPTIONS_WITH_ARGUMENT.get(wrapper, frozenset())
    for index in range(1, len(option)):
        letter = option[index]
        if letter in letters:
            kind = "payload" if letter in payload_letters else "argument"
            return kind, option[index + 1:] or None
    return None, None


def detaching_normalised(command):
    """`command` with backslash-newline pairs deleted, then `DETACHING_DELETED`."""
    return DETACHING_DELETED.sub("", command.replace("\\\n", ""))


def detaching_texts(command):
    """The texts `detaching_word` scans, in order: the raw command, then its
    deletion copy."""
    return (command, detaching_normalised(command))


def detaching_hit(text):
    """The lowercased detaching word of the first match in `text`, or None."""
    matches = [
        match for match in (
            DETACHING_PATTERN.search(text), DETACHING_DEFAULT_PATTERN.search(text),
        ) if match
    ]
    if not matches:
        return None
    first = min(matches, key=lambda match: match.start(1)).group(1)
    return detaching_normalised(first).lower()


# The read-only allowlist of issue 656 (D4). Every admitted option is enumerated,
# so an option that changes where the pattern comes from (`-f`), drops it
# (`--files`) or runs a program (rg's `--pre`, `--hostname-bin`, `-z`) refuses the
# admission.
DETACHING_SEARCH_FLAG_LETTERS = {"grep": "cEFHhiIlLnoqRrsvwx", "rg": "FHiIlLnNoqsSuvwx"}
DETACHING_SEARCH_FLAGS = {
    "grep": frozenset({
        "--count", "--extended-regexp", "--fixed-strings", "--with-filename",
        "--no-filename", "--ignore-case", "--files-with-matches",
        "--files-without-match", "--line-number", "--only-matching", "--quiet",
        "--recursive", "--dereference-recursive", "--no-messages", "--invert-match",
        "--word-regexp", "--line-regexp",
    }),
    "rg": frozenset({
        "--count", "--fixed-strings", "--ignore-case", "--smart-case",
        "--case-sensitive", "--files-with-matches", "--line-number",
        "--no-line-number", "--only-matching", "--quiet", "--hidden", "--no-ignore",
        "--word-regexp", "--line-regexp", "--invert-match", "--follow",
        "--with-filename", "--no-filename", "--heading", "--no-heading",
    }),
}
DETACHING_SEARCH_VALUE_OPTIONS = {
    "grep": frozenset({
        "-A", "-B", "-C", "-m", "--max-count", "--after-context", "--before-context",
        "--context", "--include", "--exclude", "--exclude-dir",
    }),
    "rg": frozenset({
        "-A", "-B", "-C", "-m", "--max-count", "--after-context", "--before-context",
        "--context", "-g", "--glob", "--iglob", "-t", "--type", "-T", "--type-not",
        "-d", "--max-depth",
    }),
}
DETACHING_GH_TEXT_OPTIONS = frozenset({"--title", "-t", "--body", "-b"})
DETACHING_GH_VALUE_OPTIONS = frozenset({"--repo", "-R", "--base", "-B", "--head", "-H"})


def _detaching_content(text, kind):
    """A word's text with its outer quote pair removed when it is quoted."""
    return text[1:-1] if kind == "quoted" else text


def _detaching_holds_hit(content):
    return any(detaching_hit(text) is not None for text in detaching_texts(content))


def _detaching_search_roles(program, contents, kinds):
    """The roles of the words after the program of a grep or rg call, or None."""
    letters = DETACHING_SEARCH_FLAG_LETTERS[program]
    flags = DETACHING_SEARCH_FLAGS[program]
    value_options = DETACHING_SEARCH_VALUE_OPTIONS[program]
    roles = []
    after_dashdash = False
    expect = None
    explicit = False
    for content, kind in zip(contents, kinds):
        if kind == "and":
            return None
        if expect is not None:
            roles.append(expect)
            expect = None
        elif after_dashdash or not content.startswith("-") or content == "-":
            roles.append("positional")
        elif content == "--":
            roles.append("other")
            after_dashdash = True
        elif content in ("-e", "--regexp"):
            roles.append("other")
            expect = "pattern"
            explicit = True
        elif content.startswith("--regexp="):
            roles.append("pattern")
            explicit = True
        elif content in flags or (
            content[1:] and not content.startswith("--")
            and all(letter in letters for letter in content[1:])
        ):
            roles.append("other")
        elif content in value_options:
            roles.append("other")
            expect = "other"
        elif content.startswith("--") and "=" in content \
                and content.split("=", 1)[0] in value_options:
            roles.append("other")
        else:
            return None
    if expect is not None:
        return None
    if not explicit:
        if "positional" not in roles:
            return None
        roles[roles.index("positional")] = "pattern"
    return ["other" if role == "positional" else role for role in roles]


def _detaching_gh_roles(contents, kinds):
    """The roles of the words of a gh issue/pr create/comment call, or None."""
    if any(kind == "and" for kind in kinds):
        return None
    if len(contents) < 3 or any(kind != "plain" for kind in kinds[:3]) \
            or contents[0] != "gh" or contents[1] not in ("issue", "pr") \
            or contents[2] not in ("create", "comment"):
        return None
    roles = ["other"] * 3
    index = 3
    while index < len(contents):
        content, kind = contents[index], kinds[index]
        if kind == "plain" and content in DETACHING_GH_TEXT_OPTIONS:
            if index + 1 >= len(contents):
                return None
            roles += ["other", "text" if kinds[index + 1] == "quoted" else "other"]
            index += 2
        elif kind == "plain" and content in DETACHING_GH_VALUE_OPTIONS:
            if index + 1 >= len(contents):
                return None
            roles += ["other", "other"]
            index += 2
        elif kind == "plain" and content == "--draft" \
                and contents[1] == "pr" and contents[2] == "create":
            roles.append("other")
            index += 1
        elif content.startswith("-"):
            return None
        else:
            roles.append("other")
            index += 1
    return roles


def detaching_mention_allowed(command):
    """True when `command` is one of the two read-only forms that may name a
    detaching word (issue 656, D4), read with `lifecycle_words`: the word only in
    the pattern of one enumerated grep or rg call, or only in a quoted title or
    body of one `gh issue|pr create|comment` call after at most the `unset`
    credential scrub. Anything not enumerated refuses the admission."""
    words, problem = lifecycle_words(command)
    if problem is not None or not words:
        return False
    kinds = [kind for _, kind in words]
    contents = [_detaching_content(text, kind) for text, kind in words]
    first_content, first_kind = contents[0], kinds[0]
    if first_kind != "plain":
        return False
    if first_content in ("grep", "rg"):
        rest = _detaching_search_roles(first_content, contents[1:], kinds[1:])
        roles = None if rest is None else ["other"] + rest
    elif first_content == "unset":
        names = []
        index = 1
        while (index < len(words) and kinds[index] == "plain"
               and contents[index] in GH_ENV_TOKEN_NAMES
               and contents[index] not in names and len(names) < 2):
            names.append(contents[index])
            index += 1
        if not names or index >= len(words) or kinds[index] != "and":
            return False
        call = _detaching_gh_roles(contents[index + 1:], kinds[index + 1:])
        roles = None if call is None else ["other"] * (index + 1) + call
    elif first_content == "gh":
        roles = _detaching_gh_roles(contents, kinds)
    else:
        return False
    if roles is None:
        return False
    return not any(
        role == "other" and _detaching_holds_hit(content)
        for role, content in zip(roles, contents)
    )


def detaching_word(command):
    """The detaching word (`nohup`, `setsid`, `disown`) in `command`, or None.

    Policy-free and global. It reads no shell syntax (issue 656): the raw text is
    matched first, then a copy with the characters that rebuild a word deleted
    (`no''hup`, `no{,}hup`), and the earliest hit of the first text that has one
    is named. So a mention, a heredoc body, a comment, `nohup.out` and a word
    handed to `xargs` or `timeout` are refused too, unless
    `detaching_mention_allowed` admits the command (the narrow read-only
    allowlist: a grep or rg pattern, or quoted gh issue/pr text). A default-value expansion
    (`${x:-nohup}`, `${@:-nohup}`, `${a[0]:-no''hup}`) and a word after `$` and one
    digit, `!`, `@` or `*` count.
    Accepted residuals: a word assembled at run time, a glob, an ANSI-C escape,
    a brace expansion with a non-empty other alternative, and a word glued to a
    letter other than `c` or `s` as an attached option value a program runs.
    """
    for text in detaching_texts(command):
        word = detaching_hit(text)
        if word is not None:
            return None if detaching_mention_allowed(command) else word
    return None


def lifecycle_words(command):
    """(words, problem): `command` read as the allowlist's words, each (text, kind)
    with kind `plain`, `quoted` or `and` (a `&&`), split at spaces and tabs; else
    (None, the first thing outside the grammar)."""
    words = []
    index, length = 0, len(command)
    while index < length:
        character = command[index]
        if character in " \t":
            index += 1
            continue
        if command.startswith("&&", index):
            kind, end = "and", index + 2
        elif character in "'\"":
            close = command.find(character, index + 1)
            if close == -1:
                return None, f"an unterminated {character} quote"
            active = next((c for c in command[index + 1:close] if c in DOUBLE_QUOTE_ACTIVE),
                          None) if character == '"' else None
            if active is not None:
                return None, f"`{active}` inside double quotes"
            kind, end = "quoted", close + 1
        else:
            match = PLAIN_WORD.match(command, index)
            if match is None:
                return None, f"`{shown_character(character)}` outside quotes"
            if character == "=":
                return None, "a word beginning with `=`"
            kind, end = "plain", match.end()
        if end < length and command[end] not in " \t":
            following = command[end]
            if kind == "quoted" or following in "'\"":
                return None, "a quoted string glued to another word"
            return None, f"`{shown_character(following)}` outside quotes"
        words.append((command[index:end], kind))
        index = end
    return words, None


def lifecycle_shape(command):
    """(directory, problem) for a command holding a lifecycle verb (issue 418).

    Admitted only as `[<unset scrub> && ][cd <dir> && ][env -u scrub ]<verb> <args>`,
    with at most one scrub, `<verb>` one of `LIFECYCLE_VERBS` (`git -C <dir>` before
    `push` or `branch -d`), `<dir>` a plain word and every word as `lifecycle_words`
    reads it. `directory` is the cd word, else None; `problem` is None when admitted.
    The scrub's exact spelling is left to the verb's grammar.
    """
    words, problem = lifecycle_words(command)
    if problem is not None:
        return None, problem
    segments = [[]]
    for text, kind in words:
        if kind == "and":
            segments.append([])
        else:
            segments[-1].append((text, kind))
    if any(not segment for segment in segments):
        return None, "an empty command beside `&&`"
    *prelude, verb = segments
    names = set(GH_ENV_TOKEN_NAMES)
    directory, scrubbed = None, False
    for segment in prelude:
        values = [text for text, _ in segment]
        if (values[0] == "unset" and not scrubbed and directory is None
                and 2 <= len(values) <= 3 and set(values[1:]) <= names
                and len(set(values[1:])) == len(values) - 1):
            scrubbed = True
        elif values[0] == "cd" and directory is None and len(segment) == 2 \
                and segment[1][1] == "plain":
            directory = values[1]
        else:
            return None, f"`{shown_value(' '.join(values))} &&` before the verb"
    values = [text for text, _ in verb]
    if not scrubbed and values[0] == "env":
        position = 1
        unset = []
        while values[position:position + 1] == ["-u"] and position + 1 < len(values) \
                and values[position + 1] in names - set(unset):
            unset.append(values[position + 1])
            position += 2
        if unset:
            values = values[position:]
    if values[1:2] == ["-C"] and values[:1] == ["git"] and len(verb) > 2 \
            and PLAIN_WORD.fullmatch(values[2]):
        values = ["git"] + values[3:]
    if not any(tuple(values[:len(form)]) == form for form in LIFECYCLE_VERBS):
        lead = next((index for index, value in enumerate(values) if value in ("git", "gh")), 0)
        if lead:
            return None, f"`{shown_value(' '.join(values[:lead]))}` before the verb"
        return None, f"`{shown_value(' '.join(values[:3]))}` is not a lifecycle verb"
    return directory, None


def cd_directory_problem(command, directory):
    """Why the leading `cd <directory>` of `command`, which `lifecycle_shape` admitted,
    leaves the verb's directory unresolved, or None: it is spelled `cd <directory> && `
    with single spaces, after any `unset` scrub spelling, and `<directory>` is
    absolute with no `..` component (issue 418 D1)."""
    rest = command
    for spelling in SCRUB_PREFIXES:
        if spelling.startswith("unset ") and strip_spelling(rest, spelling) is not None:
            rest = strip_spelling(rest, spelling)
            break
    if (strip_spelling(rest, f"cd {directory} && ") is None
            or not os.path.isabs(directory) or ".." in directory.split("/")):
        return CD_PRELUDE_PROBLEM
    return None


def strip_spelling(text, spelling):
    """The rest of `text` after a leading `spelling`, or None.

    None also when the rest is empty or begins with whitespace: a doubled space
    is not the spelling (issue 400 D13).
    """
    if not text.startswith(spelling):
        return None
    rest = text[len(spelling):]
    if not rest or rest[0].isspace():
        return None
    return rest


def strip_scrub_prefix(text):
    """`text` without its leading credential-scrub prefix, else `text` unchanged."""
    for prefix in SCRUB_PREFIXES:
        rest = strip_spelling(text, prefix)
        if rest is not None:
            return rest
    return text


def canonical_text(operation, text, directory):
    """The text `operation`'s grammar judges (issue 400 D13).

    Push and PR creation are judged per segment, with leading whitespace dropped;
    every operation whose form-table entry carries the scrub-prefix property (all
    but branch deletion, issue 400 D2) then loses an exact scrub prefix; and,
    with a `git -C` `directory`, a leading `git -C <directory> ` becomes `git `.
    Text in any other spelling is returned whole, for the grammar to refuse.
    """
    if operation in ("push", "pr-create"):
        text = text.lstrip()
    if FORM_TABLE[operation]["scrub_prefix"]:
        text = strip_scrub_prefix(text)
    if directory is not None:
        rest = strip_spelling(text, f"git -C {directory} ")
        if rest is not None:
            text = "git " + rest
    return text


def target_directory(directory, cwd):
    """The directory a push's repository context is built from (issue 400 D7).

    The `git -C` `directory` joined to the payload `cwd` (an absolute one stands
    alone; no normalisation, so git resolves it as the shell's `git -C` would),
    or `cwd` with no `-C`. None when there is none to use: a relative
    `directory` with no string `cwd`, or no `-C` and no string `cwd`.
    """
    base = cwd if isinstance(cwd, str) and cwd else None
    if directory is None:
        return base
    if os.path.isabs(directory):
        return directory
    if base is None:
        return None
    return os.path.join(base, directory)


GITHUB_URL_PREFIXES = (
    "git@github.com:",
    "ssh://git@github.com/",
    "https://github.com/",
    "http://github.com/",
)


def github_slug(url):
    """The owner/name slug a GitHub remote URL names, or None."""
    url = url.strip()
    if url.endswith(".git"):
        url = url[: -len(".git")]
    for prefix in GITHUB_URL_PREFIXES:
        if url.startswith(prefix):
            slug = url[len(prefix):]
            break
    else:
        return None
    slug = slug.strip("/")
    if SLUG_PATTERN.fullmatch(slug) is None:
        return None
    return slug


class RepositoryLookupFailed(Exception):
    """The lookup of a checkout's origin could not run to an answer (timed out or could not
    start), which is not the same as a checkout that names no repository."""


def detect_repository(git_bin, cwd, timeout, strict=False):
    """Return the owner/name slug of cwd's origin remote, or None.

    With `strict`, a lookup that times out or cannot start raises `RepositoryLookupFailed`
    instead of returning None (issue 1149 review)."""
    if not isinstance(cwd, str) or not cwd:
        return None
    try:
        child = subprocess.run(
            [git_bin, "-C", cwd, "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as error:
        if strict:
            raise RepositoryLookupFailed(
                "timed out" if isinstance(error, subprocess.TimeoutExpired) else "could not start"
            ) from error
        return None
    if child.returncode != 0:
        return None
    return github_slug(child.stdout)


PUSH_URL_LOOKUP = ("remote", "get-url", "--push", "--all", "origin")
PUSH_URL_TIMEOUT = "push URL lookup timed out"
PUSH_URL_UNRESOLVED = "cannot resolve origin's push URL"


def push_url_slug_problem(url, repository):
    """Why the GitHub push URL `url` does not name `repository`, or None.

    The one predicate both modes apply to a push URL: the text mode to each URL
    git reports for `origin` (`push_url_problem`), the pre-push mode to the URL
    git hands the hook (issue 672 D2).
    """
    if github_slug(url) != repository:
        return f"push URL {shown_value(url)} does not name {repository}"
    return None


def push_url_problem(context):
    """Why origin's effective push URL does not name the judged repository, or None.

    Issue 655 D3/D10. git itself applies `remote.origin.pushurl`,
    `url.<base>.insteadOf` and `url.<base>.pushInsteadOf`, so the guard asks git
    for the push URLs and never reimplements the rewriting. `--all` lists every
    `pushurl` entry, and git pushes to each of them, so each must name the
    repository. A lookup that times out, cannot start, fails or prints nothing
    is a problem too.
    """
    try:
        child = subprocess.run(
            [context.git_bin, "-C", context.cwd, *PUSH_URL_LOOKUP],
            capture_output=True, text=True, timeout=context.timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return PUSH_URL_TIMEOUT
    except OSError:
        return PUSH_URL_UNRESOLVED
    urls = [line.strip() for line in child.stdout.splitlines() if line.strip()]
    if child.returncode != 0 or not urls:
        return PUSH_URL_UNRESOLVED
    for url in urls:
        problem = push_url_slug_problem(url, context.repository)
        if problem is not None:
            return "origin's " + problem
    return None


def default_branch(git_bin, cwd, timeout):
    """The branch origin/HEAD points at, or None when it cannot be resolved."""
    if not isinstance(cwd, str) or not cwd:
        return None
    try:
        child = subprocess.run(
            [git_bin, "-C", cwd, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if child.returncode != 0:
        return None
    prefix = "origin/"
    value = child.stdout.strip()
    if not value.startswith(prefix):
        return None
    name = value[len(prefix):]
    if REF_NAME_PATTERN.fullmatch(name) is None:
        return None
    return name


class BasePolicy:
    """The values of the base policy file named by `--base-policy`.

    The store file holds the five trusted members: the authorized owners, the
    literal integration bases and the absolute paths of `git`, `gh` and `jq`.
    Nothing outside this file supplies any of them; a test passes any file of the
    same schema.
    """

    def __init__(self, document):
        self.authorized_owners = frozenset(document["authorized_owners"])
        self.integration_bases = dict(document["integration_bases"])
        self.git_bin = document["git_bin"]
        self.gh_bin = document["gh_bin"]
        self.jq_bin = document["jq_bin"]


def _read_policy_bytes(path):
    """(bytes, None) for a regular file at `path` of at most POLICY_MAX_BYTES, else (None, why).

    The open never blocks (`O_NONBLOCK`, so a FIFO with no writer opens at once), and
    the descriptor's own `fstat` decides: anything but a regular file, a FIFO or a
    device such as `/dev/zero` behind a symlink included, is refused before a byte
    is read, and so is a file over the cap or one that grows past it while read.
    """
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOCTTY)
    except OSError as error:
        return None, str(error)
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            return None, "not a regular file"
        if status.st_size > POLICY_MAX_BYTES:
            return None, f"larger than {POLICY_MAX_BYTES} bytes"
        chunks = []
        size = 0
        while size <= POLICY_MAX_BYTES:
            chunk = os.read(descriptor, POLICY_MAX_BYTES + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        if size > POLICY_MAX_BYTES:
            return None, f"larger than {POLICY_MAX_BYTES} bytes"
        return b"".join(chunks), None
    except OSError as error:
        return None, str(error)
    finally:
        os.close(descriptor)


def _load_json_object(path, keys):
    """(document, None) for a JSON object at `path` with exactly `keys`, else (None, reason)."""
    data, why = _read_policy_bytes(path)
    if data is None:
        return None, f"cannot load {path}: {why}"
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        # A document nested past the interpreter's limit raises RecursionError, which is
        # an unloadable file like any other (issue 1149 review).
        return None, f"cannot load {path}: {error}"
    if not isinstance(document, dict) or set(document) != keys:
        return None, f"{path}: expected an object with exactly the keys {', '.join(sorted(keys))}"
    return document, None


def load_base_policy(path):
    """(BasePolicy, None) for a well-formed base policy at `path`, else (None, reason)."""
    document, reason = _load_json_object(path, BASE_POLICY_KEYS)
    if document is None:
        return None, reason
    owners = document["authorized_owners"]
    if not isinstance(owners, list) or not all(
        isinstance(owner, str) and owner for owner in owners
    ):
        return None, f"{path}: authorized_owners must be a list of non-empty strings"
    bases = document["integration_bases"]
    if not isinstance(bases, dict) or not all(
        isinstance(repository, str) and repository and isinstance(base, str) and base
        for repository, base in bases.items()
    ):
        return None, f"{path}: integration_bases must be an object of non-empty strings"
    for key in ("git_bin", "gh_bin", "jq_bin"):
        if not isinstance(document[key], str) or not os.path.isabs(document[key]):
            return None, f"{path}: {key} must be an absolute path"
    return BasePolicy(document), None


def production_problem(production):
    """Why a row's `production` value is malformed, else None.

    An object with PRODUCTION_KEYS and optionally PRODUCTION_OPTIONAL_KEYS:
    `key_files` is a list of non-empty strings and `mcp_tools` a list of
    `mcp__<server>__<tool>` names; `changes` and `read_only` are lists
    (possibly empty) of objects with exactly PRODUCTION_COMMAND_KEYS, each a
    non-empty `id` and a non-empty `argv` list of non-empty strings, and
    `release_profile` is a non-empty string; `console_activation`, when present, is a
    non-empty string equal to the `id` of one `changes` entry.
    """
    if not isinstance(production, dict) or not (
        PRODUCTION_KEYS <= set(production) <= PRODUCTION_KEYS | PRODUCTION_OPTIONAL_KEYS
    ):
        keys = ", ".join(sorted(PRODUCTION_KEYS))
        optional = ", ".join(sorted(PRODUCTION_OPTIONAL_KEYS))
        return f"must be an object with exactly the keys {keys} and optionally {optional}"
    if "key_files" in production:
        globs = production["key_files"]
        if not isinstance(globs, list) or not all(
            isinstance(glob, str) and glob for glob in globs
        ):
            return "key_files must be a list of non-empty strings"
    if "mcp_tools" in production:
        names = production["mcp_tools"]
        if not isinstance(names, list) or not all(
            isinstance(name, str) and MCP_TOOL_NAME.fullmatch(name) for name in names
        ):
            return "mcp_tools must be a list of mcp__<server>__<tool> names"
    for member in ("changes", "read_only"):
        commands = production[member]
        if not isinstance(commands, list):
            return f"{member} must be a list"
        for command in commands:
            if not isinstance(command, dict) or set(command) != PRODUCTION_COMMAND_KEYS:
                keys = ", ".join(sorted(PRODUCTION_COMMAND_KEYS))
                return f"{member} entries must be objects with exactly the keys {keys}"
            if not isinstance(command["id"], str) or not command["id"]:
                return f"{member} entry id must be a non-empty string"
            argv = command["argv"]
            if (
                not isinstance(argv, list)
                or not argv
                or not all(isinstance(word, str) and word for word in argv)
            ):
                return f"{member} entry argv must be a non-empty list of non-empty strings"
    profile = production["release_profile"]
    if not isinstance(profile, str) or not profile:
        return "release_profile must be a non-empty string"
    if "console_activation" in production:
        activation = production["console_activation"]
        if not isinstance(activation, str) or activation not in [
            command["id"] for command in production["changes"]
        ]:
            return "console_activation must name the id of one changes entry"
    return None


def load_compiled_policy(path):
    """(rows, None) for a well-formed compiled policy at `path`, else ({}, reason).

    The file supplies derived rows alone: `derived_repositories` maps a repository
    slug to its row, and the guard reads a row's two branches and its required checks and leaves
    `evidence` and `derivation` to the compiler that wrote them. A row may also carry
    `production`, the project's declared production rules, validated by
    `production_problem`; a row without it loads as before. The path is read
    without blocking and only when it is a regular file of at most
    POLICY_MAX_BYTES (`_read_policy_bytes`). A file that is anything else, cannot
    be read or carries any malformed row contributes no row at all, so it is never
    partially read, and it never blocks a call by itself.
    """
    document, reason = _load_json_object(path, COMPILED_POLICY_KEYS)
    if document is None:
        return {}, reason
    derived = document["derived_repositories"]
    if not isinstance(derived, dict):
        return {}, f"{path}: derived_repositories must be an object"
    for repository, row in derived.items():
        if not isinstance(repository, str) or SLUG_PATTERN.fullmatch(repository) is None:
            return {}, f"{path}: derived_repositories key {repository!r} is not an owner/name slug"
        if (
            not isinstance(row, dict)
            or not DERIVED_ROW_KEYS <= set(row) <= DERIVED_ROW_KEYS | DERIVED_ROW_OPTIONAL_KEYS
        ):
            keys = ", ".join(sorted(DERIVED_ROW_KEYS))
            return {}, (
                f"{path}: derived_repositories {repository} must be an object "
                f"with exactly the keys {keys} and optionally production"
            )
        for key in ("default_branch", "integration_branch"):
            branch = row[key]
            if not isinstance(branch, str) or REF_NAME_PATTERN.fullmatch(branch) is None:
                return {}, f"{path}: derived_repositories {repository} {key} must be a branch name"
        checks = row["required_checks"]
        if (
            not isinstance(checks, list)
            or not all(isinstance(check, str) and check for check in checks)
            or len(set(checks)) != len(checks)
        ):
            return {}, (
                f"{path}: derived_repositories {repository} required_checks "
                "must be a list of distinct non-empty strings"
            )
        if not isinstance(row["evidence"], dict):
            return {}, f"{path}: derived_repositories {repository} evidence must be an object"
        if "production" in row:
            reason = production_problem(row["production"])
            if reason is not None:
                return {}, f"{path}: derived_repositories {repository} production {reason}"
    if document["derivation"] is not None and not isinstance(document["derivation"], dict):
        return {}, f"{path}: derivation must be null or an object"
    return dict(derived), None


def bounded_timeout(deadline, child_timeout):
    """The bound for the next child, read immediately before it starts.

    A child starts only when its whole bound ends before the deadline: the bound
    is never clipped to the time left, so a child that starts has the full
    `child_timeout` and one that cannot is refused before it starts.
    """
    if deadline - time.monotonic() < child_timeout:
        raise DeadlineExhausted()
    return child_timeout


DIRECTORY_CHANGING_WORDS = frozenset({"cd", "pushd", "popd", "chdir"})
# Programs that run a later word of their own run as a command (issue 1149 D5),
# matched by basename. Only a one-word production verb uses it.
PRODUCTION_RUNNERS = frozenset({
    "xargs", "timeout", "nice", "ionice", "stdbuf", "watch", "chrt", "taskset", "flock",
    "doas", "caffeinate", "find", "parallel", "strace", "unbuffer", "nix", "nix-shell",
    "devenv", "direnv",
})
# The runners that run a quoted word of their own run as shell text (issue 1192 D10).
PRODUCTION_SHELL_RUNNERS = frozenset({"watch", "nix-shell", "flock", "parallel"})
# `devenv shell` also runs its first word as shell text; see `devenv_command_words`.
PRODUCTION_ROUTE = "release transaction preview and release transaction run"


def production_verb(argv):
    """The words a production command is matched by: the program by basename, then the
    arguments exactly."""
    return [program_name(argv[0]), *argv[1:]]


def words_in_order(words, needed):
    """True when the exact `needed` words occur in `words` in order, not necessarily
    adjacent; True for no needed word."""
    position = 0
    if not needed:
        return True
    for word in words:
        if word == needed[position]:
            position += 1
            if position == len(needed):
                return True
    return False


def production_raw_hit(text, verb):
    """The raw-text reading of a production verb in `text`: its words in order in either
    reading of the quotes and backslashes, or its words joined by one space a substring of
    the text or of the text with its quotes and backslashes deleted."""
    readings = (raw_words(text), raw_words(text, glued=True))
    texts = (text, "".join(c for c in text if c not in RAW_GLUE_CHARS))
    return (
        any(verb_occurs_in_order(words, verb) for words in readings)
        or any(" ".join(verb) in each for each in texts)
    )


def production_lifted(run, verb, read_only):
    """True when `run`, the words from a match onward, begins with a read-only verb that
    properly extends the production verb `verb`."""
    return any(
        len(each) > len(verb)
        and each[:len(verb)] == verb
        and len(run) >= len(each)
        and program_name(run[0]) == each[0]
        and run[1:len(each)] == each[1:]
        for each in read_only
    )


REDIRECTION = re.compile(r"[0-9]*(?:&>>?|>>|>&|<&|<>|<<<|<<-?|>|<)(.*)", re.DOTALL)
ENV_PAYLOAD_PROGRAM = "env"


def production_flags(tokens):
    """`command_position_flags` of `tokens` with each redirection read out of the way, as the
    shell does: `>/dev/null ./deploy.sh` runs `./deploy.sh`, and a bare `>` or `2>` takes the
    word after it as its target. Same result shape, over all of `tokens`."""
    kept = []
    skip = False
    for index, (value, operator) in enumerate(tokens):
        if skip:
            skip = False
            continue
        redirection = None if operator else REDIRECTION.fullmatch(value)
        if redirection is not None:
            skip = not redirection.group(1)
            skip = skip and index + 1 < len(tokens) and not tokens[index + 1][1]
            continue
        kept.append(index)
    kept_flags, split_string = command_position_flags([tokens[index] for index in kept])
    flags = [False] * len(tokens)
    for index, flag in zip(kept, kept_flags):
        flags[index] = flag
    return flags, split_string


def production_runner_hides_shell(tokens, flags):
    """True when a run whose command-position program is in `PRODUCTION_RUNNERS` holds a
    shell (`timeout 600 sh -c ...`, `devenv shell -- bash -c ...`) or an `env -S` later, since
    the shell text it runs is one quoted token that no verb's first word matches."""
    start = 0
    while start < len(tokens):
        if tokens[start][1]:
            start += 1
            continue
        end = start
        while end < len(tokens) and not tokens[end][1]:
            end += 1
        flagged = next((k for k in range(start, end) if flags[k]), None)
        if flagged is not None and program_name(tokens[flagged][0]) in PRODUCTION_RUNNERS:
            seen_env = False
            for value, _ in tokens[flagged + 1:end]:
                if program_name(value) in SHELL_EVALUATORS:
                    return True
                if program_name(value) == ENV_PAYLOAD_PROGRAM:
                    seen_env = True
                elif seen_env and value.startswith("-") and wrapper_option("env", value)[0] == "payload":
                    return True
        start = end
    return False


ANSI_C_ESCAPES = {"'": "'", "\\": "\\", '"': '"', "n": "\n", "t": "\t"}


def ansi_c_unquoted(text):
    """`text` with each `$'...'` rewritten as the plain single-quoted word the shell reads
    it as, and the `$` of each `$"..."` deleted, so `$'just'` reads as `just` rather than
    `$just` and `$'it\\'s'` keeps its escaped quote inside the string. A backslash escape
    inside `$'...'` is decoded when it is one of `\\'`, `\\\\`, `\\"`, `\\n` and `\\t` and kept
    as written otherwise. Quotes, backslashes and comments outside a `$'...'` are tracked as
    the segmenter does, so a `$'` inside another quote stays as it is; a `$'` with no closing
    quote is left for the segmenter to refuse."""
    return "".join(ansi_c_pieces(text)[0])


def ansi_c_pieces(text):
    """`(pieces, guarded)`: the pieces `ansi_c_unquoted` joins, and the indices of those that
    are a heredoc's delimiter redirection or body, which the shell reads as written and a
    later rewrite of the text must therefore leave alone."""
    out = []
    guarded = set()
    pending = []
    quote = None
    index = 0
    length = len(text)
    while index < length:
        character = text[index]
        if quote == "'":
            out.append(character)
            quote = None if character == "'" else quote
            index += 1
            continue
        if character == "\\" and index + 1 < length:
            out.append(text[index:index + 2])
            index += 2
            continue
        if quote == '"':
            out.append(character)
            quote = None if character == '"' else quote
            index += 1
            continue
        if character == "#" and (
            not out or out[-1] in " \t\n" or out[-1] in SEGMENT_SEPARATORS
        ):
            while index < length and text[index] != "\n":
                out.append(text[index])
                index += 1
            continue
        if character == "<" and text.startswith("<<", index):
            # A heredoc body is skipped as the segmenter skips it, so an apostrophe in
            # it never opens a quote here that the segmenter does not see.
            if text.startswith("<<<", index):
                out.append("<<<")
                index += 3
                continue
            cursor, delimiter, strip_tabs, expands = read_heredoc_delimiter(text, index)
            if delimiter is None:
                # The segmenter refuses the same text, and its bodies stay as written.
                guarded.add(len(out))
                out.append(text[index:])
                break
            guarded.add(len(out))
            out.append(text[index:cursor])
            pending.append((delimiter, strip_tabs, expands))
            index = cursor
            continue
        if character == "\n" and pending:
            out.append(character)
            index += 1
            end = skip_heredoc_bodies(text, index, pending)
            pending = []
            if end is None:
                # The remainder holds bodies the scan could not read: it stays as
                # written, so the segmenter refuses it as it does the original text
                # and no earlier body is closed by a rewritten delimiter (issue 1173).
                guarded.add(len(out))
                out.append(text[index:])
                break
            body = text[index:end]
            guarded.add(len(out))
            if body.endswith("\n"):
                out.append(body[:-1])
                out.append("\n")
            else:
                out.append(body)
            index = end
            continue
        if text.startswith("$'", index):
            cursor = index + 2
            body = []
            while cursor < length and text[cursor] != "'":
                if text[cursor] == "\\" and cursor + 1 < length:
                    body.append(ANSI_C_ESCAPES.get(text[cursor + 1], text[cursor:cursor + 2]))
                    cursor += 2
                else:
                    body.append(text[cursor])
                    cursor += 1
            if cursor >= length:
                out.append(text[index:])
                break
            out.append("'" + "".join(body).replace("'", "'\\''") + "'")
            index = cursor + 1
            continue
        if text.startswith('$"', index):
            out.append('"')
            quote = '"'
            index += 2
            continue
        if character in "'\"":
            quote = character
        out.append(character)
        index += 1
    return out, guarded


def redirections_unglued(text):
    """`text` with the `&` of a redirection operator (`2>&1`, `&>file`, `<&3`) deleted, so
    the segmenter does not cut the command there and leave the redirection's target as a
    command word. Only the `&` goes, and a quoted `&` was inert, so no word is hidden. The
    `|` of a noclobber `>|` goes for the same reason, so the segmenter does not cut there."""
    return (
        text.replace("&>>", ">>").replace("&>", ">").replace(">&", ">").replace("<&", "<")
        .replace(">|", ">")
    )


def production_text(command):
    """`command` as the segmenter reads it: ANSI-C words rewritten and redirection operators
    unglued everywhere except in a heredoc's delimiter and body, so the segmenter ends each
    body on the same line the shell does (issue 1173)."""
    pieces, guarded = ansi_c_pieces(command)
    out = []
    run = []
    for position, piece in enumerate(pieces):
        if position in guarded:
            out.append(redirections_unglued("".join(run)))
            run = []
            out.append(piece)
        else:
            run.append(piece)
    out.append(redirections_unglued("".join(run)))
    return "".join(out)


def joined_continuations(text):
    """`text` with each backslash-newline deleted, as the shell joins the lines."""
    return text.replace("\\\n", "")


PIPE_RUNS = frozenset({"|", "|&"})
INLINE_SHELL_OPTION = re.compile(r"-[A-Za-z]*c[A-Za-z]*")


def unquoted_readings(segment):
    """`(bare, live)` for `segment`: its text outside every quote, and outside single quotes,
    the text the shell may expand. A backslash-escaped pair stays in both, so an escaped quote
    never opens a quote and an escaped marker still counts."""
    bare = []
    live = []
    quote = None
    index = 0
    while index < len(segment):
        character = segment[index]
        if quote == "'":
            quote = None if character == "'" else quote
        elif character == "\\" and index + 1 < len(segment):
            if quote is None:
                bare.append(segment[index:index + 2])
            live.append(segment[index:index + 2])
            index += 1
        elif quote == '"':
            if character == '"':
                quote = None
            else:
                live.append(character)
        elif character in "'\"":
            quote = character
        else:
            bare.append(character)
            live.append(character)
        index += 1
    return "".join(bare), "".join(live)


def redirect_targets(tokens):
    """The words an output redirection of `tokens` writes to (`> f`, `>>f`, `2> f`)."""
    targets = []
    for index, (value, operator) in enumerate(tokens):
        match = None if operator else REDIRECTION.fullmatch(value)
        if match is None or ">" not in value[:len(value) - len(match.group(1))]:
            continue
        if match.group(1):
            targets.append(match.group(1))
        elif index + 1 < len(tokens) and not tokens[index + 1][1]:
            targets.append(tokens[index + 1][0])
    return targets


def devenv_command_words(tokens):
    """The word `devenv shell` splices unescaped into a bash script (`exec {cmd} ...`): the
    first word after `shell` that is not an option or the `--` separator. Only the arguments
    after it are passed literally, so a program name beside them stays a mention."""
    words = [value for value, _ in tokens]
    if "shell" not in words:
        return []
    for value in words[words.index("shell") + 1:]:
        if not value.startswith("-"):
            return [value]
    return []


def production_parse(command):
    """`(commands, code)` for `command`, or None when the guard reads the whole command as
    raw text: it cannot be parsed or tokenised, or a segment that hands text to a shell may
    take that text from somewhere the segments do not show (issue 1192 D10).

    `commands` is the tokens and command-position flags of each segment read as commands, with
    the raw text of the segments after it. `code` is the text of the segments that hand text
    to a shell, which counts as raw text: a command word that is an evaluator or `env -S`, or
    a runner holding one. The whole command is raw text when a shell is present with any of: a
    pipeline, a shell that reads a file or stdin (no `-c`, not `eval`), a `$` or backtick
    outside single quotes (a variable or substitution the shell expands), a `$`, backtick or
    `<` in the shell's own text, a `<`, `{` or `(` outside every quote (input, a group or a
    subshell: `echo 'just switch' | { true; sh; }`), or a file one segment redirects to that
    the shell's text names."""
    split = split_segments_with_runs(production_text(command))
    if split is None:
        return None
    segments, runs = split
    read = []
    for segment in segments:
        tokens = tokenize_segment(segment)
        if tokens is None:
            return None
        flags, split_string = production_flags(tokens)
        shell = split_string or any(
            flag and program_name(value) in SHELL_EVALUATORS
            for flag, (value, _) in zip(flags, tokens)
        ) or production_runner_hides_shell(tokens, flags)
        inline = split_string or any(
            value == "eval" or (not operator and INLINE_SHELL_OPTION.fullmatch(value))
            for value, operator in tokens
        )
        read.append((tokens, flags, shell, inline))
    if any(shell for _, _, shell, _ in read):
        if any(run in PIPE_RUNS for run in runs) or any(
            shell and not inline for _, _, shell, inline in read
        ):
            return None
        code_text = joined_continuations(
            "\n".join(s for s, (_, _, shell, _) in zip(segments, read) if shell)
        )
        code_words = set(raw_words(code_text)) | set(raw_words(code_text, glued=True))
        for segment, (tokens, _, shell, _) in zip(segments, read):
            bare, live = unquoted_readings(segment)
            if (
                any(c in bare for c in "<{(") or any(c in live for c in "$`")
                or (shell and any(c in segment for c in "$`<"))
                or (not shell and any(t in code_words for t in redirect_targets(tokens)))
            ):
                return None
    commands = [
        (tokens, flags, "\n".join(segments[position + 1:]))
        for position, (tokens, flags, shell, _) in enumerate(read)
        if not shell
    ]
    return commands, "\n".join(s for s, (_, _, shell, _) in zip(segments, read) if shell)


GH_VALUE_OPTIONS = frozenset({
    "assignee", "author", "base", "body", "body-file", "branch", "commit", "event", "field",
    "head", "header", "hostname", "input", "job", "jq", "json", "label", "limit", "message",
    "milestone", "name", "notes", "notes-file", "project", "raw-field", "ref", "reviewer",
    "search", "state", "status", "tag", "target", "template", "title", "user", "workflow",
})
GH_VALUE_LETTERS = frozenset("abBfFHjlLmnpqrsStT")


def gh_repository_words(run):
    """`run`'s words after the program, as the shell hands them to gh: a redirection
    (`>log`, `2>&1`, and the word a bare `>` takes) is not one of them."""
    words = []
    skip = False
    for word in run[1:]:
        if skip:
            skip = False
            continue
        redirection = REDIRECTION.fullmatch(word)
        if redirection is not None:
            skip = not redirection.group(1)
            continue
        words.append(word)
    return words


def gh_repository_selectors(run):
    """The repository flags of the `gh` run `run`, in order, each a `(value, doubtful)`
    pair, as gh's flag parser reads them: `--repo V`, `--repo=V`, `-R V`, `-RV`, `-R=V`, and
    `-R` inside a group of short flags (`-dR V`). The word after a value-taking option is
    that option's value and never a flag, and `--` ends the flags. `doubtful` is True for a
    read the guard cannot be sure of: `-R` behind another letter of its group, which may be
    a value-taking letter's text, and a value cut at a glued redirection. A flag with no
    value has value None (issue 1375)."""
    words = gh_repository_words(run)
    selectors = []
    position = 0
    while position < len(words):
        word = words[position]
        position += 1
        if word == "--":
            break
        if word.startswith("--"):
            name, equals, value = word[2:].partition("=")
            if name == "repo":
                if not equals:
                    value = words[position] if position < len(words) else None
                    position += 1
                selectors.append((value, False))
            elif not equals and name in GH_VALUE_OPTIONS:
                position += 1
        elif word.startswith("-") and len(word) > 1:
            for offset, letter in enumerate(word[1:], 1):
                if letter == "R":
                    value = word[offset + 1:]
                    value = value[1:] if value.startswith("=") else value
                    if not value:
                        value = words[position] if position < len(words) else None
                        position += 1
                    selectors.append((value, offset > 1))
                    break
                if letter in GH_VALUE_LETTERS:
                    if offset + 1 == len(word):
                        position += 1
                    break
    return selectors


def gh_named_repository(run):
    """`(slug, by_checkout)` for the `gh` run `run`: `slug` is the lower-cased `owner/repo`
    that the last repository flag names (the last wins, as in gh), else None; `by_checkout`
    is True when the checkout must be judged too. A run that names no repository, a value
    holding `$` or a backtick, one that does not end in `owner/repo` (`HOST/OWNER/REPO` and
    a trailing `.git` are read) and a flag with no value name nothing the guard can tell,
    so they are `(None, True)`; a doubtful read (see `gh_repository_selectors`) names its
    slug and is judged by the checkout as well (issue 1375)."""
    selectors = gh_repository_selectors(run)
    if not selectors:
        return None, True
    value, doubtful = selectors[-1]
    if not value or "$" in value or "`" in value:
        return None, True
    cut = min((value.index(c) for c in "<>" if c in value), default=None)
    if cut is not None:
        value, doubtful = value[:cut], True
    value = value[:-4] if value.endswith(".git") else value
    parts = value.split("/")
    if len(parts) < 2 or not parts[-1] or not parts[-2]:
        return None, True
    return f"{parts[-2]}/{parts[-1]}".lower(), doubtful


def add_production_hit(hits, hit, named, by_checkout):
    """Record `hit` in `hits`, a map of `(slug, index)` to `(named, by_checkout)`: the
    frozenset of repositories the runs that hit it name, and whether any run is judged by
    the checkout. The two are joined independently, so a run that names no repository
    never erases the repository another run names."""
    before, checkout = hits.get(hit, (frozenset(), False))
    hits[hit] = (before | named, checkout or by_checkout)


def production_hits(command, rules):
    """(hits, certain) for `command` against `rules`, a map of slug to its `production`
    member: the `(slug, index into changes)` pairs the shell would run, each mapped to
    `(named, by_checkout)`: the frozenset of repositories the `gh` runs that hit it name with
    `--repo` (issue 1375), and True when any run that hit it is judged by the checkout; and
    False for `certain` when any word of either raw reading is a directory change (issue
    1149 D5 to D7). A mention as another program's argument never hits a one-word verb."""
    raw = joined_continuations(command)
    verbs = {
        slug: (
            [production_verb(change["argv"]) for change in rule["changes"]],
            [production_verb(change["argv"]) for change in rule["read_only"]],
        )
        for slug, rule in rules.items()
    }
    certain = not any(
        program_name(word) in DIRECTORY_CHANGING_WORDS
        for words in (raw_words(raw), raw_words(raw, glued=True))
        for word in words
    )
    hits = {}
    parsed = production_parse(command)
    if parsed is None:
        raw_texts = [raw]
        commands = []
    else:
        commands, code = parsed
        raw_texts = [joined_continuations(code)] if code else []
    for text in raw_texts:
        for slug, (changes, _) in verbs.items():
            for index, verb in enumerate(changes):
                if production_raw_hit(text, verb):
                    add_production_hit(hits, (slug, index), frozenset(), True)
    for tokens, flags, later in commands:
        later = joined_continuations(later)
        later_words = (raw_words(later), raw_words(later, glued=True))
        for value, operator in tokens:
            if not operator and ("$(" in value or "`" in value):
                for slug, (changes, _) in verbs.items():
                    for index, verb in enumerate(changes):
                        if production_raw_hit(value, verb):
                            add_production_hit(hits, (slug, index), frozenset(), True)
        start = 0
        while start < len(tokens):
            if tokens[start][1]:
                start += 1
                continue
            end = start
            while end < len(tokens) and not tokens[end][1]:
                end += 1
            flagged = next((k for k in range(start, end) if flags[k]), None)
            runner = program_name(tokens[flagged][0]) if flagged is not None else None
            cut = end < len(tokens)
            if flagged is not None and runner in PRODUCTION_RUNNERS:
                # Shell text a runner takes as one word (`watch 'just switch'`,
                # `nix-shell --run '...'`, `flock f -c '...'`, `devenv shell 'just switch'`) is
                # read as raw text, wherever the runner sits in the run (`timeout 5 flock f -c
                # '...'`); a word an argv runner passes on (`timeout 5 echo 'just switch'`) is a
                # mention.
                for j in range(flagged, end):
                    word = program_name(tokens[j][0])
                    if word in PRODUCTION_SHELL_RUNNERS:
                        spoken = [token[0] for token in tokens[j + 1:end]]
                    elif word == "devenv":
                        spoken = devenv_command_words(tokens[j + 1:end])
                    else:
                        continue
                    for value in spoken:
                        if any(character.isspace() for character in value):
                            for slug, (changes, _) in verbs.items():
                                for index, verb in enumerate(changes):
                                    if production_raw_hit(value, verb):
                                        add_production_hit(hits, (slug, index), frozenset(), True)
            for i in range(start, end):
                name = program_name(tokens[i][0])
                run = [token[0] for token in tokens[i:end]]
                after = [token[0] for token in tokens[i + 1:] if not token[1]]
                for slug, (changes, read_only) in verbs.items():
                    for index, verb in enumerate(changes):
                        if name != verb[0]:
                            continue
                        if name != "gh" and hits.get((slug, index), (None, False))[1]:
                            continue
                        in_run = False
                        if len(verb) == 1:
                            matched = flags[i] or (
                                flagged is not None and i > flagged
                                and runner in PRODUCTION_RUNNERS
                            )
                        else:
                            in_run = words_in_order(run[1:], verb[1:])
                            matched = in_run or (
                                cut and any(
                                    words_in_order(after + words, verb[1:])
                                    for words in later_words
                                )
                            )
                        if matched and not production_lifted(run, verb, read_only):
                            # A `gh` run that names its repository is a command on that
                            # repository alone (issue 1375); every other reading is judged
                            # by the checkout.
                            named, by_checkout = (
                                gh_named_repository(run) if in_run and name == "gh"
                                else (None, True))
                            add_production_hit(
                                hits, (slug, index),
                                frozenset() if named is None else frozenset({named}),
                                by_checkout)
            start = end
    return hits, certain


def production_refusal_text(slug, rule, production):
    """The one sentence that refuses a production command (issue 1149 D8).

    The rule `production` names as `console_activation` is approved through the console's
    Activate (issue 1193); every other rule through the row's release profile.
    """
    head = (
        f"`{shown_value(shlex.join(rule['argv']))}` changes the production of {slug} "
        f"(production rule {shown_value(rule['id'])}), so it runs only through "
    )
    if production.get("console_activation") == rule["id"]:
        return f"{head}{CONSOLE_ACTIVATION_ROUTE}."
    return (
        f"{head}the release profile {shown_value(production['release_profile'])} "
        f"with {PRODUCTION_ROUTE}."
    )


def production_problem_for(command, rows, cwd, git_bin, timeout):
    """The reason to refuse `command` as a production command, or None.

    Only a row whose `production` has a `changes` entry takes part. With no hit nothing
    runs; with one, `detect_repository` names the payload cwd's repository. A command that
    may change directory is judged against every declaring row, that repository first,
    then by sorted slug; otherwise only that repository's rules refuse. A `gh` run that
    names its repository (`--repo`, `-R`) is judged against that repository's rules from any
    directory, and by the checkout only when some run of the command is not narrowed (issue
    1375). Inside a row the first
    rule in `changes` order that hits names the refusal.
    """
    rules = {
        slug: row["production"] for slug, row in rows.items()
        if row.get("production") and row["production"]["changes"]
    }
    if not rules:
        return None
    hits, certain = production_hits(command, rules)
    if not hits:
        return None
    here = None
    if any(by_checkout for _, by_checkout in hits.values()):
        try:
            here = detect_repository(git_bin, cwd, timeout, strict=True)
        except RepositoryLookupFailed as error:
            return (f"the repository lookup {error} for a command that may change the "
                    "production of a declared project, so the guard cannot judge it")
    order = [here] if here in rules else []
    if not certain:
        order += sorted(slug for slug in rules if slug != here)
    for slug in order + sorted(slug for slug in rules if slug not in order):
        for index, change in enumerate(rules[slug]["changes"]):
            if (slug, index) not in hits:
                continue
            named, by_checkout = hits[(slug, index)]
            if (by_checkout and slug in order) or slug.lower() in named:
                return production_refusal_text(slug, change, rules[slug])
    return None


FILE_EDIT_TOOLS = {"Edit": "file_path", "Write": "file_path", "MultiEdit": "file_path",
                   "NotebookEdit": "notebook_path"}
MCP_TOOL_PREFIX = "mcp__"


def mcp_refusal_text(tool, slug, release_profile):
    """The one sentence that refuses a declared production MCP tool (issue 1150)."""
    return (
        f"`{shown_value(tool)}` changes the production of {slug} (production MCP tool), so it "
        f"runs only through the release profile {shown_value(release_profile)} with "
        f"{PRODUCTION_ROUTE}."
    )


def key_file_refusal_text(relative, slug, glob, release_profile):
    """The one sentence that refuses a write to a declared key file (issue 1150)."""
    return (
        f"`{shown_value(relative)}` is a key file of {slug} (key file glob {shown_value(glob)}), "
        f"so it changes only through the release profile {shown_value(release_profile)} with "
        f"{PRODUCTION_ROUTE}."
    )


def mcp_tool_problem(tool_name, rows):
    """The reason to refuse the MCP tool `tool_name`, or None: the first project, by sorted
    slug, whose `production.mcp_tools` names it exactly. No child process runs."""
    for slug in sorted(rows):
        production = rows[slug].get("production")
        if production and tool_name in production.get("mcp_tools", []):
            return mcp_refusal_text(tool_name, slug, production["release_profile"])
    return None


def disk_spelling(path):
    """`path` with every existing component spelled as the file system spells it, so a case
    alias on a case-insensitive file system reads as the file it reaches. The glob match
    itself stays exact. Starts no child process."""
    parts = [part for part in path.split("/") if part]
    spelled = "/"
    for index, name in enumerate(parts):
        try:
            found = os.lstat(os.path.join(spelled, name))
        except OSError:
            return os.path.join(spelled, *parts[index:])
        kept = name
        try:
            other = name.swapcase()
            if other != name:
                alias = os.lstat(os.path.join(spelled, other))
                identity = (found.st_dev, found.st_ino)
                if (alias.st_dev, alias.st_ino) == identity:
                    entries = os.listdir(spelled)
                    if name not in entries:
                        for entry in entries:
                            listed = os.lstat(os.path.join(spelled, entry))
                            if (listed.st_dev, listed.st_ino) == identity:
                                kept = entry
                                break
        except OSError:
            kept = name
        spelled = os.path.join(spelled, kept)
    return spelled


def key_file_spellings(path, cwd):
    """The spellings of `path` a key-file write is judged by, or None when `path` is relative
    and `cwd` is not a non-empty absolute string: the path as named, its directories resolved
    with the final component kept as named, and the file the write reaches."""
    if not path.startswith("/") and not (
            isinstance(cwd, str) and cwd.startswith("/")):
        return None
    lexical = os.path.normpath(os.path.join(cwd if isinstance(cwd, str) and cwd else "/", path))
    named = os.path.join(os.path.realpath(os.path.dirname(lexical)), os.path.basename(lexical))
    target = os.path.realpath(lexical)
    spellings = []
    for spelling in (named, target, lexical):
        spelling = disk_spelling(spelling)
        if spelling not in spellings:
            spellings.append(spelling)
    return spellings


def key_file_candidate(spellings, rows):
    """Whether some declared key file glob matches a component suffix of some spelling."""
    globs = [glob for row in rows.values() for glob in
             (row.get("production") or {}).get("key_files", [])]
    if not globs:
        return False
    for spelling in spellings:
        parts = [part for part in spelling.split("/") if part]
        for index in range(len(parts)):
            suffix = "/".join(parts[index:])
            if any(fnmatch.fnmatchcase(suffix, glob) for glob in globs):
                return True
    return False


def checkout_of(git_bin, directory, timeout):
    """The realpath of the checkout `directory` is in, or None when git confirms it is in
    none. Any other failure of the lookup (a timeout, a git that cannot start, or a nonzero
    exit that is not git's "not a git repository", as dubious ownership or a malformed
    config is) raises `RepositoryLookupFailed`: it is no answer, so it is never "outside"."""
    try:
        child = subprocess.run(
            [git_bin, "-C", directory, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=timeout, check=False,
            env={**os.environ, "LC_ALL": "C", "LANGUAGE": "C"},
        )
    except (subprocess.TimeoutExpired, OSError) as error:
        raise RepositoryLookupFailed(
            "timed out" if isinstance(error, subprocess.TimeoutExpired) else "could not start"
        ) from error
    top = child.stdout.strip()
    if child.returncode == 0 and top:
        return os.path.realpath(top)
    if child.returncode != 0 and "not a git repository" in child.stderr:
        return None
    raise RepositoryLookupFailed(f"failed (exit {child.returncode})")


def lookup_directories(spelling):
    """The directories git is asked about for `spelling`: the nearest existing directory
    (git follows a symlinked directory to its target), then each lexical ancestor holding a
    `.git`, so a checkout reached through a symlinked directory inside it is still found."""
    directory = os.path.dirname(spelling)
    while not os.path.isdir(directory):
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    found = [directory]
    ancestor = os.path.dirname(spelling)
    while True:
        if os.path.isdir(ancestor) and os.path.lexists(os.path.join(ancestor, ".git")):
            found.append(ancestor)
        parent = os.path.dirname(ancestor)
        if parent == ancestor:
            return found
        ancestor = parent


def checkout_anchor(spelling, top):
    """The deepest ancestor of `spelling` that is the directory `top`, whatever route names
    it (a symlinked or case-variant route into the checkout), or None."""
    try:
        wanted = os.stat(top)
    except OSError:
        return None
    ancestor = os.path.dirname(spelling)
    while True:
        try:
            found = os.stat(ancestor)
        except OSError:
            found = None
        if found is not None and (found.st_dev, found.st_ino) == (wanted.st_dev, wanted.st_ino):
            return ancestor
        parent = os.path.dirname(ancestor)
        if parent == ancestor:
            return None
        ancestor = parent


def key_file_problem(spellings, rows, git_bin, deadline, child_timeout):
    """The reason to refuse a write that reaches `spellings`, or None: the first spelling
    that, relative to its own checkout, matches a declared key file glob of that checkout's
    origin project. Each child starts only within the deadline."""
    checkouts = {}
    slugs = {}
    for spelling in spellings:
        for directory in lookup_directories(spelling):
            try:
                resolved = os.path.realpath(directory)
                if resolved not in checkouts:
                    checkouts[resolved] = checkout_of(
                        git_bin, directory, bounded_timeout(deadline, child_timeout))
                top = checkouts[resolved]
                if top is None:
                    continue
                anchor = checkout_anchor(spelling, top)
                if anchor is None:
                    continue
                if top not in slugs:
                    slugs[top] = detect_repository(
                        git_bin, top, bounded_timeout(deadline, child_timeout), strict=True)
            except RepositoryLookupFailed as error:
                return (f"the repository lookup {error} for a write to "
                        f"`{shown_value(spelling)}`, which may be a key file of a declared "
                        "project, so the guard cannot judge it")
            slug = slugs[top]
            production = (rows.get(slug) or {}).get("production")
            if not production:
                continue
            relative = spelling[len(anchor):].lstrip("/")
            for glob in production.get("key_files", []):
                if fnmatch.fnmatchcase(relative, glob):
                    return key_file_refusal_text(
                        relative, slug, glob, production["release_profile"])
    return None


def judge_tool_call(payload, args, started):
    """The verdict for a file-edit or MCP tool call (issue 1150): an exit status."""
    tool_name = payload["tool_name"]
    field = FILE_EDIT_TOOLS.get(tool_name)
    value = None
    if field is not None:
        tool_input = payload.get("tool_input")
        value = tool_input.get(field) if isinstance(tool_input, dict) else None
        if not isinstance(value, str) or not value:
            return block(f"invalid hook input: expected tool_input.{field} to be a non-empty "
                         "string")
    rows, _reason = load_compiled_policy(args.policy)
    if field is None:
        reason = mcp_tool_problem(tool_name, rows)
        return block(reason) if reason is not None else 0
    spellings = key_file_spellings(value, payload.get("cwd"))
    if spellings is None or not key_file_candidate(spellings, rows):
        return 0
    base, reason = load_base_policy(args.base_policy)
    if base is None:
        return block(f"invalid policy: {reason}")
    git_bin = args.git_bin or base.git_bin
    try:
        refusal = key_file_problem(
            spellings, rows, git_bin, started + INVOCATION_DEADLINE_SECONDS,
            args.child_timeout_seconds)
    except DeadlineExhausted:
        return block(DEADLINE_REFUSAL)
    return block(refusal) if refusal is not None else 0



class Context:
    """Injected dependencies plus one repository's facts, resolved once per
    directory or per named repository (issue 400 D8, issue 418 D4).

    `cwd` is that directory: the payload `cwd`, or a push's `git -C` directory
    (`target_directory`). With `repository` given this is a named-repository
    context (issue 418 D5): the repository is the slug a PR creation or merge
    names with `--repo`, no checkout is read for it (`cwd` is None, no `git`
    child runs), and the base branch is its row's `default_branch` once the row
    check confirms the row. Building a context is the one place the row check
    runs, so a command with no push, PR creation, merge or release creation never starts the row check; the
    compiled policy is also read once before it, for the production rules.
    """

    def __init__(self, args, base, cwd, deadline, repository=None):
        self.git_bin = args.git_bin
        self.gh_bin = args.gh_bin
        self.jq_bin = args.jq_bin
        self.look_bin = args.look_bin
        self.deadline = deadline
        self.child_timeout = args.child_timeout_seconds
        self.authorized_owners = base.authorized_owners
        self.named = repository is not None
        if self.named:
            self.repository = repository
            self.base_branch = None
            self.cwd = None
        else:
            self.repository = detect_repository(self.git_bin, cwd, self.timeout)
            self.base_branch = default_branch(self.git_bin, cwd, self.timeout)
            self.cwd = cwd
        rows, self.compiled_problem = load_compiled_policy(args.policy)
        self.derived_row = rows.get(self.repository)
        self.row_problem = self._row_problem(base, args)
        if self.named and self.derived_row is not None and self.row_problem is None:
            self.base_branch = self.derived_row["default_branch"]
        # A derived row with two distinct branches declares an integration
        # branch exactly as an `integration_bases` entry does, so every reader
        # of `integration_bases` sees both without knowing where a row came from.
        # A row with a problem declares nothing.
        self.integration_bases = dict(base.integration_bases)
        if self.derived_row is not None and self.row_problem is None and (
            self.derived_row["integration_branch"] != self.derived_row["default_branch"]
        ):
            self.integration_bases[self.repository] = self.derived_row["integration_branch"]
        # A confirmed row's declared checks are the plan-gated merge floor's input
        # (issue 552 D2); a row with a problem, a literal row and no row declare none.
        self.required_checks = (
            tuple(self.derived_row["required_checks"])
            if self.derived_row is not None and self.row_problem is None
            else ()
        )

    @property
    def timeout(self):
        """The bound for the next child (`bounded_timeout`)."""
        return bounded_timeout(self.deadline, self.child_timeout)

    def _row_problem(self, base, args):
        """Why the repository's derived row cannot be used, or None (also None with no row).

        Three checks, in this order, and the first to fail is the answer: the
        literal conflict, `origin/HEAD` against the row's default branch, and the
        row check. A named-repository context has no checkout, so it skips the
        second: the row check proves the row's default branch against `origin`'s
        listed default itself (issue 418 D5).
        """
        row = self.derived_row
        if row is None:
            return None
        if self.repository in base.integration_bases:
            return (
                f"repository {self.repository} has both a literal integration base "
                "and a derived policy row; repair: run claude-guard-policy"
            )
        if not self.named and self.base_branch != row["default_branch"]:
            live = self.base_branch if self.base_branch is not None else "no branch"
            return (
                f"repository {self.repository}: origin/HEAD names {live}, "
                f"its derived policy row names {row['default_branch']}"
            )
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise DeadlineExhausted()
        return row_check_problem(
            args.derive_bin, self.repository, row,
            min(args.derive_timeout_seconds, remaining),
            getattr(args, "row_check_dropped_env", ()),
        )


def _refusal_with_detail(item):
    """A refusal as its message shows it: the reason code, then its detail when it
    is a non-empty string, as `shown_value` shows it (one line, no control
    character) and cut to `ROW_CHECK_DETAIL_LIMIT` characters."""
    detail = item.get("detail")
    if not isinstance(detail, str) or not detail:
        return item["reason_code"]
    shown = shown_value(detail[:ROW_CHECK_DETAIL_LIMIT])[:ROW_CHECK_DETAIL_LIMIT]
    return f"{item['reason_code']}: {shown}"


def _report_mismatch(report, status, repository, row):
    """`(why, transient)`: why `report` (the row check's parsed stdout) does not
    confirm `row`, or None, and whether a plain rerun is the remedy.

    `transient` is true only for a refusal whose every reason code is one of
    `ROW_CHECK_TRANSIENT_REASONS`, and only then does `why` show each refusal's
    detail (`_refusal_with_detail`); any other refusal shows its reason codes
    alone. A shape failure, a `row.required_checks` that is not a list of strings
    included, is an unreadable report. The branches are compared first, then the
    required checks as lists, order included (issue 552 D5); `evidence` is never
    compared.
    """
    unreadable = f"unreadable report (exit {status})"
    if not isinstance(report, dict) or report.get("repository") != repository:
        return unreadable, False
    outcome = report.get("outcome")
    if not isinstance(outcome, str) or ROW_CHECK_EXIT_STATUSES.get(outcome) != status:
        return unreadable, False
    if outcome == "derived":
        derived = report.get("row")
        branches = ("default_branch", "integration_branch")
        if (
            not isinstance(derived, dict)
            or not all(isinstance(derived.get(key), str) for key in branches)
            or not isinstance(derived.get("required_checks"), list)
            or not all(isinstance(check, str) for check in derived["required_checks"])
        ):
            return unreadable, False
        if any(derived[key] != row[key] for key in branches):
            return (
                f"it derives {derived['default_branch']} and {derived['integration_branch']}, "
                f"the row names {row['default_branch']} and {row['integration_branch']}"
            ), False
        if derived["required_checks"] != row["required_checks"]:
            derives, names = (
                json.dumps(checks, separators=(",", ":"))
                for checks in (derived["required_checks"], row["required_checks"])
            )
            return f"it derives required checks {derives}, the row names {names}", False
        return None, False
    if outcome == "refused":
        refused = report.get("refused")
        if not isinstance(refused, list):
            return unreadable, False
        if not refused:
            return "refused (no registered project derives it)", False
        if not all(
            isinstance(item, dict) and isinstance(item.get("reason_code"), str)
            for item in refused
        ):
            return unreadable, False
        # Issue 844: a failed read of `origin` or the provider says what failed.
        transient = all(item["reason_code"] in ROW_CHECK_TRANSIENT_REASONS for item in refused)
        shown = (
            _refusal_with_detail(item) if transient else item["reason_code"]
            for item in refused
        )
        return "refused (" + ", ".join(shown) + ")", transient
    cause = report.get("cause")
    if not isinstance(cause, dict) or not isinstance(cause.get("reason_code"), str):
        return unreadable, False
    return f"unavailable ({cause['reason_code']})", False


def row_check_env(dropped=()):
    """os.environ without the shell startup variables and exported bash functions.

    A `BASH_ENV` or `ENV` file, or a `BASH_FUNC_<name>%%` function, could make a
    shell script in the row check print a report the check never derived. `dropped`
    names more variables to remove: the pre-push hook passes git's repository-local
    variables (D10), which would point the check's own `git` at the pushing repository.
    """
    return {
        name: value
        for name, value in os.environ.items()
        if name not in ROW_CHECK_ENV_DROPPED
        and name not in dropped
        and not name.startswith(ROW_CHECK_ENV_DROPPED_PREFIX)
    }


def row_check_problem(derive_bin, repository, row, timeout, dropped_env=()):
    """Why the row check does not confirm `row` for `repository`, or None when it does.

    The check is `derive_bin --repository <repository>`, run once with no stdin,
    the environment of `row_check_env`, its output captured and its own session,
    so one SIGKILL to its process group on the bound takes its descendants with
    it. The pipes are not read again after the kill; only the direct child is
    reaped.

    A timeout's refusal ends in the transient marker (issue 476 D6), and so does
    a refusal made only of `ROW_CHECK_TRANSIENT_REASONS`, which also carries each
    failed read's detail (issue 844); every other refusal ends in the
    claude-guard-policy repair.
    """
    why = None
    remedy = "repair: run claude-guard-policy"
    try:
        child = subprocess.Popen(
            [derive_bin, "--repository", repository],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=row_check_env(dropped_env),
            start_new_session=True,
        )
    except OSError as error:
        why = f"could not start ({error})"
    else:
        try:
            stdout, _stderr = child.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                # Gone, or (macOS) a group of zombies only, which signals as EPERM.
                pass
            child.wait()
            why = "timed out"
            # Issue 476 D6: a slow check clears on a plain rerun, and recompiling
            # the policy cannot speed it up.
            remedy = ROW_CHECK_TRANSIENT_REMEDY
        else:
            try:
                report = json.loads(stdout)
            except ValueError:
                report = None
            why, transient = _report_mismatch(report, child.returncode, repository, row)
            if transient:
                remedy = ROW_CHECK_TRANSIENT_REMEDY
    if why is None:
        return None
    return (
        f"repository {repository}: the row check did not confirm its derived "
        f"policy row: {why}; {remedy}"
    )


def ownership_problem(context):
    """Why the context's repository is outside standing authorization, or None.

    A derived row authorizes exactly its repository, whoever the owner is, and
    only while it has no problem: it must not sit beside a literal integration
    base, and origin/HEAD must name the branch the row recorded as the default.
    Without a row the owner must be a literal authorized owner, and a compiled
    policy that contributed no row says why.
    """
    repository = context.repository
    if repository is None:
        return "repository unknown is outside standing authorization"
    if context.derived_row is not None:
        return context.row_problem
    if repository.split("/", 1)[0] not in context.authorized_owners:
        message = f"repository {repository} is outside standing authorization"
        if context.compiled_problem is not None:
            message += (
                f"; the compiled policy contributed no row: {context.compiled_problem}"
                "; repair: run claude-guard-policy"
            )
        return message
    return None


def authorized_bases(repository, base_branch, integration_bases):
    """The branches a guarded PR may target in `repository`.

    Always the default branch, plus the repository's declared integration
    branch when it has one. Membership decides only what may be TARGETED;
    the merge's protection requirement is applied to whichever base the PR
    actually carries.
    """
    bases = {base_branch}
    integration_base = integration_bases.get(repository)
    if integration_base is not None:
        bases.add(integration_base)
    return bases


def branch_name_problem(git_bin, branch, timeout):
    """Why `branch` is not a plain, safe branch name, or None; the problem names
    the value, escaped (issue 402 D4, D18)."""
    shown = shown_value(branch)
    if not branch:
        return "branch name must not be empty"
    if branch.startswith("-"):
        return f"branch {shown} must not begin with a dash"
    if ":" in branch:
        return f"refspec {shown} is not accepted; name the branch alone"
    if "+" in branch:
        return f"force-push refspec {shown} is not accepted"
    forbidden = next((c for c in branch if c in UNSAFE_BRANCH_CHARS), None)
    if forbidden is not None:
        return f"branch {shown} contains the forbidden character `{shown_character(forbidden)}`"
    if any(component in REF_NAMESPACE_COMPONENTS for component in branch.split("/")):
        # `refs/heads/main` and `heads/main` both name the branch `main`, so a
        # plain string comparison against the default branch would miss them.
        return f"namespaced ref {shown} is not accepted; name the branch directly"
    try:
        child = subprocess.run(
            [git_bin, "check-ref-format", "--branch", branch],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return BRANCH_VALIDATION_TIMEOUT
    if child.returncode != 0:
        return f"invalid branch name {shown}"
    return None


def free_text_problem(value, allow_newlines):
    """Why `value` is not safe to hand to the shell verbatim, or None."""
    if not value:
        return "must not be empty"
    forbidden = set(UNSAFE_TEXT_CHARS)
    if not allow_newlines:
        forbidden.add("\n")
    found = next((character for character in value if character in forbidden), None)
    if found is not None:
        return f"contains the forbidden character `{shown_character(found)}`"
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        return "contains an unpaired surrogate"
    return None


def compile_word(word, fail):
    """One bracket-stripped template word as a `Literal` or a `Slot`."""
    if LITERAL_WORD.fullmatch(word):
        return Literal(word)
    quoted = QUOTED_SLOT_WORD.fullmatch(word)
    if quoted:
        if quoted.group(1):
            fail(f"quoted slot {word!r} must not carry a prefix")
        name, is_quoted, prefix = quoted.group(2), True, ""
    else:
        slot = SLOT_WORD.fullmatch(word)
        if not slot:
            fail(f"word {word!r} is neither a literal nor a slot")
        prefix, name, is_quoted = slot.group(1), slot.group(2), False
    if name not in FORM_SLOTS:
        fail(f"slot <{name}> is not one of {', '.join(FORM_SLOTS)}")
    return Slot(name, is_quoted, prefix)


def compile_template(operation, template):
    """A template's elements: `Literal`, `Slot` and `Group` in order."""
    def fail(why):
        raise FormTableError(f"form table {operation}: {template!r}: {why}")

    elements = []
    group = None
    for word in template.split(" "):
        opens = word.startswith("[")
        closes = word.endswith("]")
        inner = word[1 if opens else 0:len(word) - 1 if closes else len(word)]
        if not inner:
            fail("empty word")
        if "[" in inner or "]" in inner:
            fail(f"misplaced bracket in {word!r}")
        if opens and group is not None:
            fail("a group does not nest")
        if closes and not opens and group is None:
            fail(f"{word!r} closes no group")
        element = compile_word(inner, fail)
        if opens:
            if not (isinstance(element, Literal) and element.word.startswith("-")):
                fail(f"a group must begin with a flag literal, not {inner!r}")
            group = []
        (elements if group is None else group).append(element)
        if closes:
            elements.append(Group(tuple(group)))
            group = None
    if group is not None:
        fail("a group is never closed")
    return tuple(elements)


def flag_words(elements):
    """The literal flag words in `elements`, groups included, and the flags each
    followed immediately by a quoted slot."""
    flags, quoted_value_flags = set(), set()
    for index, element in enumerate(elements):
        if isinstance(element, Group):
            inner_flags, inner_quoted = flag_words(element.elements)
            flags |= inner_flags
            quoted_value_flags |= inner_quoted
        elif isinstance(element, Literal) and element.word.startswith("-"):
            flags.add(element.word)
            following = elements[index + 1:index + 2]
            if following and isinstance(following[0], Slot) and following[0].quoted:
                quoted_value_flags.add(element.word)
    return flags, quoted_value_flags


def compile_form_table(table):
    """`table` as one `CompiledOperation` per operation, or `FormTableError`.

    Run first on every invocation, so a template that does not compile refuses
    every call instead of leaving a verb unjudged (issue 402 D14).
    """
    if not isinstance(table, dict) or set(table) != FORM_TABLE_OPERATIONS:
        raise FormTableError(
            "form table: the operations must be exactly "
            + ", ".join(sorted(FORM_TABLE_OPERATIONS))
        )
    compiled = {}
    for operation, entry in table.items():
        if not isinstance(entry, dict) or set(entry) != {"forms", *FORM_TABLE_PROPERTIES}:
            raise FormTableError(
                f"form table {operation}: the keys must be exactly forms, "
                + ", ".join(FORM_TABLE_PROPERTIES)
            )
        for name in FORM_TABLE_PROPERTIES:
            if not isinstance(entry[name], bool):
                raise FormTableError(f"form table {operation}: {name} must be a bool")
        forms = entry["forms"]
        if not isinstance(forms, tuple) or not forms:
            raise FormTableError(f"form table {operation}: forms must be a non-empty tuple")
        compiled_forms = []
        for form in forms:
            if (
                not isinstance(form, tuple)
                or len(form) != 3
                or not isinstance(form[0], str)
                or not isinstance(form[1], str)
                or not (form[2] is None or isinstance(form[2], str))
            ):
                raise FormTableError(
                    f"form table {operation}: a form must be (id, template, note), got {form!r}"
                )
            form_id, template, note = form
            if any(form_id == earlier.id for earlier in compiled_forms):
                raise FormTableError(f"form table {operation}: {template!r}: duplicate id {form_id}")
            elements = compile_template(operation, template)
            if not isinstance(elements[0], Literal):
                raise FormTableError(
                    f"form table {operation}: {template!r}: a form must begin with a literal"
                )
            if note is not None and any(
                placeholder not in NOTE_PLACEHOLDERS
                for placeholder in re.findall(r"<[^>]*>", note)
            ):
                raise FormTableError(
                    f"form table {operation}: {template!r}: the note names a placeholder "
                    "other than <integration> and <default>"
                )
            compiled_forms.append(CompiledForm(form_id, template, note, elements))
        programs = {form.elements[0].word for form in compiled_forms}
        if len(programs) != 1:
            raise FormTableError(
                f"form table {operation}: the forms begin with different literals: "
                + ", ".join(sorted(programs))
            )
        flags, quoted_value_flags = set(), set()
        for form in compiled_forms:
            form_flags, form_quoted = flag_words(form.elements)
            flags |= form_flags
            quoted_value_flags |= form_quoted
        compiled[operation] = CompiledOperation(
            operation, tuple(compiled_forms), entry["whole_text_characters"],
            entry["exact_spelling"], entry["scrub_prefix"], programs.pop(),
            frozenset(flags), frozenset(quoted_value_flags),
        )
    return compiled


def walk_form(elements, words, flags):
    """How far `words` follow a compiled form's `elements` from the first word.

    An optional group is entered only when the next word equals its flag; once
    entered, every element in it must match. A literal matches its own word; an
    unquoted slot takes one word not in `flags`; a glued slot takes a word that
    starts with its literal, its value the rest; a quoted slot takes any one
    word. `expected` is the element that could not be matched at `position`,
    None when every element matched; `quoted` holds the indices of the words
    quoted slots took.
    """
    position = 0
    values = {}
    quoted = set()

    def take(element):
        nonlocal position
        if position >= len(words):
            return False
        word = words[position]
        if isinstance(element, Literal):
            if word != element.word:
                return False
        elif element.quoted:
            values[element.name] = word
            quoted.add(position)
        elif element.prefix:
            if not word.startswith(element.prefix):
                return False
            values[element.name] = word[len(element.prefix):]
        elif word in flags:
            return False
        else:
            values[element.name] = word
        position += 1
        return True

    for element in elements:
        if isinstance(element, Group):
            if position < len(words) and words[position] == element.elements[0].word:
                for inner in element.elements:
                    if not take(inner):
                        return FormWalk(position, inner, values, frozenset(quoted))
            continue
        if not take(element):
            return FormWalk(position, element, values, frozenset(quoted))
    return FormWalk(position, None, values, frozenset(quoted))


def match_form(compiled, text):
    """The first of `compiled`'s forms that `text` spells, with its slot values, else None
    (issue 402 D2): the whole-text character rule, the `shlex` words, the forms in
    table order, and for an exact-spelling operation the rendered form against `text`.
    Every operation refuses a shell-active character outside quotes (issue 386): `shlex`
    keeps `x<notes.md` or `{x,--base,y}` as one word, while the shell redirects or
    expands it."""
    if forbidden_character(text, anywhere=compiled.whole_text_characters) is not None:
        return None
    try:
        words = shlex.split(text)
    except ValueError:
        return None
    for form in compiled.forms:
        walk = walk_form(form.elements, words, compiled.flags)
        if walk.expected is not None or walk.position != len(words):
            continue
        if compiled.exact_spelling:
            rendered = " ".join(
                f'"{word}"' if index in walk.quoted else word
                for index, word in enumerate(words)
            )
            if rendered != text:
                return None
        return FormMatch(form, walk.values)
    return None


# Characters that join or redirect a command: their refusal adds the run-alone advice (D5).
ADVISED_CHARACTERS = frozenset(";&|<>\n")


def shown_character(character):
    """`character` as a message shows it: itself, or its escape when it does not print."""
    return character if character.isprintable() else repr(character)[1:-1]


def shown_value(value):
    """`value` as a message shows it: each character through `shown_character`,
    so a value holding a newline keeps the refusal on one line (D18)."""
    return "".join(shown_character(character) for character in value)


def forbidden_character(text, anywhere):
    """The first character of `text` in UNSAFE_BRANCH_CHARS, anywhere or only
    outside single and double quotes (a backslash escapes inside double quotes),
    else None."""
    quote = None
    index = 0
    while index < len(text):
        character = text[index]
        if quote == "'":
            if character == "'":
                quote = None
        elif quote == '"':
            if character == "\\":
                index += 1
            elif character == '"':
                quote = None
        elif not anywhere and character in "'\"":
            quote = character
        elif character in UNSAFE_BRANCH_CHARS:
            return character
        index += 1
    return None


def doubled_space_before(text, program):
    """Whether the raw text before the first whitespace-delimited `program` word
    holds two whitespace characters in a row."""
    match = re.search(rf"(?<!\S){re.escape(program)}(?!\S)", text)
    head = text[:match.start()] if match else text
    return re.search(r"\s\s", head) is not None


def element_spelling(element):
    """How a refusal names a form element: its word, or the slot as the form spells it."""
    if isinstance(element, Literal):
        return element.word
    if element.quoted:
        return f'"<{element.name}>"'
    return f"{element.prefix}<{element.name}>"


def structure_problem(compiled, words):
    """Step 7 (issue 402 D4, D16): read at the furthest point any form reached, ties
    to table order; None when every word matched a form."""
    best = None
    for form in compiled.forms:
        walk = walk_form(form.elements, words, compiled.flags)
        if walk.expected is None and walk.position == len(words):
            return None
        if best is None or walk.position > best.position:
            best = walk
    found = words[best.position] if best.position < len(words) else None
    if best.expected is None:
        if found in compiled.flags:
            return f"{shown_value(found)} is out of place"
        return f"unexpected {shown_value(found)} at the end"
    expected = element_spelling(best.expected)
    if found is None:
        return f"missing {expected}"
    if (isinstance(best.expected, Literal) and not best.expected.word.startswith("-")
            and not found.startswith("-")):
        return f"expected {expected}, found {shown_value(found)}"
    if isinstance(best.expected, Slot) or best.expected.word not in words[best.position:]:
        return f"missing {expected}"
    return f"{shown_value(found)} is out of place"


def form_problem(operation, compiled, text):
    """The first problem (issue 402 D4) of `text`, which `match_form` refused."""
    label = OPERATION_LABELS[operation]
    try:
        words, quoting = shlex.split(text), None
    except ValueError as error:
        words, quoting = None, f"invalid command quoting: {error}"
    start = None
    if words is not None and compiled.program in words:
        start = words.index(compiled.program)
    before = words[:start] if start else []
    if before and (before[0] in ("unset", "env") or before[0].startswith("-")):
        if not compiled.scrub_prefix:
            return f"{label} takes no credential-scrub prefix"
        problem = f"unaccepted credential-scrub prefix `{shown_value(' '.join(before))}`"
        if doubled_space_before(text, compiled.program):
            problem += " (doubled space)"
        return problem
    character = forbidden_character(text, anywhere=compiled.whole_text_characters)
    if character is not None:
        problem = f"forbidden character `{shown_character(character)}`"
        if character in ADVISED_CHARACTERS:
            problem += (f": run the {label} as its own Bash call and read its output "
                        "with a follow-up call")
        return problem
    if quoting is not None:
        return quoting
    if before:
        return f"unaccepted wrapper `{shown_value(' '.join(before))}`"
    if start is None:
        return "does not match an accepted form"
    rest = words[start:]
    if compiled.program == "git" and len(rest) > 1 and rest[1].startswith("-"):
        if rest[1] == "-C":
            return "git -C takes one unquoted directory word followed by a single space"
        return f"git global option {shown_value(rest[1])} is not accepted"
    for index, word in enumerate(rest):
        if index and rest[index - 1] in compiled.quoted_value_flags:
            continue
        if word.startswith("-") and word not in compiled.flags:
            return f"unknown flag {shown_value(word)}"
    problem = structure_problem(compiled, rest)
    if problem is not None:
        return problem
    if compiled.exact_spelling:
        return (f"spell the {label} exactly as the accepted form: single spaces, "
                "free text in double quotes")
    return "does not match an accepted form"


def prefix_clause():
    """`optional prefix: …`: the one-name scrub spellings of the first credential
    name, in SCRUB_PREFIXES order (issue 402 D8)."""
    name = GH_ENV_TOKEN_NAMES[0]
    spellings = [
        spelling.rstrip() for spelling in SCRUB_PREFIXES
        if spelling.split() in (["unset", name, "&&"], ["env", "-u", name])
    ]
    return "optional prefix: " + " | ".join(spellings)


def declared_integration(context):
    """The context's integration branch when it declares one distinct from its
    resolved default branch, else None (also with no context)."""
    if context is None or context.base_branch is None:
        return None
    integration = context.integration_bases.get(context.repository)
    if integration is None or integration == context.base_branch:
        return None
    return integration


def accepted_forms(compiled, context, form_ids=None):
    """The accepted forms a text refusal prints, in table order (issue 402 D6, D7).

    `form_ids` names the forms the refusal's facts admit; None means before any
    PR lookup: every form, a noted form only where `declared_integration` names
    a branch. `context` fills `<slug>`, `<base>` (one form per authorized base)
    and the note; None fills nothing.
    """
    integration = declared_integration(context)
    printed = []
    for form in compiled.forms:
        if form_ids is None:
            if form.note is not None and integration is None:
                continue
        elif form.id not in form_ids:
            continue
        text = form.template
        if context is not None and context.repository is not None:
            text = text.replace("<slug>", context.repository)
        texts = [text]
        if "<base>" in text and context is not None and context.base_branch is not None:
            texts = [
                text.replace("<base>", base)
                for base in sorted(authorized_bases(
                    context.repository, context.base_branch, context.integration_bases))
            ]
        note = ""
        if form.note is not None:
            note = " (" + form.note.replace("<integration>", integration).replace(
                "<default>", context.base_branch) + ")"
        printed.extend(text + note for text in texts)
    return printed


def refuse(operation, problem, forms=()):
    """Print `operation`'s refusal and return 2 (issue 402 D3).

    With `forms` (a text refusal) the message continues `; accepted: ` and the
    forms joined by `; or `, then the prefix clause for an operation that takes
    a scrub prefix; without them (a refusal of the repository or forge state)
    it names only the problem.
    """
    message = f"unsafe {OPERATION_LABELS[operation]}: {problem}"
    if forms:
        message += "; accepted: " + "; or ".join(forms)
        if FORM_TABLE[operation]["scrub_prefix"]:
            message += "; " + prefix_clause()
    return block(message)


def validate_branch_delete(text, git_bin, timeout, compiled):
    """Branch deletion is guarded in every repository, ownership aside."""
    match = match_form(compiled, text)
    if match is None:
        return refuse("branch", form_problem("branch", compiled, text),
                      accepted_forms(compiled, None))
    branch = match.values["branch"]
    if branch.startswith("-"):
        return refuse("branch", f"branch {shown_value(branch)} must not begin with a dash",
                      accepted_forms(compiled, None))
    try:
        ref_check = subprocess.run(
            [git_bin, "check-ref-format", "--branch", branch],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return refuse("branch", BRANCH_VALIDATION_TIMEOUT)
    if ref_check.returncode != 0:
        return refuse("branch", f"invalid branch name {shown_value(branch)}",
                      accepted_forms(compiled, None))
    return 0


def tag_problem(tag):
    """Why `tag` is not a vMAJOR.MINOR.PATCH release tag, or None."""
    if SEMVER_TAG.fullmatch(tag) is None:
        return f"tag {shown_value(tag)} is not a vMAJOR.MINOR.PATCH tag"
    return None


def branch_target_problem(context, branch, deleting):
    """Why `branch` may not be the target of a push (or of a remote deletion), or None.

    The default branch must resolve; a deletion never names the default branch or
    the repository's declared integration branch (issue 458 D2); anything else
    never pushes the default branch.
    """
    if context.base_branch is None:
        return "cannot resolve the repository default branch"
    if deleting:
        if branch in (context.base_branch, context.integration_bases.get(context.repository)):
            return f"refusing to delete the permanent branch {branch}"
        return None
    if branch == context.base_branch:
        return f"refusing to push the default branch {branch}"
    return None


def annotated_tag_problem(context, tag, object_name):
    """Why `object_name` is not an existing annotated tag object, or None.

    `git cat-file -t <object_name>` in the context's directory must print `tag`,
    so a lightweight tag, a missing one or a branch of the same name never passes.
    """
    try:
        kind = subprocess.run(
            [context.git_bin, "cat-file", "-t", object_name],
            capture_output=True,
            text=True,
            timeout=context.timeout,
            check=False,
            cwd=context.cwd,
        )
    except subprocess.TimeoutExpired:
        return "tag lookup timed out"
    if kind.returncode != 0 or kind.stdout.strip() != "tag":
        return f"{tag} is not an existing annotated tag"
    return None


def push_arm_problem(context, form_id, value, tag_object):
    """Why one arm of the push forms refuses, as (problem or None, offer_forms).

    `form_id` is a `FORM_TABLE["push"]` form id and `value` its tag or branch.
    `offer_forms` is true when the problem lies in the command's text, so the
    text mode appends the accepted forms; a state problem offers none. Both modes
    judge through this one function (issue 672 D2).
    """
    if form_id == "tag":
        problem = tag_problem(value)
        if problem is not None:
            return problem, True
        return annotated_tag_problem(context, value, tag_object), False
    if form_id in ("branch", "delete"):
        problem = branch_name_problem(context.git_bin, value, context.timeout)
        if problem == BRANCH_VALIDATION_TIMEOUT:
            return problem, False
        if problem is not None:
            return problem, True
        return branch_target_problem(context, value, form_id == "delete"), False
    raise AssertionError(f"unhandled push form {form_id}")


def validate_push(text, context, compiled):
    problem = ownership_problem(context)
    if problem is not None:
        return refuse("push", problem)
    match = match_form(compiled, text)
    if match is None:
        return refuse("push", form_problem("push", compiled, text),
                      accepted_forms(compiled, context))
    problem = push_url_problem(context)
    if problem is not None:
        return refuse("push", problem)
    form_id = match.form.id
    if form_id == "tag":
        value = match.values["vX.Y.Z"]
        tag_object = TAG_REF_PREFIX + value
    else:
        value = match.values.get("branch")
        tag_object = None
    problem, offer = push_arm_problem(context, form_id, value, tag_object)
    if problem is not None:
        return refuse("push", problem, accepted_forms(compiled, context) if offer else ())
    return 0


PRE_PUSH_LABEL = "lifecycle guard pre-push"
PRE_PUSH_FORMS = ("tag", "branch", "delete")
PRE_PUSH_UNREADABLE = "cannot read the refs git handed the pre-push hook"
PRE_PUSH_SHA = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})")


def pre_push_refuse(problem):
    """Print one refused push on stderr and return 1, which aborts the push (D6)."""
    print(f"{PRE_PUSH_LABEL}: unsafe push: {problem}", file=sys.stderr)
    return 1


def pre_push_form(remote_ref, local_sha, remote_sha, cwd, context):
    """One ref update, read as a `FORM_TABLE["push"]` form: (form_id, value, problem).

    The facts git hands the hook decide the form (issue 672 D2): a branch deleted is
    `delete`, a branch created or fast-forwarded is `branch`, a tag created is `tag`,
    and everything else (a force, a moved or deleted tag, another namespace) matches
    no form and carries its problem. An all-zero sha means the ref is absent.
    """
    deleting = set(local_sha) == {"0"}
    creating = set(remote_sha) == {"0"}
    if remote_ref.startswith("refs/heads/"):
        branch = remote_ref[len("refs/heads/"):]
        if deleting:
            return "delete", branch, None
        if creating:
            return "branch", branch, None
        try:
            child = subprocess.run(
                [context.git_bin, "-C", cwd, "merge-base", "--is-ancestor",
                 remote_sha, local_sha],
                capture_output=True, text=True, timeout=context.timeout, check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            child = None
        if child is None or child.returncode != 0:
            return None, branch, f"update of {branch} is not a fast-forward"
        return "branch", branch, None
    if remote_ref.startswith(TAG_REF_PREFIX):
        tag = remote_ref[len(TAG_REF_PREFIX):]
        if deleting:
            return None, tag, f"refusing to delete the tag {tag}"
        if not creating:
            return None, tag, f"refusing to move the existing tag {tag}"
        return "tag", tag, None
    return None, remote_ref, (
        f"remote ref {shown_value(remote_ref)} is neither a branch nor a release tag")


def judge_pre_push(args, base, url, lines, cwd):
    """Judge one push in `cwd`: 0 when admitted, else the first refusal's status (1).

    The order is the text mode's: standing authorization, the push URL, then each
    ref line in the order git handed them. `lines` are (local_ref, local_sha,
    remote_ref, remote_sha) tuples.
    """
    deadline = time.monotonic() + INVOCATION_DEADLINE_SECONDS
    try:
        context = Context(args, base, cwd, deadline)
        problem = ownership_problem(context)
        if problem is None:
            problem = push_url_slug_problem(url, context.repository)
        if problem is not None:
            return pre_push_refuse(problem)
        for _local_ref, local_sha, remote_ref, remote_sha in lines:
            form_id, value, problem = pre_push_form(
                remote_ref, local_sha, remote_sha, cwd, context)
            if problem is None:
                problem, _offer = push_arm_problem(context, form_id, value, local_sha)
            if problem is not None:
                return pre_push_refuse(problem)
    except DeadlineExhausted:
        return pre_push_refuse(DEADLINE_REFUSAL)
    return 0


def parse_pre_push_lines(stdin_bytes):
    """The ref lines git wrote to the hook, or None when any cannot be read."""
    try:
        text = stdin_bytes.decode("ascii")
    except UnicodeDecodeError:
        return None
    if not text:
        return []
    if not text.endswith("\n"):
        return None
    lines = []
    for line in text[:-1].split("\n"):
        fields = line.split(" ")
        if len(fields) != 4:
            return None
        local_sha, remote_sha = fields[1], fields[3]
        if (PRE_PUSH_SHA.fullmatch(local_sha) is None
                or PRE_PUSH_SHA.fullmatch(remote_sha) is None
                or len(local_sha) != len(remote_sha)):
            return None
        lines.append(tuple(fields))
    return lines


PRE_PUSH_LFS_NAMES = ("pre-push", "post-checkout", "post-commit", "post-merge")


def hook_exit_status(returncode):
    """A chained hook's status as the hook's own: a signal death is 1."""
    return returncode if returncode >= 0 else 1


def run_chained(program, stdin_bytes, cwd, chain_env):
    """Run `program` with git's stdin; an executable text file with no `#!` line runs
    through `/bin/sh`, as git itself retries it (COR-002)."""
    try:
        return subprocess.run(program, input=stdin_bytes, cwd=cwd, env=dict(chain_env),
                              check=False)
    except OSError as error:
        if error.errno != errno.ENOEXEC:
            raise
    return subprocess.run(["/bin/sh", *program], input=stdin_bytes, cwd=cwd,
                          env=dict(chain_env), check=False)


def chain_pre_push(args, base, stdin_bytes, cwd, chain_env):
    """Run the repository's own pre-push hook, else git-lfs for an LFS repository (D5).

    The hook is `<git-common-dir>/hooks/pre-push` when it is an executable regular file
    that is not the hook git is running now, so a link to the managed hook cannot
    recurse. A repository hook takes precedence over git-lfs, as git-lfs never
    overwrites an existing hook. The chained program gets git's argv, the identical
    stdin bytes, the pre-scrub environment, and this process's stdout, stderr and cwd.
    The hooks are located under that same pre-scrub environment, so a push that names
    its repository with `GIT_DIR` or `--git-dir` chains that repository's hooks, as the
    shim does; only the row check reads the scrubbed environment.
    """
    unlocated = f"{PRE_PUSH_LABEL}: cannot locate the repository's own hooks"
    git_bin = args.git_bin or base.git_bin
    answers = []
    for query in ("--git-common-dir", "--git-path"):
        words = [git_bin, "rev-parse", "--path-format=absolute", query]
        if query == "--git-path":
            words.append("hooks")
        try:
            done = subprocess.run(words, cwd=cwd, env=dict(chain_env), capture_output=True,
                                  text=True, timeout=args.child_timeout_seconds, check=False)
        except (subprocess.TimeoutExpired, OSError):
            print(unlocated, file=sys.stderr)
            return 1
        answer = done.stdout.strip()
        if done.returncode != 0 or not answer:
            print(unlocated, file=sys.stderr)
            return 1
        answers.append(answer)
    common, running_hooks = answers
    candidate = os.path.join(common, "hooks", "pre-push")
    if (os.path.isfile(candidate) and os.access(candidate, os.X_OK)
            and os.path.realpath(candidate)
            != os.path.realpath(os.path.join(running_hooks, "pre-push"))):
        program = [candidate, *args.hook_args]
    elif args.git_lfs_bin:
        # An LFS repository has `<common>/lfs`, or keeps its objects elsewhere through
        # `lfs.storage` (COR-001); the shim applies the same rule.
        try:
            storage = subprocess.run(
                [git_bin, "config", "--get", "lfs.storage"], cwd=cwd, env=dict(chain_env),
                capture_output=True, text=True, timeout=args.child_timeout_seconds,
                check=False)
        except (subprocess.TimeoutExpired, OSError):
            print(unlocated, file=sys.stderr)
            return 1
        if os.path.isdir(os.path.join(common, "lfs")) or (
                storage.returncode == 0 and storage.stdout.strip()):
            program = [args.git_lfs_bin, "pre-push", *args.hook_args]
        else:
            return 0
    else:
        return 0
    try:
        done = run_chained(program, stdin_bytes, cwd, chain_env)
    except OSError as error:
        print(f"{PRE_PUSH_LABEL}: cannot run {program[0]}: {error.strerror or error}",
              file=sys.stderr)
        return 1
    return hook_exit_status(done.returncode)


def pre_push_main(args, stdin_bytes, environ, cwd):
    """The git pre-push hook entry (issue 672): judge an agent session's push, then chain.

    `args.hook_args` is git's `<remote> <url>`. The base policy loads first in
    every session (D7). Repository-local `GIT_*` variables git exports to hooks
    are removed from the row check's environment only (D10): the context's own `git`
    queries keep them, so the repository git was told to push from, by `GIT_DIR` or
    `--git-dir`, is the one judged wherever the hook's cwd is. The chained hook gets
    a copy of the original environment.
    """
    if len(args.hook_args) != 2:
        print(f"{PRE_PUSH_LABEL}: expected <remote> <url> from git", file=sys.stderr)
        return 1
    _remote, url = args.hook_args
    base, reason = load_base_policy(args.base_policy)
    if base is None:
        print(f"{PRE_PUSH_LABEL}: invalid policy: {reason}", file=sys.stderr)
        return 1
    if args.git_bin is None:
        args.git_bin = base.git_bin
    if args.gh_bin is None:
        args.gh_bin = base.gh_bin
    if args.jq_bin is None:
        args.jq_bin = base.jq_bin
    unreadable = f"{PRE_PUSH_LABEL}: cannot read git's repository-local variables"
    try:
        names = subprocess.run(
            [base.git_bin, "rev-parse", "--local-env-vars"],
            capture_output=True, text=True, timeout=args.child_timeout_seconds, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        print(unreadable, file=sys.stderr)
        return 1
    local_names = names.stdout.split()
    if names.returncode != 0 or not local_names:
        print(unreadable, file=sys.stderr)
        return 1
    chain_env = dict(environ)
    args.row_check_dropped_env = tuple(local_names)
    if environ.get("CLAUDECODE", ""):
        lines = parse_pre_push_lines(stdin_bytes)
        if lines is None:
            return pre_push_refuse(PRE_PUSH_UNREADABLE)
        status = judge_pre_push(args, base, url, lines, cwd)
        if status != 0:
            return status
    return chain_pre_push(args, base, stdin_bytes, cwd, chain_env)


def worktree_root(git_bin, cwd, timeout):
    """The real path of cwd's working-tree top, or None when it cannot be read."""
    if not isinstance(cwd, str) or not cwd:
        return None
    try:
        child = subprocess.run(
            [git_bin, "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    top = child.stdout.strip()
    if child.returncode != 0 or not top:
        return None
    return os.path.realpath(top)


BODY_FILE_DEVICE_ROOTS = ("/dev/", "/proc/")


def body_file_problem(path, context, standalone):
    """Why a PR `--body-file` path fails (issue 386), or None.

    A placement check, not a content boundary: the PR creation must be the whole
    command (no other segment can make or relink the file first), and the path
    must be absolute with no whitespace, shell-active character or `..`
    component, name no device or process file (`/dev/stdin` reads a pipe), and
    resolve outside the working tree (a tree that cannot be read fails closed).
    """
    if not standalone:
        return ("--body-file is accepted only when the PR creation is the whole "
                "command, so no other segment can prepare the file")
    if (
        not os.path.isabs(path)
        or any(c in UNSAFE_BRANCH_CHARS or c.isspace() for c in path)
        or ".." in path.split("/")
    ):
        return (f"--body-file {shown_value(path)} is not an absolute path without "
                "whitespace, shell-active characters or `..`")
    real = os.path.realpath(path)
    if any(candidate.casefold().startswith(BODY_FILE_DEVICE_ROOTS)
           for candidate in (path, real)):
        return f"--body-file {shown_value(path)} is a device or process file"
    root = worktree_root(context.git_bin, context.cwd, context.timeout)
    if root is None:
        return "cannot resolve the working tree to check --body-file against"
    # Case-folded: a case-insensitive volume must not let a respelled path escape.
    real = real.casefold()
    root = root.casefold()
    if real == root or real.startswith(root.rstrip("/") + "/"):
        return f"--body-file {shown_value(path)} is inside the working tree"
    return None


def validate_pr_create(text, context, compiled, standalone):
    problem = ownership_problem(context)
    if problem is not None:
        return refuse("pr-create", problem)
    match = match_form(compiled, text)
    if match is None:
        return refuse("pr-create", form_problem("pr-create", compiled, text),
                      accepted_forms(compiled, context))
    repository_argument = match.values["slug"]
    base = match.values["base"]
    head = match.values["branch"]
    title = match.values["title"]
    body = match.values.get("body")
    if repository_argument != context.repository:
        return refuse(
            "pr-create",
            f"--repo {shown_value(repository_argument)} is not the current repository "
            f"{context.repository}",
            accepted_forms(compiled, context),
        )
    reason = branch_name_problem(context.git_bin, head, context.timeout)
    if reason == BRANCH_VALIDATION_TIMEOUT:
        return refuse("pr-create", f"head {reason}")
    if reason is not None:
        return refuse("pr-create", f"head {reason}", accepted_forms(compiled, context))
    texts = (("title", title, False), ("body", body, True))
    for name, value, allow_newlines in texts:
        if value is None:
            continue
        text_problem = free_text_problem(value, allow_newlines)
        if text_problem is not None:
            return refuse("pr-create", f"{name} {text_problem}",
                          accepted_forms(compiled, context))
    if context.base_branch is None:
        return refuse("pr-create", "cannot resolve the repository default branch")
    allowed_bases = authorized_bases(
        context.repository, context.base_branch, context.integration_bases
    )
    if match.form.id == "pr-create-file":
        path_problem = body_file_problem(match.values["path"], context, standalone)
        if path_problem is not None:
            return refuse("pr-create", path_problem, accepted_forms(compiled, context))
    if base not in allowed_bases:
        return refuse(
            "pr-create",
            f"--base {shown_value(base)} is not one of " + ", ".join(sorted(allowed_bases)),
            accepted_forms(compiled, context),
        )
    if head == base:
        return refuse("pr-create", "head and base must differ")
    return 0


def release_slot_problem(values, repository):
    """Why a matched release creation's slots fail, in order, or None."""
    problem = tag_problem(values["vX.Y.Z"])
    if problem is not None:
        return problem
    if values["slug"] != repository:
        return (f"--repo {shown_value(values['slug'])} is not the current repository "
                f"{repository}")
    title_problem = free_text_problem(values["title"], False)
    if title_problem is not None:
        return f"title {title_problem}"
    path = values["path"]
    if (
        not os.path.isabs(path)
        or any(character in UNSAFE_BRANCH_CHARS or character.isspace() for character in path)
    ):
        return (f"--notes-file {shown_value(path)} is not an absolute path without "
                "whitespace or shell-active characters")
    return None


def validate_release(text, context, compiled):
    """Release creation is judged on the whole canonical command, like the merge."""
    problem = ownership_problem(context)
    if problem is not None:
        return refuse("release", problem)
    match = match_form(compiled, text)
    if match is None:
        return refuse("release", form_problem("release", compiled, text),
                      accepted_forms(compiled, context))
    problem = release_slot_problem(match.values, context.repository)
    if problem is not None:
        return refuse("release", problem, accepted_forms(compiled, context))
    return 0


def merge_slot_problem(values, repository):
    """Why a matched merge's `<n>`, `<slug>` and `<subject>` fail, in order, or None."""
    number = values["n"]
    if (
        not number
        or any(character < "0" or character > "9" for character in number)
        or int(number) <= 0
    ):
        return f"PR number {shown_value(number)} is not a positive decimal number"
    if values["slug"] != repository:
        return (f"--repo {shown_value(values['slug'])} is not the current repository "
                f"{repository}")
    subject = values.get("subject")
    subject_problem = None if subject is None else free_text_problem(subject, False)
    if subject_problem is not None:
        return f"subject {subject_problem}"
    return None


def validate_merge(text, context, compiled):
    problem = ownership_problem(context)
    if problem is not None:
        return refuse("merge", problem)
    repository = context.repository
    # `text` is the whole canonical command, its scrub prefix already
    # stripped, so the merge still tolerates no other chaining.
    match = match_form(compiled, text)
    if match is None:
        return refuse("merge", form_problem("merge", compiled, text),
                      accepted_forms(compiled, context))
    problem = merge_slot_problem(match.values, repository)
    if problem is not None:
        return refuse("merge", problem, accepted_forms(compiled, context))
    number = match.values["n"]
    head_commit = match.values.get("sha")
    if head_commit is not None and HEAD_COMMIT.fullmatch(head_commit) is None:
        return refuse(
            "merge",
            f"--match-head-commit {shown_value(head_commit)} is not 40 lowercase "
            "hexadecimal characters",
            accepted_forms(compiled, context),
        )
    if match.form.id == "feature":
        delete_branch = True
    elif match.form.id == "release":
        delete_branch = False
    else:
        raise AssertionError(f"unhandled merge form {match.form.id}")
    if context.base_branch is None:
        return refuse("merge", "cannot resolve the repository default branch")
    allowed_bases = authorized_bases(
        repository, context.base_branch, context.integration_bases
    )
    integration_base = context.integration_bases.get(repository)

    # The release arm — no `--delete-branch` — exists for one PR shape
    # only: the declared integration branch promoted into the default
    # branch, whose head must survive the merge. Where no such branch is
    # declared there is nothing to spare, so refuse before any lookup.
    if not delete_branch and integration_base is None:
        return refuse(
            "merge",
            "missing --delete-branch: it may be omitted only in a repository "
            "with a declared integration branch",
            accepted_forms(compiled, context, ["feature"]),
        )

    try:
        pr_lookup = subprocess.run(
            [
                context.gh_bin, "pr", "view", number, "--repo", repository,
                "--json",
                "state,baseRefName,headRefName,headRefOid,mergeStateStatus,url,statusCheckRollup",
            ],
            capture_output=True,
            text=True,
            timeout=context.timeout,
            check=False,
            env=gh_lookup_env(),
        )
    except subprocess.TimeoutExpired:
        return block("PR lookup timed out")
    if pr_lookup.returncode != 0:
        return block_child_failure("PR lookup failed", pr_lookup)

    try:
        base_predicate = " or ".join(
            f'.baseRefName == "{candidate}"' for candidate in sorted(allowed_bases)
        )
        pr_predicate_query = (
            f'.state == "OPEN" and ({base_predicate}) and '
            f'(.url | startswith("https://github.com/{repository}/pull/"))'
        )
        pr_predicate = subprocess.run(
            [
                context.jq_bin,
                "-e",
                pr_predicate_query,
            ],
            input=pr_lookup.stdout,
            capture_output=True,
            text=True,
            timeout=context.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return block("PR predicate timed out")
    if pr_predicate.returncode != 0:
        return block_child_failure("PR predicate failed", pr_predicate)

    # Protection is demanded of the branch this PR actually targets, not of
    # the default branch. The predicate above already confined it to
    # `allowed_bases`, so this reads back one of those names.
    try:
        pr_facts = json.loads(pr_lookup.stdout)
        base = pr_facts["baseRefName"]
    except (ValueError, KeyError, TypeError):
        return refuse("merge", "cannot read the PR base branch")
    if base not in allowed_bases:
        return refuse("merge", f"PR base {base} is not an authorized base")

    if not delete_branch:
        return validate_release_merge(
            pr_facts, base, integration_base, head_commit, context, compiled, number,
            match.values.get("subject"))

    # The feature arm deletes the PR's head branch, so the head must be
    # disposable: never the default branch, never the declared integration
    # branch (#116 D5). Judged before any protection lookup.
    head = pr_facts.get("headRefName")
    if not isinstance(head, str) or not head:
        return refuse("merge", "cannot read the PR head branch")
    if head in (context.base_branch, integration_base):
        permanent = f"--delete-branch would delete the permanent branch {head}"
        # The one permanent head an arm still admits is the integration branch
        # promoted into the default branch: the release form names it.
        if (
            head == integration_base
            and base == context.base_branch
            and declared_integration(context) is not None
        ):
            return refuse("merge", permanent, accepted_forms(compiled, context, ["release"]))
        return refuse("merge", permanent)

    problem = mergeability_problem(pr_facts, base, head_commit)
    if problem is not None:
        return refuse("merge", problem)
    status = look_problem(
        context, number, pr_facts, head_commit, match.values.get("subject"))
    if status is not None:
        return status

    # A declared integration branch is deliberately exempt from the
    # protection demand: it is the development-pace branch, and its CI
    # gate lives in the shipping flow's wait-for-checks (nodo's CI is
    # path-filtered, so no required check could report on every PR shape
    # anyway). The default branch keeps the protection demand — even if it is
    # ever also declared as the integration base — and only a plan-gated
    # protection answer, for a confirmed row that declares required checks, is
    # judged by the merge floor instead (issue 552 D2).
    if (
        integration_base is not None
        and base == integration_base
        and base != context.base_branch
    ):
        return 0

    try:
        protection_lookup = subprocess.run(
            [context.gh_bin, "api", f"repos/{repository}/branches/{base}/protection"],
            capture_output=True,
            text=True,
            timeout=context.timeout,
            check=False,
            env=gh_lookup_env(),
        )
    except subprocess.TimeoutExpired:
        return block("protection lookup timed out")
    if protection_lookup.returncode != 0:
        # Issue 552 D2: only the plan-gated answer, for a row that declares checks, is
        # judged by the floor; every other failed read keeps its refusal.
        if context.required_checks and plan_gated_answer(protection_lookup.stdout):
            problem = merge_floor_problem(pr_facts, base, head_commit, context.required_checks)
            return 0 if problem is None else refuse("merge", problem)
        return block_child_failure("protection lookup failed", protection_lookup)

    try:
        protection_predicate = subprocess.run(
            [
                context.jq_bin,
                "-e",
                "(.required_status_checks.contexts | length) > 0 "
                "and .enforce_admins.enabled == true",
            ],
            input=protection_lookup.stdout,
            capture_output=True,
            text=True,
            timeout=context.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return block("protection predicate timed out")
    if protection_predicate.returncode != 0:
        return block_child_failure("protection predicate failed", protection_predicate)
    return 0


def mergeability_problem(pr_facts, base, head_commit):
    """Why the PR's forge state refuses this merge, or None (issue 476 D1-D5).

    `pr_facts` is the PR lookup's object, `base` its read-back base branch and
    `head_commit` the command's `--match-head-commit` value, None without the
    flag. A merge state of exactly `BEHIND` is judged first; the head commit is
    read and compared only when the flag is present. Every other merge state
    passes: GitHub keeps its own up-to-date rule and its atomic head match.
    """
    state = pr_facts.get("mergeStateStatus")
    if not isinstance(state, str) or not state:
        return "cannot read the PR merge state"
    if state == "BEHIND":
        return (f"the PR is behind its base {base}; repair: sync the branch with {base}, "
                "push it and wait for its required checks before merging")
    if head_commit is None:
        return None
    head = pr_facts.get("headRefOid")
    if not isinstance(head, str) or HEAD_COMMIT.fullmatch(head) is None:
        return "cannot read the PR head commit"
    if head != head_commit:
        return (f"--match-head-commit {head_commit} is not the PR head commit {head}; "
                "merge only a head you reviewed")
    return None


def look_issue_numbers(head_ref, body, repository, linked=()):
    """The issues a pull request settles, ascending (issue 1138).

    The number in an `issue-<n>-` head branch, every number in `linked` (the
    repository's issues the forge links to the PR), and every closing keyword of
    GitHub (`close`, `closes`, `closed`, `fix`, `fixes`, `fixed`, `resolve`,
    `resolves`, `resolved`) or `Refs` (any case, an optional colon) in `body`
    followed by `#<n>`, `<repository>#<n>` or this repository's issue URL; a
    reference naming another repository is ignored.
    """
    found = set(linked)
    named = re.match(r"issue-([1-9][0-9]*)-", head_ref) if isinstance(head_ref, str) else None
    if named is not None:
        found.add(int(named.group(1)))
    for url_slug, slug, number in LOOK_REFERENCE.findall(body):
        slug = url_slug or slug
        if not slug or slug.lower() == repository.lower():
            found.add(int(number))
    return sorted(found)


def look_pr_texts(pr, repository):
    """`(text, linked)` from the PR lookup's object, or `(None, None)` when unreadable.

    `text` is the PR title, body and every commit message (headline and body) joined by
    newlines; `linked` the numbers of `repository`'s issues in
    `closingIssuesReferences`, other repositories' issues ignored. A missing or
    mistyped field, an entry that is not readable, or `LOOK_COMMIT_LIMIT` commits
    or more is unreadable.
    """
    if not isinstance(pr, dict) or "body" not in pr or not isinstance(pr.get("title"), str):
        return None, None
    body, commits, references = pr["body"], pr.get("commits"), pr.get("closingIssuesReferences")
    if not (body is None or isinstance(body, str)):
        return None, None
    if not isinstance(commits, list) or len(commits) >= LOOK_COMMIT_LIMIT:
        return None, None
    if not isinstance(references, list):
        return None, None
    texts = [pr["title"], body or ""]
    for commit in commits:
        if not isinstance(commit, dict):
            return None, None
        for key in ("messageHeadline", "messageBody"):
            text = commit.get(key)
            if not isinstance(text, str):
                return None, None
            texts.append(text)
    linked = []
    for reference in references:
        url = reference.get("url") if isinstance(reference, dict) else None
        found = LOOK_ISSUE_URL.fullmatch(url) if isinstance(url, str) else None
        if found is None:
            return None, None
        if found.group(1).lower() == repository.lower():
            linked.append(int(found.group(2)))
    return "\n".join(texts), linked


def look_json(context, argv, timed_out, failed, unreadable):
    """The parsed stdout of one gh lookup of the look gate, or the status to return.

    Returns `(value, None)` on success and `(None, status)` on a timeout, a
    non-zero exit or output that is not JSON; `unreadable` is the refusal text of
    the last.
    """
    try:
        child = subprocess.run(
            [context.gh_bin, *argv],
            capture_output=True,
            text=True,
            timeout=context.timeout,
            check=False,
            env=gh_lookup_env(),
        )
    except subprocess.TimeoutExpired:
        return None, block(timed_out)
    if child.returncode != 0:
        return None, block_child_failure(failed, child)
    try:
        return json.loads(child.stdout), None
    except ValueError:
        return None, refuse("merge", unreadable)


def look_issue_facts(context, number):
    """`({"number", "body", "comments"}, None)` for one issue, or `(None, status)`."""
    repository = context.repository
    issue, status = look_json(
        context, ["api", f"repos/{repository}/issues/{number}"],
        f"issue {number} lookup timed out", f"issue {number} lookup failed",
        f"cannot read issue {number}")
    if status is not None:
        return None, status
    if not isinstance(issue, dict) or "body" not in issue or not (
        issue["body"] is None or isinstance(issue["body"], str)
    ):
        return None, refuse("merge", f"cannot read issue {number}")
    pages, status = look_json(
        context,
        ["api", "--paginate", "--slurp", f"repos/{repository}/issues/{number}/comments?per_page=100"],
        f"issue {number} comment lookup timed out", f"issue {number} comment lookup failed",
        f"cannot read the comments of issue {number}")
    if status is not None:
        return None, status
    if not isinstance(pages, list) or not all(
        isinstance(page, list) and all(isinstance(entry, dict) for entry in page)
        for page in pages
    ):
        return None, refuse("merge", f"cannot read the comments of issue {number}")
    comments = [entry for page in pages for entry in page]
    return {"number": number, "body": issue.get("body"), "comments": comments}, None


def look_problem(context, number, pr_facts, head_commit, subject=None):
    """None when the look gate passes, else the status the merge returns (issue 1138).

    `number` is the pull request number string, `head_commit` the command's
    `--match-head-commit` value, None without the flag, and `subject` its `--subject`
    value, None without it; the subject, the PR title and the head branch name are
    read for closing keywords like the body, since GitHub closes an issue on the merge
    commit's headline and body (its default body is the PR title). The gate reads the PR body, then
    each issue the PR settles (`look_issue_numbers`) with its comments, and asks the
    look check (`--look-bin`) whether every issue whose body carries a look marker
    has the owner's approval of the PR's head or of an earlier head it keeps. A PR settling no issue passes with
    no further lookup; any failed, timed-out or unreadable lookup refuses. When
    the approval covers at least one marked issue the merge must carry
    `--match-head-commit` (the mergeability check has held it equal to the PR
    head), so GitHub's atomic head match decides the head that merges.
    """
    repository = context.repository
    pr_body, status = look_json(
        context, ["pr", "view", number, "--repo", repository, "--json",
         "title,body,commits,closingIssuesReferences"],
        "PR body lookup timed out", "PR body lookup failed", "cannot read the PR body")
    if status is not None:
        return status
    texts, linked = look_pr_texts(pr_body, repository)
    if texts is None:
        return refuse("merge", "cannot read the PR body")
    head_ref = pr_facts.get("headRefName")
    merge_commit = "\n".join(
        part for part in (head_ref, subject) if isinstance(part, str))
    numbers = look_issue_numbers(head_ref, f"{texts}\n{merge_commit}", repository, linked)
    if not numbers:
        return None
    issues = []
    for issue_number in numbers:
        facts, status = look_issue_facts(context, issue_number)
        if status is not None:
            return status
        issues.append(facts)
    head = pr_facts.get("headRefOid")
    if not isinstance(head, str) or HEAD_COMMIT.fullmatch(head) is None:
        head = None
    if context.look_bin is None:
        return block("look check failed: no --look-bin was given")
    payload = {"pr": int(number), "head": head, "issues": issues}
    child, verdict = look_child(context, payload)
    if child is None:
        return block("look check timed out")
    if isinstance(verdict, dict):
        admitted = look_admit(verdict, child, head, head_commit)
        if admitted is not False:
            return admitted
        issue = verdict.get("issue")
        if (
            child.returncode == 1
            and verdict.get("verdict") == "refuse"
            and isinstance(issue, int)
            and not isinstance(issue, bool)
        ):
            if head is None:
                return refuse("merge", "cannot read the PR head commit")
            problem = (
                f"issue {issue} needs the owner's look before merge, and head {head[:7]} "
                "has no recorded approval; ask the owner and record the answer")
            if look_candidates(verdict):
                return look_carry(context, payload, pr_facts, head, head_commit, problem)
            return refuse("merge", problem)
    return block_child_failure("look check failed", child)


def look_child(context, payload):
    """`(child, verdict)` of one run of the look check with `payload` on stdin.

    `child` is None when the run timed out; `verdict` is the parsed stdout, None
    when it is not JSON.
    """
    try:
        child = subprocess.run(
            [context.look_bin],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=context.timeout,
            check=False,
            env=row_check_env(),
        )
    except subprocess.TimeoutExpired:
        return None, None
    try:
        return child, json.loads(child.stdout)
    except ValueError:
        return child, None


def look_admit(verdict, child, head, head_commit):
    """None when the look check admits and the merge is pinned as it must be, the refusal
    status when it admits an unpinned merge of a marked issue, False when it does not admit."""
    marked = verdict.get("marked")
    if (
        child.returncode == 0
        and verdict.get("verdict") == "admit"
        and isinstance(marked, list)
        and all(isinstance(n, int) and not isinstance(n, bool) for n in marked)
    ):
        if marked and head_commit is None:
            return refuse(
                "merge",
                f"issue {marked[0]} awaits the owner's look, so the merge must carry "
                f"--match-head-commit {head}, the head the owner approved")
        return None
    return False


def look_candidates(verdict):
    """Whether a refusal lists at least one candidate and every entry is well formed."""
    candidates = verdict.get("candidates")
    return (
        isinstance(candidates, list)
        and bool(candidates)
        and all(
            isinstance(entry, dict)
            and isinstance(entry.get("issue"), int)
            and not isinstance(entry.get("issue"), bool)
            and isinstance(entry.get("head"), str)
            and HEAD_COMMIT.fullmatch(entry["head"]) is not None
            and entry.get("answer") in ("approved", "fix")
            for entry in candidates))


def look_read(context, path):
    """The parsed stdout of `gh api <path>`, or None on a timeout, a failed run or
    output that is not JSON (`DeadlineExhausted` propagates)."""
    try:
        child = subprocess.run(
            [context.gh_bin, "api", path],
            capture_output=True,
            text=True,
            timeout=context.timeout,
            check=False,
            env=gh_lookup_env(),
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if child.returncode != 0:
        return None
    try:
        return json.loads(child.stdout)
    except ValueError:
        return None


def look_base(context, base_ref):
    """The sha of the base branch's tip, or None when it cannot be read as one."""
    answer = look_read(context, f"repos/{context.repository}/branches/{base_ref}")
    commit = answer.get("commit") if isinstance(answer, dict) else None
    sha = commit.get("sha") if isinstance(commit, dict) else None
    if isinstance(sha, str) and HEAD_COMMIT.fullmatch(sha) is not None:
        return sha
    return None


def look_carry(context, payload, pr_facts, head, head_commit, problem):
    """The look gate's status once the look check has named a kept approval's candidates
    (issue 1211): None when a carry run admits, else the step 4 refusal `problem`, or the look
    check's own failure.

    The guard reads the base branch's tip once, then each path a run names (the set file
    at that sha or a compare of two full shas), at most `LOOK_READ_LIMIT` reads over at
    most `LOOK_CARRY_RUNS` runs; any other path, a failed read or a run left asking
    refuses with `problem`.
    """
    base_ref = pr_facts.get("baseRefName")
    if not isinstance(base_ref, str) or not base_ref:
        return refuse("merge", problem)
    base = look_base(context, base_ref)
    if base is None:
        return refuse("merge", problem)
    allowed = f"contents/{LOOK_FILES_PATH}?ref={base}"
    reads = {}
    for run in range(1, LOOK_CARRY_RUNS + 1):
        child, verdict = look_child(
            context, {**payload, "carry": {"base": base, "reads": reads}})
        if child is None:
            return block("look check timed out")
        if not isinstance(verdict, dict):
            return block_child_failure("look check failed", child)
        admitted = look_admit(verdict, child, head, head_commit)
        if admitted is not False:
            return admitted
        need = verdict.get("need")
        issue = verdict.get("issue")
        if not (
            child.returncode == 1
            and verdict.get("verdict") == "refuse"
            and isinstance(issue, int)
            and not isinstance(issue, bool)
        ):
            return block_child_failure("look check failed", child)
        if (
            not isinstance(need, list)
            or not need
            or run == LOOK_CARRY_RUNS
            or len(reads) + len(need) > LOOK_READ_LIMIT
            or not all(
                isinstance(path, str)
                and path not in reads
                and (path == allowed or LOOK_READ_PATH.fullmatch(path) is not None)
                for path in need)
        ):
            return refuse("merge", problem)
        for path in need:
            answer = look_read(context, f"repos/{context.repository}/{path}")
            if answer is None:
                return refuse("merge", problem)
            reads[path] = answer
    return refuse("merge", problem)


def plan_gated_answer(stdout):
    """Whether a failed protection read's stdout is GitHub's plan-gated answer (issue
    552 D2): a JSON object whose status is PLAN_GATED_STATUS and whose message is
    PLAN_GATED_MESSAGE."""
    try:
        answer = json.loads(stdout)
    except ValueError:
        return False
    return (
        isinstance(answer, dict)
        and answer.get("status") == PLAN_GATED_STATUS
        and answer.get("message") == PLAN_GATED_MESSAGE
    )


def rollup_entry_name(entry):
    """The check a rollup entry names: a CheckRun's name or a StatusContext's context
    when it is a string, else None, which makes the rollup unreadable."""
    if not isinstance(entry, dict):
        return None
    typename = entry.get("__typename")
    key = {"CheckRun": "name", "StatusContext": "context"}.get(typename)
    name = entry.get(key) if key is not None else None
    return name if isinstance(name, str) else None


def rollup_entry_green(entry):
    """Whether a rollup entry is green by the one rule the release arm's predicate is
    rendered from (issue 552 D6)."""
    if entry.get("__typename") == "CheckRun":
        return (
            entry.get("status") == GREEN_CHECK_RUN_STATUS
            and entry.get("conclusion") in GREEN_CHECK_RUN_CONCLUSIONS
        )
    return (
        entry.get("__typename") == "StatusContext"
        and entry.get("state") == GREEN_STATUS_CONTEXT_STATE
    )


def observed_state(entry):
    """A non-green entry as a refusal shows it: CheckRun <status>/<conclusion> or
    StatusContext <state>, each fact escaped when a string and none otherwise (issue
    552 D12)."""

    def fact(key):
        value = entry.get(key)
        return shown_value(value) if isinstance(value, str) else "none"

    if entry.get("__typename") == "CheckRun":
        return f"CheckRun {fact('status')}/{fact('conclusion')}"
    return f"StatusContext {fact('state')}"


def merge_floor_problem(pr_facts, base, head_commit, required_checks):
    """Why the plan-gated floor refuses this feature merge, or None (issue 552 D3,
    D11).

    It runs only after the protection read of `base` gave the plan-gated answer for
    a confirmed row declaring `required_checks`, and starts no child. It judges in
    order the `--match-head-commit` flag (`head_commit`, None without it, which
    `mergeability_problem` has already held to `headRefOid`), a readable rollup and
    each declared check in row order.
    """
    unprotectable = f"{shown_value(base)} cannot be protected on this repository's plan"
    if head_commit is None:
        return (f"{unprotectable}, so the merge must carry --match-head-commit "
                "with the reviewed PR head")
    rollup = pr_facts.get("statusCheckRollup")
    if not isinstance(rollup, list) or any(rollup_entry_name(entry) is None for entry in rollup):
        return "cannot read the PR check rollup"
    for check in required_checks:
        naming = [entry for entry in rollup if rollup_entry_name(entry) == check]
        if not naming:
            return (f"{unprotectable}, and the declared required check {shown_value(check)} "
                    "is missing from the PR's check rollup")
        for entry in naming:
            if not rollup_entry_green(entry):
                return (f"{unprotectable}, and the declared required check "
                        f"{shown_value(check)} is not green ({observed_state(entry)})")
    return None


def validate_release_merge(
        pr_facts, base, integration_base, head_commit, context, compiled, number, subject=None):
    """The release arm: the integration branch promoted into the default branch.

    Its head is permanent, so the merge may omit `--delete-branch`, and in
    return exactly that PR shape is required. Forge protection is not
    consulted: with path-filtered CI no required-status-check rule on the
    default branch can stand in for the release PR's actual checks, so the
    guard reads the PR's own rollup and demands every check completed and
    green — a pending, failed, cancelled, or empty rollup blocks.
    """
    head = pr_facts.get("headRefName")
    if not isinstance(head, str) or not head:
        return refuse("merge", "cannot read the PR head branch")
    if head != integration_base or base != context.base_branch:
        omitted = (
            f"may be omitted only when merging {integration_base} into "
            f"{context.base_branch}; this PR merges {shown_value(head)} into "
            f"{shown_value(base)}"
        )
        # A feature head still fits the feature arm, which names the missing flag;
        # a permanent head fits no arm.
        if head not in (context.base_branch, integration_base):
            return refuse("merge", f"missing --delete-branch: it {omitted}",
                          accepted_forms(compiled, context, ["feature"]))
        return refuse("merge", f"--delete-branch {omitted}")
    problem = mergeability_problem(pr_facts, base, head_commit)
    if problem is not None:
        return refuse("merge", problem)
    status = look_problem(context, number, pr_facts, head_commit, subject)
    if status is not None:
        return status
    try:
        rollup_predicate = subprocess.run(
            [
                context.jq_bin,
                "-e",
                RELEASE_ROLLUP_PREDICATE,
            ],
            input=json.dumps(pr_facts),
            capture_output=True,
            text=True,
            timeout=context.timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return block("check rollup predicate timed out")
    if rollup_predicate.returncode != 0:
        return block_child_failure(
            "unsafe merge: the PR's check rollup is not entirely green",
            rollup_predicate,
        )
    return 0


def repository_context(operation, text, target, contexts, args, base, deadline, compiled):
    """The context a verb is judged in (issue 418 D4).

    A PR creation or merge whose `--repo` slug differs from its target
    directory's repository, and which has a row in the compiled policy, is
    judged in a named-repository context built from that row, and the directory
    context is not built. Anything else (another verb, a text that matches no
    form, the directory's own slug, a slug with no row) is judged in the
    directory context, as before.
    """
    requested = None
    if operation in ("pr-create", "merge"):
        match = match_form(compiled, text)
        if match is not None:
            requested = match.values["slug"]
    if requested is not None:
        here = detect_repository(
            args.git_bin, target, bounded_timeout(deadline, args.child_timeout_seconds))
        if here != requested:
            key = ("repository", requested)
            named = contexts.get(key)
            if named is None:
                named = contexts[key] = Context(
                    args, base, None, deadline, repository=requested)
            if named.derived_row is not None:
                return named
    context = contexts.get(target)
    if context is None:
        context = contexts[target] = Context(args, base, target, deadline)
    return context


def main():
    table = compile_form_table(FORM_TABLE)
    started = time.monotonic()
    parser = argparse.ArgumentParser(prog="claude-bash-lifecycle-guard")
    parser.add_argument("--base-policy", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--derive-bin", required=True)
    parser.add_argument("--look-bin", default=None)
    parser.add_argument("--derive-timeout-seconds", type=float, default=15)
    parser.add_argument("--git-bin", default=None)
    parser.add_argument("--gh-bin", default=None)
    parser.add_argument("--jq-bin", default=None)
    parser.add_argument("--child-timeout-seconds", type=float, default=5)
    parser.add_argument("--mode", choices=("hook", "pre-push"), default="hook")
    parser.add_argument("--git-lfs-bin", default=None)
    parser.add_argument("hook_args", nargs="*")
    args = parser.parse_args()

    if args.mode == "pre-push":
        return pre_push_main(args, sys.stdin.buffer.read(), os.environ, os.getcwd())
    if args.hook_args:
        return block("invalid hook input: unexpected arguments")

    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeError) as error:
        return block(f"invalid hook input: malformed JSON: {error}")

    if not isinstance(payload, dict):
        return block("invalid hook input: expected a JSON object")
    tool_name = payload.get("tool_name")
    if tool_name in FILE_EDIT_TOOLS or (
            isinstance(tool_name, str) and tool_name.startswith(MCP_TOOL_PREFIX)):
        return judge_tool_call(payload, args, started)
    tool_input = payload.get("tool_input")
    if tool_name != "Bash" or not isinstance(tool_input, dict):
        return block("invalid hook input: expected a Bash tool call")
    command = tool_input.get("command")
    if not isinstance(command, str):
        return block("invalid hook input: expected tool_input.command to be a string")

    word = detaching_word(command)
    if word is not None:
        return block(f"detaching command `{word}` refused: {DETACHING_ROUTES}")

    base, reason = load_base_policy(args.base_policy)
    if base is None:
        return block(f"invalid policy: {reason}")
    if args.git_bin is None:
        args.git_bin = base.git_bin
    if args.gh_bin is None:
        args.gh_bin = base.gh_bin
    if args.jq_bin is None:
        args.jq_bin = base.jq_bin

    # Issue 1149 D4, D10: the compiled policy is read on every call that passes the
    # detaching check and the base policy, for the production rules.
    rows, _reason = load_compiled_policy(args.policy)
    try:
        refusal = production_problem_for(
            command, rows, payload.get("cwd"), args.git_bin,
            bounded_timeout(started + INVOCATION_DEADLINE_SECONDS,
                            args.child_timeout_seconds))
    except DeadlineExhausted:
        return block(DEADLINE_REFUSAL)
    if refusal is not None:
        return block(refusal)

    operations = guarded_operations(command)
    for operation, _segment, problem, _directory in operations:
        if operation == "label":
            return block(f"unsafe {OPERATION_LABELS[operation]}: {problem}")

    # Issue 418: a command holding a lifecycle verb is admitted only in the
    # allowlist grammar, so the only directory change left is its one leading cd.
    lifecycle = [
        operation for operation, *_ in operations
        if operation not in ("label", "transmit")
    ]
    shell_dir = shell_problem = None
    if lifecycle:
        shell_dir, problem = lifecycle_shape(command)
        if problem is not None:
            return refuse(lifecycle[0], f"{problem}; {LIFECYCLE_GRAMMAR}",
                          accepted_forms(table[lifecycle[0]], None))
        if shell_dir is not None:
            shell_problem = cd_directory_problem(command, shell_dir)
    # Issue 655 D6: a git invocation that could transmit refs and is no lifecycle
    # form is refused as a push, after the grammar check and before any
    # repository context is built.
    for operation, _segment, problem, _directory in operations:
        if operation == "transmit":
            return refuse("push", problem, accepted_forms(table["push"], None))
    # One context per distinct target directory, all under one deadline.
    contexts = {}
    for operation, segment, problem, directory in operations:
        if time.monotonic() >= started + INVOCATION_DEADLINE_SECONDS:
            return refuse(operation, DEADLINE_REFUSAL)
        if problem is not None:
            return refuse(operation, problem, accepted_forms(table[operation], None))
        in_shell_directory = operation in ("push", "pr-create")
        if in_shell_directory and shell_problem is not None:
            return refuse(operation, shell_problem,
                          accepted_forms(table[operation], None))
        try:
            # Push and PR creation are judged per segment; the other verbs on the
            # whole command, so they tolerate no chaining.
            judged = segment if operation in ("push", "pr-create") else command
            text = canonical_text(operation, judged, directory)
            if operation == "branch":
                # Branch deletion is judged in every repository: it needs no
                # forge state.
                status = validate_branch_delete(
                    text, args.git_bin, args.child_timeout_seconds, table[operation]
                )
            else:
                target = target_directory(
                    directory,
                    shell_dir if in_shell_directory and shell_dir is not None
                    else payload.get("cwd"))
                context = repository_context(
                    operation, text, target, contexts, args, base,
                    started + INVOCATION_DEADLINE_SECONDS, table[operation])
                if operation == "push":
                    status = validate_push(text, context, table[operation])
                elif operation == "pr-create":
                    # Issue 386: the body-file form is judged against the
                    # whole command too, which must be this one segment.
                    standalone = (canonical_text(operation, command, directory).rstrip()
                                  == text.rstrip())
                    status = validate_pr_create(text, context, table[operation],
                                                standalone)
                elif operation == "release":
                    status = validate_release(text, context, table[operation])
                else:
                    status = validate_merge(text, context, table[operation])
        except DeadlineExhausted:
            return refuse(operation, DEADLINE_REFUSAL)
        if status != 0:
            return status
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(
            f"lifecycle guard: unexpected failure: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        raise SystemExit(2)
