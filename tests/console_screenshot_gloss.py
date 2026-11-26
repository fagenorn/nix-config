"""The picture run's `jargon-gloss` state (#1797).

`jargon-gloss` is the stuck sprint whose report status is `GLOSS_STATUS`, with its report fold opened. On the
head's console (`style_applies()`), the mark inside that status is tapped, so its gloss shows. A head page
without the mark fails the shot. On the base commit's console, the same open report shows the plain status,
which is the before picture (#1797).

This module imports nothing from `agent_tools`: a base run puts the base commit's `python/` on the path, which
has no `owner_words`."""
from __future__ import annotations

MINUTE = 60.0
GLOSS_STATE = "jargon-gloss"
GLOSS_STATUS = "waiting on the land lock"
GLOSS_FOLD = 'details[data-key^="sprint:"]'
GLOSS_MARK = GLOSS_FOLD + " p.report-status button.gloss"


def seed_gloss(seed, web: str) -> None:
    """One stuck sprint of `web` whose report status holds a glossary word."""
    seed.sprint(web, "Add resumable uploads", started=60 * MINUTE, report=45 * MINUTE,
                report_extra={"status": GLOSS_STATUS})


def shoot_gloss(page, head: bool) -> None:
    """Open the seeded sprint's report; on the head, tap the mark in its status and wait for the gloss."""
    page.click(GLOSS_FOLD + " > summary")
    page.wait_for_selector(GLOSS_FOLD + "[open] p.report-status")
    if head:
        if page.query_selector(GLOSS_MARK) is None:
            raise RuntimeError("the head page drew no gloss mark in the seeded report: " + GLOSS_MARK)
        page.click(GLOSS_MARK)
        page.wait_for_selector(GLOSS_FOLD + " p.report-status .gloss-text")
