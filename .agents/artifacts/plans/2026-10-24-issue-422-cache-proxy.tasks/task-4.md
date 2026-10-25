# Task 4: Port binding, wrapper substitution and both services

Spec § Service, § Wrapper routing (the build-time URL), § claude-local and § Docs, per D5, D9, D10, D11, D12, D13 and D17. `home/common/claude-code/default.nix` gains the port's one home, rewrites the launcher's `CACHE_PROXY_URL`, and declares the launchd agent (darwin) and the systemd user unit (anis-desktop); the claude-code README documents them.

**Files:**
- Modify: `home/common/claude-code/default.nix`
- Modify: `home/common/claude-code/README.md`

**Interfaces:**
- Consumes (Task 2): `agentTools.launchers.cache-proxy` (store path `<hash>-agent-tools-cache-proxy`, accepting `--port N`). Consumes (Task 3): the single `CACHE_PROXY_URL=` line in `accounts/bin/claude-account`. Consumes (Task 1): `Tool-search switch:` in `docs/spikes/cache-proxy-spike.md` (README wording only).
- Produces (Task 5 runs them from `./result`): the plist store path `<hash>-org.nix-community.home.claude-cache-proxy.plist` (home-manager's default label; its `ProgramArguments` become `/bin/sh -c "/bin/wait4path /nix/store && exec <launcher> --port 27183"`, the arguments unquoted because they hold no shell-special character), the built `claude-accounts-mod` whose `bin/claude-account` holds `CACHE_PROXY_URL=http://127.0.0.1:27183`, and the built `claude-code-with-accounts-<version>/bin/claude`.

**Invariants:**
- `27183` appears once in `default.nix`, in `cacheProxyPort`; the URL and the service arguments derive from it (D5, D9).
- The darwin agent and the Linux unit are each gated by platform (`lib.mkIf pkgs.stdenv.isDarwin` / `isLinux`), so neither platform evaluates the other's assertion.
- Both run the launcher store path with `--port 27183` and `SSL_CERT_FILE=${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt`.
- Nothing activates: no `just switch` (D14).

- [ ] **Step 1: Write the failing checks**

Save as `<scratch>/i422/nix-check.sh` (scratch from `launch-scope scratch …`):

```bash
#!/usr/bin/env bash
# Task 4's declared-service check: both darwin agents and the anis-desktop unit (#422 D17).
set -euo pipefail
nixe() { nix eval --extra-experimental-features 'nix-command flakes' --json "$1"; }
for host in mbp eleven-m5; do
  nixe ".#darwinConfigurations.$host.config.home-manager.users.anis.launchd.agents.claude-cache-proxy.config" |
    jq -e '(.ProgramArguments | length == 3 and (.[0] | endswith("-agent-tools-cache-proxy"))
              and .[1:] == ["--port", "27183"])
           and .RunAtLoad == true and .KeepAlive == true
           and (.EnvironmentVariables.SSL_CERT_FILE | endswith("/etc/ssl/certs/ca-bundle.crt"))
           and (.StandardErrorPath | endswith("/Library/Logs/claude-cache-proxy.log"))
           and .StandardOutPath == .StandardErrorPath' >/dev/null
done
nixe '.#nixosConfigurations.anis-desktop.config.home-manager.users.anis.systemd.user.services.claude-cache-proxy' |
  jq -e '([.Service.ExecStart] | flatten | .[0] | test("-agent-tools-cache-proxy --port 27183$"))
         and ([.Service.Restart] | flatten) == ["always"]
         and ([.Install.WantedBy] | flatten) == ["default.target"]
         and ([.Service.Environment] | flatten
              | any(startswith("SSL_CERT_FILE=") and endswith("/etc/ssl/certs/ca-bundle.crt")))' >/dev/null
if nixe '.#nixosConfigurations.anis-desktop.config.home-manager.users.anis.launchd.agents' |
  jq -e 'has("claude-cache-proxy")' >/dev/null; then exit 1; fi
test "$(grep -c '27183' home/common/claude-code/default.nix)" -eq 1
echo services-declared
```

Run (timeout 600 s): `bash <scratch>/i422/nix-check.sh`
Expected: FAIL — `nix eval` reports that attribute `claude-cache-proxy` is missing.

- [ ] **Step 2: Add the binding, the substitution and the services**

In the `let` block of `home/common/claude-code/default.nix`, directly above the `accountsMod` comment, add:

```nix
  # The cache proxy (agent_tools.cache_proxy, #422). This port is its one home:
  # the service below listens on it and the launcher's CACHE_PROXY_URL is
  # rewritten to it, so `claude` routes through the proxy while it is healthy.
  cacheProxyPort = 27183;
  cacheProxyUrl = "http://127.0.0.1:${toString cacheProxyPort}";
  cacheProxyArgs = [
    "${agentTools.launchers.cache-proxy}"
    "--port"
    (toString cacheProxyPort)
  ];
  # launchd and systemd start services with a minimal environment, so upstream
  # TLS verification is pinned to the nixpkgs CA bundle.
  cacheProxyCaFile = "${pkgs.cacert}/etc/ssl/certs/ca-bundle.crt";
```

In `accountsMod`, add `--replace-fail 'CACHE_PROXY_URL=' 'CACHE_PROXY_URL=${cacheProxyUrl}'` as the last `substituteInPlace` argument (after the `DEFAULT_CLAUDE_BIN=` line), and extend the comment above `accountsMod` so its last sentence reads: `The launcher's tools are rewritten to store paths rather than prefixed onto PATH, which the claude it execs would inherit, and its CACHE_PROXY_URL to the cache proxy's URL.`

In the module body, after the `home.packages` list, add:

```nix
  # The cache proxy as a user service on each platform (#422); README § Cache proxy.
  launchd.agents.claude-cache-proxy = lib.mkIf pkgs.stdenv.isDarwin {
    enable = true;
    config = {
      ProgramArguments = cacheProxyArgs;
      EnvironmentVariables.SSL_CERT_FILE = cacheProxyCaFile;
      RunAtLoad = true;
      KeepAlive = true;
      StandardOutPath = "${config.home.homeDirectory}/Library/Logs/claude-cache-proxy.log";
      StandardErrorPath = "${config.home.homeDirectory}/Library/Logs/claude-cache-proxy.log";
    };
  };

  systemd.user.services.claude-cache-proxy = lib.mkIf pkgs.stdenv.isLinux {
    Unit.Description = "Claude Code cache proxy (pass-through to the Anthropic API)";
    Service = {
      ExecStart = lib.concatStringsSep " " cacheProxyArgs;
      Environment = [ "SSL_CERT_FILE=${cacheProxyCaFile}" ];
      Restart = "always";
    };
    Install.WantedBy = [ "default.target" ];
  };
```

- [ ] **Step 3: Document it**

In `home/common/claude-code/README.md` § Accounts, the clause `rewriting the launcher's \`jq\`, \`git\`, \`curl\` and real-\`claude\` paths` becomes `rewriting the launcher's \`jq\`, \`git\`, \`curl\` and real-\`claude\` paths and its cache-proxy URL`. Add a new section after § Accounts (before `## Editing the codex-plugin-cc patch`):

```markdown
## Cache proxy

`claude` reaches the Anthropic API through `cache-proxy` (`python/README.md` § `cache-proxy`) while the proxy is healthy. It forwards requests unchanged today; request reshaping is the follow-up to #422, and the spike behind it is `docs/spikes/cache-proxy-spike.md`. `default.nix` holds the port, `27183`, in one binding: it runs the `cache-proxy` launcher with `--port 27183` and `SSL_CERT_FILE` set to the nixpkgs CA bundle as the launchd agent `claude-cache-proxy` on darwin (`RunAtLoad`, `KeepAlive`; stdout and stderr append to `~/Library/Logs/claude-cache-proxy.log`, which nothing rotates) and as the systemd user unit `claude-cache-proxy` on anis-desktop (`Restart=always`, `WantedBy=default.target`; its log is the journal), and it writes `http://127.0.0.1:27183` into the launcher's `CACHE_PROXY_URL`. The service starts at activation (`just switch`); until something answers on the port, every launch goes direct.

Before every launch (the early exec for a caller-chosen `CLAUDE_CONFIG_DIR`, the first launch and each `/account` relaunch) `claude-account run` leaves alone an `ANTHROPIC_BASE_URL` set to anything but the proxy URL, since that is the caller's own endpoint. Otherwise it probes `GET /_proxy/health` with a 0.5 s limit: an answer naming `"service":"cache-proxy"` exports the proxy URL TOOL_SEARCH_CLAUSE, and anything else unsets `ANTHROPIC_BASE_URL`, so the launch goes direct and a dead proxy costs at most half a second. The probe runs only at launch: a session keeps the route it started with, and if the proxy dies mid-session the service manager restarts it while Claude Code retries. A routed session has no Remote Control, which Claude Code turns off behind a non-first-party base URL. `ANTHROPIC_BASE_URL=https://api.anthropic.com claude` goes direct for one launch. `claude-local` is never routed: it execs the pinned binary itself and exports its own `ANTHROPIC_BASE_URL`.LOCAL_CLAUSE
```

Replace the two markers by the spike's `Tool-search switch:` value. On `ship`: `TOOL_SEARCH_CLAUSE` becomes `and \`ENABLE_TOOL_SEARCH=true\` unless the caller set that variable (before 2.1.304 Claude Code turns tool search off behind a non-first-party base URL, and the pin is older)`, and `LOCAL_CLAUSE` becomes ` One started inside a routed session inherits \`ENABLE_TOOL_SEARCH=true\`; from 2.1.304 on, tool search is the default behind any gateway regardless.` On `drop`: both markers become the empty string (and the space before `TOOL_SEARCH_CLAUSE` goes with it).

- [ ] **Step 4: Verify**

Run (timeout 600 s): `bash <scratch>/i422/nix-check.sh` — expected `services-declared`.

Run (timeout 3600 s): `just build mbp`, then (timeout 60 s):

```bash
set -euo pipefail
q() { nix-store --query --requisites ./result | grep -- "$1" || true; }
set -- $(q '-claude-accounts-mod$'); test "$#" -eq 1
grep -qx 'CACHE_PROXY_URL=http://127.0.0.1:27183' "$1/bin/claude-account"
set -- $(q '-org.nix-community.home.claude-cache-proxy.plist$'); test "$#" -eq 1
test "$(plutil -extract KeepAlive raw "$1")" = true
plutil -extract ProgramArguments.2 raw "$1" | grep -Eq -- '-agent-tools-cache-proxy --port 27183$'
if grep -nE 'TOOL_SEARCH_CLAUSE|LOCAL_CLAUSE' home/common/claude-code/README.md; then exit 1; fi
grep -q '^## Cache proxy$' home/common/claude-code/README.md
echo built-ok
```

Expected: `built-ok`. At the starting commit the store queries find no `claude-cache-proxy` plist. The anis-desktop toplevel evaluation is CI's `Nix Eval` on the PR, because on mbp it needs an x86_64-linux builder (D17).

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/default.nix home/common/claude-code/README.md
git commit -m "feat(claude-code): cache-proxy service and wrapper URL (#422)"
```
