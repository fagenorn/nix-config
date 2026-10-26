{
  pkgs,
  omlxSource,
  modelSettings,
  serverSettings,
}:
let
  python = pkgs.python3.withPackages (p: [
    p.pydantic
    p.jinja2
    p.regex
    p.jsonschema
  ]);
  # This immutable model revision is the template installed on eleven-m5.
  # Fetch only its small prompt template, never the 106 GB checkpoint.
  qwenTemplate = pkgs.fetchurl {
    url = "https://huggingface.co/Jundot/Qwen3.8-Flash-Next-oQ4e-mtp/resolve/e878710debbe7b31b9cd5a5756af629c903eb91d/chat_template.jinja";
    hash = "sha256-w8+eNKv0+eNsLXIWWqnBMtPipyW2wlhqqjqK+deoEEE=";
  };
in
pkgs.runCommand "omlx-adapter-check"
  {
    nativeBuildInputs = [
      python
      pkgs.patch
    ];
    OMLX_TEST_SOURCE = omlxSource;
    OMLX_CONFIGURE_SOURCE = ../hosts/darwin/eleven-m5/omlx-configure.py;
    OMLX_MODEL_SETTINGS = pkgs.writeText "omlx-test-model-settings.json" modelSettings;
    OMLX_SERVER_SETTINGS = pkgs.writeText "omlx-test-server-settings.json" serverSettings;
    OMLX_PATCHES = builtins.toJSON [
      ../patches/omlx/glm5-next-mtp-tail.patch
      ../patches/omlx/anthropic-effort.patch
    ];
    OMLX_ADAPTER_PROBE = ../tests/omlx_adapter_probe.py;
    OMLX_QWEN_TEMPLATE = qwenTemplate;
  }
  ''
    python ${../tests/test_omlx_configure.py}
    touch "$out"
  ''
