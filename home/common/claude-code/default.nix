{
  config,
  lib,
  pkgs,
  inputs,
  agentTools,
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

  # Latest Claude Code from the community flake: official native binary, autoupdater
  # pre-disabled for the read-only store, served from its Cachix cache (no local compile).
  # Advances on `just update` (nix flake update) + the next rebuild.
  claudeUnwrapped = inputs.claude-code.packages.${pkgs.system}.default;

  # The cache proxy (agent_tools.cache_proxy, #422). This port is its one home:
  # the service below listens on it and the launcher's CACHE_PROXY_URL is
  # rewritten to it, so `claude` routes through the proxy while it is healthy
  # unless launched with CLAUDE_CACHE_PROXY=0 (on by default since #450).
  # `--keepalive` (#423) turns on the keepalive pings; dropping it and rebuilding turns them off.
  # `--reorder` (#429) reorders each subagent's first user message so siblings share a cached start-up prefix; dropping it and rebuilding turns that off.
  cacheProxyPort = 27183;
  cacheProxyUrl = "http://127.0.0.1:${toString cacheProxyPort}";
  cacheProxyArgs = [
    "${agentTools.launchers.cache-proxy}"
    "--port"
    (toString cacheProxyPort)
    "--keepalive"
    "--reorder"
  ];
  # launchd and systemd start services with a minimal environment, so upstream
  # TLS verification is pinned to the nixpkgs CA bundle.
  cacheProxyCaFile = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";

  # The `accounts` mod (./accounts): one config directory per Claude account,
  # bound per project. Mod and launcher are one store path because the mod runs
  # `$.plugin.root/bin/claude-account` and the launcher names its own folder in
  # CLAUDE_CODE_PLUGIN_DIRS. The launcher's tools are rewritten to store paths
  # rather than prefixed onto PATH, which the claude it execs would inherit, and its
  # CACHE_PROXY_URL to the cache proxy's URL.
  accountsMod =
    pkgs.runCommand "claude-accounts-mod"
      {
        buildInputs = [ pkgs.bash ];
      }
      ''
        cp -R ${./accounts} "$out"
        chmod -R u+w "$out"
        substituteInPlace "$out/bin/claude-account" \
          --replace-fail 'JQ=jq' 'JQ=${pkgs.jq}/bin/jq' \
          --replace-fail 'GIT=git' 'GIT=${pkgs.git}/bin/git' \
          --replace-fail 'CURL=curl' 'CURL=${pkgs.curl}/bin/curl' \
          --replace-fail 'DEFAULT_CLAUDE_BIN=' 'DEFAULT_CLAUDE_BIN=${claudeUnwrapped}/bin/claude' \
          --replace-fail 'CACHE_PROXY_URL=' 'CACHE_PROXY_URL=${cacheProxyUrl}'
        patchShebangs "$out/bin"
        HOME="$(mktemp -d)" "$out/bin/claude-account" status
      '';

  # `claude` on PATH starts under the account the current project is bound to,
  # for interactive and non-interactive callers alike. Both entries are scripts,
  # not links, because the launcher finds the mod relative to its own real location.
  claudeWithAccounts = pkgs.symlinkJoin {
    name = "claude-code-with-accounts-${claudeUnwrapped.version}";
    paths = [ claudeUnwrapped ];
    postBuild = ''
      rm "$out/bin/claude"
      printf '%s\n' '#!${pkgs.runtimeShell}' 'exec ${accountsMod}/bin/claude-account run "$@"' > "$out/bin/claude"
      printf '%s\n' '#!${pkgs.runtimeShell}' 'exec ${accountsMod}/bin/claude-account "$@"' > "$out/bin/claude-account"
      chmod +x "$out/bin/claude" "$out/bin/claude-account"
    '';
    inherit (claudeUnwrapped) meta version;
  };

  # The GitHub owners whose repositories carry standing authorization for the
  # guarded verbs (push, PR creation, merge, release creation) without being
  # registered projects. A registered project is not listed here: its
  # repository gets a derived row in the compiled policy, which authorizes that
  # one repository. Adding a name here hands every repository under it the
  # standing chain, so keep the list to owners whose unregistered repos we
  # ship from. Branch deletion stays guarded regardless of ownership.
  authorizedOwners = [
    "fagenorn"
  ];

  # Unregistered repositories whose integration branch is not the branch
  # origin/HEAD points at. The guard otherwise requires every guarded PR to be
  # opened against, and merged into, the default branch. A registered project
  # never gets a row here: its integration branch comes from its derived row,
  # and a repository present in both is refused: the compiler denies that project
  # its derived row (`literal_conflict`), the literal row stays in the base
  # policy, and the guard refuses the guarded verbs of a repository that has both
  # a literal row and a compiled row. A repository with neither keeps the
  # default-branch-only rule, and the default branch stays acceptable
  # everywhere. The set is empty: every repository that has an integration
  # branch is a registered project with a derived row. Add a row only for one
  # that is not.
  #
  # Declaring a branch here widens which branch may be targeted AND waives the
  # merge's forge-protection demand for that branch: an integration branch is
  # the development-pace branch, deliberately unprotected, and its CI gate
  # lives in the shipping flow's wait-for-checks (a path-filtered CI has no
  # required status check that could report on every PR shape anyway). The
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
  integrationBases = { };

  # The base policy: the five trusted members, the literal rows above and the
  # tool paths, as one store JSON file. It is the only place the guard reads
  # those members from, and no one copies it: `guard-policy compile` only
  # validates it and checks derived slugs against its literal rows. The wrapper's
  # build check and the guard suite load it. The tool paths keep git, gh and jq
  # in the closure.
  lifecycleGuardBasePolicy = pkgs.writeText "claude-bash-lifecycle-guard-base-policy.json" (
    builtins.toJSON {
      authorized_owners = authorizedOwners;
      integration_bases = integrationBases;
      git_bin = "${pkgs.git}/bin/git";
      gh_bin = "${pkgs.gh}/bin/gh";
      jq_bin = "${pkgs.jq}/bin/jq";
    }
  );

  # The compiled policy the registered hook reads: derived rows only, one per
  # registered project, written by `claude-guard-policy`.
  lifecycleGuardPolicyPath = "${config.home.homeDirectory}/.agents/state/guard/policy.json";

  # The store git, gh and ssh bin directories, as one PATH string shared by
  # `claude-guard-policy` and the row check below.
  guardToolPath = lib.makeBinPath [
    pkgs.git
    pkgs.gh
    pkgs.openssh
  ];

  # `guard-policy compile` with the base policy and the compiled path fixed, and
  # the store git, gh and ssh first on PATH. The activation step below and a
  # repair from an authenticated shell both run it with no argument; any argument
  # is handed to `compile`, so `--help` prints usage and writes nothing (#470).
  claudeGuardPolicy = pkgs.writeShellScriptBin "claude-guard-policy" ''
    export PATH="${guardToolPath}:$PATH"
    exec ${agentTools.launchers.guard-policy} compile \
      --base ${lifecycleGuardBasePolicy} --output ${lifecycleGuardPolicyPath} "$@"
  '';

  # The row check the guard runs before relying on a compiled row: `guard-policy
  # derive`, which re-derives one repository's row from the fleet registry. It
  # pins the store git, gh and ssh first on PATH as `claude-guard-policy` does.
  # The hook wrapper names it by store path, and it is not installed on PATH.
  # Bash's `-p` ignores BASH_ENV and inherited functions here, and the `unset`
  # keeps BASH_ENV and ENV from the launcher it execs, which runs under `-p` too;
  # the guard also drops them and every exported function from its environment.
  lifecycleGuardRowCheck = pkgs.writeTextFile {
    name = "claude-guard-row-check";
    executable = true;
    text = ''
      #!${pkgs.runtimeShell} -p
      unset BASH_ENV ENV
      export PATH="${guardToolPath}:$PATH"
      exec ${agentTools.launchers.guard-policy} derive "$@"
    '';
    checkPhase = ''
      ${pkgs.stdenv.shellDryRun} "$target"
    '';
  };

  # The registered hook: one argument-free store path. Bash's `-p` ignores
  # BASH_ENV and inherited functions, `-I` and the unset keep PYTHONPATH, user
  # site and NIX_PYTHON* `.pth` hooks out, and `exec` hands the hook's timeout
  # kill to Python. `--base-policy` names the store base policy and `--policy`
  # the compiled policy, whose path is fixed at evaluation time, and
  # `--derive-bin` the row check. The check runs the wrapper on a payload with no
  # repository-bound verb: the guard loads the base policy, so the build refuses
  # a guard source or a base policy that cannot load, and never opens the
  # compiled path or runs the row check.
  lifecycleGuard = pkgs.writeTextFile {
    name = "claude-bash-lifecycle-guard";
    executable = true;
    destination = "/bin/claude-bash-lifecycle-guard";
    text = ''
      #!${pkgs.runtimeShell} -p
      unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE
      exec ${pkgs.python3}/bin/python3 -I ${./lifecycle_guard.py} --base-policy ${lifecycleGuardBasePolicy} --policy ${lifecycleGuardPolicyPath} --derive-bin ${lifecycleGuardRowCheck} "$@"
    '';
    checkPhase = ''
      if ! printf '%s' '{"tool_name":"Bash","tool_input":{"command":"true"}}' \
        | "$target"; then
        echo "claude-bash-lifecycle-guard: refused a harmless Bash payload" >&2
        exit 1
      fi
    '';
  };

  # The managed global git hooks (issue 672). `core.hooksPath` replaces every
  # per-repository hook directory, so the directory holds the authoritative
  # `pre-push` guard wrapper and, for every other hook git runs, a shim that
  # chains to the repository's own hook and serves git-lfs. `agentGitHookNames`
  # leaves out `push-to-checkout`, `fsmonitor-watchman`, `reference-transaction`
  # and `post-index-change` (README § Pre-push hook, D5). The `pre-push` text is
  # the lifecycleGuard exec line plus `--mode pre-push`, the LFS binary and the
  # hook's own arguments, so both read the same interpreter, source and policy.
  agentGitHookNames = [
    "applypatch-msg"
    "pre-applypatch"
    "post-applypatch"
    "pre-commit"
    "pre-merge-commit"
    "prepare-commit-msg"
    "commit-msg"
    "post-commit"
    "pre-rebase"
    "post-checkout"
    "post-merge"
    "pre-receive"
    "update"
    "proc-receive"
    "post-receive"
    "post-update"
    "pre-auto-gc"
    "post-rewrite"
    "sendemail-validate"
    "p4-changelist"
    "p4-prepare-changelist"
    "p4-post-changelist"
    "p4-pre-submit"
  ];
  gitLfsBin = lib.optionalString config.programs.git.lfs.enable "${config.programs.git.lfs.package}/bin/git-lfs";
  agentGitHooks = pkgs.runCommand "agent-git-hooks" { nativeBuildInputs = [ pkgs.git ]; } ''
    mkdir -p $out
    cat > $out/pre-push <<'EOF'
    #!${pkgs.runtimeShell} -p
    unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE
    exec ${pkgs.python3}/bin/python3 -I ${./lifecycle_guard.py} --base-policy ${lifecycleGuardBasePolicy} --policy ${lifecycleGuardPolicyPath} --derive-bin ${lifecycleGuardRowCheck} --mode pre-push${lib.optionalString (gitLfsBin != "") " --git-lfs-bin ${gitLfsBin}"} -- "$@"
    EOF
    chmod 0555 $out/pre-push
    for name in ${lib.concatStringsSep " " agentGitHookNames}; do
      substitute ${./git-hooks/chain-hook} $out/$name \
        --subst-var-by git ${pkgs.git}/bin/git \
        --subst-var-by gitlfs '${gitLfsBin}'
      chmod 0555 $out/$name
      ${pkgs.stdenv.shellDryRun} $out/$name
    done
    for name in pre-push ${lib.concatStringsSep " " agentGitHookNames}; do
      test -x $out/$name || { echo "agent-git-hooks: missing hook $name" >&2; exit 1; }
    done
    export HOME=$TMPDIR GIT_CONFIG_NOSYSTEM=1
    git init -q $TMPDIR/scratch
    cd $TMPDIR/scratch
    if ! env -u CLAUDECODE $out/pre-push origin git@github.com:x/y.git < /dev/null; then
      echo "agent-git-hooks: pre-push refused an empty push outside an agent session" >&2
      exit 1
    fi
  '';

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

    # No Co-Authored-By trailer, PR line or session link in any project (#619).
    attribution = {
      commit = "";
      pr = "";
      sessionUrl = false;
    };

    env = {
      CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = "1";
      # Ceiling for an explicit Bash timeout (60 min), so a long verification
      # command can run in the foreground; the 120 s default is unchanged (#261).
      BASH_MAX_TIMEOUT_MS = "3600000";
    };

    # Owner-action status line (issue 624): prints `owner N (oldest Xd)` for the current
    # project's repo only, from the cache, with no network call, and starts a detached
    # refresh when that repo's entry is older than 15 minutes.
    statusLine = {
      type = "command";
      command = "${agentTools.launchers.owner-actions} statusline";
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
          # The context meter (issue 424): rewrites each `workflow-state progress` call to
          # carry this agent's measured context and, once per crossing of the hand-off
          # threshold, tells an owner to run its phase gate. It never grants or denies,
          # so the guard above still judges every call.
          {
            type = "command";
            command = "${agentTools.launchers.context-meter}";
            timeout = 10;
          }
        ];
      }
    ];

    # The broad push, PR-create, branch-delete and PR-merge entries are usable only
    # through the lifecycle guard above, which adjudicates every one of them at the
    # command position of a segment. Bare `Agent` remains inert while defaultMode is "auto".
    # The lifecycle helpers workflow-state, artifact-budget and ship-delivery
    # are allowed whole, bare and by their ~/.agents/bin path: their only writes are validated
    # ledger transitions under .superpowers/workflows/, and every lifecycle call is one
    # heredoc-fed command, so each pipeline segment matches a rule. The verification-observe adapter is allowed the same way:
    # its only write is fetching the integration branch into refs/remotes/origin/<branch>.
    # forge-issue is allowed the same way (issue 697): its only writes are one issue and its
    # dependency links, each linked by database id and read back.
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
        "Bash(ship-delivery:*)"
        "Bash(~/.agents/bin/ship-delivery:*)"
        "Bash(verification-observe:*)"
        "Bash(~/.agents/bin/verification-observe:*)"
        "Bash(forge-issue:*)"
        "Bash(~/.agents/bin/forge-issue:*)"
        "Agent"
      ];
      ask = [ ];
      # Issue 735: the claude.ai Claude Docs connector is never used. A server-wide deny
      # removes all its tools and keeps the other claude.ai connectors
      # (disableClaudeAiConnectors would drop them all).
      deny = [ "mcp__claude_ai_Claude_Docs" ];
    };

    # Hidden from the model's skill listing, each still runnable as /<name> (issue 425):
    # skills synced from claude.ai by their full `anthropic-skills:` name, which Claude
    # Code matches before the bare one, bundled skills by their bare name. A plugin's
    # skills ignore this map, so the skill-creator kept listed is the plugin's (below).
    skillOverrides = (lib.genAttrs [
      "artifact-design"
      "artifact-diagramming"
      "artifact-capabilities"
      "dataviz"
      "anthropic-skills:docx"
      "anthropic-skills:pptx"
      "anthropic-skills:xlsx"
      "anthropic-skills:pdf"
      "anthropic-skills:google-workspace"
      "anthropic-skills:morning"
      "anthropic-skills:import-memory"
      "anthropic-skills:skill-creator"
    ] (_: "user-invocable-only"))
    // (
      # Issue 735: synced skills never used here, off for the model and for /<name>.
      lib.genAttrs [
        "anthropic-skills:docs"
        "anthropic-skills:chrome-browser"
        "anthropic-skills:built-in-browser"
        "anthropic-skills:computer-use"
        "anthropic-skills:deep-research"
      ] (_: "off")
    );

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
  # The managed global git hooks, on every host (issue 672 O4); README § Pre-push hook.
  programs.git.settings.core.hooksPath = "${agentGitHooks}";

  programs.claude-code = {
    enable = true;

    # The pinned binary behind the account-aware launcher (see claudeWithAccounts).
    package = claudeWithAccounts;

    # ~/.claude/CLAUDE.md — global user instructions (read-only store symlink is safe; static).
    memory.source = ../agent-guidance/AGENTS.md;

    # ~/.claude/skills/<name>/ — the global skills, recursively symlinked (multi-file skills
    # like prototype/ keep SKILL.md + UI.md + LOGIC.md). ~/.claude/skills stays a real dir.
    skillsDir = ../agent-skills/skills;

    # NOTE: MCP servers are intentionally NOT set here. The 25.11 module injects them via a
    # `--mcp-config` flag on a wrapper binary, but in Claude Code 2.1.183 that flag is variadic
    # (`--mcp-config <configs...>`), so the wrapper swallows any following args and breaks every
    # `claude` subcommand (`claude mcp list`, `claude doctor`, opening a dir, ...). Instead a
    # server is merged into ~/.claude.json (user scope) by an idempotent jq activation script,
    # which shows up natively in `claude mcp list` and `/mcp` and leaves subcommands intact.

    # NOTE: `settings` is deliberately left unset. The module writes ~/.claude/settings.json
    # as a READ-ONLY store symlink, which breaks Claude Code's in-app /config flow and the
    # sandbox (both rewrite the file). It is materialised as a writable copy below instead.
  };

  # codex-plugin-cc is implemented in Node and shells out to the separately
  # managed native Codex CLI. The lifecycle guard is also on PATH so the forge
  # adapter and the project resolver find `claude-bash-lifecycle-guard` by name;
  # the registered hook keeps its own store path.
  home.packages = [
    pkgs.nodejs
    codexCompanionBin
    lifecycleGuard
    claudeGuardPolicy
  ];

  # The cache proxy as a user service on each platform (#422); README § Cache proxy.
  launchd.agents.claude-cache-proxy = lib.mkIf pkgs.stdenv.isDarwin {
    enable = true;
    config = {
      ProgramArguments = cacheProxyArgs;
      EnvironmentVariables.SSL_CERT_FILE = cacheProxyCaFile;
      RunAtLoad = true;
      KeepAlive = true;
      StandardOutPath = "${config.home.homeDirectory}/Library/Logs/claude-cache-proxy.log";
      StandardErrorPath = "${config.home.homeDirectory}/Library/Logs/claude-cache-proxy.log";
    };
  };

  systemd.user.services.claude-cache-proxy = lib.mkIf pkgs.stdenv.isLinux {
    Unit.Description = "Claude Code cache proxy (Anthropic API, with keepalive pings and the subagent prefix reorder)";
    Service = {
      ExecStart = lib.concatStringsSep " " cacheProxyArgs;
      Environment = [ "SSL_CERT_FILE=${cacheProxyCaFile}" ];
      Restart = "always";
    };
    Install.WantedBy = [ "default.target" ];
  };

  # Claude-only bridge orchestration: Codex is the reviewer this skill drives,
  # so it is linked only into ~/.claude/skills.
  home.file.".claude/skills/codex-collaboration" = {
    source = ./skills/codex-collaboration;
    recursive = true;
  };

  # Claude-only standard lane: its SKILL.md starts deliver-standard.js with the
  # Workflow tool, a Claude Code feature Codex lacks.
  home.file.".claude/skills/deliver-standard" = {
    source = ./skills/deliver-standard;
    recursive = true;
  };

  # Claude-only batch lane: its SKILL.md starts deliver-batch.js (in the
  # deliver-standard directory) with the Workflow tool, a Claude Code feature
  # Codex lacks.
  home.file.".claude/skills/deliver-batch" = {
    source = ./skills/deliver-batch;
    recursive = true;
  };

  # ~/.claude/agents/<name>.md — tiered pipeline agent definitions. Global
  # effortLevel stays xhigh for interactive/orchestrator sessions; pipeline
  # subagents dispatch explicitly as implementer (opus/high), reviewer
  # (opus/high) or reviewer-lite (sonnet/medium). The Workflow programs' steps
  # run as clerk (sonnet/low; Bash, Read and Skill only, for judgment-free
  # steps) and planner (opus/high; the plan step). Skills reference them by
  # name; home/common/agent-skills/model-matrix.json owns every tier.
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

  # Compile the guard policy the registered hook reads, on every switch. It runs
  # after linkGeneration because the compiler loads the platform manifest from
  # ~/.agents/share, and before the settings copy. It never aborts the switch:
  # exit 1 leaves a policy without the refused projects' rows (or, when every
  # project was refused, keeps the previous populated policy), and any other
  # failure removes the policy file, so registered projects lose their derived
  # guard row and with it their derived integration branch: only a repository
  # that relies on a derived row for its authorization is refused until
  # `claude-guard-policy` succeeds, while authorization from the base policy (an
  # authorized owner or a literal integration row) still applies. The removal is
  # an `if` condition because the activation script runs under `set -e`. When it
  # fails the step says so instead, and the hook reads whatever is at the path:
  # a directory or an unreadable or malformed file contributes no row, and a
  # readable earlier policy stays in force.
  home.activation.claudeGuardPolicy =
    lib.hm.dag.entryBetween [ "claudeCodeSettings" ] [ "writeBoundary" "linkGeneration" ]
      ''
        guardPolicyStatus=0
        run ${claudeGuardPolicy}/bin/claude-guard-policy >/dev/null || guardPolicyStatus=$?
        if [ "$guardPolicyStatus" -eq 1 ]; then
          echo "claude-guard-policy: the projects named above have no derived guard row; rerun claude-guard-policy from an authenticated shell" >&2
        elif [ "$guardPolicyStatus" -ne 0 ]; then
          if run rm -f ${lifecycleGuardPolicyPath}; then
            echo "claude-guard-policy: no guard policy was written (exit $guardPolicyStatus), so registered projects lose their derived guard row and with it their derived integration branch, and the lifecycle guard refuses a repository that relies on one until it succeeds, while authorization from the base policy (an authorized owner or a literal integration row) still applies; rerun claude-guard-policy from an authenticated shell" >&2
          else
            echo "claude-guard-policy: no guard policy was written (exit $guardPolicyStatus) and ${lifecycleGuardPolicyPath} could not be removed, so the lifecycle guard reads whatever rows are there; remove it, then rerun claude-guard-policy from an authenticated shell" >&2
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

  # palmier-pro is no longer installed anywhere: drop the user-scope MCP entry an earlier
  # generation merged into ~/.claude.json. Touches only that key; a no-op once it is gone.
  home.activation.palmierProMcpRemove = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    cfg="$HOME/.claude.json"
    jq=${pkgs.jq}/bin/jq
    if [ -f "$cfg" ] && "$jq" -e '.mcpServers["palmier-pro"]' "$cfg" >/dev/null 2>&1; then
      tmp="$cfg.hm-tmp.$$"
      "$jq" 'del(.mcpServers["palmier-pro"])' "$cfg" > "$tmp"
      chmod 600 "$tmp"
      mv -f "$tmp" "$cfg"
    fi
  '';
}
