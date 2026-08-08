When devenv.nix doesn't exist and a command/tool is missing, create ad-hoc environment:

    $ devenv -O languages.rust.enable:bool true -O packages:pkgs "mypackage mypackage2" shell -- cli args

When the setup becomes complex create `devenv.nix` and run commands within:

    $ devenv shell -- cli args

See https://devenv.sh/ad-hoc-developer-environments/

Before starting a task, check the available-skills listing for a match; if a
skill plausibly applies, invoke it via the Skill tool before acting. Skills
evolve — read the current version instead of working from memory.
