# Task 1: Codex rollout scanner and its counting rule

**Files:**
- Modify: `scripts/agent-costs.py`
- Test: `tests/test_agent_costs.py`

**Interfaces:**
- Consumes: nothing from an earlier task. From the existing module: nothing — this function is
  self-contained and uses only `json` and `collections.Counter`, both already imported.
- Produces, for Task 2: `scan_codex_file(path) -> dict | None`. On success the dict has exactly
  these keys:

  ```
  {"session_id": str,       # session_meta.payload.session_id — the root thread's id
   "rollout_id": str,       # session_meta.payload.id — this file's own id
   "is_root": bool,         # session_meta.payload.thread_source == "user"
   "cwd": str,              # session_meta.payload.cwd, "" when absent
   "fresh": int, "cache_create": int, "cache_read": int,
   "output": int, "reasoning": int, "input_total": int,
   "peak_ctx": int, "turns": int,
   "models": dict, "efforts": dict}
  ```

  `models` and `efforts` are plain `dict`s mapping name to turn count. Task 2 reads every key.

**Invariants:**
- Tokens come from `Σ info.last_token_usage` over `event_msg`/`token_count` records.
  `total_token_usage` is never read, summed, or trusted (D3).
- `cached_input_tokens` and `reasoning_output_tokens` are subsets and are never added on top:
  `input_total = Σ input_tokens`, `cache_read = Σ cached_input_tokens`,
  `cache_create = Σ cache_write_input_tokens`,
  `fresh = input_total − cache_read − cache_create`, `output = Σ output_tokens`,
  `reasoning = Σ reasoning_output_tokens` (D3).
- `peak_ctx = max(input_tokens)` over the file's `last_token_usage` records, `0` when none.
- `turns` counts the records that carried a non-null `info.last_token_usage` — one per model
  turn (D27). No record-level dedup key is applied: the rollout file is the dedup unit (D3).
- The function returns `None` — never a partial dict — for a file it cannot open and for a file
  with no `session_meta` record. It never raises on malformed JSON: an unparseable line is skipped.
- Nothing in this task is wired into `main`; `scripts/agent-costs.py`'s CLI behavior, its text
  output and its scan set are unchanged by this commit.

## Steps

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent_costs.py`, above any `if __name__ == "__main__":` guard. `json`,
`tempfile`, `unittest` and `Path` are already imported by the module header; add nothing else.

```python
def codex_meta(session_id, rollout_id=None, cwd="/Users/me/repo",
               thread_source="user", parent=None):
    payload = {
        "session_id": session_id,
        "id": rollout_id or session_id,
        "cwd": cwd,
        "thread_source": thread_source,
        "originator": "codex-tui",
    }
    if thread_source == "subagent":
        payload["parent_thread_id"] = parent or session_id
        payload["source"] = {"subagent": {"thread_spawn": {
            "parent_thread_id": parent or session_id,
            "depth": 1, "agent_nickname": "Nash", "agent_role": None}}}
    return record({"timestamp": "2026-08-04T14:08:50.499Z",
                   "type": "session_meta", "payload": payload})


def codex_usage(inp, cached=0, write=0, out=0, reasoning=0, total=None):
    """One token_count event. `total` is the (untrustworthy) running counter."""
    last = {"input_tokens": inp, "cached_input_tokens": cached,
            "cache_write_input_tokens": write, "output_tokens": out,
            "reasoning_output_tokens": reasoning,
            "total_tokens": inp + out}
    running = dict(last) if total is None else dict(last, input_tokens=total)
    return record({"timestamp": "2026-08-04T14:08:55.871Z", "type": "event_msg",
                   "payload": {"type": "token_count",
                               "info": {"total_token_usage": running,
                                        "last_token_usage": last,
                                        "model_context_window": 258400}}})


