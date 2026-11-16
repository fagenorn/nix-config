# ADR-console-045 — An owner check card shows the pictures and the reading its prompt names

- **Status:** accepted
- **Decided in:** #1112

## Context

A manual check asks the owner to look at something: a page, a layout, a screenshot a delivery run saved. Its prompt names the PNG files by path or by folder, and the owner reading the card on the page cannot open them, because the page has no file access and the console serves no host path. The same prompt often holds an instruction for reading the result, buried in its text. ADR-console-036 gave the console a store of pictures that only the page can read, and ADR-console-038 gave a card a gallery and a viewer for them. This decision joins the owner check to both: which files the console may copy, from where, what the card shows, and what it says when a named file is not there.

## Decision

**D1. The pictures.** Each verification item (the ones carrying `check_id`) is passed through `inbox.attach_pictures` when the console polls the tracker, outside the ingest lock. The PNGs its prompt names are read on the console host and copied into the picture store of ADR-console-036 with `pictures.store`. The item then carries `pictures`, a list of `{"id", "line", "pair"}` whose `line` is the file name and whose `pair` is null, and `missing_pictures`. The page reads a picture only through `GET /api/picture/<id>` with its token; no route serves a host path. The attach gives the same result for the same files, so an unchanged poll appends no row. The `inbox.*` row that carries the item keeps its pictures from the sweep: `pictures.referenced` counts a `pictures` member that is an object whose `id` is a picture id, as well as one that is the id itself.

**D2. The allowed roots.** A file may come from the registered project's root or from a screenshot location the console is given: `console --screenshots DIR`, repeatable, set on a host by the home-manager option `agentConsole.screenshotDirs`, which defaults to the `tmp/clarity-screenshots` folder of the home directory, the output of the repository's `console-screenshots` recipe. A path is inside a root when its normalised spelling (never the candidate's realpath) is the root or lies under it, with the root spelt both as written and as its realpath. A file under a root is opened by an anchored walk: the root's realpath is opened as a directory, and each later component is opened relative to the one before it without following a symlink. So no symlink under a root is served, even one swapped in after an earlier check.

**D3. PNG only, the size limit, skipping and the missing line.** Only a name ending `.png` (any case) is a candidate, and a named folder lists only its `.png` entries. A candidate is stored only when it is a regular file of at most `pictures.MAX_BYTES` that `pictures.checked_png` accepts. A candidate outside every root, unreadable, too large or not a PNG is skipped, with no line and nothing stored. A candidate inside a root that does not exist becomes one `missing_pictures` entry, its name as written. An item carries at most 8 pictures and 8 missing names.

**D4. The `Reading:` convention.** A manual check whose detail, after the heading split of #1046, holds `Reading:` at a line start or after whitespace, outside a code fence, is a reading check. Its `reading` is the rest of that line with the whitespace collapsed; the detail loses that text and loses the line if it is left blank. Every other verification item carries `reading` as an empty string. The verify block grammar has no reading member, so only the console reads the convention.

**D5. Only verification items, and the card.** Only a verification item gets pictures and missing names; a decision, a conflict and a needs-label item are unchanged, and an answered check, the folded answered line, shows no pictures. The card shows the pictures in the shared gallery of ADR-console-038 D3, opening the same viewer, each thumbnail's line being its file name. A missing name reads `<name> was not found on this host.` under the gallery. The reading reads `Reading: <instruction>` as its own line in the answer box, right before the answer buttons.

**D6. The page change is held for the owner.** This is a change to how the page looks. The delivery makes before and after PNG screenshots of the owner check card at 1440 and 480 px, and the pull request stays unmerged until the owner approves them on the pull request.

## Consequences

- ADR-console-036's reference rule is amended: an owner check's pictures are stored and referenced by the inbox row's picture entries.
- ADR-console-038's gallery and viewer are reused by the owner check card; its Work column is unchanged.
- The console reads project files and the configured screenshot locations on its own host; nothing outside those roots is read, and a symlink under one is never followed.
- A host's screenshot locations are set in one place, `agentConsole.screenshotDirs`, and both platforms pass them to the same command.
- A prompt that names no PNG, and one with no `Reading:`, show exactly what they showed before.
- Related: ADR-console-008, ADR-console-036, ADR-console-038.
