{ pkgs, ... }:
{

  # GitHub
  programs.gh = {
    enable = true;

    settings = {
      git_protocol = "ssh";
      prompt = "enabled";
    };

    extensions = [ ];
  };

  programs.gh-dash.enable = true;
}
