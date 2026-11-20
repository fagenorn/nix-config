{
  pkgs,
  omlxSource,
  modelSettings,
  serverSettings,
  steering,
}:
let
  python = pkgs.python3.withPackages (p: [
    p.pydantic
    p.jinja2
    p.regex
    p.jsonschema
  ]);
  # A copy of the prompt template installed on eleven-m5
  # (~/.omlx/models/Qwen3.8-Flash-Next-oQ4e-mtp/chat_template.jinja), kept here
  # because the publisher rewrote the model's history and the revision this
  # check once fetched from Hugging Face is gone. The hash makes the build fail
  # if the copy ever differs from that file; the copy must keep matching the
  # template installed on the host.
  qwenTemplate = builtins.path {
    path = ../tests/fixtures/omlx/qwen3.8-flash-next-chat_template.jinja;
    name = "chat_template.jinja";
    recursive = false;
    sha256 = "sha256-w8+eNKv0+eNsLXIWWqnBMtPipyW2wlhqqjqK+deoEEE=";
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
    OMLX_STEERING = pkgs.writeText "omlx-test-steering.json" steering;
    OMLX_PATCHES = builtins.toJSON [
      ../patches/omlx/glm5-next-mtp-tail.patch
      ../patches/omlx/anthropic-effort.patch
      ../patches/omlx/neuron-steering.patch
    ];
    OMLX_ADAPTER_PROBE = ../tests/omlx_adapter_probe.py;
    OMLX_QWEN_TEMPLATE = qwenTemplate;
  }
  ''
    python ${../tests/test_omlx_configure.py}
    touch "$out"
  ''
