# Geist Serif from upstream geist-font. The pinned nixpkgs `geist-font` predates
# Serif. Only the four static TTFs are installed, each named, so a missing or
# renamed upstream variant fails the build (issue 486 D3).
{ pkgs }:
pkgs.stdenvNoCC.mkDerivation rec {
  pname = "geist-serif";
  version = "1.9.0";

  # A bump edits `version` and `hash` together.
  src = pkgs.fetchurl {
    url = "https://github.com/vercel/geist-font/releases/download/v${version}/geist-font-v${version}.zip";
    hash = "sha256-Hy3Z6pDmjQNYodI0pfFWgHssPg4pXXjYeYCm260fpYw=";
  };

  nativeBuildInputs = [ pkgs.unzip ];

  dontUnpack = true;

  installPhase = ''
    runHook preInstall
    mkdir -p "$out/share/fonts/truetype"
    unzip -j "$src" \
      geist-font/GeistSerif/ttf/GeistSerif-Regular.ttf \
      geist-font/GeistSerif/ttf/GeistSerif-Square.ttf \
      geist-font/GeistSerif/ttf/GeistSerif-Triangle.ttf \
      geist-font/GeistSerif/ttf/GeistSerif-Heart.ttf \
      -d "$out/share/fonts/truetype"
    runHook postInstall
  '';

  meta = {
    description = "Geist Serif typeface by Vercel, static Regular, Square, Triangle and Heart variants";
    homepage = "https://vercel.com/font";
    license = pkgs.lib.licenses.ofl;
    platforms = pkgs.lib.platforms.all;
  };
}
