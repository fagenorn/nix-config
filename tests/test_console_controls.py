"""The console's one control system: every desk control carries exactly one kind (#1137)."""

import re
import unittest
from datetime import timedelta
from pathlib import Path

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .test_console_spend_page import render_spend, spend_view_fixture
from .test_console_page import (
    ADD_STEPS, ANSWERABLE, ASKING, BRIEF, CHECK, DECISION_ITEM, DRAFTED, F3, FAILED_ITEM,
    FAILED_REGISTRATION, GOAL_FRAME, MORE_KEY, NOW_MS, NOW_S, NO_LINK_RUNNING, OPEN_A, OWNER_W, PICTURED, PROGRESS,
    Q0, REGISTER_TYPED, REPORTED, SIGNIN, SPRINT, START, STALL, T0, V, WORK_CAP, ANSWER, cards,
    check_item, frame, media_block, nodes, postable, project, real_capacity, render, style_rules,
    view, with_check, with_notices, with_run, with_sprints)

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "python/agent_tools/console/page.html"
SPEND = REPO_ROOT / "python/agent_tools/console/spend.html"

KINDS = ("btn-primary", "btn-quiet", "btn-danger", "btn-option", "field-line", "field-area",
         "field-code")
TREES = ("inbox", "statement", "projects", "unmanaged", "digest", "goal", "capacity", "account_add",
         "register", "accounts", "accounts_body", "promoted", "viewer")
BUTTON_FOLDS = ("sprint-more", "item-detail")
QUIET_ONLY = frozenset({"btn-quiet"})
PRIMARY_OR_QUIET = frozenset({"btn-primary", "btn-quiet"})
PRIMARY_ONLY = frozenset({"btn-primary"})
DANGER_ONLY = frozenset({"btn-danger"})
OPTION_ONLY = frozenset({"btn-option"})
LINE_ONLY = frozenset({"field-line"})
AREA_ONLY = frozenset({"field-area"})
CODE_ONLY = frozenset({"field-code"})
ANS_PLAIN = ("ans-note", "ans-words", "ans-draft")
ANS_ROLE = "ans-*"


def _roles(kinds: frozenset, *names: str) -> dict:
    return {name: kinds for name in names}


DESK_CONTROLS: dict = {
    **_roles(PRIMARY_OR_QUIET, "approve", "send", "try-again", "signin-start", ANS_ROLE),
    **_roles(PRIMARY_ONLY, "continue", "answer"),
    **_roles(DANGER_ONLY, "withdraw", "stall-withdraw", "progress-withdraw", "acct-remove",
             "acct-remove-send"),
    **_roles(OPTION_ONLY, "opt"),
    **_roles(
        QUIET_ONLY, "tell-open", "tell-send", "retry", "stop", "stop-confirm", "stop-cancel",
        "more-open", "acct-toggle", "acct-pin", "acct-signin", "acct-remove-cancel", "acct-close",
        "signin-send", "signin-cancel", "give-goal", "notice-open", "notice-send",
        "notice-cancel", "notice-withdraw", "reply-send", "undo", *ANS_PLAIN, "goal-project",
        "detail-open", "account-add-open", "account-add-send", "account-add-cancel",
        "account-code-send", "account-signin-cancel", "account-link-get", "register-open",
        "register-send", "register-cancel", "register-withdraw", "draft-send", "draft-option",
        "draft-cancel", "draft-change", "goal-send", "goal-cancel", "viewer-prev", "viewer-next",
        "viewer-close", "cap", "pic-thumb", "sprint-check", "draft-pick"),
    **_roles(AREA_ONLY, "tell", "reply-text", "note-text", "words-text"),
    **_roles(LINE_ONLY, "draft-text", "confirm-text", "account-name", "acct-remove-name",
             "notice-text", "register-path", "goal-filter", "goal-text"),
    **_roles(CODE_ONLY, "signin-code", "account-code"),
}
SPEND_CONTROLS: dict = {"span": QUIET_ONLY}
BARE_BUTTONS = frozenset({"cap", "pic-thumb", "sprint-check", "draft-pick"})
BARE_FIELDS = frozenset({"goal-text"})
BARE_ROLES = BARE_BUTTONS | BARE_FIELDS


