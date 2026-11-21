"""The console's one control system: every desk control carries exactly one kind (#1137)."""

import html
import json
import re
import unittest
from datetime import timedelta
from pathlib import Path

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .console_screenshots import CONTROL_SELECTOR
from .test_console_spend_page import render_spend, spend_view_fixture
from .test_console_page import (
    ACTIVATION, ADD_STEPS, ADDED, ADOPTION_ITEM, ANSWERABLE, ASK_ANSWERED, ASK_CHOOSE, ASKING, BRIEF, CHECK, DECISION_ITEM, DRAFTED, F3, FAILED_ITEM,
    FAILED_REGISTRATION, FAILED_START, GOAL_FRAME, HEADSUP_W, MORE_KEY, NOW_MS, NOW_S, NO_ITEM, NO_LINK_RUNNING,
    OPEN_A, OWNER_W, PICTURED, PROGRESS, Q0, Q1, R0, R2, REGISTER_TYPED, REPORTED, SIGNED_IN_STEPS,
    SIGNIN, SPRINT, ACTIVATION, START, STALL, T0, V, WORK_CAP, ANSWER, ASK_ANSWERED, cards,
    FAILED_LINE, asking, check_item, frame, media_block, nodes, panel, postable, project, real_capacity, render,
    look_answered, style_rules, thread, view, with_check, with_notices, with_run, with_sprints, css_declared)
from .test_console_guest_page import (
    CHANGE_FRAME, GUEST, MANUAL, OPEN_OWN, SHARED_FRAME, TICK, UNSHARED_OPEN, attempt_reply, harness)

REPO_ROOT = Path(__file__).resolve().parents[1]
PAGE = REPO_ROOT / "python/agent_tools/console/page.html"
SPEND = REPO_ROOT / "python/agent_tools/console/spend.html"

KINDS = ("btn-primary", "btn-quiet", "btn-danger", "btn-option", "field-line", "field-area",
         "field-code")
TREES = ("inbox", "statement", "projects", "unmanaged", "digest", "goal", "capacity", "account_add",
         "register", "accounts", "accounts_body", "promoted", "viewer", "reading", "sharing_open",
         "sharing_body")
BUTTON_FOLDS = ("sprint-more", "item-detail")
QUIET_ONLY = frozenset({"btn-quiet"})
PRIMARY_OR_QUIET = frozenset({"btn-primary", "btn-quiet"})
PRIMARY_ONLY = frozenset({"btn-primary"})
DANGER_ONLY = frozenset({"btn-danger"})
OPTION_ONLY = frozenset({"btn-option"})
LINE_ONLY = frozenset({"field-line"})
AREA_ONLY = frozenset({"field-area"})
CODE_ONLY = frozenset({"field-code"})
ANS_PLAIN = ("ans-note", "ans-draft")
ANS_ROLE = "ans-*"


def _roles(kinds: frozenset, *names: str) -> dict:
    return {name: kinds for name in names}


DESK_CONTROLS: dict = {
    **_roles(PRIMARY_OR_QUIET, "approve", "send", "try-again", "signin-start", ANS_ROLE),
    **_roles(PRIMARY_ONLY, "continue", "answer", "start-retry", "look-retry", "adoption-merge"),
    **_roles(DANGER_ONLY, "withdraw", "stall-withdraw", "start-withdraw", "progress-withdraw",
             "acct-remove", "acct-remove-send", "share-off", "share-remove"),
    **_roles(OPTION_ONLY, "opt"),
    **_roles(
        QUIET_ONLY, "tell-open", "tell-send", "retry", "stop", "stop-confirm", "stop-cancel",
        "more-open", "acct-toggle", "acct-pin", "acct-signin", "acct-signout", "acct-remove-cancel", "acct-close",
        "signin-send", "signin-cancel", "give-goal", "notice-open", "notice-send",
        "notice-cancel", "notice-withdraw", "ask-open", "ask-send", "ask-cancel", "ask-goal", "follow-open", "follow-send",
        "follow-cancel", "thread-open", "reading-close", "ask-choice", "reply-send", "undo", *ANS_PLAIN, "goal-project",
        "detail-open", "kept-words-dismiss", "account-add-open", "account-add-send", "account-add-cancel",
        "account-code-send", "account-signin-cancel", "account-link-get", "register-open",
        "register-send", "register-cancel", "register-withdraw", "draft-send", "draft-option",
        "draft-cancel", "draft-change", "goal-send", "goal-cancel", "viewer-prev", "viewer-next",
        "viewer-close", "cap", "pic-thumb", "sprint-check", "draft-pick", "activate",
        "share-open", "share-close", "share-on", "share-edit", "share-project",
        "share-add", "adoption-failed-dismiss"),
    **_roles(AREA_ONLY, "tell", "reply-text", "note-text", "words-text", "kept-words-text", "ask-text",
             "follow-text"),
    **_roles(LINE_ONLY, "draft-text", "confirm-text", "account-name", "acct-remove-name",
             "notice-text", "register-path", "goal-filter", "goal-text", "share-login"),
    **_roles(CODE_ONLY, "signin-code", "account-code"),
}
# The guest page's own-account controls (#1343): drawn only on the guest door, so the desk scenarios never reach them.
GUEST_CONTROLS: dict = {"pool-add": QUIET_ONLY, "guest-signin": PRIMARY_ONLY, "guest-code": QUIET_ONLY,
                        "guest-cancel": QUIET_ONLY, "pool-signout": QUIET_ONLY, "pool-remove": DANGER_ONLY,
                        "pool-remove-send": DANGER_ONLY, "pool-remove-cancel": QUIET_ONLY}
