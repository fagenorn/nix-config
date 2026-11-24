"""Each host's configuration, evaluated once per checkout content and read by name (issue 1289).

A test that reads a host configuration reads a named part with `host_readings.read(host, part)`,
in `setUpClass`, and never runs a `nix eval` of its own. A new attribute is a new entry in `PARTS`.
Call `read` qualified (never `from .host_readings import read`), so one patch sees every read.

One registry. Every attribute a test reads is a `Part`: a Nix function `c: u: ...` of the host's
`config` and the user's home-manager config `u`, the hosts it applies to, and what this machine
must offer to evaluate it (`needs`: `darwin-machine` or `x86_64-linux-builder`).

One evaluation per host. `reading(host)` evaluates every part of the host this machine can, in one
`nix eval --json` over `<root>#<output>.config`, and returns `{part: value}`. A darwin host is
evaluated with `allow-import-from-derivation false` unless a selected part needs a darwin machine,
so the shared parts prove they need no build of another system wherever that part is absent (the
required CI job runs on Linux); on a darwin machine the activation parts join the evaluation and
allow it. anis-desktop is never pure, and its `console` part joins only where nix can build
x86_64-linux.

The cache is on disk, because the suite runs its members as separate processes. There is no
in-process memo: each read looks its entry up under the host's `flock`, so concurrent readers of
one host make one evaluation. The entry is `<cache>/<host>-<key>.json`, one per host (a newer
entry replaces the older), and the lock is `<cache>/<host>.lock`. `<cache>` is
`<git rev-parse --absolute-git-dir>/host-readings` (per worktree, never tracked, never under
HOME), or the non-empty `HOST_READINGS_CACHE`.

The key is the sha256 of the host, its output, its purity, the selected parts (each apply text
resolved against the requested root), `nix --version` and the checkout's tree. The tree is
`verified_tree.current_tree`: the index's entries with tracked working-tree edits and deletions
applied, untracked files excluded, as a Git-backed nix build sees it. The key is the tree and not
the commit, because the configurations set `system.configurationRevision` from `self.rev or
self.dirtyRev`: an answer may carry store paths built for an earlier commit with the same tree.
A part must not read a commit id or an exact store hash; match store paths by pattern.

A failed evaluation is never stored, and fails every reader of the host with the evaluation's
stderr tail. A cache whose directory or lock cannot be made, or in which the miss's temporary
output cannot be reserved (made under the lock, before the evaluation), fails the read with an
AssertionError naming the cache before anything is evaluated, and a publish that fails after an
evaluation fails it the same way without evaluating again, so an unusable cache never becomes one
evaluation per process. Only `<host>-<sha256>.json` entries are replaced; any other file in the
cache stays. An unreadable or mismatched entry is a miss. The tree is read under the lock, so an
edit made while a reader waited gives a fresh key, and again after the evaluation, and when it
changed the read fails and nothing is published: the key names the tree that was evaluated. An
edit made and undone within one evaluation is not detected.

Every nix child runs with the environment from before the accounts sandbox (#1286).
"""
import fcntl
import hashlib
import json
import os
import platform
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

try:
    from . import accounts_sandbox
except ImportError:  # run directly: no parent package, and tests/ is sys.path[0]
    import accounts_sandbox
from agent_tools.verification import verified_tree

ROOT = Path(__file__).resolve().parents[1]
EVAL_TIMEOUT = 1200
NIX = ["nix", "--extra-experimental-features", "nix-command flakes", "eval"]
NO_IFD = ["--option", "allow-import-from-derivation", "false"]
CACHE_ENV = "HOST_READINGS_CACHE"
NIX_CONFIG = ["nix", "--extra-experimental-features", "nix-command flakes", "config", "show", "--json"]

HOSTS: dict[str, str] = {
    "anis-desktop": "nixosConfigurations",
    "mbp": "darwinConfigurations",
    "eleven-m5": "darwinConfigurations",
}
DARWIN_HOSTS = ("mbp", "eleven-m5")
ALL_HOSTS = ("anis-desktop", *DARWIN_HOSTS)


def output(host: str) -> str:
    return f"{HOSTS[host]}.{host}"


@dataclass(frozen=True)
class Part:
    """`apply` is Nix text, or a function of the checkout root that returns it."""

    apply: str | Callable[[Path], str]
    hosts: tuple[str, ...]
    needs: str | None = None


