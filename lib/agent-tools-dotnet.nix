# The .NET solution under dotnet/ (ADR-system-007). `package` builds every production project
# and is the agent-tools executable; `tests` builds them again with the *.Tests projects and
# runs those. Both restore from the one NuGet lock dotnet/deps.json. The package's source
# leaves out every *.Tests directory, the solution file and the lock, so a test edit does not
# rebuild it.
{ pkgs }:
let
  inherit (pkgs) lib;
  fs = lib.fileset;
  solution = ../dotnet;
  lock = solution + "/deps.json";
  platforms = [ "x86_64-linux" "aarch64-darwin" ];
  directories = lib.attrNames (lib.filterAttrs (_: type: type == "directory") (builtins.readDir solution));
  testNames = lib.filter (lib.hasSuffix ".Tests") directories;
  productionNames = lib.filter (name: !lib.hasSuffix ".Tests" name) directories;
  projectFiles = prefix: map (name: "${prefix}${name}/${name}.csproj");
  common = {
    version = "0.1.0";
    nugetDeps = lock;
    dotnet-sdk = pkgs.dotnet-sdk_10;
    dotnet-runtime = pkgs.dotnet-runtime_10;
  };
in
{
  package = pkgs.buildDotnetModule (common // {
    pname = "agent-tools-dotnet";
    src = fs.toSource {
      root = solution;
      fileset = fs.difference solution (fs.unions (
        map (name: solution + "/${name}") testNames ++ [ (solution + "/AgentTools.slnx") lock ]
      ));
    };
    projectFile = projectFiles "" productionNames;
    executables = [ "agent-tools" ];
    meta = { inherit platforms; mainProgram = "agent-tools"; };
  });
  tests = pkgs.buildDotnetModule (common // {
    pname = "agent-tools-dotnet-tests";
    src = fs.toSource { root = ../.; fileset = fs.unions [ solution ../docs/guides/architecture.md ]; };
    projectFile = projectFiles "dotnet/" productionNames;
    testProjectFile = projectFiles "dotnet/" testNames;
    doCheck = true;
    # VSTest's runner and test host talk over a loopback socket, which a sandboxed darwin build refuses.
    __darwinAllowLocalNetworking = true;
    dontDotnetFixup = true;
    installPhase = ''
      runHook preInstall
      mkdir -p "$out"
      runHook postInstall
    '';
    meta = { inherit platforms; };
  });
}
