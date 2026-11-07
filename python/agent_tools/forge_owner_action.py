"""Owner-action markers a batch posts for the owner (issue 636): `forge-claim owner-action`.

1. A marker's first line is `<!-- agent:owner-action v1 issue=<n> reason=<reason> holder=<holder> -->`
   (a decision prompt adds `round=<k>` and optionally `clears=<label>`), line 2 is the sentence
   of its reason. A `conflict` or `needs-label` marker follows with one line `- <item>` per item
   with its whitespace collapsed (D1). A `decision` prompt follows with, per question, an empty
   line, `**Q<i>.** <question>` and one line `- [ ] <option>` per option; the owner ticks exactly
   one box under each question (D11). `reason` is `decision`, `conflict` or `needs-label`.
2. The marker carries no `claim` field (D6): claim retirement (`forge_claim.retire_obsolete`,
   `retire_owner_actions`) ends only owner-action markers that name a claim, so `forge-claim
   status`, `renew` and `release` never end one of these.
3. `post` of `conflict` / `needs-label` never posts while a live marker of the same issue and
   reason exists (`already_posted` with the smallest live id). `post` of `decision` posts a new
   round (`round` one above every trusted decision prompt ever posted) unless a live prompt is not
   yet answered, which it re-adopts (D15, D20). Both always ensure and add the `owner-action`
   label afterwards; only trusted markers (`TRUSTED`) are read for a decision prompt.
4. `end` ends every live marker of the reason (end reason `resolved`) and removes the label only
   when no live owner-action of any reason remains; nothing live is `none`, with no mutation. For
   `decision` it also always removes the `owner-answered` label and then the `owner-action` label
   (when no live trusted owner-action remains), nothing live included, so a retry after an
   interrupted removal repairs both (D21).
5. `status` only reads. A decision prompt is `answered` when every one of its questions has exactly
   one ticked box, read from the box lines alone, never from a comment (D1, D15); the verdict is
   `none`, `open` or `answered`.
6. `--items-file` holds a JSON array of 1 to `MAX_ITEMS` strings, each non-empty once its
   whitespace is collapsed; `--questions-file` holds a JSON array of 1 to `MAX_ITEMS` objects with
   exactly the keys `question` and `options` (1 to `MAX_OPTIONS` distinct strings), likewise
   collapsed and non-empty; anything else is a usage error before any `gh` call.
7. Every call prints one JSON object on one line; exit 0 success, 1 forge error, 2 usage.
"""
import json
import re
from collections.abc import Collection
from pathlib import Path
from typing import Any

from agent_tools import forge_markers as fm

KIND = "owner-action"
LABEL = ("owner-action", "D93F0B")
REASONS = ("decision", "conflict", "needs-label")
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")
MAX_ITEMS = 20
MAX_OPTIONS = 8
ANSWERED_LABEL = ("owner-answered", "0E8A16")
QUESTION_LINE = re.compile(r"\*\*Q(\d+)\.\*\* (.+)")
BOX_LINE = re.compile(r"\s*[-*] \[( |x|X)\] (.+?)\s*")
ACTIONS = ("post", "end", "status")
RESOLVED = "resolved"
USAGE = 2
SENTENCES = {
    "decision": "Delivery waits for the owner's choice: tick exactly one box under each question.",
    "conflict": "Landing stopped on a second merge conflict with the integration branch; "
                "resolve it on the branch, then relaunch the batch.",
    "needs-label": "A required check needs a label that only the owner applies.",
}


class _ItemsError(Exception):
    """The items file broke the items invariant; carries the usage detail."""


def add_actions(sub: Any) -> None:
    from agent_tools.forge_claim import HOLDER, REPO, _issue  # forge_claim imports this module
    actions = sub.add_subparsers(dest="action", required=True)
    for name in ACTIONS:
        parser = actions.add_parser(name)
        parser.add_argument("--repo", required=True, type=REPO)
        parser.add_argument("--issue", required=True, type=_issue)
        if name == "post":
            parser.add_argument("--holder", required=True, type=HOLDER)
        parser.add_argument("--reason", required=True, choices=REASONS)
        if name == "post":
            parser.add_argument("--items-file")
            parser.add_argument("--questions-file")
            parser.add_argument("--clears")


