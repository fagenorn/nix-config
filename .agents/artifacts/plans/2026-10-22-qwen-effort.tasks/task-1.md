# Task 1: Honor and bound Qwen effort

**Files:**
- Create: `patches/omlx/anthropic-effort.patch`
- Modify: `hosts/darwin/eleven-m5/omlx.nix`
- Create: `hosts/darwin/eleven-m5/omlx-configure.py`
- Create: `tests/test_omlx_configure.py`, `tests/omlx_adapter_probe.py`
- Create: `lib/omlx-check.nix`
- Modify: `flake.nix`, `.github/workflows/ci.yaml`

**Interfaces:**
- The patched `MessagesRequest` accepts typed `output_config.effort`.
- The Anthropic route calls `_merge_anthropic_chat_template_kwargs(request,
  settings, entry)` before rendering, using the existing upstream merge helper.
- `omlx-configure --state-dir PATH --site-packages PATH... --patch-bin PATH
  --patch PATH... --model-settings PATH --server-settings PATH` exits nonzero on
  drift, writes `.restart-needed` after mutations and prints a secret-free JSON
  change summary. Inputs are generated Nix store JSON files and patch paths.

**Invariants:**
- Per D1, all five API efforts map deliberately and invalid inputs fail loudly.
- Explicit valid template values and forced keys retain their precedence.
- Per D2, Qwen defaults are medium and4096; explicit thinking disable survives.
- Per D3, failed patches cannot report successful activation; unchanged settings
  remain byte-for-byte unchanged on the second application.

- [ ] **Step 1: Write the failing tests.** Run a probe against patched real
  upstream modules. The request `output_config={"effort":"low"}` must survive
  parsing and render the low reasoning instructions. Test all API efforts and
  explicit/forced values, including rejected unknown effort. Run the host command
  on scratch source with unrelated nested settings and secrets; expect preserved
  values, bounded defaults and no second mutation. Corrupt one patch target and
  expect nonzero exit with no successful settings application.
- [ ] **Step 2: Observe failure.** Run focused tests before the patch and support
  command exist; expect missing command/effort schema failures.
- [ ] **Step 3: Implement.** Add the schema and narrow model-capability mapping,
  keeping existing thinking controls. Generate a checked host configuration
  command, recursively merge only desired keys, and wire it into activation.
- [ ] **Step 4: Verify.** Run `nix build .#checks.aarch64-darwin.omlx-adapter
  --no-link` and `python3 -m unittest tests/test_branch_protection.py`. Caller runs
  the full host build, required workflow suite and deployed streamed smoke.
- [ ] **Step 5: Commit.** Signed commit of the tested adapter/configuration change
  with `Co-Authored-By: Codex <noreply@openai.com>`; return checks and limitations
  to the caller for review/shipping.

**Falsifiable gate:** Low/medium requests reach different real Qwen prompt
instructions, disabled thinking remains disabled, and incompatible patch input
exits nonzero. These fail if effort is dropped or activation ignores patch drift.

**Payload discipline:** Targeted reads; bounded logs; pass artifacts by path.
