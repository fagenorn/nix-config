"""Production-shaped owner transcripts for the owner report and replay tests (issue 432).

Usage repeats on every content block of a message, as Claude Code writes it.
"""
import json
from datetime import datetime, timedelta, timezone

T0 = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)
RUN = "rel_01a1test-0000-7000-8000-000000000001"


def _line(value):
    """Compact JSON, as transcripts are written (the reader's prefilter needs it)."""
    return json.dumps(value, separators=(",", ":")) + "\n"


def at(seconds):
    return (T0 + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def progress(phase, *, action_id="7:1:1", handoff=None, absolute=False):
    helper = "/Users/me/.agents/bin/workflow-state" if absolute else "workflow-state"
    words = [helper, "progress", "--repo-root", "/Users/me/repo", "--run-id", RUN,
             "--issue", action_id.split(":")[0], "--attempt", action_id.split(":")[1],
             "--action-id", action_id,
             "--phase", str(phase), "--next-needs-context", "true",
             "--artifacts-sufficient", "false", "--remainder-self-contained", "false"]
    if handoff:
        words += ["--handoff-path", handoff]
    return " ".join(words) + " | artifact-budget validate-report --boundary workflow-response --input -"


def gate_reply(action, *, issue=7, attempt=1, launch=1, handoff_path=None):
    return json.dumps({"interface_version": 2, "kind": "phase_gate", "run_id": RUN, "issue": issue,
                       "custody": {"action_id": f"{issue}:{attempt}:{launch}", "attempt": attempt,
                                   "kind": "implementation", "launch": launch},
                       "action": action, "handoff_path": handoff_path}) + "\nexit=0"


def finish_reply(issue=7, kind="delivery_complete"):
    return json.dumps({"interface_version": 2, "issue": issue, "kind": kind, "run_id": RUN,
                       "state": kind, "pending_stage_ids": []})


FINISH = f"workflow-state finish --repo-root /Users/me/repo --run-id {RUN} --summary-file - <<'EOF'"


class Session:
    """One session under <root>/<project>/<session>.jsonl plus its subagents."""

    def __init__(self, root, project="-Users-me-repo", session="s1"):
        self.dir = root / project
        self.session = session
        self.lines = {None: []}
        self.meta = {}
        self.ids = 0

    def _id(self, prefix):
        self.ids += 1
        return f"{prefix}{self.ids:04d}"

    def child(self, agent_id, *, tool_use_id, parent=None, agent_type="general-purpose"):
        self.lines[agent_id] = []
        meta = {"agentType": agent_type, "description": "fixture", "toolUseId": tool_use_id}
        if parent is not None:
            meta["parentAgentId"] = parent
        self.meta[agent_id] = meta

    def call(self, agent, seconds, *, context, write, fresh=2, out=40, ttl="5m",
             model="claude-opus-5-5", bash=None, agent_tool=False, read_file=None, end=None, tool=None):
        """One API call; returns the id of its tool use, if it made one."""
        write = min(write, context - fresh)
        usage = {"input_tokens": fresh, "cache_read_input_tokens": context - write - fresh,
                 "cache_creation_input_tokens": write, "output_tokens": out,
                 "cache_creation": {"ephemeral_5m_input_tokens": write if ttl == "5m" else 0,
                                    "ephemeral_1h_input_tokens": write if ttl == "1h" else 0},
                 "service_tier": "standard"}
        blocks, tool_id = [{"type": "text", "text": "Working."}], None
        if tool is not None or bash is not None or agent_tool or read_file is not None:
            tool_id = self._id("toolu_")
            name, tool_input = (tool if tool is not None else
                                ("Bash", {"command": bash}) if bash is not None else
                                ("Agent", {"subagent_type": "general-purpose", "prompt": "x"})
                                if agent_tool else ("Read", {"file_path": read_file}))
            blocks.append({"type": "tool_use", "id": tool_id, "name": name, "input": tool_input})
        message_id = self._id("msg_")
        for index, block in enumerate(blocks):
            stamp = seconds if end is None or index == 0 else end
            self.lines[agent].append(_line({
                "type": "assistant", "isSidechain": agent is not None, "timestamp": at(stamp),
                "message": {"id": message_id, "model": model, "role": "assistant",
                            "content": [block], "usage": usage}}))
        return tool_id

    def result(self, agent, seconds, tool_id, text="ok"):
        self.lines[agent].append(_line({
            "type": "user", "isSidechain": agent is not None, "timestamp": at(seconds),
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool_id, "content": text}]}}))

    def shape(self, agent, *, system, tools):
        """An `api-request-shape` record: the system blocks' texts and the tool definitions."""
        self.lines[agent].append(_line({
            "type": "api-request-shape", "agentId": agent, "shapeHash": self._id("shape-"),
            "shape": {"system": [{"type": "text", "text": text} for text in system],
                      "tools": list(tools)}}))

    def blob(self, agent, role, blocks):
        """An `api-request-blob` record holding one message; returns its hash."""
        digest = self._id("blob-")
        self.lines[agent].append(_line({
            "type": "api-request-blob", "agentId": agent, "hash": digest,
            "message": {"role": role, "content": list(blocks)}}))
        return digest

    def request(self, agent, tail):
        """An `api-request` record whose tail names blob hashes."""
        self.lines[agent].append(_line({
            "type": "api-request", "agentId": agent, "id": self._id("req-"), "tail": list(tail)}))

    def skill_body(self, agent, seconds, tool_id, text):
        """The meta user message that carries the body a Skill call loaded."""
        self.lines[agent].append(_line({
            "type": "user", "isSidechain": agent is not None, "isMeta": True,
            "sourceToolUseID": tool_id, "timestamp": at(seconds),
            "message": {"role": "user", "content": [{"type": "text", "text": text}]}}))

    def measured(self, agent, tool_id, tokens):
        self.lines[agent].append(_line({
            "type": "attachment", "isSidechain": agent is not None, "attachment": {
                "type": "hook_additional_context", "hookName": "PreToolUse:Bash",
                "toolUseID": tool_id,
                "content": [f"context-meter: this workflow-state progress call carries "
                            f"--context-tokens {tokens}, measured from your transcript."]}}))

    def write(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / f"{self.session}.jsonl").write_text("".join(self.lines[None]), encoding="utf-8")
        subagents = self.dir / self.session / "subagents"
        for agent_id, lines in self.lines.items():
            if agent_id is None:
                continue
            subagents.mkdir(parents=True, exist_ok=True)
            (subagents / f"agent-{agent_id}.jsonl").write_text("".join(lines), encoding="utf-8")
            (subagents / f"agent-{agent_id}.meta.json").write_text(
                json.dumps(self.meta[agent_id]), encoding="utf-8")


def cost(context, write, *, fresh=2, out=40, write_price=5.0, read_price=0.20):
    """The Opus 5.5 list price of one builder call, in dollars (writes capped as `call` caps them)."""
    write = min(write, context - fresh)
    return (fresh * 4.0 + out * 20.0 + write * write_price
            + (context - write - fresh) * read_price) / 1e6
