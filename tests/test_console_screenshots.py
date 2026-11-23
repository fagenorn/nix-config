"""The sprint screenshot set against a fixture console (#1086).

Run: just agent-workflow-tests
"""
import base64
import dataclasses
import http.client
import json
import os
import pwd
import re
import shutil
import sys
import tempfile
import time
import types
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent_tools.console import account_add, approve, event_log, pictures, service, sprints

from . import accounts_sandbox
from . import console_screenshots as shots
from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)


def fixture_paths(fixture):
    paths = [value for field in dataclasses.fields(fixture) if field.name not in ("holding", "deaf", "activating", "registering", "adopting", "refusing", "prompting")
             for value in ([getattr(fixture, field.name)] if field.name != "projects"
                           else list(fixture.projects))]
    return paths


def entries_of(view):
    for entry in view["entries"]:
        yield from (entry["projects"] if entry["type"] == "quiet_group" else [entry])


def all_sprints(view):
    found = []
    for project in entries_of(view):
        found.extend(project.get("sprints") or [])
        found.extend((project.get("finished_sprints") or {"sprints": []})["sprints"])
    return found


def fake_browser(present):
    class Page:
        def __init__(self):
            self.clicks = []
            self.waits = []
            self.reads = 0
            self.card = ()
            self.fills = []
            self.style = []
            self.placed = []
            self.order = []
            self.mutations = []
            self.unbreakable = set()
            self.media = []
            self.viewports = []
            self.cdp = []
            self.fresh_mutation = False
            page = self

            class Session:
                def send(self, method, params=None):
                    page.cdp.append((method, params))
                    page.order.append(method)
                    if method == "DOM.getDocument":
                        return {"root": {"nodeId": 1}}
                    if method == "DOM.querySelectorAll":
                        return {"nodeIds": [2]}
                    return {}

            self.context = SimpleNamespace(new_cdp_session=lambda _page: Session())

        def emulate_media(self, **kw):
            self.media.append(kw)

        def set_viewport_size(self, size):
            self.viewports.append(size)

        def goto(self, url):
            pass

        def wait_for_selector(self, selector):
            self.waits.append(selector)

        def query_selector(self, selector):
            return object() if selector in present else None

        def click(self, selector):
            self.clicks.append(selector)

        def fill(self, selector, text):
            self.fills.append((selector, text))

        def evaluate(self, expression, arg=None):
            if expression == shots.STYLE_PLACE:
                self.order.append("STYLE_PLACE")
                self.placed.append(arg)
                return 0
            if expression == shots.STYLE_CLEAR:
                self.order.append("STYLE_CLEAR")
                self.fresh_mutation = False
                return None
            if expression == shots.STYLE_SETTLE:
                self.order.append("STYLE_SETTLE")
                return None
            if expression == shots.STYLE_MUTATE:
                self.order.append("STYLE_MUTATE")
                self.mutations.append(arg)
                self.fresh_mutation = True
                return None
            if expression == shots.STYLE_READING:
                self.order.append("STYLE_READING")
                found = list(self.style)
                if (self.fresh_mutation and len(arg) == 1
                        and arg[0]["name"] not in self.unbreakable):
                    found.append(f"{arg[0]['name']}: x is y")
                return found
            if expression == shots.ASK_READING:
                self.reads += 1
                return list(shots.HEAD_ASK if shots.READING_PANEL in present else shots.OPEN_ASK)
            if expression == shots.READ_READING:
                self.reads += 1
                self.counted = arg
                return list(shots.READ_SHOWN)
            if expression == shots.DEEPER_READING:
                self.reads += 1
                return json.loads(json.dumps(shots.DEEPER_SHOWN["deeper-answer"]))
            if expression == shots.OFFER_READING:
                self.reads += 1
                return json.loads(json.dumps(shots.DEEPER_SHOWN["deeper-offer"]))
            if expression == shots.THREAD_READING:
                self.reads += 1
                return list(shots.OPEN_THREAD if shots.ASK_FOLD in present else shots.BASE_THREAD)
            if expression == shots.GOAL_READING:
                self.reads += 1
                return list(shots.FILLED_GOAL)
            if expression == shots.ACTIVATION_READING:
                self.reads += 1
                return list(shots.ACTIVATION_SHOWN["activation-tooling"])
            if expression == shots.REGISTER_READING:
                self.reads += 1
                return list(shots.REGISTER_SHOWN["register-reconcile-apply"])
            if expression == shots.CARD_READING:
                self.reads += 1
                return list(self.card)
            if expression == shots.ACTS_ROW:
                return []
            if expression == shots.SCROLL_Y:
                return 0.0
            if expression == "document.documentElement.scrollWidth":
                return 480
            if expression == shots.SHORT_CONTROLS:
                return []
            return 0

        def screenshot(self, path, full_page):
            self.order.append("screenshot")

        def close(self):
            pass

    page = Page()

    class Browser:
        def new_page(self, viewport):
            return page

    return Browser(), page


def style_row(name="held-nowrap", **kw):
    fields = dict(name=name, states=("live-several",), widths=(1440,), selector=".held.blocks",
                  prop="white-space", want="equals", value="nowrap",
                  broken=".held.blocks { white-space: normal !important }")
    fields.update(kw)
    return shots.StyleCheck(**fields)


@dataclasses.dataclass(frozen=True)
class Moved:
    """One property a removed source-reading test asserted, and the style rows that now read it."""
    test: str
    selector: str
    prop: str
    widths: tuple[int, ...]
    rows: tuple[str, ...]
    via: str = ""


PAGE = "tests/test_console_page.py"
BOTH = (1440, 480)
PEACH_VIA = "the rendered page is read for peach on every element"
MOVED: tuple[Moved, ...] = (
    Moved(f"{PAGE}::PageTest::test_the_spend_link_is_quiet", ".nav", "color", BOTH,
          ("nav-quiet",)),
    Moved(f"{PAGE}::PageTest::test_the_spend_link_is_quiet", ".nav", "white-space", BOTH,
          ("nav-nowrap",)),
    Moved(f"{PAGE}::PageTest::test_the_spend_link_is_quiet", ".nav", "width", BOTH,
          ("nav-width",)),
    Moved(f"{PAGE}::PageTest::test_the_spend_link_is_quiet", ".nav", "min-width", BOTH,
          ("nav-min-width",)),
    Moved(f"{PAGE}::PageTest::test_peach_marks_only_needs_you", ".btn-primary", "color", BOTH,
          ("peach-only-needs",), via=PEACH_VIA),
    Moved(f"{PAGE}::PageTest::test_peach_marks_only_needs_you", ".needs", "color", BOTH,
          ("peach-only-needs",), via=PEACH_VIA),
    Moved(f"{PAGE}::PageTest::test_session_states_use_the_state_colours", ".s-working", "color",
          (1440,), ("state-working",)),
    Moved(f"{PAGE}::PageTest::test_session_states_use_the_state_colours", ".s-waiting_answer",
          "color", (1440,), ("state-waiting-answer",)),
    Moved(f"{PAGE}::PageTest::test_session_states_use_the_state_colours", ".s-waiting_permission",
          "color", (1440,), ("state-waiting-permission",)),
    Moved(f"{PAGE}::PageTest::test_session_states_use_the_state_colours", ".s-limit", "color",
          (1440,), ("state-limit",)),
    Moved(f"{PAGE}::PageTest::test_session_states_use_the_state_colours", ":root", "--*", (1440,),
          ("tokens-desk",), via="the :root token list is read from the rendered page"),
    Moved(f"{PAGE}::PageTest::test_runs_are_never_peach_or_red_and_never_stalled", ".run", "color",
          (1440,), ("runs-not-red",)),
    Moved(f"{PAGE}::PageTest::test_runs_are_never_peach_or_red_and_never_stalled", ".run", "color",
          BOTH, ("peach-only-needs",), via=PEACH_VIA),
    Moved(f"{PAGE}::CapacityPageTest::test_every_account_out_reads_out_in_red_and_when_work_resumes",
          ".cap-out", "color", (1440,), ("cap-out-red",)),
    Moved(f"{PAGE}::CapacityPageTest::test_every_account_out_reads_out_in_red_and_when_work_resumes",
          ".cap", "color", BOTH, ("peach-only-needs",), via=PEACH_VIA),
    Moved(f"{PAGE}::PageNoticeTest::test_the_notices_fold_uses_no_peach_and_no_new_colour",
          ".notice", "color", BOTH, ("palette-notices",),
          via="fold_colour_faults is the painted colours of the notices fold on the rendered page"),
    Moved(f"{PAGE}::PageNoticeTest::test_the_notices_fold_uses_no_peach_and_no_new_colour",
          ":root", "--*", (1440,), ("tokens-desk",),
          via="the :root token list is read from the rendered page"),
    Moved(f"{PAGE}::PageNoticeTest::test_the_colour_check_rejects_peach_written_any_way",
          ".notice", "color", BOTH, ("palette-notices",),
          via="a colour written as rgb(), hex, a token, a name, a color-mix() or hsl() is one "
              "painted colour that palette-notices refuses after normalisation"),
    Moved(f"{PAGE}::PageNoticeTest::test_the_colour_check_rejects_peach_written_any_way",
          ".notice", "background-image", BOTH, ("palette-notices-gradient",),
          via="a colour painted by a gradient's stops is one painted colour that the palette "
              "refuses after normalisation"),
    Moved(f"{PAGE}::PageTest::test_peach_marks_only_needs_you", "body", "background-image", BOTH,
          ("peach-only-needs-gradient",),
          via="the rendered page is read for peach in the stops of every element's gradient"),
    Moved(f"{PAGE}::PageNoticeTest::test_the_colour_check_rejects_peach_written_any_way",
          ".notice-long", "color", BOTH, ("palette-notices",),
          via="a painted colour that palette-notices refuses after normalisation"),
    Moved(f"{PAGE}::PageNoticeTest::test_the_colour_check_rejects_peach_written_any_way",
          ".notice", "color", BOTH, ("palette-notices",),
          via="a custom property is checked where it paints"),
    Moved(f"{PAGE}::PageOptionTest::test_option_rows_fill_the_width_and_mark_the_pick_beyond_colour",
          ".btn-option", "width", BOTH, ("option-fills",)),
    Moved(f"{PAGE}::PageOptionTest::test_option_rows_fill_the_width_and_mark_the_pick_beyond_colour",
          '.btn-option[aria-pressed="true"] kbd', "background-color", BOTH, ("option-pick-key",)),
    Moved(f"{PAGE}::PageOptionTest::test_option_rows_fill_the_width_and_mark_the_pick_beyond_colour",
          ".btn-option", "color", BOTH, ("peach-only-needs",), via=PEACH_VIA),
    Moved(f"{PAGE}::PageMessageLifeTest::test_the_new_marks_are_never_peach", ".new-replies",
          "color", BOTH, ("peach-only-needs",), via=PEACH_VIA),
    Moved(f"{PAGE}::PageMessageLifeTest::test_the_new_marks_are_never_peach", ".message-new",
          "color", BOTH, ("peach-only-needs",), via=PEACH_VIA),
    Moved(f"{PAGE}::PageMessageLifeTest::test_the_owners_words_read_you_in_lavender",
          ".message-text", "color", BOTH, ("message-you-lav",)),
    Moved(f"{PAGE}::PageManagerTest::test_the_quiet_withdraw_buttons_share_the_page_button_rules",
          ".card .reason", "color", (1440,), ("reason-quiet",)),
    Moved(f"{PAGE}::PageSprintGlanceTest::test_pip_marks_differ_beyond_colour", ".pip",
          "border-top-style", (1440,), ("pips-differ",),
          via="the four marks are compared on border, radius, shadow, image and width"),
    Moved(f"{PAGE}::PageSprintGlanceTest::test_pip_marks_differ_beyond_colour", ".pip", "color",
          BOTH, ("peach-only-needs",), via=PEACH_VIA),
    Moved(f"{PAGE}::PageSprintGlanceTest::test_only_an_owner_ball_reads_as_needs_you",
          ".sprint-ball.needs", "color", (1440,), ("ball-needs",)),
    Moved(f"{PAGE}::PageSprintGlanceTest::test_only_an_owner_ball_reads_as_needs_you", ".st-go",
          "color", (1440,), ("tone-go",)),
    Moved(f"{PAGE}::PageSprintGlanceTest::test_only_an_owner_ball_reads_as_needs_you", ".st-wait",
          "color", (1440,), ("tone-wait",)),
    Moved(f"{PAGE}::PageSprintGlanceTest::test_only_an_owner_ball_reads_as_needs_you", ".st-dim",
          "color", (1440,), ("tone-dim",)),
    Moved(f"{PAGE}::AccountsPanelPageTest::test_the_panel_uses_only_the_page_tokens_and_hides_when_hidden",
          ".acct-panel[hidden]", "display", (1440,), ("accounts-hidden",)),
    Moved(f"{PAGE}::AccountsPanelPageTest::test_the_panel_uses_only_the_page_tokens_and_hides_when_hidden",
          "#accounts", "color", BOTH, ("palette-accounts",)),
    Moved(f"{PAGE}::AccountsPanelPageTest::test_the_panel_uses_only_the_page_tokens_and_hides_when_hidden",
          "#accounts", "font-size", (1440,), ("sizes-accounts",)),
    Moved(f"{PAGE}::AccountsPanelPageTest::test_the_panel_uses_only_the_page_tokens_and_hides_when_hidden",
          ":root", "--*", (1440,), ("tokens-desk",),
          via="the :root token list is read from the rendered page"),
    Moved(f"{PAGE}::PanelSigninPageTest::test_the_panel_never_draws_peach", ".acct-", "color", BOTH,
          ("peach-only-needs",), via=PEACH_VIA),
    Moved(f"{PAGE}::PageSpendFigureTest::test_the_figure_is_quiet_overlay_2_and_never_peach",
          ".spend", "color", BOTH, ("spend-quiet",)),
    Moved(f"{PAGE}::PageSpendFigureTest::test_the_figure_is_quiet_overlay_2_and_never_peach",
          ".sp-spend", "color", BOTH, ("sp-spend-quiet",)),
    Moved(f"{PAGE}::PageSpendFigureTest::test_the_figure_is_quiet_overlay_2_and_never_peach",
          ".spend", "color", BOTH, ("peach-only-needs",), via=PEACH_VIA),
    Moved("tests/test_console_controls.py::ControlStateTest::test_peach_is_only_on_the_primary_kind",
          ".btn-primary", "color", BOTH, ("peach-only-needs",), via=PEACH_VIA),
    Moved("tests/test_console_controls.py::ControlStateTest::test_peach_is_only_on_the_primary_kind",
          "body", "color", BOTH, ("palette-spend",)),
    Moved("tests/test_console_spend_page.py::SpendStaticTest::"
          "test_the_spend_page_uses_no_peach_and_only_the_desk_palette",
          "body", "color", BOTH, ("palette-spend",)),
    Moved("tests/test_console_spend_page.py::SpendStaticTest::"
          "test_the_spend_page_uses_no_peach_and_only_the_desk_palette",
          ":root", "--*", (1440,), ("tokens-spend",)),
)
GOAL = "tests/test_console_goal_box.py"
NARROW = (480,)
WIDE = (1440,)


def moved(test, selector, prop, widths, *rows, via=""):
    return Moved(test, selector, prop, widths, rows, via)


def _each(test, selector, widths, reads, via=""):
    """One entry per `(prop, rows...)` read of a selector."""
    return tuple(moved(test, selector, prop, widths, *rows, via=via) for prop, *rows in reads)


SEC_H_FONT = ("font-style", "font-weight", "font-size", "line-height", "font-family")


def _sec_h(test, selector, group, via=""):
    names = [f"{group}-{prop}" for prop in SEC_H_FONT]
    return (moved(test, selector, "font", BOTH, *names, via=via),
            moved(test, selector, "font-size", BOTH, f"{group}-font-size", via=via),
            moved(test, selector, "font-weight", BOTH, f"{group}-font-weight", via=via),
            moved(test, selector, "color", BOTH, f"{group}-color", via=via))


_NARROW_RULE = f"{PAGE}::PageTest::test_the_page_has_a_narrow_rule_for_480_wide"
_CHOOSER = f"{PAGE}::PageTest::test_the_open_chooser_stays_inside_the_viewport_and_the_panel"
_LEAD_TYPE = f"{PAGE}::PageTest::test_the_lead_headline_is_the_largest_type_after_the_statement"
_TOP_BAR = f"{PAGE}::PageTest::test_the_top_bar_fits_480_wide"
_NOTICE_BLOCKS = (f"{PAGE}::PageNoticeTest::"
                  "test_notice_blocks_stand_apart_with_the_age_at_the_end_of_the_first_line")
_NOTICE_GAP = f"{PAGE}::PageNoticeTest::test_the_post_control_stands_a_notice_gap_below_the_last_notice"
_CUT_WORD = f"{PAGE}::PageNoticeTest::test_a_cut_word_stays_on_one_line_with_an_ellipsis"
_NOTICE_WRAP = f"{PAGE}::PageNoticeTest::test_notice_words_wrap_within_the_column"
_ARROW = (f"{PAGE}::PageNoticeTest::"
          "test_the_closed_notices_fold_shows_the_reports_disclosure_arrow")
_THREAD = (f"{PAGE}::PageAskTest::"
           "test_a_thread_line_is_a_flex_row_with_an_ellipsised_first_question")
_READING_BOLD = (f"{PAGE}::PageReadingTest::"
                 "test_the_decision_readings_bold_rule_does_not_reach_the_reading_panel")
_ANSWER_SIZE = (f"{PAGE}::PageReadingFormatTest::"
                "test_the_answer_reads_at_the_size_of_a_cards_option_text")
_BREAKS = f"{PAGE}::PageReadingFormatTest::test_a_paragraph_keeps_its_line_breaks"
_BLOCKS = f"{PAGE}::PageQuestionTest::test_the_blocks_line_stays_one_line"
_HEADINGS = f"{PAGE}::PageDigestTest::test_section_headings_share_one_style"
_DIGEST = f"{PAGE}::PageDigestTest::test_each_digest_line_is_its_age_then_its_sentence"
_STRIP_NEVER = (f"{PAGE}::StripPageTest::"
                "test_at_1440_the_strip_never_shrinks_and_the_goal_placeholder_stays_one_line")
_STRIP_THREE = f"{PAGE}::StripPageTest::test_three_accounts_fit_one_line_at_1440"
_STRIP_480 = (f"{PAGE}::StripPageTest::"
              "test_at_480_only_the_summary_word_and_the_tightest_account_show")
_STRIP_DIM = f"{PAGE}::StripPageTest::test_an_excluded_accounts_bar_is_dimmed"
_FOCUS = f"{PAGE}::PageStandingRulesTest::test_the_goal_field_shows_one_border_in_focus"
_LEAD_CARD = f"{PAGE}::PageStandingRulesTest::test_the_lead_card_narrows_under_900"
_REG = f"{PAGE}::RegisterCardKeysPageTest::test_register_asks_are_set_small_enough_to_read_at_480"
_SEG = f"{PAGE}::PathWrapPageTest::test_a_segment_is_an_atomic_inline_block"
_FULL = f"{PAGE}::PathWrapPageTest::test_every_card_ask_uses_the_full_width"
_COUNT = f"{GOAL}::GoalCountTest::test_the_count_is_a_quiet_corner_label_that_takes_no_room"
_REFUSAL = (f"{GOAL}::GoalRefusalStyleTest::"
            "test_no_rule_hides_a_refusal_the_page_has_put_in_the_status_line")
PLACEHOLDER_VIA = "the placeholder is read through its ::placeholder pseudo-element"
INLINE_BLOCK_PROPS = ("display", "max-width", "overflow", "text-overflow", "white-space",
                      "vertical-align")
_FIT = "top-fit-width", "top-fit-min-width", "top-fit-flex-basis"

