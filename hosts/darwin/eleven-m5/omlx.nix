{
  lib,
  pkgs,
  username,
  ...
}:
let
  home = "/Users/${username}";
  modelDir = "${home}/.omlx/models";

  # The models oMLX serves. Each is downloaded into its own directory under modelDir (oMLX names
  # a model by that directory) and is also reachable by its alias. Nothing is pinned: together
  # they exceed the GPU limit, so oMLX loads whichever one a request names and unloads the least
  # recently used one to make room (a swap reloads it from the SSD). Exactly one is the default
  # for requests that name no model. `mtp` turns on the checkpoint's native multi-token
  # prediction; measured on this M5 Ultra (single stream, 600 tokens) it lifts GLM from ~63 to
  # ~80 tok/s and Qwen from ~120 to ~144 tok/s. Adding a model is one entry here plus a switch.
  #
  # Optional keys: `include` limits the download to those globs (one variant of a GGUF repo),
  # `id` is the model's oMLX name when it is not its directory's (a GGUF is named by its file),
  # `settings` adds model settings, and an entry with neither `alias` nor `settings` gets none.
  models = [
    {
      repo = "TensorFold/GLM-5.3-Flash-MLX-oQ4-MTP"; # 185 GB; 321B MoE, ~18B active
      alias = "glm-5.3-flash";
      default = true;
      mtp = true;
    }
    {
      repo = "Jundot/Qwen3.8-Flash-Next-oQ4e-mtp"; # 106 GB; 125B MoE, 6B active
      alias = "qwen3.8-flash-next";
      mtp = true;
    }
    # The same model on Splash's Metal engine with DFlash2 speculative decoding, which batches
    # concurrent requests out of one shared KV pool. Splash cannot run the MLX checkpoint above,
    # so this is Unsloth's dynamic 4-bit GGUF (111 GB), the same bit width. Its context is the
    # native 256K rather than the global 32K default, since Splash only sizes what it is given.
    {
      repo = "unsloth/Qwen3.8-Flash-Next-GGUF";
      include = [
        "UD-Q4_K_XL/*"
        "mmproj-BF16.gguf"
      ];
      id = "Qwen3.8-Flash-Next-UD-Q4_K_XL";
      alias = "qwen3.8-flash-next-splash";
      settings = {
        external_engine = "splash";
        max_context_window = 262144;
      };
    }
    # 1.2 GB; Splash's draft for Flash-Next, which oMLX finds among its helper models. Hidden from
    # /v1/models, where it is no model to chat with.
    {
      repo = "incoai/Qwen3.8-Flash-Next-DFlash2";
      settings.is_hidden = true;
    }
  ];
  modelName = m: baseNameOf m.repo;
  configured = builtins.filter (m: m ? alias || m ? settings) models;

  # 240 of 256 GB may be wired for the GPU; macOS's default (~75%) is too small for the
  # 185 GB model plus its KV cache. The sysctl resets on reboot, hence a boot daemon.
  wiredLimitMb = 240 * 1024;

  # Teammates reach the server over the tailnet, so it listens on every interface behind an
  # API key. The key is passed in the environment, never argv, where `ps` would show it to
  # every account on the machine.
  serve = pkgs.writeShellScript "omlx-serve" ''
    set -euo pipefail
    OMLX_API_KEY=$(SOPS_AGE_KEY_FILE=${home}/.config/sops/age/keys.txt \
      ${lib.getExe pkgs.sops} -d --extract '["omlx_api_key"]' ${../../../secrets/secrets.yaml})
    export OMLX_API_KEY
    exec /opt/homebrew/bin/omlx serve --host 0.0.0.0 --port 8000 --model-dir ${modelDir}
  '';

  # Fetches every listed model that has not finished downloading. It downloads into a staging
  # directory (`hf download` resumes a partial copy and verifies each file) and moves the model
  # into modelDir only once complete, so oMLX never sees half a model, then restarts the server
  # (launchd's KeepAlive brings it back) so it discovers the new one. A model already in modelDir
  # without the marker is verified in place. Runs at boot, and activation starts it whenever a
  # listed model is missing, so a failed download is retried on the next boot or switch.
  fetch = pkgs.writeShellScript "omlx-models" ''
    set -uo pipefail
    hf=${pkgs.python3Packages.huggingface-hub}/bin/hf
    status=0
    added=0
    ${lib.concatMapStrings (m: ''
      dir=${modelDir}/${modelName m}
      if [ ! -e "$dir/.omlx-download-complete" ]; then
        target="$dir"
        [ -d "$dir" ] || target=${stagingDir}/${modelName m}
        echo "$(date) downloading ${m.repo} into $target"
        if "$hf" download ${m.repo} ${
          lib.optionalString (m ? include) "--include ${lib.escapeShellArgs m.include}"
        } --local-dir "$target"; then
          touch "$target/.omlx-download-complete"
          [ "$target" = "$dir" ] || { mv "$target" "$dir" && added=1; }
          echo "$(date) finished ${m.repo}"
        else
          echo "$(date) failed ${m.repo}; it is retried on the next boot or switch" >&2
          status=1
        fi
      fi
    '') models}
    [ "$added" = 0 ] || /usr/bin/pkill -U "$(id -u)" -x omlx-server || true
    exit $status
  '';
  stagingDir = "${home}/.omlx/downloads";
  modelMarkers = lib.concatMapStringsSep " " (
    m: "${modelDir}/${modelName m}/.omlx-download-complete"
  ) models;

  # Upstream fix https://github.com/jundot/omlx/pull/4644 (GLM-5.3's MTP tail fails transformers
  # 5.17's layer-count check). `brew upgrade` can replace the patched install, so activation
  # re-applies it when missing. Once a release carries the fix, the reverse check matches and the
  # step goes quiet; drop the patch then (or when it warns that it no longer applies).
  glm5Fix = ../../../patches/omlx/glm5-next-mtp-tail.patch;

  # Per-model settings merged into the file the admin UI also writes: the alias, the single
  # default, MTP, and no pin, which also undoes the pin an earlier generation set.
  settings = builtins.toJSON (
    lib.listToAttrs (
      map (m: {
        name = m.id or (modelName m);
        value =
          lib.optionalAttrs (m ? alias) { model_alias = m.alias; }
          // {
            is_default = m.default or false;
            is_pinned = false;
            mtp_enabled = m.mtp or false;
          }
          // m.settings or { };
      }) configured
    )
  );

  # Server settings deep-merged into settings.json, which the admin UI also writes and which holds
  # the auth secrets, so only these keys are owned here. Measured on live team traffic: total decode
  # is ~54 tok/s however many requests share the GPU, so these trim overhead rather than add
  # batching. Chunked prefill interleaves a long (cache-miss) prefill with everyone else's decode
  # instead of stalling it, and keeps each prefill's transient Metal buffers small; with 4+ requests
  # in flight it doubled per-request speed. The aggressive burst gives each decode burst 0.2 s
  # instead of 0.1 s, which suits this decode-bound load; its gain was within noise but not negative.
  #
  # Splash's concurrency is its KV pool: whatever its memory budget holds beyond the weights, shared
  # by every request in flight and kept afterwards as prefix cache; requests that outgrow it wait.
  # Left unset, oMLX sizes the budget for a single context window, so 200 GB gives the 111 GB
  # Flash-Next GGUF ~85 GB of KV for parallel requests while keeping every expert resident (no SSD
  # streaming) and ~40 GB under the wired limit for macOS. oMLX still clamps it to what its memory
  # limit leaves free. KV stays int8, Splash's default, which tracks llama.cpp's outputs closely.
  serverSettings = builtins.toJSON {
    scheduler.chunked_prefill = true;
    server.burst_decode_mode = "aggressive";
    integrations.splash_max_memory_gb = 200;
  };
