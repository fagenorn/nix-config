"""The human view of a stored adoption plan, `adopt-project plan --format human`.

A bounded semantic rendering of the plan document the command stores; what is
stored is unchanged (R4.8). It lives apart from `adopt_project` so that file
stays under the line limit the repository's bar sets.
"""

from __future__ import annotations

import sys


def emit_human(document: dict) -> int:
    """A bounded semantic view. What is stored is unchanged (R4.8)."""
    plan = document["plan"]
    rewrites = document["link_rewrites"]
    inbound, outbound = rewrites["inbound"], rewrites["outbound"]
    rows = document["path_references"]

    def count(answer: str | None) -> int:
        return sum(1 for row in rows if row["answer"] == answer)

    lines = [
        f"outcome: {plan['outcome']}",
        f"state:   {plan['state']}",
        f"project: {plan['project_id']}",
        f"base:    {plan['base_revision']}",
        f"plan id: {plan['plan_id']}",
        f"evidence: {len(document['evidence'])} entries",
        f"changes:  {len(document['changes'])} operations",
        f"links: inbound {inbound['links']} in {len(inbound['files'])} "
        f"files, outbound {outbound['links']} in {len(outbound['files'])} "
        f"files, unrewritable {len(rewrites['unrewritable'])}, "
        f"already broken {rewrites['already_broken']}",
        f"references: {len(rows)} occurrences, "
        f"extended {count('extend')}, rewritten {count('rewrite')}, "
        f"retained {count('retain')}, open {count(None)}",
    ]
    member = plan.get("conformance")
    if member is not None:
        check = member["required_check"]
        lines.insert(lines.index(f"changes:  {len(document['changes'])} operations") + 1, (
            f"platform lock: {member['lock']['input']} at "
            f"{member['revision']['rev']} ({member['lock']['path']})"))
        lines.insert(lines.index(f"changes:  {len(document['changes'])} operations") + 2, (
            f"workflow: {member['workflow']}"))
        lines.insert(lines.index(f"changes:  {len(document['changes'])} operations") + 3, (
            f"required check: {check['context']} on {check['branch']} of {check['repo']}"))
    for row in document["reference_policies"]:
        lines.append(
            f"policy {row['subject']}: {row['files']} files, "
            f"{row['occurrences']} occurrences, rewritable "
            f"{row['rewritable']}, rewritten {row['rewritten']}, retained "
            f"{row['retained']}, extended {row['extended']}, open "
            f"{row['open']}")
    for row in document["reference_formatting"]:
        lines.append(
            f"format {row['class']}: {len(row['files'])} files, "
            f"command {row['command'] or 'none'}")
    for entry in document["decisions"]["recommended"]:
        lines.append(f"recommended {entry['id']}: {entry['value']}")
    for entry in document["decisions"]["answered"]:
        lines.append(f"answered {entry['id']} {entry['subject']}: "
                     f"{entry['value']}")
    for entry in document["decisions"]["open"]:
        if entry["id"] == "candidate-class":
            answer = "none" if entry["value"] is None else entry["value"]
            lines.append(f"open {entry['id']} {entry['subject']} "
                         f"(answer: {answer}): {entry['recommendation']}")
        elif entry["id"] == "reference-policy":
            answer = "none" if entry["value"] is None else entry["value"]
            lines.append(f"open {entry['id']} {entry['subject']} (answers: "
                         f"{'|'.join(entry['answers'])}, recommended: "
                         f"{answer}): {entry['recommendation']}")
        elif entry["id"] == "path-reference":
            lines.append(f"open {entry['id']} {entry['subject']} (answers: "
                         f"{'|'.join(entry['answers'])}): "
                         f"{entry['recommendation']}")
        else:
            lines.append(f"open {entry['id']}: {entry['recommendation']}")
    for item in plan.get("open_items", []):
        lines.append(f"open item {item['id']}: {item['path']}")
    for blocker in plan["blockers"]:
        lines.append(f"blocked by {blocker['id']}: {blocker['message']}")
    if plan["available_migration"] is not None:
        lines.append(f"available: migrate {plan['available_migration']}")
    lines.append(f"next: {document['handoff']['next_command'] or '(none)'}")
    lines.append(f"stored at {document['handoff']['plan_path']}")
    sys.stdout.write("\n".join(lines) + "\n")
    return 0
