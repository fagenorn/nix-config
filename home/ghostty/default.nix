{...}: {
  programs.ghostty = {
    settings = {
      theme = "dark:catppuccin-frappe";
      window-title-font-family = "Fira Code Medium";
      macos-option-as-alt = true;
      macos-window-shadow = false;
      macos-auto-secure-input = true;
      macos-secure-input-indication = true;
      macos-titlebar-style = tabs;
      macos-non-native-fullscreen = true;

      keybind = "global:cmd+shift+f=toggle_fullscreen";
      keybind = "global:f11=toggle_quick_terminal";

      background-opacity = 0.93
    };
  };
}