MOVED += (
    # The 480 rule of the top bar and the statement.
    *_each(_NARROW_RULE, ".top-in", NARROW, (("flex-wrap", "top-wrap-flex-wrap"),)),
    moved(_NARROW_RULE, ".statement h1", "font-size", NARROW, "statement-narrow-font-size"),
    # The open chooser.
    *_each(_CHOOSER, ".goal-box", BOTH, (("max-height", "goal-box-max-height"),
                                         ("overflow-y", "goal-box-overflow-y"))),
    *_each(_CHOOSER, ".goal-projects", BOTH, (
        ("min-width", "goal-projects-min-width"), ("max-width", "goal-projects-max-width"),
        ("overflow-y", "goal-projects-overflow-y"), ("flex", "goal-projects-flex"),
        ("min-height", "goal-projects-min-height"))),
    *_each(_CHOOSER, ".goal-projects li", BOTH, (
        ("min-width", "goal-projects-li-min-width"), ("max-width", "goal-projects-li-max-width"))),
    *_each(_CHOOSER, ".goal-project", BOTH, (
        ("min-width", "goal-project-min-width"), ("max-width", "goal-project-max-width"),
        ("overflow-wrap", "goal-project-overflow-wrap"))),
    moved(_CHOOSER, ".goal-filter", "min-width", BOTH, "goal-filter-min-width"),
    moved(_CHOOSER, ".goal-act", "flex", BOTH, "goal-act-flex"),
    # The lead type.
    moved(_LEAD_TYPE, ".card .q", "font-size", BOTH, "lead-type-card-font-size"),
    moved(_LEAD_TYPE, ".card .q", "font", BOTH, "lead-type-card-font"),
    moved(_LEAD_TYPE, ".reading-question", "font-size", BOTH, "lead-type-reading-font-size"),
    moved(_LEAD_TYPE, ".reading-question", "font", BOTH, "lead-type-reading-font"),
    moved(_LEAD_TYPE, ".statement h1", "font-size", BOTH, "lead-type-font-size",
          via="every rendered element's font-size is read against the lead question's 24px"),
    # The top bar at 480.
    moved(_TOP_BAR, ".top-in", "flex-wrap", NARROW, "top-wrap-flex-wrap"),
    moved(_TOP_BAR, ".goal-bar", "flex", NARROW, "goal-bar-flex-480"),
    moved(_TOP_BAR, ".goal-box", "width", BOTH, "goal-box-width-1440", "goal-box-width-480"),
    moved(_TOP_BAR, ".cap-acct b", "overflow", BOTH, "cap-acct-name-overflow"),
    moved(_TOP_BAR, ".cap-acct b", "text-overflow", BOTH, "cap-acct-name-text-overflow"),
    moved(_TOP_BAR, ".cap-acct b", "white-space", BOTH, "cap-acct-name-white-space"),
    moved(_TOP_BAR, ".cap-acct b", "max-width", BOTH, "cap-acct-name-max-width"),
    moved(_TOP_BAR, ".cap", "min-width", BOTH, "cap-min-width"),
    moved(_TOP_BAR, ".cap", "max-width", BOTH, "cap-max-width"),
    moved(_TOP_BAR, ".cap", "white-space", BOTH, "cap-white-space"),
    moved(_TOP_BAR, ".cap-acct", "max-width", BOTH, "cap-acct-max-width"),
    moved(_TOP_BAR, ".cap-acct", "white-space", BOTH, "cap-acct-white-space"),
    moved(_TOP_BAR, ".brand", "white-space", BOTH, "brand-white-space"),
    moved(_TOP_BAR, ".goal-in .goal-text::placeholder", "white-space", BOTH,
          "placeholder-white-space", via=PLACEHOLDER_VIA),
    moved(_TOP_BAR, ".nav", "white-space", BOTH, "nav-nowrap"),
    *(moved(_TOP_BAR, selector, prop, NARROW, *_FIT,
            via="no top bar rule asks for more than the 480 column: its widths are read rendered")
      for selector in (".top", ".conn", ".cap", ".goal-bar", ".nav", ".brand")
      for prop in ("width", "min-width", "flex-basis")),
    # The meter sits inside the clipped `.cap`, so no row above reads it: its own rows do.
    *(moved(_TOP_BAR, ".meter", prop, NARROW, f"top-fit-meter-{prop}",
            via="the meter sits inside the clipped `.cap`, so its own rendered value is read")
      for prop in ("width", "min-width", "flex-basis")),
    # The notices.
    moved(_NOTICE_BLOCKS, ".notice + .notice", "margin-top", BOTH, "notice-margin-top"),
    moved(_NOTICE_BLOCKS, ".notice-head", "display", BOTH, "notice-head-display"),
    moved(_NOTICE_BLOCKS, ".notice-head", "flex-wrap", BOTH, "notice-head-flex-wrap"),
    moved(_NOTICE_BLOCKS, ".notice-who", "flex", BOTH, "notice-who-flex"),
    moved(_NOTICE_BLOCKS, ".notice-who", "min-width", BOTH, "notice-who-min-width"),
    moved(_NOTICE_BLOCKS, ".notice-who", "display", BOTH, "notice-who-display"),
    moved(_NOTICE_BLOCKS, ".notice-label", "display", BOTH, "notice-label-display"),
    moved(_NOTICE_BLOCKS, ".notice-from", "display", BOTH, "notice-from-display"),
    moved(_NOTICE_BLOCKS, ".notice-head .notice-age", "margin-left", BOTH,
          "notice-age-margin-left", "notice-age-right"),
    moved(_NOTICE_BLOCKS, ".notice-head .notice-age", "flex", BOTH, "notice-age-flex"),
    moved(_NOTICE_BLOCKS, ".notice-head .notice-age", "color", BOTH, "notice-age-color"),
    moved(_NOTICE_BLOCKS, ".notice-words", "color", BOTH, "notice-words-color"),
    moved(_NOTICE_BLOCKS, ".notice code", "background", BOTH, "notice-code-background-color",
          "notice-code-background-image"),
    moved(_NOTICE_BLOCKS, ".notice code", "white-space", BOTH, "notice-code-white-space"),
    moved(_NOTICE_GAP, ".notice-open", "margin-top", BOTH, "notice-gap-open",
          via="the control is read where the page draws it, beside the last notice"),
    moved(_NOTICE_GAP, ".notice-post", "margin-top", BOTH, "notice-gap-post",
          via="the control is read where the page draws it, beside the last notice"),
    moved(_NOTICE_GAP, ".notice", "margin-top", BOTH, "notice-margin-top",
          via="the gap above the post control is read as at least the 12px between notices"),
    moved(_NOTICE_GAP, ".notice + .notice", "margin-top", BOTH, "notice-margin-top"),
    *(moved(_CUT_WORD, selector, prop, BOTH, f"{group}-{prop}")
      for selector, group in ((".notice .notice-long", "notice-long"), (".notice code", "notice-code"))
      for prop in INLINE_BLOCK_PROPS),
    moved(_NOTICE_WRAP, ".notice > *", "overflow-wrap", BOTH, "notice-child-overflow-wrap"),
    moved(_NOTICE_WRAP, ".notice > *", "min-width", BOTH, "notice-child-min-width"),
    moved(_NOTICE_WRAP, ".notices-project", "overflow-wrap", BOTH, "notices-project-overflow-wrap"),
    # The disclosure arrows, the threads and the readings.
    *(moved(_ARROW, selector, prop, BOTH, f"disclosure-{name}-{read}")
      for name, selector in (("notices", ".line.notices summary"),
                             ("finished", ".finished-list > summary"),
                             ("sprint", ".sprint-detail summary"))
      for prop, read in (("display", "display"), ("list-style", "list-style-type"),
                         ("list-style-type", "list-style-type"))),
    moved(_ARROW, ".line.notices summary::-webkit-details-marker", "display", BOTH,
          "disclosure-notices-marker-display",
          via="the marker's own display is read from the cascade, no engine resolves its style"),
    moved(_ARROW, ".notices-project", "margin-left", BOTH, "notices-project-margin-left"),
    moved(_THREAD, ".thread-open", "display", BOTH, "thread-open-display"),
    moved(_THREAD, ".thread-first", "flex", BOTH, "thread-first-flex"),
    moved(_THREAD, ".line.questions > details > summary", "display", BOTH,
          "thread-summary-display"),
    moved(_THREAD, ".line.questions > details > summary", "list-style", BOTH,
          "thread-summary-list-style-type"),
    moved(_THREAD, ".thread-first", "text-overflow", BOTH, "thread-first-text-overflow"),
    moved(_THREAD, ".thread-first", "white-space", BOTH, "thread-first-white-space"),
    moved(_READING_BOLD, "p.reading", "font-weight", BOTH, "reading-weight-call-out"),
    moved(_READING_BOLD, ".reading", "font-weight", BOTH, "reading-weight-panel",
          via="the reading panel's own weight is read, not the shared class"),
    # The answer's type and line breaks.
    moved(_ANSWER_SIZE, ".opt .ot", "font-size", BOTH, "answer-type-font-size",
          via="the answer is read against a probe wearing the card's option text"),
    moved(_ANSWER_SIZE, ".ask-answer", "font-size", BOTH, "answer-type-font-size"),
    moved(_ANSWER_SIZE, ".ask-answer p", "font-size", BOTH, "answer-type-p-font-size"),
    moved(_ANSWER_SIZE, ".ask-answer p", "font", BOTH, "answer-type-font"),
    moved(_ANSWER_SIZE, ".ask-answer li", "font-size", BOTH, "answer-type-li-font-size"),
    moved(_ANSWER_SIZE, ".ask-answer li", "font", BOTH, "answer-type-li-font"),
    *(moved(_ANSWER_SIZE, ".ask-answer .md-list", prop, BOTH, row)
      for prop, row in (("font-size", "answer-type-list-font-size"),
                        ("font", "answer-type-list-font"))),
    *(moved(_ANSWER_SIZE, f".ask-answer {kind}.md-list", prop, BOTH, f"answer-type-{kind}-{key}")
      for kind in ("ul", "ol") for prop, key in (("font-size", "font-size"), ("font", "font"))),
    moved(_BREAKS, ".ask-answer p", "white-space", BOTH, "answer-type-white-space"),
    moved(_BLOCKS, ".held.blocks", "white-space", BOTH, "held-blocks-white-space"),
    moved(_BLOCKS, ".held.blocks", "overflow", BOTH, "held-blocks-overflow"),
    moved(_BLOCKS, ".held.blocks", "text-overflow", BOTH, "held-blocks-text-overflow"),
    # The digest and the headings.
    *(moved(_DIGEST, f"{list_} li", prop, BOTH, f"digest-lines-{name}-{prop}")
      for list_, name in ((".digest", "digest"), (".earlier-list", "earlier"))
      for prop in ("display", "grid-template-columns", "flex-wrap")),
    moved(_DIGEST, ".earlier-list .more-n", "display", BOTH, "digest-lines-more-display"),
    moved(_DIGEST, ".earlier-list .more-n", "grid-column", BOTH, "digest-lines-more-grid-column"),
    *_sec_h(_HEADINGS, ".sec-h", "sec-h-work",
            via="the Work, digest and Capacity headings are each read against the one style"),
    *_sec_h(_HEADINGS, ".digest-head", "sec-h-digest"),
    *_sec_h(_HEADINGS, ".side h2", "sec-h-work", via="the Work heading is the side column's"),
    *_sec_h(_HEADINGS, "#promoted h2", "sec-h-promoted"),
    # The goal field, the lead card, the asks and the segment.
    moved(_FOCUS, ".goal-in:focus-within", "border-color", BOTH, "goal-focus-border-color",
          via="focus is forced on the goal field and its border read"),
    moved(_FOCUS, ".field-bare:focus-visible", "outline", BOTH, "goal-focus-outline",
          via="keyboard focus is forced on the goal field's text and its outline read"),
    moved(_LEAD_CARD, ".card.lead", "padding", NARROW, "lead-narrow-padding"),
    moved(_LEAD_CARD, ".card.lead", "padding-left", NARROW, "lead-narrow-padding-left"),
    moved(_LEAD_CARD, ".card.lead", "padding-right", NARROW, "lead-narrow-padding-right"),
    moved(_REG, ".card .q.reg", "font-size", NARROW, "reg-ask-font-size-480"),
    moved(_REG, ".card .q.reg", "font-size", WIDE, "reg-ask-font-size-1440"),
    moved(_REG, ".rest .q.reg", "font", BOTH, "reg-ask-rest-font", "reg-ask-rest-font-weight",
          "reg-ask-rest-font-size", "reg-ask-rest-line-height"),
    moved(_SEG, ".seg", "display", BOTH, "seg-display"),
    moved(_SEG, ".seg", "max-width", BOTH, "seg-max-width"),
    moved(_SEG, ".seg", "overflow-wrap", BOTH, "seg-overflow-wrap"),
    moved(_FULL, ".card .q", "text-wrap", BOTH, "q-full-width-text-wrap"),
    moved(_FULL, ".card .q.reg", "text-wrap", BOTH, "q-full-width-reg-text-wrap"),
    moved(_FULL, ".rest .q.reg", "text-wrap", BOTH, "q-full-width-rest-text-wrap"),
    # The goal count and the status line.
    moved(_COUNT, ".goal-count", "display", BOTH, "goal-count-closed-display"),
    moved(_COUNT, ".goal-bar.open .goal-count", "display", BOTH, "goal-count-display"),
    moved(_COUNT, ".goal-count", "position", BOTH, "goal-count-position",
          via="the count is read where it is drawn, in the open box"),
    moved(_COUNT, ".goal-count", "color", BOTH, "goal-count-color",
          via="the count is read where it is drawn, in the open box"),
    moved(_COUNT, ".goal-count.over", "color", BOTH, "goal-count-over-color"),
    moved(_COUNT, ".goal-count.near", "color", BOTH, "goal-count-near-color",
          via="there is no near colour: the near count reads the quiet one"),
    *(moved(_COUNT, selector, prop, BOTH, *rows, via=via)
      for selector, rows_for, via in (
          (".goal-count", "goal-count", "the count is read where it is drawn, in the open box"),
          (".goal-bar.open .goal-count", "goal-count", ""),
          (".goal-count.over", "goal-count-over", ""))
      for prop, rows in (("width", (f"{rows_for}-width",)),
                         ("min-width", (f"{rows_for}-min-width",)),
                         ("flex-basis", (f"{rows_for}-flex-basis",)),
                         ("white-space", (f"{rows_for}-white-space",)))),
    moved(_REFUSAL, ".goal-status:empty", "display", BOTH, "goal-status-empty-display"),
    moved(_REFUSAL, ".goal-status", "display", BOTH, "goal-status-display"),
    moved(_REFUSAL, ".goal-status", "visibility", BOTH, "goal-status-visibility"),
    moved(_REFUSAL, ".fail", "display", BOTH, "fail-shown-display"),
    moved(_REFUSAL, ".fail", "visibility", BOTH, "fail-shown-visibility"),
    # The strip.
    *(moved(_STRIP_NEVER, selector, prop, WIDE, row,
            via=PLACEHOLDER_VIA if "::" in selector else "")
      for selector, prop, row in (
          (".cap", "flex", "cap-flex"), (".cap", "overflow", "cap-overflow"),
          (".cap", "min-width", "cap-min-width"), (".cap", "max-width", "cap-max-width"),
          (".cap", "white-space", "cap-white-space"), (".cap", "flex-wrap", "cap-flex-wrap"),
          (".goal-bar", "flex", "goal-bar-flex-1440"),
          (".goal-bar", "min-width", "goal-bar-min-width-1440"),
          (".goal-bar", "max-width", "goal-bar-max-width-1440"),
          (".top-in", "flex-wrap", "top-wrap-flex-wrap"), (".top-in", "gap", "top-wrap-gap"),
          (".goal-in .goal-text::placeholder", "white-space", "placeholder-white-space"),
          (".goal-in .goal-text::placeholder", "overflow", "placeholder-overflow"),
          (".goal-in .goal-text::placeholder", "text-overflow", "placeholder-text-overflow"),
          (".goal-in .goal-text", "text-overflow", "placeholder-host-text-overflow"))),
    moved(_STRIP_NEVER, ".top-in", "gap", WIDE, "top-wrap-gap", "top-wrap-row-gap",
          "top-wrap-column-gap"),
    moved(_STRIP_NEVER, ".goal-bar", "flex", NARROW, "goal-bar-flex-480"),
    moved(_STRIP_NEVER, ".goal-bar", "max-width", NARROW, "goal-bar-max-width-480"),
    *(moved(_STRIP_THREE, ".cap", prop, WIDE, *rows)
      for prop, rows in (
          ("flex-wrap", ("cap-flex-wrap",)), ("white-space", ("cap-white-space",)),
          ("overflow", ("cap-overflow",)), ("min-width", ("cap-min-width",)),
          ("max-width", ("cap-max-width",)), ("padding", ("cap-padding",)),
          ("text-align", ("cap-text-align",)), ("cursor", ("cap-cursor",)),
          ("font-size", ("cap-font-size",)), ("color", ("cap-color",)),
          ("font", ("cap-font-style", "cap-font-weight", "cap-font-size", "cap-line-height",
                    "cap-font-family")),
          ("background", ("cap-background-color", "cap-background-image")))),
    moved(_STRIP_THREE, ".cap > *", "flex", WIDE, "cap-child-flex"),
    moved(_STRIP_THREE, ".cap-excl", "color", WIDE, "cap-excl-color"),
    moved(_STRIP_THREE, ".cap-pin-mark", "color", WIDE, "cap-pin-mark-color"),
    moved(_STRIP_480, ".cap-extra", "display", NARROW, "cap-extra-display"),
    moved(_STRIP_DIM, ".cap-excluded .meter i", "background", BOTH, "meter-excluded-background-color",
          "meter-excluded-background-image"),
    moved(_STRIP_DIM, ".meter i", "background", BOTH, "meter-fill-background-color",
          "meter-fill-background-image"),
)
_NEW_MARK = f"{PAGE}::PageMessageLifeTest::test_a_new_reply_mark_in_a_summary_is_set_off_from_the_words_before_it"
_CHECK_LINE = (f"{PAGE}::PageSprintBlockTest::"
               "test_the_check_line_wears_the_sprint_openers_look_and_keeps_a_touch_target")
_NOW_SPAN = f"{PAGE}::PageSprintGlanceTest::test_the_now_sentence_spans_the_text_columns_of_the_head_grid"
_NOW_CLAMP = f"{PAGE}::PageSprintBlockTest::test_the_now_sentence_is_clamped_to_two_lines"
_PIPS = f"{PAGE}::PageSprintGlanceTest::test_a_full_report_keeps_every_pip_and_wraps_them"
_WAIT = (f"{PAGE}::WaitingLinePageTest::"
         "test_a_sprints_wait_sits_in_the_check_list_with_the_check_lines_indent_and_gap")
_PROJECT = f"{PAGE}::PageSideColumnTest::test_a_project_is_a_block_headed_by_its_name"
_ANSWERED = f"{PAGE}::PageAnsweredRowTest::test_an_answered_row_clips_its_question_to_one_line"
_ROW_HEAD = f"{PAGE}::PageBriefRowTest::test_the_brief_row_head_keeps_the_shared_flex_layout"
_REST_HEAD = f"{PAGE}::PageBriefRowTest::test_a_register_row_head_keeps_the_flex_layout_of_a_card_head"
_ROW_TITLE = f"{PAGE}::PageBriefRowTest::test_a_collapsed_row_title_wraps_a_long_unbroken_goal"
_ROW_GAP = f"{PAGE}::PageBriefRowTest::test_the_first_row_sits_one_row_gap_below_the_card"
_DRAFT = f"{PAGE}::DraftedContractPageTest::test_change_controls_never_wrap_under_their_row"
_GALLERY = f"{PAGE}::PagePictureTest::test_the_gallery_wraps_and_the_pair_stacks_at_480"
_SHAPE = f"{PAGE}::PagePictureTest::test_a_thumbnail_follows_its_pictures_shape_up_to_a_bound"
_TINT = f"{PAGE}::PagePictureTest::test_a_thumbnails_letterbox_is_a_light_tint_of_the_card"
_PAIR_ROW = f"{PAGE}::PagePictureTest::test_the_pair_sits_in_one_row_on_a_desktop"
_VIEWER_PAIR = f"{PAGE}::PageViewerTest::test_the_viewer_pair_is_a_row_and_stacks_at_480"
_VIEWER_TOP = f"{PAGE}::PageViewerTest::test_the_viewer_shows_its_pictures_at_the_top_of_the_stage"
_VIEWER_OPAQUE = (f"{PAGE}::PageViewerTest::"
                  "test_the_viewer_is_opaque_and_the_page_behind_it_does_not_scroll")
_VIEWER_ARROWS = f"{PAGE}::PageViewerTest::test_arrows_move_the_picture_and_leave_focus_where_it_is"
_VIEWER_BAR = f"{PAGE}::PageViewerTest::test_the_viewer_controls_share_one_bar_that_stays_in_view"

MOVED += (
    # The new-reply mark, the check line and the wait line.
    moved(_NEW_MARK, ".finished-list > summary .message-new", "margin-left", WIDE,
          "new-mark-gap-finished"),
    moved(_NEW_MARK, ".sprint-earlier summary .message-new", "margin-left", WIDE,
          "new-mark-gap-earlier"),
    moved(_CHECK_LINE, ".sprint-check", "color", BOTH, "check-line-color"),
    moved(_CHECK_LINE, ".sprint-detail summary", "color", BOTH, "check-line-color",
          via="the opener's colour is what the check line is read against"),
    moved(_CHECK_LINE, ".sprint-check", "cursor", BOTH, "check-line-cursor"),
    moved(_CHECK_LINE, ".sprint-detail summary", "cursor", BOTH, "check-line-cursor",
          via="the opener's cursor is what the check line is read against"),
    moved(_CHECK_LINE, ".sprint-check", "font-size", BOTH, "check-line-font-size"),
    moved(_CHECK_LINE, ".sprint-detail", "font-size", BOTH, "check-line-font-size",
          via="the sprint block's size is what the check line is read against"),
    moved(_CHECK_LINE, ".sprint-check", "text-decoration", BOTH, "check-line-text-decoration-line"),
    moved(_CHECK_LINE, ".sprint-check", "min-height", WIDE, "check-line-min-height-1440"),
    moved(_CHECK_LINE, ".sprint-check", "min-height", NARROW, "check-line-min-height-480"),
    moved(_CHECK_LINE, ".sprint-check", "display", NARROW, "check-line-display-480"),
    moved(_CHECK_LINE, ".sprint-check", "align-items", NARROW, "check-line-align-items-480"),
    moved(_CHECK_LINE, ".sprint-check", "flex", NARROW, "check-line-display-480",
          via="the literal flex is the display value the row wants"),
    moved(_CHECK_LINE, ".sprint-checks", "padding", BOTH, "check-line-list-padding"),
    moved(_WAIT, ".sprint-checks", "padding", BOTH, "check-line-list-padding"),
    moved(_WAIT, ".sprint-checks .wait", "margin", BOTH, "wait-line-margin"),
    moved(_WAIT, ".sprint-checks .wait", "padding", BOTH, "wait-line-padding"),
    moved(_WAIT, ".sprint-check", "padding", BOTH, "wait-line-padding",
          via="the check line's padding is what the wait line is read against"),
    moved(_WAIT, ".sprint-checks .wait", "font-size", BOTH, "wait-line-font-size"),
    moved(_WAIT, ".sprint-check", "font-size", BOTH, "wait-line-font-size",
          via="the check line's size is what the wait line is read against"),
    moved(_WAIT, ".sprint-checks .wait", "min-height", NARROW, "wait-line-min-height-480",
          "wait-line-min-height-same-480"),
    moved(_WAIT, ".sprint-check", "min-height", NARROW, "wait-line-min-height-same-480",
          via="the check line's height is what the wait line is read against"),
    # The now sentence and the head grid.
    moved(_NOW_SPAN, ".sp-now", "grid-column", BOTH, "now-sentence-column-start",
          "now-sentence-column-end"),
    moved(_NOW_CLAMP, ".sp-now", "grid-column", BOTH, "now-sentence-column-start",
          "now-sentence-column-end"),
    moved(_NOW_CLAMP, ".sp-now", "display", BOTH, "now-sentence-display"),
    moved(_NOW_CLAMP, ".sp-now", "-webkit-box-orient", BOTH, "now-sentence-box-orient"),
    moved(_NOW_CLAMP, ".sp-now", "-webkit-line-clamp", BOTH, "now-sentence-line-clamp"),
    moved(_NOW_CLAMP, ".sp-now", "overflow", BOTH, "now-sentence-overflow-y"),
    moved(_PIPS, ".pips", "flex-wrap", BOTH, "pips-wrap-flex-wrap"),
    moved(_PIPS, ".pips", "white-space", BOTH, "pips-wrap-pips-white-space"),
    moved(_PIPS, ".sp-prog", "white-space", BOTH, "pips-wrap-prog-white-space"),
    moved(_PIPS, ".sp-head", "grid-template-columns", BOTH, "pips-wrap-columns",
          "pips-wrap-columns-max"),
    moved(_PROJECT, "#list > li.line + li.line", "border-top", BOTH, "project-block-border-color",
          "project-block-border-width",
          via="the blocks the rule draws are read, not the after-line ones it removes it from"),
    moved(_PROJECT, ".pname", "font-weight", BOTH, "project-block-pname-weight"),
    # The brief rows, the register head and the answered rows.
    moved(_ROW_HEAD, ".row-head", "display", WIDE, "row-head-display"),
    moved(_ROW_HEAD, ".brief-row > summary", "display", WIDE, "row-head-summary-display"),
    moved(_ROW_HEAD, ".row-head", "flex", WIDE, "row-head-display", "row-head-summary-display",
          via="the literal flex is the display value the row wants"),
    moved(_REST_HEAD, ".rest .head", "display", WIDE, "rest-head-display"),
    moved(_REST_HEAD, ".card .head", "display", WIDE, "rest-head-display",
          via="the card head is what the register head is read against"),
    moved(_REST_HEAD, ".rest .head", "column-gap", WIDE, "rest-head-column-gap"),
    moved(_REST_HEAD, ".rest .head", "align-items", WIDE, "rest-head-align-items"),
    moved(_REST_HEAD, ".rest .head", "flex", WIDE, "rest-head-display",
          via="the literal flex is the display value the row wants"),
    moved(_REST_HEAD, ".head .wait", "margin-left", WIDE, "rest-head-wait-margin-left",
          "rest-head-wait-right"),
    moved(_ROW_TITLE, ".row-head b", "overflow-wrap", WIDE, "row-head-b-overflow-wrap"),
    moved(_ROW_GAP, ".brief-row", "padding-top", WIDE, "row-gap-padding-top",
          "row-gap-padding-top-same"),
    moved(_ROW_GAP, ".brief-row", "padding-bottom", WIDE, "row-gap-padding-bottom",
          "row-gap-padding-bottom-same"),
    moved(_ROW_GAP, ".brief-row", "padding-left", WIDE, "row-gap-padding-left",
          "row-gap-padding-left-same"),
    moved(_ROW_GAP, ".brief-row", "padding-right", WIDE, "row-gap-padding-right",
          "row-gap-padding-right-same"),
    moved(_ROW_GAP, ".rest > li.row", "padding", WIDE, "row-gap-padding-top-same",
          "row-gap-padding-bottom-same", "row-gap-padding-left-same", "row-gap-padding-right-same",
          via="the registration row's padding is what the brief row is read against"),
    moved(_ROW_GAP, ".card.lead + .brief-row", "margin-top", WIDE, "row-gap-lead-brief-margin-top"),
    moved(_ROW_GAP, ".card.lead + .rest", "margin-top", WIDE, "row-gap-lead-rest-margin-top"),
    moved(_ROW_GAP, ".brief-row + .brief-row", "border-top", WIDE, "row-gap-brief-border-color"),
    *(moved(_ANSWERED, selector, prop, BOTH, f"answered-row-{name}-{key}")
      for selector, name in ((".done-item summary > b", "b"), (".done-item summary > span", "span"))
      for prop, key in (("white-space", "white-space"), ("overflow", "overflow"),
                        ("text-overflow", "text-overflow"), ("min-width", "min-width"))),
    moved(_ANSWERED, ".done-item summary > b", "flex", BOTH, "answered-row-b-flex-grow",
          "answered-row-b-flex-shrink"),
    moved(_ANSWERED, ".done-item summary > span", "flex", BOTH, "answered-row-span-flex-grow",
          "answered-row-span-flex-shrink"),
    moved(_ANSWERED, ".done-item summary", "flex-wrap", BOTH, "answered-row-summary-flex-wrap"),
    moved(_ANSWERED, ".done-item", "min-width", BOTH, "answered-row-item-min-width"),
    moved(_DRAFT, ".register-draft li", "display", WIDE, "draft-row-display"),
    moved(_DRAFT, ".register-draft li", "grid-template-columns", WIDE, "draft-row-columns"),
    moved(_DRAFT, ".draft-change", "white-space", WIDE, "draft-row-change-white-space"),
    # The pictures and the viewer.
    moved(_GALLERY, ".pics", "flex-wrap", BOTH, "pics-flex-wrap"),
    moved(_GALLERY, ".pic", "min-width", BOTH, "pics-pic-min-width"),
    moved(_GALLERY, ".pic", "max-width", BOTH, "pics-pic-max-width"),
    moved(_GALLERY, ".pic-pair", "min-width", BOTH, "pics-pair-min-width"),
    moved(_GALLERY, ".pic-pair", "max-width", BOTH, "pics-pair-max-width"),
    moved(_GALLERY, ".pic-line", "overflow-wrap", BOTH, "pics-line-overflow-wrap"),
    moved(_GALLERY, ".pic-pair", "flex-direction", NARROW, "pics-pair-direction-480"),
    moved(_SHAPE, ".pic-thumb img", "width", BOTH, "thumb-width"),
    moved(_SHAPE, ".pic-thumb img", "height", BOTH, "thumb-height"),
    moved(_SHAPE, ".pic-thumb img", "object-fit", BOTH, "thumb-object-fit"),
    moved(_SHAPE, ".pic-thumb img", "max-height", WIDE, "thumb-max-height-1440"),
    moved(_SHAPE, ".pic-thumb img", "max-height", NARROW, "thumb-max-height-480"),
    moved(_SHAPE, ".pic-pair", "align-items", WIDE, "pics-pair-align-items-1440"),
    moved(_SHAPE, ".pic-pair", "align-items", NARROW, "pics-pair-align-items-480"),
    *(moved(_TINT, selector, "background", BOTH, *names)
      for selector, names in ((".pic-thumb", ("thumb-background-color", "thumb-background-image")),
                              (".pic-thumb img", ("thumb-img-background-color",
                                                  "thumb-img-background-image")))),
    moved(_PAIR_ROW, ".pic-pair", "display", WIDE, "pics-pair-display-1440"),
    moved(_PAIR_ROW, ".pic-pair", "flex-direction", (1440, 1180, 900), "pics-pair-direction-1440",
          "pics-pair-direction-1180", "pics-pair-direction-900"),
    moved(_PAIR_ROW, ".pic-pair .pic", "flex", WIDE, "pics-pair-pic-flex-1440"),
    moved(_VIEWER_PAIR, ".viewer-pair", "display", BOTH, "viewer-pair-display"),
    moved(_VIEWER_PAIR, ".viewer-pair", "flex", BOTH, "viewer-pair-display",
          via="the literal flex is the display value the row wants"),
    moved(_VIEWER_PAIR, ".viewer-pair", "flex-direction", WIDE, "viewer-pair-direction-1440"),
    moved(_VIEWER_PAIR, ".viewer-pair", "flex-direction", NARROW, "viewer-pair-direction-480"),
    moved(_VIEWER_PAIR, ".viewer img", "max-width", BOTH, "viewer-img-max-width"),
    moved(_VIEWER_PAIR, ".viewer img", "object-fit", BOTH, "viewer-img-object-fit"),
    moved(_VIEWER_TOP, ".viewer-stage", "align-items", BOTH, "viewer-stage-align-items"),
    moved(_VIEWER_TOP, ".viewer-stage > *", "margin", BOTH, "viewer-stage-child-margin-top"),
    *(moved(_VIEWER_OPAQUE, selector, "background", BOTH, *names)
      for selector, names in ((".viewer", ("viewer-background-color", "viewer-background-image")),
                              (".viewer-bar", ("viewer-bar-background-color",
                                               "viewer-bar-background-image")))),
    moved(_VIEWER_OPAQUE, ":root", "--*", WIDE, "tokens-desk",
          via="the viewer's fills are read as the page's palette colours"),
    moved(_VIEWER_OPAQUE, "html:has(#viewer:not([hidden]))", "overflow", BOTH,
          "viewer-html-overflow-y", via="the page behind the open viewer is read on html"),
    moved(_VIEWER_ARROWS, ".viewer:focus-visible", "outline", BOTH, "viewer-focus-outline",
          "viewer-focus-outline-style", via="keyboard focus is forced on the viewer and its outline read"),
    moved(_VIEWER_BAR, ".viewer-bar", "display", BOTH, "viewer-bar-display"),
    moved(_VIEWER_BAR, ".viewer-bar", "flex-direction", BOTH, "viewer-bar-direction"),
    moved(_VIEWER_BAR, ".viewer-bar", "flex-wrap", BOTH, "viewer-bar-wrap"),
    moved(_VIEWER_BAR, ".viewer-bar", "flex", BOTH, "viewer-bar-flex"),
    moved(_VIEWER_BAR, ".viewer", "display", BOTH, "viewer-display"),
    moved(_VIEWER_BAR, ".viewer", "flex-direction", BOTH, "viewer-direction"),
    moved(_VIEWER_BAR, ".viewer", "overflow", BOTH, "viewer-overflow-y"),
    moved(_VIEWER_BAR, ".viewer", "overflow-y", BOTH, "viewer-overflow-y"),
    moved(_VIEWER_BAR, ".viewer-stage", "overflow", BOTH, "viewer-stage-overflow-y"),
    moved(_VIEWER_BAR, ".viewer-bar button", "min-height", NARROW, "viewer-bar-button-min-height-480"),
)
CONTROLS = "tests/test_console_controls.py"
SPEND_PAGE = "tests/test_console_spend_page.py"
_DECLARED = f"{CONTROLS}::ControlStyleTest::test_the_kinds_are_declared_once_in_the_controls_block"
_SHARED = f"{CONTROLS}::ControlStyleTest::test_both_pages_share_one_controls_block"
_REDUCED = f"{CONTROLS}::ControlStyleTest::test_both_pages_turn_motion_off_under_reduced_motion"
_OWNS = f"{CONTROLS}::ControlStyleTest::test_kind_rules_own_the_control_look"
_FLOOR = f"{CONTROLS}::ControlStyleTest::test_no_rule_shrinks_a_control_below_32_px"
_FLOOR_SPEND = f"{CONTROLS}::ControlStyleTest::test_the_height_floor_gate_sees_a_later_spend_rule"
_DISABLED = (f"{CONTROLS}::ControlStateTest::"
             "test_disabled_and_busy_carry_an_attribute_and_a_non_colour_cue")
_HOVER = f"{CONTROLS}::ControlStateTest::test_hover_is_shared_by_both_pages"
_RING = f"{CONTROLS}::ControlStateTest::test_every_kind_shows_the_lavender_ring_on_keyboard_focus"
_PRESSED = f"{CONTROLS}::ControlStateTest::test_pressed_is_an_attribute_with_a_non_colour_cue"
_PLACEHOLDERS = (f"{CONTROLS}::ControlLabelTest::"
                 "test_placeholders_meet_4_5_to_1_against_their_field")
_WCAG = f"{CONTROLS}::ControlLabelTest::test_contrast_matches_the_wcag_formula"
_PRIMARY = f"{PAGE}::PageCardTest::test_the_primary_style_outranks_the_button_base_rules"
_PAGE_MOTION = f"{PAGE}::PageStandingRulesTest::test_motion_is_off_under_reduced_motion"
_SPEND_FIT = f"{SPEND_PAGE}::SpendStaticTest::test_the_spend_page_fits_480_wide"
_BTNS = ("btn-primary", "btn-quiet", "btn-danger", "btn-option")
_FIELDS = ("field-line", "field-area", "field-code")
_SPLIT = {("btn-primary", "background-color"), ("btn-primary", "border-color"),
          ("btn-primary", "color"), ("btn-danger", "color")}
