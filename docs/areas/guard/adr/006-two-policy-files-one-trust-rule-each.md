# ADR-guard-006 — The guard reads a trusted store base policy and an untrusted compiled policy

- **Status:** accepted
- **Decided in:** issue 377 D1, D2, D4, D5

## Context

The guard needs two kinds of fact. Some it must trust absolutely: which owners are authorized and which programs it runs. Others come from the fleet registry and the contract each project publishes, and change as projects are registered. The compiled policy that carries the second kind is written at activation, which cannot write the Nix store, so it is a user-writable file that a session can rewrite.

## Decision

The guard reads two files with disjoint closed schemas, and a loader refuses a file with any other key set. The base policy is a store file that holds every trusted member: the authorized owners, the literal integration bases and the store paths of `git`, `gh` and `jq`. The compiled policy is a user state file that holds only derived rows and a record of their derivation. No member exists in both, so neither file is a valid instance of the other.

The guard takes no trusted member from the compiled policy and treats each derived row as a claim to be confirmed before it is relied on (ADR-guard-007). A compiled policy that is missing, unreadable, not a regular file, over 1 MiB, not JSON or outside its schema contributes no row and blocks nothing the base policy allows. A base policy that is bad blocks every Bash call, because it is a store file the build check loaded and a bad one is an installation defect. The compiler leaves out a project whose slug or branch it finds unsupported, so that project alone has no row. The loader is stricter: a stored row whose slug or branch it cannot accept empties the whole compiled policy, so one malformed row removes every derived authorization.

The guard is not a sandbox.

## Consequences

- The guard catches the mistakes of a cooperating session. Rewriting the compiled policy alone gains nothing: it cannot add an owner, an integration base or a program, and a forged row is refused at use. What stays user-writable:
  - The fleet registry. A session can add an entry, but the row check still demands that the repository's own branch on `origin` publishes a resolving contract that names that project id, that repository as tracker and as release target, and that the provider confirms the name. A registry edit therefore authorizes only a repository that already declares itself adopted and that the session could register with the registration command anyway.
  - Transport and tool configuration: `~/.ssh/config`, git configuration and the `gh` credential decide what `origin` and the provider answer. A session that rewrites them and the registry can forge a derivation, which takes several deliberate edits to stores unrelated to the guard.
  - The checkout's object store. A session that plants an object under the id `origin` lists forges that read, as it already could before a fetch that finds the object present (issue 385).
  - `~/.claude/settings.json`, a writable copy: removing the hook removes the guard.
  - The window between check and use: the verb runs after the verdict, and a remote that changes between them is not seen.
- A derived-only repository loses its authorization when the compiled policy is bad, and an owner-literal repository is judged as an unregistered one, with no row to check `origin/HEAD` against.