def applied(part: Part, root: Path) -> str:
    return part.apply(root) if callable(part.apply) else part.apply


def recipe_apply(root: Path) -> str:
    """The one `--apply` expression of the `register-runners` recipe of `<root>/justfile`."""
    text = (root / "justfile").read_text(encoding="utf-8")
    match = re.search(r"^register-runners ([^\n]*):\n((?:  [^\n]*\n)+)", text, re.M)
    if match is None:
        raise AssertionError(f"no register-runners recipe in {root / 'justfile'}")
    found = re.findall(r"--apply '([^']*)'", match.group(2))
    if len(found) != 1:
        raise AssertionError(f"expected one --apply expression in register-runners, found {len(found)}")
    return found[0]


def runner_triples_apply(root: Path) -> str:
    return f"c: u: ({recipe_apply(root)}) c.services.github-runners"


# What each host installs of the flake's platform package, read from the definitions of `home.file`
# (the host's own option, found through `inputs.self`) and not from the merged `home.file`: merging
# forces an import-from-derivation (catppuccin's starship definition) that a pure evaluation, and a
# Linux machine evaluating a darwin host, cannot do. Each entry is resolved the way home-manager
# resolves it (`enable` drops it, `target` defaults to the attribute name, `recursive` defaults to
# false, an absolute `target` under the home directory loses that prefix); a field or entry wrapped by `mkIf`/`mkForce` reads as `<kind>`, so it never equals a plain link.
AGENT_PLATFORM = """c: u: let
  system = c.nixpkgs.hostPlatform.system;
  inputs = c.home-manager.extraSpecialArgs.inputs;
  package = inputs.self.packages.${system}.agent-platform;
  commands = builtins.attrNames package.launchers;
  mine = builtins.filter (s: s.config.networking.hostName == c.networking.hostName)
    (builtins.attrValues inputs.self.darwinConfigurations ++ builtins.attrValues inputs.self.nixosConfigurations);
  definitions = (builtins.head mine).options.home-manager.users.valueMeta.attrs.${u.home.username}.configuration.options.home.file.definitionsWithLocations;
  wrapped = v: builtins.isAttrs v && v ? _type;
  home = "${u.home.homeDirectory}/";
  relative = t: if builtins.isString t && builtins.substring 0 (builtins.stringLength home) t == home
    then builtins.substring (builtins.stringLength home) (builtins.stringLength t) t else t;
  field = e: name: default: if !(e ? ${name}) then default else if wrapped e.${name} then "<${e.${name}._type}>" else e.${name};
  entries = builtins.concatMap (d: map (n: let e = d.value.${n}; in
    if wrapped e then { name = n; target = n; enable = "<${e._type}>"; recursive = null; source = "<${e._type}>"; }
    else {
      name = n;
      target = relative (field e "target" n);
      enable = field e "enable" true;
      recursive = field e "recursive" false;
      source = if e ? source && !(wrapped e.source) then "${e.source}" else null;
    }) (builtins.attrNames d.value)) definitions;
  under = p: n: builtins.substring 0 (builtins.stringLength p) n == p;
  installed = builtins.filter (e: e.enable != false && (e.target == ".agents" || under ".agents/" e.target)) entries;
  reachesBin = t: t == ".agents" || t == ".agents/bin" || under ".agents/bin/" t;
  at = path: let m = builtins.filter (e: e.target == path) installed;
    in if builtins.length m == 1 then builtins.removeAttrs (builtins.head m) [ "name" ] else m;
in {
  package = "${package}";
  inherit commands;
  launchers = builtins.mapAttrs (_: l: "${l}") package.launchers;
  bin = builtins.listToAttrs (map (n: { name = n; value = at ".agents/bin/${n}"; }) commands);
  binEntries = map (e: e.target) (builtins.filter (e: reachesBin e.target) installed);
  standards = at ".agents/standards";
  manifest = at ".agents/share/platform-manifest.json";
  python = "${package.python}";
  channelPython = "${(if system == "aarch64-darwin" then inputs.nixpkgs-darwin else inputs.nixpkgs).legacyPackages.${system}.python3}";
}"""