def role(cls: str) -> str:
    """The first class token: the control's role."""
    return cls.split()[0] if cls.split() else ""


def role_key(cls: str) -> str:
    """The `DESK_CONTROLS` key of a role: a dynamic answer role is `ans-*`."""
    name = role(cls)
    if name.startswith("ans-") and name not in ANS_PLAIN:
        return ANS_ROLE
    return name


def _is_control(node: dict, parent: dict | None) -> bool:
    classes = node["cls"].split()
    if node["tag"] in ("button", "input", "textarea", "select"):
        return True
    if node["tag"] == "a":
        return any(c.startswith("btn-") for c in classes)
    if node["tag"] == "summary":
        if any(c.startswith("btn-") for c in classes):
            return True
        return parent is not None and bool(set(parent["cls"].split()) & set(BUTTON_FOLDS))
    return False


def _walk(node: dict, parent: dict | None):
    yield node, parent
    for child in node["children"]:
        yield from _walk(child, node)


def controls_of(snapshot: dict) -> list:
    """Every control node over every tree of a harness snapshot."""
    found = []
    for tree in TREES:
        if snapshot.get(tree) is None:
            continue
        for node, parent in _walk(snapshot[tree], None):
            if _is_control(node, parent):
                found.append(node)
    return found


def controls_block(text: str) -> str:
    """The text strictly between the `/* controls */` and `/* end controls */` marker lines."""
    lines = text.splitlines()
    if "/* controls */" not in lines or "/* end controls */" not in lines:
        raise AssertionError("no /* controls */ marker")
    start, end = lines.index("/* controls */"), lines.index("/* end controls */")
    return "\n".join(lines[start + 1:end])


def desk_block(text: str) -> str:
    """The text strictly between the `/* controls: desk */` and `/* end controls: desk */` lines."""
    lines = text.splitlines()
    if "/* controls: desk */" not in lines or "/* end controls: desk */" not in lines:
        raise AssertionError("no /* controls: desk */ marker")
    start, end = lines.index("/* controls: desk */"), lines.index("/* end controls: desk */")
    return "\n".join(lines[start + 1:end])


def outside_blocks(text: str) -> str:
    """The text without the shared block and the desk addendum right after it."""
    lines = text.splitlines()
    controls_block(text)
    desk_block(text)
    start, end = lines.index("/* controls */"), lines.index("/* end controls: desk */")
    return "\n".join(lines[:start] + lines[end + 1:])


def page_style() -> str:
    return re.search(r"(?s)<style>(.*?)</style>", PAGE.read_text(encoding="utf-8")).group(1)


def spend_style() -> str:
    return re.search(r"(?s)<style>(.*?)</style>", SPEND.read_text(encoding="utf-8")).group(1)


def spend_buttons() -> list:
    """Every button node of the Spend page's default render."""
    (snap,) = render_spend([{"frame": spend_view_fixture()}, {"snapshot": True}])["snapshots"]
    return [node for tree in snap.values() if isinstance(tree, dict)
            for node, _parent in _walk(tree, None) if node["tag"] == "button"]


def page_script() -> str:
    return re.search(r"(?s)<script>(.*?)</script>", PAGE.read_text(encoding="utf-8")).group(1)


