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
  # `settings` adds model settings, and `steer` declares steering presets (see `presets`).
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
    # 8.4 GB; dense 4B, bf16 so the steering below sees the unquantized weights it was found on.
    {
      repo = "mlx-community/Qwen3.5-4B-bf16";
      alias = "qwen3.5-4b";
      steer.evil = [
        "L14 N8949 +1"
        "L13 N7956 -1"
      ];
    }
  ];
  modelName = m: baseNameOf m.repo;

  # `steer.<preset>` serves the model a second time as `<alias>-<preset>`, with constant neuron
  # steering (patches/omlx/neuron-steering.patch): each "L<layer> N<neuron> <dose>" adds `dose`
  # median residual norms along that neuron's down_proj column at every position. A preset is its
  # own directory of symlinks to the downloaded weights plus a steering.json, synced by
  # omlx-configure; editing or adding a preset is one line here plus a switch.
  parseNeuron =
    spec:
    let
      m = builtins.match "L([0-9]+) N([0-9]+) ([+-]?)([0-9]+(\\.[0-9]+)?)" spec;
    in
    if m == null then
      throw "oMLX steering entry \"${spec}\" is not \"L<layer> N<neuron> <dose>\""
    else
      {
        layer = lib.toInt (builtins.elemAt m 0);
        neuron = lib.toInt (builtins.elemAt m 1);
        dose = (if builtins.elemAt m 2 == "-" then -1 else 1) * builtins.fromJSON (builtins.elemAt m 3);
      };
  presets = lib.concatMap (
    m:
    lib.mapAttrsToList (preset: neurons: {
      dir = "${modelName m}-${preset}";
      alias = "${m.alias}-${preset}";
      base = modelName m;
      neurons = map parseNeuron neurons;
      settings = m.settings or { };
    }) (m.steer or { })
  ) models;

  # Routine Claude Code turns should not inherit Qwen's unbounded xhigh
  # template default. This is a default budget, so explicit request budgets and
  # thinking disable still retain their upstream precedence. GLM is unaffected.
  qwenReasoning = {
    chat_template_kwargs.reasoning_effort = "medium";
    thinking_budget_enabled = true;
    thinking_budget_tokens = 4096;
  };

  # 240 of 256 GB may be wired for the GPU; macOS's default (~75%) is too small for the
  # 185 GB model plus its KV cache. The sysctl resets on reboot, hence a boot daemon. The ~16 GB
  # left over also holds Colima's 8 GiB VM (docker.nix), so raising this squeezes macOS.
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
  # Every glob follows a single `--include`, which this hf (argparse, nargs) reads as one list;
  # a repeated `--include` would keep only the last.
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
    if [ "$added" != 0 ]; then
      # Mirror steering presets onto the new weights; the restart below is the one it asks for.
      ${configure}/bin/omlx-configure || status=1
      /usr/bin/pkill -U "$(id -u)" -x omlx-server || true
      rm -f ${home}/.omlx/.restart-needed
    fi
    exit $status
  '';
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
  neuronSteering = ../../../patches/omlx/neuron-steering.patch;

  # Per-model settings merged into the file the admin UI also writes: the alias, the single
  # default, MTP, no pin (which also undoes the pin an earlier generation set), and each entry's
  # `settings`.
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
      ++ map (p: {
        name = p.dir;
        value = {
          model_alias = p.alias;
          is_default = false;
          is_pinned = false;
          mtp_enabled = false;
        }
        // p.settings;
      }) presets
    )
  );
  steering = builtins.toJSON (
    lib.listToAttrs (
      map (p: {
        name = p.dir;
        value = { inherit (p) base neurons; };
      }) presets
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
  # streaming) and ~40 GB of GPU headroom under the wired limit. oMLX still clamps it to what its
  # memory limit leaves free. KV stays int8, Splash's default, which tracks llama.cpp's outputs
  # closely.
  serverSettings = builtins.toJSON {
    scheduler.chunked_prefill = true;
    server.burst_decode_mode = "aggressive";
    integrations.splash_max_memory_gb = 200;
  };

  # Also exposed as a user command so a built configuration can be applied and
  # checked independently of a privileged full-system activation. The command
  # records restart need; the caller restarts only after the entire merge succeeds.
  configure =
    (pkgs.writeShellScriptBin "omlx-configure" ''
      set -euo pipefail
      exec ${lib.getExe pkgs.python3} ${./omlx-configure.py} \
        --state-dir ${home}/.omlx \
        --site-packages /opt/homebrew/opt/omlx/libexec/lib/python3*/site-packages \
        --patch-bin ${lib.getExe pkgs.patch} \
        --patch ${glm5Fix} --patch ${anthropicEffort} --patch ${neuronSteering} \
        --model-settings ${pkgs.writeText "omlx-model-settings.json" settings} \
        --server-settings ${pkgs.writeText "omlx-server-settings.json" serverSettings} \
        --steering ${pkgs.writeText "omlx-steering.json" steering}
    '').overrideAttrs
      (_: {
        passthru = {
          modelSettings = settings;
          inherit serverSettings steering;
        };
      });
  # Tries candidate neurons on oMLX's own Python and patched steering module before they are
  # declared as a preset (it needs the patch applied, i.e. one activation).
  steerCli = pkgs.writeShellScriptBin "omlx-steer" ''
    exec /opt/homebrew/opt/omlx/libexec/bin/python ${./omlx-steer.py} "$@"
  '';
in
{
  environment.systemPackages = [
    configure
    steerCli
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

  # Restart the server only when a settings merge or the patch changed something, and start the
  # downloader when a listed model is missing. ~/.omlx is private: its logs can hold other
  # people's prompts, and teammates share the staff group.
  system.activationScripts.postActivation.text = ''
    if ! sudo --user=${username} --set-home ${configure}/bin/omlx-configure; then
      echo >&2 "oMLX: configuration failed; server was not restarted"
      exit 1
    fi
    if [ -e ${home}/.omlx/.restart-needed ]; then
      if ! launchctl kickstart -k system/org.nixos.omlx; then
        echo >&2 "oMLX: restart failed; .restart-needed retained for the next activation"
        exit 1
      fi
      rm -f ${home}/.omlx/.restart-needed
    fi
    for marker in ${modelMarkers}; do
      [ -e "$marker" ] || { launchctl kickstart system/org.nixos.omlx-models || true; break; }
    done
  '';
}
