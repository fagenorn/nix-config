# Acceptance record — issue #294

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] The guard blocks the label verbs in their quoted, wrapped and spaced spellings, and passes other labels through unchanged — measured: new rows in the adversarial table of `tests/test_claude_permission_guard.py` | code | `CLAUDE_SETTINGS_PATH=<built claude-code-settings.json> python3 -m unittest tests/test_claude_permission_guard.py` (plan D6) | in final verification | — | run against the settings `just build` produces | met |
| AC2 | [code] `just build` succeeds with the guard change — measured: `Nix Eval` CI job | code | `just build` (declared verification); `Nix Eval` is the required PR check | in final verification | — | `Nix Eval` evaluates `nixosConfigurations.anis-desktop` on Linux and gates the merge | met |
