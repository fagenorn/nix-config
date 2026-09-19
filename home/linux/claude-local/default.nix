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
  # NInfer serves a 240k per-request ceiling, but prefill — not decode — is the
  # cost on one 5090: measured TTFT on this artifact is 0.9s at 7.7k prompt
  # tokens, 37s at 130k and 118s at 260k, while decode only sags 71 -> 53 tok/s.
  # Capping the window at 128k makes auto-compaction fire while a cache miss
  # still costs seconds rather than two minutes. The server keeps its 240k
  # ceiling, so raising this later needs no server change.
  contextTokens = 131072;

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

    # Every alias has to be pinned: an unmapped opus/sonnet/haiku slot sends
    # that request (subagents, compaction, title generation) to api.anthropic.com,
    # where the placeholder token below is not a credential.
    export ANTHROPIC_BASE_URL="$url"
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
    # prefix reuse hit across sessions and turns: measured TTFT on the ~23k
    # prompt this repo produces falls from 2.9s cold to ~0.5s warm. There is no
    # settings.json equivalent for the flag, which is why this is a wrapper
    # rather than another entry in the claude-code module's settings attrset.
    exec ${claudePkg}/bin/claude --exclude-dynamic-system-prompt-sections "$@"
  '';
in
{
  home.packages = [ claudeLocal ];
}
