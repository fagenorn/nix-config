# Task 3: `build-delivery --kind contract` stamps an omitted `now`

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`command_build_delivery`, its docstring, and the `build-delivery` parser description)
- Modify: `CLAUDE.md` (one sentence in the "Delivery objects are built" bullet)
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py` (`DeliveryBuilderTest`, and `WorktreePolicyTest.test_help_states_the_contract_resolution_root`)

**Interfaces:**
- Consumes, from Task 1, in `workflow-state.py`: `ledger_clock() -> datetime` and `supplied_time(value: str | None, label: str) -> datetime | None`. Consumes, in `test_delivery_workflow.py`: `CLOCK_ENV`, `PINNED` and `SKEW`.
- Produces: `stamp_contract_input(value: dict[str, Any]) -> None` in `workflow-state.py`.

**Invariants:**
- Only `--kind contract` reads the clock. Every other kind is unchanged (D5).
- A contract input without `now` gets `now = format_utc(ledger_clock())` before the builder runs. The sealed `provenance.created_at` is that value. The builder (`workflow_delivery_build.py`) is not edited and stays pure (D5).
- A supplied `now` that is a string and parses with `parse_utc` is skew-checked with the label `contract now`. A non-string or malformed value reaches the builder unchanged, so its refusal text is unchanged (D12).
- The skew refusal exits 2 with empty stdout and the exact `SKEW` line on stderr.
- The help text and `CLAUDE.md` state the one clock read. No other "read-only" wording changes.

- [ ] **Step 1: Write the failing tests**

In `DeliveryBuilderTest`, change the existing case that expects a contract input without `now` to be refused. In the test that holds `missing = self.contract_input(); missing.pop("now")`, change that line to `missing = self.contract_input(); missing.pop("issue")`. A missing `issue` is still refused with `builder input keys`.

In `WorktreePolicyTest.test_help_states_the_contract_resolution_root`, replace the clause `"It takes no lock, reads no clock and writes nothing.",` with:

```python
                "It takes no lock and writes nothing, and it reads the clock only to stamp "
                "a --kind contract input that omits now.",
```

Append to `DeliveryBuilderTest`:

```python
    def test_a_contract_input_without_now_is_stamped_from_the_clock(self):
        """#309 D5: the command fills `now`; the builder stays pure."""
        self.project()
        value = self.contract_input(); value.pop("now")
        with mock.patch.dict(os.environ, {CLOCK_ENV: PINNED}):
            pinned = self.build("contract", value)
        self.assertEqual(pinned["contract"]["provenance"]["created_at"], PINNED)
        with mock.patch.dict(os.environ):
            os.environ.pop(CLOCK_ENV, None)
            stamped = self.build("contract", value)["contract"]["provenance"]["created_at"]
        recorded = datetime.fromisoformat(stamped.replace("Z", "+00:00"))
        self.assertLessEqual(abs((datetime.now(timezone.utc) - recorded).total_seconds()), 5)

    def test_a_contract_now_over_the_bound_is_refused(self):
        """#309 D5, D12: a parsing future `now` is refused; a malformed one is the builder's."""
        self.project()
        ahead = "2026-09-30T12:15:00Z"
        with mock.patch.dict(os.environ, {CLOCK_ENV: PINNED}):
            refused = self.build("contract", self.contract_input(now=ahead), ok=False)
            at_bound = self.build("contract", self.contract_input(now="2026-09-30T12:01:00Z"))
            malformed = self.build("contract", self.contract_input(now="soon"), ok=False)
        self.assertEqual(
            (refused.returncode, refused.stdout, refused.stderr),
            (2, b"", SKEW.format(label="contract now", supplied=ahead, lead=900,
                                 clock=PINNED).encode()))
        self.assertEqual(at_bound["contract"]["provenance"]["created_at"], "2026-09-30T12:01:00Z")
        self.assertEqual((malformed.returncode, malformed.stdout), (2, b""))
        self.assertTrue(malformed.stderr.startswith(b"workflow-state: build-delivery refused: "),
                        malformed.stderr)
        self.assertNotIn(b"ahead of the clock", malformed.stderr)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py -k DeliveryBuilderTest -k WorktreePolicyTest`
Expected: FAIL. The input without `now` is refused with `builder input keys`. The future `now` is sealed instead of refused. The help clause is not found.

- [ ] **Step 3: Implement**

1. Add beside the Task 1 helpers:

```python
def stamp_contract_input(value: dict[str, Any]) -> None:
    """Fill an omitted contract ``now`` from the clock, and skew-check a supplied one (#309 D5, D12).

    A non-string or malformed ``now`` is left for the builder to refuse in its own words.
    """
    if "now" not in value:
        value["now"] = format_utc(ledger_clock())
        return
    supplied = value["now"]
    if not isinstance(supplied, str):
        return
    try:
        parse_utc(supplied, "contract now")
    except WorkflowError:
        return
    supplied_time(supplied, "contract now")
```

2. In `command_build_delivery`, right after `value = load_json_request(args.input, "builder input")`, add `if args.kind == "contract" and isinstance(value, dict): stamp_contract_input(value)`.

3. Change the docstring's first line to `"""Print one sealed delivery value: no lock and no write, and a clock read only to stamp a contract input that omits ``now`` (#309 D5)."""`. In the `build-delivery` parser description, replace `"It takes no lock, reads no clock and writes nothing. "` with `"It takes no lock and writes nothing, and it reads the clock only to stamp a --kind contract input that omits now. "`.

4. In `CLAUDE.md`, in the "Delivery objects are built, never hand-composed" bullet, replace `It is read-only — no lock, clock or write.` with `It is read-only — no lock or write; it reads the clock only to stamp a \`--kind contract\` input that omits \`now\`.`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_delivery_workflow.py home/common/agent-skills/tests/test_workflow_delivery.py 2>&1 | tail -5` (timeout 1200 s)
Expected: `OK`.

Run: `if grep -q "It is read-only — no lock, clock or write." CLAUDE.md; then echo stale; exit 1; fi`
Expected: no output, exit 0.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/workflow-state.py home/common/agent-skills/tests/test_delivery_workflow.py CLAUDE.md
git commit -m "feat(workflow-state): stamp an omitted contract now from the clock (#309)"
```
