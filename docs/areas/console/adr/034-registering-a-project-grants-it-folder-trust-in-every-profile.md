# ADR-console-034 — Registering a project grants it folder trust in every profile

- **Status:** accepted; amended by ADR-console-035
- **Decided in:** #1078

## Context

A background launch (`claude --bg`) and a wake of a parked session refuse a folder the client does not trust: the first reads `Workspace not trusted`, and the console reports the second as `workspace_untrusted`. Trust lives per profile, in the `projects` object of the profile's own `.claude.json`, keyed by the git root of the main checkout; the interactive prompt that sets it never runs in a background session. No flag, environment variable or settings key marks a folder trusted for `--bg`, so a project the owner registered could not start its first goal until the owner opened the folder interactively in every profile. The client documents the key and the refusal: https://code.claude.com/docs/en/permissions#project-allow-rules-and-workspace-trust and https://code.claude.com/docs/en/errors#workspace-not-trusted-when-dispatching-a-background-session. #1078 makes the owner's Register approval grant that trust, in words that say what it allows.

## Decision

**D1. Which approvals grant.** Only the owner's Register approval grants, and only once for a repository: the `Apply it` answer of the `Apply this adoption?` card (ADR-console-030), and, for an already-adopted repository, the `Register it` answer of the `Register <name>` card (ADR-console-028 D5, amended). The grant runs at the approval, before the apply or the register check, whatever they then do. `Apply it again`, `Try again`, `Retry`, both `Not now` answers, the registry watcher and the auto-registration of a merged adoption (ADR-console-028 D10) grant nothing. Both cards say what registering allows, verbatim: `Registering lets agents run in this folder with the folder's own settings and hooks.`

**D2. The key.** The write sets `projects[<key>].hasTrustDialogAccepted` to `true` and nothing else. `<key>` is the real path of the main checkout's git root: `git rev-parse --path-format=absolute --git-common-dir`, its parent when its last segment is `.git`, resolved with `os.path.realpath`, the same value the launcher's `project_key` computes. Every other member of the document (`oauthAccount` included) and every other member of an existing project entry is kept.

**D3. The write.** The targets are every account profile's `.claude.json` and `~/.claude.json`. The merge is written to a temporary file in the same directory, with the original file's mode (0600 for a new file), and replaces the file by an exchanging rename: `renameat2` with `RENAME_EXCHANGE` on Linux, `renamex_np` with `RENAME_SWAP` on Darwin. The document the exchange displaced is always in hand and is compared with the one the merge was based on; a changed one is merged again and swapped again, so a client write in the window between the last read and the replacement is never overwritten unseen. After a bounded number of displacements the newest one is put back unchanged and the result is `failed`; a document displaced by that put-back is kept beside the file as `.claude.json.trust-kept-<n>`. A host with no exchanging rename gets `failed` with nothing written, never a plain-rename fallback. The result is read back. A file that does not exist is created (mode 0600); a file that is not a JSON object, whose `projects` or project entry is not an object, or that is a symbolic link, is never written and reads `failed`.

**D4. The row.** Each grant appends one owner-action row `trust.granted` with `{by, cause, project, root, profiles}`, where `profiles` names each profile and its result. It is not a kept kind (ADR-console-015) and carries no file content: rows and stderr name profiles, the project, the key and results only. A grant that has written files always logs its row, even when `close` has begun, and `close` waits for running grants before it closes the log; a grant that starts after `close` began writes nothing.

**D5. A failed read-back.** A (root, profile) pair whose read-back failed is an inbox question card with the single option `Check again`, which grants that one pair again, logs it and goes when a later row reads `granted` or `already` for the pair. The card gives the terminal route in plain words: `cd <root> && CLAUDE_ACCOUNT=<profile> claude`, then accept the prompt and type `/exit`. It is offered only for a pair a logged grant named.

**D6. A profile added later.** A profile added on the page is granted every project in the fleet registry by the console, after the launcher's add and before the sign-in, read back and logged. The console's `Adder` sets `CLAUDE_ACCOUNT_SKIP_FOLDER_TRUST=1`, so the launcher's thirty-second creation deadline covers creation only. A profile added by `claude-account add` in a terminal is granted the same projects by the launcher through `folder-trust grant-registered`, one implementation for both, before its first session.

**D7. Nothing else grants.** Trust is set only by writing the documented key. No undocumented route is used, such as the `CLAUDE_CODE_SANDBOXED` environment variable, and no flag, environment variable or settings key marks a folder trusted; `CLAUDE_ACCOUNT_SKIP_FOLDER_TRUST` withholds only the launcher's own grant (D6). No grant is made for a project the owner did not approve.

**D8. The host check.** The host check `console-register` of #1052 keeps exercising registration end to end: it answers the `Register <name>` card, expects `registered`, and its restore removes the trust entry its throwaway root caused from every target, so it still leaves no trace.

## Consequences

- A first goal in a registered project starts without the interactive prompt, in every profile that existed at the approval or was added after.
- Tests sandbox HOME, the profile directories and the repositories; none touches the real `~/.claude.json`, the real profiles or the real fleet registry.
- A project registered before this change is not granted until a profile is added or the owner runs `folder-trust grant-registered`; nothing sweeps the registry on its own.
- A residual remains: no lock is shared with the client, so a client that reads the console's interim merge in the instant between two swaps and later writes from it can drop the key; the next grant restores it.
- The Darwin swap (`RENAME_SWAP`) is tested only by a local run on a Mac, since CI is Linux only.
- Related: ADR-console-015, ADR-console-025, ADR-console-028, ADR-console-030, ADR-hosts-005.
