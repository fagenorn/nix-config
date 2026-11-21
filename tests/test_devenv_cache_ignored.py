"""The devenv shell's cache must not make a checkout look dirty, while the devenv
files are tracked, their lock pins exactly the declared inputs, and the shell
declares only its tools.

Issue 1447 replaces the issue 1070 rule that also hid `devenv.lock`: the
repository now carries `devenv.nix`, `devenv.yaml` and `devenv.lock`, and only
the `.devenv/` cache directory is ignored.
"""

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _status_porcelain(root: Path, host_home: Path) -> list[str]:
    # Isolate git from the host's global and system config and its default
    # global ignore file ($XDG_CONFIG_HOME/git/ignore), so only this
    # repository's own `.gitignore` can hide a path.
    env = {
        **os.environ,
        "HOME": str(host_home),
        "XDG_CONFIG_HOME": str(host_home / ".config"),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    out = subprocess.run(
        [
            "git",
            "-c",
            f"core.excludesFile={os.devnull}",
            "-C",
            str(root),
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout
    return out.splitlines()


def _make_checkout(root: Path, gitignore: bytes) -> None:
    subprocess.run(["git", "init", "--quiet", str(root)], check=True, capture_output=True)
    (root / ".gitignore").write_bytes(gitignore)
    (root / ".devenv").mkdir()
    (root / ".devenv" / "state").write_text("cache\n")
    (root / ".devenv" / "profile" / "bin").mkdir(parents=True)
    (root / ".devenv" / "profile" / "bin" / "tool").write_text("x\n")
    (root / "devenv.lock").write_text("{}\n")
    (root / "devenv.nix").write_text("{ }\n")
    (root / "devenv.yaml").write_text("inputs: {}\n")
    (root / "stray.txt").write_text("not ignored\n")


def _hostile_host_home(parent: Path) -> Path:
    # A host whose default global git ignore file already hides the cache.
    home = parent / "home"
    (home / ".config" / "git").mkdir(parents=True)
    (home / ".config" / "git" / "ignore").write_text(".devenv/\ndevenv.lock\ndevenv.nix\ndevenv.yaml\n")
    return home


NIXPKGS_URL = "github:cachix/devenv-nixpkgs/rolling"
DECLARED = {"nixpkgs": NIXPKGS_URL}

ALLOWED_SOURCES = {
    ("github", "cachix", "devenv"),
    ("github", "cachix", "devenv-nixpkgs"),
    ("github", "NixOS", "nixpkgs"),
}

_INPUTS_LINE = re.compile(r"^inputs:$")
_INPUT_LINE = re.compile(r"^  ([A-Za-z0-9_.-]+):$")
_URL_LINE = re.compile(r"^    url: [^\s{}\[\],#]+$")
_FLAKE_LINE = re.compile(r"^    flake: (true|false)$")


def _declared_inputs(text: str) -> list[str]:
    """The input names of a devenv.yaml read whole by a strict line grammar."""
    names: list[str] = []
    has_url: dict[str, bool] = {}
    seen_inputs = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if _INPUTS_LINE.match(line) and not seen_inputs and not names:
            seen_inputs = True
            continue
        match = _INPUT_LINE.match(line)
        if match and seen_inputs:
            names.append(match.group(1))
            has_url[match.group(1)] = False
            continue
        if names and _URL_LINE.match(line):
            has_url[names[-1]] = True
            continue
        if names and _FLAKE_LINE.match(line):
            continue
        raise ValueError(f"unsupported devenv.yaml line: {line!r}")
    for name in names:
        if not has_url[name]:
            raise ValueError(f"input {name!r} has no url line")
    return names


_GITHUB_URL = re.compile(r"^github:([^/]+)/([^/]+)(?:/(.+))?$")


def _declared_urls(text: str) -> dict[str, str]:
    """Each declared input name with its url, read through the strict grammar."""
    urls: dict[str, str] = {}
    current = None
    for name in _declared_inputs(text):
        urls[name] = ""
    for line in text.splitlines():
        match = _INPUT_LINE.match(line)
        if match:
            current = match.group(1)
        elif _URL_LINE.match(line):
            urls[current] = line.split("url: ", 1)[1]
    return urls


def _original_problems(name: str, url: str | None, node: dict) -> list[str]:
    original = node.get("original")
    if not isinstance(original, dict):
        return [f"root input {name} has no original to compare with its declaration"]
    if url is None:
        want = {"type": "github", "owner": "cachix", "repo": "devenv"}
    else:
        match = _GITHUB_URL.match(url)
        if match is None:
            return [f"root input {name} declares an unsupported url {url!r}"]
        want = {"type": "github", "owner": match.group(1), "repo": match.group(2)}
        if match.group(3):
            want["ref"] = match.group(3)
    wrong = {key: original.get(key) for key, value in want.items() if original.get(key) != value}
    if url is not None and "ref" not in want and original.get("ref") is not None:
        wrong["ref"] = original["ref"]
    return [f"root input {name} original differs from its declaration: {wrong}"] if wrong else []


def _lock_problems(declared: dict[str, str], lock: dict) -> list[str]:
    problems: list[str] = []
    if lock.get("version") != 7:
        problems.append(f"version != 7: {lock.get('version')!r}")
    nodes = lock["nodes"]
    roots = set(nodes["root"]["inputs"])
    want = set(declared) | {"devenv"}
    if roots != want:
        problems.append(
            f"root inputs differ: extra {sorted(roots - want)}, missing {sorted(want - roots)}"
        )
    for name in sorted(roots):
        target = nodes["root"]["inputs"][name]
        if not isinstance(target, str) or target not in nodes:
            problems.append(f"root input {name} points at a missing node {target!r}")
            continue
        problems.extend(_original_problems(name, declared.get(name), nodes[target]))
    for name, node in nodes.items():
        for key, reference in node.get("inputs", {}).items():
            if isinstance(reference, list):
                # A follows path starts at a root input, not at a node name.
                head = reference[0] if reference else None
                found = isinstance(head, str) and head in nodes["root"]["inputs"]
            else:
                head = reference
                found = isinstance(head, str) and head in nodes
            if not found:
                problems.append(f"node {name} input {key} points at a missing node {head!r}")
    for name, node in nodes.items():
        if name == "root":
            continue
        locked = node.get("locked")
        if not isinstance(locked, dict) or not locked.get("narHash"):
            problems.append(f"node {name} is not locked with a narHash")
            continue
        source = (locked.get("type"), locked.get("owner"), locked.get("repo"))
        if source not in ALLOWED_SOURCES:
            problems.append(f"node {name} is locked to a foreign source {source}")
    return problems


def _valid_lock() -> dict:
    return {
        "version": 7,
        "root": "root",
        "nodes": {
            "root": {"inputs": {"devenv": "devenv", "nixpkgs": "nixpkgs"}},
            "devenv": {
                "original": {"type": "github", "owner": "cachix", "repo": "devenv"},
                "locked": {
                    "type": "github",
                    "owner": "cachix",
                    "repo": "devenv",
                    "narHash": "sha256-x",
                }
            },
            "nixpkgs": {
                "original": {
                    "type": "github",
                    "owner": "cachix",
                    "repo": "devenv-nixpkgs",
                    "ref": "rolling",
                },
                "locked": {
                    "type": "github",
                    "owner": "cachix",
                    "repo": "devenv-nixpkgs",
                    "narHash": "sha256-x",
                }
            },
        },
    }


class DevenvFilesTests(unittest.TestCase):
    def test_only_the_devenv_cache_directory_is_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            _make_checkout(root, (REPO_ROOT / ".gitignore").read_bytes())
            listed = _status_porcelain(root, _hostile_host_home(Path(tmp)))

        for path in ("stray.txt", "devenv.lock", "devenv.nix", "devenv.yaml"):
            self.assertIn(f"?? {path}", listed)
        self.assertEqual([l for l in listed if l.startswith("?? .devenv/")], [])

    def test_a_host_ignore_file_cannot_mask_a_missing_repo_rule(self):
        # Without the repo's rules the cache must show even though the host's
        # own ignore file names it; otherwise the test above measures the host.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            _make_checkout(root, b"")
            listed = _status_porcelain(root, _hostile_host_home(Path(tmp)))

        self.assertIn("?? .devenv/state", listed)
        self.assertIn("?? .devenv/profile/bin/tool", listed)
        self.assertIn("?? devenv.lock", listed)

    def test_the_devenv_files_are_tracked(self):
        out = subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "ls-files",
                "--error-unmatch",
                "devenv.nix",
                "devenv.yaml",
                "devenv.lock",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(
            sorted(out.stdout.splitlines()),
            ["devenv.lock", "devenv.nix", "devenv.yaml"],
        )

    def test_the_tracked_lock_locks_exactly_the_declared_inputs(self):
        declared = _declared_urls((REPO_ROOT / "devenv.yaml").read_text())
        lock = json.loads((REPO_ROOT / "devenv.lock").read_text())
        self.assertEqual(declared, {"nixpkgs": NIXPKGS_URL})
        problems = _lock_problems(declared, lock)
        self.assertEqual(problems, [], problems)

    def test_a_declaration_the_grammar_does_not_know_is_refused(self):
        url = "    url: github:cachix/devenv-nixpkgs/rolling\n"
        refused = {
            "flow input": "inputs:\n  nixpkgs:\n" + url + "  extra: {url: github:example/extra}\n",
            "flow inputs": "inputs: {nixpkgs: {url: github:cachix/devenv-nixpkgs/rolling}}\n",
            "other key": "inputs:\n  nixpkgs:\n" + url + "imports:\n  - ./extra\n",
            "no url": "inputs:\n  nixpkgs:\n    flake: false\n",
        }
        for label, text in refused.items():
            with self.subTest(label), self.assertRaises(ValueError):
                _declared_inputs(text)
        self.assertEqual(
            _declared_inputs("# c\ninputs:\n  nixpkgs:\n" + url), ["nixpkgs"]
        )

    def test_a_lock_pinning_anything_beyond_the_declared_inputs_is_a_problem(self):
        self.assertEqual(_lock_problems(DECLARED, _valid_lock()), [])

        with self.subTest("extra root input"):
            lock = _valid_lock()
            lock["nodes"]["root"]["inputs"]["platform"] = "platform"
            lock["nodes"]["platform"] = {
                "locked": {
                    "type": "github",
                    "owner": "example",
                    "repo": "platform",
                    "narHash": "sha256-x",
                }
            }
            problems = _lock_problems(DECLARED, lock)
            self.assertTrue(any("platform" in p for p in problems), problems)

        with self.subTest("foreign transitive node"):
            lock = _valid_lock()
            lock["nodes"]["platform-src"] = {
                "locked": {
                    "type": "github",
                    "owner": "example",
                    "repo": "platform",
                    "narHash": "sha256-x",
                }
            }
            problems = _lock_problems(DECLARED, lock)
            self.assertTrue(any("platform-src" in p for p in problems), problems)

        with self.subTest("a root input whose node is gone"):
            lock = _valid_lock()
            del lock["nodes"]["nixpkgs"]
            problems = _lock_problems(DECLARED, lock)
            self.assertTrue(any("nixpkgs" in p and "missing" in p for p in problems), problems)

        with self.subTest("a transitive input whose node is gone"):
            lock = _valid_lock()
            lock["nodes"]["nixpkgs"]["inputs"] = {"nixpkgs-src": "nixpkgs-src"}
            problems = _lock_problems(DECLARED, lock)
            self.assertTrue(any("nixpkgs-src" in p and "missing" in p for p in problems), problems)

        with self.subTest("a root input locked from another source than declared"):
            for member, value in (("repo", "other"), ("ref", "stable"), ("owner", "example")):
                lock = _valid_lock()
                lock["nodes"]["nixpkgs"]["original"][member] = value
                problems = _lock_problems(DECLARED, lock)
                self.assertTrue(any("differs" in p for p in problems), (member, problems))
            lock = _valid_lock()
            del lock["nodes"]["devenv"]["original"]
            self.assertTrue(_lock_problems(DECLARED, lock))

        with self.subTest("unlocked input"):
            lock = _valid_lock()
            lock["nodes"]["nixpkgs"]["locked"]["narHash"] = ""
            problems = _lock_problems(DECLARED, lock)
            self.assertTrue(any("nixpkgs" in p for p in problems), problems)

    def test_the_shell_declares_exactly_its_tools_and_nothing_else(self):
        text = (REPO_ROOT / "devenv.nix").read_text()
        text = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
        self.assertEqual(
            " ".join(text.split()),
            "{ pkgs, ... }: { packages = [ pkgs.git pkgs.just pkgs.python3 pkgs.nodejs pkgs.jq ]; }",
        )


if __name__ == "__main__":
    unittest.main()
