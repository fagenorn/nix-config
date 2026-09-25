{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
let
  agentPlugins = import ../../../lib/agent-plugins.nix { inherit inputs pkgs; };

  # Bare `codex-companion` on PATH. The codex-collaboration bridge (and its
  # `command -v` pre-flight) invokes it by name; without this every spawned
  # session gets exit 127 (observed: nodo evidence run, 2026-08-09). The
  # runtime is self-contained (node built-ins + relative lib imports only).
  #
  # The agent helpers ride down the same wrapper. `~/.agents/bin` reaches a
  # reviewer today only because home.sessionPath put it in the launching login
  # shell and the whole chain inherited it; a scrubbed or non-login parent
  # silently loses it and the reviewer's bare-name `artifact-budget` call gets
  # exit 127. Exporting here makes the guarantee a construction rather than an
  # inheritance. Unconditional on purpose: on a machine whose shell already
  # exported it the entry appears twice, which is inert.
  codexCompanionBin = pkgs.writeShellScriptBin "codex-companion" ''
    export PATH="$HOME/.agents/bin:$PATH"
    exec ${pkgs.nodejs}/bin/node ${agentPlugins.codex}/plugins/codex/scripts/codex-companion.mjs "$@"
  '';

  # The GitHub owners whose repositories carry standing authorization for the
  # guarded verbs (push, PR creation, merge). Membership is the whole of the
  # ownership test, so adding a name here hands every repository under it the
  # standing chain — keep the list to owners whose repos we actually ship from.
  # Branch deletion stays guarded regardless of ownership.
  authorizedOwners = [
    "fagenorn"
    "elevenyellow"
  ];

  # Repositories whose integration branch is not the branch origin/HEAD points
  # at. The guard otherwise requires every guarded PR to be opened against, and
  # merged into, the default branch; nodo integrates on `dev` and promotes to
  # `main` only at release, so both verbs have to accept that branch there. A
  # repository absent from this set keeps the default-branch-only rule, and the
  # default branch stays acceptable everywhere.
  #
  # Declaring a branch here widens which branch may be targeted AND waives the
  # merge's forge-protection demand for that branch: an integration branch is
  # the development-pace branch, deliberately unprotected, and its CI gate
  # lives in the shipping flow's wait-for-checks (nodo's CI is path-filtered,
  # so no required status check could report on every PR shape anyway). The
  # default branch keeps the full demand for feature merges — required status
  # checks plus enforce_admins — even if it is ever also declared here.
  #
  # Declaring a branch also opens the merge grammar's release arm: a PR whose
  # head IS the declared integration branch and whose base is the default
  # branch may be merged without `--delete-branch` (the integration branch is
  # permanent; deleting it would strand every in-flight worktree). That arm is
  # gated on the PR's own check rollup — every check completed and green — read
  # by the guard itself, in place of the forge-protection demand: the same
  # path-filtered CI means no required-status-check rule on the default branch
  # could stand in for the release PR's actual checks.
  integrationBases = {
    "elevenyellow/nodocom" = "dev";
    # arcwave is a private free-plan repository: GitHub refuses branch
    # protection there, so the default-branch merge demand can never be met.
    # Feature PRs integrate on `dev`; releases promote `dev` to `main`.
    "fagenorn/arcwave" = "dev";
  };

  # The Nix-owned values the lifecycle guard reads at run time, as one store
  # JSON file. The guard's source never embeds them, so an owner or base change
  # moves only this file, and the tool paths keep git, gh and jq in the closure.
  lifecycleGuardPolicy = pkgs.writeText "claude-bash-lifecycle-guard-policy.json" (
    builtins.toJSON {
      authorized_owners = authorizedOwners;
      integration_bases = integrationBases;
      git_bin = "${pkgs.git}/bin/git";
      gh_bin = "${pkgs.gh}/bin/gh";
      jq_bin = "${pkgs.jq}/bin/jq";
    }
  );

  # The registered hook: one argument-free store path. Bash's `-p` ignores
  # BASH_ENV and inherited functions, `-I` and the unset keep PYTHONPATH, user
  # site and NIX_PYTHON* `.pth` hooks out, and `exec` hands the hook's timeout
  # kill to Python. The check refuses a guard that cannot load its policy.
  lifecycleGuard = pkgs.writeTextFile {
    name = "claude-bash-lifecycle-guard";
    executable = true;
    destination = "/bin/claude-bash-lifecycle-guard";
    text = ''
      #!${pkgs.runtimeShell} -p
      unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE
      exec ${pkgs.python3}/bin/python3 -I ${./lifecycle_guard.py} --policy ${lifecycleGuardPolicy} "$@"
    '';
    checkPhase = ''
      if ! printf '%s' '{"tool_name":"Bash","tool_input":{"command":"true"}}' | "$target"; then
        echo "claude-bash-lifecycle-guard: refused a harmless Bash payload" >&2
        exit 1
      fi
    '';
  };

  # Durable, user-authored Claude Code settings (ported from the existing ~/.claude/settings.json).
  # Runtime-mutable noise — the accumulated project-specific permissions.allow list, OAuth,
  # project history, statsig caches — is intentionally NOT frozen here.
  settings = {
    "$schema" = "https://json.schemastore.org/claude-code-settings.json";

    # Disable auto-memory: Claude no longer reads from or writes to the per-project
    # ~/.claude/projects/<project>/memory/ MEMORY.md + topic files.
    autoMemoryEnabled = false;

    # Durable global preferences.
    alwaysThinkingEnabled = true;
    effortLevel = "xhigh";
    teammateMode = "auto";
    remoteControlAtStartup = true;
    agentPushNotifEnabled = true;
    skipAutoPermissionPrompt = true;
    skipDangerousModePermissionPrompt = true;
    skipWorkflowUsageWarning = true;

    env = {
      CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = "1";
    };

    hooks.PreToolUse = [
      {
        matcher = "Bash";
        hooks = [
          {
            type = "command";
            command = "${lifecycleGuard}/bin/claude-bash-lifecycle-guard";
            timeout = 30;
          }
        ];
      }
    ];

    # The broad push, PR-create, branch-delete and PR-merge entries are usable only
    # through the lifecycle guard above, which adjudicates every one of them at the
    # command position of a segment. Bare `Agent` remains inert while defaultMode is "auto".
    # The two lifecycle helpers are allowed whole, bare and by their ~/.agents/bin path:
    # their only writes are validated ledger transitions under .superpowers/workflows/, and
    # every lifecycle call is one heredoc-fed command, so each pipeline segment matches a rule.
    permissions = {
      defaultMode = "auto";
      allow = [
        "Bash(git fetch:*)"
        "Bash(git status:*)"
        "Bash(git log:*)"
        "Bash(git diff:*)"
        "Bash(gh pr view:*)"
        "Bash(gh pr list:*)"
        "Bash(gh pr checks:*)"
        "Bash(gh issue view:*)"
        "Bash(gh issue list:*)"
        "Bash(git worktree add:*)"
        "Bash(git worktree list:*)"
        "Bash(git worktree remove:*)"
        "Bash(git worktree prune:*)"
        "Bash(git push:*)"
        "Bash(gh pr create:*)"
        "Bash(git branch -d:*)"
        "Bash(gh pr merge:*)"
        "Bash(workflow-state:*)"
        "Bash(~/.agents/bin/workflow-state:*)"
        "Bash(artifact-budget:*)"
        "Bash(~/.agents/bin/artifact-budget:*)"
        "Agent"
      ];
      ask = [ ];
      deny = [ ];
    };

    # Plugins + their marketplaces, declared so the setup is portable to a fresh machine.
    # The patched plugin sources are Nix store paths; Claude's install/cache state under
    # ~/.claude/plugins stays mutable (never Nix-owned).
    enabledPlugins = {
      "skill-creator@claude-plugins-official" = true;
      "codex@nix-codex" = true;
    };
    extraKnownMarketplaces = {
      claude-plugins-official.source = {
        source = "github";
        repo = "anthropics/claude-plugins-official";
      };
      nix-codex.source = {
        source = "directory";
        path = "${agentPlugins.codex}";
      };
    };
  };

  settingsFile = (pkgs.formats.json { }).generate "claude-code-settings.json" settings;
in
{
  programs.claude-code = {
    enable = true;

    # Latest Claude Code from the community flake: official native binary, autoupdater
    # pre-disabled for the read-only store, served from its Cachix cache (no local compile).
    # Advances on `just update` (nix flake update) + the next rebuild.
    package = inputs.claude-code.packages.${pkgs.system}.default;

    # ~/.claude/CLAUDE.md — global user instructions (read-only store symlink is safe; static).
    memory.source = ../agent-guidance/AGENTS.md;

    # ~/.claude/skills/<name>/ — the global skills, recursively symlinked (multi-file skills
    # like prototype/ keep SKILL.md + UI.md + LOGIC.md). ~/.claude/skills stays a real dir.
    skillsDir = ../agent-skills/skills;

    # NOTE: MCP servers are intentionally NOT set here. The 25.11 module injects them via a
    # `--mcp-config` flag on a wrapper binary, but in Claude Code 2.1.183 that flag is variadic
    # (`--mcp-config <configs...>`), so the wrapper swallows any following args and breaks every
    # `claude` subcommand (`claude mcp list`, `claude doctor`, opening a dir, ...). Instead the
    # palmier-pro server is merged into ~/.claude.json (user scope) by the activation script
    # below, which shows up natively in `claude mcp list` and `/mcp` and leaves subcommands intact.

    # NOTE: `settings` is deliberately left unset. The module writes ~/.claude/settings.json
    # as a READ-ONLY store symlink, which breaks Claude Code's in-app /config flow and the
    # sandbox (both rewrite the file). It is materialised as a writable copy below instead.
  };

  # codex-plugin-cc is implemented in Node and shells out to the separately
  # managed native Codex CLI.
  home.packages = [
    pkgs.nodejs
    codexCompanionBin
  ];

  # Claude-only bridge orchestration. Keeping this outside the shared
  # ~/.agents/skills tree prevents Codex from recursively invoking itself.
  home.file.".claude/skills/codex-collaboration" = {
    source = ./skills/codex-collaboration;
    recursive = true;
  };

  # Claude-only dispatcher: fans issues out to independent background
  # `/from-issue --auto` agents (background agents + task notifications are
  # Claude-harness features Codex lacks).
  home.file.".claude/skills/orchestrate-issues" = {
    source = ./skills/orchestrate-issues;
    recursive = true;
  };

  # ~/.claude/agents/<name>.md — tiered pipeline agent definitions. Global
  # effortLevel stays xhigh for interactive/orchestrator sessions; pipeline
  # subagents dispatch explicitly as implementer/reviewer (opus/high) or
  # mechanic/reviewer-lite (sonnet/medium). Skills reference them by name.
  home.file.".claude/agents" = {
    source = ./agents;
    recursive = true;
  };

  # Repair Claude's mutable plugin-install record when it drifts from the
  # Nix-declared marketplace. After a rebuild the recorded codex installPath
  # can dangle (old store path GC'd, cache copy wiped) or point at a stale
  # patch revision — spawned sessions then resolve stale or broken agent
  # definitions (observed: p1 record while the marketplace served p2, exit-127
  # bridge behavior in the nodo evidence run). Idempotent: rewrites only when
  # installPath differs from the current store plugin.
  home.activation.repairCodexPluginInstall = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    installed="$HOME/.claude/plugins/installed_plugins.json"
    target="${agentPlugins.codex}/plugins/codex"
    if [ -f "$installed" ]; then
      current=$(${pkgs.jq}/bin/jq -r '.plugins["codex@nix-codex"][0].installPath // empty' "$installed")
      if [ -n "$current" ] && [ "$current" != "$target" ]; then
        tmp=$(mktemp)
        ${pkgs.jq}/bin/jq --arg p "$target" --arg v "${agentPlugins.codexMetadata.version}" \
          '.plugins["codex@nix-codex"] |= map(.installPath = $p | .version = $v)' \
          "$installed" > "$tmp"
        run mv "$tmp" "$installed"
      fi
    fi
  '';

  # Copy settings.json to a writable location on each activation. Nix is the source of truth
  # (re-asserted every `sudo just`), but Claude Code can still rewrite it at runtime — your
  # live edits persist until the next switch, which resets it to the declared content.
  home.activation.claudeCodeSettings = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    run mkdir -p "$HOME/.claude"
    run cp -f ${settingsFile} "$HOME/.claude/settings.json"
    run chmod u+w "$HOME/.claude/settings.json"
  '';

  # Declaratively register the palmier-pro MCP server at user scope by merging it into
  # ~/.claude.json (the file Claude Code reads natively). Idempotent: only rewrites when the
  # entry is missing/changed, minimising any race with a running Claude Code. We do NOT own the
  # whole file (it holds OAuth + runtime state) — just this one key.
  home.activation.palmierProMcp = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    cfg="$HOME/.claude.json"
    jq=${pkgs.jq}/bin/jq
    want='{"type":"http","url":"http://127.0.0.1:19789/mcp"}'
    wantC=$(printf '%s' "$want" | "$jq" -cS .)
    if [ -f "$cfg" ] && "$jq" -e . "$cfg" >/dev/null 2>&1; then
      haveC=$("$jq" -cS '.mcpServers["palmier-pro"] // null' "$cfg")
      src=$(cat "$cfg")
    else
      haveC=null
      src='{}'
    fi
    # Only rewrite when the entry is actually missing/different (idempotent → avoids churn
    # and minimises any race with a concurrently-running Claude Code rewriting the file).
    if [ "$haveC" != "$wantC" ]; then
      tmp="$cfg.hm-tmp.$$"
      printf '%s' "$src" | "$jq" --argjson v "$want" '.mcpServers["palmier-pro"] = $v' > "$tmp"
      chmod 600 "$tmp"
      mv -f "$tmp" "$cfg"
    fi
  '';
}
