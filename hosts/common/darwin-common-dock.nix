{ config, ... }:
{
  system.defaults.dock = {
    persistent-apps = [
      "/Applications/Edge.app"
      "/Applications/Whatsapp.app"
      "/Applications/Discord.app"
      "/Applications/Slack.app"
      "/Applications/Fantastical.app"
      "/Applications/Visual Studio Code.app"
      "/Applications/Spotify.app"
      "/Applications/Ghostty.app"
    ];
  };
}