_LOOK_GROUPS = {
    "font": ("font-style", "font-weight", "font-size", "line-height", "font-family"),
    "background": ("background-color", "background-image"),
    "border": ("border-width", "border-style", "border-color"),
    "transition": ("transition-property", "transition-duration"),
    "text-decoration": ("text-decoration-line",),
}


def kind_rows(kind, *props):
    """The kind rows reading `props` of `kind`; a prop the desk page holds differently has two."""
    names = []
    for prop in props:
        if (kind, prop) in _SPLIT:
            names += [f"kind-{kind}-{prop}-desk", f"kind-{kind}-{prop}-spend"]
        else:
            names.append(f"kind-{kind}-{prop}")
    return tuple(names)


def kind_entries(test, kind, props):
    """One entry per declared property of a kind, a group read by its longhands."""
    return tuple(
        moved(test, f".{kind}", prop, BOTH, *kind_rows(kind, *_LOOK_GROUPS.get(prop, (prop,))))
        for prop in props)


_BUTTON_PROPS = ("display", "align-items", "gap", "min-height", "padding", "font", "text-align",
                 "text-decoration", "color", "background", "border", "border-radius", "cursor",
                 "transition")
_FIELD_PROPS = ("min-height", "padding", "font", "color", "background", "border", "border-radius")
_HOVER_ROWS = tuple(f"hover-{kind}-{prop}" for kind in ("btn-quiet", "btn-danger", "btn-option")
                    for prop in ("background-color", "border-color", "background-image"))
_RING_PROPS = ("outline-style", "outline-width", "outline-color", "outline-offset", "border-radius")
_MOTION_ROWS = {prop: tuple(f"motion-{mode}-{prop}{where}" for mode in ("reduced", "normal")
                            for where in ("", "-before", "-after"))
                for prop in ("transition-duration", "animation-duration")}
_FORCED_FOCUS = "keyboard focus is forced on a specimen of the kind and its ring read"
_PLACEHOLDER_VIA = "the placeholder is read through its ::placeholder pseudo-element"

MOVED += (
    # The kinds, each declared once in the shared controls block.
    *kind_entries(_DECLARED, "btn-primary", _BUTTON_PROPS + ("font-weight",)),
    *kind_entries(_DECLARED, "btn-quiet", _BUTTON_PROPS),
    *kind_entries(_DECLARED, "btn-danger", _BUTTON_PROPS),
    *kind_entries(_DECLARED, "btn-option", _BUTTON_PROPS + ("column-gap", "width", "border-color")),
    moved(_DECLARED, ".btn-option", "grid-template-columns", BOTH, "kind-btn-option-grid",
          "kind-btn-option-grid-tracks"),
    moved(_DECLARED, ".btn-option", "transition", BOTH, *kind_rows("btn-option",
                                                              "transition-property",
                                                              "transition-duration")),
    *kind_entries(_DECLARED, "field-line", _FIELD_PROPS),
    *kind_entries(_DECLARED, "field-area", _FIELD_PROPS + ("display", "width", "resize")),
    *kind_entries(_DECLARED, "field-code", _FIELD_PROPS + ("letter-spacing", "font-family")),
    moved(_DECLARED, ".btn-bare", "padding", BOTH, "bare-btn-quiet-padding",
          via="the bare modifier is read on a bare quiet button"),
    moved(_DECLARED, ".field-bare", "padding-left", BOTH, "bare-field-line-padding-left",
          via="the bare modifier is read on a bare line field"),
    *(moved(_DECLARED, ".btn-bare", prop, BOTH, f"bare-btn-quiet-{prop}",
            via="the bare modifier is read on a bare quiet button")
      for prop in ("border-color", "background-color")),
    *(moved(_DECLARED, ".field-bare", prop, BOTH, f"bare-field-line-{prop}",
            via="the bare modifier is read on a bare line field")
      for prop in ("padding-right", "background-color", "border-color")),
    moved(_DECLARED, ":root", "--*", WIDE, "tokens-desk",
          via="the --hover token is read by the page tokens check"),
    moved(_DECLARED, ".btn-primary", "min-height", BOTH, "kind-look",
          via="every control on the page is compared with a bare element of its kind"),
    # The two pages share one controls block, and the spend page has no desk addendum.
    *(moved(_SHARED, f".{kind}", prop, BOTH, *kind_rows(kind, prop))
      for kind in _BTNS + _FIELDS for prop in ("min-height", "padding", "border-radius")),
    *(moved(_SHARED, ".btn-primary", prop, BOTH, f"kind-btn-primary-{prop}-spend")
      for prop in ("background-color", "border-color", "color")),
    moved(_SHARED, ":root", "--*", WIDE, "tokens-spend",
          via="the spend page's --hover token is read by the page tokens check"),
    # Motion is off under reduced motion on both pages.
    *(moved(_REDUCED, selector, prop, WIDE, *_MOTION_ROWS[prop],
            via="the rules are read on a specimen that moves without them")
      for selector in ("*", "*::before", "*::after")
      for prop in ("transition-duration", "animation-duration")),
    *(moved(_PAGE_MOTION, "*", prop, WIDE, *_MOTION_ROWS[prop],
            via="the rules are read on a specimen that moves without them")
      for prop in ("transition-duration", "animation-duration")),
    # A kind rule owns the control look: every control is read against a bare element of its kind.
    moved(_OWNS, ".picked", "min-height", BOTH, "kind-look",
          via="a control in the picked state is skipped, and the pressed rows read it"),
    moved(_OWNS, ".btn-primary", "min-height", BOTH, "kind-look",
          via="every control on the page is compared with a bare element of its kind"),
    moved(_OWNS, ".btn-primary", "height", BOTH, "kind-height-floor",
          via="a control under 32px is read on the page, not in a rule"),
    # No rule shrinks a control below 32px.
    *(moved(_FLOOR, f".{kind}", "min-height", BOTH, *kind_rows(kind, "min-height"), "kind-look")
      for kind in _BTNS + _FIELDS),
    moved(_FLOOR, ".btn-quiet", "height", BOTH, "kind-height-floor",
          via="every control of every state is read for a height under 32px"),
    moved(_FLOOR_SPEND, ".span", "min-height", BOTH, "kind-btn-quiet-min-height", "kind-look",
          via="the kind rows read the spend page, and the desk controls are read for 32px"),
    # Disabled and busy.
    *(moved(_DISABLED, f".{kind}", prop, BOTH, *(
        f"disabled-{kind}-{prop}-desk", f"disabled-{kind}-{prop}-spend")
              if kind == "btn-primary" and prop == "border-color" else (f"disabled-{kind}-{prop}",))
      for kind in _BTNS + _FIELDS for prop in ("border-width", "border-style", "border-color",
                                                "cursor", "opacity")),
    *(moved(_DISABLED, f".{kind}", prop, BOTH, f"busy-{kind}-{prop}")
      for kind in _BTNS + _FIELDS for prop in ("border-width", "border-style", "cursor")),
    *(moved(_DISABLED, f".{kind}", "content", BOTH, f"busy-{kind}-content",
            via="the ::after of a busy control is read through its pseudo-element")
      for kind in ("btn-primary", "btn-quiet", "btn-danger")),
    *(moved(_DISABLED, ".btn-primary", prop, WIDE + NARROW, f"disabled-btn-primary-{prop}-desk",
            via="the desk addendum's disabled primary is read on a disabled primary")
      for prop in ("background-color", "color")),
    # Hover is shared by both pages.
    *(moved(_HOVER, f".{kind}", "background", BOTH, f"hover-{kind}-background-color",
            f"hover-{kind}-background-image") for kind in ("btn-quiet", "btn-danger", "btn-option")),
    *(moved(_HOVER, f".{kind}", "border-color", BOTH, f"hover-{kind}-border-color")
      for kind in ("btn-quiet", "btn-danger", "btn-option")),
    moved(_HOVER, ".btn-quiet.btn-bare", "border-color", BOTH, "hover-btn-quiet-bare-border-color"),
    moved(_HOVER, ".btn-primary", "background", BOTH, "hover-btn-primary-background-color-desk",
          "kind-btn-primary-background-image", via="the desk addendum's primary hover is forced"),
    moved(_HOVER, ".btn-primary", "border-color", BOTH, "hover-btn-primary-border-color-desk",
          via="the desk addendum's primary hover is forced"),
    moved(_HOVER, ":root", "--*", WIDE, "tokens-desk", "tokens-spend",
          via="the --hover token is read by the page tokens check"),
    *(moved(_HOVER, ".btn-quiet", prop, BOTH, f"hover-disabled-btn-quiet-{prop}",
            via=f"a disabled control is forced to hover and its {prop} read")
      for prop in ("background-color", "border-style")),
    # The lavender ring on keyboard focus.
    *(moved(_RING, f".{kind}:focus-visible", "outline", BOTH,
            *(f"ring-{kind}-{prop}" for prop in _RING_PROPS[:3]), via=_FORCED_FOCUS)
      for kind in _BTNS + _FIELDS),
    *(moved(_RING, f".{kind}:focus-visible", prop, BOTH, f"ring-{kind}-{prop}", via=_FORCED_FOCUS)
      for kind in _BTNS + _FIELDS for prop in _RING_PROPS[3:]),
    moved(_RING, ".field-bare:focus-visible", "outline-style", BOTH, "ring-field-bare-outline-style",
          via=_FORCED_FOCUS),
    moved(_RING, ":focus-visible", "outline-style", BOTH, "ring-every-outline-style",
          via="every control is forced to keyboard focus and its outline read"),
    moved(_RING, ".viewer", "outline-style", BOTH, "ring-every-outline-style",
          via="every control but a bare field and the viewer is forced to keyboard focus"),
    # Pressed is an attribute with a non-colour cue.
    *(moved(_PRESSED, f".{kind}:active", "transform", BOTH, f"pressed-{kind}-transform",
            via="the press is forced on a specimen of the kind and its transform read")
      for kind in _BTNS),
    moved(_PRESSED, ".btn-option", "background-color", BOTH, "pressed-btn-option-background-color-desk",
          via="the desk addendum's pressed option tint is read on a pressed option"),
    *(moved(_PRESSED, f".{kind}", prop, BOTH, f"pressed-{kind}-{prop}")
      for kind in _BTNS for prop in ("border-color", "font-weight")),
    # The placeholder meets 4.5 to 1, and the formula.
    *(moved(_PLACEHOLDERS, f".{kind}::placeholder", prop, BOTH,
            f"placeholder-{kind}-{'color' if prop == 'color' else prop}", via=_PLACEHOLDER_VIA)
      for kind in _FIELDS for prop in ("opacity", "color")),
    *(moved(_PLACEHOLDERS, f".{kind}", "background", BOTH, f"placeholder-{kind}-contrast",
            *kind_rows(kind, "background-color", "background-image"),
            via="the contrast is read against the field's painted background")
      for kind in _FIELDS),
    moved(_PLACEHOLDERS, ".goal-bar.open .goal-in", "background", BOTH, "placeholder-goal-contrast",
          "placeholder-goal-background-color", "placeholder-goal-background-image",
          via="the contrast is read against the goal field's painted background"),
    moved(_WCAG, ".field-line::placeholder", "color", BOTH, "placeholder-field-line-contrast",
          via="the formula is pinned by the contrast want kind's Chromium test"),
    # The primary style outranks the button base rules.
    moved(_PRIMARY, ".btn-primary", "color", BOTH, "kind-btn-primary-color-desk",
          "primary-real-color", via="the primary is read as painted on the card"),
    moved(_PRIMARY, ".btn-primary", "background", BOTH, "kind-btn-primary-background-color-desk",
          "kind-btn-primary-background-image", "primary-real-background-color",
          via="the primary is read as painted on the card"),
    moved(_PRIMARY, ".btn-primary", "border-color", BOTH, "kind-btn-primary-border-color-desk",
          "primary-real-border-color", via="the primary is read as painted on the card"),
    # The spend page fits 480 wide.
    moved(_SPEND_FIT, ".top-in", "flex-wrap", NARROW, "spend-fit-top-wrap"),
    moved(_SPEND_FIT, ".trend-day", "min-width", NARROW, "spend-fit-trend-min-width"),
    moved(_SPEND_FIT, ".row-name", "overflow-wrap", NARROW, "spend-fit-row-name-wrap"),
    moved(_SPEND_FIT, "#summary", "width", NARROW, "spend-fit-width",
          via="every width the page declares is read as drawn at 480"),
    moved(_SPEND_FIT, ".figure", "min-width", NARROW, "spend-fit-min-width",
          via="every min-width the page declares is read as drawn at 480"),
    moved(_SPEND_FIT, ".trend-day", "flex-basis", NARROW, "spend-fit-flex-basis",
          via="every flex-basis the page declares is read as drawn at 480"),
)
_TICK = f"{CONTROLS}::ControlStyleTest::test_the_consent_tick_is_at_least_32_px_in_both_directions"
MOVED += (
    moved(_TICK, ".guest-tick", "width", BOTH, "guest-tick-width"),
    moved(_TICK, ".guest-tick", "height", BOTH, "guest-tick-height"),
)
GUEST_PAGE = "tests/test_console_guest_page.py"
_GUEST_HIDE = (f"{GUEST_PAGE}::GuestPageTest::"
               "test_the_guest_bytes_hide_the_owner_header_before_the_script")
MOVED += (moved(_GUEST_HIDE, ".top-in > [hidden]", "display", BOTH, "guest-top-hidden-display"),)
STRIPPED: frozenset[str] = frozenset({
    f"{PAGE}::PageTest::test_runs_are_never_peach_or_red_and_never_stalled",
    f"{PAGE}::CapacityPageTest::test_every_account_out_reads_out_in_red_and_when_work_resumes",
    f"{PAGE}::PageNoticeTest::test_the_notices_fold_uses_no_peach_and_no_new_colour",
    f"{PAGE}::PageMessageLifeTest::test_the_owners_words_read_you_in_lavender",
    f"{PAGE}::PageSprintGlanceTest::test_only_an_owner_ball_reads_as_needs_you",
    f"{PAGE}::PanelSigninPageTest::test_the_panel_never_draws_peach",
    f"{PAGE}::PageSpendFigureTest::test_the_figure_is_quiet_overlay_2_and_never_peach",
    "tests/test_console_controls.py::ControlStateTest::test_peach_is_only_on_the_primary_kind",
    _TOP_BAR, _ARROW, _BREAKS, _BLOCKS, _HEADINGS, _DIGEST, _STRIP_THREE, _STRIP_480, _STRIP_DIM,
    _NOW_CLAMP, _PIPS, _WAIT, _PROJECT, _ANSWERED, _VIEWER_ARROWS, _VIEWER_BAR, _PRESSED,
    _GUEST_HIDE,
})
RENAMED: dict[str, str] = {
    f"{PAGE}::PageTest::test_runs_are_never_peach_or_red_and_never_stalled":
        "test_the_page_never_says_stalled",
}
LONGHANDS = {
    "font": ("font-style", "font-weight", "font-size", "line-height", "font-family"),
    "background": ("background-color", "background-image"),
    "border-top": ("border-top-color",),
    "flex": ("flex-grow", "flex-shrink"),
    "grid-column": ("grid-column-start", "grid-column-end"),
    "line-clamp": ("-webkit-line-clamp",),
    "margin": ("margin-top",),
    "overflow": ("overflow-y",),
    "padding": ("padding-top", "padding-bottom"),
    "transition": ("transition-property", "transition-duration"),
    "text-decoration": ("text-decoration-line",),
    "list-style": ("list-style-type",),
    "border": ("border-width", "border-style", "border-color"),
    "outline": ("outline-style", "outline-width", "outline-color"),
}
SOURCE_READING = re.compile(
    r"style_rules|css_rules|css_decls|css_declared|page_css|media_block|margin_top_at|"
    r"fold_colour_faults|PAGE_TEXT|PAGE\.read_text|SPEND\.read_text|<style>|base_rules|rules_of|"
    r"controls_block|desk_block|outside_blocks|page_style|spend_style|short_rules|decls_of|"
    r"kind_owned|self\.style\b|"
    r"\{ ?-?[a-z]+(?:-[a-z]+)*: [^{};]+; ?\}")


def uncovered(moved, rows) -> list[str]:
    """Name each moved property, at each width, that no style row reads."""
    by_name = {row.name: row for row in rows}
    misses = []
    for entry in moved:
        absent = [f"{entry.test}: no row {name}" for name in entry.rows if name not in by_name]
        if absent:
            misses += absent
            continue
        counting = [
            by_name[name] for name in entry.rows
            if entry.via or entry.selector == by_name[name].selector
            or entry.selector in [part.strip() for part in by_name[name].selector.split(",")]]
        required = ((entry.prop,) if entry.prop not in LONGHANDS
                    or any(row.prop == entry.prop for row in counting) else LONGHANDS[entry.prop])
        # A literal that is the value a listed row wants (`"flex"` for a `display`) is read there.
        valued = {width for row in counting if entry.via and row.want == "equals"
                  and row.value == entry.prop for width in row.widths}
        if valued:
            required = (entry.prop,)
        for prop in required:
            seen = {width for row in counting if row.prop == prop for width in row.widths} | valued
            if not set(entry.widths) <= seen:
                misses.append(f"{entry.test} {entry.selector} {entry.prop} @{entry.widths}: "
                              "no row reads it")
                break
    return misses