PARTS: dict[str, Part] = {
    "verify-pending": Part("""c: u: {
          command = u.verifyPending.command;
          label = u.verifyPending.label;
          kickScript = u.verifyPending.kick;
          start = u.verifyPending.start;
          probe = u.verifyPending.probe;
          kickText = u.verifyPending.kickText;
          service = u.systemd.user.services.verify-pending;
          timer = u.systemd.user.timers.verify-pending;
          paths = builtins.attrNames u.systemd.user.paths;
          kick = u.home.activation.verifyPendingKick;
        }""", ("anis-desktop",)),
    "verify-pending-darwin": Part("""c: u: {
          atBoot = c.ownerServices.atBoot;
          user = u.home.username;
          home = u.home.homeDirectory;
          command = u.verifyPending.command;
          label = u.verifyPending.label;
          kickScript = u.verifyPending.kick;
          start = u.verifyPending.start;
          probe = u.verifyPending.probe;
          kickText = u.verifyPending.kickText;
          homeKick = u.home.activation ? verifyPendingKick;
          agentCommand = if c.launchd.user.agents ? verify-pending then c.launchd.user.agents.verify-pending.command else null;
          daemonCommand = if c.launchd.daemons ? verify-pending then c.launchd.daemons.verify-pending.command else null;
          inUserAgents = c.environment.userLaunchAgents ? "org.nixos.verify-pending.plist";
          inDaemons = c.environment.launchDaemons ? "org.nixos.verify-pending.plist";
          plist = (c.environment.userLaunchAgents // c.environment.launchDaemons)."org.nixos.verify-pending.plist".text;
        }""", DARWIN_HOSTS),
    "verify-pending-activation": Part("""c: u: {
          user = u.home.username;
          kickScript = u.verifyPending.kick;
          post = c.system.activationScripts.postActivation.text;
          activate = c.system.activationScripts.script.text;
        }""", DARWIN_HOSTS, needs="darwin-machine"),
    "console": Part("""c: u: {
      command = u.agentConsole.command;
      launcher = "${c.home-manager.extraSpecialArgs.inputs.self.packages.${c.nixpkgs.hostPlatform.system}.agent-platform.launchers.console}";
      home = u.home.homeDirectory;
      path = u.agentConsole.path;
      gh = "${u.programs.gh.package}";
      profile = u.home.profileDirectory;
      system = map (p: p.pname or (builtins.parseDrvName p.name).name) c.environment.systemPackages;
      homePackages = map (p: p.name) u.home.packages;
      claude = u.programs.claude-code.package.name;
      agentBin = builtins.filter (n: n == ".agents/bin/sprint" || n == ".agents/bin/resolve-project") (builtins.attrNames u.home.file);
      service = u.systemd.user.services.agent-console;
    }""", ("anis-desktop",), needs="x86_64-linux-builder"),
    "console-darwin": Part("""c: u: {
      command = u.agentConsole.command;
      launcher = "${c.home-manager.extraSpecialArgs.inputs.self.packages.${c.nixpkgs.hostPlatform.system}.agent-platform.launchers.console}";
      path = u.agentConsole.path;
      home = u.home.homeDirectory;
      tailscaleClient = if c.services.tailscale.enable then "${c.services.tailscale.package}/bin/tailscale" else null;
      profile = u.home.profileDirectory;
      user = u.home.username;
      atBoot = c.ownerServices.atBoot;
      agentCommand = if c.launchd.user.agents ? agent-console then c.launchd.user.agents.agent-console.command else null;
      daemonCommand = if c.launchd.daemons ? agent-console then c.launchd.daemons.agent-console.command else null;
      inUserAgents = c.environment.userLaunchAgents ? "org.nixos.agent-console.plist";
      inDaemons = c.environment.launchDaemons ? "org.nixos.agent-console.plist";
      homeAgent = u.launchd.agents ? agent-console;
      plist = (c.environment.userLaunchAgents // c.environment.launchDaemons)."org.nixos.agent-console.plist".text;
    }""", DARWIN_HOSTS),
    "user-launchd": Part("""c: u: {
          text = c.system.activationScripts.userLaunchd.text;
          agents = builtins.attrNames c.environment.userLaunchAgents;
        }""", DARWIN_HOSTS),
    "zsh-init": Part("c: u: { init = u.programs.zsh.initContent; }", DARWIN_HOSTS),
    "sudo": Part("c: u: c.security.sudo.extraConfig", DARWIN_HOSTS),
    "runner-home": Part("c: u: c.users.users._github-runner.home", DARWIN_HOSTS),
    "system-packages": Part(
        "c: u: map (p: p.pname or (builtins.parseDrvName p.name).name) c.environment.systemPackages",
        ALL_HOSTS),
    "owner-services": Part("""c: u: {
      atBoot = c.ownerServices.atBoot;
      user = u.home.username; home = u.home.homeDirectory;
      homeAgents = builtins.filter (n: u.launchd.agents.${n}.enable) (builtins.attrNames u.launchd.agents);
      userAgents = builtins.attrNames c.launchd.user.agents;
      daemonPlists = builtins.attrNames c.environment.launchDaemons;
      proxyArgs = u.launchd.agents.claude-cache-proxy.config.ProgramArguments;
      proxyEnv = u.launchd.agents.claude-cache-proxy.config.EnvironmentVariables;
      sopsProgram = u.launchd.agents.sops-nix.config.Program;
      sopsEnv = u.launchd.agents.sops-nix.config.EnvironmentVariables;
      plists = builtins.mapAttrs (_: p: p.text) (builtins.intersectAttrs {
        "org.nixos.agent-console.plist" = 0; "org.nixos.verify-pending.plist" = 0;
        "org.nixos.claude-cache-proxy.plist" = 0; "org.nixos.sops-nix.plist" = 0; } c.environment.launchDaemons);
      sopsActivation = u.home.activation.sops-nix.data;
      pre = c.system.activationScripts.preActivation.text;
      launchdText = c.system.activationScripts.launchd.text;
    }""", DARWIN_HOSTS),
    "owner-activation": Part("""c: u: {
          pre = c.system.activationScripts.preActivation.text;
          activate = c.system.activationScripts.script.text;
        }""", ("eleven-m5",), needs="darwin-machine"),
    "runners": Part("""c: u: {
  runners = builtins.mapAttrs (n: r: {
    inherit (r) url tokenFile extraLabels ephemeral user group name enable;
    daemon = let s = c.launchd.daemons."github-runner-${n}".serviceConfig; in {
      inherit (s) UserName GroupName;
      SoftResourceLimits = s.SoftResourceLimits or null;
      HardResourceLimits = s.HardResourceLimits or null;
    };
  }) c.services.github-runners;
  account =
    let u = c.users.users."_github-runner-jarbird" or null; in
    if u == null then null else { inherit (u) uid gid home createHome; };
  accountGroup =
    let g = c.users.groups."_github-runner-jarbird" or null; in
    if g == null then null else { inherit (g) gid; };
  knownUsers = c.users.knownUsers;
  knownGroups = c.users.knownGroups;
  activation = c.system.activationScripts.launchd.text;
  checks = c.system.checks.text;
  trustedSettings = c.nix.settings.trusted-users or [ ];
  extraOptions = c.nix.extraOptions;
  postgres =
    if c.services ? postgresql then
      { inherit (c.services.postgresql) enable port; }
    else
      null;
}""", DARWIN_HOSTS),
    "runner-triples": Part(runner_triples_apply, DARWIN_HOSTS),
    "agent-platform": Part(AGENT_PLATFORM, ALL_HOSTS),
    "omlx": Part("""c: u: let o = c.system.build.omlxConfigure; in {
  models = (builtins.fromJSON o.modelSettings);
  server = (builtins.fromJSON o.serverSettings);
  activation = o.activation;
  fetch = o.fetch;
  serve = o.serve;
  reload = o.reload;
  restart = o.restart;
}""", ("eleven-m5",)),
    # jetsamElsewhere is every daemon plist but oMLX's that carries a jetsam priority.
    "memory-budget": Part("""c: u: {
  budget = c.system.build.memoryBudget;
  colimaFlags = c.system.build.colimaStartFlags;
  omlxCeiling = (builtins.fromJSON c.system.build.omlxConfigure.serverSettings).memory.memory_guard_custom_ceiling_gb;
  runners = builtins.attrNames c.services.github-runners;
  omlxPlist = c.environment.launchDaemons."org.nixos.omlx.plist".text;
  jetsamElsewhere = builtins.filter (n: n != "org.nixos.omlx.plist" && builtins.length (builtins.split "JetsamProperties" c.environment.launchDaemons.${n}.text) > 1) (builtins.attrNames c.environment.launchDaemons);
  watch = let d = c.launchd.daemons.omlx-memory-watch; in {
    inherit (d) command;
    inherit (d.serviceConfig) UserName StartInterval RunAtLoad KeepAlive;
    home = d.serviceConfig.EnvironmentVariables.HOME;
  };
  trim = let d = c.launchd.daemons.fseventsd-trim; in {
    inherit (d) command;
    inherit (d.serviceConfig) UserName StartInterval KeepAlive;
  };
  floor = let d = c.launchd.daemons.memory-floor; in {
    inherit (d) command;
    inherit (d.serviceConfig) KeepAlive RunAtLoad StandardOutPath;
    UserName = d.serviceConfig.UserName or null;
  };
  runnerUsers = map (r: r.user) (builtins.attrValues c.services.github-runners);
  owner = u.home.username;
  sopsSecrets = builtins.attrNames u.sops.secrets;
}""", ("eleven-m5",)),
}