GUEST_CHECKBOXES = frozenset({"guest-tick"})  # a native tick has no kind: it is neither a button nor a typed field
SPEND_CONTROLS: dict = {"span": QUIET_ONLY}
BARE_BUTTONS = frozenset({"cap", "pic-thumb", "sprint-check", "draft-pick", "thread-open"})
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
    panel_open = {"click": "cap"}  # the Add account form sits in the accounts panel, shut at first
    manual = check_item("A", "manual-check")
    approval = check_item("B", "approval")
    words = {"type": {"class": "words-text", "text": "use the reader"}}
    pinned = [{"click": "cap"}, {"click": "acct-toggle"}, {"click": "acct-pin"}]
    colleague_cap = real_capacity(NOW_S, [
        {"name": "work", "week": .6, "five": .5, "week_reset": NOW_S + 4 * 86400, "five_reset": NOW_S + 3600},
        {"name": "colleague-1", "week": .3, "five": .4, "week_reset": NOW_S + 5 * 86400,
         "five_reset": NOW_S + 3600}])
    colleague_cap = {**colleague_cap, "profiles": [
        {**p, "owner": "colleague@example.invalid" if p["profile"] == "colleague-1" else None}
        for p in colleague_cap["profiles"]]}
    own_notice = with_notices(postable(project(0, [])), OWNER_W)
    drawn_notice = [
        begin, {"frame": view([own_notice])}, {"open": "notices:owner/p00"},
        {"click": "notice-open"}, snapshot]
    return [
        [begin, {"frame": view([asking(project(0, []), ASK_ANSWERED)])}, {"click": "ask-open"},
         {"type": {"class": "ask-text", "text": "what runs?"}}, snapshot],
        # a thread's follow-up box under its last answer (#1178)
        [begin, {"frame": view([asking(project(0, []), thread(ASK_CHOOSE))])},
         {"open": "questions:owner/p00"}, {"click": "thread-open"}, snapshot, {"click": "follow-open"},
         {"type": {"class": "follow-text", "text": "and then?"}}, snapshot],
        # a sprint block with Tell open and End the sprint opened, then a stop question
        [START, {"frame": with_sprints([SPRINT])}, {"click": "tell-open"},
         {"open": MORE_KEY}, snapshot],
        [START, {"frame": with_sprints([{**SPRINT, "stoppable": True}])}, {"open": MORE_KEY},
         snapshot],
        [START, {"frame": with_sprints([{**SPRINT, "stoppable": True}])}, {"open": MORE_KEY},
         {"click": "stop"}, snapshot],
        [START, {"frame": with_sprints([{**SPRINT, "manager_state": "failed",
                                         "manager_text": "no manager", "retry": True}])}, snapshot],
        # a refused answer whose question left keeps the owner's words on a card of their own
        [START, {"frame": frame([Q0, Q1])}, words, {"hold": True}, {"click": "send"},
         {"clock": 5000}, {"frame": frame([])},
         {"release": {"status": 409, "text": "this question is already answered"}}, snapshot],
        [START, {"frame": with_check([])}, snapshot],
        # the activation line with its Activate button (#1193)
        [START, {"frame": {**view([project(0, [], quiet=True)]), "activation": ACTIVATION}},
         snapshot],
        [START, {"frame": with_check([DECISION_ITEM])}, snapshot],
        # an approved look card whose post failed, with its Retry (#1260)
        [START, {"frame": frame([look_answered("failed", FAILED_LINE)])}, snapshot],
        # an adoption card with Merge, then the notice a refused click leaves once its card is gone
        [START, {"frame": frame([ADOPTION_ITEM])}, snapshot],
        [START, {"frame": frame([ADOPTION_ITEM])}, ADOPTION_REFUSED, {"click": "adoption-merge"},
         {"frame": frame([])}, snapshot],
        # a stall and a progress card
        [START, {"frame": frame([STALL, PROGRESS])}, snapshot],
        [START, {"frame": frame([FAILED_START])}, snapshot],
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
        # a colleague's account in the panel: its Sign out beside Remove (#1345)
        [START, {"frame": {**view([]), "capacity": colleague_cap}}, {"click": "cap"}, snapshot],
        # Add account: naming, then the code phase
        [START, {"frame": V}, panel_open, {"click": "account-add-open"}, snapshot],
        [*ADD_STEPS[:2], panel_open, *ADD_STEPS[2:], snapshot],
        [*NO_LINK_RUNNING[:2], panel_open, *NO_LINK_RUNNING[2:], snapshot],
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
        [*OPEN, {"click": "share-edit"}, snapshot],
        [*UNSHARED_OPEN, snapshot],
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

    def test_the_guest_page_draws_every_own_account_control_with_one_kind(self) -> None:
        start, linked = harness([*OPEN_OWN, SNAP, TICK, attempt_reply(7, MANUAL, "manual"),
                                 {"click": "guest-signin"}, SNAP], GUEST)
        (changing,) = harness([START, {"frame": CHANGE_FRAME}, {"click": "pool-remove"}, SNAP], GUEST)
        drawn, wrong = set(), []
        for tree, snap in (("own_account", start), ("own_account", linked), ("pool", changing)):
            for node, parent in _walk(snap[tree], None):
                if not _is_control(node, parent):
                    continue
                key = role(node["cls"])
                drawn.add(key)
                if key in GUEST_CHECKBOXES:
                    continue
                kinds = set(node["cls"].split()) & set(KINDS)
                allowed = GUEST_CONTROLS.get(key, DESK_CONTROLS.get(key))
                if len(kinds) != 1 or allowed is None or not kinds <= allowed:
                    wrong.append(node["cls"])
        self.assertEqual(wrong, [])
        self.assertEqual(sorted((set(GUEST_CONTROLS) | GUEST_CHECKBOXES) - drawn), [])

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
                if not dynamic and name not in DESK_CONTROLS and name not in GUEST_CONTROLS \
                        and name not in GUEST_CHECKBOXES:
                    problems.append(f"unlisted role {name!r} in {expression!r}")
                if not kind_in(literal) and not suffixed and name not in GUEST_CHECKBOXES:
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


def targets_control(selector: str, roles: dict = DESK_CONTROLS) -> str | None:
    """The control role, kind or tag a selector's last compound targets, else None."""
    compound = last_compound(selector)
    if ':not([class*="btn-"])' in compound:
        return None
    classes = set(re.findall(r"\.([\w-]+)", compound))
    for name in sorted(classes):
        if name in roles or name in KINDS or (
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


def short_rules(style: str, roles: dict) -> list:
    """Every rule of the style aimed at a control of `roles` that sets a height below 32 px."""
    small = []
    for selector, decls in rules_of(style):
        if targets_control(selector, roles) is None:
            continue
        for prop in ("height", "min-height", "max-height"):
            if prop in decls and css_px(decls[prop]) < 32:
                small.append(f"{selector} {{ {prop}: {decls[prop]} }}")
    return small


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
        for page, style, roles in (("desk", self.style, DESK_CONTROLS),
                                   ("spend", spend_style(), SPEND_CONTROLS)):
            with self.subTest(page=page):
                self.assertEqual(short_rules(style, roles), [])
        block = style_rules(controls_block(self.style))
        for kind in KINDS:
            with self.subTest(kind=kind):
                heights = [d["min-height"] for s, d in block if s == "." + kind and "min-height" in d]
                self.assertTrue(heights, kind)
                self.assertGreaterEqual(css_px(heights[-1]), 32)

    def test_the_consent_tick_is_at_least_32_px_in_both_directions(self) -> None:
        # The screenshot check rejects every visible input under 32 px, and the tick is an input.
        declared = css_declared(self.style, ".guest-tick")
        for prop in ("width", "height"):
            with self.subTest(prop=prop):
                self.assertGreaterEqual(css_px(declared.get(prop, "0")), 32)

    def test_the_height_floor_gate_sees_a_later_spend_rule(self) -> None:
        shrunk = spend_style() + "\n.span { min-height: 20px; }\n"
        self.assertEqual(short_rules(shrunk, SPEND_CONTROLS), [".span { min-height: 20px }"])
        self.assertEqual(short_rules(shrunk, DESK_CONTROLS), [])


def css_px(value: str) -> float:
    """A length in px; `rem` and `em` count 16 px. An unreadable length is 0, so it fails a floor."""
    match = re.match(r"^([\d.]+)(px|rem|em)?(?:\s*!important)?$", value.strip())
    if match is None:
        return 0.0
    number = float(match.group(1))
    return number if match.group(2) in (None, "px") else number * 16


HOVER = ':hover:not(:disabled):not([aria-disabled="true"])'
SNAP = {"snapshot": True}
ADOPTION_REFUSED = {"respond": {"status": 409, "text": "the pull request was merged elsewhere\n"}}
NO_REPLY = {"status": 204, "text": ""}
BUTTON_KINDS = ("btn-primary", "btn-quiet", "btn-danger", "btn-option")
BUSY_ROLES = frozenset({
    "tell-send", "notice-send", "register-send", "account-add-send", "goal-send", "reply-send",
    "acct-toggle", "acct-pin", "acct-remove-send", "acct-remove-cancel", "acct-signin",
    "account-link-get", "account-code-send", "account-signin-cancel", "draft-option", "draft-send",
    "register-withdraw", "send", "retry", "withdraw", "stop-confirm", "stop-cancel", "try-again",
    "stall-withdraw", "start-retry", "start-withdraw", "continue", "progress-withdraw",
    "signin-start", "signin-send", "look-retry",
    "signin-cancel", "notice-withdraw", "ans-draft", "opt", "words-text", "draft-text",
    "share-on", "share-off", "share-add", "share-remove", "adoption-merge"})


def refusal(text: str) -> dict:
    return {"status": 409, "text": text + "\n"}


def held(click: str, *more) -> list:
    """The act of a busy row: hold the next post, click, any further step, then a snapshot."""
    return [{"hold": True}, {"click": click}, *more, SNAP]


def held_click(cls: str) -> list:
    return [{"hold": True}, {"click": cls}]


def busy_row(name, setup, act, release, roles=None, where=None, exceptions=None) -> tuple:
    return (name, [*setup, SNAP], act, [{"release": release}, SNAP],
            frozenset(roles or {name}), where, exceptions or {})


def _removal_frame() -> dict:
    return {**view([]), "capacity": real_capacity(NOW_S, [{"name": "a", "week": .35},
                                                          {"name": "b", "week": .7}]),
            "profile_sessions": {"a": 2}}


def _panel_signin_steps() -> list:
    shown = {**frame([SIGNIN]), "capacity": WORK_CAP}
    running = {**frame([with_run(SIGNIN, "running", 7)]), "capacity": WORK_CAP,
               "signin_runs": {"work": {"state": "running", "at": None, "attempt": 7}}}
    return [START, {"frame": shown}, *OPEN_A, {"frame": running},
            {"type": {"class": "signin-code", "text": "abc"}}]


def _signed_out_panel_steps() -> list:
    shown = {**view([]), "capacity": real_capacity(NOW_S, [
        {"name": "b", "week": .5, "signin": ("signed_out", None)}])}
    return [START, {"frame": shown}, {"click": "cap"}]


REMOVAL_STEPS = [START, {"frame": _removal_frame()}, {"click": "cap"}, {"click": "acct-remove"},
                 {"type": {"class": "acct-remove-name", "text": "a"}}]
OWNER_NOTICE = postable(with_notices(project(0, []), OWNER_W, HEADSUP_W))
NOTICE_STEPS = [{"start": {"focused": False, "clock": NOW_MS}}, {"frame": view([OWNER_NOTICE])},
                {"open": "notices:owner/p00"}]
OTHER_DRAFT = {**DRAFTED, "draft": [DRAFTED["draft"][0], {**DRAFTED["draft"][1], "value": "tagged"}]}
CANCELLABLE = cards([FAILED_ITEM], {**FAILED_REGISTRATION, "cancel": True})
REGISTER_REFUSED = "only a registration that was not applied yet can be cancelled"
TYPED_WORDS = {"type": {"class": "words-text", "text": "use the reader"}}
SPRINT_STOPPABLE = {**SPRINT, "stoppable": True}

OPEN = [START, {"frame": SHARED_FRAME}, {"click": "share-open"}]

BUSY_SCENARIOS = [
    busy_row("tell-send", [START, {"frame": with_sprints([SPRINT])}, {"click": "tell-open"},
                           {"type": {"class": "tell", "text": "slow down"}}],
             held("tell-send"), NO_REPLY),
    busy_row("notice-send", [*NOTICE_STEPS, {"click": "notice-open"},
                             {"type": {"class": "notice-text", "text": "routes are frozen"}}],
             held("notice-send"), NO_REPLY),
    busy_row("register-send", REGISTER_TYPED, held("register-send"), NO_REPLY),
    busy_row("account-add-send", [START, {"frame": V}, {"click": "account-add-open"},
                                  {"type": {"class": "account-name", "text": "fresh"}}],
             held("account-add-send"), NO_REPLY),
    busy_row("goal-send", [START, {"frame": GOAL_FRAME}, {"key": "g"},
                           {"input": {"cls": "goal-text", "value": "ship the reader"}}],
             held("goal-send"), refusal("no such project")),
    busy_row("reply-send", [START, {"frame": frame([BRIEF])},
                            {"input": {"cls": "reply-text", "value": "redo"}}],
             held("reply-send"), NO_REPLY),
    busy_row("adoption-merge", [START, {"frame": frame([ADOPTION_ITEM])}], held("adoption-merge"),
             NO_REPLY),
    busy_row("acct-toggle", [START, {"frame": F3}, {"click": "cap"}], held("acct-toggle"),
             NO_REPLY, where="panel"),
    busy_row("acct-pin", [START, {"frame": F3}, {"click": "cap"}], held("acct-pin"),
             NO_REPLY, where="panel"),
    busy_row("acct-remove-send", REMOVAL_STEPS, held("acct-remove-send"),
             {"status": 502, "text": "the account was not removed: its sign-out failed: exited\n"},
             {"acct-remove-send", "acct-remove-cancel"}, "panel"),
    busy_row("panel acct-signin", _signed_out_panel_steps(), held("acct-signin"),
             refusal("a sign-in is already running"), {"acct-signin"}, "panel"),
    busy_row("panel signin-send", _panel_signin_steps(), held("signin-send"), NO_REPLY,
             {"signin-send"}, "panel"),
    busy_row("panel signin-cancel", _panel_signin_steps(), held("signin-cancel"), NO_REPLY,
             {"signin-cancel"}, "panel"),
    busy_row("account-link-get", NO_LINK_RUNNING, held("account-link-get"),
             {"status": 200, "text": ADDED}),
    busy_row("account-code-send", [*NO_ITEM, {"type": {"class": "account-code", "text": "abc"}}],
             held("account-code-send"), NO_REPLY),
    busy_row("account-signin-cancel", NO_ITEM, held("account-signin-cancel"), NO_REPLY),
    busy_row("draft-option", [START, {"frame": cards([], OTHER_DRAFT)}, {"open": "draft-more"},
                              {"click": "draft-pick"}, {"click": "draft-option"}],
             held("draft-send"), NO_REPLY, {"draft-option", "draft-send"}),
    busy_row("draft-text", [START, {"frame": cards([], DRAFTED)}, {"click": "draft-change"},
                            {"type": {"class": "draft-edit", "text": "main"}}],
             held("draft-send"), refusal("not a branch"), {"draft-text", "draft-send"}),
    busy_row("register-withdraw", [START, {"frame": CANCELLABLE}], held("register-withdraw"),
             refusal(REGISTER_REFUSED)),
    busy_row("send", [START, {"frame": cards([R0, R2])}],
             [{"hold": True}, {"key": "1"}, {"key": "Enter"}, {"clock": 20000}, SNAP],
             refusal("no")),
    busy_row("retry", [START, {"frame": with_sprints([{
        **SPRINT, "manager_state": "failed", "manager_text": "x", "retry": True}])}],
             held("retry"), refusal("this sprint has a manager")),
    busy_row("withdraw", [START, {"frame": with_sprints([SPRINT])}, {"open": MORE_KEY}],
             held("withdraw"), refusal("this sprint is not open")),
    busy_row("stop-confirm", [START, {"frame": with_sprints([SPRINT_STOPPABLE])},
                              {"open": MORE_KEY}, {"click": "stop"}],
             held("stop-confirm"), refusal("this sprint is already stopping"),
             {"stop-confirm", "stop-cancel"}),
    busy_row("look-retry", [START, {"frame": frame([look_answered("failed", FAILED_LINE)])}],
             held("look-retry"), refusal("this approval is not waiting to be recorded")),
    busy_row("try-again", [START, {"frame": frame([STALL])}], held("try-again"),
             refusal("this sprint has a manager")),
    busy_row("stall-withdraw", [START, {"frame": frame([STALL])}], held("stall-withdraw"),
             refusal("this sprint is not open")),
    busy_row("start-retry", [START, {"frame": frame([FAILED_START])}], held("start-retry"),
             refusal("this sprint has a manager")),
    busy_row("start-withdraw", [START, {"frame": frame([FAILED_START])}],
             held("start-withdraw"), refusal("this sprint is not open")),
    busy_row("continue", [START, {"frame": frame([PROGRESS])}], held("continue"),
             refusal("this sprint's manager is not waiting for you")),
    busy_row("progress-withdraw", [START, {"frame": frame([PROGRESS])}],
             held("progress-withdraw"), refusal("this sprint is not open")),
    busy_row("card signin-start", [START, {"frame": frame([SIGNIN])}], held("signin-start"),
             refusal("a sign-in is running"), {"signin-start"}),
    busy_row("card signin-send", [*SIGNED_IN_STEPS, {"type": {"class": "signin-code",
                                                         "text": "ab#C-1"}}],
             held("signin-send"), NO_REPLY, {"signin-send"}),
    busy_row("card signin-cancel", SIGNED_IN_STEPS, held("signin-cancel"), NO_REPLY,
             {"signin-cancel"}),
    busy_row("notice-withdraw", NOTICE_STEPS, held("notice-withdraw"),
             refusal("this notice has ended")),
    busy_row("question send", [START, {"frame": frame([Q0, Q1])}, TYPED_WORDS],
             held("send", {"clock": 5000}), NO_REPLY, {"send", "words-text", "opt"}),
    busy_row("ans-draft", [START, {"frame": cards([T0])},
                           {"type": {"class": "draft-text", "text": "sample-owner/sample-app"}}],
             held("ans-draft", {"clock": 5000}), refusal("no"), {"ans-draft", "draft-text"}),
    busy_row("share-on", UNSHARED_OPEN, held("share-on"), NO_REPLY),
    busy_row("share-off", OPEN, held("share-off"), NO_REPLY),
    busy_row("share-add", [*OPEN, {"click": "share-edit"}], held("share-add"), NO_REPLY,
             exceptions={"share-remove"}),
    busy_row("share-remove", OPEN, held("share-remove"), NO_REPLY),
]


BUSY_FOCUS = (
    ("acct-toggle", [START, {"frame": F3}, {"click": "cap"}, {"focus_on": "acct-toggle"},
                     *held_click("acct-toggle")]),
    ("acct-pin", [START, {"frame": F3}, {"click": "cap"}, {"focus_on": "acct-pin"},
                  *held_click("acct-pin")]),
    ("acct-remove-send", [*REMOVAL_STEPS, {"focus_on": "acct-remove-send"}, {"hold": True},
                          {"click": "acct-remove-send"}, {"focus_on": "acct-remove-send"}]),
    ("acct-remove-cancel", [*REMOVAL_STEPS, {"focus_on": "acct-remove-send"}, {"hold": True},
                            {"click": "acct-remove-send"}, {"focus_on": "acct-remove-cancel"}]),
    ("acct-signin", [*_signed_out_panel_steps(), {"focus_on": "acct-signin"},
                     *held_click("acct-signin")]),
    ("signin-send", [*_panel_signin_steps(), {"focus_on": "signin-send"},
                     *held_click("signin-send")]),
    ("signin-cancel", [*_panel_signin_steps(), {"focus_on": "signin-cancel"},
                       *held_click("signin-cancel")]),
)


def _is_disabled(node: dict) -> bool:
    return node["disabled"] is True or node["aria_disabled"] == "true"


def _pool(snapshot: dict, where: str | None) -> list:
    """The control nodes a busy row reads: the panel's alone for a panel row, else every tree's."""
    return controls_of({"accounts_body": panel(snapshot)} if where == "panel" else snapshot)


def _every_node(snapshot: dict) -> list:
    return [node for tree in TREES if snapshot.get(tree) is not None
            for node, _parent in _walk(snapshot[tree], None)]


def decls_of(rules: list, selector: str) -> dict:
    merged = {}
    for name, decls in rules:
        if name == selector:
            merged.update(decls)
    return merged


class ControlStateTest(unittest.TestCase):
    def test_a_sending_control_is_busy(self) -> None:
        self.assertEqual(frozenset().union(*(row[4] for row in BUSY_SCENARIOS)), BUSY_ROLES)
        for name, setup, act, settle, roles, where, exceptions in BUSY_SCENARIOS:
            with self.subTest(row=name):
                before, during, after = render([*setup, *act, *settle])
                pool = _pool(during, where)
                for want in sorted(roles):
                    self.assertTrue(
                        [n for n in pool if role(n["cls"]) == want and n["busy"] == "true"],
                        f"{want} is not busy while the post is held")
                for node in pool:
                    if node["busy"] != "true":
                        continue
                    self.assertTrue(_is_disabled(node), node["cls"])
                    if where == "panel":
                        self.assertEqual(node["aria_disabled"], "true", node["cls"])
                        self.assertIs(node["disabled"], False, node["cls"])
                was = {role(n["cls"]) for n in _pool(before, where) if _is_disabled(n)}
                for node in pool:
                    kind = role(node["cls"])
                    if _is_disabled(node) and kind not in was and kind not in exceptions:
                        self.assertEqual(node["busy"], "true", f"{node['cls']} is disabled, not busy")
                self.assertEqual([n["cls"] for n in _every_node(after) if n["busy"] is not None], [])

    def test_a_busy_account_control_keeps_the_focus(self) -> None:
        for cls, steps in BUSY_FOCUS:
            with self.subTest(cls=cls):
                (snap,) = render([*steps, SNAP])
                (kept,) = [n for n in nodes(panel(snap)) if n["focused"]]
                self.assertEqual(role(kept["cls"]), cls)
                self.assertEqual(kept["busy"], "true")
                self.assertEqual(kept["aria_disabled"], "true")
                self.assertIs(kept["disabled"], False)

    def test_disabled_and_busy_carry_an_attribute_and_a_non_colour_cue(self) -> None:
        for name, page in (("desk", PAGE), ("spend", SPEND)):
            rules = style_rules(controls_block(page.read_text(encoding="utf-8")))
            with self.subTest(page=name):
                dashed = {"border-width": "1px", "border-style": "dashed",
                          "border-color": "var(--s1)", "cursor": "not-allowed", "opacity": ".55"}
                dotted = {"border-width": "1px", "border-style": "dotted", "cursor": "progress"}
                last_disabled, first_busy = -1, len(rules)
                for kind in KINDS:
                    for state, want in ((":disabled", dashed), ('[aria-disabled="true"]', dashed),
                                        ('[aria-busy="true"]', dotted)):
                        selector = "." + kind + state
                        found = [i for i, (sel, _d) in enumerate(rules) if sel == selector]
                        self.assertTrue(found, selector)
                        have = decls_of(rules, selector)
                        self.assertEqual({k: have.get(k) for k in want}, want, selector)
                        if want is dashed:
                            last_disabled = max(last_disabled, *found)
                        else:
                            first_busy = min(first_busy, *found)
                self.assertGreater(first_busy, last_disabled)
                after = [sel for sel, decls in rules if "::after" in sel]
                self.assertEqual(sorted(after), sorted(
                    f'.{k}[aria-busy="true"]::after' for k in
                    ("btn-primary", "btn-quiet", "btn-danger")))
                for sel, decls in rules:
                    if "::after" in sel:
                        self.assertEqual(decls.get("content"), r'"\2026"', sel)
        desk = style_rules(desk_block(PAGE.read_text(encoding="utf-8")))
        self.assertFalse([sel for sel, _d in desk if "::after" in sel])

    def test_hover_is_shared_by_both_pages(self) -> None:
        shared = {"background": "var(--hover)", "border-color": "var(--s2)"}
        for name, page in (("desk", PAGE), ("spend", SPEND)):
            text = page.read_text(encoding="utf-8")
            rules = style_rules(controls_block(text))
            with self.subTest(page=name):
                for kind in ("btn-quiet", "btn-danger", "btn-option"):
                    have = decls_of(rules, "." + kind + HOVER)
                    self.assertEqual({k: have.get(k) for k in shared}, shared, kind)
                self.assertEqual(
                    decls_of(rules, ".btn-quiet.btn-bare" + HOVER).get("border-color"), "transparent")
                self.assertFalse([sel for sel, _d in rules if ":enabled" in sel])
        addendum = style_rules(desk_block(PAGE.read_text(encoding="utf-8")))
        self.assertFalse([sel for sel, _d in addendum if ":enabled" in sel])
        have = decls_of(addendum, ".btn-primary" + HOVER)
        self.assertEqual((have.get("background"), have.get("border-color")), ("#f8bb98", "#f8bb98"))

    def test_every_kind_shows_the_lavender_ring_on_keyboard_focus(self) -> None:
        ring = {"outline": "2px solid var(--lav)", "outline-offset": "2px", "border-radius": "8px"}
        for name, page in (("desk", PAGE), ("spend", SPEND)):
            text = page.read_text(encoding="utf-8")
            rules = style_rules(controls_block(text))
            with self.subTest(page=name):
                for kind in KINDS:
                    have = decls_of(rules, "." + kind + ":focus-visible")
                    self.assertEqual({k: have.get(k) for k in ring}, ring, kind)
                self.assertEqual(decls_of(rules, ".field-bare:focus-visible").get("outline"), "none")
                ring_at = max(i for i, (sel, _d) in enumerate(rules) if sel == ".field-code:focus-visible")
                bare_at = max(i for i, (sel, _d) in enumerate(rules) if sel == ".field-bare:focus-visible")
                self.assertGreater(bare_at, ring_at)
        for name, style in (("desk", page_style()), ("spend", spend_style())):
            quiet = []
            for selector, decls in rules_of(outside_blocks(style) if name == "desk" else style):
                if decls.get("outline") in ("none", "0") and targets_control(selector) is not None:
                    quiet.append(selector)
            with self.subTest(outside=name):
                self.assertEqual(quiet, [])

    def test_pressed_is_an_attribute_with_a_non_colour_cue(self) -> None:
        (goal,) = render([START, {"frame": GOAL_FRAME}, {"key": "g"}, SNAP])
        (register,) = render([
            START, {"frame": cards([], OTHER_DRAFT)}, {"open": "draft-more"},
            {"click": "draft-pick"}, {"click": "draft-option"}, SNAP])
        projects = [n for n in controls_of(goal) if role(n["cls"]) == "goal-project"]
        self.assertEqual([n["pressed"] for n in projects], ["true", "false", "false"])
        options = [n for n in controls_of(register) if role(n["cls"]) == "draft-option"]
        self.assertTrue(options)
        self.assertEqual([n["pressed"] for n in options], ["true"] + ["false"] * (len(options) - 1))
        for node in projects + options:
            self.assertNotIn("picked", node["cls"].split())
        for name, page in (("desk", PAGE), ("spend", SPEND)):
            rules = style_rules(controls_block(page.read_text(encoding="utf-8")))
            with self.subTest(page=name):
                for kind in BUTTON_KINDS:
                    active = decls_of(rules, "." + kind + ":active")
                    self.assertEqual(active.get("transform"), "translateY(1px)", kind)
                    pressed = decls_of(rules, "." + kind + '[aria-pressed="true"]')
                    self.assertEqual((pressed.get("border-color"), pressed.get("font-weight")),
                                     ("var(--lav)", "600"), kind)

    def test_peach_is_only_on_the_primary_kind(self) -> None:
        for name, style in (("desk", page_style()), ("spend", spend_style())):
            for selector, decls in rules_of(style):
                if not any("var(--peach)" in value for value in decls.values()):
                    continue
                classes = set(re.findall(r"\.([\w-]+)", last_compound(selector)))
                primary = "btn-primary" in classes and not classes & (set(KINDS) - {"btn-primary"})
                needs = ".needs" in selector and targets_control(selector) is None
                with self.subTest(page=name, selector=selector):
                    self.assertTrue(primary or needs)
        for snap in snapshots_of(desk_scenarios()):
            for node in controls_of(snap):
                self.assertNotIn("needs", node["cls"].split(), node["cls"])
            for tree in ("inbox", "statement"):
                if snap.get(tree) is None:
                    continue
                for card, _parent in _walk(snap[tree], None):
                    if {"card", "lead"} <= set(card["cls"].split()):
                        primaries = [n for n, _p in _walk(card, None)
                                     if "btn-primary" in n["cls"].split()]
                        self.assertLessEqual(len(primaries), 1)


def contrast(fg_hex: str, bg_hex: str) -> float:
    """The WCAG 2 contrast ratio of two `#rrggbb` colours."""
    def luminance(hex_colour: str) -> float:
        channels = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return .2126 * r + .7152 * g + .0722 * b
    lighter, darker = sorted((luminance(fg_hex), luminance(bg_hex)), reverse=True)
    return (lighter + .05) / (darker + .05)


def _field_nodes(snapshot: dict):
    for tree in TREES:
        if snapshot.get(tree) is None:
            continue
        stack = [(snapshot[tree], [])]
        while stack:
            node, ancestors = stack.pop()
            yield node, ancestors
            stack.extend((child, ancestors + [node]) for child in node["children"])


def _text_of(node: dict) -> str:
    """The text of a node and of everything below it."""
    return node["text"] + "".join(_text_of(child) for child in node["children"])


class ControlLabelTest(unittest.TestCase):
    def test_every_input_has_a_label(self) -> None:
        unlabelled = []
        for snap in snapshots_of(desk_scenarios()):
            for node, ancestors in _field_nodes(snap):
                if node["tag"] not in ("input", "textarea"):
                    continue
                if node.get("label"):
                    continue
                if any(a["tag"] == "label" and _text_of(a).strip() for a in ancestors):
                    continue
                unlabelled.append(role(node["cls"]))
        self.assertEqual(sorted(set(unlabelled)), [])

    def test_placeholders_meet_4_5_to_1_against_their_field(self) -> None:
        style = page_style()
        root_rule = re.search(r":root \{[^}]*\}", style).group(0)
        root = dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})", root_rule))

        def colour(value: str) -> str:
            return root[re.fullmatch(r"var\((--[\w-]+)\)", value).group(1)]

        rules = [(s, d) for s, d in style_rules(controls_block(style)) if "::placeholder" in s]
        self.assertEqual([s for s, _d in rules],
                         [".field-line::placeholder", ".field-area::placeholder",
                          ".field-code::placeholder"])
        decls = rules[0][1]
        self.assertTrue(all(d == decls for _s, d in rules))
        self.assertEqual(decls["opacity"], "1")
        placeholder = colour(decls["color"])
        everything = style_rules(style)
        backgrounds = {}
        for kind in ("field-line", "field-area", "field-code"):
            backgrounds[kind] = colour(decls_of(everything, "." + kind)["background"])
        backgrounds["goal-in open"] = colour(
            decls_of(everything, ".goal-bar.open .goal-in")["background"])
        for name, background in backgrounds.items():
            with self.subTest(field=name):
                self.assertGreaterEqual(contrast(placeholder, background), 4.5)

    def test_contrast_matches_the_wcag_formula(self) -> None:
        self.assertEqual(round(contrast("#939ab7", "#1e2030"), 2), 5.79)
        self.assertEqual(round(contrast("#181926", "#f5a97f"), 2), 9.01)