def result(args: Any, verdict: str, comment_id: int | None = None, **extra: Any) -> dict[str, Any]:
    return {"command": "owner-action", "action": args.action, "repo": args.repo, "issue": args.issue,
            "reason": args.reason, "verdict": verdict, "comment_id": comment_id, **extra}


def usage_result(argv: list[str], detail: str) -> dict[str, Any]:
    action = argv[1] if len(argv) > 1 and argv[1] in ACTIONS else None
    return {"command": "owner-action", "action": action, "repo": None, "issue": None, "reason": None,
            "verdict": "error", "comment_id": None, "error": "usage", "detail": detail}


def _read_json(path: str, what: str) -> Any:
    try:
        raw = Path(path).read_text(encoding="utf-8")
        return json.loads(raw)
    except (OSError, UnicodeDecodeError) as error:
        raise _ItemsError(f"{what} file {path!r} is unreadable: {error}") from None
    except ValueError:
        raise _ItemsError(f"{what} file {path!r} is not JSON") from None


def _read_items(path: str) -> list[str]:
    value = _read_json(path, "items")
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _ItemsError("items must be a JSON array of strings")
    if not 1 <= len(value) <= MAX_ITEMS:
        raise _ItemsError(f"items must hold 1 to {MAX_ITEMS} entries, not {len(value)}")
    items = [" ".join(item.split()) for item in value]
    if not all(items):
        raise _ItemsError("an item is empty")
    return items


def _read_question_file(path: str) -> list[dict[str, Any]]:
    value = _read_json(path, "questions")
    if not isinstance(value, list) or not all(isinstance(q, dict) for q in value):
        raise _ItemsError("questions must be a JSON array of objects")
    if not 1 <= len(value) <= MAX_ITEMS:
        raise _ItemsError(f"questions must hold 1 to {MAX_ITEMS} entries, not {len(value)}")
    questions = []
    for raw in value:
        options = raw.get("options")
        if (set(raw) != {"question", "options"} or not isinstance(raw["question"], str)
                or not isinstance(options, list) or not all(isinstance(o, str) for o in options)):
            raise _ItemsError("a question needs exactly a string `question` and an array of string `options`")
        if not 1 <= len(options) <= MAX_OPTIONS:
            raise _ItemsError(f"a question needs 1 to {MAX_OPTIONS} options, not {len(options)}")
        question = " ".join(raw["question"].split())
        collapsed = [" ".join(o.split()) for o in options]
        if not question or not all(collapsed):
            raise _ItemsError("a question or an option is empty")
        if len(set(collapsed)) != len(collapsed):
            raise _ItemsError("the options of a question must be distinct")
        questions.append({"question": question, "options": collapsed})
    return questions


def render_questions(questions: list[dict]) -> str:
    """The prompt text after the sentence line: per question an empty line, its header and its boxes."""
    lines: list[str] = []
    for index, q in enumerate(questions, 1):
        lines += ["", f"**Q{index}.** {q['question']}"]
        lines += [f"- [ ] {option}" for option in q["options"]]
    return "\n".join(lines)


def read_questions(body: str) -> list[dict]:
    """The questions of a decision prompt, read from its header and box lines only."""
    questions: list[dict] = []
    ticked: list[list[str]] = []
    for line in body.splitlines()[2:]:
        header = QUESTION_LINE.fullmatch(line)
        if header:
            questions.append({"question": header[2], "options": [], "chosen": None})
            ticked.append([])
            continue
        box = BOX_LINE.fullmatch(line)
        if box and questions:
            questions[-1]["options"].append(box[2])
            if box[1] != " ":
                ticked[-1].append(box[2])
    for question, ticks in zip(questions, ticked):
        question["chosen"] = ticks[0] if len(ticks) == 1 else None
    return questions


def answered(marker: fm.Marker) -> bool:
    if marker.kind != KIND or marker.fields.get("reason") != "decision":
        return False
    questions = read_questions(marker.body)
    return bool(questions) and all(q["chosen"] is not None for q in questions)