def select(host, parts, *, darwin_machine: bool, linux_builder: bool) -> tuple[dict[str, Part], bool]:
    """The parts of `host` this machine can evaluate, and whether the evaluation forbids IFD."""
    available = {"darwin-machine": darwin_machine, "x86_64-linux-builder": linux_builder}
    selected = {
        name: part for name, part in parts.items()
        if host in part.hosts and (part.needs is None or available[part.needs])
    }
    pure = HOSTS[host] == "darwinConfigurations" and not any(
        part.needs == "darwin-machine" for part in selected.values())
    return selected, pure


def builder_entries(text):
    """The entries of a `builders` value or machines file, as Nix 2.31.5 expands them (`expandBuilderLines`)."""
    for line in text.split("\n"):
        for entry in line.split("#", 1)[0].split(";"):
            entry = entry.strip()
            if not entry:
                continue
            if entry.startswith("@"):
                try:
                    yield from builder_entries(Path(entry[1:].strip()).read_text())
                except FileNotFoundError:
                    pass
            else:
                yield entry


def can_build(system) -> bool:
    """Whether this host's nix names `system` in its `system`, `extra-platforms` or `builders` settings."""
    done = subprocess.run(NIX_CONFIG, cwd=ROOT, capture_output=True, text=True, timeout=60,
                          env=accounts_sandbox.unsandboxed_environment())
    if done.returncode != 0:
        raise AssertionError(f"nix config show failed:\n{done.stderr[-4000:]}")
    settings = json.loads(done.stdout)
    local = settings["system"]["value"]
    if system == local or system in settings["extra-platforms"]["value"]:
        return True
    for entry in builder_entries(settings["builders"]["value"]):
        fields = entry.split()
        systems = fields[1] if len(fields) > 1 and fields[1] != "-" else local
        if system in systems.split(","):
            return True
    return False


