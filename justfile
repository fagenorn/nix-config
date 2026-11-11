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
[macos]
switch target_host=hostname: (build target_host)
  @echo "switching to new config for {{target_host}}"
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
[linux]
switch target_host=hostname: (build target_host)
  @echo "Switching NixOS config for {{target_host}}..."
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

# Verify durable workflow lifecycle and skill contracts, min(8, CPUs - 2) test files at a time, longest first (SUITE_RUNNER_JOBS or --jobs N sets the cap; --jobs 1 runs them serially with live output).
agent-workflow-tests *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.delivery.suite_runner {{args}} \
    home/common/agent-skills/tests/test_host_admission.py \
    home/common/agent-skills/tests/test_inprocess_cli.py \
    home/common/agent-skills/tests/test_workflow_skill_contracts.py \
    home/common/agent-skills/tests/test_dispatch_contracts.py \
    home/common/agent-skills/tests/test_shell_example_contracts.py \
    home/common/agent-skills/tests/test_ship_release_contracts.py \
    home/common/agent-skills/tests/test_eval_cases.py \
    home/common/agent-skills/tests/test_agent_model_matrix.py \
    home/common/agent-skills/tests/test_instruction_load.py \
    home/common/agent-skills/tests/test_skill_lint.py \
    home/common/agent-skills/tests/test_agnostic_lint.py \
    home/common/agent-skills/tests/test_diff_scope.py \
    home/common/agent-skills/tests/test_resolve_project.py \
    home/common/agent-skills/tests/test_resolve_platform.py \
    home/common/agent-skills/tests/test_resolve_platform_status.py \
    home/common/agent-skills/tests/test_conformance.py \
    home/common/agent-skills/tests/test_conformance_checks.py \
    home/common/agent-skills/tests/test_conformance_registry.py \
    home/common/agent-skills/tests/test_adopt_project.py \
    home/common/agent-skills/tests/test_adopt_migrate.py \
    home/common/agent-skills/tests/test_adopt_project_boundaries.py \
    home/common/agent-skills/tests/test_adopt_apply.py \
    home/common/agent-skills/tests/test_adopt_verify.py \
    home/common/agent-skills/tests/test_adopt_links.py \
    home/common/agent-skills/tests/test_adopt_references.py \
    home/common/agent-skills/tests/test_artifact_budget.py \
    tests/test_agent_tools_canonical.py \
    tests/test_agent_tools_siblings.py \
    tests/test_agent_tools_layout.py \
    tests/test_agent_tools_semver.py \
    tests/test_lane_triage.py \
    tests/test_plan_amend.py \
    tests/test_verify_block.py \
    tests/test_verify_pending.py \
    tests/test_verify_pending_owner.py \
    tests/test_verify_pending_pass.py \
    tests/test_verify_pending_units.py \
    tests/test_darwin_user_agent_reload.py \
    tests/test_darwin_path_order.py \
    tests/test_github_runners.py \
    tests/test_host_sudo.py \
    tests/test_runner_home.py \
    tests/test_verify_checks.py \
    tests/test_issue_branch.py \
    tests/test_keepalive_end_turn_cap.py \
    tests/test_forge_markers.py \
    tests/test_forge_claim.py \
    tests/test_forge_issue.py \
    tests/test_forge_owner_action.py \
    tests/test_owner_actions.py \
    tests/test_forge_land_lock.py \
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
    tests/test_release_crash_matrix.py \
    tests/test_release_cutover.py \
    tests/test_release_evidence.py \
    tests/test_release_verification.py \
    tests/test_forge_adapter.py \
    tests/test_actions_health_adapter.py \
    tests/test_railway_deploy_adapter.py \
    tests/test_release_merge.py \
    tests/test_release_sync.py \
    tests/test_guard_policy.py \
    tests/test_git_pre_push_hook.py \
    tests/test_release_adapter_core.py \
    tests/test_codesigned_artifact_adapter.py \
    tests/test_launchd_agent_adapter.py \
    tests/test_run_profile.py \
    tests/test_agent_gate_bundle.py \
    tests/test_agent_gate_corpus.py \
    tests/test_retired_surfaces.py \
    tests/test_promotion_documents.py \
    tests/test_promotion_lifecycle.py \
    tests/test_promotion_deployment.py \
    tests/test_promotion_demo.py \
    tests/test_context_map_lint.py \
    tests/test_docs_tree.py \
    tests/test_cache_proxy.py \
    tests/test_cache_keepalive.py \
    tests/test_claude_account_routing.py \
    tests/test_branch_protection.py \
    tests/test_suite_runner.py \
    tests/test_console_event_log.py \
    tests/test_console_view.py \
    tests/test_console_page.py \
    tests/test_console_service.py \
    tests/test_console_stream.py \
    tests/test_console_sessions.py \
    tests/test_console_session_start.py \
    tests/test_console_hook_cost.py \
    home/common/agent-skills/tests/test_deliver_standard_program.py \
    home/common/agent-skills/tests/test_deliver_batch_program.py \
    home/common/agent-skills/evals/tests/test-run-eval-tree.sh

# Validate every explicit pipeline dispatch and print the representative trace.
agent-model-matrix:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_model_matrix validate
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_model_matrix trace representative

# Compare the instruction documents each agent profile loads at two revisions (#155 D9).
agent-instruction-load *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.instruction_load {{args}}

# Run the Instruction Budget gate against origin/main; pass --raise-label for a labelled raise (#292 D9).
agent-instruction-budget *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.instruction_load check --base origin/main {{args}}

# Run this host's due read-only verification checks and close passing issues (issue 630)
verify host *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.verification.verify_pending run --host {{host}} {{args}}

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
      | grep -- '-claude-code-with-accounts-[^/]*$' || true); \
    if [ "$#" -ne 1 ]; then \
      echo "expected exactly one built Claude Code package; found $#" >&2; \
      exit 1; \
    fi; \
    AGENT_SKILLS_INSTALLED_HOME="$installed_home" AGENT_TOOLS_SYSTEM_RESULT="{{system_result}}" CLAUDE_SETTINGS_PATH="$settings" CLAUDE_CODE_PACKAGE="$1" python3 -m unittest -v \
      home/common/agent-skills/tests/test_dispatch_contracts.py \
      home/common/agent-skills/tests/test_shell_example_contracts.py \
      home/common/agent-skills/tests/test_workflow_skill_contracts.py \
      tests/test_agent_tools_launchers.py \
      tests/test_promotion_installed.py \
      tests/test_impeccable_installed.py \
      tests/test_claude_code_installed.py

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

# Apply .github/branch-protection.json to `main`, making its contexts (`Nix Eval`, `Instruction Budget`, `Agent Workflow Tests`) required checks.
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