def desk_scenarios() -> list:
    """Step lists that together draw every `DESK_CONTROLS` role; each ends with a snapshot."""
    snapshot = {"snapshot": True}
    begin = {"start": {"focused": False, "clock": NOW_MS}}
    posting = {"respond": {"status": 204, "text": ""}}
    brief_open = {"frame": frame([BRIEF, DECISION_ITEM])}
    manual = check_item("A", "manual-check")
    approval = check_item("B", "approval")
    words = {"type": {"class": "words-text", "text": "use the reader"}}
    pinned = [{"click": "cap"}, {"click": "acct-toggle"}, {"click": "acct-pin"}]
    own_notice = with_notices(postable(project(0, [])), OWNER_W)
    drawn_notice = [
        begin, {"frame": view([own_notice])}, {"open": "notices:owner/p00"},
        {"click": "notice-open"}, snapshot]
    return [
        # a sprint block with Tell open and End the sprint opened, then a stop question
        [START, {"frame": with_sprints([SPRINT])}, {"click": "tell-open"},
         {"open": MORE_KEY}, snapshot],
        [START, {"frame": with_sprints([{**SPRINT, "stoppable": True}])}, {"open": MORE_KEY},
         snapshot],
        [START, {"frame": with_sprints([{**SPRINT, "stoppable": True}])}, {"open": MORE_KEY},
         {"click": "stop"}, snapshot],
        [START, {"frame": with_sprints([{**SPRINT, "manager_state": "failed",
                                         "manager_text": "no manager", "retry": True}])}, snapshot],
        [START, {"frame": with_check([])}, snapshot],
        [START, {"frame": with_check([DECISION_ITEM])}, snapshot],
        # a stall and a progress card
        [START, {"frame": frame([STALL, PROGRESS])}, snapshot],
        # the raised decision card with its Detail fold, and a brief
        [START, {"frame": frame([DECISION_ITEM])}, snapshot],
        [START, brief_open, {"input": {"cls": "reply-text", "value": "redo"}}, snapshot],
        [START, {"frame": frame([BRIEF])}, {"click": "approve"}, snapshot],
        # a manual check with a note, and an approval with its confirmation
        [START, {"frame": frame([manual])}, {"type": {"class": "note-text", "text": "slow"}}, snapshot],
        [START, {"frame": frame([approval])},
         {"type": {"class": "confirm-text", "text": "octo/widgets#1"}}, snapshot],
        # a words answer and a draft answer, a question to choose and send
        [START, {"frame": frame([Q0])}, words, snapshot],
        [START, {"frame": frame([Q0])}, {"click": "opt"}, snapshot],
        [START, {"frame": frame([ANSWERABLE])}, {"click": "opt"}, snapshot],
        [START, {"frame": frame([ANSWERABLE])}, {"click": "opt"}, {"click": "send"}, snapshot],
        [START, {"frame": cards([T0])}, snapshot],
        # an adoption question with draft options: pick an option then type into the draft field
        [START, {"frame": cards([], DRAFTED)}, {"open": "draft-more"}, {"click": "draft-pick"},
         snapshot],
        [START, {"frame": cards([], DRAFTED)}, {"click": "draft-change"},
         {"type": {"class": "draft-edit", "text": "main"}}, snapshot],
        [START, {"frame": cards([], {**DRAFTED, "draft": [
            DRAFTED["draft"][0], {**DRAFTED["draft"][1], "value": "tagged"}]})},
         {"open": "draft-more"}, {"click": "draft-pick"}, {"click": "draft-option"},
         {"type": {"class": "draft-edit", "text": "main"}}, snapshot],
        [START, {"frame": cards([FAILED_ITEM], {**FAILED_REGISTRATION, "cancel": True})},
         snapshot],
        # the accounts panel: exclusion, pin, a row's own Sign in, Remove opened, a running sign-in
        [START, {"frame": F3}, *pinned, {"click": "acct-remove"}, snapshot],
        [START, {"frame": {**view([]), "capacity": real_capacity(NOW_S, [
            {"name": "work", "week": .5, "signin": ("signed_out", None), "ever": True}])}},
         {"click": "cap"}, snapshot],
        [START, {"frame": {**frame([SIGNIN]), "capacity": WORK_CAP}}, *OPEN_A,
         {"frame": {**frame([with_run(SIGNIN, "running", 7)]), "capacity": WORK_CAP,
                    "signin_runs": {"work": {"state": "running", "at": None, "attempt": 7}}}},
         snapshot],
        [START, {"frame": frame([SIGNIN])}, {"respond": {"status": 200, "text": ANSWER}},
         {"click": "signin-start"},
         {"frame": frame([with_run(SIGNIN, "running", 7)])}, snapshot],
        [START, {"frame": frame([SIGNIN])}, snapshot],
        # Add account: naming, then the code phase
        [START, {"frame": V}, {"click": "account-add-open"}, snapshot],
        [*ADD_STEPS, snapshot],
        [*NO_LINK_RUNNING, snapshot],
        # Register project with a result
        [*REGISTER_TYPED, snapshot],
        # the notices fold with post opened and an own notice
        drawn_notice,
        [begin, {"frame": view([own_notice])}, {"open": "notices:owner/p00"}, snapshot],
        # the goal box open with projects, and a quiet project's Give it a goal
        [START, {"frame": GOAL_FRAME}, {"key": "g"}, snapshot],
        [START, {"frame": {**view([project(1, [], quiet=True, ago=timedelta(days=3))]),
                           "recent_projects": ["owner/p01"]}}, snapshot],
        # the picture viewer open
        [START, {"frame": frame([PICTURED])}, {"click": "pic-thumb", "nth": 1}, snapshot],
        [START, {"frame": {**F3, **frame([ANSWERABLE])}}, snapshot],
        [START, {"frame": frame([ANSWERABLE])}, {"click": "opt"}, {"click": "send"},
         posting, snapshot],
        [START, {"frame": frame([manual])}, {"click": "ans-passed"}, snapshot],
    ]


