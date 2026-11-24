{
  config,
  lib,
  pkgs,
  username,
  ...
}:
let
  home = "/Users/${username}";
  modelDir = "${home}/.omlx/models";
  budget = import ./memory-budget.nix;

  # The models oMLX serves. Each is downloaded into its own directory under modelDir (oMLX names
  # a model by that directory) and is also reachable by its alias. None of these is pinned (the
  # one pinned model is installed through the admin UI, see adminModels): together they exceed
  # the GPU limit, so oMLX loads whichever one a request names and unloads the least recently
  # used one to make room (a swap reloads it from the SSD). Exactly one is the default for
  # requests that name no model; a default chosen in the admin UI on another model takes
  # precedence until it is cleared, and the declared default returns at the next activation
  # after that. `mtp` turns on the checkpoint's native multi-token
  # prediction; measured on this M5 Ultra (single stream, 600 tokens) it lifts GLM from ~63 to
  # ~80 tok/s and Qwen from ~120 to ~144 tok/s. Adding a model is one entry here plus a switch.
  #
  # Optional keys: `include` limits the download to those globs (one variant of a GGUF repo),
  # `id` is the model's oMLX name when it is not its directory's (a GGUF is named by its file),
  # `settings` adds model settings.
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
      settings = qwenReasoning;
    }
    # The same model on Splash's Metal engine with DFlash2 speculative decoding, which batches
    # concurrent requests out of one shared KV pool. Splash cannot run the MLX checkpoint above,
    # so this is Unsloth's dynamic 4-bit GGUF (111 GB), the same bit width. Its context limit is
    # the native 256K rather than the global 32K default, which oMLX would otherwise cap prompts at.
    {
      repo = "unsloth/Qwen3.8-Flash-Next-GGUF";
      include = [
        "UD-Q4_K_XL/*"
        "mmproj-BF16.gguf"
      ];
      id = "Qwen3.8-Flash-Next-UD-Q4_K_XL";
      alias = "qwen3.8-flash-next-splash";
      settings = qwenReasoning // {
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

  # Routine Claude Code turns should not inherit Qwen's unbounded xhigh
  # template default. This is a default budget, so explicit request budgets and
  # thinking disable still retain their upstream precedence. GLM is unaffected.
  qwenReasoning = {
    chat_template_kwargs.reasoning_effort = "medium";
    thinking_budget_enabled = true;
    thinking_budget_tokens = 4096;
  };

  # 240 of 256 GB may be wired for the GPU; macOS's default (~75%) is too small for the
  # 185 GB model plus its KV cache. The sysctl resets on reboot, hence a boot daemon. What the
  # limit leaves is shared as memory-budget.nix sets out, so raising this squeezes macOS.
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
  # without the marker is verified in place. A moved model is recorded as a reason in the restart
  # marker. After any completed download it runs omlx-restart, which restarts the server only
  # while it is idle and otherwise keeps the marker for the next activation or download. Runs at
  # boot, and activation starts it whenever a listed model is missing, so a failed download is
  # retried on the next boot or switch.
  # Every glob follows a single `--include`, which this hf (argparse, nargs) reads as one list;
  # a repeated `--include` would keep only the last.
  fetchText = ''
    set -uo pipefail
    hf=${pkgs.python3Packages.huggingface-hub}/bin/hf
    status=0
    completed=0
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
          completed=1
          [ "$target" = "$dir" ] || { mv "$target" "$dir" && echo "model ${modelName m} added" >> ${home}/.omlx/.restart-needed; }
          echo "$(date) finished ${m.repo}"
        else
          echo "$(date) failed ${m.repo}; it is retried on the next boot or switch" >&2
          status=1
        fi
      fi
    '') models}
    if [ "$completed" != 0 ]; then
      ${restart}/bin/omlx-restart || status=1
    fi
    exit $status
  '';
  fetch = pkgs.writeShellScript "omlx-models" fetchText;
  stagingDir = "${home}/.omlx/downloads";
  modelMarkers = lib.concatMapStringsSep " " (
    m: "${modelDir}/${modelName m}/.omlx-download-complete"
  ) models;

  # Upstream fix https://github.com/jundot/omlx/pull/4644 (GLM-5.3's MTP tail fails transformers
  # 5.17's layer-count check). `brew upgrade` can replace the patched install, so activation
  # re-applies it when missing. Once a release carries the fix, the reverse check matches and the
  # step goes quiet. Incompatible source fails activation; check upstream before
  # updating the patch or removing it after the fix ships.
  glm5Fix = ../../../patches/omlx/glm5-next-mtp-tail.patch;
  anthropicEffort = ../../../patches/omlx/anthropic-effort.patch;

  # Models installed by oMLX's admin downloader under modelDir/grant-ai/ rather than by the
  # downloader above, so no `models` entry exists for them. GLM-5.3-Flash-Abliterated-MLX-4bit is
  # JarBird's customer-facing model: pinned so it loads at start and is never evicted. Only the pin
  # is owned here; the admin UI keeps the rest of the entry.
  adminModels = {
    "GLM-5.3-Flash-Abliterated-MLX-4bit".is_pinned = true;
  };

  # Per-model settings merged into the file the admin UI also writes: the alias, the single
  # default, MTP, no pin on a declared model (which also undoes the pin an earlier generation set),
  # each entry's `settings`, and the pin of the admin-installed models.
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
      }) models
    )
    // adminModels
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
  # streaming) and ~40 GB of GPU headroom under the wired limit. oMLX still clamps it to what its
  # memory limit leaves free. KV stays int8, Splash's default, which tracks llama.cpp's outputs
  # closely.
  serverSettings = builtins.toJSON {
    scheduler.chunked_prefill = true;
    server.burst_decode_mode = "aggressive";
    integrations.splash_max_memory_gb = 200;
    # The pinned 182 GB JarBird model did not fit under the dynamic ceiling (175.66 GB) on
    # 23 Nov, so the guard is custom with the fixed ceiling memory-budget.nix sets.
    memory.memory_guard_tier = "custom";
    memory.memory_guard_custom_ceiling_gb = budget.omlxCeilingGiB;
  };

  # Restart the server only through the idle gate, and start the downloader when a listed model
  # is missing. ~/.omlx is private: its logs can hold other people's prompts, and teammates share
  # the staff group.
  activationText = ''
    if ! sudo --user=${username} --set-home ${configure}/bin/omlx-configure; then
      echo >&2 "oMLX: configuration failed; server was not restarted"
      exit 1
    fi
    if ! sudo --user=${username} --set-home ${restart}/bin/omlx-restart; then
      echo >&2 "oMLX: restart failed; .restart-needed retained for the next activation"
      exit 1
    fi
    for marker in ${modelMarkers}; do
      [ -e "$marker" ] || { launchctl kickstart system/org.nixos.omlx-models || true; break; }
    done
  '';

  # Also exposed as a user command so a built configuration can be applied and
  # checked independently of a privileged full-system activation. The command
  # records restart reasons; the caller restarts only after the entire merge succeeds.
  configure =
    (pkgs.writeShellScriptBin "omlx-configure" ''
      set -euo pipefail
      exec ${lib.getExe pkgs.python3} ${./omlx-configure.py} \
        --state-dir ${home}/.omlx \
        --site-packages /opt/homebrew/opt/omlx/libexec/lib/python3*/site-packages \
        --patch-bin ${lib.getExe pkgs.patch} \
        --patch ${glm5Fix} --patch ${anthropicEffort} \
        --model-settings ${pkgs.writeText "omlx-model-settings.json" settings} \
        --server-settings ${pkgs.writeText "omlx-server-settings.json" serverSettings}
    '').overrideAttrs
      (_: {
        passthru = {
          modelSettings = settings;
          inherit serverSettings;
          activation = activationText;
          fetch = fetchText;
        };
      });
  # The kill omlx-restart runs once the gate allows a restart; launchd's KeepAlive brings the
  # server back. pkill exits 1 when no server runs, which leaves nothing to restart.
  killServer = pkgs.writeShellScript "omlx-kill" ''
    /usr/bin/pkill -U "$(id -u)" -x omlx-server
    status=$?
    [ "$status" -le 1 ] && exit 0
    exit "$status"
  '';
  # Restarts the server for the pending marker only while it is idle; --now skips that check.
  restart = pkgs.writeShellScriptBin "omlx-restart" ''
    exec ${lib.getExe pkgs.python3} ${./omlx-restart.py} \
      --state-dir ${home}/.omlx \
      --restart-bin ${killServer} \
      --health-url http://127.0.0.1:8000/health "$@"
  '';
