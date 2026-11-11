# ADR-console-008 — Only the page writes, with a per-install token and the console's own origin

- **Status:** accepted
- **Decided in:** #837, #838, #861

## Context

ADR-console-004 gave the console one write route, the hook route, which appends session observations and answers nothing, so it carries no token. The page's digest of what changed since the owner last looked (#861) needs the page to write: the console, not the browser, stores when the owner looked (#837 item 8). A write the page makes can change what the owner is told, so any local process or foreign web page must not be able to make it. #838 item 7 decided that page writes need a per-install token and an origin check.

## Decision

A write made by the page is a page write, and the only paths that take one are the members of `PAGE_WRITES` in `agent_tools.console.service`. Every member goes through one guard, `_page_write`, and a later write joins the set rather than adding a route of its own. The first member is `POST /api/looked`, which appends one `page.looked` event and answers an empty `204`.

The guard admits a page write only when exactly one `Origin` header equals `http://<Host>`, the console's own origin, and exactly one `X-Console-Token` header equals the install's token, compared in constant time. It runs after the loopback `Host` check and before any body is read, so a refused write reads nothing and appends nothing. A terminal sends no `Origin` and a foreign page sends its own, so neither passes. A page write carries no body: a `Content-Length` other than absent or `0`, or any `Transfer-Encoding`, is refused as `400` `no body`.

The token is 43 URL-safe characters, created once in `page-token` beside the event log (mode 0600, directory 0700, created with `O_EXCL`) and read back on every start. A token file that is unreadable or malformed stops the console, with `console: page token unusable: <error>` and exit 1. The token is placed in the page's `console-token` meta tag when the page is served and appears in no API answer, stream frame, log row or stderr line.

## Consequences

- A local process can read the token from the page or from the file: loopback trust is the boundary (#826), and the token only stops a foreign page and a request that did not come from the page.
- A page served before a restart keeps working, because the token belongs to the install and not to the run.
- The hook route stays tokenless, as ADR-console-004 decided.
- Deleting `page-token` makes the next start mint a new token; a page still open from before shows a `403` on its next write until reloaded.
