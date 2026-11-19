# ADR-console-080 — The sign-in hands out the client's manual link, or names the port to forward

- **Status:** accepted
- **Decided in:** #1323

## Context

On 19 Nov the owner signed a profile in from the page on eleven-m5 while the browser was on another Mac. The link the console handed out returned to `http://localhost:<port>/callback`, and that address is the browser's own machine, not the console's, so the sign-in never finished. Claude Code 2.1.322 has a way out: with its input not a terminal, `claude auth login` writes its manual link to stdout (`If the browser didn't open, visit: <link>`), a link whose return address is `https://platform.claude.com/oauth/code/callback`, and reads `code#state` from stdin. The console had sent that output to nowhere, so it never saw the manual link, while the code box already feeds the pipe the manual route reads.

## Decision

**D1. The console reads the client's output.** The console reads the client's stdout and keeps the manual link: a link whose `redirect_uri` is an `https` address on a host that is not loopback. The client may wrap the link in terminal hyperlink escapes, and it is read wrapped or not.

**D2. The answer prefers the manual link.** The answer's link is the manual link when the client offers one, with route `manual`. After the browser link arrives the console waits at most 2 seconds for the manual link, and the first answer of an attempt is its answer for every later page, the start and the link route alike.

**D3. A loopback-only run names its port.** When the client offers no manual link and the browser link returns to a loopback address, the answer is that link with route `loopback`, the port it names (80 when none is written) and the command `ssh -N -L <port>:localhost:<port> <host>`, with the console host's short name. A browser link whose return address cannot be read is handed out as route `unknown`, and the card says so.

**D4. The answer shape.** This amends ADR-console-024 D1 and the add answer of ADR-console-025: the start, link and add answers carry `route` (`manual`, `loopback`, `unknown` or null), `port` and `forward` (null unless the route is `loopback`) beside `attempt` and `link`, and the add answer also `profile`. One link only is handed out.

**D5. Secrecy.** The client's output is read into memory only. A candidate that does not parse is dropped without a word. The port and the command appear only in those answers; no row, stderr line, view or stream frame carries them, the link or the code, and ADR-console-024 D7 stands.

**D6. The page.** The page shows one sentence under the link naming its route. This amends ADR-console-024 D8; its wording is the page's.

## Considered options

- Rewriting the loopback link's `redirect_uri` to the manual address: the state and the challenge belong to the client's own listener, so the client would reject the code.
- Showing both links: the owner would pick the wrong one on the very machine where it fails.
- A pseudo-terminal to read the prompt: the client writes the link to stdout with no terminal, so a pipe is enough and the pseudo-terminal's echo would add the code to the output.

## Consequences

- A sign-in from another machine needs no forward.
- A loopback-only client still tells the owner the exact forward to run.
- The client's output is read in memory, and it is the one new input the console parses.
