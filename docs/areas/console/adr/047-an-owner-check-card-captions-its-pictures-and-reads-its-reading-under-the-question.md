# ADR-console-047 — An owner check card captions its pictures and reads its reading under the question

Context: the owner found raw file names under thumbnails noisy and the `Reading:` line easy to miss (#1131). Decision: the page, not the console, captions an owner check thumbnail from its file name (dropping `.png`, a trailing width read as px). The stored line and the viewer keep the full name, and the reading sits right after the question. Rejected: rewriting the stored line, which would lose which file a thumbnail is.