VOID_TAGS = frozenset({"input", "br", "hr", "img"})
CONTROL_HEIGHTS = f"""Array.from(document.querySelectorAll({json.dumps(CONTROL_SELECTOR)})).filter(
  (n) => n.getClientRects().length > 0 && getComputedStyle(n).visibility !== "hidden").map(
  (n) => [(n.getAttribute("class") || "").split(/\\s+/)[0], n.getBoundingClientRect().height,
          getComputedStyle(n).display])"""
CONTROL_BORDERS = f"""Array.from(document.querySelectorAll({json.dumps(CONTROL_SELECTOR)})).filter(
  (n) => n.matches(':disabled, [aria-disabled="true"], [aria-busy="true"]')).map((n) => {{
  const s = getComputedStyle(n);
  return [(n.getAttribute("class") || "").split(/\\s+/)[0], s.borderTopWidth, s.borderTopStyle,
          s.borderTopColor, n.getAttribute("aria-busy") === "true"];
}})"""


def tree_html(node: dict) -> str:
    """A desk harness snapshot node written back as markup: no `src` and no `href`."""
    attrs = {"class": node["cls"] or None, "hidden": node["hidden"] or None,
             "open": node["open"] is True and node["tag"] == "details" or None,
             "disabled": node["disabled"] or None, "placeholder": node["placeholder"],
             "aria-label": node["label"], "aria-pressed": node["pressed"],
             "aria-busy": node["busy"], "aria-disabled": node["aria_disabled"]}
    if node["tag"] == "input" and node["value"] is not None:
        attrs["value"] = node["value"]
    open_tag = "".join(
        f" {name}" if value is True else f' {name}="{html.escape(str(value), quote=True)}"'
        for name, value in attrs.items() if value is not None and value is not False)
    if node["tag"] in VOID_TAGS:
        return f"<{node['tag']}{open_tag}>"
    text = node["value"] if node["tag"] == "textarea" and node["value"] is not None else node["text"]
    inner = html.escape(text or "") + "".join(tree_html(child) for child in node["children"])
    return f"<{node['tag']}{open_tag}>{inner}</{node['tag']}>"


