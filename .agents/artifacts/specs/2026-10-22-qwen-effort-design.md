# Honor Claude reasoning effort in oMLX

## Problem

Claude Code's Anthropic requests lose `output_config.effort` in oMLX 0.7.2.
Qwen3.8 then selects xhigh reasoning with no configured thinking bound, making
routine issue work spend minutes on individual responses (#410).

## Solution

Declaratively patch the installed Anthropic adapter and configure the two served
Qwen models with medium default effort and a 4096-token default thinking budget.
Use the existing effort merge helper and preserve explicit template overrides,
forced model settings, and Anthropic thinking controls. Activation must fail when
a required patch cannot be applied or verified.

## Decisions

- Parse `output_config.effort` as the closed set low, medium, high, xhigh, max;
  unsupported inputs fail request validation. Other output configuration fields
  remain accepted for client compatibility.
- For templates advertising exactly low, medium, xhigh, translate high and max
  to xhigh. Other templates receive the requested effort unchanged. Validate the
  effective Qwen effort after merging model defaults and explicit overrides;
  invalid overrides fail before the renderer can silently choose its default.
- Explicit request template effort wins over the translated API effort; forced
  model keys win over both. Existing thinking enabled, adaptive, disabled and
  forced-key precedence remain in effect.
- The Qwen defaults apply to the MLX and Splash served model entries. A positive
  explicit `thinking.budget_tokens` retains upstream request precedence; 4096 is
  a default bound rather than a cap on explicitly requested deep work. Medium
  removes Qwen's additional xhigh instructions for unspecified effort.
- A user-executable configuration command applies checked patches and deep-merges
  owned settings. It preserves unrelated settings, secrets, and nested template
  settings; it records restart need only after a successful mutation.

## Test seams

- Apply the patch to the pinned upstream source, which matches the installed
  adapter, and exercise its real request schema, route merge helper, budget
  resolver and Qwen template. No MLX inference is needed for this seam.
- Run configuration against temporary source and settings directories, twice,
  asserting preserved data, bounded defaults, idempotence and loud patch failure.
- The caller builds the Darwin host and runs Claude-shaped streamed requests
  after installation, with valid text or tool output and no adapter errors.

## Out of scope

Concurrency tuning, model tier separation, workflow helper redesign, and changing
upstream effort behavior for non-Qwen templates. No live settings or Homebrew
package changes happen during implementation.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Translate only the advertised Qwen effort set, reject invalid effective values | Installed Qwen template accepts low/medium/xhigh; upstream fallback otherwise silently removes invalid effort | Global high-to-xhigh mapping changes unrelated models |
| D2 | Medium default plus 4096 thinking tokens on both served Qwen entries | #410 requests bounded default reasoning; explicit upstream budget precedence supports deliberate deeper work | Unbounded xhigh preserves the observed minutes-long default |
| D3 | Checked declarative patching and recursive settings merge in one host support command | Host already owns these keys; universal truthful-terminal-states and tests-that-can-fail standards | Warning-only activation can report success without the fix |
| D4 | Portable flake check uses the pinned upstream fixture and real schema/template | Existing omlx-tap input exactly matches installed adapter; caller owns live smoke | Vendored copy drifts and a duplicate test schema misses dropped fields |
