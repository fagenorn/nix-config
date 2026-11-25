"""The picture run's control target floors, read from every shot after its state is drawn.

Three floors hold, each over the rendered, visible controls of the page (`CONTROL_SELECTOR`, plus
every `a[href]` and `summary`, the whole of `TARGET_SELECTOR`):

- A control under 32 px tall fails (`SHORT_CONTROLS`, read after the state is drawn): a rendered,
  visible button, input, textarea, select, `btn-` link or `btn-` summary.
- A control under 24 by 24 px fails at every width (`SMALL_TARGETS`), except a link in running
  text (an `a` whose computed display is `inline`).
- While `PHONE_MEDIA` matches, a card answer or Tell the manager (`PHONE_TALL`) under 44 px tall
  fails (`SMALL_TARGETS`).

`control_report` turns the shots' readings into the command's failure lines.
"""
from __future__ import annotations

import json

PHONE_WIDTH = 390
PHONE_MEDIA = "(max-width: 480px)"
CONTROL_SELECTOR = 'button, input, textarea, select, a[class*="btn-"], summary[class*="btn-"]'
TARGET_SELECTOR = f"{CONTROL_SELECTOR}, a[href], summary"
PHONE_TALL = (".sprint-acts .tell-open, #inbox .card :is(button, a, summary)"
              ":is(.btn-primary, .btn-quiet, .btn-danger, .btn-option):not(.btn-bare)")

ACTS_ROW = """Array.from(document.querySelectorAll('li[data-project]')).filter((line) => {
  const give = line.querySelector('button.give-goal');
  const ask = line.querySelector('button.ask-open');
  if (!give || !ask || line.getClientRects().length === 0) return false;
  const centre = (node) => {
    const rect = node.getBoundingClientRect();
    return rect.top + rect.height / 2;
  };
  return Math.abs(centre(give) - centre(ask)) > 4;
}).map((line) => line.dataset.project)"""

SHORT_CONTROLS = f"""Array.from(document.querySelectorAll({json.dumps(CONTROL_SELECTOR)})).filter(
  (n) => n.getClientRects().length > 0 && getComputedStyle(n).visibility !== "hidden").map(
  (n) => [n, n.getBoundingClientRect().height]).filter(([n, h]) => h < 32).map(
  ([n, h]) => n.tagName.toLowerCase() + "." + (n.getAttribute("class") || "").split(/\\s+/)[0]
    + " " + Math.round(h * 100) / 100 + "px")"""

SMALL_TARGETS = r"""(() => {
  const round = (x) => Math.round(x * 100) / 100;
  const tall = matchMedia(__MEDIA__).matches
    ? new Set(document.querySelectorAll(__TALL__)) : new Set();
  return Array.from(document.querySelectorAll(__TARGETS__)).filter((n) => {
    const style = getComputedStyle(n);
    return n.getClientRects().length > 0 && style.visibility !== "hidden"
      && !(n.tagName === "A" && style.display === "inline");
  }).flatMap((n) => {
    const box = n.getBoundingClientRect();
    const role = (n.getAttribute("class") || "").trim().split(/\s+/)[0] || "-";
    const name = n.tagName.toLowerCase() + "." + role;
    if (box.width < 24 || box.height < 24) {
      return [name + " " + round(box.width) + "x" + round(box.height) + "px"];
    }
    if (tall.has(n) && box.height < 44) return [name + " " + round(box.height) + "px under 44"];
    return [];
  });
})()""".replace("__MEDIA__", json.dumps(PHONE_MEDIA)).replace(
    "__TALL__", json.dumps(PHONE_TALL)).replace("__TARGETS__", json.dumps(TARGET_SELECTOR))

SPRINT_FOLD = "#projects li.sprint details.sprint-detail > summary"
END_FOLD = "#projects li.sprint summary.more-open"
END_OPEN = "#projects li.sprint details.sprint-more[open] button.withdraw"


def open_end_fold(page) -> None:
    """Open the sprint's own fold, then its End the sprint fold, and wait for Drop the sprint."""
    page.click(SPRINT_FOLD)
    page.click(END_FOLD)
    page.wait_for_selector(END_OPEN)


def control_report(taken) -> list[str]:
    """The failure lines for the shots' control readings: a short one, then a small one."""
    lines = [f"console-screenshots: {shot.path.name} has a control under 32 px "
             f"({', '.join(shot.short)})" for shot in taken if shot.short]
    lines += [f"console-screenshots: {shot.path.name} has a control under 24 by 24 px or a phone "
              f"answer under 44 px ({', '.join(shot.small)})" for shot in taken if shot.small]
    return lines