def snapshots_of(scenarios: list) -> list:
    return [snap for steps in scenarios for snap in render(steps)]


class ControlInventoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snaps = snapshots_of(desk_scenarios())

    def test_every_control_on_both_pages_carries_exactly_one_kind(self) -> None:
        wrong = []
        for snap in self.snaps:
            for node in controls_of(snap):
                classes = node["cls"].split()
                kinds = set(classes) & set(KINDS)
                key = role_key(node["cls"])
                allowed = DESK_CONTROLS.get(key)
                bad = len(kinds) != 1 or allowed is None or not kinds <= allowed
                if "btn-bare" in classes and (kinds != {"btn-quiet"} or key not in BARE_BUTTONS):
                    bad = True
                if "field-bare" in classes and (kinds != {"field-line"} or key not in BARE_FIELDS):
                    bad = True
                if key in BARE_BUTTONS and "btn-bare" not in classes:
                    bad = True
                if key in BARE_FIELDS and "field-bare" not in classes:
                    bad = True
                if bad:
                    wrong.append(f"{role(node['cls'])}: {node['cls']}")
        self.assertEqual(sorted(set(wrong)), [])
        buttons = spend_buttons()
        self.assertTrue(buttons)
        for node in buttons:
            kinds = set(node["cls"].split()) & set(KINDS)
            with self.subTest(spend=node["cls"]):
                self.assertEqual(len(kinds), 1)
                self.assertLessEqual(kinds, SPEND_CONTROLS.get(role(node["cls"]), frozenset()))

    def test_every_listed_desk_control_is_drawn(self) -> None:
        drawn = {role_key(n["cls"]) for snap in self.snaps for n in controls_of(snap)
                 if n["tag"] != "a" or "btn-primary" in n["cls"].split()}
        self.assertEqual(sorted(set(DESK_CONTROLS) - drawn), [])

    def test_every_creation_site_names_a_listed_role(self) -> None:
        script = page_script()
        problems = []
        summaries = []
        for expression in creation_expressions(script):
            literals = string_literals(expression)
            if not literals:
                continue
            suffixed = any(s.startswith(" ") and kind_in(s) for s in literals)
            for literal in literals:
                if literal.startswith(" "):
                    continue
                dynamic = literal == "ans-" and re.match(r'\s*"ans-"\s*\+', expression)
                name = literal.split()[0] if literal.split() else ""
                if not dynamic and name not in DESK_CONTROLS:
                    problems.append(f"unlisted role {name!r} in {expression!r}")
                if not kind_in(literal) and not suffixed:
                    problems.append(f"no kind in {expression!r}")
        for literal in summary_literals(script):
            if "btn-" in literal:
                summaries.append(literal)
        self.assertEqual(problems, [])
        self.assertEqual(sorted(summaries), ["detail-open btn-quiet", "more-open btn-quiet"])


CALLS = ("actionButton(", "viewerButton(", 'el("button", ', 'el("input", ', 'el("textarea", ',
         "typedArea(", "draftInput(", "accountField(", "signinStartButton(item, ",
         "answerLink(item, ")