def specimen(style: str, body: str) -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><style>{style}</style>'
            f"</head><body>{body}</body></html>")


def held_specimens() -> list:
    """The held snapshot of every busy scenario, under the desk `<style>`."""
    style = page_style()
    pages = []
    for _name, setup, act, _settle, _roles, _where, _exceptions in BUSY_SCENARIOS:
        held_snap = render([*setup, *act])[-1]
        body = "".join(f'<div id="{tree.replace("_", "-")}">{tree_html(held_snap[tree])}</div>'
                       for tree in TREES if held_snap.get(tree) is not None)
        pages.append(specimen(style, body))
    return pages


KIND_SPECIMENS = (
    '<button class="btn-primary">p</button>', '<button class="btn-quiet">q</button>',
    '<button class="btn-danger">d</button>', '<button class="btn-option">o</button>',
    '<input class="field-line">', '<textarea class="field-area"></textarea>',
    '<input class="field-code">')
BARE_SPECIMENS = (
    '<button class="cap btn-quiet btn-bare">c</button>',
    '<button class="pic-thumb btn-quiet btn-bare">t</button>',
    '<button class="sprint-check btn-quiet btn-bare">s</button>',
    '<div class="register"><button class="draft-pick btn-quiet btn-bare">k</button></div>',
    '<ul class="thread-list"><li class="thread"><button class="thread-open btn-quiet btn-bare">t</button></li></ul>',
    '<div class="goal-bar open"><div class="goal-in">'
    '<textarea class="goal-text field-line field-bare"></textarea></div></div>')


