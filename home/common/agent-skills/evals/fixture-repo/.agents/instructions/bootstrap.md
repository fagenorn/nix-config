# Project invariants — tinytask

- Project policy lives in `.agents/project.json`. Resolve once at phase entry
  with `resolve-project resolve` and retain the returned `ResolvedProject`.
- No policy is defaulted or inferred. Resolver refusal stops before mutation or
  external effects.
- Use only snapshot paths and command bindings; supported capabilities may be
  required and unsupported capabilities take their documented no-capability route.
