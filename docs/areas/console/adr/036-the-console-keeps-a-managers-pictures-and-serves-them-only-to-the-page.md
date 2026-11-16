# ADR-console-036 — The console keeps a manager's pictures and serves them only to the page

- **Status:** accepted; amended by ADR-console-038 and ADR-console-043
- **Decided in:** #1089

## Context

A manager that builds or checks a page has a screenshot of its work, and the owner reading the sprint on the page has no way to see it. The manager's writes (ADR-console-013, ADR-console-019) carry JSON and the sprint's secret in the body; a picture is bytes, and the console must not keep arbitrary files from a local process, grow without bound, or hand a stranger's bytes to a browser. This decision covers what the console accepts and keeps; showing a picture to the owner is a later decision, and the page is not changed here.

## Decision

**D1. A PNG check.** The console keeps a body only when `pictures.checked_png` accepts it: the PNG signature, then an IHDR chunk of length 13 with a matching CRC32, a width and height from 1 to 2**31-1, a colour type and bit depth pair the PNG specification allows, compression 0, filter 0 and interlace 0 or 1. The bytes after the header are not inspected. A body that fails is refused with one of three reasons that start `not a PNG`.

**D2. A size limit.** A picture is at most 2 MiB (2097152 bytes). A longer `Content-Length` is `413` `too large` before any body byte is read, and exactly 2 MiB is taken.

**D3. The store.** Pictures live in `pictures` beside the event log, a directory of mode `0700`. A picture is the file `pictures/<id>`, `id` being the SHA-256 of its bytes in lowercase hex, mode `0600`, written once through a temporary file and moved into place. Sending the same bytes again writes nothing, keeps the file where it is and renews its age.

**D4. The row.** Each accepted send, a resend included, appends one `picture.stored` row `{"picture": <id>, "sprint_id": <id>}` of the sprint's project. The kind is not kept (ADR-console-009): it leaves with the other rows after 90 days.

**D5. References and the sweep.** A row references a picture when its payload `pictures` is a list holding the id; the `picture.stored` row does not reference its own picture. Each retention pass, the one at construction included (ADR-console-009), removes every entry of `pictures` that no row references once it is more than one day old, by the file's modification time. A resend renews that time, so a picture a manager keeps sending lives on. A failing sweep is one stderr line and does not stop the console.

**D6. The write.** `POST /api/picture` is a manager write like the brief, guarded by the sprint's secret and not by the page token (ADR-console-013, ADR-console-019). The body is the PNG with `Content-Type: image/png`; the sprint and its secret travel in the headers `X-Console-Sprint` and `X-Console-Secret`, each exactly once. The checks run in this order and each leaves no file and no row: any `Origin` (the console's own included) is `403` `origin refused`; another media type is `415` `png only`; a length that is not digits is `411`; one over the limit is `413`; a missing, repeated or malformed header, or a body shorter than its length, is `400` `bad picture`; a sprint that is not open is `409`; a wrong secret is `403` `secret refused`; a body that is not a PNG is `400` with its reason. Success is `200` `application/json` `{"picture":"<id>"}`. Neither the secret nor the bytes appear in a stderr line or an answer.

**D7. The read.** `GET /api/picture/<id>` serves a stored picture to the page and to nothing else. It is guarded like a page write (ADR-console-008) with one difference: a browser omits `Origin` on a same-origin `GET` and sends `Sec-Fetch-Site: same-origin`, so a read with no `Origin` is admitted. The checks run in this order after the loopback `Host` check, before the id is looked at, and each refusal is `403`: more than one `Origin`, or one that is not the console's own, is `origin refused`; any `Sec-Fetch-Site` that is not exactly one `same-origin` is `origin refused`; the `X-Console-Token` header exactly once with the install's token, compared in constant time, is required or the answer is `token refused`. Then the id is the route after `/api/picture/`: a query string, or an id that is not 64 lowercase hex digits, is `400` `bad picture id`. The file is read only as `pictures/<id>` and only when it is a regular file that is not a symlink (opened without following and without blocking, so a named pipe is refused rather than waited on); any other case, an unknown id included, is `404` `this picture is not known`. Success is `200` `image/png` with the stored bytes, `X-Content-Type-Options: nosniff` and `Cache-Control: private`, so the page's browser may keep a picture the token already admitted; a refusal keeps `Cache-Control: no-store`. The token is in no header or body.

## Consequences

- A manager can hand the console a screenshot and name it by the id the answer returns; the page can read it with its token, the question card draws pictures from object URLs, and the content security policy's `img-src` is `data: blob:` (ADR-console-038).
- A picture no row names disappears a day after it was last sent; a row that names it keeps it as long as the row is kept.
- The store is bounded by what managers send in a day plus what rows reference, each at most 2 MiB.
- ADR-console-008 lists the route among the manager's writes and ADR-console-009 is amended by the sweep.
- An owner check's pictures are stored and referenced by the inbox row's picture entries (ADR-console-043).
- Related: ADR-console-008, ADR-console-009, ADR-console-013, ADR-console-019.
