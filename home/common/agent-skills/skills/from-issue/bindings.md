# Project bindings (from-issue)

Loaded from `SKILL.md` at startup. Resolve once, carry the values.

This included document receives the phase owner's retained `ResolvedProject`; use only `bindings.tracker`, `bindings.vcs`, `bindings.paths.artifacts`, and `bindings.workflow`, and never resolve or infer policy.

Use `bindings.tracker.{kind,cli,repo_slug,credential_env.unset_before_invocation}`, `bindings.vcs`, `bindings.paths.artifacts`, `bindings.workflow`, and command IDs dereferenced through `bindings.commands`. A blocked required capability stops; authored unsupported takes only its documented no-capability route. `<tracker-cli>` is `bindings.tracker.cli`; branch values are from `bindings.vcs`. Unset only names listed by `bindings.tracker.credential_env.unset_before_invocation` before the invocation.