def state_specimen() -> str:
    """Every kind and every bare role three times: disabled, aria-disabled and busy."""
    states = ("disabled", 'aria-disabled="true"', 'aria-busy="true" aria-disabled="true"')
    cells = []
    for state in states:
        for markup in (*KIND_SPECIMENS, *BARE_SPECIMENS):
            cells.append(re.sub(r"<(button|input|textarea)", rf"<\1 {state}", markup))
    return specimen(page_style(), "<div>" + "".join(cells) + "</div>")


PATH_OPTION = "owner/repo/release/main"
PATH_DRAFT = {**DRAFTED, "draft": [DRAFTED["draft"][0], {
    **DRAFTED["draft"][1], "value": "tagged", "line": "release branch: owner/repo/main (tagged)",
    "options": [{"value": "path", "label": PATH_OPTION}]}]}


class OptionWrapTest(unittest.TestCase):
    def test_a_registration_option_label_is_one_flex_item(self) -> None:
        """`.btn-quiet` is a flex box: a label's path segments must share one child (#1137)."""
        (snap,) = render([START, {"frame": cards([], PATH_DRAFT)}, {"open": "draft-more"},
                          {"click": "draft-pick"}, {"snapshot": True}])
        (button,) = [n for n in nodes(snap["register"]) if "draft-option" in n["cls"].split()]
        self.assertEqual(button["text"], "")
        (label,) = button["children"]
        self.assertEqual(label["tag"], "span")
        self.assertEqual("".join(n["text"] for n in nodes(label)), PATH_OPTION)

    def test_a_registration_setting_line_is_one_flex_item(self) -> None:
        (snap,) = render([START, {"frame": cards([], PATH_DRAFT)}, {"open": "draft-more"},
                          {"snapshot": True}])
        (button,) = [n for n in nodes(snap["register"]) if "draft-pick" in n["cls"].split()]
        self.assertEqual(button["text"], "")
        (label,) = button["children"]
        self.assertEqual(label["tag"], "span")