def wanted_labels(markers: list[fm.Marker]) -> tuple[bool, bool, set[str]]:
    """`(owner_action, owner_answered, clears)` the live owner-action markers of a trusted listing want.

    `D` is the live decision prompts, `O` every other live owner-action marker: `owner_answered`
    when `D` is non-empty and all answered, `owner_action` when `O` is non-empty or `D` is not
    all answered, and `clears` the labels the answered prompts name."""
    live = [m for m in markers if m.kind == KIND and fm.is_live(m, markers)]
    decisions = [m for m in live if m.fields.get("reason") == "decision"]
    others = [m for m in live if m.fields.get("reason") != "decision"]
    done = bool(decisions) and all(answered(m) for m in decisions)
    clears = {m.fields["clears"] for m in decisions if "clears" in m.fields} if done else set()
    return bool(others) or (bool(decisions) and not done), done, clears


def apply_labels(slug: str, issue: int, markers: list[fm.Marker], labels: Collection[str], *,
                 drop_bare: bool) -> str:
    """The single writer of `owner-answered` and `owner-action`: write only what differs from the
    markers (a trusted listing) and the issue's current label names, and return `answered`, `open`
    or `none`. A bare `owner-action` (no live marker) goes only with `drop_bare` or a live decision."""
    action, done, clears = wanted_labels(markers)
    has_decision = any(m.kind == KIND and m.fields.get("reason") == "decision" and fm.is_live(m, markers)
                       for m in markers)
    if done and ANSWERED_LABEL[0] not in labels:
        fm.ensure_label(slug, *ANSWERED_LABEL)
        fm.add_label(slug, issue, ANSWERED_LABEL[0])
    if action and LABEL[0] not in labels:
        fm.ensure_label(slug, *LABEL)
        fm.add_label(slug, issue, LABEL[0])
    if not action and LABEL[0] in labels and (has_decision or drop_bare):
        fm.remove_label(slug, issue, LABEL[0])
    for name in sorted(clears):
        if name in labels:
            fm.remove_label(slug, issue, name)
    if not done and ANSWERED_LABEL[0] in labels:
        fm.remove_label(slug, issue, ANSWERED_LABEL[0])
    return "open" if action else "answered" if done else "none"


def reconcile(slug: str, issue: int | None = None) -> list[dict]:
    """One pass over the open issues carrying `owner-action` or `owner-answered` (only `issue` when
    given): one report line each. A forge error on one issue skips it; a listing failure raises."""
    names: dict[int, set[str]] = {}
    for label in (LABEL[0], ANSWERED_LABEL[0]):
        for item in fm.open_issues(slug, label):
            number = item.get("number")
            if isinstance(number, int) and not isinstance(number, bool):
                found = item.get("labels")
                held = names.setdefault(number, set())
                if isinstance(found, list):
                    held.update(n["name"] for n in found if isinstance(n, dict) and isinstance(n.get("name"), str))
    reasons = {"answered": "owner_answered", "open": "owner_waiting", "none": "owner_none"}
    lines: list[dict] = []
    for number in sorted(names):
        if issue is not None and number != issue:
            continue
        line: dict[str, Any] = {"repo": slug, "issue": number, "check": None, "ac": None}
        try:
            state = apply_labels(slug, number, fm.list_markers(slug, number, TRUSTED), names[number],
                                 drop_bare=False)
            lines.append({**line, "state": state, "reason": reasons[state]})
        except fm.ForgeError:
            lines.append({**line, "state": "skipped", "reason": "forge_error"})
    return lines


def decisions_text(questions: list[dict]) -> str:
    return "\n".join(f"{q['question']} Chosen: {q['chosen']}" for q in questions)


def _match(args: Any) -> dict[str, str]:
    return {"issue": str(args.issue), "reason": args.reason}


def _usage(args: Any, detail: str) -> tuple[int, dict[str, Any]]:
    return USAGE, result(args, "error", holder=args.holder, error="usage", detail=detail)


def _label_owner_action(args: Any) -> None:
    fm.ensure_label(args.repo, *LABEL)
    fm.add_label(args.repo, args.issue, LABEL[0])


