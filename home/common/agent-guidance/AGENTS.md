When devenv.nix doesn't exist and a command/tool is missing, create ad-hoc environment:

    $ devenv -O languages.rust.enable:bool true -O packages:pkgs "mypackage mypackage2" shell -- cli args

When the setup becomes complex create `devenv.nix` and run commands within:

    $ devenv shell -- cli args

See https://devenv.sh/ad-hoc-developer-environments/

Before starting a task, check the available-skills listing; if a skill
plausibly applies, invoke it via the Skill tool before acting, and read its
current version rather than working from memory.

Run `git push`, `git branch -d`, `gh pr create`, `gh pr merge` and
`gh release create` each alone in its own Bash call: no chain, pipe or
redirection beyond an `unset GITHUB_TOKEN && ` prefix, an explicit `--repo`
on each `gh` verb, and no `"`, `$`, backtick or backslash in a title,
subject or body.

Only the user applies the `instruction-budget-raise` label.
