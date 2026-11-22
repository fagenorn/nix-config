# The platform package (ADR-system-005): the agent_tools package (python/) in one
# interpreter environment with a build-time import of every module, one isolated
# launcher per command-table row, the standards directory and the platform
# manifest. `commands` is still the one command-to-module authority (#175 D4, D11;
# parent D2, D10, D13):
# `agent_tools.delivery.engine_commands.PLATFORM_MODULES` mirrors the rows of the commands an
# engine procedure may run, and tests/test_engine_commands.py pins the mirror to these rows.
# The revision record is the flake revision a project's lock pins (adoption's lock entry).
{ pkgs, revision }:
let
  inherit (pkgs) lib;
  python = pkgs.python3;
  source = ../python;
  sourceRoot = toString source;
  project = (lib.importTOML (source + "/pyproject.toml")).project;

  # Every .py file under agent_tools as a dotted module name; an __init__.py
  # names its package. Walking the tree means a new module is import-checked
  # without anyone editing a list.
  moduleOf =
    file:
    lib.removeSuffix ".__init__" (
      lib.replaceStrings [ "/" ] [ "." ] (lib.removeSuffix ".py" (lib.removePrefix "${sourceRoot}/" file))
    );
  modules = map moduleOf (
    lib.filter (lib.hasSuffix ".py") (
      map toString (lib.filesystem.listFilesRecursive (source + "/agent_tools"))
    )
  );

  pythonPackage = python.pkgs.buildPythonPackage {
    pname = project.name;
    inherit (project) version;
    pyproject = true;
    src = source;
    build-system = [ python.pkgs.setuptools ];
    pythonImportsCheck = modules;
  };

  env = python.withPackages (_: [ pythonPackage ]);

  # A row maps a command to its module path under agent_tools, and the module is named for the command:
  # its last segment is the command with each "-" replaced by "_".
  # context-map-lint is a stable path other projects' CIs call without vendoring it (parent D15).
  commands = {
    "adopt-project" = "project_contract.adopt_project";
    "adr-number" = "delivery.adr_number";
    "agent-model-matrix" = "agent_model_matrix";
    "artifact-budget" = "delivery.artifact_budget";
    "bypass-proof" = "console.bypass_proof";
    "cache-proxy" = "hosts.cache_proxy";
    "conformance" = "project_contract.conformance";
    "console" = "console.console";
    "context-map-lint" = "delivery.context_map_lint";
    "diff-scope" = "delivery.diff_scope";
    "engine" = "delivery.engine";
    "fallback-audit" = "project_contract.fallback_audit";
    "fleet-preflight" = "project_contract.fleet_preflight";
    "folder-trust" = "console.folder_trust";
    "forge-claim" = "claims.forge_claim";
    "forge-issue" = "claims.forge_issue";
    "guard-policy" = "guard.guard_policy";
    "host-readiness" = "project_contract.host_readiness";
    "issue-branch" = "delivery.issue_branch";
    "look-approval" = "delivery.look_approval";
    "look-lint" = "delivery.look_lint";
    "owner-actions" = "claims.owner_actions";
    "plan-amend" = "delivery.plan_amend";
    "program-copies" = "delivery.program_copies";
    "pr-green" = "verification.pr_green";
    "promotion" = "delivery.promotion";
    "release" = "release.release";
    "release-card" = "console.release_card";
    "resolve-project" = "project_contract.resolve_project";
    "skill-lint" = "skill_lint";
    "sprint" = "console.sprint";
    "standards-lint" = "delivery.standards_lint";
    "verified-tree" = "verification.verified_tree";
    "verify-pending" = "verification.verify_pending";
    "verify-slot" = "delivery.verify_slot";
  };

  # -I drops every PYTHON* variable, the working directory and the user site.
  # nixpkgs' sitecustomize still reads the NIX_PYTHON* variables under -I, and
  # this environment's python3 sets none of them, so the launcher clears them.
  # The shebang is bash under `-p`, which ignores BASH_ENV and the functions an
  # environment exports, so neither can run in place of the launcher's lines
  # (issue 377, where the lifecycle guard's row check execs the guard-policy
  # launcher). The root export points resolve-project at the package's own
  # manifest, so no home configuration is read (#1439).
  # A row whose module does not exist fails evaluation rather than building a
  # launcher that can only fail at run time (D14).
  checkedModule =
    name: path:
    let
      module = "agent_tools.${path}";
    in
    assert lib.assertMsg (lib.elem module modules)
      "agent-tools: command ${name} has no module ${module}";
    assert lib.assertMsg (
      lib.last (lib.splitString "." path) == lib.replaceStrings [ "-" ] [ "_" ] name
    ) "agent-tools: command ${name} runs ${module}, which is not named for it";
    module;

  writeLauncher =
    name: path:
    let
      module = checkedModule name path;
    in
    ''
      cat > "$out/bin/${name}" <<EOF
      #!${pkgs.runtimeShell} -p
      unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE
      export AGENT_PLATFORM_ROOT=$out/share/agent-platform
      exec ${env}/bin/python3 -I -m ${module} "\$@"
      EOF
      chmod 0555 "$out/bin/${name}"
      ${pkgs.stdenv.shellDryRun} "$out/bin/${name}"
    '';

  revisionRecord = pkgs.writeText "platform-revision.json" (
    builtins.toJSON (
      {
        schema_version = 1;
        type = "github";
      }
      // revision
    )
  );

  package =
    pkgs.runCommand "agent-platform"
      {
        passthru = {
          launchers = lib.mapAttrs (name: _: "${package}/bin/${name}") commands;
          inherit python;
        };
      }
      ''
        mkdir -p "$out/bin" "$out/share/agent-platform"
        cp ${../home/common/agent-skills/platform-manifest.json} "$out/share/agent-platform/platform-manifest.json"
        cp ${revisionRecord} "$out/share/agent-platform/platform-revision.json"
        cp -R ${../home/common/agent-skills/standards} "$out/share/agent-platform/standards"
        chmod -R u+w "$out/share/agent-platform"
        ${lib.concatStrings (lib.mapAttrsToList writeLauncher commands)}
      '';
in
package
