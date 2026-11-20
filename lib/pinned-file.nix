# A repository file copied into the store only if its content hashes to the pin.
# builtins.path with a sha256 reuses an existing store path of that hash without
# reading the file again, so an edited file would still build against the old
# copy; hashing the file itself here makes the pin hold for the file on disk.
# `sha256` is the base16 digest.
{
  path,
  name,
  sha256,
}:
let
  actual = builtins.hashFile "sha256" path;
in
assert
  actual == sha256 || throw "${toString path} hashes to sha256 ${actual}, but the pin is ${sha256}";
builtins.path {
  inherit path name;
  recursive = false;
}
