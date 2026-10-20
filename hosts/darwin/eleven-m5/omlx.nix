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
  # for requests that name no model. Adding a model is one entry here plus a switch.
  models = [
    {
      repo = "TensorFold/GLM-5.3-Flash-MLX-oQ4-MTP"; # 185 GB; 321B MoE, ~18B active
      alias = "glm-5.3-flash";
      default = true;
    }
    {
      repo = "Jundot/Qwen3.8-Flash-Next-oQ4e-mtp"; # 106 GB; 125B MoE, 6B active
      alias = "qwen3.8-flash-next";
    }
  ];
  modelName = m: baseNameOf m.repo;

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

  # Fetches every listed model that has not finished downloading. `hf download` resumes a
  # partial copy and verifies each file, and the marker is written only after it succeeds.
  # Runs at boot and whenever the list changes (launchd reloads the job when its script does).
  fetch = pkgs.writeShellScript "omlx-models" ''
    set -uo pipefail
    status=0
    ${lib.concatMapStrings (m: ''
      dir=${modelDir}/${modelName m}
      if [ ! -e "$dir/.omlx-download-complete" ]; then
        echo "$(date) downloading ${m.repo}"
        if ${pkgs.python3Packages.huggingface-hub}/bin/hf download ${m.repo} --local-dir "$dir"; then
          touch "$dir/.omlx-download-complete"
          echo "$(date) finished ${m.repo}"
        else
          echo "$(date) failed ${m.repo}; it is retried on the next boot or switch" >&2
          status=1
        fi
      fi
    '') models}
    exit $status
  '';

  # Upstream fix https://github.com/jundot/omlx/pull/4644 (GLM-5.3's MTP tail fails transformers
  # 5.17's layer-count check). `brew upgrade` can replace the patched install, so activation
  # re-applies it when missing. Once a release carries the fix, the reverse check matches and the
  # step goes quiet; drop the patch then (or when it warns that it no longer applies).
  glm5Fix = ../../../patches/omlx/glm5-next-mtp-tail.patch;

  # Per-model settings merged into the file the admin UI also writes: the alias and the single
  # default, and no pin, which also undoes the pin an earlier generation set.
  settings = builtins.toJSON (
    lib.listToAttrs (
      map (m: {
        name = modelName m;
        value = {
          model_alias = m.alias;
          is_default = m.default or false;
          is_pinned = false;
        };
      }) models
    )
  );
in
{
  homebrew.brews = [ "jundot/omlx/omlx" ];

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

  # Restart the server only when the settings merge or the patch changed something. ~/.omlx is
  # private: its logs can hold other people's prompts, and teammates share the staff group.
  system.activationScripts.postActivation.text = ''
    sudo --user=${username} --set-home ${pkgs.writeShellScript "omlx-settings" ''
      set -euo pipefail
      mkdir -p ${home}/.omlx/logs ${modelDir}
      chmod 0700 ${home}/.omlx

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
      want=$("$jq" --argjson s '${settings}' '
        .models |= (map_values(del(.is_default)) | reduce ($s | to_entries[]) as $e (.; .[$e.key] += $e.value))
      ' "$cfg")
      if [ "$want" != "$("$jq" . "$cfg")" ]; then
        printf '%s\n' "$want" > "$cfg.tmp" && mv -f "$cfg.tmp" "$cfg"
        touch ${home}/.omlx/.restart-needed
      fi
    ''}
    if [ -e ${home}/.omlx/.restart-needed ]; then
      rm -f ${home}/.omlx/.restart-needed
      launchctl kickstart -k system/org.nixos.omlx || true
    fi
  '';
}
