# The agent_tools package (python/): one interpreter environment, a build-time
# import of every module, and one isolated launcher per command-table row.
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

  # A command's module is its name with each "-" replaced by "_".
  commands = [ "agent-evidence" ];

  # -I drops every PYTHON* variable, the working directory and the user site.
  # nixpkgs' sitecustomize still reads the NIX_PYTHON* variables under -I, and
  # this environment's python3 sets none of them, so the launcher clears them.
  # A row whose module does not exist fails evaluation rather than building a
  # launcher that can only fail at run time (D14).
  launcher =
    name:
    let
      module = "agent_tools.${lib.replaceStrings [ "-" ] [ "_" ] name}";
    in
    assert lib.assertMsg (lib.elem module modules) "agent-tools: command ${name} has no module ${module}";
    pkgs.writeShellScript "agent-tools-${name}" ''
      unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE
      exec ${env}/bin/python3 -I -m ${module} "$@"
    '';
in
{
  launchers = lib.genAttrs commands launcher;
}
