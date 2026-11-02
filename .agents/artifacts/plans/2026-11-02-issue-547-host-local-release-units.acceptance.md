# Acceptance record — issue #547

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | A release profile can declare Argus's launchd daemon and signed helper units, and that profile compiles through the 124 profile and adapter contract with no violations. | code | `HostLocalProfileTest` (`tests/test_release_grammar.py`, `tests/test_release_profile.py`), `HostLocalReleaseTest` (`home/common/agent-skills/tests/test_resolve_project.py`), `HostLocalInspectTest` (`tests/test_release_command.py`) under `just agent-workflow-tests` | in final verification | — | — | met |
| AC2 | No Argus-specific literal is added to central policy or to the adapter registry; the vocabulary is neutral. | code | `RegistryTest.test_no_agent_tools_module_names_argus` (`tests/test_release_adapter_core.py`) under `just agent-workflow-tests` | in final verification | — | — | met |
| AC3 | The existing forge and actions-health profiles (nix-config, Nodo) compile unchanged, and the release, conformance and adoption suites stay green. | code | `RegistryTest.test_prior_descriptors_and_forge_profiles_keep_their_base_digests` (`tests/test_release_adapter_core.py`) and the release, conformance and adoption suites under `just agent-workflow-tests` | in final verification | — | — | met |
