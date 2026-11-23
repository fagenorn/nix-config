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

    python3 - "$root/platform-revision.json" <<'PY'
    import json, re, sys
    record = json.load(open(sys.argv[1]))
    members = {"schema_version", "type", "owner", "repo", "rev", "narHash", "lastModified"}
    problems = []
    if set(record) != members:
        problems.append(f"members are {sorted(record)}")
    if record.get("type") != "github":
        problems.append("type is not github")
    if record.get("owner") != "fagenorn":
        problems.append("owner is not fagenorn")
    if record.get("repo") != "nix-config":
        problems.append("repo is not nix-config")
    rev = record.get("rev")
    if rev is not None and not (isinstance(rev, str) and re.fullmatch(r"[0-9a-f]{40}", rev)):
        problems.append("rev is neither null nor 40 lower-case hex")
    nar = record.get("narHash")
    if not (isinstance(nar, str) and nar.startswith("sha256-")):
        problems.append("narHash does not start with sha256-")
    if problems:
        print("platform-revision.json: " + "; ".join(problems), file=sys.stderr)
        sys.exit(1)
    PY

    if [ -n "$(ls -A "$HOME")" ]; then
      echo "HOME is no longer empty: $(ls -A "$HOME")" >&2
      exit 1
    fi
    touch "$out"
  ''
