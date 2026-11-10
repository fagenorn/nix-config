# The agent_tools package (python/): one interpreter environment, a build-time
# import of every module and one isolated launcher per command-table row.
# `commands` is the only command-to-module mapping (#175 D4, D11; parent D2,
# D10, D13).
{ pkgs }:
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

  package = python.pkgs.buildPythonPackage {
    pname = project.name;
    inherit (project) version;
    pyproject = true;
    src = source;
    build-system = [ python.pkgs.setuptools ];
    pythonImportsCheck = modules;
  };

  env = python.withPackages (_: [ package ]);

  # A row maps a command to its module path under agent_tools, and the module is named for the command:
  # its last segment is the command with each "-" replaced by "_".
  # context-map-lint is a stable path other projects' CIs call without vendoring it (parent D15).
  commands = {
    "adopt-project" = "project_contract.adopt_project";
    "agent-model-matrix" = "agent_model_matrix";
    "artifact-budget" = "artifact_budget";
    "cache-proxy" = "hosts.cache_proxy";
    "conformance" = "project_contract.conformance";
    "context-map-lint" = "context_map_lint";
    "diff-scope" = "diff_scope";
    "fallback-audit" = "project_contract.fallback_audit";
    "forge-claim" = "claims.forge_claim";
    "forge-issue" = "claims.forge_issue";
    "guard-policy" = "guard.guard_policy";
    "issue-branch" = "issue_branch";
    "lane-triage" = "lane_triage";
    "owner-actions" = "claims.owner_actions";
    "promotion" = "promotion";
    "release" = "release.release";
    "resolve-project" = "project_contract.resolve_project";
    "skill-lint" = "skill_lint";
    "verified-tree" = "verification.verified_tree";
    "verify-pending" = "verification.verify_pending";
  };

  # A launcher script: bash under `-p`, which ignores BASH_ENV and the functions
  # an environment exports, so neither can run in place of its two lines (issue
  # 377, where the lifecycle guard's row check execs the guard-policy launcher).
  launcherScript =
    name: text:
    pkgs.writeTextFile {
      name = "agent-tools-${name}";
      executable = true;
      text = ''
        #!${pkgs.runtimeShell} -p
        ${text}
      '';
      checkPhase = ''
        ${pkgs.stdenv.shellDryRun} "$target"
      '';
    };

  # -I drops every PYTHON* variable, the working directory and the user site.
  # nixpkgs' sitecustomize still reads the NIX_PYTHON* variables under -I, and
  # this environment's python3 sets none of them, so the launcher clears them.
  # A row whose module does not exist fails evaluation rather than building a
  # launcher that can only fail at run time (D14).
  launcher =
    name: path:
    let
      module = "agent_tools.${path}";
    in
    assert lib.assertMsg (lib.elem module modules)
      "agent-tools: command ${name} has no module ${module}";
    assert lib.assertMsg (
      lib.last (lib.splitString "." path) == lib.replaceStrings [ "-" ] [ "_" ] name
    ) "agent-tools: command ${name} runs ${module}, which is not named for it";
    launcherScript name ''
      unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE
      exec ${env}/bin/python3 -I -m ${module} "$@"'';
in
{
  launchers = lib.mapAttrs launcher commands;
}
