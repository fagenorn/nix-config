"""The wire entries of a question card's look and action, which `view._question_entry` embeds.

`look_entry(question)` is `{"issue", "pr", "head", "state", "line", "approve_index"}` of a card that carries a look
and `action_entry(question)` is `{"command", "approve_index", "line"}` of one that carries an action (#1687); each
is None for a card without one. `view` documents both entries in its module docstring.
"""

from agent_tools.console import answer as owner_answer
from agent_tools.console.sprints import MAX_OPTION_CHARS, Question, cut


def look_entry(question: Question) -> dict | None:
    look = question.look
    if look is None:
        return None
    state, line = "open", owner_answer.LOOK_APPROVES.format(
        option=cut(look.approve, MAX_OPTION_CHARS), head=look.head[:7], pr=look.pr, issue=look.issue)
    if question.look_state == "moved":
        state = "moved"
        line = (owner_answer.LOOK_MOVED.format(found=(question.look_found or "")[:7], head=look.head[:7])
                if question.look_found_state == "open" and question.look_found is not None
                else owner_answer.LOOK_CLOSED.format(state=question.look_found_state))
    elif question.look_state == "posting":
        state, line = "posting", owner_answer.LOOK_RECORDING.format(head=look.head[:7], issue=look.issue)
    elif question.look_state == "failed":
        state, line = "failed", question.look_reason
    approve = question.options.index(look.approve) if look.approve in question.options else None
    return {"issue": look.issue, "pr": look.pr, "head": look.head, "state": state, "line": line,
            "approve_index": approve}


def action_entry(question: Question) -> dict | None:
    action = question.action
    if action is None:
        return None
    approve = question.options.index(action.approve) if action.approve in question.options else None
    return {"command": action.command, "approve_index": approve,
            "line": owner_answer.ACTION_APPROVES.format(option=cut(action.approve, MAX_OPTION_CHARS))}
