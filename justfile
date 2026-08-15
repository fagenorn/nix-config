# Build the system config and switch to it when running `just` with no args
default: switch

hostname := `hostname | cut -d "." -f 1`

### macos
# Build the nix-darwin system configuration without switching to it
[macos]
build target_host=hostname flags="":
  @echo "Building nix-darwin config..."
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
  @echo "Building NixOS config for {{target_host}}..."
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

# Verify durable workflow lifecycle and skill contracts without agent/network timing.
agent-workflow-tests:
  python3 -m unittest -v \
    home/common/agent-skills/tests/test_workflow_state.py \
    home/common/agent-skills/tests/test_workflow_skill_contracts.py \
    home/common/agent-skills/tests/test_ship_release_contracts.py \
    tests/test_agent_costs.py

# Validate every explicit pipeline dispatch and print the four-family demo trace.
agent-model-matrix:
  python3 home/common/agent-skills/scripts/agent-model-matrix.py validate
  python3 home/common/agent-skills/scripts/agent-model-matrix.py trace representative

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


# Report agent token spend per issue from the local Claude Code transcripts
agent-costs *args:
  python3 scripts/agent-costs.py {{args}}

# Garbage collect old OS generations and remove stale packages from the nix store
gc generations="5":
  nix-env --delete-generations {{generations}}
  nix-store --gc
