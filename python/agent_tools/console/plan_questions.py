"""The console's plain questions for an adoption plan's open decisions (#1053).

Decided in ADR-console-029. The adoption plan's `decisions.open` holds the questions the owner must
answer before the plan can be applied. This module words them for the page, builds the request that
answers one, and words the refusals. It is pure: no I/O, no clock, and no text is composed from
anything but the document's own strings and the fixed words below.

Questions. `questions(document)` returns one question per member of `document["decisions"]["open"]`,
in that order, each a dict with exactly the keys `id`, `subject`, `ask`, `options`, `recommended`
and `why`. `options` holds exactly the values the plan offers, in its order, each as
`{"value", "label"}`: for `candidate-class` `[value]` when the plan's `value` is not None, else `[]`;
for `path-reference` and `reference-policy` the entry's `answers`; for `project-id` and any other id
`[]`. `why` is None exactly when `options` is not empty; otherwise it says in plain words why the
question cannot be answered on the page (`NO_ANSWER` for an unknown id). `recommended` is the
`reference-policy` entry's `value` (None allowed) and None for every other id. A missing
`path_references`, `reference_policies`, `value`, `answers` or `subject` never raises: each is read
with a default of `[]`, None or `""`.

Single answer (#1065, #1079). A question whose plan offers exactly one answer keeps its plain ask; the
page sets that answer as the card's action (ADR-console-033).

Wording. `candidate-class` asks what should happen to the subject; `archive-history` reads `Archive
it under .agents/knowledge/archive/adopted/` and `retain-product` reads `Keep it where it is`. A
null value says the subject looks like a secret (`adopt_inspection.is_secret_path`) or points outside
the repository, and asks for its removal in its own commit. `path-reference` is worded from the first
`path_references` row with the question's subject (`extend`: `Also name <additions>`, `rewrite`:
`Change it to <replacement>`, `retain`: `Leave it as it is`), and without a row from the subject
alone. `reference-policy` is worded from the first `reference_policies` row with the subject (a class
of `-` reads as files with no extension) and marks the option equal to its `value` with `
(recommended)`. `project-id` asks `Which project is this repository?` and says how to settle it
outside the page. Any other answer is its own label.

Request. `parse_answer_request(body)` takes a UTF-8 JSON object with exactly the members `plan_id`,
`id`, `subject` and `value`, each a non-empty string with no character below 0x20 and no 0x7F, and
returns `(plan_id, question_id, subject, value)`. It raises `ValueError` otherwise, a decode error
included (chained).

Refusals. `refusal_text(error)` words an adoption tool's error object: for a repair id in
`REFUSED_REPAIRS` it is `The plan refused that answer: <message>` (the whitespace-collapsed message
of the first violation, or `The plan refused that answer.` without one); otherwise it is
`The plan was not made again: <message>` with the same message (`The plan was not made again.`
without one), never the repair id or the code (#1057). `rerun_failed(words)` is `The plan was not
made again: <words>`, the words being those a failed run is given (the caller maps a failure kind
through `register.RUN_WORDS`; this module cannot import it). `UNAVAILABLE` and `STALE` are the texts of an answer the host cannot
take and of an answer to a plan no longer shown.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from agent_tools.project_contract import adopt_inspection

UNAVAILABLE = "answering the adoption's questions is not available on this host"
STALE = "that plan is no longer the one shown; answer the plan shown now"
REFUSED_REPAIRS = ("adopt.decisions.invalid_answer", "adopt.decisions.unmatched_answer")
NO_ANSWER = (
    "This question cannot be answered here: answer it with adopt-project plan --answer in a "
    "terminal."
)
MEMBERS = {"plan_id", "id", "subject", "value"}
REMOVE_THEN_REGISTER = (
    "remove it from the repository in its own commit, then register the repository again."
)
FOLLOW = "Should it follow the move?"
POLICY_MOVES = "name paths this plan moves. Should they follow the move?"
CANDIDATE_LABELS = {
    "archive-history": "Archive it under .agents/knowledge/archive/adopted/",
    "retain-product": "Keep it where it is",
}
POLICY_LABELS = {
    "rewrite": "Change every path that can follow the move",
    "retain": "Leave these files as they are",
}
PROJECT_ASK = "Which project is this repository?"
PROJECT_UNKNOWN = (
    "The plan cannot tell which project this is, so it cannot be answered here: give the repository "
    "exactly one git remote, or write its project id in .agents/project.json, then register it "
    "again."
)


def _row(rows: list, subject: str) -> Mapping | None:
    return next((row for row in rows if row.get("subject") == subject), None)


def _options(answers: list, labels: Mapping[str, str]) -> list[dict]:
    return [{"value": answer, "label": labels.get(answer, answer)} for answer in answers]


def _question(entry: Mapping, ask: str, options: list, recommended, why) -> dict:
    return {
        "id": entry.get("id", ""),
        "subject": entry.get("subject", ""),
        "ask": ask,
        "options": options,
        "recommended": recommended,
        "why": None if options else why,
    }


def _candidate(entry: Mapping) -> dict:
    subject = entry.get("subject", "")
    value = entry.get("value")
    if value is not None:
        why = None
    elif adopt_inspection.is_secret_path(subject):
        why = f"{subject} looks like a secret, so it cannot be answered here: {REMOVE_THEN_REGISTER}"
    else:
        why = (
            f"{subject} points outside the repository, so it cannot be answered here: "
            f"{REMOVE_THEN_REGISTER}"
        )
    return _question(
        entry,
        f"What should happen to {subject}? No rule covers this agent file.",
        _options([] if value is None else [value], CANDIDATE_LABELS),
        None,
        why,
    )


def _path_reference(entry: Mapping, rows: list) -> dict:
    subject = entry.get("subject", "")
    row = _row(rows, subject)
    labels = {"retain": "Leave it as it is"}
    if row is None:
        ask = f"{subject} names a path this plan moves. {FOLLOW}"
        labels["extend"] = "Also name the new place"
        labels["rewrite"] = "Change it to the new place"
    else:
        ask = (
            f"{row.get('path')} line {row.get('line')} names {row.get('literal')}, which this plan "
            f"moves. {FOLLOW}"
        )
        additions = row.get("additions") or []
        labels["extend"] = (
            "Also name " + " and ".join(additions) if additions else "Also name the new place"
        )
        replacement = row.get("replacement")
        labels["rewrite"] = (
            f"Change it to {replacement}" if replacement is not None else "Change it to the new place"
        )
    return _question(entry, ask, _options(entry.get("answers") or [], labels), None, NO_ANSWER)


def _reference_policy(entry: Mapping, rows: list) -> dict:
    subject = entry.get("subject", "")
    row = _row(rows, subject)
    if row is None:
        ask = f"The files of {subject} {POLICY_MOVES}"
    else:
        klass, tree = row.get("class"), row.get("tree")
        kind = "files with no extension" if klass == "-" else f"{klass} files"
        ask = f"The {kind} under {tree} {POLICY_MOVES}"
    value = entry.get("value")
    options = _options(entry.get("answers") or [], POLICY_LABELS)
    for option in options:
        if option["value"] == value:
            option["label"] += " (recommended)"
    return _question(entry, ask, options, value, NO_ANSWER)


def _project_id(entry: Mapping) -> dict:
    value = entry.get("value")
    if value is None:
        why = PROJECT_UNKNOWN
    else:
        why = (
            f"{value} is already registered for another checkout, so it cannot be answered here: "
            "write the intended project id in .agents/project.json, then register the repository "
            "again."
        )
    return _question(entry, PROJECT_ASK, [], None, why)


def _unknown(entry: Mapping) -> dict:
    ask = f"{entry.get('id', '')} {entry.get('subject', '')}".strip()
    return _question(entry, ask, [], None, NO_ANSWER)


def questions(document: Mapping) -> list[dict]:
    references = document.get("path_references") or []
    policies = document.get("reference_policies") or []
    built = []
    for entry in (document.get("decisions") or {}).get("open") or []:
        kind = entry.get("id")
        if kind == "candidate-class":
            built.append(_candidate(entry))
        elif kind == "path-reference":
            built.append(_path_reference(entry, references))
        elif kind == "reference-policy":
            built.append(_reference_policy(entry, policies))
        elif kind == "project-id":
            built.append(_project_id(entry))
        else:
            built.append(_unknown(entry))
    return built


def parse_answer_request(body: bytes) -> tuple[str, str, str, str]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("not a JSON object") from error
    if not isinstance(value, dict) or set(value) != MEMBERS:
        raise ValueError("wrong members")
    for text in value.values():
        if not isinstance(text, str) or text == "":
            raise ValueError("not a non-empty string")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in text):
            raise ValueError("control character")
    return value["plan_id"], value["id"], value["subject"], value["value"]


def rerun_failed(words: str) -> str:
    return f"The plan was not made again: {words}"


def refusal_text(error: Mapping) -> str:
    violations = error.get("violations") or []
    message = ""
    if violations:
        message = " ".join(str(violations[0].get("message", "")).split())
    if error.get("repair_id") in REFUSED_REPAIRS:
        if message:
            return f"The plan refused that answer: {message}"
        return "The plan refused that answer."
    if message:
        return rerun_failed(message)
    return "The plan was not made again."