def codex_turn_context(model="gpt-5.6-sol", effort="xhigh"):
    return record({"timestamp": "2026-08-04T14:08:50.873Z", "type": "turn_context",
                   "payload": {"turn_id": "t1", "cwd": "/Users/me/repo",
                               "model": model, "effort": effort, "summary": "auto"}})


def codex_compacted():
    return record({"timestamp": "2026-08-04T14:20:00.000Z", "type": "event_msg",
                   "payload": {"type": "compacted"}})


class ScanCodexFileTest(unittest.TestCase):
    def write_rollout(self, *lines):
        tmp = Path(tempfile.mkdtemp())
        path = tmp / "rollout-2026-08-04T16-08-42-abc.jsonl"
        path.write_text("".join(lines), encoding="utf-8")
        return path

    def test_sums_last_token_usage_and_ignores_the_rebased_running_total(self):
        path = self.write_rollout(
            codex_meta("s1"),
            codex_turn_context(),
            codex_usage(1000, cached=600, write=0, out=50, reasoning=20, total=1000),
            codex_compacted(),
            # After compaction the running counter rebases; summing it would
            # lose the pre-compaction turn, and reading the last one alone
            # would report 400 input tokens instead of 1400.
            codex_usage(400, cached=100, write=0, out=10, reasoning=5, total=400),
        )
        got = agent_costs.scan_codex_file(path)
        self.assertEqual(got["input_total"], 1400)
        self.assertEqual(got["cache_read"], 700)
        self.assertEqual(got["cache_create"], 0)
        self.assertEqual(got["fresh"], 700)
        self.assertEqual(got["output"], 60)
        self.assertEqual(got["reasoning"], 25)
        self.assertEqual(got["turns"], 2)

    def test_cached_and_reasoning_are_subsets_not_addends(self):
        path = self.write_rollout(
            codex_meta("s1"),
            codex_usage(1000, cached=900, write=100, out=80, reasoning=70),
        )
        got = agent_costs.scan_codex_file(path)
        self.assertEqual(got["input_total"], 1000)      # not 1900
        self.assertEqual(got["fresh"], 0)               # 1000 - 900 - 100
        self.assertEqual(got["output"], 80)             # not 150
        self.assertEqual(got["reasoning"], 70)

    def test_peak_ctx_is_the_largest_single_turn_input(self):
        path = self.write_rollout(
            codex_meta("s1"),
            codex_usage(500), codex_usage(9000), codex_usage(700),
        )
        self.assertEqual(agent_costs.scan_codex_file(path)["peak_ctx"], 9000)

    def test_root_and_subagent_classification_and_identity(self):
        root = self.write_rollout(codex_meta("s1"), codex_usage(10))
        sub = self.write_rollout(
            codex_meta("s1", rollout_id="r2", thread_source="subagent",
                       cwd="/Users/me/repo/.claude/worktrees/issue-120-x"),
            codex_usage(20))
        got_root = agent_costs.scan_codex_file(root)
        got_sub = agent_costs.scan_codex_file(sub)
        self.assertTrue(got_root["is_root"])
        self.assertEqual(got_root["rollout_id"], "s1")
        self.assertFalse(got_sub["is_root"])
        self.assertEqual(got_sub["session_id"], "s1")
        self.assertEqual(got_sub["rollout_id"], "r2")
        self.assertEqual(got_sub["cwd"],
                         "/Users/me/repo/.claude/worktrees/issue-120-x")

    def test_models_and_efforts_come_from_turn_context(self):
        path = self.write_rollout(
            codex_meta("s1"),
            codex_turn_context("gpt-5.6-sol", "xhigh"),
            codex_turn_context("gpt-5.6-sol", "xhigh"),
            codex_turn_context("gpt-5.6", "medium"),
            codex_usage(10),
        )
        got = agent_costs.scan_codex_file(path)
        self.assertEqual(got["models"], {"gpt-5.6-sol": 2, "gpt-5.6": 1})
        self.assertEqual(got["efforts"], {"xhigh": 2, "medium": 1})

    def test_no_session_meta_and_unreadable_file_return_none(self):
        headless = self.write_rollout(codex_usage(10))
        self.assertIsNone(agent_costs.scan_codex_file(headless))
        missing = Path(tempfile.mkdtemp()) / "absent.jsonl"
        self.assertIsNone(agent_costs.scan_codex_file(missing))

    def test_malformed_line_is_skipped_not_raised(self):
        path = self.write_rollout(
            codex_meta("s1"), "{not json\n", codex_usage(10))
        self.assertEqual(agent_costs.scan_codex_file(path)["input_total"], 10)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v tests/test_agent_costs.py -k ScanCodexFileTest 2>&1 | tail -5`
Expected: FAIL — `AttributeError: module 'agent_costs' has no attribute 'scan_codex_file'`
on every test in the class.

- [ ] **Step 3: Write the minimal implementation**

Add to `scripts/agent-costs.py`, immediately after `scan_file`'s `owner_issue` helper and
before `scan_paths`, so the scanners sit together:

```python
def scan_codex_file(path):
    """Parse one Codex rollout. Returns per-file usage and identity, or None.

    Contract: tokens are the sum of ``info.last_token_usage`` over the file's
    ``token_count`` events (D3); ``cached_input_tokens`` and
    ``reasoning_output_tokens`` are subsets of their parents and are never
    added on top.
    """
