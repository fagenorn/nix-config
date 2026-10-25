# Task 1: Opus-class list price and the shared write-split rule

Spec § Pricing correction and § Module boundary, per D9 and D2. The Opus-class `PRICING` row becomes `(5.0, 25.0, 10.0, 6.25, 0.50)`; the rule "a usage object with no TTL breakdown is all 5-minute writes" moves out of `scan_file` into one function that Task 2's scanner also calls; `python/README.md` gains an `agent-costs` section stating the price change.

**Files:**
- Modify: `python/agent_tools/agent_costs.py` (module docstring, the comment above `PRICING`, `PRICING`, new `cache_write_split`, `scan_file`)
- Modify: `tests/test_agent_costs.py` (`ScanFileTest`, `EndToEndTest`)
- Modify: `python/README.md` (new last section)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `agent_costs.cache_write_split(usage: dict) -> tuple[int, int]` returning `(cw_1h, cw_5m)`; `agent_costs.PRICING["opus"] == (5.0, 25.0, 10.0, 6.25, 0.50)`; a `## agent-costs` section at the end of `python/README.md` that Task 3 extends.

**Invariants:**
- `PRICING` tuples stay `(input, output, cache_write_1h, cache_write_5m, cache_read)` per Mtok; the `sonnet` and `haiku` rows are unchanged.
- `cache_write_split(usage)` returns the recorded `cache_creation.ephemeral_1h_input_tokens` and `ephemeral_5m_input_tokens` (missing or `null` read as 0); when both are 0 it returns `(0, cache_creation_input_tokens or 0)`.
- `scan_file` returns the same keys and token counts as at base; only Opus-family `cost`/`cost_by_family` values change.
- `SCHEMA_VERSION` stays 1 and the golden text fixture is untouched (its rows print `$0` before and after).

- [ ] **Step 1: Write the failing tests**

In `tests/test_agent_costs.py`, add this method to `ScanFileTest`, directly after `test_cost_uses_model_family_pricing`:

```python
    def test_opus_class_list_price_is_five_and_twenty_five_per_mtok(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
                 "cache_read_input_tokens": 1_000_000,
                 "cache_creation_input_tokens": 3_000_000,
                 "cache_creation": {"ephemeral_1h_input_tokens": 1_000_000,
                                    "ephemeral_5m_input_tokens": 2_000_000}}
        r = self.scan([assistant("m1", usage=usage, model="claude-opus-5-5")])
        # $5 in + $25 out + 1M x $10 (1h write, 2x) + 2M x $6.25 (5m write, 1.25x)
        # + 1M x $0.50 (read, 0.1x); the stale $15/$75 row gives $159.
        self.assertAlmostEqual(r["cost"], 5.0 + 25.0 + 10.0 + 12.5 + 0.5, places=9)
        self.assertAlmostEqual(r["cost_by_family"]["opus"], 53.0, places=9)
```

In `EndToEndTest.test_dispatcher_owners_reviews_and_forced_fallback_are_truthful`, change the one line

```python
        self.assertAlmostEqual(direct["cost"], 0.0113625, places=12)
```

to

```python
        # six Opus-class USAGE_1 calls: (10 x 5 + 20 x 25 + 5 x 6.25 + 100 x 0.50) x 6 / 1e6
        self.assertAlmostEqual(direct["cost"], 0.0037875, places=12)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (focused test run, timeout 600 s): `-k test_opus_class_list_price -k test_dispatcher_owners_reviews`
Expected: `FAILED (failures=2)` — `159.0 != 53.0` and `0.0113625 != 0.0037875`.

- [ ] **Step 3: Implement**

In `python/agent_tools/agent_costs.py`:

1. `PRICING["opus"]` becomes `(5.0, 25.0, 10.0, 6.25, 0.50)`. Replace the three comment lines above `PRICING` with:

   ```python
   # List price per million tokens: (input, output, cache_write_1h, cache_write_5m, cache_read).
   # Cache writes cost 2x input for the 1-hour TTL and 1.25x for 5 minutes; reads 0.1x.
   # The Opus-class row is the Opus 5.x list price (issue 421); model_family also
   # prices Fable and any unrecognised model with it.
   ```

2. In the module docstring, the sentence ending "exist so runs can be compared against each other and against the 35-day baseline; they are not what anyone was billed." loses "and against the 35-day baseline", reading "exist so runs can be compared against each other; they are not what anyone was billed." (re-wrap the paragraph's lines). Nothing else in the docstring changes in this task.

3. Add, directly after `model_family`:

   ```python
   def cache_write_split(usage):
       """(1-hour, 5-minute) cache-write tokens of one usage object.

       A usage object that records no TTL breakdown is taken as all 5-minute writes.
       """
   ```

   with the body the invariant states (`split = usage.get("cache_creation") or {}`, the two `or 0` reads, the fallback to `usage.get("cache_creation_input_tokens") or 0`).

4. In `scan_file`, replace the four lines from `split = usage.get("cache_creation") or {}` through `cw_5m = c_create  # no TTL breakdown recorded; assume 5m` with `cw_1h, cw_5m = cache_write_split(usage)`. Nothing else in `scan_file` changes.

In `python/README.md`, append this section at the end of the file (after `## Retained review evidence`), exactly:

```markdown
## agent-costs

`agent-costs` (`just agent-costs`; source entry `python -m agent_tools.agent_costs`) reports agent token spend per issue from the Claude Code transcripts under `~/.claude/projects`, and with `--format json` projects one `agent-cost-record` (Codex rollouts too, with `--strata`). Its dollar figures apply list prices per model family from `PRICING`: comparative telemetry, not billing data.

Issue 421 corrected the Opus-class row from $15 input / $75 output per million tokens to $5 / $25, with cache writes at 2× input for the 1-hour TTL and 1.25× for 5 minutes and reads at 0.1×, so dollar figures from before and after that change are not comparable; token counts and the record's shape (`schema_version` 1) are unchanged. `model_family` prices Opus, Fable and any model it does not recognise with that row, so figures for Opus 5.5 and Fable, whose own list prices differ, are approximate.
```

- [ ] **Step 4: Verify**

Run (focused test run, timeout 600 s) with no `-k`.
Expected: `Ran 90 tests` … `OK` (89 at base plus the new one; `TextByteIdentityTest` green unmodified).

Run: `bash -c 'set -e; if grep -n -e "35-day" -e "15.0, 75.0" -e "assume 5m" python/agent_tools/agent_costs.py; then exit 1; fi; grep -c "cache_write_split(usage)" python/agent_tools/agent_costs.py'`
Expected: exit 0 printing `2` — the `def` line and the one call in `scan_file`; any stale baseline claim, stale row or inline split rule prints its line and exits 1.

Run: `git diff --stat 7601d318 -- tests/fixtures/agent_costs_text_golden.txt python/agent_tools/agent_model_drift_schema.py`
Expected: no output.

Run (build, timeout 3600 s).
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/agent_costs.py tests/test_agent_costs.py python/README.md
launch-commit … -- -m "fix(agent-costs): price Opus-class at the \$5/\$25 list price (issue 421)" \
  -m "One cache_write_split function now owns the no-TTL-breakdown rule. Dollar figures before and after are not comparable; python/README.md says so." \
  -m "<session trailers>"
```