def username(root: Path = ROOT) -> str:
    done = subprocess.run(
        [*NIX, "--raw", "--file", str(root / "vars/default.nix"), "username"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=EVAL_TIMEOUT,
        env=accounts_sandbox.unsandboxed_environment(),
    )
    if done.returncode != 0:
        raise AssertionError(f"nix eval of the username failed:\n{done.stderr[-4000:]}")
    return done.stdout


def nix_version() -> str:
    done = subprocess.run(["nix", "--version"], capture_output=True, text=True,
                          env=accounts_sandbox.unsandboxed_environment())
    if done.returncode != 0:
        raise AssertionError(f"nix --version failed:\n{done.stderr[-4000:]}")
    return done.stdout.strip()


def fingerprint(root: Path) -> str:
    try:
        return verified_tree.current_tree(root)
    except verified_tree.VerifiedTreeError as error:
        raise AssertionError(f"cannot fingerprint the checkout {root}: {error}") from error


def cache_dir(root: Path) -> Path:
    override = os.environ.get(CACHE_ENV)
    if override:
        return Path(override)
    done = subprocess.run(["git", "-C", str(root), "rev-parse", "--absolute-git-dir"],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise AssertionError(f"git rev-parse --absolute-git-dir failed in {root}:\n{done.stderr[-4000:]}")
    return Path(done.stdout.strip()) / "host-readings"


def _evaluate(host: str, selected: dict[str, Part], pure: bool, root: Path) -> dict:
    """The one host evaluation: every selected part, applied to the host's config and the user's."""
    members = " ".join(
        f"{json.dumps(name)} = ({applied(selected[name], root)}) c u;" for name in sorted(selected))
    expression = f"c: let u = c.home-manager.users.{json.dumps(username(root))}; in {{ {members} }}"
    done = subprocess.run(
        [*NIX, *(NO_IFD if pure else []), "--json", f"{root}#{output(host)}.config", "--apply", expression],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=EVAL_TIMEOUT,
        env=accounts_sandbox.unsandboxed_environment(),
    )
    if done.returncode != 0:
        raise AssertionError(f"nix eval of {output(host)} failed:\n{done.stderr[-4000:]}")
    return json.loads(done.stdout)


def _unusable(cache: Path, error: OSError) -> AssertionError:
    return AssertionError(f"host readings cache {cache} is unusable: {error}")


def _stored(path: Path, key: str) -> dict | None:
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(entry, dict) and entry.get("key") == key and isinstance(entry.get("reading"), dict):
        return entry["reading"]
    return None


def _reserve(cache: Path, host: str) -> Path:
    """The temporary output of a miss, made under the host lock before anything is evaluated."""
    try:
        descriptor, name = tempfile.mkstemp(dir=cache, prefix=f".{host}-", suffix=".tmp")
    except OSError as error:
        raise _unusable(cache, error) from error
    os.close(descriptor)
    return Path(name)


def _publish(cache: Path, host: str, key: str, answer: dict, reserved: Path) -> dict:
    text = json.dumps({"key": key, "host": host, "reading": answer})
    target = cache / f"{host}-{key}.json"
    try:
        reserved.write_text(text, encoding="utf-8")
        os.replace(reserved, target)
    except OSError as error:
        raise _unusable(cache, error) from error
    # Only this host's generated entries are replaced: another file of the directory is not ours.
    generated = re.compile(rf"{re.escape(host)}-[0-9a-f]{{64}}\.json")
    for older in cache.iterdir():
        if older != target and generated.fullmatch(older.name):
            older.unlink(missing_ok=True)
    return json.loads(text)["reading"]


def reading(host, *, root: Path = ROOT, cache: Path | None = None, parts: dict[str, Part] | None = None) -> dict:
    """Every part of `host` this machine evaluates, as `{part: value}`; evaluated at most once per key."""
    parts = PARTS if parts is None else parts
    wants_builder = any(
        part.needs == "x86_64-linux-builder" for part in parts.values() if host in part.hosts)
    selected, pure = select(
        host, parts,
        darwin_machine=platform.system() == "Darwin",
        linux_builder=wants_builder and can_build("x86_64-linux"))
    nix = nix_version()
    cache = cache_dir(root) if cache is None else cache
    try:
        cache.mkdir(parents=True, exist_ok=True)
        lock = os.open(cache / f"{host}.lock", os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as error:
        raise _unusable(cache, error) from error
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
        except OSError as error:
            raise _unusable(cache, error) from error
        # The tree is read under the lock: an edit made while this reader waited must not leave
        # the key of an earlier tree usable.
        checkout = fingerprint(root)
        key = hashlib.sha256(json.dumps({
            "host": host,
            "output": output(host),
            "pure": pure,
            "parts": {name: applied(part, root) for name, part in selected.items()},
            "nix": nix,
            "checkout": checkout,
        }, sort_keys=True).encode()).hexdigest()
        stored = _stored(cache / f"{host}-{key}.json", key)
        if stored is not None:
            return stored
        reserved = _reserve(cache, host)
        try:
            answer = _evaluate(host, selected, pure, root)
            if fingerprint(root) != checkout:
                raise AssertionError(
                    f"the checkout changed during the evaluation of {output(host)}; nothing was stored")
            return _publish(cache, host, key, answer, reserved)
        finally:
            reserved.unlink(missing_ok=True)
    finally:
        os.close(lock)


def read(host, part, *, root=ROOT, cache=None):
    """One named part of `host`'s reading; a part this machine does not evaluate is an AssertionError."""
    wanted = PARTS[part]
    got = reading(host, root=root, cache=cache)
    if part not in got:
        raise AssertionError(
            f"the part {part!r} is not evaluated for {host} on this machine "
            f"(hosts {wanted.hosts}, needs {wanted.needs})")
    return got[part]