def _post(args: Any) -> tuple[int, dict[str, Any]]:
    decision = args.reason == "decision"
    try:
        if decision:
            if args.items_file is not None or args.questions_file is None:
                raise _ItemsError("--reason decision takes --questions-file and no --items-file")
            payload: Any = _read_question_file(args.questions_file)
        else:
            if args.questions_file is not None or args.items_file is None:
                raise _ItemsError(f"--reason {args.reason} takes --items-file and no --questions-file")
            if args.clears is not None:
                raise _ItemsError("--clears belongs to --reason decision")
            payload = _read_items(args.items_file)
        if args.clears is not None and not re.fullmatch(fm.VALUE, args.clears):
            raise _ItemsError(f"--clears {args.clears!r} is not a label value")
    except _ItemsError as error:
        return _usage(args, str(error))
    if decision:
        return _post_decision(args, payload)
    live = fm.contest(fm.list_markers(args.repo, args.issue), KIND, _match(args))
    if live:
        verdict, comment_id = "already_posted", live[0].comment_id
    else:
        written = fm.write(args.repo, args.issue, KIND, {**_match(args), "holder": args.holder},
                           SENTENCES[args.reason], _match(args),
                           "\n".join(f"- {item}" for item in payload))
        if written.won:
            verdict, comment_id = "posted", written.own_id
        else:
            verdict = "already_posted"
            comment_id = written.winner.comment_id if written.winner else None
    _label_owner_action(args)
    return 0, result(args, verdict, comment_id, holder=args.holder)


def _round(marker: fm.Marker) -> int:
    value = marker.fields.get("round", "0")
    return int(value) if value.isdigit() else 0


def _post_decision(args: Any, questions: list[dict]) -> tuple[int, dict[str, Any]]:
    markers = fm.list_markers(args.repo, args.issue, TRUSTED)
    unanswered = [m for m in fm.contest(markers, KIND, _match(args)) if not answered(m)]
    if unanswered:
        verdict, comment_id = "already_posted", unanswered[0].comment_id
    else:
        every = [m for m in markers if m.kind == KIND and m.fields.get("reason") == "decision"]
        round_no = 1 + max((_round(m) for m in every), default=0)
        match = {**_match(args), "round": str(round_no)}
        fields = {**_match(args), "holder": args.holder, "round": str(round_no),
                  **({"clears": args.clears} if args.clears else {})}
        written = fm.write(args.repo, args.issue, KIND, fields, SENTENCES["decision"], match,
                           render_questions(questions), associations=TRUSTED)
        if written.won:
            verdict, comment_id = "posted", written.own_id
        else:
            verdict = "already_posted"
            comment_id = written.winner.comment_id if written.winner else None
    _label_owner_action(args)
    return 0, result(args, verdict, comment_id, holder=args.holder)


def _end(args: Any) -> tuple[int, dict[str, Any]]:
    decision = args.reason == "decision"
    markers = fm.list_markers(args.repo, args.issue, TRUSTED if decision else None)
    named = [m.comment_id for m in fm.contest(markers, KIND, _match(args))]
    for comment_id in named:
        fm.end(args.repo, args.issue, comment_id, RESOLVED)
    if not named and not decision:
        return 0, result(args, "none", ended=[])
    if decision:
        fm.remove_label(args.repo, args.issue, ANSWERED_LABEL[0])
    if not any(m.kind == KIND and m.comment_id not in named and fm.is_live(m, markers)
               for m in markers):
        fm.remove_label(args.repo, args.issue, LABEL[0])
    if not named:
        return 0, result(args, "none", ended=[])
    return 0, result(args, "ended", named[0], ended=named)


def _status_decision(args: Any) -> tuple[int, dict[str, Any]]:
    live = fm.contest(fm.list_markers(args.repo, args.issue, TRUSTED), KIND, _match(args))
    if not live:
        return 0, result(args, "none", questions=[], decisions="")
    questions = [{**q, "comment_id": m.comment_id} for m in live for q in read_questions(m.body)]
    done = all(answered(m) for m in live)
    return 0, result(args, "answered" if done else "open", live[0].comment_id, questions=questions,
                     decisions=decisions_text(questions) if done else "")


def _status(args: Any) -> tuple[int, dict[str, Any]]:
    if args.reason == "decision":
        return _status_decision(args)
    live = fm.contest(fm.list_markers(args.repo, args.issue), KIND, _match(args))
    if not live:
        return 0, result(args, "none", items=[])
    marker = live[0]
    items = [line[2:] for line in marker.body.splitlines()[2:] if line.startswith("- ")]
    return 0, result(args, "open", marker.comment_id, items=items)


def run(args: Any) -> tuple[int, dict[str, Any]]:
    return {"post": _post, "end": _end, "status": _status}[args.action](args)