CONSOLE_URL = "http://console.test"
PAGE_STUBS = """
window.__sources = [];
window.__replies = [];
window.EventSource = class {
  constructor() { this.listeners = {}; window.__sources.push(this); }
  addEventListener(name, fn) { this.listeners[name] = fn; }
};
window.fetch = (url) => {
  if (String(url).startsWith("/api/picture/")) {
    return Promise.resolve({ status: 200, ok: true, text: () => Promise.resolve(""),
                             blob: () => Promise.resolve(new Blob([""])) });
  }
  const reply = window.__replies.shift() || { status: 204, text: "" };
  return Promise.resolve({ status: reply.status, ok: reply.status >= 200 && reply.status < 300,
                           text: () => Promise.resolve(reply.text) });
};
window.__step = (step) => {
  const fold = (key) => key === undefined ? document
    : Array.from(document.querySelectorAll("details")).find((d) => d.dataset.key === key);
  const find = (cls, key, nth) => {
    const scope = fold(key);
    const found = scope && Array.from(scope.querySelectorAll("." + cls))[nth || 0];
    if (!found) throw new Error("no element with class " + cls);
    if (found.getClientRects().length === 0) throw new Error("the owner cannot see " + cls);
    return found;
  };
  const fill = (spec, key, append) => {
    const target = find(spec.class, key, 0);
    target.focus();
    target.value = append ? target.value + spec.text : spec.text;
    target.dispatchEvent(new Event("input", { bubbles: true }));
  };
  if ("frame" in step) window.__sources[0].listeners.view({ data: JSON.stringify(step.frame) });
  else if ("open" in step) fold(step.open).open = true;
  else if ("click" in step) { const t = find(step.click, step.in, step.nth); if (!t.disabled) t.click(); }
  else if ("type" in step) fill(step.type, step.in, false);
  else if ("append" in step) fill(step.append, step.in, true);
  else if ("input" in step) {
    const target = find(step.input.cls, step.in, 0);
    target.value = step.input.value;
    target.dispatchEvent(new Event("input", { bubbles: true }));
  } else if ("key" in step) document.body.dispatchEvent(new KeyboardEvent("keydown", { key: step.key, bubbles: true }));
  else if ("respond" in step) window.__replies.push(step.respond);
  else throw new Error("unsupported step " + Object.keys(step));
};
"""
SETTLE = "new Promise((done) => setTimeout(done, 25))"


