# eleven-m5 inference settings

`omlx.nix` owns model aliases/defaults, selected performance settings, and the
patches required by the Homebrew oMLX installation. `omlx-configure` is generated
as a user command and called by system activation. It checks every patch before
applying any, recursively merges owned settings, preserves unrelated UI settings
and server secrets, and writes one reason line to `.omlx/.restart-needed` for each
change the server reads only at start: an applied patch, a changed declared key or a
created file. It prints the reasons as `restart_reasons`.
It also removes the preset directories an earlier version created (each marked by a
`.omlx-*-preset` file) and lists them as `removed_presets`; it refuses one that holds
anything but symlinks and JSON files.
Incompatible patches fail activation. It leaves the entries of undeclared models
untouched. When the admin UI makes an undeclared model (or the JarBird model) the
default, the declared default yields to it so there stays one default, and returns
at the next activation after that default is cleared.

`omlx-restart` restarts the server only while it is idle or stopped. While `/health`
reports a loaded model, a preload or an answer it cannot read, it prints the
`oMLX: restart deferred (...)` line and keeps the marker; `omlx-restart --now`
applies it regardless. Activation and the downloader both go through it, never
through a kill of their own. While a restart is deferred, an admin-UI save can
overwrite the declared change in the files; the next activation writes it again.
Applying `omlx-configure` alone does not restart active work.

The JarBird model `GLM-5.3-Flash-Abliterated-MLX-4bit`, installed by oMLX's admin
downloader under `models/grant-ai/`, is pinned so it loads at start and is never
evicted, and the memory guard is `custom` at a 192 GB ceiling, because the pinned
182 GB model did not fit under the dynamic ceiling (175.66 GB). Both are declared in
`omlx.nix`.

## What else an activation restarts

nix-darwin reloads every launchd daemon whose plist changed, so an activation
restarts oMLX outside the gate whenever its serve script changes. That script
embeds the store path of `secrets/secrets.yaml`, so any secrets edit does it. The
same holds for `omlx-models`, `iogpu-wired-limit` (which re-runs the sysctl),
`colima` and `docker-socket`, the GitHub runners, and the owner's `agent-console`,
`verify-pending`, `claude-cache-proxy` and `sops-nix` daemons when their plists
change. Homebrew's `onActivation.upgrade` can replace the oMLX install; the running
server keeps its loaded code, and the re-applied patches become a deferred restart.

The Anthropic patch accepts Claude Code's `output_config.effort` and preserves
valid explicit `chat_template_kwargs.reasoning_effort`. Qwen4-exp templates
receive low→low, medium→medium, and unsupported high/max→xhigh. An advertised
high alias remains valid. Other model families receive their original tier.
Unknown API effort strings and invalid
effective Qwen template overrides fail explicitly. Omitted or null effort uses
the model setting. Forced model keys retain precedence, as do Anthropic thinking
controls over unforced enable_thinking values.

Both served Qwen3.8 variants default to medium effort and a 4096-token thinking
budget. This bounds routine reasoning while preserving an explicit request's
`thinking.budget_tokens` override. Disabled thinking stays disabled even when the
default budget is attached to generation parameters. GLM's reasoning settings
are not changed. A budget is a reasoning-token bound, not a latency guarantee.

## Retiring a model

Deleting a `models` entry stops its download and its declared settings, but leaves
its weights on the host: delete `~/.omlx/models/<directory>` (the repository name
after the slash, or the admin UI's directory) by hand, then apply the change with
`omlx-restart --now` when the server may pause. Its entry in `model_settings.json`
is left as the admin UI keeps it.

Run `nix build --no-link .#checks.aarch64-darwin.omlx-adapter` for the portable
adapter/configuration tests, then `just build eleven-m5` for the host. The restart
gate and the declaration (the pin, the memory guard and the restart wiring) are
covered by `tests/test_omlx_restart.py` and `tests/test_omlx_declaration.py` in
Agent Workflow Tests. CI builds
the corresponding x86_64-linux check as part of the required Nix Eval job. The
check uses the pinned oMLX flake input and immutable real Qwen template, parsing
the real schema and executing the real Anthropic endpoint to engine preflight.
GPU inference is covered separately by deployed Claude-shaped smoke requests.

After a Homebrew update, incompatible patches require checking upstream before
regenerating or removing them. The GLM fix tracks upstream PR4644; the effort
patch is the local compatibility change for nix-config issue410.
