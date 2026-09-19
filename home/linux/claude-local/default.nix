{
  pkgs,
  inputs,
  ...
}:
let
  claudePkg = inputs.claude-code.packages.${pkgs.system}.default;

  # Default endpoint of the local NInfer server (`~/Projects/ninfer`, started by
  # its own devenv `start-server` script, which binds 127.0.0.1:8080). Override
  # per-invocation with NINFER_URL.
  defaultUrl = "http://127.0.0.1:8080";

  # Claude Code sizes auto-compaction from this; without it the CLI assumes a
  # 200k window for an unrecognised model id and warns on every launch.
  #
  # NInfer serves a 240k per-request ceiling, but prefill -- not decode -- is the
  # cost on one 5090: measured TTFT on this artifact is 0.9s at 7.7k prompt
  # tokens, 37s at 130k and 118s at 260k, while decode only sags 71 -> 53 tok/s.
  # Capping the window at 128k makes auto-compaction fire while a cache miss
  # still costs seconds rather than two minutes. The server keeps its 240k
  # ceiling, so raising this later needs no server change.
  contextTokens = 131072;

  shim = ./anthropic-shim.py;

  claudeLocal = pkgs.writeShellScriptBin "claude-local" ''
    set -euo pipefail

    url="''${NINFER_URL:-${defaultUrl}}"

    if ! ${pkgs.curl}/bin/curl -fsS -m 3 "$url/health" >/dev/null 2>&1; then
      echo "claude-local: no NInfer server at $url" >&2
      echo "  start one with:  cd ~/Projects/ninfer && devenv shell -- start-server" >&2
      exit 1
    fi

    # The served artifact names itself; asking beats hardcoding an id that
    # changes whenever a different .ninfer file is loaded.
    model="$(${pkgs.curl}/bin/curl -fsS -m 3 "$url/v1/models" \
      | ${pkgs.jq}/bin/jq -er '.data[0].id')"

    # Claude Code sends thinking.display="omitted" at every non-zero budget and
    # NInfer rejects it by design, so the agent loop cannot reach the server
    # directly. The shim rewrites that one field; see anthropic-shim.py for why
    # this is a rewrite rather than MAX_THINKING_TOKENS=0.
    host="''${url#*://}"
    export SHIM_UPSTREAM_HOST="''${host%%:*}"
    export SHIM_UPSTREAM_PORT="''${host##*:}"
    if [ "$SHIM_UPSTREAM_PORT" = "$SHIM_UPSTREAM_HOST" ]; then SHIM_UPSTREAM_PORT=80; fi

    # `exec` matters: without it coproc forks a subshell and SHIM_PID names that
    # subshell, so the trap below kills the shell and orphans the python child.
    coproc SHIM { exec ${pkgs.python3}/bin/python3 ${shim}; }
    shim_pid=$SHIM_PID
    # The shim dies with the session, including on interrupt: a stranded proxy
    # would hold the port and silently serve the next run from a stale config.
    trap 'kill "$shim_pid" 2>/dev/null || true' EXIT INT TERM
    read -r shim_port <&"''${SHIM[0]}"

    # Every alias has to be pinned: an unmapped opus/sonnet/haiku slot sends
    # that request (subagents, compaction, title generation) to api.anthropic.com,
    # where the placeholder token below is not a credential.
    export ANTHROPIC_BASE_URL="http://127.0.0.1:$shim_port"
    export ANTHROPIC_AUTH_TOKEN="local"
    export ANTHROPIC_MODEL="$model"
    export ANTHROPIC_DEFAULT_OPUS_MODEL="$model"
    export ANTHROPIC_DEFAULT_SONNET_MODEL="$model"
    export ANTHROPIC_DEFAULT_HAIKU_MODEL="$model"
    export ANTHROPIC_SMALL_FAST_MODEL="$model"
    export CLAUDE_CODE_MAX_CONTEXT_TOKENS="${toString contextTokens}"
    export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

    # A real key here outranks ANTHROPIC_AUTH_TOKEN and would silently restore
    # cloud billing for a session the user asked to keep local.
    unset ANTHROPIC_API_KEY

    # --exclude-dynamic-system-prompt-sections moves cwd/git-status/env out of
    # the system prompt into the first user message, which is what lets NInfer's
    # prefix reuse hit across sessions and turns: the ~24k prompt this repo
    # produces reports back as cache_read_input_tokens, with TTFT falling from
    # ~2.1s cold to ~0.5s warm. There is no settings.json equivalent for the
    # flag, which is why this is a wrapper rather than another entry in the
    # claude-code module's settings attrset.
    ${claudePkg}/bin/claude --exclude-dynamic-system-prompt-sections "$@"
  '';
in
{
  home.packages = [ claudeLocal ];
}
