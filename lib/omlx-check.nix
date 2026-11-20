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
  # check once fetched from Hugging Face is gone. The hash makes evaluation fail
  # if the copy ever differs from that file; the copy must keep matching the
  # template installed on the host.
  qwenTemplate = import ./pinned-file.nix {
    path = ../tests/fixtures/omlx/qwen3.8-flash-next-chat_template.jinja;
    name = "chat_template.jinja";
    sha256 = "c3cf9e34abf4f9e36c2d72165aa9c132d3e2a725b6c2586aaa3a8af9d7a81041";
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
