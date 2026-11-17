# ADR-console-065 — A question session reads the project's history, tracker and live state and answers plainly

- **Status:** accepted; amended by ADR-console-066
- **Decided in:** #1225

## Context

The owner asked a registered project what was done in the last 7 days and what is in production, in plain business terms. The answer came back full of decision-record jargon. The session could not run `git log`, because ADR-console-058 admitted only Read, Grep, Glob and the bare declared read-only commands, so it answered from the decision records it could read. Its declared production read also ran outside the project's development environment, so a command that needs the environment failed there. ADR-console-058 D4, D6, D7 and D8 and ADR-console-059 fixed the session this ADR extends; ADR-console-062 carries a follow-up's thread, which this does not change.

## Decision

**D1. Git reads.** The hook admits `git log`, `git show`, `git diff`, `git status`, `git blame`, `git ls-files` and `git tag` only when the subcommand is word 1, so `-C`, `-c`, `--git-dir` and `--work-tree` never apply. A later word that starts `--ou` or `--ext` is refused, since `--output` writes a file, git's option parser accepts abbreviations and `--ext-diff` runs a configured program. `git tag` is a listing only. The owner's question is answerable: `git log --since=7.days.ago --oneline` is admitted, and the prompt names it.

**D2. gh reads are pinned to the project's own repository.** `gh pr`, `gh release`, `gh issue` and `gh run` `list` and `view` are admitted only for the GitHub repository of the contract: `bindings.tracker.repo_slug`, and only when `bindings.tracker.kind` is `github`. A project with no such tracker gets no gh read, and the prompt says so. The session then answers what was merged with `gh pr list --repo <slug> --state merged --limit 30` and what was released with `gh release list --repo <slug>`.

**D3. The `--repo` pin sits right after the verb.** gh parses its flags with pflag: a string flag takes the next word as its value even when that word starts with `-`, and `--` ends flag parsing. A `--repo` word placed later could be the value of an earlier option or a positional after `--`, and gh would then fall back to `GH_REPO` or its default repository, which the session's inherited environment may set. Word 3 follows the verb directly, so it can be neither: it is `--repo=<slug>`, or `--repo` or `-R` followed by the slug, compared exactly. After the pin no word may be `--`, start with `--repo`, open a browser (`--web`), be a short-option cluster holding `w` or `R`, or contain `/`.

**D4. The hook takes the repository and stays fail closed.** The hook has a second argument: the slug, or an empty string for none. A missing or malformed argument denies every call, and `"onFailure": "block"` is unchanged, so a hook that errors, fails to start or times out still blocks. The lifecycle verbs stay refused whatever the new rules say.

**D5. Bash is always offered and the allow rules are narrowed by the hook.** `--tools` is `Read,Grep,Glob,Bash` for every session, since the git reads need Bash even with no route. The allow list gains a `Bash(git <verb>:*)` rule per git read and, with a repository, a `Bash(gh <group> <verb>:*)` rule per gh read. A hook `allow` with no allow rule is not confirmed to admit a call under `dontAsk`, so each admitted read also has a rule; the prefix rules are broader than the hook, and the hook is the narrower judge. This amends ADR-console-058 D4 and D6.

**D6. A route runs inside the development environment.** When `<project.root>/devenv.nix` is a regular file, each declared read-only argv becomes `devenv shell -- <argv>` unless it already starts with `devenv`; the hook, the allow rules and the prompt all see the wrapped argv. The contract does not declare the environment, so this is an inference from the root. This amends ADR-console-058 D7.

**D7. The prompt names the reads.** After the routes paragraph it lists the git reads and, with a repository, the gh reads with their `--repo` pin and the three examples above, or says that gh cannot be used. This follows from D1 to D3.

**D8. The answer is direct and plain.** The lead gains answer rules before the heading shape: a direct answer in two or three sentences in the owner's plain business terms, then at most a short list of five lines; what is live first when the question asks about production; no decision-record jargon unless the owner asks; answers from the history, the pull requests and releases and the declared production read, not from the decision records alone; and a failed command named plainly in the answer. The five headings are unchanged. This amends ADR-console-058 D8.

**D9. The seam.** The service resolves one `Reach` of routes and repository per question, and the question's `Ask` carries the repository to the settings, the hook argument and the prompt.

## Considered Options

- A hook `allow` with no allow rule: simpler, but whether it admits a call under `dontAsk` is not confirmed, so a read could be refused after the hook admitted it.
- Admitting `gh` without a repository: the session could read any repository the account can reach, and the question is about this project.
- A contract member naming the development environment: the contract does not declare one today, so D6 infers it from `devenv.nix`.

## Consequences

- Git reads honour the repository's own git configuration, such as an external diff driver or an fsmonitor, which the owner controls.
- `--exit-code` and revisions such as `HEAD~3` are refused, which over-denies some harmless reads; the prompt tells the session to name revisions by sha, tag or `--since`.
- `devenv shell` may build the environment on first use, within the 300 s cap.
- A project with no GitHub tracker answers from git and its declared reads only.
- Related: ADR-console-058, ADR-console-059, ADR-console-062.
