"""The guard on the console's page writes (#861): a per-install token and the console's own origin.

The console's one hook route (`POST /api/hooks`) takes observations from Claude Code and carries
no token (ADR-console-004). A write made by the page is different: the page is the only caller,
so it is refused unless it proves it is the page (ADR-console-008, decisions D1 and D3 of #861).

A page write is admitted only when, in this order:

1. exactly one `Origin` header equals `http://<Host>`, the origin the console's own page
   has (a terminal sends none, a foreign page sends its own): else `403` `origin refused`;
2. exactly one `X-Console-Token` header equals the install's token, compared in constant
   time: else `403` `token refused`.

A caller meets this guard after the service's loopback `Host` check and before any body is
read, so a refused write reads nothing, appends nothing and publishes nothing.

The token is `secrets.token_urlsafe(32)`: 43 characters of `[A-Za-z0-9_-]`. `load_token` creates
it once, in `page-token` beside the event log (`~/.agents/state/console/page-token`), with
`O_CREAT | O_EXCL`, mode 0600 and the parent directory 0700, and reads the same value back on
every later start. A file that is unreadable, or whose content (one trailing newline allowed) is
not such a token, raises `TokenError`: the service does not start rather than serve with a
token it cannot trust. The token reaches a client only inside the page the service serves, in
the slot `TOKEN_SLOT`; it is in no API answer, no stream frame, no log row and no stderr line.
"""

import hmac
import os
import re
import secrets
from pathlib import Path

TOKEN_HEADER = "X-Console-Token"
TOKEN_SLOT = b"__CONSOLE_TOKEN__"
TOKEN_FILE = "page-token"
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\n?")


class TokenError(Exception):
    """The page token cannot be created, read or trusted."""


def load_token(path: Path) -> str:
    """The install's token: read from `path`, created there when the file is absent."""
    path = Path(path)
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            text = path.read_text(encoding="utf-8")
        else:
            text = secrets.token_urlsafe(32) + "\n"
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(text)
    except (OSError, UnicodeDecodeError) as error:
        raise TokenError(f"{path}: {error}") from error
    if _TOKEN.fullmatch(text) is None:
        raise TokenError(f"{path}: not a 43-character token")
    return text.removesuffix("\n")


def refusal(host: str, origins: list[str], tokens: list[str], token: str) -> tuple[int, str] | None:
    """The `(status, text)` that refuses a page write, or None when it is admitted."""
    if origins != [f"http://{host}"]:
        return 403, "origin refused"
    if len(tokens) != 1 or not hmac.compare_digest(tokens[0].encode(), token.encode()):
        return 403, "token refused"
    return None