def served(route) -> None:
    """Serve the real desk page at `/` and the real Spend page at `/spend`; nothing else."""
    path = route.request.url.removeprefix(CONSOLE_URL) or "/"
    pages = {"/": (PAGE, "__CONSOLE_TOKEN__"), "/spend": (SPEND, None)}
    if path not in pages:
        route.fulfill(status=204, body="")
        return
    file, slot = pages[path]
    body = file.read_text(encoding="utf-8")
    route.fulfill(status=200, content_type="text/html",
                  body=body.replace(slot, "test-token") if slot else body)


def real_readings(browser, width: int, expression: str) -> dict:
    """The control readings of the real pages at one width: `desk` (one list per scenario
    snapshot, the real page.html replaying the scenario steps) and `spend` (the real
    spend.html over its fixture view)."""
    page = browser.new_page(viewport={"width": width, "height": 900})
    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route(f"{CONSOLE_URL}/**", served)
    page.add_init_script(PAGE_STUBS)
    found = {"desk": [], "spend": []}

    def load(path: str, clock: int) -> None:
        page.clock.set_fixed_time(clock)
        page.goto(CONSOLE_URL + path)
        page.evaluate(SETTLE)

    for steps in desk_scenarios():
        first = next(step["start"] for step in steps if "start" in step)
        load("/", first["clock"])
        for step in steps:
            if "start" in step:
                continue
            if "snapshot" in step:
                found["desk"].append(page.evaluate(expression))
                continue
            page.evaluate("(step) => window.__step(step)", step)
            page.evaluate(SETTLE)
    load("/spend", NOW_MS)
    page.evaluate("(view) => window.__step({ frame: view })", spend_view_fixture())
    page.evaluate(SETTLE)
    found["spend"].append(page.evaluate(expression))
    page.close()
    if errors:
        raise AssertionError(f"the real page threw at {width}: {errors}")
    return found


