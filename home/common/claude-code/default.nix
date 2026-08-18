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
  codexCompanionBin = pkgs.writeShellScriptBin "codex-companion" ''
    exec ${pkgs.nodejs}/bin/node ${agentPlugins.codex}/plugins/codex/scripts/codex-companion.mjs "$@"
  '';

  lifecycleGuard = pkgs.writeTextFile {
    name = "claude-bash-lifecycle-guard";
    executable = true;
    destination = "/bin/claude-bash-lifecycle-guard";
    text = ''
      #!${pkgs.python3}/bin/python3
      import argparse
      import json
      import shlex
      import subprocess
      import sys


      DEFAULT_GIT_BIN = "${pkgs.git}/bin/git"
      DEFAULT_GH_BIN = "${pkgs.gh}/bin/gh"
      DEFAULT_JQ_BIN = "${pkgs.jq}/bin/jq"
      REPOSITORY = "fagenorn/nix-config"
      PR_URL_PREFIX = "https://github.com/fagenorn/nix-config/pull/"
      BRANCH_LITERAL = "git branch -d"
      MERGE_LITERAL = "gh pr merge"
      UNSAFE_BRANCH_CHARS = set(";&|<>$`\\\n\r*?[]{}()#~")


      def block(reason):
          print(f"lifecycle guard: {reason}", file=sys.stderr)
          return 2


      def parse_merge_raw(command):
          prefix = "gh pr merge "
          if not command.startswith(prefix):
              return None

          number, separator, remainder = command[len(prefix):].partition(" ")
          if (
              not separator
              or not number
              or any(character < "0" or character > "9" for character in number)
              or int(number) <= 0
          ):
              return None

          no_subject = "--repo fagenorn/nix-config --merge --delete-branch"
          if remainder == no_subject:
              return number, None

          subject_prefix = '--repo fagenorn/nix-config --merge --subject "'
          subject_suffix = '" --delete-branch'
          if not remainder.startswith(subject_prefix) or not remainder.endswith(subject_suffix):
              return None

          subject = remainder[len(subject_prefix):-len(subject_suffix)]
          forbidden = {'"', "$", "`", "\\", "\0", "\n", "\r"}
          if (
              not subject
              or any(character in forbidden for character in subject)
              or any(0xD800 <= ord(character) <= 0xDFFF for character in subject)
          ):
              return None
          return number, subject


      def main():
          parser = argparse.ArgumentParser()
          parser.add_argument("--git-bin", default=DEFAULT_GIT_BIN)
          parser.add_argument("--gh-bin", default=DEFAULT_GH_BIN)
          parser.add_argument("--jq-bin", default=DEFAULT_JQ_BIN)
          parser.add_argument("--child-timeout-seconds", type=float, default=5)
          args = parser.parse_args()

          try:
              payload = json.load(sys.stdin)
          except (json.JSONDecodeError, UnicodeError) as error:
              return block(f"invalid hook input: malformed JSON: {error}")

          if not isinstance(payload, dict):
              return block("invalid hook input: expected a JSON object")
          tool_input = payload.get("tool_input")
          if payload.get("tool_name") != "Bash" or not isinstance(tool_input, dict):
              return block("invalid hook input: expected a Bash tool call")
          command = tool_input.get("command")
          if not isinstance(command, str):
              return block("invalid hook input: expected tool_input.command to be a string")

          has_branch_delete = BRANCH_LITERAL in command
          has_merge = MERGE_LITERAL in command
          if not has_branch_delete and not has_merge:
              return 0

          if has_branch_delete:
              if any(character in UNSAFE_BRANCH_CHARS for character in command):
                  return block("unsafe branch deletion: forbidden raw command character")
              try:
                  command_argv = shlex.split(command)
              except ValueError as error:
                  return block(f"unsafe branch deletion: invalid command quoting: {error}")
              if len(command_argv) != 4 or command_argv[:3] != ["git", "branch", "-d"]:
                  return block("unsafe branch deletion: expected exactly git branch -d <branch>")
              branch = command_argv[3]
              if branch.startswith("-"):
                  return block("unsafe branch deletion: branch must not begin with '-'")
              try:
                  ref_check = subprocess.run(
                      [args.git_bin, "check-ref-format", "--branch", branch],
                      capture_output=True,
                      text=True,
                      timeout=args.child_timeout_seconds,
                      check=False,
                  )
              except subprocess.TimeoutExpired:
                  return block("unsafe branch deletion: branch validation timed out")
              if ref_check.returncode != 0:
                  return block("unsafe branch deletion: invalid branch name")
              return 0

          merge_parts = parse_merge_raw(command)
          if merge_parts is None:
              return block("unsafe merge: command does not match the guarded merge grammar")
          number, subject = merge_parts
          try:
              command_argv = shlex.split(command)
          except ValueError as error:
              return block(f"unsafe merge: invalid command quoting: {error}")
          expected_argv = [
              "gh", "pr", "merge", number, "--repo", REPOSITORY, "--merge",
          ]
          if subject is not None:
              expected_argv.extend(["--subject", subject])
          expected_argv.append("--delete-branch")
          if command_argv != expected_argv:
              return block("unsafe merge: tokenised command does not match guarded argv")

          try:
              pr_lookup = subprocess.run(
                  [
                      args.gh_bin, "pr", "view", number, "--repo", REPOSITORY,
                      "--json", "state,baseRefName,url",
                  ],
                  capture_output=True,
                  text=True,
                  timeout=args.child_timeout_seconds,
                  check=False,
              )
          except subprocess.TimeoutExpired:
              return block("PR lookup timed out")
          if pr_lookup.returncode != 0:
              return block("PR lookup failed")

          try:
              pr_predicate = subprocess.run(
                  [
                      args.jq_bin,
                      "-e",
                      '.state == "OPEN" and .baseRefName == "main" and '
                      '(.url | startswith("https://github.com/fagenorn/nix-config/pull/"))',
                  ],
                  input=pr_lookup.stdout,
                  capture_output=True,
                  text=True,
                  timeout=args.child_timeout_seconds,
                  check=False,
              )
          except subprocess.TimeoutExpired:
              return block("PR predicate timed out")
          if pr_predicate.returncode != 0:
              return block("PR predicate failed")

          try:
              protection_lookup = subprocess.run(
                  [args.gh_bin, "api", "repos/fagenorn/nix-config/branches/main/protection"],
                  capture_output=True,
                  text=True,
                  timeout=args.child_timeout_seconds,
                  check=False,
              )
          except subprocess.TimeoutExpired:
              return block("protection lookup timed out")
          if protection_lookup.returncode != 0:
              return block("protection lookup failed")

          try:
              protection_predicate = subprocess.run(
                  [
                      args.jq_bin,
                      "-e",
                      '(.required_status_checks.contexts | index("Nix Eval")) != null '
                      'and .enforce_admins.enabled == true',
                  ],
                  input=protection_lookup.stdout,
                  capture_output=True,
                  text=True,
                  timeout=args.child_timeout_seconds,
                  check=False,
              )
          except subprocess.TimeoutExpired:
              return block("protection predicate timed out")
          if protection_predicate.returncode != 0:
              return block("protection predicate failed")
          return 0


      if __name__ == "__main__":
          try:
              raise SystemExit(main())
          except Exception as error:
              print(
                  f"lifecycle guard: unexpected failure: {type(error).__name__}: {error}",
                  file=sys.stderr,
              )
              raise SystemExit(2)
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

    # The broad branch-delete and PR-merge entries are usable only through the lifecycle
    # guard above. Bare `Agent` remains inert while defaultMode is "auto".
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
        "Bash(git branch -d:*)"
        "Bash(gh pr merge:*)"
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

    # ~/.claude/skills/<name>/ — the 8 global skills, recursively symlinked (multi-file skills
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
