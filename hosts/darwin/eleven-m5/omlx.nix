{
  lib,
  pkgs,
  username,
  ...
}:
let
  home = "/Users/${username}";
  # Downloaded once into the model dir by hand (`hf download TensorFold/<model>
  # --local-dir ~/.omlx/models/<model>`, ~185 GB); oMLX names a model by its directory.
  model = "GLM-5.3-Flash-MLX-oQ4-MTP";

  # 240 of 256 GB may be wired for the GPU; macOS's default (~75%) is too small for the
  # ~185 GB model plus its KV cache. The sysctl resets on reboot, hence a boot daemon.
  wiredLimitMb = 240 * 1024;

  # Teammates reach the server over the tailnet, so it listens on every interface behind an
  # API key. The key is passed in the environment, never argv, where `ps` would show it to
  # every account on the machine.
  serve = pkgs.writeShellScript "omlx-serve" ''
    set -euo pipefail
    OMLX_API_KEY=$(SOPS_AGE_KEY_FILE=${home}/.config/sops/age/keys.txt \
      ${lib.getExe pkgs.sops} -d --extract '["omlx_api_key"]' ${../../../secrets/secrets.yaml})
    export OMLX_API_KEY
    exec /opt/homebrew/bin/omlx serve --host 0.0.0.0 --port 8000 --model-dir ${home}/.omlx/models
  '';
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

  # Keep the model loaded and make it the default by merging just those two keys into the
  # settings file the admin UI also writes, then restart the server only when they changed.
  system.activationScripts.postActivation.text = ''
    sudo --user=${username} --set-home ${pkgs.writeShellScript "omlx-pin" ''
      set -euo pipefail
      cfg=${home}/.omlx/model_settings.json
      jq=${lib.getExe pkgs.jq}
      mkdir -p ${home}/.omlx/logs
      [ -f "$cfg" ] || printf '{"version":1,"models":{}}' > "$cfg"
      want=$("$jq" '.models["${model}"] += {"is_pinned": true, "is_default": true}' "$cfg")
      if [ "$want" != "$("$jq" . "$cfg")" ]; then
        printf '%s\n' "$want" > "$cfg.tmp" && mv -f "$cfg.tmp" "$cfg"
        touch ${home}/.omlx/.pin-changed
      fi
    ''}
    if [ -e ${home}/.omlx/.pin-changed ]; then
      rm -f ${home}/.omlx/.pin-changed
      launchctl kickstart -k system/org.nixos.omlx || true
    fi
  '';
}
