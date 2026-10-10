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

# Verify durable workflow lifecycle and skill contracts without agent/network timing.
agent-workflow-tests:
  PYTHONPATH="{{agent_tools_path}}" python3 -m unittest -v \
    home/common/agent-skills/tests/test_workflow_state.py \
    home/common/agent-skills/tests/test_host_admission.py \
    home/common/agent-skills/tests/test_admission_replay.py \
    home/common/agent-skills/tests/test_delivery_model.py \
    home/common/agent-skills/tests/test_delivery_workflow.py \
    home/common/agent-skills/tests/test_delivered_control.py \
    home/common/agent-skills/tests/test_workflow_delivery.py \
    home/common/agent-skills/tests/test_task_brief.py \
    home/common/agent-skills/tests/test_sdd_workspace.py \
    home/common/agent-skills/tests/test_review_package.py \
    tests/test_review_pack.py \
    tests/test_review_feasibility.py \
    tests/test_review_projection_cases.py \
    tests/test_review_history.py \
    tests/test_review_task7.py \
    tests/test_review_issue121.py \
    tests/test_review_compact121.py \
    tests/test_review_issue100.py \
    tests/test_review_compact100.py \
    tests/test_review_witness.py \
    tests/test_review_derivation.py \
    tests/test_review_replay.py \
    tests/test_review_evidence.py \
    home/common/agent-skills/tests/test_workflow_skill_contracts.py \
    home/common/agent-skills/tests/test_dispatch_contracts.py \
    home/common/agent-skills/tests/test_shell_example_contracts.py \
    home/common/agent-skills/tests/test_ship_release_contracts.py \
    home/common/agent-skills/tests/test_eval_cases.py \
    home/common/agent-skills/tests/test_agent_evidence.py \
    home/common/agent-skills/tests/test_agent_model_matrix.py \
    home/common/agent-skills/tests/test_instruction_load.py \
    home/common/agent-skills/tests/test_skill_lint.py \
    home/common/agent-skills/tests/test_diff_scope.py \
    home/common/agent-skills/tests/test_resolve_project.py \
    home/common/agent-skills/tests/test_resolve_platform.py \
    home/common/agent-skills/tests/test_resolve_platform_status.py \
    home/common/agent-skills/tests/test_conformance.py \
    home/common/agent-skills/tests/test_conformance_checks.py \
    home/common/agent-skills/tests/test_conformance_registry.py \
    home/common/agent-skills/tests/test_adopt_project.py \
    home/common/agent-skills/tests/test_adopt_project_boundaries.py \
    home/common/agent-skills/tests/test_adopt_apply.py \
    home/common/agent-skills/tests/test_adopt_verify.py \
    home/common/agent-skills/tests/test_artifact_budget.py \
    tests/test_agent_tools_canonical.py \
    tests/test_agent_tools_siblings.py \
    tests/test_lane_triage.py \
    tests/test_launch_commit.py \
    tests/test_launch_scope.py \
    tests/test_review_range.py \
    tests/test_verified_tree.py \
    tests/test_transaction_core.py \
    tests/test_attempt_identity.py \
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
    tests/test_agent_costs.py \
    tests/test_agent_model_drift_schema.py \
    tests/test_agent_model_drift_routing.py \
    tests/test_agent_model_drift_scheduling.py \
    tests/test_agent_model_drift_producer_integration.py \
    tests/test_agent_gate_bundle.py \
    tests/test_promotion_documents.py \
    tests/test_promotion_lifecycle.py \
    tests/test_promotion_deployment.py \
    tests/test_promotion_demo.py \
    tests/test_context_map_lint.py \
    tests/test_branch_protection.py
  bash home/common/agent-skills/evals/tests/test-run-eval-tree.sh

# Validate every explicit pipeline dispatch and print the four-family demo trace.
agent-model-matrix:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_model_matrix validate
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_model_matrix trace representative

# Compare the instruction documents each agent profile loads at two revisions (#155 D9).
agent-instruction-load *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.instruction_load {{args}}

# Run the Instruction Budget gate against origin/main; pass --raise-label for a labelled raise (#292 D9).
agent-instruction-budget *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.instruction_load check --base origin/main {{args}}

# Check the skill contracts and agent-tool launchers against what the Nix build installs.
agent-installed-skill-tests: build
  @set -- $(nix-store --query --requisites ./result \
    | grep -- '-home-manager-files$' || true); \
    if [ "$#" -ne 1 ]; then \
      echo "expected exactly one built home-manager-files output; found $#" >&2; \
      exit 1; \
    fi; \
    AGENT_SKILLS_INSTALLED_HOME="$1" python3 -m unittest -v \
      home/common/agent-skills/tests/test_dispatch_contracts.py \
      home/common/agent-skills/tests/test_shell_example_contracts.py \
      home/common/agent-skills/tests/test_workflow_skill_contracts.py \
      tests/test_agent_tools_launchers.py \
      tests/test_promotion_installed.py \
      tests/test_impeccable_installed.py

# Full-shape retained tier (#249): the real retained objects and archive under `root`. Not part of agent-workflow-tests.
agent-retained-tests root: build
  @set -- $(nix-store --query --requisites ./result \
    | grep -- '-home-manager-files$' || true); \
    if [ "$#" -ne 1 ]; then \
      echo "expected exactly one built home-manager-files output; found $#" >&2; \
      exit 1; \
    fi; \
    log=$(mktemp "${TMPDIR:-/tmp}/agent-retained-XXXXXX") || exit 1; \
    trap 'rm -f -- "$log"' EXIT; \
    status=0; \
    AGENT_RETAINED_ROOT="{{root}}" AGENT_SKILLS_INSTALLED_HOME="$1" PYTHONPATH="{{agent_tools_path}}" \
      python3 -m unittest -v tests/test_review_retained_full.py tests/test_agent_tools_launchers.py \
      >"$log" 2>&1 || status=$?; \
    cat "$log"; \
    if [ "$status" -ne 0 ]; then exit "$status"; fi; \
    if grep -Eq '\.\.\. skipped|^OK \(.*skipped=' "$log"; then \
      echo "agent-retained-tests: a skipped test is not acceptance" >&2; \
      exit 1; \
    fi

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

# Apply .github/branch-protection.json to `main`, making `Nix Eval` and `Instruction Budget` required checks.
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


# Report agent token spend per issue from the local Claude Code and Codex sessions
agent-costs *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_costs {{args}}

agent-model-drift *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_model_drift {{args}}

# Apply issue #70's token-and-quality gate to a trials manifest of emitted cost records
agent-gate-bundle *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.agent_gate_bundle {{args}}

# Capture, evaluate, validate and advance promotion candidates (#127)
[positional-arguments]
promotion *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.promotion "$@"

# Garbage collect old OS generations and remove stale packages from the nix store
gc generations="5":
  nix-env --delete-generations {{generations}}
  nix-store --gc