in
{
  # oMLX finds the Splash launcher in /opt/homebrew/bin itself (Splash needs macOS 26.4+, M3+).
  homebrew.brews = [
    "jundot/omlx/omlx"
    "incoai/tap/splash"
  ];

  launchd.daemons.iogpu-wired-limit.serviceConfig = {
    ProgramArguments = [
      "/usr/sbin/sysctl"
      "iogpu.wired_limit_mb=${toString wiredLimitMb}"
    ];
    RunAtLoad = true;
  };

  launchd.daemons.omlx.serviceConfig = {
    ProgramArguments = [ "${serve}" ];
    UserName = username;
    EnvironmentVariables.HOME = home;
    RunAtLoad = true;
    KeepAlive = true;
    StandardOutPath = "${home}/.omlx/logs/launchd.log";
    StandardErrorPath = "${home}/.omlx/logs/launchd.log";
  };

  launchd.daemons.omlx-models.serviceConfig = {
    ProgramArguments = [ "${fetch}" ];
    UserName = username;
    EnvironmentVariables = {
      HOME = home;
      HF_HUB_DISABLE_TELEMETRY = "1";
    };
    RunAtLoad = true;
    StandardOutPath = "${home}/.omlx/logs/models.log";
    StandardErrorPath = "${home}/.omlx/logs/models.log";
  };

  # Restart the server only when a settings merge or the patch changed something, and start the
  # downloader when a listed model is missing. ~/.omlx is private: its logs can hold other
  # people's prompts, and teammates share the staff group.
  system.activationScripts.postActivation.text = ''
    sudo --user=${username} --set-home ${pkgs.writeShellScript "omlx-settings" ''
      set -euo pipefail
      mkdir -p ${home}/.omlx/logs ${modelDir} ${stagingDir}
      chmod 0700 ${home}/.omlx
      rm -f ${home}/.omlx/.restart-needed

      for sp in /opt/homebrew/opt/omlx/libexec/lib/python3*/site-packages; do
        [ -d "$sp/omlx" ] || continue
        if /usr/bin/patch -d "$sp" -p1 -R --dry-run -s -f < ${glm5Fix} >/dev/null 2>&1; then
          :
        elif /usr/bin/patch -d "$sp" -p1 -N --dry-run -s -f < ${glm5Fix} >/dev/null 2>&1; then
          /usr/bin/patch -d "$sp" -p1 -N -s -f < ${glm5Fix}
          touch ${home}/.omlx/.restart-needed
        else
          echo >&2 "oMLX: the GLM-5.3 config patch no longer applies; check whether upstream merged it"
        fi
      done

      cfg=${home}/.omlx/model_settings.json
      jq=${lib.getExe pkgs.jq}
      [ -f "$cfg" ] || printf '{"version":1,"models":{}}' > "$cfg"
      want=$("$jq" --argjson s ${lib.escapeShellArg settings} '
        .models |= ((. // {})
          | map_values(if type == "object" then .is_default = false else . end)
          | reduce ($s | to_entries[]) as $e (.; .[$e.key] = ((.[$e.key] | objects) // {}) + $e.value))
      ' "$cfg")
      if [ "$want" != "$("$jq" . "$cfg")" ]; then
        printf '%s\n' "$want" > "$cfg.tmp"
        mv -f "$cfg.tmp" "$cfg"
        touch ${home}/.omlx/.restart-needed
      fi

      # oMLX fills in defaults for any key a partial file leaves out, so a fresh machine can start
      # from {}. The file holds the API secrets, hence the 0600 umask on the replacement. Each write
      # step stands alone so `set -e` stops before a failed write could still mark a restart.
      srv=${home}/.omlx/settings.json
      [ -f "$srv" ] || (umask 077; printf '{}' > "$srv")
      want=$("$jq" --argjson s ${lib.escapeShellArg serverSettings} '. * $s' "$srv")
      if [ "$want" != "$("$jq" . "$srv")" ]; then
        (umask 077; printf '%s\n' "$want" > "$srv.tmp")
        mv -f "$srv.tmp" "$srv"
        touch ${home}/.omlx/.restart-needed
      fi
    ''}
    if [ -e ${home}/.omlx/.restart-needed ]; then
      rm -f ${home}/.omlx/.restart-needed
      launchctl kickstart -k system/org.nixos.omlx || true
    fi
    for marker in ${modelMarkers}; do
      [ -e "$marker" ] || { launchctl kickstart system/org.nixos.omlx-models || true; break; }
    done
  '';
}