```

Algorithm, in one pass over the lines:

1. `open(path, "r", errors="replace")`; on `OSError` return `None`. This mirrors `scan_file`.
2. Cheap prefilter before `json.loads`, matching `scan_file`'s style: skip any line that
   contains none of the substrings `"session_meta"`, `"token_count"`, `"turn_context"`. Parse
   what survives with `json.loads`, skipping a line that raises `ValueError`.
3. `type == "session_meta"` and no meta captured yet: take `payload`, set
   `session_id = payload.get("session_id") or payload.get("id")`,
   `rollout_id = payload.get("id") or session_id`,
   `cwd = payload.get("cwd") or ""`,
   `is_root = payload.get("thread_source") == "user"`. A later `session_meta` is ignored.
4. `type == "event_msg"` and `payload.get("type") == "token_count"`: read
   `payload.get("info") or {}` then `info.get("last_token_usage")`. When it is a mapping, add
   its five fields (`input_tokens`, `cached_input_tokens`, `cache_write_input_tokens`,
   `output_tokens`, `reasoning_output_tokens`, each defaulting to `0`) into the running sums,
   raise `peak_ctx` to `input_tokens` when larger, and increment `turns`. When it is absent or
   `None`, the record contributes nothing — including no turn.
5. `type == "turn_context"`: increment `models[payload["model"]]` and
   `efforts[payload["effort"]]` for each key that is present and truthy.
6. After the loop: return `None` when no `session_meta` was seen. Otherwise return the dict
   under **Produces**, with `input_total` the summed `input_tokens`,
   `fresh = input_total - cache_read - cache_create`, and `models`/`efforts` converted with
   `dict(...)`.

No caller is added in this task. `PRICING` is not consulted: the Codex stratum carries no cost
(D7), and this function returns no `cost` key at all, which is what makes Task 2 emit
`cost_usd: null` for it.

- [ ] **Step 4: Verify**

```sh
python3 -m unittest -v tests/test_agent_costs.py -k ScanCodexFileTest
python3 -m unittest tests/test_agent_costs.py
git diff --stat HEAD -- scripts/agent-costs.py tests/test_agent_costs.py
```
Expected: the first prints `OK` with 7 tests; the second prints `OK` with the whole suite
(the pre-existing tests are untouched); the third shows exactly those two files changed.

- [ ] **Step 5: Commit**

```bash
git add scripts/agent-costs.py tests/test_agent_costs.py
git commit -m "feat(agent-costs): mine Codex rollout token usage per file

Sums info.last_token_usage per rollout and never trusts the rebased
total_token_usage running counter (D3). Not yet wired into the CLI.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
