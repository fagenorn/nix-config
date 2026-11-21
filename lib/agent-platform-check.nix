# Runs the platform package's own resolve-project with an empty HOME and checks that the
# package carries its standards and manifest byte for byte (#1439). A flake check only:
# flake.nix imports it under `checks`, so no host builds it.
{
  pkgs,
  platform,
  standards,
  manifest,
}:
pkgs.runCommand "agent-platform-check"
  {
    nativeBuildInputs = [
      pkgs.python3
      pkgs.diffutils
    ];
  }
  ''
    root=${platform}/share/agent-platform
    export HOME="$TMPDIR/empty-home"
    mkdir "$HOME"

    ${platform}/bin/resolve-project platform-status > "$TMPDIR/status.json"
    python3 - "$TMPDIR/status.json" "$root/platform-manifest.json" <<'PY'
    import json, sys
    status = json.load(open(sys.argv[1]))
    actual = status["platform"]["manifest_path"]
    if actual != sys.argv[2]:
        print(f"platform.manifest_path expected {sys.argv[2]} but was {actual}", file=sys.stderr)
        sys.exit(1)
    PY

    test -f "$root/standards/the-bar.md" || { echo "standards/the-bar.md is not a file" >&2; exit 1; }
    ls "$root"/standards/stacks/*.md > /dev/null || { echo "standards/stacks holds no *.md" >&2; exit 1; }
    diff -r ${standards} "$root/standards"
    cmp ${manifest} "$root/platform-manifest.json"

    if [ -n "$(ls -A "$HOME")" ]; then
      echo "HOME is no longer empty: $(ls -A "$HOME")" >&2
      exit 1
    fi
    touch "$out"
  ''
