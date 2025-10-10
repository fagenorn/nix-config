{
  inputs,
  outputs,
  stateVersion,
  myvars,
  ...
}:
let
  helpers = import ./helpers.nix {
    inherit
      inputs
      outputs
      stateVersion
      myvars
      ;
  };
in
{
  inherit (helpers)
    mkDarwin
    scanPaths
    mergeFilesOrdered
    mkNixos
    ;
}
