# Task 1: Per-model pricing and the shared call reader

Spec § Pricing; per D2 and D19. Pricing moves from per-family (`agent_costs.PRICING`, which prices Opus 5.5 at Opus-5 rates) to a per-model-ID table in one module, and the cache report's private call reader moves into its own module, gaining the facts Task 2 needs. Both existing reports keep their output shapes; only their dollar figures move.

**Files:**
- Create: `python/agent_tools/model_pricing.py`
- Create: `python/agent_tools/transcript_calls.py`
- Modify: `python/agent_tools/agent_costs.py` (`scan_file` prices through `model_pricing`; delete `PRICING`; `cache_write_split` moves out; the module docstring's interpretation note says per-model list prices)
- Modify: `python/agent_tools/agent_cache_report.py` (reads through `transcript_calls`; `_premium`/`_reread_above` price through `model_pricing`; the report's last line before `NOTE:` names the pricing source and the approximate-call count)
- Modify: `python/README.md` (§ agent-costs: one paragraph on per-model pricing, its source URL and date, and approximate calls)
- Test: `tests/test_agent_costs.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (Tasks 2 and 4 rely on these exact names):
  - `model_pricing.Rates` — `NamedTuple(input: float, output: float, write_5m: float, write_1h: float, read: float)`, dollars per million tokens.
  - `model_pricing.SOURCE_URL: str`, `model_pricing.SOURCE_DATE = "2026-10-25"`.
  - `model_pricing.rates(model: str | None, prompt_tokens: int) -> tuple[Rates, bool]` returns the rates and whether they are approximate.
  - `model_pricing.cache_write_split(usage: dict) -> tuple[int, int]` returns `(1-hour, 5-minute)` write tokens. It moves unchanged from `agent_costs`, and `agent_costs` imports it back so its existing callers keep working.
  - `model_pricing.usage_cost(model: str | None, usage: dict) -> tuple[float, bool]` returns the dollars of one deduplicated usage object, and whether they are approximate.
  - `transcript_calls.Call` — the moved `_Call` dataclass (same fields and `context`), plus `tool_inputs: dict[str, dict]` (tool-use ID → its `input` object) beside `tool_names`.
  - `transcript_calls.ToolResult` — `NamedTuple(line: int, text: str, size: int, ends_turn: bool)`. `text` is the result's text: a string content as is, a list content's `text` blocks joined with `"\n"`, cut to its first 65,536 characters. `size` is the full length before the cut.
  - `transcript_calls.Transcript` — dataclass `(calls: list[Call], user_entries: list, attachments: dict, results: dict[str, ToolResult], hook_notes: dict[str, str])`. `hook_notes` maps a `toolUseID` to the joined `content` of every `hook_additional_context` attachment whose `hookName` is `PreToolUse:Bash`.
  - `transcript_calls.read_transcript(handle) -> Transcript`. It is the moved `_read_records`, keeping the same filtering and order (calls deduplicated per message ID, in first-line order, context > 0).
  - `transcript_calls.is_death(prev: Call, call: Call, ttl: int) -> bool`, `TTL_SECONDS`, `TTL_SLACK_SECONDS`, `MIN_DEATH_CONTEXT` — moved unchanged.

**Invariants:**
- The rate rows are exactly spec § Pricing (per MTok: input / output / 5-minute write / 1-hour write / read). Model IDs: `claude-opus-5-5`; `claude-opus-5`, `claude-opus-4-5` … `claude-opus-4-8`; `claude-sonnet-5-5`; `claude-sonnet-5`; `claude-sonnet-4-5`, `claude-sonnet-4-6`; `claude-haiku-5-5` (prompt ≤ 100,000 → first tier, > 100,000 → second tier); `claude-haiku-4-5`; `claude-fable-5-1`; `claude-fable-5`.
- An ID equal to a row's ID, or equal to it plus `-<8 digits>` (a date suffix), is exact. Any other ID containing `opus`, `sonnet`, `haiku` or `fable` takes that family's newest row (Opus 5.5, Sonnet 5.5, Haiku 5.5, Fable 5.1) and is approximate. An ID matching no family, or `None`, takes Opus 5.5 and is approximate. `<synthetic>` costs `Rates(0, 0, 0, 0, 0)` and is exact.
- `prompt_tokens` = `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` of the same usage object (only Haiku 5.5 reads it).
- The table lives only in `model_pricing`; no other module holds a price literal. `agent_costs.model_family` stays, because `cost_by_family` keys by family.
- `agent_cache_report`'s text output keeps every existing line. It adds one line, `Pricing: <SOURCE_URL> (<SOURCE_DATE>); <n> calls priced approximately`, directly before `NOTE:`.

- [ ] **Step 0: Confirm the source**

Fetch the Anthropic pricing page (`https://docs.claude.com/en/docs/about-claude/pricing`, following redirects). Set `SOURCE_URL` to the final URL it resolves to. If any rate row on that page differs from spec § Pricing, stop this task as BLOCKED and name the row (the spec's table is the contract).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_agent_costs.py`; `assistant`, `USAGE_1`, `cache_usage` are its existing helpers)

```python
from agent_tools import model_pricing


class ModelPricingTest(unittest.TestCase):
    def test_opus_5_5_is_priced_at_its_own_row(self):
        self.assertEqual(model_pricing.rates("claude-opus-5-5", 1_000),
                         (model_pricing.Rates(4.0, 20.0, 5.0, 8.0, 0.20), False))

    def test_a_date_suffix_matches_its_base_row(self):
        self.assertEqual(model_pricing.rates("claude-haiku-4-5-20251001", 1_000),
                         (model_pricing.Rates(1.0, 5.0, 1.25, 2.0, 0.10), False))

    def test_haiku_5_5_switches_tier_above_100k_prompt(self):
        low, _ = model_pricing.rates("claude-haiku-5-5", 100_000)
        high, _ = model_pricing.rates("claude-haiku-5-5", 100_001)
        self.assertEqual(low, model_pricing.Rates(0.10, 0.50, 0.125, 0.20, 0.01))
        self.assertEqual(high, model_pricing.Rates(0.50, 2.50, 0.625, 1.0, 0.05))

    def test_unknown_ids_take_the_family_newest_row_and_are_approximate(self):
        self.assertEqual(model_pricing.rates("claude-opus-9-9", 1),
                         (model_pricing.Rates(4.0, 20.0, 5.0, 8.0, 0.20), True))
        self.assertEqual(model_pricing.rates("claude-sonnet-7", 1)[1], True)
        self.assertEqual(model_pricing.rates("mystery-model", 1),
                         (model_pricing.Rates(4.0, 20.0, 5.0, 8.0, 0.20), True))
        self.assertEqual(model_pricing.rates(None, 1)[1], True)

    def test_older_rows_are_exact(self):
        self.assertEqual(model_pricing.rates("claude-sonnet-4-6", 1),
                         (model_pricing.Rates(3.0, 15.0, 3.75, 6.0, 0.30), False))
        self.assertEqual(model_pricing.rates("claude-opus-4-8", 1),
                         (model_pricing.Rates(5.0, 25.0, 6.25, 10.0, 0.50), False))
        self.assertEqual(model_pricing.rates("claude-fable-5", 1),
                         (model_pricing.Rates(10.0, 50.0, 12.5, 20.0, 1.0), False))

    def test_synthetic_costs_nothing(self):
        self.assertEqual(model_pricing.usage_cost("<synthetic>", cache_usage(5_000, 5_000)),
                         (0.0, False))

    def test_usage_cost_prices_each_bucket(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
                 "cache_read_input_tokens": 1_000_000,
                 "cache_creation_input_tokens": 3_000_000,
                 "cache_creation": {"ephemeral_1h_input_tokens": 1_000_000,
                                    "ephemeral_5m_input_tokens": 2_000_000}}
        cost, approximate = model_pricing.usage_cost("claude-opus-5-5", usage)
        self.assertAlmostEqual(cost, 4.0 + 20.0 + 8.0 + 2 * 5.0 + 0.20, places=9)
        self.assertFalse(approximate)
```

Update the two existing expectations that priced by family:
- `test_cost_uses_model_family_pricing` (`claude-sonnet-5`): rename it `test_cost_uses_per_model_pricing` and expect `(10 * 2.0 + 20 * 10.0 + 5 * 2.50 + 100 * 0.20) / 1e6`.
- `test_opus_class_list_price_is_five_and_twenty_five_per_mtok` (`claude-opus-5-5`): rename it `test_opus_5_5_list_price_is_four_and_twenty_per_mtok`, expect `42.2` for both `cost` and `cost_by_family["opus"]`, and rewrite its comment to the Opus 5.5 row.

The cache tests whose fixtures use `claude-opus-5-5` (the default of `cache_call`) assert premiums and reread dollars at Opus-5 rates. Re-derive each from the Opus 5.5 row. Line 1819's `32_002 * (6.25 - 0.50) / 1e6` becomes `32_002 * (5.0 - 0.20) / 1e6`. Recompute every `$` cell regex in `CacheReportCliTest` from the fixture and write the computed value. A cell that rounds to the same dollar stays, and the arithmetic goes in a comment beside each changed assertion. Add one assertion to the first `CacheReportCliTest` case:

```python
        self.assertRegex(out, r"(?m)^Pricing: https://\S+ \(2026-10-25\); 0 calls priced approximately$")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: **Report tests** (Global Constraints), naming only `tests/test_agent_costs.py`.
Expected: FAIL. `ModuleNotFoundError: No module named 'agent_tools.model_pricing'` aborts the module; once the module exists, the updated expectations fail on the old rates.

- [ ] **Step 3: Implement**

- `model_pricing.py`: a module docstring naming issue 432, the source and the tier rule; `Rates`; a dict from exact model ID to `Rates`, where Haiku 5.5 maps to a `(low, high)` pair; a dict from family to newest ID. In `rates`, strip a trailing `-\d{8}`, look up the exact ID, else the family (the first of `opus`, `sonnet`, `haiku`, `fable` contained in the lowercased ID), else Opus 5.5. `usage_cost` uses `cache_write_split` and the formula `(input·in + output·out + cw_5m·write_5m + cw_1h·write_1h + read·read) / 1e6`.
- `transcript_calls.py`: move `_Call`, `_count`, `_merge_usage`, `_add_assistant`, `_waker_kind`, `_user_entry`, `_rendered_size`, `_read_records`, `_is_death` and the TTL constants out of `agent_cache_report`, under the public names above (a partial move, so it is a cut-and-paste rather than `git mv`). `_add_assistant` also records each `tool_use` block's `input` dict in `tool_inputs`. The user-record pass also fills `results` from each `tool_result` block. Attachments of type `hook_additional_context` fill `hook_notes`. The attachment object carries `hookName`, `toolUseID` and a `content` list, whose items are joined with spaces. `STARTUP_ATTACHMENTS` handling stays in `agent_cache_report`, reading the raw attachment entries the reader keeps.
- `agent_cache_report.py`: import from `transcript_calls`. `_premium` uses `rates(call.model, call.context)`: write price = `(cw_1h·write_1h + cw_5m·write_5m)/(cw_1h + cw_5m)`, read = `read`. `_reread_above` uses the read rate. `scan_transcript` returns `approximate_calls`, the count of counted calls whose rates are approximate. `print_report` prints the `Pricing:` line.
- `agent_costs.py`: `scan_file` replaces the `PRICING[family]` block with `message_cost, _ = usage_cost(model, usage)`. Delete `PRICING` and its comment. Import `cache_write_split` from `model_pricing`.

- [ ] **Step 4: Verify**

Run: **Report tests** with `tests/test_agent_costs.py`.
Expected: `OK`. Then run `rg -n "PRICING|6\.25|0\.50\b" python/agent_tools/*.py` and confirm that no hit outside `model_pricing.py` is a price literal.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/model_pricing.py python/agent_tools/transcript_calls.py \
  python/agent_tools/agent_costs.py python/agent_tools/agent_cache_report.py \
  tests/test_agent_costs.py python/README.md
launch-commit … -- -m "feat(agent-costs): price each call by model ID, share one call reader (issue 432)"
```
