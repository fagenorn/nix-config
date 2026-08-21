# Prototype — release transactions across unlike project shapes

Throwaway. Answers one question, for [issue #86](https://github.com/fagenorn/nix-config/issues/86):

> Does the settled release contract (#81, #82, #83, #84, #85, #87, #88) survive concrete
> no-mutation dry runs for three unlike real projects and one adversarial future shape,
> **without project-specific branches in the core**?

Nothing here touches a real provider. `invoke` writes to an in-memory dict and `inspect`
reads it back, so no run tags, publishes, deploys, activates, restarts, or mutates any
repository. The clock is a counter you advance by hand.

## Run it

```sh
just prototype-release-transactions        # interactive TUI
python3 prototype-release-transactions/drive.py                     # sweep the whole matrix
python3 prototype-release-transactions/drive.py platform rollback   # one cell, full event ledger
```

## Layout

| file | role |
| --- | --- |
| `core.py` | the keeper: closed vocabularies, profile resolution, the transaction state machine, action protocol, publication/activation sealing, proof evaluation, recovery. **Contains no project name, provider name, or provider verb** (see *Invariant* below). |
| `world.py` | the simulated external world plus the `describe`/`inspect`/`invoke` adapter seam and the fault switches. |
| `profiles.py` | the four shapes, authored the way `.agents/project.json` would author them. All project specifics live here. |
| `scenarios.py` | the case table #86 asks for: success, resume, partial publication, failed activation, false-positive health, irreversible migration, rollback, unsupported operation, plus anchor/unknown/convergence/freshness cases. |
| `drive.py` | headless autopilot over every shape × scenario. No assertions — it prints where each cell lands. |
| `tui.py` | throwaway shell. `[v]` cycles views: state, event ledger, proof plan, gaps, plan preview. |

## The four shapes

* **platform** — closure materialization + forge release index, two independent local host
  activations, retained generations as restore anchors, an advisory smoke obligation with
  no collector.
* **product** — OCI image materialization, channel `index` by compare-and-set, two
  provider-deploy services (one carrying a forward-only startup migration, so it is
  declared `irreversible`), and a `convergent_pull` unit over a frozen fleet membership.
* **daemon** — locally built signed helpers (`materialize` then `promote` into the live
  path), launchd install then restart, resident-identity and interval-smoke proof.
* **library** — the adversarial future shape: publish-only, `activation: "none"`,
  `irreversible` publication, and **no adapter operation that can recall a published
  artifact** — both units are `supersedable_only`, so rollback is structurally impossible.

## Invariant under test

The core must never learn which project it is running. That is checkable, not aspirational:

```sh
python3 - <<'EOF'
import io, tokenize
src = open('prototype-release-transactions/core.py').read()
code = ' '.join(t.string for t in tokenize.generate_tokens(io.StringIO(src).readline)
                if t.type != tokenize.COMMENT
                and not (t.type == tokenize.STRING and t.string.startswith(('"""', "'''")))).lower()
print([w for w in ('nix','railway','ghcr','launchd','docker','github','plist','oci') if w in code] or 'CLEAN')
EOF
```

It currently prints `CLEAN`: every one of the four shapes, across every scenario, is driven
by the same unbranched core. That is the prototype's positive result.

## Verdict

See [`NOTES.md`](./NOTES.md) — four findings, all in the *proof and truth* layer rather than
in the profile/adapter/publication/activation vocabularies.
