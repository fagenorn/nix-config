# Build the system config and switch to it when running `just` with no args
default: switch

hostname := `hostname | cut -d "." -f 1`

### macos
# Build the nix-darwin system configuration without switching to it
[macos]
build target_host=hostname flags="":
  @echo "Building nix-darwin config..." >&2
  nix --extra-experimental-features 'nix-command flakes'  build ".#darwinConfigurations.{{target_host}}.system" {{flags}}

# Build the nix-darwin config with the --show-trace flag set
[macos]
trace target_host=hostname: (build target_host "--show-trace")

# Build the nix-darwin configuration and switch to it
# Fleet preflight (issue 1451) runs between the build and the activation, as a body line so --no-deps cannot skip it.
# It reads the working directory's tree (the one built and activated), not the justfile's, so --working-directory cannot split them.
[macos]
switch target_host=hostname: (build target_host)
  @echo "switching to new config for {{target_host}}"
  PYTHONPATH="$PWD/python" nix --extra-experimental-features 'nix-command flakes' shell --inputs-from "$PWD" nixpkgs#python3 --command python3 -B -m agent_tools.project_contract.fleet_preflight --manifest "$PWD/home/common/agent-skills/platform-manifest.json"
  sudo ./result/sw/bin/darwin-rebuild switch --flake ".#{{target_host}}"

