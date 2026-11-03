"""The one rule for naming a GitHub repository from a remote URL (#124; issue 126 D9)."""

import re

GITHUB_REMOTE = re.compile(r"(?:git@github\.com:|https://github\.com/|ssh://git@github\.com/)"
                           r"(?P<slug>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?")


def github_slug(url: str) -> str | None:
    """`owner/name` of a remote URL on the host `github.com` exactly, else None.

    Only the three GitHub spellings are recognised (`git@github.com:`, `https://github.com/`
    and `ssh://git@github.com/`): a URL on any other host, a lookalike host included, names
    no GitHub repository however its path reads.
    """
    match = GITHUB_REMOTE.fullmatch(url.strip())
    return None if match is None or ".." in match["slug"] else match["slug"]
