# ADR-console-076 — The owner's port answers only the owner's own processes

- **Status:** accepted
- **Decided in:** #1294

## Context

ADR-console-008 relied on loopback trust (#826), which was safe while only the owner had an account on the host. The console now runs on eleven-m5, a shared Mac with other people's accounts and one system user per repository's CI runner, and acting as the owner includes starting managers and activating the host (ADR-system-004). Any local account could load the owner's page, read its token and write.

## Decision

**D1. Who the owner is.** The owner is the user the console runs as, its effective uid (`owner_uid`, default `os.geteuid()`).

**D2. How the connecting process is read.** The console reads the processes holding the client end of the accepted loopback TCP connection, in any TCP state a process still holds, so a client that half-closed after sending its request is attributed. On macOS it runs `/usr/sbin/lsof` with `-w -nP -iTCP@127.0.0.1:<client port> -Fpcun` under a 2 s timeout, takes only the file `<client>-><server>`, and reads it only from a completed run: exit 0 with no diagnostic, or exit 1 with no output at all. On Linux it reads `/proc/net/tcp` and `/proc/net/tcp6`: the row's socket inode, then the processes whose `/proc/<pid>/fd` links hold it, each with the uids of its `status`; the row's own uid must match too but admits nobody alone. No other platform has a reader. There is one lookup per connection.

**D3. Every route of the owner's port.** Reads and writes alike are checked: the page, the Spend page, the state, the stream, the pictures, every page write, the manager writes despite their sprint secret, the hook and reading routes, unknown paths and every method. The check runs before the `Host` check, before any interim `100 Continue` and before any body is read. A refused connection gets `403` `text/plain`, one line (`peer.NOT_OWNER_TEXT`), nothing is appended or published, and one stderr line `console: peer_refused <other_user|not_found|unreadable>` names no uid or command. A request the inherited parser refuses as malformed is answered `400` before the check and carries nothing of the console.

**D4. The lookup fails closed.** Admission needs at least one process of the owner seen holding the client end and no holder of another uid. A lookup that fails, times out, raises, exits with a diagnostic or with partial output, an unreadable proc table, or a platform with no reader is refused with `peer.UNREADABLE_TEXT`. A completed lookup that sees no owner process (another user's connection, whose holder the owner's lookup cannot see) or a holder of another uid is refused with `peer.NOT_OWNER_TEXT`.

**D5. The owner's SSH local forward keeps working.** Its client end is held by the owner's own `sshd-session` (seen on eleven-m5 on 18 Nov), and the command is never judged.

**D6. Out of reach.** An administrator (sudo) or root can always act as the owner, and this record does not claim to stop one. Any relay the owner runs on this host, such as an `ssh -L` or `-D` forward or `socat`, admits whoever reaches it, because the console sees only the owner's own process holding the connection. A descriptor an owner process hands to another user's process, by descriptor passing or across a set-user-ID program, is seen only through the owner's holder, so it is a relay of the same kind. A root process's connection is refused, because the owner's lookup does not see it, which is no defence against an administrator, who can run as the owner.

**D7. The guest port is unchanged.** By the owner's answer of 19 Nov the guest door moves to a Unix socket only Serve and the owner can reach, in a later slice (ADR-console-066).

### Considered options

- The page token alone: any local account could load the page and read the token.
- Parsing the `net.inet.tcp.pcblist_n` sysctl: a binary layout tied to the macOS version.
- Serving the owner on a Unix socket: a browser through an SSH forward cannot reach one.

## Consequences

- This amends the first consequence of ADR-console-008: "loopback trust is the boundary" now holds for the owner's processes only.
- Every owner-port connection on macOS costs one lsof run (about 50 ms measured) before its first answer, a running console's hook call included. A stopped console still costs nothing, and the hook-cost check gates only that.
- The state read's no-file, no-subprocess promise covers an admitted connection.
- The evidence after activation is the `console-owner-port` check on eleven-m5, whose SSH forward listens on a Unix socket in a mode-0700 temporary directory, never a loopback TCP port, and which shows another user cannot open it.