# Mint a one-hour registration token per self-hosted runner (see
# hosts/common/darwin-github-runners.nix) for the repository its URL names, and
# install it into that runner's own token file, readable only by the runner's group;
# the runner daemon watches the file and registers on change. Needed once, after the
# first switch, or again after deleting /var/lib/github-runners/<name>/.runner.
# Naming another host mints here and installs there over ssh, which needs passwordless
# sudo on that host.
[macos]
register-runners target_host=hostname:
  #!/usr/bin/env bash
  set -euo pipefail
  triples=$(nix eval --raw ".#darwinConfigurations.{{target_host}}.config.services.github-runners" \
    --apply 'rs: builtins.concatStringsSep " " (map (r: "${builtins.replaceStrings [ "https://github.com/" ] [ "" ] r.url}=${r.tokenFile}=${if r.group == null then "_github-runner" else r.group}") (builtins.attrValues rs))')
  # install refuses a pipe as its source, so stage each token in a private file.
  umask 077
  tmp=$(mktemp)
  trap 'rm -f "$tmp"' EXIT
  for triple in $triples; do
    slug=${triple%%=*}
    rest=${triple#*=}
    file=${rest%%=*}
    group=${rest#*=}
    echo "registering runner for $slug on {{target_host}}" >&2
    gh api -X POST "repos/$slug/actions/runners/registration-token" -q .token | tr -d '\n' > "$tmp"
    if [ "{{target_host}}" = "{{hostname}}" ]; then
      sudo install -m 0440 -o root -g "$group" "$tmp" "$file"
    else
      # The token travels on ssh's stdin into a private file on the target, never on a command line.
      ssh -o BatchMode=yes "{{target_host}}" "umask 077; t=\$(mktemp) && cat > \"\$t\" && sudo -n install -m 0440 -o root -g '$group' \"\$t\" '$file'; rc=\$?; rm -f \"\$t\"; exit \$rc" < "$tmp"
    fi
  done

### linux
# Build the NixOS configuration without switching to it
[linux]
build target_host=hostname flags="":
  @echo "Building NixOS config for {{target_host}}..." >&2
  nixos-rebuild build --flake .#{{target_host}} {{flags}}

# Build the NixOS config with the --show-trace flag set
[linux]
trace target_host=hostname: (build target_host "--show-trace")

# Build the NixOS configuration and switch to it.
# Fleet preflight (issue 1451) runs between the build and the activation, as a body line so --no-deps cannot skip it.
# It reads the working directory's tree (the one built and activated), not the justfile's, so --working-directory cannot split them.
[linux]
switch target_host=hostname: (build target_host)
  @echo "Switching NixOS config for {{target_host}}..."
  PYTHONPATH="$PWD/python" nix --extra-experimental-features 'nix-command flakes' shell --inputs-from "$PWD" nixpkgs#python3 --command python3 -B -m agent_tools.project_contract.fleet_preflight --manifest "$PWD/home/common/agent-skills/platform-manifest.json"
  sudo nixos-rebuild switch --flake .#{{target_host}}

## colmena
cbuild:
  colmena build

capply:
  colmena apply

# Update flake inputs to their latest revisions
update:
  nix flake update

## agent skills
# Run one skill eval. Pipeline evals sandbox the fixture repo and grade the artifacts;
# plan-only evals print the prompt + expected output for manual grading.
# See home/common/agent-skills/evals/README.md
evals skill id:
  ./home/common/agent-skills/evals/run-eval.sh {{skill}} {{id}}

# The source package the agent recipes run (#175 D6).
agent_tools_path := justfile_directory() / "python"
system_result := justfile_directory() / "result"

# Run the lints (verification command `lint`): every member runs and each failing one is named.
lint:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.delivery.verification_command lint

# Run the build then the agent workflow suite (verification command `test`), naming each failing member.
test:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.delivery.verification_command test

# Run the suite members this branch touches, or the whole suite when a build input changes (the `test-touched` command).
test-touched:
  tools="$(nix build --no-link --print-out-paths '{{justfile_directory()}}#agent-platform.tools')" && test -n "$tools" && AGENT_PLATFORM_TOOLS="$tools/bin" WORKFLOW_POLICY_SURFACE=source PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.delivery.touched_tests --base origin/main --source-root python --pair home/common/claude-code/lifecycle_guard.py=tests/test_claude_permission_guard.py --cover 'python/agent_tools/delivery/engine*.py=tests/test_engine_*.py' --cover 'python/agent_tools/delivery/host_admission.py=tests/test_engine_*.py' --cover 'python/agent_tools/delivery/procedure_check.py=tests/test_engine_*.py' --cover 'python/agent_tools/delivery/procedure_terms.py=tests/test_engine_*.py' --cover 'python/agent_tools/delivery/size_caps.py=tests/test_engine_*.py' --cover 'python/agent_tools/delivery/lane_rule.py=tests/test_engine_*.py' --cover 'python/agent_tools/delivery/rule_reader.py=tests/test_engine_*.py' --cover 'python/agent_tools/delivery/procedures/*=tests/test_engine_*.py' --cover 'tests/engine_*.py=tests/test_engine_*.py' --cover 'tests/fixtures/engine-*=tests/test_engine_*.py' --build-command 'just build' --env-from 'tests/test_claude_permission_guard.py=just claude-guard-test-env' --build-when '*.nix' --build-when flake.lock --build-when .sops.yaml --build-when 'data/*' --build-when 'homebrew/*' --build-when 'patches/*' --build-when 'secrets/*' --build-when 'vars/*' --dotnet-tests

# Run Conformance over every rule as the required CI check does (the conformance command).
conformance:
  nix shell {{quote(justfile_directory() + "#agent-platform")}} --command conformance run --purpose ci --lint-times

# Print the two variables the lifecycle guard's test reads, from the built ./result (`test-touched` builds first).
claude-guard-test-env:
  @set -- $(nix-store --query --requisites ./result \
    | grep -- '-claude-code-settings\.json$' || true); \
    if [ "$#" -ne 1 ]; then \
      echo "expected exactly one generated Claude settings artifact; found $#" >&2; \
      exit 1; \
    fi; \
    settings="$1"; \
    set -- $(nix-store --query --requisites ./result \
      | grep -- '-claude-bash-lifecycle-guard-base-policy\.json$' || true); \
    if [ "$#" -ne 1 ]; then \
      echo "expected exactly one built guard base policy; found $#" >&2; \
      exit 1; \
    fi; \
    printf 'CLAUDE_SETTINGS_PATH=%s\nCLAUDE_GUARD_BASE_POLICY_PATH=%s\n' "$settings" "$1"

# Verify durable workflow lifecycle and skill contracts, min(8, CPUs - 2) test files at a time, longest first (SUITE_RUNNER_JOBS or --jobs N sets the cap; --jobs 1 runs them serially with live output). The suite gets the platform package's pinned tools.
agent-workflow-tests *args:
  tools="$(nix build --no-link --print-out-paths '{{justfile_directory()}}#agent-platform.tools')" && test -n "$tools" && AGENT_PLATFORM_TOOLS="$tools/bin" PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.delivery.suite_runner {{args}} \
    home/common/agent-skills/tests/test_host_admission.py \
    home/common/agent-skills/tests/test_inprocess_cli.py \
    home/common/agent-skills/tests/test_workflow_skill_contracts.py \
    home/common/agent-skills/tests/test_codex_review_effort.py \
    home/common/agent-skills/tests/test_dispatch_contracts.py \
    home/common/agent-skills/tests/test_shell_example_contracts.py \
    home/common/agent-skills/tests/test_ship_release_contracts.py \
    home/common/agent-skills/tests/test_eval_cases.py \
    home/common/agent-skills/tests/test_eval_sandboxes.py \
    home/common/agent-skills/tests/test_agent_model_matrix.py \
    home/common/agent-skills/tests/test_instruction_load.py \
    home/common/agent-skills/tests/test_instruction_surface_lint.py \
    home/common/agent-skills/tests/test_skill_lint.py \
    home/common/agent-skills/tests/test_agnostic_lint.py \
    home/common/agent-skills/tests/test_diff_scope.py \
    home/common/agent-skills/tests/test_resolve_project.py \
    home/common/agent-skills/tests/test_resolve_platform.py \
    home/common/agent-skills/tests/test_resolve_schema_three.py \
    home/common/agent-skills/tests/test_verification_before_pull_request.py \
    home/common/agent-skills/tests/test_pre_pull_request_conformance.py \
    home/common/agent-skills/tests/test_resolve_unknown_bindings.py \
    home/common/agent-skills/tests/test_resolve_core.py \
    home/common/agent-skills/tests/test_resolve_conformance_workflow.py \
    home/common/agent-skills/tests/test_schema_three_derivation.py \
    home/common/agent-skills/tests/test_attempt_history.py \
    home/common/agent-skills/tests/test_attempt_budget.py \
    home/common/agent-skills/tests/test_resolve_platform_status.py \
    home/common/agent-skills/tests/test_fleet_preflight.py \
    home/common/agent-skills/tests/test_host_readiness.py \
    home/common/agent-skills/tests/test_conformance.py \
    home/common/agent-skills/tests/test_conformance_checks.py \
    home/common/agent-skills/tests/test_conformance_records.py \
    home/common/agent-skills/tests/test_conformance_suppressions.py \
    home/common/agent-skills/tests/test_node_lint.py \
    home/common/agent-skills/tests/test_conformance_registry.py \
    home/common/agent-skills/tests/test_conformance_ruff.py \
    home/common/agent-skills/tests/test_conformance_lint_times.py \
    home/common/agent-skills/tests/test_conformance_procedures.py \
    home/common/agent-skills/tests/test_adopt_project.py \
    home/common/agent-skills/tests/test_adopt_migrate.py \
    home/common/agent-skills/tests/test_adopt_project_boundaries.py \
    home/common/agent-skills/tests/test_adopt_apply.py \
    home/common/agent-skills/tests/test_adopt_hook_install.py \
    home/common/agent-skills/tests/test_adopt_draft_hook_install.py \
    home/common/agent-skills/tests/test_adopt_signing_pointer.py \
    home/common/agent-skills/tests/test_adopt_apply_formatting.py \
    home/common/agent-skills/tests/test_adopt_entries.py \
    home/common/agent-skills/tests/test_adopt_conformance.py \
    home/common/agent-skills/tests/test_adopt_schema_three_draft.py \
    home/common/agent-skills/tests/test_adopt_conformance_apply.py \
    home/common/agent-skills/tests/test_adopt_verify.py \
    home/common/agent-skills/tests/test_adopt_links.py \
    home/common/agent-skills/tests/test_adopt_references.py \
    home/common/agent-skills/tests/test_artifact_budget.py \
    tests/test_agent_tools_canonical.py \
    tests/test_agent_tools_siblings.py \
    tests/test_agent_tools_layout.py \
    tests/test_agent_tools_semver.py \
    tests/test_engine_check.py \
    tests/test_engine_check_process.py \
    tests/test_engine_direct_procedures.py \
    tests/test_engine_graders.py \
    tests/test_engine_findings.py \
    tests/test_engine_ledger.py \
    tests/test_engine_core.py \
    tests/test_engine_commands.py \
    tests/test_engine_guard.py \
    tests/test_engine_deliver.py \
    tests/test_engine_start_check.py \
    tests/test_engine_session.py \
    tests/test_engine_session_limits.py \
    tests/test_engine_tool_denied.py \
    tests/test_engine_whole_shell.py \
    tests/test_engine_reaping.py \
    tests/test_engine_keep_alive.py \
    tests/test_engine_continue.py \
    tests/test_engine_cut_continue.py \
    tests/test_engine_resume.py \
    tests/test_engine_housekeeping.py \
    tests/test_engine_history_steps.py \
    tests/test_engine_stop.py \
    tests/test_engine_caps.py \
    tests/test_engine_fanout.py \
    tests/test_engine_slots.py \
    tests/test_engine_fixture.py \
    tests/test_engine_stubbed_run.py \
    tests/test_engine_stubbed_world.py \
    tests/test_proof_run.py \
    tests/test_bound_issues.py \
    tests/test_engine_step_coverage.py \
    tests/test_independent_review.py \
    tests/test_issue_setup.py \
    tests/test_closing.py \
    tests/test_holding.py \
    tests/test_landing.py \
    tests/test_land_tally.py \
    tests/test_verify_rounds.py \
    tests/test_engine_land_recovery.py \
    tests/test_engine_verify_rounds.py \
    tests/test_plan_amend.py \
    tests/test_verify_block.py \
    tests/test_verify_pending.py \
    tests/test_verify_pending_owner.py \
    tests/test_verify_answer.py \
    tests/test_verify_pending_pass.py \
    tests/test_verify_pending_units.py \
    tests/test_verify_pending_interrupted.py \
    tests/test_host_readings.py \
    tests/test_platform_package_hosts.py \
    tests/test_fleet_preflight_recipes.py \
    tests/test_darwin_user_agent_reload.py \
    tests/test_omlx_restart.py \
    tests/test_omlx_declaration.py \
    tests/test_omlx_activation_hold.py \
    tests/test_darwin_path_order.py \
    tests/test_pinned_file.py \
    tests/test_github_runners.py \
    tests/test_host_sudo.py \
    tests/test_runner_home.py \
    tests/test_host_alerts.py \
    tests/test_omlx_memory_watch.py \
    tests/test_omlx_memory_fseventsd.py \
    tests/test_memory_budget.py \
    tests/test_omlx_memory_day.py \
    tests/test_omlx_memory_census.py \
    tests/test_omlx_memory_records.py \
    tests/test_omlx_reactive_restart.py \
    tests/test_omlx_memory_events.py \
    tests/test_omlx_memory_census_day.py \
    tests/test_omlx_memory_verify_trees.py \
    tests/test_omlx_memory_verify_day.py \
    tests/test_omlx_reactive_restart_day.py \
    tests/test_memory_floor.py \
    tests/test_memory_floor_priority.py \
    tests/test_memory_floor_gate.py \
    tests/test_memory_floor_check.py \
    tests/test_memory_floor_speed.py \
    tests/test_interrupted_reruns_check.py \
    tests/test_verify_checks.py \
    tests/test_loopback_server.py \
    tests/test_cleanup_fix_check.py \
    tests/test_console_approved_action_check.py \
    tests/test_console_takeover_merge_check.py \
    tests/test_console_release_rerun_check.py \
    tests/test_console_production_rerun_check.py \
    tests/test_issue_branch.py \
    tests/test_program_copies.py \
    tests/test_keepalive_end_turn_cap.py \
    tests/test_forge_markers.py \
    tests/test_look_marker.py \
    tests/test_look_approval.py \
    tests/test_look_lint.py \
    tests/test_program_bridge.py \
    tests/test_look_gate_end_to_end.py \
    tests/test_forge_claim.py \
    tests/test_forge_issue.py \
    tests/test_forge_owner_action.py \
    tests/test_owner_actions.py \
    tests/test_forge_land_lock.py \
    tests/test_forge_land_lease.py \
    tests/test_forge_land_deadline.py \
    tests/test_landing_reading.py \
    tests/test_verified_tree.py \
    tests/test_transaction_core.py \
    tests/test_transaction_custody.py \
    tests/test_transaction_invocation.py \
    tests/test_transaction_plan.py \
    tests/test_transaction_proof.py \
    tests/test_transaction_recovery_plan.py \
    tests/test_transaction_recovery.py \
    tests/test_transaction_recovery_settle.py \
    tests/test_transaction_receipt.py \
    tests/test_transaction_disposition.py \
    tests/test_transaction_core_sweep.py \
    tests/test_release_grammar.py \
    tests/test_release_profile.py \
    tests/test_release_command.py \
    tests/test_fallback_audit.py \
    tests/test_release_driver.py \
    tests/test_release_dispose.py \
    tests/test_release_crash_matrix.py \
    tests/test_release_cutover.py \
    tests/test_release_evidence.py \
    tests/test_release_verification.py \
    tests/test_forge_adapter.py \
    tests/test_actions_health_adapter.py \
    tests/test_railway_deploy_adapter.py \
    tests/test_release_merge.py \
    tests/test_release_sync.py \
    tests/test_release_lock.py \
    tests/test_guard_policy.py \
    tests/test_git_pre_push_hook.py \
    tests/test_guard_sandbox_git.py \
    tests/test_release_adapter_core.py \
    tests/test_codesigned_artifact_adapter.py \
    tests/test_launchd_agent_adapter.py \
    tests/test_run_profile.py \
    tests/test_agent_gate_bundle.py \
    tests/test_retired_surfaces.py \
    tests/test_promotion_documents.py \
    tests/test_promotion_lifecycle.py \
    tests/test_promotion_deployment.py \
    tests/test_promotion_demo.py \
    tests/test_context_map_lint.py \
    tests/test_adr_number.py \
    tests/test_docs_tree.py \
    tests/test_standard_ids.py \
    tests/test_standards_lint.py \
    tests/test_router.py \
    tests/test_citation_lint.py \
    tests/test_never_rise.py \
    tests/test_comment_lint.py \
    tests/test_cleanup_issue.py \
    tests/test_lint_time.py \
    tests/test_ruff_lint.py \
    tests/test_suite_source.py \
    tests/test_skipped_test_lint.py \
    tests/test_copied_test_lint.py \
    tests/test_dotnet_format_lint.py \
    tests/test_suppressions.py \
    tests/test_decision_record_wording.py \
    tests/test_module_docstring_wording.py \
    tests/test_cache_proxy.py \
    tests/test_cache_keepalive.py \
    tests/test_claude_account_routing.py \
    tests/test_branch_protection.py \
    tests/test_devenv_cache_ignored.py \
    tests/test_suite_part.py \
    tests/test_suite_runner.py \
    tests/test_suite_runner_split.py \
    tests/test_suite_tiers.py \
    tests/test_suite_timing.py \
    tests/test_verify_slot.py \
    tests/test_verify_slot_short_lane.py \
    tests/test_verify_slot_timeouts.py \
    tests/test_verify_queue.py \
    tests/test_verify_tree.py \
    tests/test_verification_command.py \
    tests/test_touched_tests.py \
    tests/test_console_event_log.py \
    tests/test_console_release_card.py \
    tests/test_console_release_card_service.py \
    tests/test_console_prompt_card.py \
    tests/test_console_prompt_card_service.py \
    tests/test_console_view.py \
    tests/test_console_view_action.py \
    tests/test_console_view_lock_place.py \
    tests/test_console_work_sentence.py \
    tests/test_console_done_for_now.py \
    tests/test_console_view_held_sprint.py \
    tests/test_console_draft_facts.py \
    tests/test_console_failed_start.py \
    tests/test_console_activation.py \
    tests/test_console_activation_check.py \
    tests/test_console_activation_contract.py \
    tests/test_console_capacity.py \
    tests/test_console_capacity_check.py \
    tests/test_console_probe.py \
    tests/test_console_signin.py \
    tests/test_console_signin_run.py \
    tests/test_console_signin_service.py \
    tests/test_console_account_add.py \
    tests/test_console_account_remove.py \
    tests/test_console_account_service.py \
    tests/test_console_account_remove_service.py \
    tests/test_console_folder_trust.py \
    tests/test_console_trust_start.py \
    tests/test_console_plan_questions.py \
    tests/test_console_project_question.py \
    tests/test_console_credential_timing.py \
    tests/test_console_question_records.py \
    tests/test_console_question_check.py \
    tests/test_console_contract_draft.py \
    tests/test_console_hooks_missing.py \
    tests/test_console_checkout_remote.py \
    tests/test_console_register.py \
    tests/test_console_register_service.py \
    tests/test_console_register_draft_service.py \
    tests/test_console_register_check.py \
    tests/test_console_draft_register_check.py \
    tests/test_console_approve.py \
    tests/test_console_approve_service.py \
    tests/test_console_approve_waits.py \
    tests/test_console_commit_failure.py \
    tests/test_console_accounts_sandbox.py \
    tests/test_console_manager_check.py \
    tests/test_console_page_account_check.py \
    tests/test_console_launch_profile_check.py \
    tests/test_console_permission_check.py \
    tests/test_console_bypass_proof_checks.py \
    tests/test_console_bypass_proof_github.py \
    tests/test_console_bypass_proof.py \
    tests/test_console_bypass_proof_mcp.py \
    tests/test_console_bypass_proof_wakes.py \
    tests/test_console_message_check.py \
    tests/test_console_revive_check.py \
    tests/test_console_cleanup_check.py \
    tests/test_adopt_hook_check.py \
    tests/test_console_lock_wait_check.py \
    tests/test_console_serve_probe_check.py \
    tests/test_console_run_line_check.py \
    tests/test_verify_engine_past_implement.py \
    tests/test_console_look_check.py \
    tests/test_console_look_kept_check.py \
    tests/test_console_live_fault_check.py \
    tests/test_pr_green.py \
    tests/test_console_page.py \
    tests/test_console_page_action.py \
    tests/test_console_page_move.py \
    tests/test_console_page_work.py \
    tests/test_console_page_done_for_now.py \
    tests/test_console_page_held_sprint.py \
    tests/test_console_long_permission_card.py \
    tests/test_console_controls.py \
    tests/test_console_goal_box.py \
    tests/test_console_service.py \
    tests/test_console_publish_hold.py \
    tests/test_console_close.py \
    tests/test_console_stream.py \
    tests/test_console_sessions.py \
    tests/test_console_session_start.py \
    tests/test_console_hook_cost.py \
    tests/test_console_inbox.py \
    tests/test_console_tracker.py \
    tests/test_console_digest.py \
    tests/test_console_delivery_ended.py \
    tests/test_console_writes.py \
    tests/test_console_host_alerts.py \
    tests/test_console_host_alerts_panel.py \
    tests/test_console_answer.py \
    tests/test_console_sprints.py \
    tests/test_console_manager_identity.py \
    tests/test_console_contract_plain_words.py \
    tests/test_console_owner_words.py \
    tests/test_console_action_card.py \
    tests/test_console_revive.py \
    tests/test_console_idle.py \
    tests/test_console_briefs.py \
    tests/test_console_messages.py \
    tests/test_console_questions.py \
    tests/test_console_look_answer.py \
    tests/test_console_notices.py \
    tests/test_console_reports.py \
    tests/test_console_screenshots.py \
    tests/test_console_screenshot_widths.py \
    tests/test_console_permission_shots.py \
    tests/test_console_control_shots.py \
    tests/test_console_sprint_end_fold.py \
    tests/test_console_screenshot_clock.py \
    tests/test_console_sprint_command.py \
    tests/test_console_manager_contract_held.py \
    tests/test_console_sprint_action.py \
    tests/test_console_sprint_warnings.py \
    tests/test_console_pictures.py \
    tests/test_console_manager.py \
    tests/test_console_launch_short_id.py \
    tests/test_console_permission.py \
    tests/test_console_manager_service.py \
    tests/test_console_permit.py \
    tests/test_console_own_reads.py \
    tests/test_console_own_reads_wiring.py \
    tests/test_console_permit_wire.py \
    tests/test_console_permit_rerun_service.py \
    tests/test_console_approved_action.py \
    tests/test_console_stops.py \
    tests/test_console_revive_service.py \
    tests/test_console_idle_service.py \
    tests/test_console_quota_move.py \
    tests/test_console_nudge.py \
    tests/test_console_deliveries.py \
    tests/test_console_engine_runs.py \
    tests/test_console_sprint_engine.py \
    tests/test_console_movement.py \
    tests/test_console_movement_check.py \
    tests/test_console_issue_titles.py \
    tests/test_console_spend.py \
    tests/test_console_engine_spend.py \
    tests/test_console_transcript_digest.py \
    tests/test_console_spend_page.py \
    tests/test_console_guest.py \
    tests/test_console_peer.py \
    tests/test_console_peer_service.py \
    tests/test_console_owner_port_check.py \
    tests/test_console_guest_socket_check.py \
    tests/test_console_guest_service.py \
    tests/test_console_guest_page.py \
    tests/test_console_guest_actions.py \
    tests/test_console_guest_account.py \
    tests/test_console_units.py \
    tests/test_owner_services_units.py \
    tests/test_proof_run_units.py \
    tests/test_system_packages.py \
    home/common/agent-skills/tests/test_program_harness.py \
    home/common/agent-skills/tests/test_deliver_standard_program.py \
    home/common/agent-skills/tests/test_deliver_standard_landing.py \
    home/common/agent-skills/tests/test_deliver_standard_resume_ahead.py \
    home/common/agent-skills/tests/test_deliver_standard_before_pull_request.py \
    home/common/agent-skills/tests/test_deliver_standard_lane_rule.py \
    home/common/agent-skills/tests/test_deliver_standard_work_rules.py \
    home/common/agent-skills/tests/test_deliver_batch_program.py \
    home/common/agent-skills/tests/test_deliver_batch_landing.py \
    home/common/agent-skills/tests/test_deliver_batch_before_pull_request.py \
    home/common/agent-skills/tests/test_deliver_batch_lane_rule.py \
    home/common/agent-skills/tests/test_deliver_batch_work_rules.py \
    home/common/agent-skills/evals/tests/test-run-eval-tree.sh

# Validate every explicit pipeline dispatch and print the representative trace.
agent-model-matrix:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_model_matrix validate
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_model_matrix trace representative

# Compare the instruction documents each agent profile loads at two revisions (#155 D9).
agent-instruction-load *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.instruction_load {{args}}

# Run this host's due read-only verification checks and close passing issues (issue 630)
verify host *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.verification.verify_pending run --host {{host}} {{args}}

# Shoot the console's sprint states against a fixture console, 120 PNGs into out (default ~/tmp/clarity-screenshots) (#1086).
console-screenshots out="":
  #!/usr/bin/env bash
  set -euo pipefail
  pkgs='(builtins.getFlake (toString ./.)).inputs.nixpkgs.legacyPackages.${builtins.currentSystem}'
  py=$(nix build --no-link --print-out-paths --impure --expr "($pkgs).python3.withPackages (ps: [ ps.playwright ])")
  browsers=$(nix build --no-link --print-out-paths --impure --expr "($pkgs).playwright-driver.browsers")
  dir="{{out}}"
  PLAYWRIGHT_BROWSERS_PATH="$browsers" PYTHONPATH="{{agent_tools_path}}" "$py/bin/python3" -m tests.console_screenshots --out "${dir:-$HOME/tmp/clarity-screenshots}"

# Check the skill contracts, agent-tool launchers, generated Claude settings and Claude launchers against what the Nix build installs.
agent-installed-skill-tests: build
  @set -- $(nix-store --query --requisites ./result \
    | grep -- '-home-manager-files$' || true); \
    if [ "$#" -ne 1 ]; then \
      echo "expected exactly one built home-manager-files output; found $#" >&2; \
      exit 1; \
    fi; \
    installed_home="$1"; \
    set -- $(nix-store --query --requisites ./result \
      | grep -- '-claude-code-settings\.json$' || true); \
    if [ "$#" -ne 1 ]; then \
      echo "expected exactly one generated Claude settings artifact; found $#" >&2; \
      exit 1; \
    fi; \
    settings="$1"; \
    set -- $(nix-store --query --requisites ./result \
      | grep -- '-claude-bash-lifecycle-guard-base-policy\.json$' || true); \
    if [ "$#" -ne 1 ]; then \
      echo "expected exactly one built guard base policy; found $#" >&2; \
      exit 1; \
    fi; \
    base_policy="$1"; \
    set -- $(nix-store --query --requisites ./result \
      | grep -- '-claude-code-with-accounts-[^/]*$' || true); \
    if [ "$#" -ne 1 ]; then \
      echo "expected exactly one built Claude Code package; found $#" >&2; \
      exit 1; \
    fi; \
    AGENT_SKILLS_INSTALLED_HOME="$installed_home" AGENT_TOOLS_SYSTEM_RESULT="{{system_result}}" CLAUDE_SETTINGS_PATH="$settings" CLAUDE_GUARD_BASE_POLICY_PATH="$base_policy" CLAUDE_CODE_PACKAGE="$1" python3 -m unittest -v \
      home/common/agent-skills/tests/test_dispatch_contracts.py \
      home/common/agent-skills/tests/test_shell_example_contracts.py \
      home/common/agent-skills/tests/test_workflow_skill_contracts.py \
      tests/test_agent_tools_launchers.py \
      tests/test_promotion_installed.py \
      tests/test_impeccable_installed.py \
      tests/test_claude_code_installed.py \
      tests/test_claude_permission_guard_own_files.py

# Compare the skills activated on this host (~/.claude/skills) with the skill source; run it after a switch, since `test` checks the skills from source only (issue 1580).
agent-activated-skill-tests:
  env -u WORKFLOW_POLICY_SURFACE PYTHONPATH="{{agent_tools_path}}" python3 -m unittest -v -k test_installed_policy_surface_matches_source_contract home/common/agent-skills/tests/test_workflow_skill_contracts.py

## claude code
# Print the Nix-generated ~/.claude/settings.json exactly as the next switch will write it.
show-claude-settings: build
  @set -- $(nix-store --query --requisites ./result \
    | grep -- '-claude-code-settings\.json$' || true); \
    if [ "$#" -ne 1 ]; then \
      echo "expected exactly one generated Claude settings artifact; found $#" >&2; \
      exit 1; \
    fi; \
    cat "$1"

## branch protection
# Idempotent: the API replaces the whole protection object, so re-running after a job
# rename converges. `main` is written literally in all three recipes on purpose —
# gh's {branch} placeholder expands to the *current* branch, which would point these
# at whatever branch you happen to be standing on.
#
# `just` shows only the LAST comment line of a block in `just --list`, so each recipe
# keeps its one-line summary immediately above it.

# Apply .github/branch-protection.json to `main`, making its contexts required checks.
protect-main:
  gh api --method PUT repos/{owner}/{repo}/branches/main/protection \
    --input .github/branch-protection.json

# Remove all branch protection from `main` — the documented undo for protect-main.
unprotect-main:
  gh api --method DELETE repos/{owner}/{repo}/branches/main/protection

# Note the API asymmetry when reading the output: GET returns enforce_admins as an object,
# {"enabled": true}, where PUT takes a plain boolean.

# Print `main`'s live branch protection as GitHub currently has it.
show-protection:
  gh api repos/{owner}/{repo}/branches/main/protection

## remote nix vm installation
install IP:
  ssh -o "StrictHostKeyChecking no" nixos@{{IP}} "sudo bash -c '\
    nix-shell -p git --run \"cd /root/ && \
    if [ -d \"nix-config\" ]; then \
        rm -rf nix-config; \
    fi && \
    git clone https://github.com/ironicbadger/nix-config.git && \
    cd nix-config/lib/install && \
    sh install-nix.sh\"'"


# Profile Workflow run dirs: fresh and cache-read tokens, wall time and tool calls per phase, agent, label family and delivered issue
agent-run-profile *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.delivery.run_profile {{args}}

# Apply issue #70's token-and-quality gate to a trials manifest of emitted cost records
agent-gate-bundle *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.delivery.agent_gate_bundle {{args}}

# Certify issue 554's forge pr_merge against the live sandbox repository (real GitHub calls)
release-merge-certification *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m tests.release_merge_certification {{args}}

# Capture, evaluate, validate and advance promotion candidates (#127)
[positional-arguments]
promotion *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.delivery.promotion "$@"

# Garbage collect old OS generations and remove stale packages from the nix store
gc generations="5":
  nix-env --delete-generations {{generations}}
  nix-store --gc
