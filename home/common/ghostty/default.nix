{ lib, pkgs, ... }: {
  programs.ghostty = {
    settings = {
      theme = "dark:catppuccin-frappe";
      window-title-font-family = "Fira Code Medium";
    background-opacity = 0.93;
    } lib.mkIf pkgs.stdenv.isDarwin {

      macos-option-as-alt = true;
      macos-window-shadow = false;
      macos-auto-secure-input = true;
      macos-secure-input-indication = true;
      macos-titlebar-style = "tabs";
      macos-non-native-fullscreen = true;
    };
  };
}