class ScreenshotFixtureTest(unittest.TestCase):
    def test_the_set_is_fifty_seven_states_at_two_widths(self) -> None:
        self.assertEqual(len(shots.STATES), 57)
        self.assertEqual(shots.STATES[shots.STATES.index("manager-cannot-hear") + 1:][:5],
                         ("permission-stale", "permission-card", "waiting-until", "paused",
                          "owner-check"))
        self.assertEqual(shots.STATES[shots.STATES.index("notice-post-open") + 1], "live-fault")
        self.assertEqual(shots.STATES[-8:], ("sharing-panel", "sharing-off", "sharing-unreadable",
                                             "sharing-reached", "guest-page", "guest-steer",
                                             "owner-actors", "owner-accounts"))
        self.assertIn("guest-steer", shots.SHARING_STATES)
        self.assertEqual(shots.STATES.index("manager-cannot-hear"),
                         shots.STATES.index("waiting-its-turn") + 1)
        self.assertEqual(shots.STATES[shots.STATES.index("manager-cannot-hear") + 1:][:2],
                         ("permission-stale", "permission-card"))
        self.assertEqual(shots.STATES[shots.STATES.index("inbox-card"):][:3],
                         ("inbox-card", "question-words", "question-refused"))
        self.assertEqual(shots.STATES.index("waiting-its-turn"),
                         shots.STATES.index("nothing-running") + 1)
        self.assertEqual(shots.STATES.index("failed-start"),
                         shots.STATES.index("desk-spend") + 1)
        self.assertEqual(shots.STATES[shots.STATES.index("register-draft") + 1:][:2],
                         ("register-reconcile-apply", "register-reconcile-draft"))
        self.assertEqual(shots.STATES[shots.STATES.index("register-reconcile-draft") + 1:][:2],
                         ("adoption-merge", "adoption-moved"))
        self.assertEqual(shots.STATES[shots.STATES.index("adoption-moved") + 1],
                         "adoption-failed")
        self.assertEqual(shots.ADOPTION_STATES, ("adoption-merge", "adoption-moved", "adoption-failed"))
        self.assertEqual(shots.STATES[-34:-8], ("goal-open", "goal-near", "goal-over", "inbox-card",
                                              "question-words", "question-refused",
                                              "look-card", "look-moved", "look-failed",
                                              "accounts-panel", "ask-box", "questions-closed",
                                              "questions-open", "ask-goal", "question-read",
                                              "deeper-offer", "deeper-answer",
                                              "activation-tooling", "activation-host",
                                              "register-apply", "register-draft",
                                              "register-reconcile-apply",
                                              "register-reconcile-draft",
                                              "adoption-merge", "adoption-moved",
                                              "adoption-failed"))
        self.assertEqual(shots.STATES.index("tell-box-open"), shots.STATES.index("stuck") + 1)
        self.assertEqual(shots.WIDTHS, (1440, 480))

    def test_the_actor_seed_holds_a_colleague_sprint_an_answer_and_an_owner_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            now_s = time.time()
            fixture = shots.build_fixture(Path(tmp).resolve(), "guest-steer", now_s)
            svc = shots.start_service(
                fixture, now_s, guest_dir=support.guest_socket_path(self).parent.parent)
            try:
                view = json.loads(svc.view_bytes)
                guest = json.loads(svc.guest_view_bytes(shots.COLLEAGUE))
            finally:
                svc.close()
        sprints = all_sprints(view)
        theirs = [s for s in sprints if s["started_by"] == shots.COLLEAGUE]
        self.assertEqual(len(theirs), 2)
        answered = [s for s in theirs if s["messages"] and s["messages"][-1]["kind"] == "answer"]
        self.assertEqual(len(answered), 1)
        self.assertEqual(answered[0]["messages"][-1]["by"], shots.COLLEAGUE)
        self.assertEqual([s for s in sprints if s["started_by"] is None][0]["messages"][-1]["by"],
                         None)
        self.assertEqual(len([s for s in sprints if s["started_by"] is None]), 1)
        opened = view["inbox"]["open"]
        confirms = [i for i in opened if i.get("reason") == "verify-approve"]
        self.assertEqual([i["confirm"] for i in confirms], ["owner/web#12"])
        briefs = [i for i in opened if i["reason"] == "brief"]
        self.assertEqual(len(briefs), 1)
        self.assertEqual(briefs[0]["started_by"], shots.COLLEAGUE)
        steer = {i["reason"]: i["steer"] for i in guest["inbox"]["open"]}
        self.assertTrue(steer["brief"])
        self.assertFalse(steer["verify-approve"])

    def test_the_guest_seed_holds_a_colleagues_own_account(self) -> None:
        for state in ("guest-page", "guest-steer", "owner-actors", "owner-accounts"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                fixture = shots.build_fixture(Path(tmp).resolve(), state, time.time())
                log = shots.EventLog(fixture.store)
                try:
                    events = log.events()
                finally:
                    log.close()
                added = [e.payload for e in events if e.kind == "account.added"]
                self.assertEqual(added, [{
                    "by": shots.COLLEAGUE, "profile": "colleague-1",
                    "identity": account_add.identity(fixture.accounts / "profiles" / "colleague-1")}])
                self.assertIsNotNone(added[0]["identity"])
                readings = [e.payload for e in events
                            if e.kind == "signin.reading" and e.payload.get("profile") == "colleague-1"]
                self.assertEqual([r["state"] for r in readings], ["signed_in"])
                self.assertTrue((fixture.accounts / "profiles" / "colleague-1").is_dir())
                for name in ("work-main", "work-spare"):
                    self.assertTrue((fixture.accounts / "profiles" / name).is_dir())

    def test_the_guest_seed_builds_against_the_base_revisions_add_row(self) -> None:
        # The before picture runs this fixture against the base revision, whose `added` takes a profile only.
        def base_added(profile):
            return (event_log.ACCOUNT_ADDED, None, {"by": "owner", "profile": profile})

        for state in ("guest-page", "guest-steer", "owner-actors"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(account_add, "added", base_added):
                fixture = shots.build_fixture(Path(tmp).resolve(), state, time.time())
                log = shots.EventLog(fixture.store)
                try:
                    added = [e.payload for e in log.events() if e.kind == "account.added"]
                finally:
                    log.close()
                self.assertEqual([(a["by"], a["profile"]) for a in added], [(shots.COLLEAGUE, "colleague-1")])

    def test_the_guest_page_shot_opens_the_consent_only_on_a_page_that_has_it(self) -> None:
        door = "#console-door"
        for state in ("guest-page", "guest-steer"):
            for width in (1440, 480):
                for has in (True, False):
                    with self.subTest(state=state, width=width, has=has), \
                            tempfile.TemporaryDirectory() as tmp:
                        present = {door, "#pool"} | ({".pool-add"} if has else set())
                        browser, page = fake_browser(present)
                        order = []
                        page.screenshot = lambda path, full_page: order.append("shot")
                        wait = page.wait_for_selector
                        page.wait_for_selector = lambda s: (wait(s), order.append(s))
                        shots._shoot(browser, "http://console.test/", state, width, Path(tmp))
                        if has:
                            self.assertEqual(page.clicks, [".pool-add"])
                            self.assertIn(".guest-consent", page.waits)
                            self.assertIn(".guest-signin:disabled", page.waits)
                            self.assertLess(order.index(".guest-signin:disabled"), order.index("shot"))
                        else:
                            self.assertEqual(page.clicks, [])
                            self.assertNotIn(".guest-consent", page.waits)
                            self.assertNotIn(".guest-signin:disabled", page.waits)

    def test_the_owner_actors_shot_waits_for_the_login_in_the_tightest_node(self) -> None:
        for width in (1440, 480):
            for has in (True, False):
                with self.subTest(width=width, has=has), tempfile.TemporaryDirectory() as tmp:
                    browser, page = fake_browser({"#console-door"} | ({".cap-owner"} if has else set()))
                    order = []
                    page.screenshot = lambda path, full_page: order.append("shot")
                    wait = page.wait_for_selector
                    page.wait_for_selector = lambda s: (wait(s), order.append(s))
                    shots._shoot(browser, "http://console.test/", "owner-actors", width, Path(tmp))
                    wanted = ".cap-tightest .cap-owner"
                    if has:
                        self.assertIn(wanted, page.waits)
                        self.assertLess(order.index(wanted), order.index("shot"))
                    else:
                        self.assertNotIn(wanted, page.waits)

    def test_the_live_fault_shot_waits_for_its_line_where_the_service_declares_them(self) -> None:
        wanted = (".sprint-checks .live-fault", ".live-fault-withdraw")
        for width in (1440, 480):
            for declared in (True, False):
                with self.subTest(width=width, declared=declared), \
                        tempfile.TemporaryDirectory() as tmp, \
                        mock.patch.object(shots, "declares_live_faults", return_value=declared):
                    browser, page = fake_browser(set())
                    order = []
                    page.screenshot = lambda path, full_page: order.append("shot")
                    wait = page.wait_for_selector
                    page.wait_for_selector = lambda s: (wait(s), order.append(s))
                    shots._shoot(browser, "http://console.test/", "live-fault", width, Path(tmp))
                    for selector in wanted:
                        if declared:
                            self.assertIn(selector, page.waits)
                            self.assertLess(order.index(selector), order.index("shot"))
                        else:
                            self.assertNotIn(selector, page.waits)

    def test_the_live_fault_withdraw_is_not_jargon(self) -> None:
        self.assertIn("button.live-fault-withdraw", shots.JARGON_COUNT)
        self.assertIn("button.notice-withdraw", shots.JARGON_COUNT)

    def test_the_owner_accounts_shot_opens_the_panel_and_waits_for_sign_out_where_the_service_offers_it(
            self) -> None:
        for width in (1440, 480):
            for offered in (True, False):
                with self.subTest(width=width, offered=offered), tempfile.TemporaryDirectory() as tmp, \
                        mock.patch.object(shots, "offers_account_changes", return_value=offered):
                    browser, page = fake_browser({"#console-door", ".acct-owner"})
                    order = []
                    page.screenshot = lambda path, full_page: order.append("shot")
                    wait = page.wait_for_selector
                    page.wait_for_selector = lambda s: (wait(s), order.append(s))
                    shots._shoot(browser, "http://console.test/", "owner-accounts", width, Path(tmp))
                    self.assertEqual(page.clicks, ["#capacity"])
                    self.assertIn("#accounts:not([hidden])", page.waits)
                    self.assertIn(".acct-row .acct-owner", page.waits)
                    if offered:
                        self.assertIn(".acct-row .acct-signout", page.waits)
                        self.assertLess(order.index(".acct-row .acct-signout"), order.index("shot"))
                    else:
                        self.assertNotIn(".acct-row .acct-signout", page.waits)

    def test_the_guest_page_shot_waits_for_his_controls_where_the_service_offers_them(self) -> None:
        controls = (".pool-yours .pool-signout", ".pool-yours .pool-remove")
        for offered in (True, False):
            with self.subTest(offered=offered), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "offers_account_changes", return_value=offered):
                browser, page = fake_browser({"#console-door", "#pool", ".pool-add"})
                order = []
                page.screenshot = lambda path, full_page: order.append("shot")
                wait = page.wait_for_selector
                page.wait_for_selector = lambda s: (wait(s), order.append(s))
                shots._shoot(browser, "http://console.test/", "guest-page", 480, Path(tmp))
                for selector in controls:
                    if offered:
                        self.assertIn(selector, page.waits)
                        self.assertLess(order.index(selector), order.index("shot"))
                    else:
                        self.assertNotIn(selector, page.waits)

    def test_the_account_changes_are_offered_by_this_service(self) -> None:
        self.assertIs(shots.offers_account_changes(), True)

    def test_capture_shoots_the_guest_steer_state_through_the_guest_door(self) -> None:
        class Browser:
            def close(self):
                pass

        class Playwright:
            chromium = types.SimpleNamespace(launch=lambda args=None: Browser())

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        api = types.ModuleType("playwright.sync_api")
        api.Error = type("Error", (Exception,), {})
        api.sync_playwright = Playwright
        seen = []

        def fake(browser, url, state, width, out, **kwargs):
            host, port = url.split("//")[1].split("/")[0].split(":")
            connection = http.client.HTTPConnection(host, int(port))
            try:
                connection.request("GET", "/api/state")
                response = connection.getresponse()
                seen.append((state, url, response.status, json.loads(response.read())))
            finally:
                connection.close()

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(sys.modules, {"playwright": types.ModuleType("playwright"),
                                              "playwright.sync_api": api}), \
                mock.patch.object(shots, "_shoot", side_effect=fake):
            shots.capture(Path(tmp), states=("guest-steer",), widths=(shots.WIDTHS[0],))
        self.assertEqual(len(seen), 1)
        state, url, status, view = seen[0]
        self.assertEqual((state, status), ("guest-steer", 200))
        theirs = [s for s in all_sprints(view) if s["started_by"] == shots.COLLEAGUE]
        self.assertEqual(len(theirs), 2)
        self.assertEqual([s["steer"] for s in theirs], [True, True])
        owners = [s for s in all_sprints(view) if s["started_by"] is None]
        self.assertEqual([s["steer"] for s in owners], [False])
        confirms = [i for i in view["inbox"]["open"] if i.get("reason") == "verify-approve"]
        self.assertTrue(confirms)
        self.assertEqual([i["steer"] for i in confirms], [False] * len(confirms))

    def test_capture_serves_each_width_of_the_adoption_failed_state_from_a_fresh_console(self) -> None:
        # The state clicks Merge, which the console cannot be asked twice, so a width shot after
        # another would find the card gone.
        class Browser:
            def close(self):
                pass

        class Playwright:
            chromium = types.SimpleNamespace(launch=lambda args=None: Browser())

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        api = types.ModuleType("playwright.sync_api")
        api.Error = type("Error", (Exception,), {})
        api.sync_playwright = Playwright
        cards = []

        def fake(browser, url, state, width, out, **kwargs):
            host, port = url.split("//")[1].split("/")[0].split(":")
            connection = http.client.HTTPConnection(host, int(port))
            try:
                connection.request("GET", "/api/state")
                view = json.loads(connection.getresponse().read())
            finally:
                connection.close()
            cards.append((width, [i["reason"] for i in view["inbox"]["open"]]))

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(sys.modules, {"playwright": types.ModuleType("playwright"),
                                              "playwright.sync_api": api}), \
                mock.patch.object(shots, "_shoot", side_effect=fake), \
                mock.patch.object(shots, "start_service", wraps=shots.start_service) as started:
            shots.capture(Path(tmp), states=("adoption-failed",))
        self.assertEqual(started.call_count, len(shots.WIDTHS))
        self.assertEqual(cards, [(width, ["adoption"]) for width in shots.WIDTHS])

    def permission_views(self, state: str) -> list:
        """What a shot of `state` finds on the console at each width: `(width, /api/state)`, from the real `capture`."""
        class Browser:
            def close(self):
                pass

        class Playwright:
            chromium = types.SimpleNamespace(launch=lambda args=None: Browser())

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        api = types.ModuleType("playwright.sync_api")
        api.Error = type("Error", (Exception,), {})
        api.sync_playwright = Playwright
        views = []

        def fake(browser, url, state, width, out, **kwargs):
            host, port = url.split("//")[1].split("/")[0].split(":")
            connection = http.client.HTTPConnection(host, int(port))
            try:
                connection.request("GET", "/api/state")
                views.append((width, json.loads(connection.getresponse().read())))
            finally:
                connection.close()

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(sys.modules, {"playwright": types.ModuleType("playwright"),
                                              "playwright.sync_api": api}), \
                mock.patch.object(shots, "_shoot", side_effect=fake):
            shots.capture(Path(tmp), states=(state,))
        return views

    def test_the_permission_card_shot_finds_the_held_prompt_at_each_width(self) -> None:
        # Without `hold_permission` in `capture` the PNGs are still named right, so the view is read at the shot.
        views = self.permission_views("permission-card")
        self.assertEqual([width for width, _ in views], list(shots.WIDTHS))
        for width, view in views:
            with self.subTest(width=width):
                held = [i for i in view["inbox"]["open"] if i["reason"] == "permission"]
                self.assertEqual([(i["command"], i["words"]) for i in held],
                                 [(shots.PERMISSION_COMMAND, shots.PERMISSION_WORDS)])
                self.assertEqual(view["statement"]["inbox_items"], 1)

    def test_the_permission_stale_shot_finds_nothing_that_needs_the_owner(self) -> None:
        views = self.permission_views("permission-stale")
        self.assertEqual([width for width, _ in views], list(shots.WIDTHS))
        for width, view in views:
            with self.subTest(width=width):
                self.assertEqual(view["statement"]["inbox_items"], 0)
                self.assertEqual(view["inbox"]["open"], [])
        with tempfile.TemporaryDirectory() as tmp:
            now_s = time.time()
            fixture = shots.build_fixture(Path(tmp), "permission-stale", now_s)
            svc = shots.start_service(fixture, now_s)
            try:
                svc.poll_sessions()
                view = json.loads(svc.view_bytes)
            finally:
                svc.close()
        self.assertEqual(view["statement"]["inbox_items"], 0)

    def test_the_held_prompt_is_a_card_in_the_fixture_view_once_posted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            now_s = time.time()
            fixture = shots.build_fixture(Path(tmp), "permission-card", now_s)
            svc = shots.start_service(fixture, now_s)
            try:
                before = json.loads(svc.view_bytes)
                held = shots.hold_permission(svc, fixture)
                shots.keep_permission(svc, fixture, held)
                view = json.loads(svc.view_bytes)
            finally:
                svc.close()
        self.assertEqual(before["statement"]["inbox_items"], 0)
        self.assertIsInstance(held, int)
        self.assertEqual([i["command"] for i in view["inbox"]["open"]], [shots.PERMISSION_COMMAND])
        self.assertEqual(view["statement"]["inbox_items"], 1)

    def test_the_recipe_help_counts_the_files_a_full_run_writes(self) -> None:
        justfile = (Path(__file__).resolve().parent.parent / "justfile").read_text()
        count = len(shots.STATES) * len(shots.WIDTHS)
        self.assertIn(f"sprint states against a fixture console, {count} PNGs into out", justfile)

    def test_a_shot_with_jargon_or_a_clamped_sentence_fails_the_command(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        code, text = run(lambda path: shots.Shot("stuck", 480, path, 480, 0, 1))
        self.assertEqual(code, 1)
        self.assertIn("jargon label", text)
        code, text = run(lambda path: shots.Shot("stuck", 480, path, 480, 1, 0))
        self.assertEqual(code, 1)
        self.assertIn("squeezes the now sentence", text)
        code, text = run(lambda path: shots.Shot("tell-box-open", 480, path, 480, 0, 0,
                                                 (False, None, None)))
        self.assertEqual(code, 1)
        self.assertIn("does not show the open Tell box", text)
        code, text = run(lambda path: shots.Shot("tell-box-open", 480, path, 480, 0, 0,
                                                 shots.OPEN_TELL))
        self.assertEqual(code, 0)

    def test_an_ask_box_shot_without_the_open_box_and_its_questions_fails_the_command(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        phrase = "does not show the open Ask box"
        for ask in ((False, None, None), (True, None, shots.ASK_READ_LINE),
                    (True, "Working on it", None)):
            with self.subTest(ask=ask):
                code, text = run(lambda path: shots.Shot("ask-box", 480, path, 480, ask=ask))
                self.assertEqual(code, 1)
                self.assertIn(phrase, text)
        code, text = run(lambda path: shots.Shot("ask-box", 480, path, 480, ask=shots.OPEN_ASK))
        self.assertEqual(code, 0)
        code, text = run(lambda path: shots.Shot("ask-box", 480, path, 480, ask=shots.HEAD_ASK))
        self.assertEqual(code, 0)
        code, text = run(lambda path: shots.Shot("ask-box", 480, path, 480, ask=None))
        self.assertEqual(code, 0)
        self.assertNotIn(phrase, text)
        code, text = run(lambda path: shots.Shot("live-several", 480, path, 480,
                                                 ask=(False, None, None)))
        self.assertEqual(code, 0)

    def test_the_ask_box_shot_opens_owner_webs_box_only_on_a_page_that_has_one(self) -> None:
        field = 'li.asks[data-project="owner/web"] textarea.ask-text'

        panel = {shots.ASK_OPEN, shots.ASK_FOLD, shots.READING_PANEL}
        through_panel = [shots.ASK_OPEN, shots.ASK_FOLD, shots.thread_line("1177a1")]
        head = {shots.ASK_OPEN, shots.ASK_FOLD}
        opened = [shots.ASK_OPEN, shots.ASK_FOLD, *shots.ASK_THREADS]
        cases = (("head with the reading panel", "ask-box", panel, through_panel, shots.HEAD_ASK),
                 ("head", "ask-box", head | {"li.asks"}, opened, shots.OPEN_ASK),
                 # The page of #1178: the line holds the button and no li.asks exists until the box opens.
                 ("head, no Ask block before opening", "ask-box", head, opened, shots.OPEN_ASK),
                 # The page of #1177: li.asks holds the button and there is no fold.
                 ("base", "ask-box", {shots.ASK_OPEN, "li.asks"}, [shots.ASK_OPEN], shots.OPEN_ASK),
                 ("no Ask control", "ask-box", set(), [], None),
                 ("other state", "live-several", head, [], None))
        for name, state, present, clicks, ask in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(present)
                shot = shots._shoot(browser, "http://console.test/", state, 480, Path(tmp))
                self.assertEqual(page.clicks, clicks)
                self.assertEqual(shot.ask, ask)
                self.assertEqual(page.reads, 1 if ask else 0)
                self.assertEqual(field in page.waits, bool(clicks))

    def test_an_activation_shot_without_its_line_and_button_fails_the_command(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        self.assertEqual(shots.ACTIVATION_SHOWN, {
            "activation-tooling": (
                "A change to the agent tooling merged at 125812581258 and is not active on this "
                "host.", 1),
            "activation-host": (
                "A change to the host configuration merged at 125812581258 and is not active on "
                "this host.", 1)})
        phrase = "does not show the activation line with its Activate button"
        for state, shown_ in shots.ACTIVATION_SHOWN.items():
            other = next(v for k, v in shots.ACTIVATION_SHOWN.items() if k != state)
            for line in ((None, 1), (shown_[0], 0), (shown_[0], 2), other,
                         ("A console change merged at 125812581258 is not active on this host.", 1)):
                with self.subTest(state=state, line=line):
                    code, text = run(lambda path: shots.Shot(state, 480, path, 480, activation=line))
                    self.assertEqual(code, 1)
                    self.assertIn(phrase, text)
            code, text = run(lambda path: shots.Shot(state, 480, path, 480, activation=shown_))
            self.assertEqual(code, 0)
            self.assertNotIn(phrase, text)
            self.assertEqual(shots.ACTIVATION_BASE, (None, 0))
            self.assertIs(shots.reads_other(), True)
            code, text = run(lambda path: shots.Shot(state, 480, path, 480,
                                                     activation=shots.ACTIVATION_BASE))
            self.assertEqual(code, 1)
            self.assertIn(phrase, text)
            with mock.patch.object(shots, "reads_other", return_value=False):
                code, text = run(lambda path: shots.Shot(state, 480, path, 480,
                                                         activation=shots.ACTIVATION_BASE))
                self.assertEqual(code, 0)
                self.assertNotIn(phrase, text)
                code, text = run(lambda path: shots.Shot(state, 480, path, 480, activation=shown_))
                self.assertEqual(code, 0)
        code, text = run(lambda path: shots.Shot("live-several", 480, path, 480,
                                                 activation=(None, 1)))
        self.assertEqual(code, 0)

    def test_the_activation_shots_read_the_line_only_in_their_own_states(self) -> None:
        for state, reads in (("activation-tooling", 1), ("activation-host", 1), ("live-several", 0)):
            with self.subTest(state), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(set())
                shot = shots._shoot(browser, "http://console.test/", state, 480, Path(tmp))
                self.assertEqual(page.reads, reads)
                self.assertEqual(shot.activation, tuple(
                    shots.ACTIVATION_SHOWN["activation-tooling"]) if reads else None)

    def test_a_register_shot_without_its_proposal_fails_the_command(self) -> None:
        def run(state, reading):
            out = StringIO()
            shot = shots.Shot(state, 480, Path("x.png"), 480, register=reading)
            with mock.patch.object(shots, "capture", return_value=[shot]), \
                    tempfile.TemporaryDirectory() as tmp, redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        line = "commits run in its development shell: devenv shell (found in its files)"
        self.assertEqual(shots.REGISTER_SHOWN, {"register-draft": (None, shots.FACT_LINE, False),
                                                "register-reconcile-apply": (line, None, False),
                                                "register-reconcile-draft": (None, line, True)})
        self.assertEqual(shots.REGISTER_BASE["register-draft"], (None, line, True))  # as the base drafts it
        phrase = "does not show the proposed commit environment"
        self.assertEqual((shots.shows_facts(), shots.proposes_reconcile()), (True, True))
        counterpart = {"register-draft": "register-reconcile-draft",
                       "register-reconcile-apply": "register-reconcile-draft",
                       "register-reconcile-draft": "register-reconcile-apply"}
        for state, shown_ in shots.REGISTER_SHOWN.items():
            other = shots.REGISTER_SHOWN[counterpart[state]]
            for reading in (other, (None, None, False), (shown_[0], shown_[1], not shown_[2]),
                            (line + " now", shown_[1], shown_[2])):
                with self.subTest(state=state, reading=reading):
                    code, text = run(state, reading)
                    self.assertEqual(code, 1)
                    self.assertIn(phrase, text)
            self.assertEqual(run(state, shown_)[0], 0)
            self.assertNotIn(phrase, run(state, shown_)[1])
            self.assertEqual(run(state, shots.REGISTER_BASE[state])[0], 1)
            with mock.patch.object(shots, "proposes", return_value=False):
                code, text = run(state, shots.REGISTER_BASE[state])
                self.assertEqual(code, 0)
                self.assertNotIn(phrase, text)
                self.assertEqual(run(state, shown_)[0], 1)
        self.assertEqual(run("live-several", (None, None, False))[0], 0)

    def test_the_register_shots_read_the_card_and_the_draft_only_in_their_own_states(self) -> None:
        for state, reads in (("register-apply", 1), ("register-draft", 1),
                             ("register-reconcile-apply", 1), ("register-reconcile-draft", 1),
                             ("live-several", 0)):
            with self.subTest(state), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(set())
                shot = shots._shoot(browser, "http://console.test/", state, 480, Path(tmp))
                self.assertEqual(page.reads, reads)
                self.assertEqual(shot.register, shots.REGISTER_SHOWN["register-reconcile-apply"] if reads else None)

    def test_an_ask_goal_shot_without_the_filled_box_fails_the_command(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        self.assertIs(shots.FILLED_GOAL[3], True)
        self.assertEqual(shots.FILLED_GOAL[1],
                         shots.ASK_ANSWERED_QUESTION + "\n\n" + shots.ASK_ANSWER_SUMMARY)
        phrase = "does not show the goal box filled from the answer"
        text_ = shots.FILLED_GOAL[1]
        for goal in ((False, None, None, None), (True, "", "owner/web", True),
                     (True, text_, "owner/api", True),
                     (True, text_ + "\nRan: just build", "owner/web", True),
                     (True, text_, "owner/web", False)):
            with self.subTest(goal=goal):
                code, text = run(lambda path: shots.Shot("ask-goal", 480, path, 480, goal=goal))
                self.assertEqual(code, 1)
                self.assertIn(phrase, text)
        for goal in (shots.FILLED_GOAL, None):
            code, text = run(lambda path: shots.Shot("ask-goal", 480, path, 480, goal=goal))
            self.assertEqual(code, 0)
            self.assertNotIn(phrase, text)
        code, text = run(lambda path: shots.Shot("live-several", 480, path, 480,
                                                 goal=(False, None, None, None)))
        self.assertEqual(code, 0)

    def test_the_ask_goal_shot_clicks_make_it_a_goal_only_on_a_page_that_has_it(self) -> None:
        fold = [shots.ASK_FOLD, shots.ASK_THREADS[1]]
        through_panel = [shots.ASK_FOLD, shots.thread_line("1177a1"), "#reading button.ask-goal"]
        cases = (("head with the reading panel", "ask-goal",
                  {shots.READING_PANEL, shots.ASK_FOLD, "#reading button.ask-goal"},
                  through_panel, shots.FILLED_GOAL),
                 ("head", "ask-goal", {shots.ASK_FOLD, shots.ASK_GOAL}, [*fold, shots.ASK_GOAL],
                  shots.FILLED_GOAL),
                 ("base", "ask-goal", {shots.ASK_FOLD}, fold, None),
                 ("no fold", "ask-goal", set(), [], None),
                 ("other state", "live-several", {shots.ASK_FOLD, shots.ASK_GOAL}, [], None))
        for name, state, present, clicks, goal in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(present)
                shot = shots._shoot(browser, "http://console.test/", state, 480, Path(tmp))
                self.assertEqual(page.clicks, clicks)
                self.assertEqual(shot.goal, goal)
                self.assertEqual(page.reads, 1 if goal else 0)
                self.assertEqual("#goal .goal-box" in page.waits, goal is not None)

    def test_a_shot_with_ask_off_the_give_goal_row_fails_the_command(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        code, text = run(lambda path: shots.Shot("questions-closed", 1440, path, 1440,
                                                 acts=("owner/api",)))
        self.assertEqual(code, 1)
        self.assertIn("puts Ask a question on another row than Give it a goal (owner/api)", text)
        code, text = run(lambda path: shots.Shot("questions-closed", 1440, path, 1440, acts=()))
        self.assertEqual(code, 0)

    def test_a_questions_open_shot_must_show_the_opened_thread(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        phrase = "does not show the opened thread"
        for thread in ((False, None, False), (True, None, True)):
            with self.subTest(thread=thread):
                code, text = run(lambda path: shots.Shot("questions-open", 480, path, 480,
                                                         thread=thread))
                self.assertEqual(code, 1)
                self.assertIn(phrase, text)
        for thread in (shots.OPEN_THREAD, shots.BASE_THREAD, None):
            with self.subTest(thread=thread):
                code, text = run(lambda path: shots.Shot("questions-open", 480, path, 480,
                                                         thread=thread))
                self.assertEqual(code, 0)
                self.assertNotIn(phrase, text)

    def test_the_questions_open_shot_opens_the_fold_only_on_a_page_that_has_it(self) -> None:
        newest = 'details[data-key="thread:owner/web:1178a2"] > summary'
        cases = (("head with the reading panel", {shots.ASK_FOLD, shots.READING_PANEL},
                  [shots.ASK_FOLD, shots.thread_line("1178a2")], shots.OPEN_THREAD),
                 ("head", {shots.ASK_FOLD}, [shots.ASK_FOLD, newest], shots.OPEN_THREAD),
                 ("base", set(), [], shots.BASE_THREAD))
        for name, present, clicks, thread in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(present)
                shot = shots._shoot(browser, "http://console.test/", "questions-open", 480,
                                    Path(tmp))
                self.assertEqual(page.clicks, clicks)
                self.assertEqual(shot.thread, thread)
                self.assertEqual(page.reads, 1)
        with tempfile.TemporaryDirectory() as tmp:
            browser, page = fake_browser({shots.ASK_FOLD})
            shot = shots._shoot(browser, "http://console.test/", "questions-closed", 480, Path(tmp))
            self.assertEqual(page.clicks, [])
            self.assertIsNone(shot.thread)
            self.assertEqual(shot.acts, ())

    def test_a_question_card_shot_without_its_pick_and_words_or_its_refusal_fails_the_command(
            self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        phrase = "does not show the question card"
        wrong = {"question-words": ((None, shots.LOOK_WORDS, True, None),
                                    ("Ask for changes", "", True, None),
                                    ("Ask for changes", shots.LOOK_WORDS, False, None),
                                    ("Ask for changes", shots.LOOK_WORDS, True, "Say what to change."),
                                    (None, None, None, None)),
                 "question-refused": (("Ask for changes", "", True, None),
                                      (None, "", True, "Say what to change."),
                                      ("Ask for changes", shots.LOOK_WORDS, True, "Say what to change."),
                                      (None, None, None, None))}
        right = {"question-words": ("Ask for changes", shots.LOOK_WORDS, True, None),
                 "question-refused": ("Ask for changes", "", True, "Say what to change.")}
        for state, readings in wrong.items():
            for card in readings:
                with self.subTest(state=state, card=card):
                    code, text = run(lambda path: shots.Shot(state, 480, path, 480, card=card))
                    self.assertEqual(code, 1)
                    self.assertIn(phrase, text)
            for card in (right[state], None):
                with self.subTest(state=state, card=card):
                    code, text = run(lambda path: shots.Shot(state, 480, path, 480, card=card))
                    self.assertEqual(code, 0)
                    self.assertNotIn(phrase, text)
        self.assertEqual((shots.WORDS_CARD, shots.REFUSED_CARD), (right["question-words"],
                                                                  right["question-refused"]))

    def test_the_question_card_shots_pick_ask_for_changes_and_type_or_send_only_on_a_page_with_the_words_box(
            self) -> None:
        empty = (None, None, None, None)
        third = ".lead ul.opts li:nth-child(3) button.opt"
        cases = (("question-words", {shots.WORDS_BOX}, [third], [(shots.WORDS_BOX, shots.LOOK_WORDS)],
                  shots.WORDS_CARD),
                 ("question-refused", {shots.WORDS_BOX}, [third, ".lead button.send"], [],
                  shots.REFUSED_CARD),
                 ("question-words", {shots.LOOK_OPTION}, [], [], None),
                 ("question-refused", {shots.LOOK_OPTION}, [], [], None),
                 ("question-words", set(), [], [], empty),
                 ("question-refused", set(), [], [], empty),
                 ("inbox-card", {shots.WORDS_BOX}, [], [], None))
        for state, present, clicks, fills, card in cases:
            for width in shots.WIDTHS:
                with self.subTest(state=state, present=bool(present), width=width), \
                        tempfile.TemporaryDirectory() as tmp:
                    browser, page = fake_browser(present)
                    page.card = card or ()
                    shot = shots._shoot(browser, "http://console.test/", state, width, Path(tmp))
                    self.assertEqual(page.clicks, clicks)
                    self.assertEqual(page.fills, fills)
                    self.assertEqual(shot.card, card)
                    self.assertEqual(page.reads, 1 if card and card != empty else 0)

    def test_the_look_check_question_is_seeded_with_needs_words_only_where_the_service_keeps_it(
            self) -> None:
        for kept in (True, False):
            with self.subTest(kept=kept), tempfile.TemporaryDirectory() as tmp:
                at = [""]
                log = shots.EventLog(Path(tmp) / "events.db", clock=lambda: at[0])
                with mock.patch.object(shots, "NEEDS_WORDS_KEPT", kept):
                    shots._Seed(log, at, 10000.0).sprint("owner/web", "t", started=1800,
                                                           look=True)
                (asked,) = [e for e in log.events() if e.kind == "questions.asked"]
                log.close()
                (question,) = asked.payload["questions"]
                self.assertEqual(question["options"], shots.LOOK_OPTIONS)
                self.assertEqual("needs_words" in question, kept)
        self.assertTrue(shots.NEEDS_WORDS_KEPT)

    def test_a_question_read_shot_that_does_not_read_the_answer_in_the_main_column_fails_the_command(
            self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        phrase = "does not show the answer in the main column"
        for reading in ((False, 1, True, True, 3), (True, 2, True, True, 3),
                        (True, 1, False, True, 3), (True, 1, True, False, 3),
                        (True, 1, True, True, 0)):
            with self.subTest(reading=reading):
                code, text = run(lambda path: shots.Shot("question-read", 480, path, 480,
                                                         reading=reading))
                self.assertEqual(code, 1)
                self.assertIn(phrase, text)
        for reading in (shots.READ_SHOWN, None):
            with self.subTest(reading=reading):
                code, text = run(lambda path: shots.Shot("question-read", 480, path, 480,
                                                         reading=reading))
                self.assertEqual(code, 0)
                self.assertNotIn(phrase, text)

    def test_the_question_read_shot_opens_the_thread_in_the_panel_only_on_a_page_that_has_it(
            self) -> None:
        cases = (("head", {shots.READING_PANEL, shots.ASK_FOLD},
                  [shots.ASK_FOLD, shots.thread_line("1226a1")], shots.READ_SHOWN),
                 ("base", {shots.ASK_FOLD},
                  [shots.ASK_FOLD, 'details[data-key="thread:owner/web:1226a1"] > summary'], None))
        for name, present, clicks, reading in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(present)
                shot = shots._shoot(browser, "http://console.test/", "question-read", 480,
                                    Path(tmp))
                self.assertEqual(page.clicks, clicks)
                self.assertEqual(shot.reading, reading)

    def test_the_deeper_shots_open_their_thread_in_the_panel_and_read_it(self) -> None:
        deep = "#reading button.ask-deep"
        head = {shots.READING_PANEL, shots.ASK_FOLD}
        answer_base = 'details[data-key="thread:owner/web:1435a1"] > summary'
        offer_base = 'details[data-key="thread:owner/web:1435b1"] > summary'
        cases = (
            ("deeper-answer", "head", head,
             [shots.ASK_FOLD, shots.thread_line("1435a1")], shots.DEEPER_SHOWN["deeper-answer"]),
            ("deeper-offer", "head", head | {deep},
             [shots.ASK_FOLD, shots.thread_line("1435b1"), deep],
             shots.DEEPER_SHOWN["deeper-offer"]),
            ("deeper-answer", "base", {shots.ASK_FOLD}, [shots.ASK_FOLD, answer_base], None),
            ("deeper-offer", "base", {shots.ASK_FOLD}, [shots.ASK_FOLD, offer_base], None),
            ("deeper-answer", "no fold", set(), [], None),
            ("deeper-offer", "no fold", set(), [], None))
        for state, name, present, clicks, deeper in cases:
            with self.subTest(state=state, name=name), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(present)
                shot = shots._shoot(browser, "http://console.test/", state, 480, Path(tmp))
                self.assertEqual(page.clicks, clicks)
                self.assertEqual(shot.deeper, deeper)
                self.assertIsNone(shot.thread)
        with tempfile.TemporaryDirectory() as tmp:
            browser, page = fake_browser(head)
            shot = shots._shoot(browser, "http://console.test/", "question-read", 480, Path(tmp))
            self.assertIsNone(shot.deeper)

    def test_a_deeper_shot_without_its_spend_lines_estimate_or_goal_fails_the_command(
            self) -> None:
        def run(shot, panel=True):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    mock.patch.object(shots, "serves_reading_panel", return_value=panel), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        answer_phrase = "does not show the deeper answer with its spend lines and Make it a goal"
        offer_phrase = ("does not show the Dig deeper estimate with the answer's spend line and "
                        "Make it a goal")
        (light, light_spend), (deep, deep_spend) = shots.DEEPER_ROWS["deeper-answer"]
        (offered, offered_spend), = shots.DEEPER_ROWS["deeper-offer"]
        answer_ok = shots.DEEPER_SHOWN["deeper-answer"]
        offer_ok = shots.DEEPER_SHOWN["deeper-offer"]
        for deeper in ((False, (), False),
                       (True, ((light, light_spend), (light, light_spend)), True),
                       (True, ((light, light_spend), (deep, light_spend)), True),
                       (True, ((light, deep_spend), (deep, deep_spend)), True),
                       (True, ((light, light_spend),), True),
                       (True, ((light, light_spend), (deep, deep_spend)), False),
                       (True, (("", light_spend), (deep, deep_spend)), True)):
            with self.subTest(state="deeper-answer", deeper=deeper):
                code, text = run(lambda path: shots.Shot("deeper-answer", 480, path, 480,
                                                         deeper=deeper))
                self.assertEqual(code, 1)
                self.assertIn(answer_phrase, text)
        intro = "Dig deeper asks again on a stronger model for up to 20 minutes. "
        row = ((offered, offered_spend),)
        for deeper in ((False, (), False, ""), (True, row, False, shots.DEEPER_ESTIMATE),
                       (True, row, True, intro),
                       (True, row, True, intro + "Earlier deeper answers here spent about  tokens,  each."),
                       (True, row, True, intro + "Earlier deeper answers here spent about "
                        "544,000 tokens, $0.38 each."),
                       (True, row, True, intro + "No earlier deeper answer here to estimate its "
                        "spend from."),
                       (True, ((offered, light_spend),), True, shots.DEEPER_ESTIMATE),
                       (True, ((light, offered_spend),), True, shots.DEEPER_ESTIMATE),
                       (True, row + row, True, shots.DEEPER_ESTIMATE)):
            with self.subTest(state="deeper-offer", deeper=deeper):
                code, text = run(lambda path: shots.Shot("deeper-offer", 480, path, 480,
                                                         deeper=deeper))
                self.assertEqual(code, 1)
                self.assertIn(offer_phrase, text)
        for state, shown in (("deeper-answer", answer_ok), ("deeper-offer", offer_ok)):
            with self.subTest(state=state, deeper=shown):
                code, text = run(lambda path: shots.Shot(state, 480, path, 480, deeper=shown))
                self.assertEqual(code, 0)
                self.assertNotIn(answer_phrase, text)
                self.assertNotIn(offer_phrase, text)
            # A reading that is missing passes only a page without the panel (the before picture).
            with self.subTest(state=state, deeper=None):
                code, text = run(lambda path: shots.Shot(state, 480, path, 480), panel=False)
                self.assertEqual(code, 0)
                code, text = run(lambda path: shots.Shot(state, 480, path, 480), panel=True)
                self.assertEqual(code, 1)
                self.assertIn(answer_phrase if state == "deeper-answer" else offer_phrase, text)
        code, text = run(lambda path: shots.Shot("deeper-offer", 480, path, 480, deeper=answer_ok))
        self.assertEqual(code, 1)
        self.assertIn(offer_phrase, text)

    def test_serves_reading_panel_only_for_a_page_that_has_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            served = Path(tmp)
            self.assertFalse(shots.serves_reading_panel(served))
            (served / "page.html").write_text('<section id="reading"></section>')
            self.assertTrue(shots.serves_reading_panel(served))
            (served / "page.html").write_text("<main></main>")
            self.assertFalse(shots.serves_reading_panel(served))
        self.assertTrue(shots.serves_reading_panel())

    def test_the_question_read_shot_counts_the_question_it_was_given(self) -> None:
        browser, page = fake_browser({shots.READING_PANEL, shots.ASK_FOLD})
        with tempfile.TemporaryDirectory() as tmp:
            shots._shoot(browser, "http://console.test/", "question-read", 480, Path(tmp),
                         question="What is in production?")
        self.assertEqual(page.counted, "What is in production?")
        self.assertNotIn("What was done", shots.READ_READING)

    def test_a_real_answer_run_shoots_only_the_question_read_state_with_that_answer(self) -> None:
        def run(reading, jargon=0):
            calls = []

            def capture(out, states=shots.STATES, widths=shots.WIDTHS, **kwargs):
                calls.append({"states": tuple(states), **kwargs})
                return [shots.Shot("question-read", width, Path(out) / f"question-read-{width}.png",
                                   width, jargon=jargon, reading=reading) for width in widths]

            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", side_effect=capture), \
                    redirect_stdout(out):
                answer = Path(tmp) / "answer.txt"
                answer.write_text("Answer: plain", encoding="utf-8")
                code = shots.main(["--out", tmp, "--question", "Q?", "--answer-file", str(answer)])
            return code, out.getvalue(), calls

        phrase = "does not show the answer in the main column"
        code, text, calls = run((True, 1, False, False, 0), jargon=1)
        self.assertEqual(code, 0)
        self.assertNotIn(phrase, text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["states"], ("question-read",))
        self.assertEqual(calls[0]["read"], ("Q?", "Answer: plain"))
        code, text, _ = run(None)
        self.assertEqual(code, 0)
        code, text, _ = run((True, 2, False, False, 0))
        self.assertEqual(code, 1)
        self.assertIn(phrase, text)
        code, text, _ = run((False, 1, True, True, 3))
        self.assertEqual(code, 1)
        self.assertIn(phrase, text)
        for flags in (["--question", "Q?"], ["--answer-file", "x.txt"]):
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as tmp, \
                    redirect_stdout(StringIO()), mock.patch("sys.stderr", new=StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    shots.main(["--out", tmp, *flags])
                self.assertEqual(raised.exception.code, 2)

    def test_a_real_answer_run_passes_the_sheets_and_the_composite_to_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(shots, "capture", return_value=[]) as capture, \
                redirect_stdout(StringIO()) as out:
            answer = Path(tmp) / "answer.txt"
            answer.write_text("Answer: plain", encoding="utf-8")
            self.assertEqual(shots.main(["--out", tmp, "--question", "Q?", "--answer-file",
                                         str(answer), "--sheets", "--composite", "combined.png"]), 0)
        self.assertEqual(capture.call_args.kwargs["composite"], "combined.png")
        self.assertIs(capture.call_args.kwargs["sheets"], True)
        self.assertEqual(capture.call_args.kwargs["states"], ("question-read",))
        self.assertIn("combined.png", out.getvalue())

    def test_a_real_answer_seeds_the_question_read_state_with_that_question_and_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            now_s = time.time()
            fixture = shots.build_fixture(
                Path(tmp), "question-read", now_s,
                read=("Q?", "Answer: plain\nQuestion for you: none"))
            svc = shots.start_service(fixture, now_s)
            try:
                view = json.loads(svc.view_bytes)
            finally:
                svc.close()
        web = next(p for p in entries_of(view) if p["project_id"] == "owner/web")
        (thread,) = web["questions"]["threads"]
        (asked,) = thread["questions"]
        self.assertEqual(asked["question"], "Q?")
        self.assertEqual(asked["answer"], "plain")
        self.assertIsNone(asked["back_text"])

    def test_the_deeper_seed_holds_a_deeper_answer_with_its_spend_and_an_offer_with_its_estimate(
            self) -> None:
        spent = re.compile(r"Spent ([\d,]+) tokens, about \$(\d+\.\d\d)")
        for state in ("deeper-offer", "deeper-answer"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                now_s = time.time()
                fixture = shots.build_fixture(Path(tmp), state, now_s)
                svc = shots.start_service(fixture, now_s)
                try:
                    view = json.loads(svc.view_bytes)
                finally:
                    svc.close()
                web = next(p for p in entries_of(view) if p["project_id"] == "owner/web")
                threads = {t["id"]: t for t in web["questions"]["threads"]}
                self.assertEqual(sorted(threads),
                                 sorted([shots.DEEPER_THREAD, shots.DEEPER_OFFER_THREAD]))
                light, deep = threads[shots.DEEPER_THREAD]["questions"]
                self.assertEqual([q["id"] for q in (light, deep)],
                                 [shots.DEEPER_THREAD, shots.DEEPER_ID])
                self.assertEqual([q["question"] for q in (light, deep)],
                                 [shots.DEEPER_QUESTION] * 2)
                self.assertEqual([q["state"] for q in (light, deep)], ["answered", "answered"])
                self.assertEqual([q["deep"] for q in (light, deep)], [False, True])
                self.assertEqual([(q["deep_offer"], q["deep_text"]) for q in (light, deep)],
                                 [(False, None), (False, None)])
                self.assertTrue(deep["answer"].startswith(
                    "**Review and planning take most of the time"))
                self.assertIn("\n- Tasks: 44% of the agent-seconds", deep["answer"])
                self.assertEqual(light["unknown_text"],
                                 "Could not find out: the time and tokens of each phase")
                light_spent = spent.fullmatch(light["spend_text"])
                deep_spent = spent.fullmatch(deep["spend_text"])
                self.assertIsNotNone(light_spent)
                self.assertIsNotNone(deep_spent)
                (light_t, light_d), (deep_t, deep_d) = light_spent.groups(), deep_spent.groups()
                self.assertEqual((light_t, deep_t), ("544,000", "2,184,000"))
                # From the published per-million rates: sonnet 3/0.30/15, opus 5/0.50/25.
                self.assertEqual((light_d, deep_d), ("0.38", "2.76"))
                self.assertGreater(float(deep_d) / int(deep_t.replace(",", "")),
                                   float(light_d) / int(light_t.replace(",", "")))
                (offer,) = threads[shots.DEEPER_OFFER_THREAD]["questions"]
                self.assertEqual((offer["state"], offer["deep"], offer["deep_offer"]),
                                 ("answered", False, True))
                self.assertIs(threads[shots.DEEPER_OFFER_THREAD]["follow_up"], True)
                self.assertEqual(spent.fullmatch(offer["spend_text"]).group(1), "362,000")
                self.assertEqual(
                    offer["deep_text"],
                    "Dig deeper asks again on a stronger model for up to 20 minutes. "
                    "Earlier deeper answers here spent about 2,184,000 tokens, $" + deep_d
                    + " each.")
                self.assertEqual(all_sprints(view), [])
                self.assertEqual(view["statement"]["inbox_items"], 0)

    def test_a_shot_with_a_short_control_fails_the_command(self) -> None:
        out = StringIO()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(shots, "capture", return_value=[
                    shots.Shot("live-several", 1440, Path(tmp) / "p.png", 1440,
                               short=("button.undo 24px",))]), \
                redirect_stdout(out):
            code = shots.main(["--out", tmp])
        self.assertEqual(code, 1)
        self.assertIn("has a control under 32 px", out.getvalue())
        self.assertIn("button.undo 24px", out.getvalue())

    def shoot_main(self, page_state, browser, width=1440):
        """Run `main` with `capture` shooting one state on the fake browser; return (code, stdout)."""
        out = StringIO()

        def fake_capture(path, *args, **kw):
            return [shots._shoot(browser, "http://console.test/", page_state, width, Path(path))]

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(shots, "capture", side_effect=fake_capture), redirect_stdout(out):
            code = shots.main(["--out", tmp])
        return code, out.getvalue()

    def test_a_shot_with_a_broken_page_style_fails_the_command(self) -> None:
        browser, page = fake_browser(set())
        page.style = ["held-nowrap: .held.blocks white-space is normal"]
        with mock.patch.object(shots, "STYLE_CHECKS", (style_row(),)):
            code, text = self.shoot_main("live-several", browser)
        self.assertEqual(code, 1)
        self.assertIn("console-screenshots: live-several-1440.png breaks a page style "
                      "(held-nowrap: .held.blocks white-space is normal)", text)

    def test_the_style_reading_runs_after_the_capture_and_clicks_only_a_present_step(self) -> None:
        row = style_row("look-row", states=("look-card",))
        for present, clicked in (({"button.pic-thumb"}, True), (set(), False)):
            with self.subTest(clicked=clicked), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(present)
                with mock.patch.object(shots, "STYLE_CHECKS", (row,)), \
                        mock.patch.object(shots, "STYLE_STEPS",
                                          {"look-card": ("button.pic-thumb",)}):
                    shot = shots._shoot(browser, "http://console.test/", "look-card", 1440,
                                        Path(tmp))
                self.assertEqual(page.order[:1], ["screenshot"])
                reading = ["STYLE_CLEAR", "STYLE_PLACE", "STYLE_SETTLE", "STYLE_READING",
                           "STYLE_CLEAR"]
                styled = [name for name in page.order if name.startswith("STYLE_")]
                self.assertEqual(styled, (["STYLE_SETTLE"] if clicked else []) + reading)
                self.assertEqual("button.pic-thumb" in page.clicks, clicked)
                if clicked:
                    self.assertEqual(page.clicks[-1], "button.pic-thumb")
                else:
                    self.assertNotIn("button.pic-thumb", page.waits)
                self.assertEqual(shot.style, ())
                self.assertEqual(shot.checked, (row.name,))

    def test_a_forced_row_forces_its_pseudo_class_settles_and_releases_it(self) -> None:
        browser, page = fake_browser(set())
        forced = ("CSS.forcePseudoState", {"nodeId": 2, "forcedPseudoClasses": ["hover"]})
        released = ("CSS.forcePseudoState", {"nodeId": 2, "forcedPseudoClasses": []})
        self.assertEqual(shots.read_style(page, [style_row(forced=("hover",))]), ())
        self.assertEqual([call for call in page.cdp if call[0] == "CSS.forcePseudoState"],
                         [forced, released])
        at = page.order.index("CSS.forcePseudoState")
        self.assertEqual(page.order[at:at + 4],
                         ["CSS.forcePseudoState", "STYLE_SETTLE", "STYLE_READING",
                          "CSS.forcePseudoState"])
        select = next(params for method, params in page.cdp if method == "DOM.querySelectorAll")
        self.assertEqual(select["nodeId"], 1)
        self.assertEqual(select["selector"],
                         ":is(.held.blocks):not([data-style-probe], [data-style-probe] *)")

    def test_a_shot_of_another_page_reads_no_style(self) -> None:
        browser, page = fake_browser({"button.pic-thumb"})
        page.style = ["r: .a b is c"]
        with mock.patch.object(shots, "style_applies", return_value=False), \
                mock.patch.object(shots, "STYLE_CHECKS", (style_row("r", states=("look-card",)),)), \
                mock.patch.object(shots, "STYLE_STEPS", {"look-card": ("button.pic-thumb",)}):
            code, text = self.shoot_main("look-card", browser)
            with tempfile.TemporaryDirectory() as tmp:
                shot = shots._shoot(browser, "http://console.test/", "look-card", 1440, Path(tmp),
                                    mutate=True)
        self.assertEqual(code, 0)
        self.assertEqual([name for name in page.order if name.startswith("STYLE_")], [])
        self.assertNotIn("button.pic-thumb", page.clicks)
        self.assertEqual((shot.style, shot.checked, shot.broke), ((), (), ()))

    def test_a_between_width_row_is_read_in_the_widest_shot_after_resizing_to_it(self) -> None:
        rows = tuple(style_row(name, states=("live-several",), widths=widths)
                     for name, widths in (("wide", (1440,)), ("mid", (900,)), ("high", (1180,)),
                                          ("narrow", (480,))))
        for width, checked, sizes in ((1440, ("wide", "high", "mid"), [1180, 900]),
                                      (480, ("narrow",), [])):
            with self.subTest(width=width), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(set())
                with mock.patch.object(shots, "STYLE_CHECKS", rows):
                    shot = shots._shoot(browser, "http://console.test/", "live-several", width,
                                        Path(tmp))
                self.assertEqual(shot.checked, checked)
                self.assertEqual([size["width"] for size in page.viewports], sizes)
        self.assertEqual(shots.BETWEEN_WIDTHS, (1180, 900))
        self.assertFalse(set(shots.BETWEEN_WIDTHS) & set(shots.WIDTHS))

    def test_a_real_answer_shot_skips_the_fixture_rows(self) -> None:
        rows = (style_row("a", states=("question-read",)),
                style_row("b", states=("question-read",), fixture=True))
        for canonical, expected in ((False, ("a",)), (True, ("a", "b"))):
            with self.subTest(canonical=canonical), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(set())
                with mock.patch.object(shots, "STYLE_CHECKS", rows):
                    shot = shots._shoot(browser, "http://console.test/", "question-read", 1440,
                                        Path(tmp), canonical=canonical)
                self.assertEqual(shot.checked, expected)
                self.assertEqual([[row["name"] for row in placed] for placed in page.placed],
                                 [list(expected)])

    def test_a_mutated_shot_records_each_row_its_rule_broke(self) -> None:
        rows = (style_row("a", broken="a { x: y }"), style_row("b", broken="b { x: y }"))
        browser, page = fake_browser(set())
        page.unbreakable = {"b"}
        with mock.patch.object(shots, "STYLE_CHECKS", rows), tempfile.TemporaryDirectory() as tmp:
            shot = shots._shoot(browser, "http://console.test/", "live-several", 1440, Path(tmp),
                                mutate=True)
            self.assertEqual((shot.checked, shot.broke, shot.style), (("a", "b"), ("a",), ()))
            self.assertEqual(page.mutations, ["a { x: y }", "b { x: y }"])
            browser, page = fake_browser(set())
            shot = shots._shoot(browser, "http://console.test/", "live-several", 1440, Path(tmp))
            self.assertEqual((shot.broke, page.mutations), ((), []))

    def test_a_shot_not_taken_from_the_top_fails_the_command(self) -> None:
        def run(shot):
            out = StringIO()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "capture", return_value=[shot(Path(tmp) / "x.png")]), \
                    redirect_stdout(out):
                code = shots.main(["--out", tmp])
            return code, out.getvalue()

        code, text = run(lambda path: shots.Shot("finished-list", 480, path, 480, 0, 0, None,
                                                 scroll_y=240.0))
        self.assertEqual(code, 1)
        self.assertIn("x.png is not taken from the top of the page", text)
        code, text = run(lambda path: shots.Shot("finished-list", 480, path, 480, 0, 0, None,
                                                 scroll_y=0.0))
        self.assertEqual(code, 0)
        self.assertNotIn("not taken from the top", text)

    @mock.patch.object(shots, "STYLE_CHECKS", ())
    def test_a_shot_scrolls_back_to_the_top_before_its_capture(self) -> None:
        def fake(reset_to):
            class Page:
                y = 0.0

                def __init__(self):
                    self.captured = []

                def goto(self, url):
                    pass

                def wait_for_selector(self, selector):
                    pass

                def click(self, selector):
                    self.y = 300.0

                def evaluate(self, expression):
                    if expression == shots.SCROLL_TOP:
                        self.y = reset_to
                        return None
                    if expression == shots.SCROLL_Y:
                        return self.y
                    if expression == "document.documentElement.scrollWidth":
                        return 480
                    if expression in (shots.SHORT_CONTROLS, shots.ACTS_ROW):
                        return []
                    return 0

                def screenshot(self, path, full_page):
                    self.captured.append((self.y, full_page))

                def close(self):
                    pass

            page = Page()

            class Browser:
                def new_page(self, viewport):
                    return page

            return Browser(), page

        for reset_to in (0.0, 40.0):
            with self.subTest(reset_to=reset_to), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake(reset_to)
                shot = shots._shoot(browser, "http://console.test/", "finished-list", 480,
                                    Path(tmp))
                self.assertEqual(page.captured, [(reset_to, True)])
                self.assertEqual(shot.scroll_y, reset_to)
                self.assertEqual(shot.scroll_y, page.captured[0][0])

    @mock.patch.object(shots, "STYLE_CHECKS", ())
    def test_the_goal_states_type_into_the_box_before_the_capture(self) -> None:
        calls: list[tuple[str, tuple]] = []

        class Page:
            def goto(self, url):
                calls.append(("goto", (url,)))

            def wait_for_selector(self, selector):
                calls.append(("wait_for_selector", (selector,)))

            def focus(self, selector):
                calls.append(("focus", (selector,)))

            def fill(self, selector, text):
                calls.append(("fill", (selector, text)))

            def click(self, selector):
                calls.append(("click", (selector,)))

            def evaluate(self, expression):
                if expression == shots.SCROLL_Y:
                    return 0.0
                if expression == "document.documentElement.scrollWidth":
                    return 480
                if expression in (shots.SHORT_CONTROLS, shots.ACTS_ROW):
                    return []
                return 0

            def screenshot(self, path, full_page):
                calls.append(("screenshot", (path, full_page)))

            def close(self):
                pass

        class Browser:
            def new_page(self, viewport):
                return Page()

        self.assertEqual(shots.GOAL_NEAR_CHARS, 1900)
        self.assertEqual(shots.GOAL_OVER_CHARS, 2100)
        for state, typed, over in (("goal-near", "x" * 1900, False),
                                   ("goal-over", "x" * 2100, True)):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                calls.clear()
                shots._shoot(Browser(), "http://console.test/", state, 480, Path(tmp))
                shot_at = next(i for i, c in enumerate(calls) if c[0] == "screenshot")
                before = calls[:shot_at]
                focus = ("focus", ("textarea.goal-text",))
                fill = ("fill", ("textarea.goal-text", typed))
                self.assertIn(focus, before)
                self.assertIn(fill, before)
                self.assertLess(before.index(focus), before.index(fill))
                self.assertNotIn(("click", ("button.goal-send",)), calls)
                hint = ("wait_for_selector", (".goal-hint:not(:empty)",))
                if over:
                    self.assertIn(hint, before)
                    self.assertLess(before.index(fill), before.index(hint))
                else:
                    self.assertNotIn(hint, calls)

    def test_the_guest_shot_goes_through_a_stand_in_serve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            now_s = time.time()
            fixture = shots.build_fixture(Path(tmp).resolve(), "guest-page", now_s)
            svc = shots.start_service(
                fixture, now_s, guest_dir=support.guest_socket_path(self).parent.parent)
            serve = None
            try:
                serve = shots._Serve(shots.guest_door(svc))

                def get(address, path):
                    connection = http.client.HTTPConnection(*address, timeout=5)
                    try:
                        connection.request("GET", path)
                        response = connection.getresponse()
                        return response.status, response.read()
                    finally:
                        connection.close()

                status, body = get(serve.address, "/api/state")
                self.assertEqual(status, 200)
                state = json.loads(body)
                self.assertNotIn("sharing", state)
                self.assertIn("owner/web", body.decode())
                self.assertNotIn("owner/api", body.decode())

                def at(seconds):
                    return datetime.fromtimestamp(int(now_s) + seconds, timezone.utc).isoformat()

                rows = state["pool"]["accounts"]
                self.assertEqual([r["label"] for r in rows], ["yours", "Account 2", "Account 3"])
                self.assertEqual(
                    [(r["week_left"], r["five_hour_left"], r["week_reset"], r["five_hour_reset"])
                     for r in rows],
                    [(5, 50, at(2 * 86400), at(3 * 3600)), (60, 75, at(3 * 86400), at(2 * 3600)),
                     (10, 40, at(5 * 86400), at(4 * 3600))])
                labelled = [s["account_label"] for s in all_sprints(state)
                            if s.get("account_label") is not None]
                self.assertEqual(labelled, ["Account 2"])
                self.assertNotIn(b"colleague-1", body)
                self.assertNotIn(b"work-main", body)
                self.assertNotIn(b"work-spare", body)
                status, body = get(serve.address, "/")
                self.assertEqual(status, 200)
                self.assertIn(service.DOOR_GUEST, body)
                status, body = get(svc.address, "/api/state")
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["sharing"]["colleagues"],
                                 [{"login": shots.COLLEAGUE, "projects": ["owner/web"]}])
                profiles = json.loads(body)["capacity"]["profiles"]
                self.assertEqual([p["profile"] for p in profiles],
                                 ["colleague-1", "work-main", "work-spare"])
                self.assertEqual(profiles[0]["owner"], shots.COLLEAGUE)
                self.assertEqual(min(profiles, key=lambda p: p["week_left"])["profile"], "colleague-1")
            finally:
                if serve is not None:
                    serve.close()
                svc.close()

    def test_the_sharing_shots_read_on_off_and_unreadable(self) -> None:
        cases = (("sharing-panel", True, True, shots.TAILNET, "serving"),
                 ("sharing-reached", True, True, shots.TAILNET, "serving"),
                 ("sharing-off", True, False, shots.TAILNET, "off"),
                 ("sharing-unreadable", False, True, None, "unreadable"))
        clients = {"sharing-panel": "this_host", "sharing-reached": "other_device"}
        for state, readable, shared, tailnet, serve in cases:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                now_s = time.time()
                fixture = shots.build_fixture(Path(tmp).resolve(), state, now_s)
                svc = shots.start_service(
                    fixture, now_s, guest_dir=support.guest_socket_path(self).parent.parent,
                    tailnet_readable=readable)
                try:
                    def read_sharing() -> dict:
                        connection = http.client.HTTPConnection(*svc.address, timeout=5)
                        try:
                            connection.request("GET", "/api/state")
                            return json.loads(connection.getresponse().read())["sharing"]
                        finally:
                            connection.close()

                    sharing = read_sharing()
                    self.assertEqual(sharing["shared"], shared)
                    self.assertEqual(sharing["tailnet"], tailnet)
                    self.assertEqual(sharing["state"], serve)
                    shots.guest_requests(state, shots.guest_door(svc))
                    sharing = read_sharing()
                    self.assertEqual(sharing["other_device_seen"], state == "sharing-reached")
                    last = sharing["last_request"]
                    if state in clients:
                        self.assertEqual(last["client"], clients[state])
                    else:
                        self.assertIsNone(last)
                finally:
                    svc.close()

    def test_the_harness_sends_each_door_its_own_headers(self) -> None:
        self.assertEqual(shots._guest_headers(("127.0.0.1", 9)), {"Host": shots.TAILNET})
        self.assertEqual(shots._guest_headers("/tmp/cg-x/g.sock"),
                         {"Host": "localhost", "X-Forwarded-Host": shots.TAILNET})

    def test_the_harness_opens_the_base_and_the_head_guest_door(self) -> None:
        def base(store, registry, *, port, guest_port=None, guest_token_path=None, **kwargs):
            pass

        folder = Path("/tmp/cg-x")
        self.assertEqual(shots.guest_door_kwargs(base, folder), {"guest_port": 0})
        self.assertEqual(shots.guest_door_kwargs(service.ConsoleService, folder),
                         {"guest_socket": folder / "guest" / "guest.sock"})
        tcp = shots._door_connection(("127.0.0.1", 9), 5)
        self.assertIsInstance(tcp, http.client.HTTPConnection)
        self.assertNotIsInstance(tcp, shots._UnixHTTPConnection)
        self.assertEqual((tcp.host, tcp.port), ("127.0.0.1", 9))
        self.assertIsInstance(shots._door_connection("/tmp/cg-x/g.sock", 5),
                              shots._UnixHTTPConnection)
        self.assertEqual(shots.guest_door(SimpleNamespace(guest_address=("127.0.0.1", 9))),
                         ("127.0.0.1", 9))
        self.assertEqual(
            shots.guest_door(SimpleNamespace(guest_socket="/tmp/g.sock", guest_address=None)),
            "/tmp/g.sock")

    @mock.patch.object(shots, "STYLE_CHECKS", ())
    def test_the_sharing_shot_opens_the_panel_only_where_the_page_has_one(self) -> None:
        for state in ("sharing-panel", "sharing-off", "sharing-unreadable", "sharing-reached"):
            for present, opens in (({"#sharing-open"}, True), (set(), False)):
                with self.subTest(state=state, opens=opens):
                    self.check_sharing_shot(state, present, opens)

    def check_sharing_shot(self, state: str, present: set, opens: bool) -> None:
        calls: list[tuple[str, tuple]] = []

        class Page:
            def goto(self, url):
                calls.append(("goto", (url,)))

            def wait_for_selector(self, selector):
                calls.append(("wait_for_selector", (selector,)))

            def query_selector(self, selector):
                return object() if selector in present else None

            def click(self, selector):
                calls.append(("click", (selector,)))

            def evaluate(self, expression, arg=None):
                if expression == shots.SCROLL_Y:
                    return 0.0
                if expression == "document.documentElement.scrollWidth":
                    return 480
                if expression in (shots.SHORT_CONTROLS, shots.ACTS_ROW):
                    return []
                return 0

            def screenshot(self, path, full_page):
                pass

            def close(self):
                pass

        class Browser:
            def new_page(self, viewport):
                return Page()

        with tempfile.TemporaryDirectory() as tmp:
            shots._shoot(Browser(), "http://console.test/", state, 480, Path(tmp))
        if not opens:
            self.assertNotIn(("click", ("#sharing-open",)), calls)
            self.assertNotIn(("wait_for_selector", ("#sharing:not([hidden])",)), calls)
            return
        click = calls.index(("click", ("#sharing-open",)))
        self.assertLess(click, calls.index(("wait_for_selector", ("#sharing:not([hidden])",))))

    def test_the_guest_shot_refuses_the_owner_page(self) -> None:
        door = "#console-door"
        for present, refused in (({door, "#capacity"}, True), ({door}, False)):
            with self.subTest(refused=refused), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(present)
                if refused:
                    with self.assertRaisesRegex(RuntimeError, "the guest shot is not the guest page"):
                        shots._shoot(browser, "http://console.test/", "guest-page", 480, Path(tmp))
                else:
                    shots._shoot(browser, "http://console.test/", "guest-page", 480, Path(tmp))
                self.assertIn("#top-who:not([hidden])", page.waits)

    def test_the_guest_shot_waits_for_the_pool_where_the_page_has_one(self) -> None:
        pool = ("#pool:not([hidden])", "#pool .pool-session time", ".sprint-account")
        for present, waits in (({"#console-door", "#pool"}, True), ({"#console-door"}, False)):
            with self.subTest(pool=waits), tempfile.TemporaryDirectory() as tmp:
                browser, page = fake_browser(present)
                shots._shoot(browser, "http://console.test/", "guest-page", 480, Path(tmp))
                if waits:
                    indexes = [page.waits.index(selector) for selector in pool]
                    self.assertEqual(indexes, sorted(indexes))
                    self.assertLess(page.waits.index("#top-who:not([hidden])"), indexes[0])
                else:
                    for selector in pool:
                        self.assertNotIn(selector, page.waits)

    def test_a_sheet_puts_the_shots_side_by_side_and_refuses_one_over_the_picture_limit(self) -> None:
        recorded = []

        class Row:
            def screenshot(self, path=None, **kwargs):
                Path(path).write_bytes(b"x" * size)

        class Page:
            def set_content(self, html, **kwargs):
                recorded.append(html)

            def locator(self, selector):
                return Row()

            def screenshot(self, path=None, **kwargs):
                Path(path).write_bytes(b"x" * size)

            def close(self):
                pass

        class Browser:
            def new_page(self, **kwargs):
                return Page()

        with tempfile.TemporaryDirectory() as tmp:
            a, b, out = Path(tmp) / "a.png", Path(tmp) / "b.png", Path(tmp) / "out-sheet.png"
            a.write_bytes(b"\x89PNG-first")
            b.write_bytes(b"\x89PNG-second")
            size = 10
            self.assertEqual(shots.sheet(Browser(), [a, b], out), out)
            self.assertTrue(out.exists())
            html = recorded[-1]
            first = base64.b64encode(a.read_bytes()).decode()
            second = base64.b64encode(b.read_bytes()).decode()
            self.assertIn("data:image/png;base64," + first, html)
            self.assertLess(html.index(first), html.index(second))
            size = pictures.MAX_BYTES + 1
            with self.assertRaisesRegex(RuntimeError, "out-sheet.png"):
                shots.sheet(Browser(), [a, b], out)

    def test_the_wait_and_pause_states_seed_a_report_that_states_them(self) -> None:
        calls = []

        class StandIn:
            now_s = 1_800_000_000.0

            def sprint(self, *args, **kwargs):
                calls.append(kwargs)
                return "0" * 16, "Add resumable uploads."

        for state, extra in (("waiting-until", {"wait_until": shots._iso(1_800_000_000.0 + 7200)}),
                             ("paused", {"paused": shots.PAUSE_REASON})):
            with self.subTest(state=state):
                calls.clear()
                shots._seed_state(StandIn(), state)
                self.assertEqual([c.get("report_extra") for c in calls], [extra])
                self.assertEqual(calls[0]["report"], 45 * shots.MINUTE)

    def test_a_composite_puts_the_named_states_sheets_side_by_side(self) -> None:
        recorded = []

        class Row:
            def screenshot(self, path=None, **kwargs):
                Path(path).write_bytes(b"x")

        class Page:
            def set_content(self, html, **kwargs):
                recorded.append(html)

            def locator(self, selector):
                return Row()

            def close(self):
                pass

        class Browser:
            def new_page(self, **kwargs):
                return Page()

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "waiting-until-sheet.png").write_bytes(b"\x89PNG-waiting")
            (tmp / "paused-sheet.png").write_bytes(b"\x89PNG-paused")
            got = shots.composite_sheet(Browser(), tmp, ("waiting-until", "paused"),
                                        "wait-and-pause.png")
            self.assertEqual(got, tmp / "wait-and-pause.png")
            waiting = base64.b64encode(b"\x89PNG-waiting").decode()
            paused = base64.b64encode(b"\x89PNG-paused").decode()
            self.assertLess(recorded[-1].index(waiting), recorded[-1].index(paused))

    def test_main_passes_the_states_and_the_composite_to_capture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(shots, "capture", return_value=[]) as capture, \
                    redirect_stdout(StringIO()) as out:
                self.assertEqual(shots.main(["--out", tmp, "--sheets", "--states",
                                             "waiting-until,paused", "--composite",
                                             "wait-and-pause.png"]), 0)
            self.assertEqual(capture.call_args.kwargs["states"], ("waiting-until", "paused"))
            self.assertEqual(capture.call_args.kwargs["composite"], "wait-and-pause.png")
            self.assertIn(str(Path(tmp) / "wait-and-pause.png"), out.getvalue())
            for argv in (["--composite", "x.png"], ["--states", "nope"]):
                with self.subTest(argv=argv), mock.patch.object(shots, "capture") as capture, \
                        redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    with self.assertRaises(SystemExit) as raised:
                        shots.main(["--out", tmp, *argv])
                    self.assertEqual(raised.exception.code, 2)
                    capture.assert_not_called()

    def test_main_asks_capture_for_sheets_only_with_the_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for flag, expected in (([], False), (["--sheets"], True)):
                with self.subTest(flag=flag), mock.patch.object(shots, "capture", return_value=[]) as capture, \
                        redirect_stdout(StringIO()):
                    self.assertEqual(shots.main(["--out", tmp, *flag]), 0)
                    self.assertIs(capture.call_args.kwargs["sheets"], expected)

    def test_the_actor_shots_wait_for_what_the_owner_judges_and_guest_steer_refuses_the_owner_page(self) -> None:
        door = "#console-door"
        with tempfile.TemporaryDirectory() as tmp:
            browser, page = fake_browser({door, "#capacity"})
            with self.assertRaisesRegex(RuntimeError, "the guest shot is not the guest page"):
                shots._shoot(browser, "http://console.test/", "guest-steer", 480, Path(tmp))
            browser, page = fake_browser({door})
            shots._shoot(browser, "http://console.test/", "guest-steer", 480, Path(tmp))
            self.assertIn("#top-who:not([hidden])", page.waits)
            judged = [w for w in page.waits if w != "#top-who:not([hidden])"][1:]
            self.assertEqual(judged, [".started-by", "text=Answered by", ".guest-wait",
                                      "#inbox button.approve"])
            browser, page = fake_browser({door})
            shots._shoot(browser, "http://console.test/", "owner-actors", 480, Path(tmp))
            self.assertEqual(page.waits[1:], [".started-by", "text=Answered by"])

    def test_the_actor_shots_of_a_base_page_wait_for_no_actor_part(self) -> None:
        self.assertIs(shots.reads_actors(), True)
        for state in ("guest-steer", "owner-actors"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(shots, "reads_actors", return_value=False):
                browser, page = fake_browser({"#console-door"})
                shots._shoot(browser, "http://console.test/", state, 480, Path(tmp))
                for part in (".started-by", "text=Answered by", ".guest-wait", "#inbox button.approve"):
                    self.assertNotIn(part, page.waits)

    def test_the_guest_shot_on_the_base_page_waits_for_no_guest_part(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            browser, page = fake_browser({"#capacity"})
            shots._shoot(browser, "http://console.test/", "guest-page", 480, Path(tmp))
        self.assertNotIn("#top-who:not([hidden])", page.waits)

    def test_every_fixture_path_is_temporary_and_never_a_real_one(self) -> None:
        real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        real_registry = real_home / ".agents" / "state" / "fleet" / "registry.json"
        protected = [*accounts_sandbox.real_accounts_dirs(), real_home / ".agents" / "state"]
        for state in shots.STATES:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                fixture = shots.build_fixture(root, state, time.time())
                paths = fixture_paths(fixture)
                for path in paths:
                    self.assertTrue(path.resolve().is_relative_to(root), path)
                self.assertFalse(accounts_sandbox.overlaps(paths, protected))
                self.assertNotEqual(fixture.registry.resolve(), real_registry.resolve())
                for value in shots.sandbox_environ(root).values():
                    self.assertTrue(Path(value).resolve().is_relative_to(root), value)
                self.assertEqual(
                    sorted(shots.sandbox_environ(root)),
                    ["CLAUDE_ACCOUNTS_DIR", "CLAUDE_CONFIG_DIR", "HOME", "XDG_CONFIG_HOME",
                     "XDG_STATE_HOME"])
                svc = shots.start_service(fixture, time.time())
                try:
                    self.assertEqual(svc.registry, fixture.registry)
                finally:
                    svc.close()

    def test_the_fixture_service_never_reads_a_real_keepalive_log(self) -> None:
        # On darwin the service's default ping log is under the real HOME; the fixture
        # must not read it, or today's real pings price as keepalive spend (#1135).
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as tmp:
            log = Path(home) / "Library/Logs/claude-cache-proxy.log"
            log.parent.mkdir(parents=True)
            log.write_text(json.dumps({
                "event": "ping", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "conversation": "real", "model": "claude-sonnet-4-6",
                "usage": {"input_tokens": 1000000}}) + "\n", encoding="utf-8")
            now_s = time.time()
            fixture = shots.build_fixture(Path(tmp), "finished-list", now_s)
            with mock.patch.dict(os.environ, {"HOME": home}), \
                    mock.patch.object(sys, "platform", "darwin"):
                svc = shots.start_service(fixture, now_s)
            try:
                days = json.loads(svc.view_bytes)["spend"]["days"]
            finally:
                svc.close()
            self.assertEqual([d["total"]["dollars"] for d in days if d["total"]["dollars"]], [])

    def test_each_look_state_carries_a_before_and_an_after_picture_the_console_serves(self) -> None:
        for state in ("look-card", "look-moved", "look-failed"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                now_s = time.time()
                fixture = shots.build_fixture(Path(tmp), state, now_s)
                svc = shots.start_service(fixture, now_s)
                try:
                    view = json.loads(svc.view_bytes)
                    pictures_dir = svc.pictures_dir
                finally:
                    svc.close()
                card = view["inbox"]["open"][0]
                self.assertEqual([p["pair"] for p in card["pictures"]], ["before", "after"])
                self.assertEqual(len({p["id"] for p in card["pictures"]}), 2)
                for picture in card["pictures"]:
                    data = (pictures_dir / picture["id"]).read_bytes()
                    self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_the_adoption_failed_state_refuses_a_click_and_the_card_leaves_the_inbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            now_s = time.time()
            fixture = shots.build_fixture(Path(tmp), "adoption-failed", now_s)
            svc = shots.start_service(fixture, now_s)
            try:
                (card,) = json.loads(svc.view_bytes)["inbox"]["open"]
                with self.assertRaises(sprints.Refused) as refused:
                    svc.merge_adoption(shots.REGISTER_PLAN_ID, card["number"], card["commit"])
                self.assertEqual(str(refused.exception), approve.MERGED_ELSEWHERE)
                self.assertEqual(
                    [i for i in json.loads(svc.view_bytes)["inbox"]["open"]
                     if i["reason"] == "adoption"], [])
            finally:
                svc.close()

    def test_each_fixture_view_shows_its_state(self) -> None:
        for state in shots.STATES:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                now_s = time.time()
                fixture = shots.build_fixture(Path(tmp), state, now_s)
                launches: list = []
                svc = shots.start_service(fixture, now_s, launches)
                try:
                    view = json.loads(svc.view_bytes)
                finally:
                    svc.close()
                sprints = all_sprints(view)
                running = [s for s in sprints if s["ended_at"] is None]
                ended = [s for s in sprints if s["ended_at"] is not None]
                self.assertEqual(launches, [])
                for sprint in running:
                    if state == "failed-start":
                        continue
                    self.assertEqual(sprint["manager_state"], "started", sprint["title"])
                    self.assertIsNone(sprint["manager_text"], sprint["title"])
                    self.assertFalse(sprint["now_text"].startswith("Working on"), sprint["title"])
                    self.assertNotEqual(sprint["now_text"], sprint["title"])
                    self.assertNotEqual(sprint["now_text"], sprint["status"])
                    self.assertEqual(
                        [m for m in sprint["messages"]
                         if m["kind"] == "approved" and m["state"] == "picked_up"], [])
                latest = [s["messages"][-1] for s in running if s["messages"]]
                if state == "live-several":
                    self.assertEqual(len(running), 3)
                    self.assertEqual(
                        len({p["project_id"] for p in entries_of(view) if p.get("sprints")}), 2)
                    self.assertEqual({s["ball"] for s in running},
                                     {"manager", "owner", "nobody"})
                elif state == "waiting-on-you":
                    self.assertEqual([s["ball"] for s in running], ["owner"])
                    self.assertEqual(
                        running[0]["now_text"],
                        "waiting for your answer: Which store should the checkpoint use?")
                elif state == "stuck":
                    self.assertEqual([s["ball"] for s in running], ["nobody"])
                    self.assertEqual(running[0]["now_text"],
                                     "last seen building 1 of 2: the upload form")
                elif state == "manager-cannot-hear":
                    self.assertEqual([s["ball"] for s in running], ["owner"])
                    self.assertEqual(
                        running[0]["now_text"],
                        "the manager cannot hear the console: bring it back or drop the sprint")
                elif state == "waiting-until":
                    self.assertEqual(running[0]["now_text"], "waiting until")
                    self.assertEqual((running[0]["ball"], running[0]["ball_text"]),
                                     ("waiting", "waiting"))
                    self.assertLess(
                        abs(datetime.fromisoformat(running[0]["now_until"]).timestamp()
                            - (now_s + 2 * 3600)), 1)
                elif state == "paused":
                    self.assertEqual(running[0]["now_text"], "paused: " + shots.PAUSE_REASON)
                    self.assertEqual((running[0]["ball"], running[0]["ball_text"]),
                                     ("paused", "paused"))
                    self.assertIsNone(running[0]["now_until"])
                elif state == "tell-box-open":
                    self.assertEqual(len(running), 1)
                    self.assertEqual(running[0]["messages"], [])
                    self.assertIsInstance(running[0]["tell_text"], str)
                elif state == "message-sent":
                    self.assertEqual(len(running[0]["messages"]), 1)
                    self.assertEqual(latest[-1]["state"], "sent")
                elif state == "message-picked-up":
                    self.assertEqual(latest[-1]["state"], "picked_up")
                elif state == "message-replied":
                    self.assertEqual(latest[-1]["state"], "replied")
                    self.assertTrue(latest[-1]["new"])
                    self.assertIsInstance(view["new_replies_text"], str)
                elif state == "message-not-picked-up":
                    self.assertEqual(latest[-1]["state"], "not_picked_up")
                    self.assertTrue(latest[-1]["action_text"])
                elif state == "finished-list":
                    self.assertGreaterEqual(len(ended), 2)
                    self.assertTrue(any(s["closing"] for s in ended))
                elif state == "owner-check":
                    self.assertEqual([s["ball"] for s in running], ["manager"])
                    self.assertEqual(running[0]["now_text"], "building 1 of 3: the upload form")
                    self.assertEqual(
                        [c["text"] for c in running[0]["checks"]],
                        ["Your check: Do the before and after pictures read well?"])
                    self.assertEqual(view["statement"]["inbox_items"], 1)
                elif state == "nothing-running":
                    self.assertEqual(running, [])
                elif state == "failed-start":
                    (sprint,) = running
                    self.assertEqual(sprint["manager_state"], "failed")
                    self.assertTrue(sprint["retry"])
                    self.assertEqual(sprint["now_text"],
                                     "waiting for you: the manager failed to start")
                    (item,) = [i for i in view["inbox"]["open"]]
                    self.assertEqual(item["reason"], "failed_start")
                    self.assertEqual(item["last_reason"],
                                     "this account does not trust the project's folder")
                    self.assertNotIn("/home/", json.dumps(view))
                elif state == "waiting-its-turn":
                    self.assertEqual(
                        [(s["state"], s["ball"], s["now_text"]) for s in running],
                        [("on_track", "manager", "waiting its turn to merge")])
                    web = next(p for p in entries_of(view) if p.get("project_id") == "owner/web")
                    lone = next(d for s in web["outside_sprints"]["sessions"]
                                for d in s["deliveries"] if d["run_id"] == "wf_l1")
                    self.assertEqual(
                        (lone["quiet"], lone["moved_text"], lone["wait_text"]),
                        (False, "waiting its turn to merge", "waiting its turn to merge"))
                elif state in ("goal-open", "goal-near", "goal-over"):
                    other = shots.build_fixture(Path(tmp) / "other", "tell-box-open", now_s)
                    again = shots.start_service(other, now_s)
                    try:
                        self.assertEqual(
                            [s["title"] for s in running],
                            [s["title"] for s in all_sprints(json.loads(again.view_bytes))])
                    finally:
                        again.close()
                elif state == "inbox-card":
                    self.assertEqual(len(view["inbox"]["open"][0]["questions"][0]["options"]), 2)
                elif state in ("activation-tooling", "activation-host"):
                    self.assertEqual(running, [])
                    self.assertEqual(view["activation"], {
                        "text": shots.ACTIVATION_SHOWN[state][0],
                        "state": "pending", "commit": "1258" * 10,
                        "root": str(fixture.projects[1]), "activate": True})  # sorted: api
                    self.assertEqual(view["statement"]["inbox_items"], 0)
                elif state in shots.REGISTER_STATES:
                    registration = view["registration"]
                    self.assertEqual(registration["name"], "sample-app")
                    self.assertEqual(running, [])
                    reconcile = state.startswith("register-reconcile")
                    proposes = shots.proposes_reconcile() if reconcile else shots.shows_facts()
                    if state.endswith("-apply"):
                        (card,) = view["inbox"]["open"]
                        self.assertEqual(card["reason"], "register_apply")
                        self.assertEqual(card["questions"][0]["options"], ["Apply it", "Not now"])
                        self.assertEqual(card["lines"][-2:], shots.REGISTER_PLAN_LINES)
                        self.assertEqual(card["lines"][:-2],
                                         [shots.PROPOSAL_LINE] if proposes and reconcile else [])
                        self.assertIsNone(registration["draft"])
                    elif reconcile:
                        self.assertEqual(view["inbox"]["open"], [])
                        if proposes:
                            (row,) = registration["draft"]
                            self.assertEqual(row["field"], "commit-environment")
                            self.assertEqual(row["line"], shots.PROPOSAL_LINE)
                        else:
                            self.assertIsNone(registration["draft"])
                    else:
                        self.assertEqual(view["inbox"]["open"], [])
                        rows = {row["field"]: row["line"] for row in registration["draft"]}
                        self.assertEqual(rows.get("project-identity"),
                                         shots.FACT_LINE if shots.shows_facts() else None)
                elif state in shots.ADOPTION_STATES:
                    (card,) = [i for i in view["inbox"]["open"] if i["reason"] == "adoption"]
                    if state in ("adoption-merge", "adoption-failed"):
                        self.assertEqual((card["merge"], card["why"]), (True, None))
                    else:
                        self.assertEqual((card["merge"], card["why"]), (False, approve.MOVED_WHY))
                elif state in ("question-words", "question-refused"):
                    (asked,) = view["inbox"]["open"]
                    (look,) = asked["questions"]
                    self.assertEqual(look["options"],
                                     ["Approve", "Approve with one fix", "Ask for changes"])
                    self.assertEqual(look["recommended_index"], 0)
                    self.assertEqual(look["needs_words_index"], [1, 2])
                elif state == "accounts-panel":
                    self.assertEqual(
                        sorted(e["profile"] for e in view["capacity"]["profiles"]),
                        ["work-main", "work-spare"])
                elif state in ("notices-fold", "notice-post-open"):
                    self.assertEqual(
                        sorted(s["title"] for s in running),
                        ["Add resumable uploads", "Fix the settings page"])
                    web = next(p for p in entries_of(view) if p["project_id"] == "owner/web")
                    self.assertTrue(web["notice_post"])
                    self.assertEqual(
                        [(n["poster"], n["kind"], n["text"], n["owner"]) for n in web["notices"]],
                        [("You", "heads-up", "routes are frozen until Friday", True),
                         ("Fix the settings page", "claim", "reworking the settings form",
                          False),
                         ("Add resumable uploads", "claim", "resuming an upload from its row",
                          False)])
                    self.assertEqual(
                        [o["text"] for o in web["overlaps"]],
                        ["Add resumable uploads and Fix the settings page both fix a live fault "
                         "in python/agent_tools/console/page.html; the rule could not decide "
                         "which lands first"])
                    self.assertFalse(shots.overlap_card())
                    self.assertEqual(
                        [i for i in view["inbox"]["open"] if i.get("reason") == "question"], [])
                elif state == "live-fault":
                    self.assertEqual([s["title"] for s in running], ["Fix the settings page"])
                    faults = running[0]["live_faults"]
                    self.assertEqual(len(faults), 1)
                    self.assertIsInstance(faults[0]["id"], int)
                    self.assertIsInstance(faults[0]["at"], str)
                    self.assertEqual(faults, [{
                        "id": faults[0]["id"], "issue": 12,
                        "observed": shots.LIVE_FAULT_OBSERVED, "when": shots.LIVE_FAULT_WHEN,
                        "proven": shots.LIVE_FAULT_PROVEN, "at": faults[0]["at"],
                        "text": "Live fault in production on #12: saving the settings form "
                                "drops the billing address, seen 12:10 UTC today, proven by a "
                                "saved form read back from the production database"}])
                    self.assertEqual(view["statement"]["inbox_items"], 0)
                elif state in ("ask-box", "ask-goal"):
                    web = next(p for p in entries_of(view) if p["project_id"] == "owner/web")
                    threads = web["questions"]["threads"]
                    asked = [q for t in threads for q in t["questions"]]
                    self.assertEqual([len(t["questions"]) for t in threads], [1, 1])
                    self.assertEqual([q["state"] for q in asked], ["working", "answered"])
                    self.assertEqual([q["question"] for q in asked],
                                     [shots.ASK_WORKING_QUESTION, shots.ASK_ANSWERED_QUESTION])
                    self.assertEqual(asked[1]["read_text"], shots.ASK_READ_LINE)
                    self.assertEqual(asked[1]["ran_text"], "Ran: just build")
                    self.assertEqual(asked[1]["answer"], shots.ASK_ANSWER_SUMMARY)
                    self.assertLessEqual(len(shots.ASK_ANSWER_SUMMARY), 45)
                    self.assertEqual(view["statement"]["inbox_items"], 0)
                elif state == "question-read":
                    web = next(p for p in entries_of(view) if p["project_id"] == "owner/web")
                    threads = web["questions"]["threads"]
                    self.assertEqual([len(t["questions"]) for t in threads], [1])
                    asked = threads[0]["questions"][0]
                    self.assertEqual(asked["state"], "answered")
                    self.assertEqual(asked["question"], shots.READ_QUESTION)
                    self.assertGreaterEqual(len(asked["answer"]), 1200)
                    for marker in ("**", "\n- ", "`", "```",
                                   "\n" + shots.READ_FENCED_LINE + "\n"):
                        self.assertIn(marker, asked["answer"])
                    self.assertNotIn("--since=7.days", asked["read_text"])
                    self.assertEqual(len(shots.READ_CHOICES), 3)
                    self.assertEqual(asked["back_choices"], list(shots.READ_CHOICES))
                    self.assertTrue(asked["back_text"].startswith("Question for you: "))
                    self.assertEqual(running, [])
                elif state in shots.DEEPER_STATES:
                    web = next(p for p in entries_of(view) if p["project_id"] == "owner/web")
                    self.assertEqual(web["questions"]["count"], 2)
                    self.assertEqual(view["statement"]["inbox_items"], 0)
                    self.assertEqual(running, [])
                elif state in ("questions-closed", "questions-open"):
                    web = next(p for p in entries_of(view) if p["project_id"] == "owner/web")
                    self.assertEqual(web["questions"]["count"], 2)
                    newest = web["questions"]["threads"][0]["questions"]
                    self.assertEqual([q["question"] for q in newest],
                                     [shots.THREAD_QUESTION, shots.FOLLOW_QUESTION])
                    self.assertEqual([q["state"] for q in newest], ["answered", "answered"])
                    self.assertEqual(newest[1]["read_text"], shots.FOLLOW_READ_LINE)
                    self.assertEqual(view["statement"]["inbox_items"], 0)
                    self.assertEqual(running, [])
                    self.assertTrue(all(p.get("quiet") for p in entries_of(view)))
                days = (view["spend"] or {"days": []})["days"]
                self.assertIsNotNone(view["spend"])
                if state == "desk-spend":
                    self.assertEqual(len(running), 1)
                    self.assertGreaterEqual(len(ended), 1)
                    self.assertLessEqual(
                        {running[0]["sprint_id"], ended[0]["sprint_id"]},
                        set().union(*(d["sprint"] for d in days[-7:])))
                    line = next(p for p in entries_of(view)
                                if p.get("project_id") == "owner/web")["outside_sprints"]
                    outside = {s["session_id"]: s for s in line["sessions"]}
                    self.assertEqual(
                        [d["run_id"] for d in outside["outside-1136"]["deliveries"]], ["wf_9"])
                    self.assertIn("wf_9", set().union(*(d["run"] for d in days[-7:])))
                    self.assertGreater(days[-1]["total"]["dollars"], 0)
                elif state == "spend-page":
                    self.assertGreater(days[-1]["total"]["dollars"], 0)
                    self.assertGreaterEqual(
                        sum(1 for d in days[-7:] if d["total"]["dollars"] > 0), 4)
                    self.assertGreaterEqual(
                        len(set().union(*(d["phase"] for d in days[-7:]))), 2)
                    self.assertIn(running[0]["sprint_id"],
                                  set().union(*(d["sprint"] for d in days[-7:])))
                elif state in shots.DEEPER_STATES:
                    self.assertGreater(days[-1]["total"]["dollars"], 0)
                else:
                    self.assertEqual(days[-1]["total"]["dollars"], 0)


class ScreenshotStyleTableTest(unittest.TestCase):
    def test_only_the_guest_rows_read_the_guest_pages(self) -> None:
        named = sorted(row.name for row in shots.STYLE_CHECKS
                       if set(row.states) & {"guest-page", "guest-steer"})
        self.assertEqual([name for name in named if not name.startswith("guest-")], [])

    def test_each_guest_row_reads_both_guest_pages_at_both_widths(self) -> None:
        guest = {row.name: row for row in shots.STYLE_CHECKS if row.name.startswith("guest-")}
        self.assertEqual(sorted(guest), ["guest-tick-height", "guest-tick-width",
                                         "guest-top-hidden-display"])
        for name, row in guest.items():
            with self.subTest(name):
                self.assertEqual(set(row.states), {"guest-page", "guest-steer"})
                self.assertEqual(set(row.widths), set(shots.WIDTHS))

    def test_every_style_check_is_well_formed(self) -> None:
        names = [row.name for row in shots.STYLE_CHECKS]
        self.assertEqual(len(names), len(set(names)))
        mapped = {name for entry in MOVED for name in entry.rows}
        for row in shots.STYLE_CHECKS:
            with self.subTest(row.name):
                self.assertRegex(row.name, r"^[a-z0-9-]+$")
                self.assertTrue(row.states and set(row.states) <= set(shots.STATES))
                self.assertTrue(row.widths and set(row.widths) <= set(shots.STYLE_WIDTHS))
                self.assertIn(row.want, shots.WANTS)
                self.assertTrue("{" in row.broken and "}" in row.broken)
                if row.probe:
                    self.assertIn("data-style-probe", row.probe)
                if row.compare_probe:
                    self.assertIn("data-style-probe", row.compare_probe)
                self.assertLessEqual(
                    set(row.forced), {"hover", "active", "focus", "focus-visible", "focus-within"})
                if row.fixture:
                    self.assertIn("question-read", row.states)
                self.assertIn(row.name, mapped)

    def test_every_moved_property_has_a_checking_row(self) -> None:
        missing = uncovered(MOVED, shots.STYLE_CHECKS)
        self.assertEqual(missing, [], "\n".join(missing))

    def test_the_coverage_check_names_a_property_or_width_no_row_reads(self) -> None:
        entry = Moved("t", ".held.blocks", "white-space", (1440, 480), ("h",))
        both = style_row("h", prop="text-overflow", widths=(1440, 480))
        self.assertEqual(uncovered([entry], [both]),
                         ["t .held.blocks white-space @(1440, 480): no row reads it"])
        narrow = style_row("h", prop="white-space", widths=(1440,))
        self.assertEqual(uncovered([entry], [narrow]),
                         ["t .held.blocks white-space @(1440, 480): no row reads it"])
        small = style_row("h2", prop="white-space", widths=(480,))
        entry = Moved("t", ".held.blocks", "white-space", (1440, 480), ("h", "h2"))
        self.assertEqual(uncovered([entry], [narrow, small]), [])
        longhands = [style_row(f"f{n}", prop=prop, widths=(1440, 480))
                     for n, prop in enumerate(LONGHANDS["font"])]
        entry = Moved("t", ".held.blocks", "font", (1440,), tuple(row.name for row in longhands))
        self.assertEqual(uncovered([entry], longhands), [])
        entry = Moved("t", ".held.blocks", "font", (1440,), tuple(row.name for row in longhands[:4]))
        self.assertEqual(uncovered([entry], longhands),
                         ["t .held.blocks font @(1440,): no row reads it"])
        entry = Moved("t", ".held.blocks", "white-space", (1440,), ("x",))
        self.assertEqual(uncovered([entry], [narrow]), ["t: no row x"])
        other = Moved("t", ".other", "white-space", (1440,), ("h",))
        self.assertEqual(uncovered([other], [narrow]),
                         ["t .other white-space @(1440,): no row reads it"])
        self.assertEqual(uncovered([dataclasses.replace(other, via="hand")], [narrow]), [])
        listed = style_row("h", selector=".a, .held.blocks", widths=(1440,))
        self.assertEqual(
            uncovered([dataclasses.replace(other, selector=".held.blocks")], [listed]), [])

    def test_a_value_a_removed_line_named_is_read_by_the_row_that_wants_it(self) -> None:
        # `"flex"` in `.get("display", "flex")` is a value of `display`, not the property `flex`;
        # an entry with a `via` is read by a listed row whose `equals` value is that literal.
        entry = Moved("t", ".row-head", "flex", (1440,), ("d",), via="the value display equals")
        display = style_row("d", selector=".row-head", prop="display", value="flex")
        self.assertEqual(uncovered([entry], [display]), [])
        for name, row, wanted in (
                ("another value", dataclasses.replace(display, value="block"), entry),
                ("another width", dataclasses.replace(display, widths=(480,)), entry),
                ("another want", dataclasses.replace(display, want="starts"), entry),
                ("no via", display, dataclasses.replace(entry, via=""))):
            with self.subTest(name):
                self.assertEqual(uncovered([wanted], [row]),
                                 ["t .row-head flex @(1440,): no row reads it"])

    def test_every_moved_test_is_gone_or_stripped(self) -> None:
        import ast
        ids = {entry.test for entry in MOVED}
        self.assertLessEqual(STRIPPED | set(RENAMED), ids)
        root = Path(__file__).resolve().parents[1]

        def body(test_id):
            path, cls, method = test_id.split("::")
            file = root / path
            if not file.is_file():
                return None
            text = file.read_text(encoding="utf-8")
            for node in ast.parse(text).body:
                if isinstance(node, ast.ClassDef) and node.name == cls:
                    for item in node.body:
                        if (isinstance(item, ast.FunctionDef)
                                and item.name == RENAMED.get(test_id, method)):
                            return ast.get_source_segment(text, item)
            return None

        for test_id in sorted(ids):
            with self.subTest(test_id):
                found = body(test_id)
                if test_id in STRIPPED:
                    self.assertIsNotNone(found)
                    self.assertIsNone(SOURCE_READING.search(found))
                else:
                    self.assertIsNone(found)

    def test_no_chromium_run_opens_a_browser_inside_another_or_waits_without_a_bound(self) -> None:
        import ast
        sources = {"module": Path(shots.__file__).read_text(encoding="utf-8"),
                   "tests": Path(__file__).read_text(encoding="utf-8")}
        trees = {label: ast.parse(text) for label, text in sources.items()}
        opens = {"capture", "main", "sandboxed_capture", "styled", "read_pages", "sync_playwright"}

        def name_of(call):
            if isinstance(call.func, ast.Name):
                return call.func.id
            return call.func.attr if isinstance(call.func, ast.Attribute) else None

        def calls_in(nodes):
            return [c for node in nodes for c in ast.walk(node) if isinstance(c, ast.Call)]

        def unbounded(value):
            return isinstance(value, ast.Constant) and value.value in (0, None)

        bad = []
        for label, tree in trees.items():
            for node in ast.walk(tree):
                if isinstance(node, ast.With) and any(
                        isinstance(item.context_expr, ast.Call)
                        and name_of(item.context_expr) == "sync_playwright" for item in node.items):
                    bad += [f"{label}:{c.lineno} opens a browser inside one ({name_of(c)})"
                            for c in calls_in(node.body) if name_of(c) in opens]
            for call in calls_in([tree]):
                if (any(k.arg == "timeout" and unbounded(k.value) for k in call.keywords)
                        or (name_of(call) in ("set_default_timeout", "set_default_navigation_timeout")
                            and call.args and isinstance(call.args[0], ast.Constant)
                            and call.args[0].value == 0)):
                    bad.append(f"{label}:{call.lineno} waits without a bound")
        opening = sorted(f.name for f in ast.walk(trees["module"]) if isinstance(f, ast.FunctionDef)
                         and any(name_of(c) == "sync_playwright" for c in calls_in([f])))
        if opening != ["capture"]:
            bad.append(f"the module opens a browser in {opening}")
        awaiting = sorted(name for name, value in vars(shots).items()
                          if isinstance(value, str) and "await " in value)
        if awaiting != ["STYLE_SETTLE"]:
            bad.append(f"page scripts that await: {awaiting}")
        if re.search(r"for \(let tries = 0; tries < \d+; tries\+\+\)", shots.STYLE_SETTLE) is None:
            bad.append("STYLE_SETTLE waits without a bound")
        self.assertEqual(bad, [])

    def test_the_look_card_opens_the_viewer_before_its_style_reading(self) -> None:
        self.assertEqual(shots.STYLE_STEPS["look-card"], ("button.pic-thumb",))

    def test_style_applies_only_to_the_page_beside_the_module(self) -> None:
        source = Path(shots.__file__).resolve().parents[1] / "python/agent_tools/console"
        with tempfile.TemporaryDirectory() as tmp:
            served = Path(tmp)
            for name in ("page.html", "spend.html"):
                shutil.copy(source / name, served / name)
            self.assertTrue(shots.style_applies(served))
            with (served / "page.html").open("ab") as handle:
                handle.write(b" ")
            self.assertFalse(shots.style_applies(served))
            shutil.copy(source / "page.html", served / "page.html")
            (served / "spend.html").unlink()
            self.assertFalse(shots.style_applies(served))


class ScreenshotStyleTest(unittest.TestCase):
    def styled(self, html, rows, mutation=None, only=None, width=1440):
        """Load `html` alone in one `width`x900 Chromium page and return the style misses."""
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
            try:
                page = browser.new_page(viewport={"width": width, "height": 900})
                page.set_content(html)
                found = shots.read_style(page, rows, mutation=mutation, only=only)
                self.last_leftover = page.evaluate(
                    "document.querySelectorAll('[data-style-probe], #style-mutation').length")
                return found
            finally:
                browser.close()

    def test_each_want_kind_passes_its_value_and_names_a_miss(self) -> None:
        html = ("<style>.a{white-space:nowrap;margin-top:12px;color:color-mix(in srgb, "
                "rgb(245, 169, 127) 100%, white 0%)} .b{margin-top:8px}</style>"
                '<p class="a">x</p><p class="b">y</p>')
        white = "white-space"
        margin = "margin-top"
        rows = [
            ("equals-ok", style_row("equals-ok", selector=".a", prop=white, value="nowrap"), None),
            ("equals-bad", style_row("equals-bad", selector=".a", prop=white, value="normal"),
             ".a white-space is nowrap"),
            ("colour", style_row("colour", selector=".a", prop="color",
                                 value="rgb(245, 169, 127)"), None),
            ("in-ok", style_row("in-ok", selector=".a", prop=white, want="in", value="nowrap|pre"),
             None),
            ("in-bad", style_row("in-bad", selector=".a", prop=white, want="in",
                                 value="normal|pre"), ".a white-space is nowrap"),
            ("not-ok", style_row("not-ok", selector=".a", prop=white, want="not",
                                 value="normal"), None),
            ("not-bad", style_row("not-bad", selector=".a", prop=white, want="not",
                                  value="nowrap"), ".a white-space is nowrap"),
            ("starts-ok", style_row("starts-ok", selector=".a", prop=white, want="starts",
                                    value="now"), None),
            ("starts-bad", style_row("starts-bad", selector=".a", prop=white, want="starts",
                                     value="pre"), ".a white-space is nowrap"),
            ("min-ok", style_row("min-ok", selector=".a", prop=margin, want="min", value="12"),
             None),
            ("min-bad", style_row("min-bad", selector=".a", prop=margin, want="min", value="13"),
             ".a margin-top is 12px"),
            ("max-ok", style_row("max-ok", selector=".a", prop=margin, want="max", value="12"),
             None),
            ("max-bad", style_row("max-bad", selector=".a", prop=margin, want="max", value="11"),
             ".a margin-top is 12px"),
            ("same-bad", style_row("same-bad", selector=".a", prop=margin, want="same_as",
                                   value=".b"), ".a margin-top is 12px"),
            ("same-white", style_row("same-white", selector=".a", prop=white, want="same_as",
                                  value=".b"), ".a white-space is nowrap"),
            ("gt-ok", style_row("gt-ok", selector=".a", prop=margin, want="gt", value=".b"),
             None),
            ("gt-bad", style_row("gt-bad", selector=".b", prop=margin, want="gt", value=".a"),
             ".b margin-top is 8px"),
        ]
        misses = self.styled(html, [row for _, row, _ in rows])
        self.assertEqual(
            list(misses), [f"{name}: {text}" for name, _, text in rows if text is not None])
        absent = style_row("gone", selector=".missing")
        self.assertEqual(self.styled(html, [absent]), ("gone: .missing is absent",))
        hidden = style_row("hidden", selector=".h", prop="color", every=True)
        self.assertEqual(self.styled('<p class="h" style="display:none">x</p>', [hidden]),
                         ("hidden: .h is absent",))
        loose = style_row("loose", selector=".a", prop=white, want="same_as", value=".nowhere")
        self.assertEqual(self.styled(html, [loose]), ("loose: .nowhere is absent",))
        every = style_row("every", selector="p", prop=margin, want="max", value="10", every=True)
        self.assertEqual(self.styled(html, [every]), ("every: p.a margin-top is 12px",))

    def test_each_row_reads_its_own_probe_and_leaves_nothing_behind(self) -> None:
        html = ('<style>#h .p{color:rgb(1, 2, 3)} #h .p.q{color:rgb(4, 5, 6)}</style>'
                '<div id="h"></div>')
        rows = [
            style_row("one", selector=".p", prop="color", value="rgb(1, 2, 3)", host="#h",
                      probe='<span class="p" data-style-probe></span>'),
            style_row("two", selector=".p", prop="color", value="rgb(4, 5, 6)", host="#h",
                      probe='<span class="p q" data-style-probe></span>'),
            style_row("root", selector=".p", prop="color", value="rgb(1, 2, 3)", host="#h",
                      probe='<span class="p" data-style-probe><span class="p q"></span></span>'),
        ]
        self.assertEqual(self.styled(html, rows), ())
        self.assertEqual(self.last_leftover, 0)
        for row in rows:
            with self.subTest(row.name):
                self.assertEqual(self.styled(html, rows, only=row.name), ())
        page_row = style_row("plain", selector=".p", prop="color", value="rgb(1, 2, 3)")
        self.assertEqual(self.styled(html, [*rows, page_row]), ("plain: .p is absent",))
        self.assertEqual(self.last_leftover, 0)

    def test_a_comparison_probe_is_read_beside_a_page_subject(self) -> None:
        html = '<style>.s{font-size:17px} #h .c{font-size:17px}</style><p class="s">x</p><div id="h"></div>'
        row = style_row("beside", selector=".s", prop="font-size", want="same_as", value=".c",
                        compare_probe='<span class="c" data-style-probe></span>',
                        compare_host="#h")
        self.assertEqual(self.styled(html, [row]), ())
        changed = html.replace("#h .c{font-size:17px}", "#h .c{font-size:16px}")
        self.assertEqual(self.styled(changed, [row]), ("beside: .s font-size is 17px",))
        bare = style_row("bare", selector=".s", prop="font-size", want="same_as", value=".c")
        self.assertEqual(self.styled(html.replace("#h .c{", "#h .z{"), [bare]),
                         ("bare: .c is absent",))

    def test_a_forced_pseudo_class_is_read_after_its_transition_settles(self) -> None:
        html = ("<style>button{color:rgb(9, 9, 9);transition:color 10s} "
                "button:hover{color:rgb(1, 2, 3)}</style><button>x</button>")
        forced = style_row("hovered", selector="button", prop="color", value="rgb(1, 2, 3)",
                           forced=("hover",))
        self.assertEqual(self.styled(html, [forced]), ())
        plain = style_row("plain", selector="button", prop="color", value="rgb(1, 2, 3)")
        self.assertEqual(self.styled(html, [plain]), ("plain: button color is rgb(9, 9, 9)",))

    def test_reduced_motion_is_read_from_a_specimen_that_moves_without_it(self) -> None:
        motion = ("@media (prefers-reduced-motion: reduce) { *, *::before, *::after { "
                  "animation-duration: .001ms !important; animation-delay: 0s !important; "
                  "transition-duration: .001ms !important } }")
        base = ('<style>.m i, .m i::before, .m i::after { content: ""; transition: opacity 1s; '
                'animation: none 1s } %s</style><span class="m"><i></i></span>')
        for pseudo in ("", "::before", "::after"):
            for prop in ("transition-duration", "animation-duration"):
                def row(name, **kw):
                    return style_row(name, selector=".m i", prop=prop, pseudo=pseudo, **kw)
                reduced = row("reduced", want="max", value="0.000001", reduced_motion=True)
                moving = row("moving", want="max", value="0.000001")
                free = row("free", want="min", value="0.5")
                with self.subTest(pseudo=pseudo, prop=prop):
                    self.assertEqual(self.styled(base % motion, [reduced, free]), ())
                    self.assertEqual(self.styled(base % motion, [moving]),
                                     (f"moving: .m i{pseudo} {prop} is 1s",))
                    self.assertEqual(
                        [m.split(":")[0] for m in self.styled(base % "", [reduced, free])],
                        ["reduced"])

    def test_a_mutation_breaks_the_row_it_names(self) -> None:
        html = ("<style>.a{white-space:nowrap}.b{margin-top:8px}</style>"
                '<p class="a">x</p><p class="b">y</p>')
        rows = [style_row("a", selector=".a"),
                style_row("b", selector=".b", prop="margin-top", value="8px")]
        mutation = ".a { white-space: normal !important }"
        self.assertEqual(self.styled(html, rows, mutation=mutation, only="a"),
                         ("a: .a white-space is normal",))
        self.assertEqual(self.last_leftover, 0)
        self.assertEqual(self.styled(html, rows, mutation=mutation, only="b"), ())

    def test_none_peach_names_a_peach_element_outside_the_allowed(self) -> None:
        row = style_row("r", selector="body", prop="color", want="none_peach",
                        value=".needs, .needs *")
        peach = "rgb(245, 169, 127)"
        mixed = f"color-mix(in srgb, {peach} 100%, white 0%)"

        def page(inner):
            return self.styled(f"<body>{inner}</body>", [row])

        found = page(f'<p class="x" style="color: {peach}">x</p>')
        self.assertIn(f"r: p.x color is {peach}", found)
        self.assertTrue(all(miss.startswith("r: p.x ") for miss in found), found)
        self.assertEqual(page(f'<div class="needs"><p class="x" style="color: {peach}">x</p></div>'), ())
        self.assertEqual(page('<p class="x">x</p>'), ())
        (mix, *_rest) = page(f'<p class="x" style="color: {mixed}">x</p>')
        self.assertTrue(mix.startswith("r: p.x color is color(srgb "), mix)
        self.assertEqual(page(f'<p class="x" style="box-shadow: 0 0 0 1px {peach}">x</p>'),
                         (f"r: p.x box-shadow is {peach}",))
        gone = style_row("g", selector=".missing", want="none_peach", value=".needs")
        self.assertEqual(self.styled("<p>x</p>", [gone]), ("g: .missing is absent",))

    def test_palette_takes_its_list_and_names_a_stray_colour(self) -> None:
        def row(name, value):
            return style_row(name, selector=".s", prop="color", want="palette", value=value)

        rows = [row("notices", "notices"), row("desk", "desk"), row("spend", "spend")]

        def page(colour):
            return self.styled(f'<div class="s" style="color: {colour}"></div>', rows)

        self.assertEqual(page("rgb(202, 211, 245)"), ())
        self.assertEqual(page("rgba(202, 211, 245, .09)"), ())
        lavender = "rgb(183, 189, 248)"
        red = "rgb(237, 135, 150)"

        def refused(colour, name):
            return tuple(f"{name}: div.s {prop} is {colour}"
                         for prop in ("color", "text-decoration-color", "caret-color"))

        self.assertEqual(page(lavender), refused(lavender, "notices"))
        self.assertEqual(page(red), refused(red, "notices") + refused(red, "spend"))
        stray = "rgba(1, 2, 3, 0.5)"
        self.assertEqual(page(stray), refused(stray, "notices") + refused(stray, "desk")
                         + refused(stray, "spend"))
        shape = style_row("p", selector=".s", prop="color", want="palette", value="desk")
        svg = ('<div class="s" style="color: rgb(202, 211, 245)"><svg width="20" height="20">'
               '<path d="M0 0h10v10z" style="fill: rgb(1, 2, 3)"/></svg></div>')
        self.assertEqual(self.styled(svg, [shape]), ("p: path. fill is rgb(1, 2, 3)",))
        shadow = style_row("s", selector=".s", prop="color", want="palette", value="desk")
        lit = ('<div class="s" style="color: rgb(202, 211, 245); box-shadow: 0 0 0 1px rgb(1, 2, 3)">'
               "x</div>")
        self.assertEqual(self.styled(lit, [shadow]), ("s: div.s box-shadow is rgb(1, 2, 3)",))

    def test_palette_names_a_shadow_colour_written_in_a_perceptual_space(self) -> None:
        row = style_row("s", selector=".s", prop="color", want="palette", value="desk")
        for prop in ("box-shadow", "text-shadow"):
            for colour in ("oklch(0.8 0.1 50)", "oklab(0.8 0.05 0.05)",
                           "lch(70 40 50)", "lab(70 20 30)"):
                with self.subTest(prop=prop, colour=colour):
                    spread = " 1px" if prop == "box-shadow" else ""
                    html = (f'<div class="s" style="color: rgb(202, 211, 245); '
                            f'{prop}: 0 0 0{spread} {colour}">x</div>')
                    (miss,) = self.styled(html, [row])
                    self.assertTrue(miss.startswith(f"s: div.s {prop} is "), miss)

    def test_tokens_read_each_token_and_name_a_wrong_one(self) -> None:
        lists = shots.STYLE_LISTS["tokens"]["desk"]
        values = {**lists["colours"], "--ui": "sans-serif", "--display": "serif"}
        declared = lambda **extra: "<style>:root{" + "".join(
            f"{name}:{value};" for name, value in {**values, **extra}.items()) + "}</style>"
        row = style_row("r", selector=":root", prop="--*", want="tokens", value="desk")
        self.assertEqual(self.styled(declared(), [row]), ())
        self.assertEqual(self.styled(declared(**{"--x": "1"}), [row]), ("r: :root declares --x",))
        self.assertEqual(self.styled(declared(**{"--green": "rgb(0, 255, 0)"}), [row]),
                         ("r: --green is rgb(0, 255, 0)",))
        thin = declared().replace("--peach:rgb(245, 169, 127);", "")
        self.assertEqual(self.styled(thin, [row]), ("r: :root lacks --peach",))
        spend = style_row("s", selector=":root", prop="--*", want="tokens", value="spend")
        self.assertEqual(self.styled(declared(), [spend]),
                         tuple(f"s: :root declares {n}" for n in sorted(
                             ("--green", "--peach", "--red", "--yellow"))))

    def test_distinct_names_two_marks_that_differ_only_in_colour(self) -> None:
        html = ("<style>i{display:block;width:9px;height:9px}"
                ".a{border:1px solid rgb(1, 2, 3)} .b{border:1px solid rgb(4, 5, 6)}"
                ".c{border:1px dashed rgb(1, 2, 3)}</style>"
                '<i class="a"></i><i class="b"></i><i class="c"></i>')

        def row(selector):
            return style_row("r", selector=selector, prop="border-top-style", want="distinct")

        self.assertEqual(self.styled(html, [row(".a | .c")]), ())
        self.assertEqual(self.styled(html, [row(".a | .b")]), ("r: .a and .b differ only in colour",))
        self.assertEqual(self.styled(html, [row(".a | .b | .c")]),
                         ("r: .a and .b differ only in colour",))
        self.assertEqual(self.styled(html, [row(".a | .z")]), ("r: .z is absent",))
        probed = style_row("r", selector=".a | .b", prop="border-top-style", want="distinct",
                           probe="<span data-style-probe><i class='a'></i><i class='b'></i></span>")
        self.assertEqual(self.styled(html, [probed]), ("r: .a and .b differ only in colour",))

    def test_sizes_shared_names_a_size_used_only_in_scope(self) -> None:
        row = style_row("r", selector=".s", prop="font-size", want="sizes_shared")
        page = ('<p>x</p><p style="font-size: 14px">y</p>'
                '<div class="s"><b style="font-size: 14px">a</b>%s</div>')
        self.assertEqual(self.styled(page % "", [row]), ())
        self.assertEqual(self.styled(page % '<i style="font-size: 17px">b</i>', [row]),
                         ("r: i. font-size is 17px",))

    def test_fills_names_an_element_narrower_than_its_parent(self) -> None:
        row = style_row("r", selector=".o", prop="width", want="fills", every=True)
        page = ('<div style="width: 300px; padding: 0 10px; box-sizing: content-box">'
                '<p class="o" style="margin: 0; %s">x</p></div>')
        self.assertEqual(self.styled(page % "", [row]), ())
        self.assertEqual(self.styled(page % "width: 200px", [row]), ("r: p.o width is 200px",))

    def test_largest_type_names_a_large_element_outside_the_allowed(self) -> None:
        row = style_row("r", selector="body", prop="font-size", want="largest_type",
                        value="24|.card .q, .card .q *")
        self.assertEqual(self.styled('<h2 class="x" style="font-size: 30px">t</h2>', [row]),
                         ("r: h2.x font-size is 30px",))
        self.assertEqual(self.styled(
            '<div class="card"><p class="q" style="font-size: 30px">t<b>u</b></p></div>', [row]), ())
        self.assertEqual(self.styled('<h2 class="x" style="font-size: 23px">t</h2>', [row]), ())

    def test_right_edge_names_an_element_short_of_its_line_end(self) -> None:
        row = style_row("r", selector=".last", prop="right", want="right_edge")
        page = ('<div style="display: flex; width: 400px; padding: 0 20px; box-sizing: content-box">'
                '<span style="display: block; width: 50px">a</span>'
                '<span class="last" style="display: block; width: 50px; %s">b</span></div>')
        self.assertEqual(self.styled(page % "margin-left: auto", [row]), ())
        self.assertEqual(self.styled(page % "", [row]), ("r: .last right is 128px",))

    def test_the_reading_waits_for_a_picture_that_is_still_being_fetched(self) -> None:
        import base64
        wide = "data:image/png;base64," + base64.b64encode(shots._solid_png((9, 8, 7), 200, 100)).decode()
        page = ('<div style="width: 300px"><img class="pic-img i" style="display: block; width: 100%; '
                'height: auto"></div><script>setTimeout(() => '
                f'document.querySelector(".i").src = "{wide}", 400)</script>')
        row = style_row("r", selector=".i", prop="height", want="follows_shape")
        self.assertEqual(self.styled(page, [row]), ())

    def test_hugs_names_a_label_wider_than_its_text(self) -> None:
        row = style_row("r", selector=".l", prop="width", want="hugs")
        page = '<span class="l" style="position: absolute; %s">a label</span>'
        self.assertEqual(self.styled(page % "", [row]), ())
        self.assertEqual(self.styled(page % "width: 300px", [row]), ("r: .l width is 300px",))

    def test_track_max_names_a_track_past_its_fraction(self) -> None:
        page = '<div class="g" style="display: grid; grid-template-columns: 16px 1fr 400px; width: 800px"><i></i></div>'
        for fraction, found in (("0.4", ("r: .g grid-template-columns is 16px 384px 400px",)),
                                ("0.5", ())):
            row = style_row("r", selector=".g", prop="grid-template-columns", want="track_max",
                            value=f"3:{fraction}")
            self.assertEqual(self.styled(page, [row]), found, fraction)

    def test_tracks_counts_the_top_level_tracks(self) -> None:
        page = ('<div class="g" style="display: grid; grid-template-columns: minmax(0, 1fr) auto">'
                '<i></i></div><div class="h" style="display: none; '
                'grid-template-columns: minmax(0, 1fr) auto"></div>'
                '<div class="one" style="display: grid; grid-template-columns: 1fr"><i></i></div>')
        for selector, count, misses in ((".g", "2", False), (".h", "2", False), (".g", "3", True),
                                        (".h", "3", True), (".one", "2", True)):
            row = style_row("r", selector=selector, prop="grid-template-columns", want="tracks",
                            value=count)
            with self.subTest(selector=selector, count=count):
                got = self.styled(page, [row])
                self.assertEqual(len(got), int(misses))
                if misses:
                    self.assertRegex(got[0], rf"^r: {selector} grid-template-columns is ")

    def test_alpha_max_takes_a_light_tint_and_names_a_dark_or_opaque_fill(self) -> None:
        page = ('<p class="a" style="background: rgba(24, 25, 38, .22)">x</p>'
                '<p class="b" style="background: rgba(0, 0, 0, .5)">x</p>'
                '<p class="c" style="background: rgb(24, 25, 38)">x</p>'
                '<p class="d" style="background: transparent">x</p>')
        rows = [style_row(name, selector=f".{name}", prop="background-color", want="alpha_max",
                          value="0.35") for name in "abcd"]
        self.assertEqual(self.styled(page, rows), (
            "b: .b background-color is rgba(0, 0, 0, 0.5)",
            "c: .c background-color is rgb(24, 25, 38)"))

    def test_opaque_takes_a_palette_colour_and_names_a_tint(self) -> None:
        page = ('<p class="a" style="background: rgb(30, 32, 48)">x</p>'
                '<p class="b" style="background: rgba(30, 32, 48, .9)">x</p>'
                '<p class="c" style="background: rgb(1, 2, 3)">x</p>')
        rows = [style_row(name, selector=f".{name}", prop="background-color", want="opaque",
                          value="") for name in "abc"]
        self.assertEqual(self.styled(page, rows), (
            "b: .b background-color is rgba(30, 32, 48, 0.9)",
            "c: .c background-color is rgb(1, 2, 3)"))

    def test_follows_shape_names_an_image_off_its_shape(self) -> None:
        import base64
        wide = "data:image/png;base64," + base64.b64encode(shots._solid_png((9, 8, 7), 200, 100)).decode()
        page = ('<div style="width: %spx"><img class="i" src="' + wide + '" style="display: block; '
                'width: 100%%; %s"></div>')
        row = style_row("r", selector=".i", prop="height", want="follows_shape")
        self.assertEqual(self.styled(page % (300, "height: auto; max-height: 180px"), [row]), ())
        self.assertEqual(self.styled(page % (400, "height: auto; max-height: 180px"), [row]), ())
        self.assertEqual(self.styled(page % (300, "height: 50px; max-height: 180px"), [row]),
                         ("r: .i height is 50px",))
        broken = '<img class="i" src="data:image/png;base64,AAAA" style="width: 100px; height: 20px">'
        self.assertEqual(self.styled(broken, [row]), ("r: .i height is 20px (not loaded)",))

    @staticmethod
    def controls_page(body):
        """The page's own controls block, with its tokens, around `body`."""
        text = (Path(shots.__file__).resolve().parents[1]
                / "python/agent_tools/console/page.html").read_text(encoding="utf-8")
        style = re.search(r"(?s)<style>(.*?)</style>", text).group(1)
        root = re.search(r"(?s):root \{.*?\n\}|:root \{[^}]*\}", style).group(0)
        block = re.search(r"(?s)/\* controls \*/\n(.*?)/\* end controls \*/", style).group(1)
        return f"<style>{root}\n{block}\n.x .btn-quiet {{ border-radius: 2px }}</style>{body}"

    def test_kind_look_names_a_control_whose_kind_property_was_overridden(self) -> None:
        row = style_row("r", selector="body", prop="min-height", want="kind_look",
                        value=",".join(shots.LOOK))
        page = self.controls_page('<div class="x"><button class="btn-quiet">x</button></div>')
        self.assertEqual(self.styled(page, [row]), tuple(
            f"r: button.btn-quiet border-{corner}-radius is 2px"
            for corner in ("top-left", "top-right", "bottom-right", "bottom-left")))
        self.assertEqual(self.last_leftover, 0)
        short = self.controls_page('<button class="btn-quiet" style="min-height: 20px">x</button>')
        self.assertEqual(self.styled(short, [row]), ("r: button.btn-quiet min-height is 20px",))
        self.assertEqual(self.styled(self.controls_page("<p>x</p>"), [row]), ("r: body is absent",))

    def test_kind_look_skips_a_control_in_a_state(self) -> None:
        row = style_row("r", selector="body", prop="min-height", want="kind_look",
                        value=",".join(shots.LOOK))
        states = ('<button class="btn-quiet" disabled>x</button>'
                  '<button class="btn-option" aria-pressed="true">x</button>'
                  '<button class="btn-quiet" aria-busy="true">x</button>'
                  '<button class="btn-option picked">x</button>'
                  '<button class="btn-quiet btn-bare" style="padding: 0; color: rgb(1, 2, 3)">x</button>'
                  '<button class="cap btn-quiet" style="padding: 0">x</button>'
                  '<div data-style-probe><button class="btn-quiet" style="border-radius: 2px">x'
                  '</button></div>')
        # The states are the controls block's own rules, so each is given a look the kind refuses.
        refused = "".join(
            f'<button class="{cls}" {attrs} style="border-radius: 2px; padding: 1px">x</button>'
            for cls, attrs in (("btn-quiet", "disabled"), ("btn-option", 'aria-pressed="true"'),
                               ("btn-quiet", 'aria-busy="true"'), ("btn-option picked", "")))
        self.assertEqual(self.styled(self.controls_page(states + refused), [row]), ())
        bare = '<button class="btn-quiet btn-bare" style="border-color: rgb(1, 2, 3)">x</button>'
        self.assertEqual(self.styled(self.controls_page(bare), [row]), tuple(
            f"r: button.btn-quiet border-{side}-color is rgb(1, 2, 3)"
            for side in ("top", "right", "bottom", "left")))

    def test_contrast_keeps_the_wcag_pins_and_names_a_faint_placeholder(self) -> None:
        def page(fg, bg):
            return f'<p class="t" style="color: {fg}; background: {bg}">x</p>'

        def row(value, **kw):
            return style_row("c", **{"selector": ".t", "prop": "color", "want": "contrast",
                                     "value": value, **kw})

        self.assertEqual(self.styled(page("#939ab7", "#1e2030"), [row("4.5")]), ())
        self.assertEqual(self.styled(page("#939ab7", "#1e2030"), [row("99")]),
                         ("c: .t contrast is 5.79",))
        self.assertEqual(self.styled(page("#181926", "#f5a97f"), [row("99")]),
                         ("c: .t contrast is 9.01",))
        self.assertEqual(self.styled(page("#494d64", "#1e2030"), [row("4.5")]),
                         ("c: .t contrast is 1.94",))
        faint = ('<style>.f::placeholder { color: #494d64; opacity: 1 }</style><div style="background:'
                 ' #1e2030"><input class="f" placeholder="x" style="background: none"></div>')
        self.assertEqual(self.styled(faint, [row("4.5", selector=".f", pseudo="::placeholder")]),
                         ("c: .f::placeholder contrast is 1.94",))

    def on_the_page(self, body, names, *, width=1440, change=(), extra="", mutation=None):
        """The misses of the table's rows `names` on `body` under the page's own style block, with
        each `(old, new)` of `change` replaced in it and `extra` rules after it."""
        text = (Path(shots.__file__).resolve().parents[1]
                / "python/agent_tools/console/page.html").read_text(encoding="utf-8")
        style = re.search(r"(?s)<style>(.*?)</style>", text).group(1)
        for old, new in change:
            self.assertIn(old, style)
            style = style.replace(old, new)
        rows = [row for name in names for row in shots.STYLE_CHECKS if row.name == name]
        self.assertEqual([row.name for row in rows], list(names))
        return self.styled(f"<style>{style}\n{extra}</style>{body}", rows, width=width,
                           mutation=mutation)

    def test_the_gallery_pair_is_read_at_both_widths_between_the_two_it_is_shot_at(self) -> None:
        body = ('<div class="pics"><div class="pic-pair"><div class="pic">a</div>'
                '<div class="pic">b</div></div></div>')
        for at in shots.BETWEEN_WIDTHS:
            name = f"pics-pair-direction-{at}"
            with self.subTest(at=at):
                self.assertEqual(self.on_the_page(body, [name], width=at), ())
                self.assertEqual(
                    self.on_the_page(body, [name], width=at, change=((
                        "@media (max-width: 480px) {\n  .pic-pair {",
                        "@media (max-width: 1180px) {\n  .pic-pair {"),)),
                    (f"{name}: .pic-pair flex-direction is column",))

    def test_the_brief_row_is_read_on_all_four_sides_of_its_padding(self) -> None:
        names = [f"row-gap-padding-{side}{kind}" for kind in ("", "-same")
                 for side in ("top", "bottom", "left", "right")]
        body = '<div id="inbox"></div>'
        self.assertEqual(self.on_the_page(body, names), ())
        self.assertEqual(
            self.on_the_page(body, names, extra=".brief-row { padding: 12px 24px }"),
            tuple(f"row-gap-padding-{side}{kind}: .brief-row padding-{side} is 24px"
                  for kind in ("", "-same") for side in ("left", "right")))

    def test_each_answer_list_kind_is_read_on_a_rendered_list_of_its_kind(self) -> None:
        body = '<div id="reading"><div class="ask-answer"><p>x</p></div></div>'
        names = [f"answer-type-{kind}-{key}" for kind in ("ul", "ol") for key in ("font-size", "font")]
        self.assertEqual(self.on_the_page(body, names), ())
        for kind in ("ul", "ol"):
            with self.subTest(kind=kind):
                misses = self.on_the_page(body, names, extra=f".ask-answer {kind}.md-list "
                                                             "{ font: 20px serif }")
                self.assertEqual(
                    sorted(miss.split(":")[0] for miss in misses),
                    [f"answer-type-{kind}-font", f"answer-type-{kind}-font-size"])

    def test_the_notices_marker_is_read_on_its_own_declared_display(self) -> None:
        body = ('<ul id="list"><li class="line notices"><details><summary>Notices</summary>'
                '</details></li></ul>')
        name = "disclosure-notices-marker-display"
        marker = ".line.notices summary::-webkit-details-marker { display: revert; }"
        self.assertEqual(self.on_the_page(body, [name]), ())
        self.assertEqual(
            self.on_the_page(body, [name], change=((marker, ""),)),
            (f"{name}: .line.notices summary::-webkit-details-marker display is none",))
        row = next(row for row in shots.STYLE_CHECKS if row.name == name)
        self.assertEqual(self.on_the_page(body, [name], mutation=row.broken),
                         (f"{name}: .line.notices summary::-webkit-details-marker display is none",))
        # the summary's own list-item display is the other row's, and it is not enough
        self.assertEqual(self.on_the_page(body, ["disclosure-notices-display"],
                                          change=((marker, ""),)), ())

    def test_declared_takes_the_winning_rule_of_a_pseudo_element(self) -> None:
        def read(css, width=1440):
            row = style_row("d", selector=".a", prop="display", want="declared", value="revert",
                            pseudo="::-webkit-details-marker")
            return self.styled(f'<style>{css}</style><p class="a">x</p>', [row], width=width)

        marker = "::-webkit-details-marker"
        self.assertEqual(read(f".a{marker} {{ display: revert }}"), ())
        self.assertEqual(read(f"p.a{marker}, .b{marker} {{ display: none }}"
                              f".a{marker} {{ display: revert }}"),
                         ("d: .a::-webkit-details-marker display is none",))
        self.assertEqual(read(f".a{marker} {{ display: revert }} p{marker} {{ display: none }}"), ())
        self.assertEqual(read(f".a{marker} {{ display: revert }} .a{marker} {{ display: none }}"),
                         ("d: .a::-webkit-details-marker display is none",))
        self.assertEqual(read(f".a{marker} {{ display: revert }} p{marker} {{ display: none }}"
                              f".a{marker} {{ color: red }} #x{marker} {{ display: none }}"), ())
        self.assertEqual(read(f"p{marker} {{ display: none !important }}"
                              f".a{marker} {{ display: revert }}"),
                         ("d: .a::-webkit-details-marker display is none",))
        wide = f"@media (min-width: 1000px) {{ .a{marker} {{ display: none }} }}"
        self.assertEqual(read(f".a{marker} {{ display: revert }}{wide}"),
                         ("d: .a::-webkit-details-marker display is none",))
        self.assertEqual(read(f".a{marker} {{ display: revert }}{wide}", width=900), ())
        self.assertEqual(read(""), ("d: .a::-webkit-details-marker display is (none)",))

    def test_a_colour_painted_by_a_gradient_is_a_painted_colour(self) -> None:
        for name, body, mutation_target in (
                ("palette-notices-gradient",
                 '<ul id="list"><li class="line notices"><p class="notice">x</p></li></ul>',
                 "p.notice"),
                ("peach-only-needs-gradient", '<div class="top-in">x</div>', "div.top-in")):
            with self.subTest(name):
                row = next(row for row in shots.STYLE_CHECKS if row.name == name)
                self.assertEqual(self.on_the_page(body, [name]), ())
                (miss,) = self.on_the_page(body, [name], mutation=row.broken)
                self.assertRegex(miss, rf"^{name}: {mutation_target} background-image is "
                                       r"rgb\(245, 169, 127\)$")

    def test_a_colour_the_page_cannot_read_as_rgb_is_a_named_miss(self) -> None:
        def row(name, value, **kw):
            return style_row(name, **{"selector": ".t", "prop": "color", "want": "contrast",
                                      "value": value, **kw})

        html = ('<style>.f::placeholder { color: oklch(0.5 0.1 200); opacity: 1 }</style>'
                '<input class="f" placeholder="x" style="background: none">'
                '<p class="t" style="color: #939ab7; background: #1e2030">x</p>')
        misses = self.styled(html, [row("c", "4.5", selector=".f", pseudo="::placeholder"),
                                    row("d", "99")])
        self.assertEqual(len(misses), 2)
        self.assertRegex(misses[0], r"^c: \.f::placeholder contrast is unreadable oklch\(")
        self.assertEqual(misses[1], "d: .t contrast is 5.79")

    def sandboxed_capture(self, **kw):
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        with sync_playwright() as pw:
            try:
                pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"]).close()
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
        with tempfile.TemporaryDirectory() as tmp:
            return shots.capture(Path(tmp) / "out", **kw)

    def test_every_style_check_passes_and_fails_when_broken(self) -> None:
        taken = self.sandboxed_capture(mutate=True)
        self.assertEqual([(s.path.name, s.style) for s in taken if s.style], [])
        for shot in taken:
            read_at = (shot.width, *(shots.BETWEEN_WIDTHS if shot.width == shots.WIDTHS[0] else ()))
            expected = {r.name for r in shots.STYLE_CHECKS
                        if shot.state in r.states and set(read_at) & set(r.widths)}
            with self.subTest(shot.path.name):
                self.assertEqual(set(shot.checked), expected)
                self.assertEqual(set(shot.broke), set(shot.checked))
        self.assertEqual(set().union(*(set(s.checked) for s in taken)),
                         {r.name for r in shots.STYLE_CHECKS})

    def test_a_plain_answer_run_reads_only_the_rows_it_can_have(self) -> None:
        taken = self.sandboxed_capture(
            states=("question-read",), read=("Q?", "Answer: plain\nQuestion for you: none"))
        fixture = {r.name for r in shots.STYLE_CHECKS if r.fixture}
        self.assertEqual([s for s in taken if s.style], [])
        read = {name for s in taken for name in s.checked}
        self.assertEqual(read & fixture, set())
        self.assertLessEqual({"reading-weight-panel", "reading-weight-call-out"}, read)


class ScreenshotCaptureTest(unittest.TestCase):
    def test_the_command_writes_a_png_per_state_and_width_and_nothing_scrolls_sideways(self) -> None:
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        with sync_playwright() as pw:
            try:
                pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"]).close()
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            taken = shots.capture(out)
            self.assertEqual([s for s in taken if s.width == 480 and s.scroll_width > 480], [])
            self.assertEqual([s for s in taken if s.squeezed], [])
            self.assertEqual([s for s in taken if s.jargon], [])
            self.assertEqual([(s.path.name, s.scroll_y) for s in taken if s.scroll_y != 0], [])
            self.assertEqual(
                [s.width for s in taken if s.state == "tell-box-open" and s.tell == shots.OPEN_TELL],
                list(shots.WIDTHS))
            self.assertEqual(
                [s for s in taken if s.state != "tell-box-open" and s.tell is not None], [])
            self.assertEqual(
                [s.width for s in taken if s.state == "ask-box" and s.ask == shots.HEAD_ASK],
                list(shots.WIDTHS))
            self.assertEqual([s for s in taken if s.state != "ask-box" and s.ask is not None], [])
            self.assertEqual(
                [s.width for s in taken if s.state == "ask-goal" and s.goal == shots.FILLED_GOAL],
                list(shots.WIDTHS))
            self.assertEqual([s for s in taken if s.state != "ask-goal" and s.goal is not None],
                             [])
            self.assertEqual(
                [s.width for s in taken
                 if s.state == "questions-open" and s.thread == shots.OPEN_THREAD],
                list(shots.WIDTHS))
            for state in ("deeper-offer", "deeper-answer"):
                self.assertEqual(
                    [s.width for s in taken
                     if s.state == state and shots.deeper_shows(state, s.deeper)],
                    list(shots.WIDTHS))
            self.assertEqual(
                [s for s in taken if s.state not in shots.DEEPER_STATES and s.deeper is not None],
                [])
            self.assertEqual([s for s in taken if s.acts != ()], [])
            self.assertEqual(shots.main(["--out", str(out)]), 0)
            names = sorted(p.name for p in out.iterdir())
            self.assertEqual(
                names, sorted(f"{s}-{w}.png" for s in shots.STATES for w in shots.WIDTHS))
            self.assertEqual(len(names), 2 * len(shots.STATES))
            for path in out.iterdir():
                self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


class ScreenshotReadingTest(unittest.TestCase):
    def read_pages(self, htmls, expression):
        """Load each markup alone in one 1440x900 Chromium page and return what `expression` reads."""
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            self.skipTest("playwright is not installed")
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            except Error as err:
                self.skipTest(f"no Chromium to launch: {err}")
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                found = []
                for html in htmls:
                    page.set_content(html)
                    found.append(page.evaluate(expression))
                return found
            finally:
                browser.close()

    def test_the_deeper_readings_read_each_rows_answer_and_spend_and_the_estimate(self) -> None:
        def row(answer, spend, goal=True):
            return ('<li class="ask"><div class="ask-answer"><p>' + answer + '</p>\n<p>  b </p></div>'
                    '<p class="ask-spend">' + spend + '</p>'
                    + ('<button class="ask-goal">Make it a goal</button>' if goal else '')
                    + '</li>')

        def panel(rows):
            return f'<section id="reading"><ol class="ask-list">{rows}</ol></section>'

        def offer(text):
            confirm = f'<div class="ask-deep-confirm"><p class="ask-deep-estimate">{text}</p></div>'
            return panel(row("a", "Spent 1 tokens, about $0.01") + confirm)

        one = row("a", "Spent 1 tokens, about $0.01", goal=False)
        two = row("c", "Spent 2 tokens, about $0.02")
        hidden = panel(one + two).replace("<li", '<li style="display:none"', 1)
        estimate = "Earlier deeper answers here spent about 2,184,000 tokens, $2.76 each."
        self.assertEqual(
            self.read_pages([panel(one + two), hidden, "<p>none</p>"], shots.DEEPER_READING),
            [[True, [["a b", "Spent 1 tokens, about $0.01"], ["c b", "Spent 2 tokens, about $0.02"]],
              True],
             [True, [["c b", "Spent 2 tokens, about $0.02"]], True],
             [False, [], False]])
        self.assertEqual(
            self.read_pages([offer(estimate), offer("No estimate."), "<p>none</p>"],
                            shots.OFFER_READING),
            [[True, [["a b", "Spent 1 tokens, about $0.01"]], True, estimate],
             [True, [["a b", "Spent 1 tokens, about $0.01"]], True, "No estimate."],
             [False, [], False, ""]])

    def test_the_jargon_count_counts_each_visible_review_phrase(self) -> None:
        samples = {
            "on track": "<p>The sprint for owner/p00 is now on track: x</p>",
            "stated": '<div id="projects"><span>stated <time>3 min ago</time></span></div>',
            "withdraw": '<div id="projects"><button>Withdraw</button></div>',
            "nudge": '<div id="projects"><p>Tell the manager again to nudge it.</p></div>',
            "stop or": '<div id="projects"><p>Stop or go</p></div>',
            "would do differently":
                '<div id="projects"><p>Would do differently: cut smaller slices</p></div>',
            "approval row": '<div id="projects"><ul><li class="message">'
                            '<span class="message-text">You: Approved version 2</span>'
                            '<span class="message-state">picked up</span></li></ul></div>'}
        counts = self.read_pages([f"<body>{html}</body>" for html in samples.values()],
                                 shots.JARGON_COUNT)
        for name, count in zip(samples, counts):
            with self.subTest(name):
                self.assertEqual(count, 1)

    def test_the_jargon_count_skips_the_owners_withdraw(self) -> None:
        owners = ('<body><div id="projects"><button class="notice-withdraw">Withdraw</button>'
                  '</div></body>')
        other = '<body><div id="projects"><button>Withdraw</button></div></body>'
        self.assertEqual(self.read_pages([owners, other], shots.JARGON_COUNT), [0, 1])

    def test_the_jargon_count_skips_hidden_text_and_the_new_words(self) -> None:
        html = ('<body><div id="projects"><details><summary>End the sprint</summary>'
                '<button>Drop the sprint</button>'
                '<p>withdraw nudge on track stated 3 min ago Stop or go Would do differently</p>'
                '</details><p style="display:none">Withdraw</p>'
                '<span>goal set <time>3 min ago</time></span><p><button>Stop and report</button></p>'
                '<p>Could not drop: no</p><p>Next time: cut smaller slices</p>'
                '<ul><li class="message"><span class="message-text">You: Approved version 2</span>'
                '<span class="message-state">sent just now</span></li></ul></div></body>')
        self.assertEqual(self.read_pages([html], shots.JARGON_COUNT), [0])

    def test_the_control_reading_flags_a_control_under_32_px(self) -> None:
        bodies = ['<button style="height:24px">a</button>',
                  '<button style="min-height:32px">b</button>',
                  '<button style="display:none;height:10px">c</button>',
                  '<input style="height:20px">',
                  '<button style="height:31.75px;padding:0;border:0">e</button>',
                  '<details><summary class="more-open btn-quiet" '
                  'style="display:block;height:24px">f</summary></details>']
        found = self.read_pages([f"<body>{html}</body>" for html in bodies], shots.SHORT_CONTROLS)
        self.assertEqual([len(f) for f in found], [1, 0, 0, 1, 1, 1])
        self.assertEqual(found[5], ["summary.more-open 24px"])

    def test_the_tell_reading_flags_an_overlapping_or_narrow_field(self) -> None:
        def layout(*, hint_first=False, field="width:100%"):
            hint = '<p class="tell-hint">hint</p>'
            label = ('<label class="tell-label" style="display:block">'
                     '<span style="display:block">Tell the manager</span>'
                     f'<textarea class="tell" style="display:block;{field};box-sizing:border-box">'
                     '</textarea></label>')
            body = (hint + label if hint_first else label + hint) + '<button class="tell-send">Send</button>'
            return ('<ul><li class="sprint" style="width:600px;padding:0 12px;list-style:none">'
                    f'<div class="sprint-tell">{body}</div></li></ul>')

        layouts = {"good": layout(), "hint above": layout(hint_first=True),
                   "narrow": layout(field="width:200px")}
        readings = self.read_pages(list(layouts.values()), shots.TELL_READING)
        for (name, _), reading in zip(layouts.items(), readings):
            with self.subTest(name):
                self.assertEqual(reading[:3], [True, "Send", "hint"])
                self.assertIs(reading[3], name == "good")

    def test_the_ask_reading_reads_the_open_box_and_its_questions(self) -> None:
        field = ('<div class="ask-box"><textarea class="ask-text" '
                 'style="width:300px;height:60px"></textarea></div>')

        def block(*, textarea=True, working_style=""):
            return ('<ul><li class="line asks" data-project="owner/web">'
                    + (field if textarea else '<div class="ask-box"></div>')
                    + '<ul class="ask-list"><li class="ask"' + working_style + '>'
                    '<p class="ask-question">Is the importer deployed on this host? '
                    '<time>just now</time></p><p class="ask-state">Working on it</p></li>'
                    '<li class="ask"><p class="ask-question">What does the build check? '
                    '<time>3 min ago</time></p><p class="ask-answer">It builds.</p>'
                    '<p class="ask-read">Read: flake.nix, lib/helpers.nix</p></li></ul>'
                    '</li></ul>')

        found = self.read_pages(
            [block(), block(textarea=False), block(working_style=' style="display:none"'),
             "<ul><li>nothing</li></ul>"], shots.ASK_READING)
        self.assertEqual(found, [
            list(shots.OPEN_ASK),
            [False, "Working on it", "Read: flake.nix, lib/helpers.nix"],
            [True, None, "Read: flake.nix, lib/helpers.nix"],
            [False, None, None]])

    def test_the_row_reading_flags_ask_below_give_goal(self) -> None:
        def line(wrapper_open="", wrapper_close="", project="owner/web"):
            return ('<ul><li class="line quiet" data-project="' + project + '">'
                    '<span class="line-acts"><button class="give-goal">Give it a goal</button>'
                    + wrapper_open + '<button class="ask-open">Ask a question</button>'
                    + wrapper_close + '</span></li></ul>')

        found = self.read_pages(
            [line(), line('<span style="display:block">', '</span>'),
             "<ul><li class=\"line\" data-project=\"owner/web\">"
             "<button class=\"give-goal\">Give it a goal</button></li></ul>"],
            shots.ACTS_ROW)
        self.assertEqual(found, [[], ["owner/web"], []])

    def test_the_thread_reading_reads_the_opened_thread(self) -> None:
        def page(*, open_fold=True, show_follow=True, rows=True):
            row = ('<li class="ask"><p class="ask-question">' + shots.FOLLOW_QUESTION
                   + ' <time>just now</time></p><p class="ask-read">' + shots.FOLLOW_READ_LINE
                   + '</p></li>')
            return ('<ul><li class="line questions"><details data-key="questions:owner/web"'
                    + (" open" if open_fold else "") + '><summary>Questions (2)</summary>'
                    '<ul class="ask-list">' + (row if rows else "") + '</ul>'
                    + ('<button class="follow-open">Ask a follow-up</button>' if show_follow else "")
                    + '</details></li></ul>')

        base = ('<ul><li class="line asks" data-project="owner/web"><ul class="ask-list">'
                '<li class="ask"><p class="ask-question">' + shots.FOLLOW_QUESTION
                + '</p><p class="ask-read">' + shots.FOLLOW_READ_LINE + '</p></li></ul></li></ul>')
        found = self.read_pages(
            [page(), page(open_fold=False), page(show_follow=False), page(rows=False), base,
             "<ul><li>nothing</li></ul>"], shots.THREAD_READING)
        self.assertEqual(found, [
            list(shots.OPEN_THREAD),
            [False, None, False],
            [True, shots.FOLLOW_READ_LINE, False],
            [True, None, True],
            list(shots.BASE_THREAD),
            [False, None, False]])

    def test_the_activation_reading_reads_the_line_and_its_visible_buttons(self) -> None:
        shown_ = shots.ACTIVATION_SHOWN["activation-host"]
        text_ = shown_[0]

        def work(*, style="", buttons=1, line=True):
            body = ('<p class="activation"' + (f' style="{style}"' if style else "") + '><span><span>'
                    + text_ + '</span></span>' + '<button class="activate btn-quiet">Activate</button>'
                    * buttons + '</p>') if line else "<p>nothing</p>"
            return '<section id="projects">' + body + '</section>'

        found = self.read_pages(
            [work(), work(buttons=0), work(buttons=2), work(style="display:none"), work(line=False)],
            shots.ACTIVATION_READING)
        self.assertEqual(found, [
            list(shown_), [text_, 0], [text_, 2], [None, 0], [None, 0]])

    def test_the_register_reading_reads_the_apply_card_and_the_draft_row(self) -> None:
        line = shots.PROPOSAL_LINE

        def page(*, card=True, row=True, change=True, style=""):
            apply = (f'<ul class="apply-lines"{style}><li>{line}</li><li>writes the project contract</li></ul>'
                     if card else "")
            draft = (f'<ul class="register-draft"><li><span class="draft-line">{line}</span>'
                     + ('<button class="draft-change">Change</button>' if change else "")
                     + "</li></ul>" if row else "")
            return f'<div class="lead">{apply}</div><section id="projects">{draft}</section>'

        found = self.read_pages(
            [page(row=False), page(card=False), page(card=False, change=False),
             page(card=False, row=False), page(row=False, style=' style="display:none"')],
            shots.REGISTER_READING)
        self.assertEqual(found, [
            [line, None, False], [None, line, True], [None, line, False],
            [None, None, False], [None, None, False]])

    def test_the_goal_reading_reads_the_filled_box(self) -> None:
        filled = shots.FILLED_GOAL[1]

        def goal(*, box_style="", area_style="height:200px;width:400px"):
            return ('<div id="goal"><div class="goal-in">'
                    f'<textarea class="goal-text" style="{area_style}">{filled}</textarea>'
                    f'<div class="goal-box" style="{box_style}">'
                    '<button class="goal-project" aria-pressed="false">owner/api</button>'
                    '<button class="goal-project" aria-pressed="true"> owner/web </button>'
                    '</div></div></div>')

        found = self.read_pages(
            [goal(), goal(box_style="display:none"),
             goal(area_style="height:22px;width:400px;overflow:auto"),
             "<ul><li>nothing</li></ul>"], shots.GOAL_READING)
        self.assertEqual(found, [
            list(shots.FILLED_GOAL),
            [False, filled, "owner/web", True],
            [True, filled, "owner/web", False],
            [False, None, None, None]])


if __name__ == "__main__":
    unittest.main()
