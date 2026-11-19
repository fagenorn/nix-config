"""The sprint screenshot set against a fixture console (#1086).

Run: just agent-workflow-tests
"""
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
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agent_tools.console import service

from . import accounts_sandbox
from . import console_screenshots as shots
from . import console_test_support as support
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)


def fixture_paths(fixture):
    paths = [value for field in dataclasses.fields(fixture) if field.name not in ("holding", "deaf", "activating")
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
            if expression == shots.THREAD_READING:
                self.reads += 1
                return list(shots.OPEN_THREAD if shots.ASK_FOLD in present else shots.BASE_THREAD)
            if expression == shots.GOAL_READING:
                self.reads += 1
                return list(shots.FILLED_GOAL)
            if expression == shots.ACTIVATION_READING:
                self.reads += 1
                return list(shots.ACTIVATION_SHOWN["activation-tooling"])
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
          "disclosure-notices-display",
          via="the marker is the summary's own arrow, read as the summary's list-item display"),
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
    *(moved(_ANSWER_SIZE, selector, prop, BOTH, row,
            via="" if selector.endswith(" .md-list") else "the list kinds inherit like the list")
      for selector in (".ask-answer .md-list", ".ask-answer ul.md-list", ".ask-answer ol.md-list")
      for prop, row in (("font-size", "answer-type-list-font-size"),
                        ("font", "answer-type-list-font"))),
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
})
RENAMED: dict[str, str] = {
    f"{PAGE}::PageTest::test_runs_are_never_peach_or_red_and_never_stalled":
        "test_the_page_never_says_stalled",
}
LONGHANDS = {
    "font": ("font-style", "font-weight", "font-size", "line-height", "font-family"),
    "background": ("background-color", "background-image"),
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
    r"kind_owned|self\.style\b")


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
        for prop in required:
            seen = {width for row in counting if row.prop == prop for width in row.widths}
            if not set(entry.widths) <= seen:
                misses.append(f"{entry.test} {entry.selector} {entry.prop} @{entry.widths}: "
                              "no row reads it")
                break
    return misses


class ScreenshotFixtureTest(unittest.TestCase):
    def test_the_set_is_forty_states_at_two_widths(self) -> None:
        self.assertEqual(len(shots.STATES), 40)
        self.assertEqual(shots.STATES[-5:], ("sharing-panel", "sharing-off", "sharing-unreadable",
                                             "sharing-reached", "guest-page"))
        self.assertEqual(shots.STATES.index("manager-cannot-hear"),
                         shots.STATES.index("waiting-its-turn") + 1)
        self.assertEqual(shots.STATES[shots.STATES.index("inbox-card"):][:3],
                         ("inbox-card", "question-words", "question-refused"))
        self.assertEqual(shots.STATES.index("waiting-its-turn"),
                         shots.STATES.index("nothing-running") + 1)
        self.assertEqual(shots.STATES.index("failed-start"),
                         shots.STATES.index("desk-spend") + 1)
        self.assertEqual(shots.STATES[-22:-5], ("goal-open", "goal-near", "goal-over", "inbox-card",
                                              "question-words", "question-refused",
                                              "look-card", "look-moved", "look-failed",
                                              "accounts-panel", "ask-box", "questions-closed",
                                              "questions-open", "ask-goal", "question-read",
                                              "activation-tooling", "activation-host"))
        self.assertEqual(shots.STATES.index("tell-box-open"), shots.STATES.index("stuck") + 1)
        self.assertEqual(shots.WIDTHS, (1440, 480))

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
                status, body = get(serve.address, "/")
                self.assertEqual(status, 200)
                self.assertIn(service.DOOR_GUEST, body)
                status, body = get(svc.address, "/api/state")
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body)["sharing"]["colleagues"],
                                 [{"login": shots.COLLEAGUE, "projects": ["owner/web"]}])
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
                          False)])
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
                else:
                    self.assertEqual(days[-1]["total"]["dollars"], 0)


class ScreenshotStyleTableTest(unittest.TestCase):
    def test_every_style_check_is_well_formed(self) -> None:
        names = [row.name for row in shots.STYLE_CHECKS]
        self.assertEqual(len(names), len(set(names)))
        mapped = {name for entry in MOVED for name in entry.rows}
        for row in shots.STYLE_CHECKS:
            with self.subTest(row.name):
                self.assertRegex(row.name, r"^[a-z0-9-]+$")
                self.assertTrue(row.states and set(row.states) <= set(shots.STATES))
                self.assertTrue(row.widths and set(row.widths) <= set(shots.WIDTHS))
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
    def styled(self, html, rows, mutation=None, only=None):
        """Load `html` alone in one 1440x900 Chromium page and return the style misses."""
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

    def test_hugs_names_a_label_wider_than_its_text(self) -> None:
        row = style_row("r", selector=".l", prop="width", want="hugs")
        page = '<span class="l" style="position: absolute; %s">a label</span>'
        self.assertEqual(self.styled(page % "", [row]), ())
        self.assertEqual(self.styled(page % "width: 300px", [row]), ("r: .l width is 300px",))

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
            expected = {r.name for r in shots.STYLE_CHECKS
                        if shot.state in r.states and shot.width in r.widths}
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