class ControlTargetTest(unittest.TestCase):
    def chromium(self):
        """A launched Chromium; the test is skipped when playwright or Chromium is missing."""
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        pw = sync_playwright().start()
        self.addCleanup(pw.stop)
        try:
            browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        except Error as err:
            self.skipTest(f"no Chromium to launch: {err}")
        self.addCleanup(browser.close)
        return browser

    def read_widths(self, pages: list, widths: tuple, expression: str) -> dict:
        """Load each markup at each width in Chromium: width -> one reading list per page."""
        browser = self.chromium()
        found = {}
        for width in widths:
            page = browser.new_page(viewport={"width": width, "height": 900})
            found[width] = []
            for markup in pages:
                page.set_content(markup)
                found[width].append(page.evaluate(expression))
            page.close()
        return found

    def test_every_listed_control_is_at_least_32_px_tall_in_chromium(self) -> None:
        """The real pages, whole: the layout containers of production stay around every control."""
        browser = self.chromium()
        for width in (1440, 480):
            read = real_readings(browser, width, CONTROL_HEIGHTS)
            for name, rows_by_snapshot in read.items():
                measured = set()
                for rows in rows_by_snapshot:
                    for cls, height, display in rows:
                        key = role_key(cls)
                        measured.add(key)
                        with self.subTest(page=name, width=width, role=key):
                            self.assertGreaterEqual(height, 32, f"{name} {key} {height}")
                            if key == "opt":
                                self.assertEqual(display, "grid", f"{name} {key} {display}")
                with self.subTest(page=name, width=width, completeness=True):
                    roles = DESK_CONTROLS if name == "desk" else SPEND_CONTROLS
                    self.assertEqual(sorted(set(roles) - measured), [])

    def test_a_disabled_or_busy_control_shows_its_border_in_chromium(self) -> None:
        pages = [*held_specimens(), state_specimen()]
        (readings,) = self.read_widths(pages, (1440,), CONTROL_BORDERS).values()
        rows = [row for page in readings for row in page]
        self.assertTrue(rows)
        for cls, width, style, colour, busy in rows:
            with self.subTest(role=cls, busy=busy):
                message = f"{cls} {width} {style} {colour}"
                self.assertEqual(width, "1px", message)
                self.assertEqual(style, "dotted" if busy else "dashed", message)
                self.assertNotEqual(colour, "rgba(0, 0, 0, 0)", message)
        self.assertEqual(sorted(BARE_ROLES - {role(row[0]) for row in rows}), [])