def split_expression(text: str, start: int) -> str:
    """The text from `start` up to the first `,` or `)` at bracket depth 0, strings skipped."""
    depth, at, quote = 0, start, None
    while at < len(text):
        char = text[at]
        if quote:
            if char == "\\":
                at += 1
            elif char == quote:
                quote = None
        elif char in "\"'`":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                break
            depth -= 1
        elif char in ",;" and depth == 0:
            break
        at += 1
    return text[start:at]


def string_literals(expression: str) -> list:
    return [a or b for a, b in re.findall(r'"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\'', expression)]


def kind_in(literal: str) -> bool:
    return bool(set(literal.split()) & set(KINDS))


def creation_expressions(script: str) -> list:
    found = []
    for call in CALLS:
        for match in re.finditer(re.escape(call), script):
            found.append(split_expression(script, match.end()))
    receivers = set(re.findall(
        r'(?:const|let) (\w+) = (?:el\("(?:button|input|textarea)"|actionButton\(|viewerButton\('
        r'|typedArea\(|draftInput\(|accountField\(|signinStartButton\('
        r'|document\.createElement\("(?:input|textarea|button)"\))', script))
    for match in re.finditer(r"\b(\w+)\.className = ", script):
        if match.group(1) in receivers:
            found.append(split_expression(script, match.end()))
    return found


def summary_literals(script: str) -> list:
    found = []
    for match in re.finditer(re.escape('el("summary", '), script):
        found += string_literals(split_expression(script, match.end()))[:1]
    return found


def rules_of(style: str) -> list:
    """Every (selector, declarations) of the style, media blocks included."""
    queries = re.findall(r"@media ([^{]*?) \{", style)
    top = re.sub(r"(?s)@media[^{]*\{.*?\}\s*\}", "", style)
    rules = style_rules(top)
    for query in queries:
        rules += style_rules(media_block(style, query))
    return rules


def last_compound(selector: str) -> str:
    return re.split(r"\s*[>+~]\s*|\s+", selector.strip())[-1]


def targets_control(selector: str) -> str | None:
    """The control role, kind or tag a selector's last compound targets, else None."""
    compound = last_compound(selector)
    if ':not([class*="btn-"])' in compound:
        return None
    classes = set(re.findall(r"\.([\w-]+)", compound))
    for name in sorted(classes):
        if name in DESK_CONTROLS or name in KINDS or (
                name.startswith("ans-") and name not in ANS_PLAIN) or name in ANS_PLAIN:
            return name
    if 'class^="ans-"' in compound:
        return "ans-"
    if re.match(r"(button|input|textarea)(?![\w-])", compound):
        return re.match(r"\w+", compound).group(0)
    if compound.startswith("summary"):
        before = selector.strip()[:len(selector.strip()) - len(compound)]
        if set(re.findall(r"\.([\w-]+)", before)) & set(BUTTON_FOLDS):
            return "summary"
    return None


LOOK = re.compile(
    r"^(padding.*|border.*|font.*|color|background.*|cursor|outline.*|opacity)$")
LOOK_OPTION = re.compile(r"^(display|grid.*|align-items|gap|column-gap|width)$")
BORDER = re.compile(r"^border.*$")


def kind_owned(name: str, prop: str) -> bool:
    if name in BARE_ROLES:
        return bool(BORDER.match(prop))
    if LOOK.match(prop):
        return True
    return (name == "opt" or name == "btn-option") and bool(LOOK_OPTION.match(prop))


class ControlStyleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.style = page_style()

    def test_the_kinds_are_declared_once_in_the_controls_block(self) -> None:
        block = controls_block(self.style)
        rows = style_rules(block)

        def merged(kind: str) -> dict:
            out = {}
            for selector, decls in rows:
                if selector == kind:
                    out.update(decls)
            return out

        shared = {
            "display": "inline-flex", "align-items": "center", "gap": "8px", "min-height": "32px",
            "padding": "5px 12px", "font": "500 .875rem/1.4 var(--ui)", "text-align": "left",
            "text-decoration": "none", "color": "var(--sub1)", "background": "none",
            "border": "1px solid var(--s1)", "border-radius": "8px", "cursor": "pointer",
            "transition": "background-color .16s, border-color .16s"}
        field = {
            "min-height": "32px", "padding": "5px 10px", "font": "400 .875rem/1.4 var(--ui)",
            "color": "var(--text)", "background": "var(--mantle)", "border": "1px solid var(--s1)",
            "border-radius": "8px"}
        expected = {
            "btn-primary": {**shared, "min-height": "40px", "padding": "0 16px",
                            "font-weight": "600"},
            "btn-quiet": shared,
            "btn-danger": shared,
            "btn-option": {**shared, "display": "grid",
                           "grid-template-columns": "22px minmax(0, 1fr) auto",
                           "column-gap": "14px", "width": "100%", "min-height": "44px",
                           "padding": "9px 14px", "color": "var(--text)",
                           "border-color": "transparent"},
            "field-line": field,
            "field-area": {**field, "display": "block", "width": "100%", "min-height": "4.5rem",
                           "resize": "vertical"},
            "field-code": {**field, "font-family":
                           'ui-monospace, "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace',
                           "letter-spacing": ".06em"},
        }
        for kind, want in expected.items():
            with self.subTest(kind=kind):
                have = merged("." + kind)
                self.assertEqual({k: have.get(k) for k in want}, want)
                self.assertGreaterEqual(css_px(have["min-height"]), 32)
        self.assertEqual(merged(".btn-bare").get("padding"), "0")
        self.assertEqual(merged(".field-bare").get("padding-left"), "0")
        self.assertIn("--hover: rgba(202, 211, 245, .05);", self.style)
        outside = style_rules(outside_blocks(self.style))
        for selector, _decls in outside:
            self.assertNotIn(selector, ["." + k for k in KINDS], selector)

    def test_both_pages_share_one_controls_block(self) -> None:
        spend = SPEND.read_text(encoding="utf-8")
        self.assertEqual(controls_block(spend), controls_block(PAGE.read_text(encoding="utf-8")))
        self.assertNotIn("/* controls: desk */", spend)
        self.assertIn("--hover: rgba(202, 211, 245, .05);", spend_style())

    def test_both_pages_turn_motion_off_under_reduced_motion(self) -> None:
        for name, style in (("desk", self.style), ("spend", spend_style())):
            with self.subTest(page=name):
                block = media_block(style, "(prefers-reduced-motion: reduce)")
                self.assertTrue(block)
                rules = style_rules(block)
                for selector in ("*", "*::before", "*::after"):
                    held = {k: v for s, d in rules if s == selector for k, v in d.items()}
                    self.assertEqual(held.get("transition-duration"), ".001ms !important")
                    self.assertEqual(held.get("animation-duration"), ".001ms !important")

    def test_kind_rules_own_the_control_look(self) -> None:
        offenders = []
        outside = outside_blocks(self.style)
        for selector, decls in rules_of(outside):
            name = targets_control(selector)
            if name is None or ".picked" in last_compound(selector):
                continue
            for prop, value in decls.items():
                if kind_owned(name, prop):
                    offenders.append(f"{selector} {{ {prop}: {value} }}")
                if prop in ("min-height", "height") and css_px(value) < 32:
                    offenders.append(f"{selector} {{ {prop}: {value} }}")
        self.assertEqual(offenders, [])

    def test_no_rule_shrinks_a_control_below_32_px(self) -> None:
        small = []
        for selector, decls in rules_of(self.style):
            if targets_control(selector) is None:
                continue
            for prop in ("height", "min-height", "max-height"):
                if prop in decls and css_px(decls[prop]) < 32:
                    small.append(f"{selector} {{ {prop}: {decls[prop]} }}")
        self.assertEqual(small, [])
        block = style_rules(controls_block(self.style))
        for kind in KINDS:
            with self.subTest(kind=kind):
                heights = [d["min-height"] for s, d in block if s == "." + kind and "min-height" in d]
                self.assertTrue(heights, kind)
                self.assertGreaterEqual(css_px(heights[-1]), 32)


def css_px(value: str) -> float:
    """A length in px; `rem` and `em` count 16 px. An unreadable length is 0, so it fails a floor."""
    match = re.match(r"^([\d.]+)(px|rem|em)?(?:\s*!important)?$", value.strip())
    if match is None:
        return 0.0
    number = float(match.group(1))
    return number if match.group(2) in (None, "px") else number * 16