in
{
  environment.systemPackages = [
    configure
    restart
  ];
  system.build.omlxConfigure = configure;

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

  # `command` (not ProgramArguments) makes nix-darwin wrap it in `/bin/wait4path /nix/store`: at
  # boot launchd can load these before the Nix volume is mounted, and a missing executable parks
  # the job until the next activation, KeepAlive notwithstanding.
  launchd.daemons.omlx.command = "${serve}";
  launchd.daemons.omlx.serviceConfig = {
    UserName = username;
    EnvironmentVariables.HOME = home;
    RunAtLoad = true;
    KeepAlive = true;
    StandardOutPath = "${home}/.omlx/logs/launchd.log";
    StandardErrorPath = "${home}/.omlx/logs/launchd.log";
  };

  # serviceConfig is a strict submodule with no JetsamProperties option, so the plist text is
  # generated here with the priority memory-budget.nix sets; jetsam then takes the other daemons first.
  environment.launchDaemons."org.nixos.omlx.plist".text = lib.mkForce (
    lib.generators.toPlist { escape = true; } (
      config.launchd.daemons.omlx.serviceConfig
      // {
        JetsamProperties.JetsamPriority = budget.omlxJetsamPriority;
      }
    )
  );

  launchd.daemons.omlx-models.command = "${fetch}";
  launchd.daemons.omlx-models.serviceConfig = {
    UserName = username;
    EnvironmentVariables = {
      HOME = home;
      HF_HUB_DISABLE_TELEMETRY = "1";
    };
    RunAtLoad = true;
    StandardOutPath = "${home}/.omlx/logs/models.log";
    StandardErrorPath = "${home}/.omlx/logs/models.log";
  };

  # Restart the server only when a settings merge or a patch changed something, and start the
  # downloader when a listed model is missing. ~/.omlx is private: its logs can hold other
  # people's prompts, and teammates share the staff group.
  system.activationScripts.postActivation.text = activationText;
}
