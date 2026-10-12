# Task 2: The `guard-policy` compiler, its command and its suite

Spec sections 1 to 3 (per D1–D5, D7, D9, D11, D13, D14, D15). `guard-policy compile` writes the compiled policy; nothing calls it until Task 3, so this task changes no guard behaviour.

**Files:**
- Create: `python/agent_tools/guard_policy.py`
- Create: `tests/guard_policy_world.py`, `tests/test_guard_policy.py`
- Modify: `lib/agent-tools.nix` (one row, `"guard-policy"`, after `"diff-scope"` in `commands`)
- Modify: `justfile` (one line, `    tests/test_guard_policy.py \`, after `    tests/test_forge_adapter.py \` in the `agent-workflow-tests` recipe)
- Modify: `python/README.md` (new section `## guard-policy` after `## Release adapters`)

**Interfaces:**
- Consumes (Task 1): `github_remote.github_slug`; `adopt_verify.remote_source(root, run_resolver, operand, *, network_timeout)` and its source's `ref`, `commit`, `branch`, `resolver_root`, `remote_default`. Existing: `adopt_inspection.run_git`, `AdoptError`; `agent_platform.read_registry`, `registry_path`, `load_manifest`, `write_atomically`, `PlatformManifestError`, `REGISTRY_SCHEMA_VERSION`; `resolve_project.resolve`, `load_contract`, `ContractError`; `release_profile.compile_profile`, `ProfileInadmissible`; `forge_adapter.TOKEN_VARIABLES`, `CHILD_TIMEOUT_SECONDS` (30), `DETAIL_LIMIT` (240); `canonical.telemetry_digest`.
- Produces (Task 3 relies on each):
  - The command `python -m agent_tools.guard_policy compile --base <path> --output <path>` (parser `prog` `guard-policy`), the launcher `agentTools.launchers.guard-policy`, and its exit statuses 0, 1, 2.
  - The compiled policy: one JSON object with exactly `authorized_owners`, `integration_bases`, `git_bin`, `gh_bin`, `jq_bin`, `derived_repositories`, `derivation`, where each derived row is exactly `{"default_branch", "integration_branch", "evidence"}`.
  - `tests/guard_policy_world.GuardPolicyWorld` with `project(...)`, `compile(base=..., output=...)`, `output`, `policy()`.

## The module's contract

Module-level names the suite imports: `POLICY_MEMBERS` (the seven members above, in that order), `BASE_MEMBERS` (the first five), `ProjectRefused(reason_code, detail)`, `target_profiles`. Also define `REASON_CODES` (the fourteen codes of spec section 2) and `CAUSES` (`base_invalid`, `registry_invalid`, `platform_unavailable`, `output_unwritable`, `internal`; D14) as closed tuples, and raise only their members.

```python
def read_base(path: Path) -> dict:
    """The base policy at `path`; `CompileRefused("base_invalid", ...)` unless it is one."""

def origin_slug(root: Path) -> str:
    """Step 2: the one github.com slug origin's fetch url and single push url name."""

def target_profiles(entry: dict, slug: str, snapshot: dict) -> list[str]:
    """Steps 5 to 8: the sorted ids of the profiles whose forge target selects `slug`."""

def derive(entry: dict) -> tuple[str, dict]:
    """Steps 1 to 10 for one registry entry: `(slug, derived row)`, or `ProjectRefused`."""

def compile_policy(base: dict, entries: list[dict]) -> tuple[dict, dict[str, dict], list[dict]]:
    """`(integration_bases, derived rows, refusals)`: `derive` per entry, then steps 11 and 12."""

def run_compile(base_path: Path, output: Path) -> tuple[int, dict]:
    """The exit status and the report; writes `output` atomically or leaves no file there."""

def main(argv: list[str] | None = None) -> int: ...
```

**Base policy (`read_base`).** A JSON object with exactly `POLICY_MEMBERS`, `derived_repositories` equal to `{}`, `derivation` equal to `null`, `authorized_owners` a list of non-empty strings, `integration_bases` an object of non-empty strings, and the three tool members absolute paths. Anything else, an unreadable file included, is `base_invalid`.

**The proof (`derive`), in this order; the first failing step raises `ProjectRefused` with the code shown.**

1. `run_git(root, "rev-parse", "--git-dir")` exits 0 (`root` is `Path(entry["root"])`); a non-zero exit or an `AdoptError` is `root_unavailable`.
2. `origin_slug(root)`: two identity reads, each a child run by name with `cwd=root` (not `git -C`), argv exactly `["git", "remote", "get-url", "origin"]` and `["git", "remote", "get-url", "--push", "--all", "origin"]`. Either read failing, a number of non-blank push lines other than one, a fetch url `github_slug` refuses, or a push url whose slug differs is `origin_unproven`. The slug `S` is `github_slug` of the fetch url, never case-folded.
3. `with adopt_verify.remote_source(root, resolver, override_branch, network_timeout=forge_adapter.CHILD_TIMEOUT_SECONDS) as source`, where `override_branch` is `entry["branch_override"]["branch"]` or `None`, and `resolver(root, command)` returns `(0, resolve_project.resolve(str(root)))` or, on `ContractError`, `(2, {"error": {"code": ..., "repair_id": ...}})` (D13). An `AdoptError` raised anywhere inside the block is `branch_unresolved` when its `repair_id` is `adopt.registration.remote_default_unknown` or `adopt.registration.integration_branch_unresolved`, and `fetch_failed` otherwise.
4. Inside the block, `resolver(source.resolver_root, "resolve")` must return status 0, else `contract_unresolved` with the resolver's repair id in the detail. The authored contract is then `resolve_project.load_contract(source.resolver_root)`; no other code opens the contract.
5. `target_profiles(entry, S, snapshot)`: `snapshot["project"]["id"] == entry["project_id"]`, else `identity_mismatch`.
6. `bindings.tracker.kind == "github"` and `bindings.tracker.repo_slug == S` exactly, else `tracker_mismatch`.
7. The entries of `snapshot["release"]["targets"]` whose `target.kind` is `github_repository`; none is `no_forge_target`.
8. Each such entry's `target.repository == S` and `target.branch == bindings.vcs.default_branch`, else `target_mismatch`; the function returns their sorted distinct `profile` ids. Back in `derive`, each id compiles through `release_profile.compile_profile(id, contract["release"]["profiles"][id], contract)`; `ProfileInadmissible` or `ValueError` is `profile_inadmissible`.
9. `bindings.vcs.integration_branch == source.branch` and `bindings.vcs.default_branch == source.remote_default`, else `branch_mismatch`.
10. A third child, argv exactly `["gh", "api", f"repos/{S}", "--jq", ".full_name"]` with `cwd=root`; a failed read or stripped stdout other than `S` is `provider_unproven`.

Every one of the three identity children runs with the `forge_adapter.TOKEN_VARIABLES` removed from its environment, `GIT_TERMINAL_PROMPT=0` and `GH_PROMPT_DISABLED=1` added, stdin at `/dev/null`, and a `forge_adapter.CHILD_TIMEOUT_SECONDS` timeout; a timeout or a missing executable is a failed read.

**The row.** `{"default_branch": <contract's>, "integration_branch": <contract's>, "evidence": {"project_id": entry["project_id"], "registry_entry_digest": telemetry_digest(entry), "source": {"ref": source.ref, "commit": source.commit}, "contract_blob": <stdout of run_git(root, "rev-parse", "--verify", "--quiet", f"{source.commit}:.agents/project.json")>, "provider_full_name": <the provider's answer>, "profiles": [{"id", "version": compiled["profile_version"], "digest": compiled["digest"]}, ...]}}`. A non-zero exit of that `rev-parse` is `contract_unresolved`. Nothing else is persisted (D11).

**Steps 11 and 12 (`compile_policy`).** Among the projects that passed steps 1 to 10: a slug derived by more than one is `duplicate_repository` for each of them; otherwise a slug that is a key of the base `integration_bases` is `literal_conflict`; otherwise the row is written. The returned `integration_bases` is the base's without every slug any such project derived (D14). A refusal is `{"project_id", "root", "reason_code", "detail"}` with `detail` cut to `DETAIL_LIMIT` characters.

**Outcomes (`run_compile`).**

| Outcome | Exit | Report `outcome` | File |
|---|---|---|---|
| every entry derived (an absent registry is the empty fleet) | 0 | `complete` | written |
| at least one refusal | 1 | `written_with_refusals` | written, refused projects absent |
| `CompileRefused`, or any other exception | 2 | `refused` | `output.unlink(missing_ok=True)` |

The written document is the base's five members with `integration_bases` replaced, plus `derived_repositories` and `derivation = {"schema_version": 1, "platform_version": manifest["platform_version"], "registry_digest": ...}`, where `manifest` is `agent_platform.load_manifest()[0]` and `registry_digest` is `telemetry_digest({"schema_version": agent_platform.REGISTRY_SCHEMA_VERSION, "projects": entries})`, or `None` when `agent_platform.registry_path()` does not exist. It is serialized as `json.dumps(document, indent=2, sort_keys=True) + "\n"` and written with `agent_platform.write_atomically`. Causes: `PlatformManifestError` from `load_manifest` is `platform_unavailable`, from `read_registry` `registry_invalid`; `OSError` from the write is `output_unwritable`; any other exception is `internal` with `"<type name>: <message>"` as its detail.

The report is always `{"schema_version": 1, "outcome", "derived": <sorted slugs>, "refused": [...], "cause": null | {"reason_code", "detail"}}`. `main` prints one stderr line per refusal, `guard-policy: <project_id> (<root>) has no derived row: <reason_code>: <detail>`, one for a cause, `guard-policy: no policy was written: <reason_code>: <detail>`, then the report as one `json.dumps(report, sort_keys=True)` line on stdout, and returns the exit status.

**Invariants:**
- No row is written for a project unless all twelve steps held in this run; a previous file's row never survives (R4).
- After exit 2 no file exists at `--output`, whatever was there before (R5).
- `gh` never sees `GITHUB_TOKEN` or `GH_TOKEN` (the world's `gh` exits 65 if it does).
- In a registered root nothing but the remote-tracking refs of the branches read (`refs/remotes/origin/<default>` and, when it differs, `refs/remotes/origin/<integration>`) and fetched objects is written: no `FETCH_HEAD`, no local branch, index or working-tree change.
- The module has no contract parser, writes no snapshot, and imports nothing by path.

- [ ] **Step 1: Write the fixture world and the failing suite**

Create `tests/guard_policy_world.py`:

```python
"""A hermetic fleet for the guard-policy suites (issue 126 D10).

`GuardPolicyWorld(test_case)` builds a temporary `HOME` holding the platform manifest, a base
policy file, and a `bin/` with `git` and `gh` shims that is first on the `PATH` of `env`.
`project(...)` commits a conformant contract derived from this repository's own, publishes it
to a local bare `origin` and returns the checkout; `register(...)` writes the fleet registry.

The `git` shim answers only `remote get-url origin` and `remote get-url --push --all origin`,
from `identities.json` keyed by its working directory, and hands every other call to the real
`git`; with no entry for the directory it hands those two over as well. The `gh` shim answers
`api repos/<slug> --jq .full_name` from `providers.json`, exits 64 for any other call and 65
when a token variable reaches it. Nothing contacts a network remote or reads the host registry.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "home/common/agent-skills/platform-manifest.json"
PUBLICATION_FREE = REPO_ROOT / "tests/fixtures/release/publication-free-profile.json"
OWN_SLUG = "fagenorn/nix-config"
REAL_GIT = shutil.which("git")

GIT_SHIM = """#!{python}
import json, os, sys
argv = sys.argv[1:]
answers = json.loads(open({state!r} + "/identities.json", encoding="utf-8").read())
answer = answers.get(os.path.realpath(os.getcwd()))
if answer is not None and argv == ["remote", "get-url", "origin"]:
    print(answer["origin"])
elif answer is not None and argv == ["remote", "get-url", "--push", "--all", "origin"]:
    print("\\n".join(answer["pushes"]))
else:
    os.execv({git!r}, [{git!r}, *argv])
"""

GH_SHIM = """#!{python}
import json, os, sys
argv = sys.argv[1:]
if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
    sys.stderr.write("gh: a token variable reached the child\\n")
    sys.exit(65)
answers = json.loads(open({state!r} + "/providers.json", encoding="utf-8").read())
if len(argv) == 4 and argv[0] == "api" and argv[2:] == ["--jq", ".full_name"] \\
        and argv[1] in answers:
    answer = answers[argv[1]]
    sys.stdout.write(answer["stdout"])
    sys.exit(answer["exit"])
sys.stderr.write("fake gh: unregistered call\\n")
sys.exit(64)
"""


class GuardPolicyWorld:
    def __init__(self, test_case: unittest.TestCase) -> None:
        tmp = tempfile.TemporaryDirectory()
        test_case.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.home, self.bin, self.state = (self.tmp / name for name in ("home", "bin", "state"))
        for directory in (self.home / ".agents/share", self.bin, self.state):
            directory.mkdir(parents=True)
        shutil.copy(MANIFEST, self.home / ".agents/share/platform-manifest.json")
        for name, text in (("git", GIT_SHIM), ("gh", GH_SHIM)):
            shim = self.bin / name
            shim.write_text(text.format(python=sys.executable, state=str(self.state),
                                        git=REAL_GIT), encoding="utf-8")
            shim.chmod(0o755)
        self.identities: dict[str, dict] = {}
        self.providers: dict[str, dict] = {}
        self._save()
        self.entries: list[dict] = []
        self.base = self.tmp / "base-policy.json"
        self.output = self.home / ".agents/state/guard/policy.json"
        self.write_base()
        # GITHUB_TOKEN is set on purpose: the compiler must scrub it before `gh` (D7).
        self.env = {**os.environ, "HOME": str(self.home), "GITHUB_TOKEN": "harness-token",
                    "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                    "PYTHONPATH": str(REPO_ROOT / "python"),
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}

    def _save(self) -> None:
        (self.state / "identities.json").write_text(json.dumps(self.identities), "utf-8")
        (self.state / "providers.json").write_text(json.dumps(self.providers), "utf-8")

    def write_base(self, **members: object) -> dict:
        document = {"authorized_owners": ["fagenorn"],
                    "integration_bases": {"fagenorn/arcwave": "dev"},
                    "git_bin": "/usr/bin/git", "gh_bin": "/usr/bin/gh", "jq_bin": "/usr/bin/jq",
                    "derived_repositories": {}, "derivation": None, **members}
        self.base.write_text(json.dumps(document), encoding="utf-8")
        return document

    def git(self, root: Path, *args: str) -> str:
        return subprocess.run(
            [REAL_GIT, "-C", str(root), *args], capture_output=True, text=True, timeout=120,
            check=True, env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
                             "GIT_CONFIG_SYSTEM": os.devnull,
                             "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                             "GIT_COMMITTER_NAME": "t",
                             "GIT_COMMITTER_EMAIL": "t@example.invalid"}).stdout

    def contract(self, project_id: str, slug: str, *, integration_branch: str = "main",
                 publication_free: bool = False) -> dict:
        """This repository's own contract, renamed to `slug` (so it stays grammar-valid)."""
        text = (REPO_ROOT / ".agents/project.json").read_text("utf-8")
        contract = json.loads(text.replace(OWN_SLUG, slug))
        contract["project"] = {"id": project_id, "name": project_id.split("/")[-1]}
        contract["bindings"]["vcs"]["integration_branch"] = integration_branch
        if publication_free:
            profile = PUBLICATION_FREE.read_text("utf-8").replace(OWN_SLUG, slug)
            contract["release"] = {"profiles": {"forge-main": json.loads(profile)}}
        return contract

    def commit_contract(self, root: Path, contract: dict, message: str = "contract", *,
                        render: bool = True) -> None:
        """Write `contract`, render its projections with the resolver unless `render` is
        false (a contract the resolver refuses cannot be rendered), and commit everything."""
        path = root / ".agents/project.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
        (root / ".agents/instructions").mkdir(exist_ok=True)
        (root / ".agents/instructions/bootstrap.md").write_text("# invariants\n", "utf-8")
        for name in ("standards", "rejections"):
            for relative in contract["bindings"]["paths"][name]:
                (root / relative).mkdir(parents=True, exist_ok=True)
                (root / relative / "keep.md").write_text("# keep\n", "utf-8")
        for relative in contract["bindings"]["paths"]["architecture"]:
            if not (root / relative).exists():
                (root / relative).write_text("# architecture\n", "utf-8")
        if render:
            done = subprocess.run(
                [sys.executable, "-m", "agent_tools.resolve_project", "write-projections",
                 "--repo-root", str(root)],
                capture_output=True, text=True, timeout=120, env=self.env)
            if done.returncode != 0:
                raise AssertionError(f"fixture projections could not be rendered: {done.stdout}")
        self.git(root, "add", "-A")
        self.git(root, "commit", "--quiet", "-m", message)

    def project(self, project_id: str, slug: str, *, integration_branch: str = "main",
                publication_free: bool = False, register: bool = True,
                override: bool = False, mutate=None) -> Path:
        """A published, conformant checkout for `slug`; its registry entry unless `register`
        is false. With another `integration_branch` than `main`, `origin` also gets that
        branch; `override=True` makes `main`'s contract unresolvable and records the override."""
        root = self.tmp / "projects" / project_id.replace("/", "-")
        root.mkdir(parents=True)
        self.git(root, "init", "--quiet", "-b", "main")
        self.git(root, "config", "commit.gpgsign", "false")
        contract = self.contract(project_id, slug, integration_branch=integration_branch,
                                 publication_free=publication_free)
        if mutate is not None:
            mutate(contract)
        self.commit_contract(root, contract)
        refs = ["main"]
        if integration_branch != "main":
            self.git(root, "branch", integration_branch)
            refs.append(integration_branch)
        if override:
            broken = dict(contract)
            del broken["release"]
            self.commit_contract(root, broken, "a default branch that lags", render=False)
        self.publish(root, refs)
        self.identity(root, f"git@github.com:{slug}.git")
        self.provider(slug)
        entry = {"project_id": project_id, "root": str(root)}
        if override:
            entry["branch_override"] = {"branch": integration_branch, "default_branch": "main",
                                        "reason": "default_contract_unresolved"}
        if register:
            self.register(entry)
        return root

    def publish(self, root: Path, refs: list[str], *, default: str = "main") -> Path:
        """Push `refs` to a new local bare repository and make it `origin`."""
        bare = Path(tempfile.mkdtemp(dir=self.tmp)) / "origin.git"
        self.git(self.tmp, "init", "--quiet", "--bare", "-b", default, str(bare))
        verb = "set-url" if "origin" in self.git(root, "remote").split() else "add"
        self.git(root, "remote", verb, "origin", str(bare))
        self.git(root, "push", "--quiet", "--force", "origin",
                 *(f"{ref}:refs/heads/{ref}" for ref in refs))
        return bare

    def identity(self, root: Path, origin: str | None, pushes: list[str] | None = None) -> None:
        """What the `git` shim reports as `root`'s origin urls; `None` restores the real ones."""
        key = os.path.realpath(root)
        if origin is None:
            self.identities.pop(key, None)
        else:
            self.identities[key] = {"origin": origin,
                                    "pushes": [origin] if pushes is None else pushes}
        self._save()

    def provider(self, slug: str, full_name: str | None = None, exit: int = 0) -> None:
        self.providers[f"repos/{slug}"] = {"stdout": (full_name or slug) + "\n", "exit": exit}
        self._save()

    def register(self, *entries: dict) -> None:
        self.entries.extend(entries)
        self.write_registry({"schema_version": 1, "projects": self.entries})

    def write_registry(self, document: object) -> Path:
        path = self.home / ".agents/state/fleet/registry.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document if isinstance(document, str) else json.dumps(document), "utf-8")
        return path

    def compile(self, *, base: Path | None = None, output: Path | None = None,
                env: dict | None = None) -> tuple[int, dict, str]:
        """Run the command from source: `(exit status, parsed report, stderr)`."""
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.guard_policy", "compile",
             "--base", str(base or self.base), "--output", str(output or self.output)],
            capture_output=True, text=True, timeout=300, env=env or self.env, cwd=self.tmp)
        return done.returncode, json.loads(done.stdout), done.stderr

    def policy(self) -> dict:
        return json.loads(self.output.read_text("utf-8"))
```

Create `tests/test_guard_policy.py`:

```python
"""The guard-policy compiler at its command seam (issue 126 D10, D15).

Every case runs `python -m agent_tools.guard_policy compile` over `GuardPolicyWorld` and
asserts on the exit status, the report and the written file. `TargetProfilesTest` is the one
imported-function suite: the release grammar refuses a foreign forge target before the
compiler sees it, so that step is pinned on a resolved snapshot edited in memory.
"""
import json
import shutil
import unittest

from agent_tools import guard_policy
from . import release_test_support as support
from .guard_policy_world import GuardPolicyWorld

NODO = "elevenyellow/nodocom"
ROW_MEMBERS = {"default_branch", "integration_branch", "evidence"}
EVIDENCE_MEMBERS = {"project_id", "registry_entry_digest", "source", "contract_blob",
                    "provider_full_name", "profiles"}


class WorldCase(unittest.TestCase):
    def setUp(self) -> None:
        self.world = GuardPolicyWorld(self)

    def refused(self, reason_code: str, project_id: str = "fixture/one") -> dict:
        """Compile, expect exit 1 with exactly one refusal for `project_id`, and return it."""
        code, report, err = self.world.compile()
        self.assertEqual((code, report["outcome"]), (1, "written_with_refusals"), report)
        [refusal] = [r for r in report["refused"] if r["project_id"] == project_id]
        self.assertEqual(refusal["reason_code"], reason_code, refusal)
        self.assertEqual(set(refusal), {"project_id", "root", "reason_code", "detail"})
        self.assertLessEqual(len(refusal["detail"]), 240)
        self.assertIn(f"{project_id} ", err)
        self.assertIn(reason_code, err)
        self.assertNotIn(project_id, json.dumps(self.world.policy()["derived_repositories"]))
        return refusal


class DerivationTest(WorldCase):
    def test_a_nodo_shaped_and_a_single_branch_project_both_derive(self):
        single = self.world.project("fixture/single", "fagenorn/single")
        nodo = self.world.project("nodocom", NODO, integration_branch="dev",
                                  publication_free=True, override=True)
        code, report, err = self.world.compile()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(report, {"schema_version": 1, "outcome": "complete", "cause": None,
                                  "derived": [NODO, "fagenorn/single"], "refused": []})
        policy = self.world.policy()
        self.assertEqual(set(policy), set(guard_policy.POLICY_MEMBERS))
        base = json.loads(self.world.base.read_text("utf-8"))
        for member in guard_policy.BASE_MEMBERS:
            self.assertEqual(policy[member], base[member], member)
        rows = policy["derived_repositories"]
        self.assertEqual(sorted(rows), [NODO, "fagenorn/single"])
        for row in rows.values():
            self.assertEqual(set(row), ROW_MEMBERS)
            self.assertEqual(set(row["evidence"]), EVIDENCE_MEMBERS)
        self.assertEqual((rows[NODO]["default_branch"], rows[NODO]["integration_branch"]),
                         ("main", "dev"))
        self.assertEqual((rows["fagenorn/single"]["default_branch"],
                          rows["fagenorn/single"]["integration_branch"]), ("main", "main"))
        evidence = rows[NODO]["evidence"]
        self.assertEqual(evidence["project_id"], "nodocom")
        self.assertEqual(evidence["source"], {
            "ref": "refs/remotes/origin/dev",
            "commit": self.world.git(nodo, "rev-parse", "dev").strip()})
        self.assertEqual(evidence["contract_blob"],
                         self.world.git(nodo, "rev-parse", "dev:.agents/project.json").strip())
        self.assertEqual(evidence["provider_full_name"], NODO)
        [profile] = evidence["profiles"]
        self.assertEqual((profile["id"], profile["version"]), ("forge-main", 1))
        self.assertRegex(profile["digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(evidence["registry_entry_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(rows["fagenorn/single"]["evidence"]["source"]["commit"],
                         self.world.git(single, "rev-parse", "main").strip())
        derivation = policy["derivation"]
        self.assertEqual(set(derivation),
                         {"schema_version", "platform_version", "registry_digest"})
        self.assertEqual(derivation["schema_version"], 1)
        self.assertRegex(derivation["registry_digest"], r"^sha256:[0-9a-f]{64}$")
        # D11: identity evidence only, never the contract or a resolved snapshot.
        text = self.world.output.read_text("utf-8")
        for leaked in ("branch_pattern", "repo_slug", "capabilities", str(self.world.home)):
            self.assertNotIn(leaked, text)

    def test_an_absent_registry_is_the_empty_fleet(self):
        code, report, _ = self.world.compile()
        self.assertEqual((code, report["outcome"], report["derived"]), (0, "complete", []))
        policy = self.world.policy()
        self.assertEqual(policy["derived_repositories"], {})
        self.assertEqual(policy["integration_bases"], {"fagenorn/arcwave": "dev"})
        self.assertEqual(policy["authorized_owners"], ["fagenorn"])
        self.assertIsNone(policy["derivation"]["registry_digest"])

    def test_the_contract_is_read_from_origin_and_the_checkout_is_left_alone(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        published = self.world.git(root, "rev-parse", "main")
        # A local branch, a moved remote-tracking ref and a dirty tree, none of them origin's.
        self.world.git(root, "checkout", "--quiet", "-b", "local-work")
        (root / ".agents/project.json").write_text("not json", "utf-8")
        self.world.git(root, "commit", "--quiet", "-am", "local only")
        self.world.git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
        (root / "untracked.txt").write_text("dirty", "utf-8")
        before = (self.world.git(root, "status", "--porcelain"),
                  self.world.git(root, "rev-parse", "HEAD"),
                  self.world.git(root, "for-each-ref", "refs/heads"))
        code, report, _ = self.world.compile()
        self.assertEqual((code, report["derived"]), (0, ["fagenorn/one"]))
        self.assertEqual(before, (self.world.git(root, "status", "--porcelain"),
                                  self.world.git(root, "rev-parse", "HEAD"),
                                  self.world.git(root, "for-each-ref", "refs/heads")))
        self.assertFalse((root / ".git/FETCH_HEAD").exists())
        self.assertEqual(self.world.git(root, "rev-parse", "refs/remotes/origin/main"), published)

    def test_a_refused_project_loses_its_stale_row(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.world.project("fixture/two", "fagenorn/two")
        self.assertEqual(self.world.compile()[0], 0)
        self.assertIn("fagenorn/one", self.world.policy()["derived_repositories"])
        self.world.provider("fagenorn/one", exit=1)
        self.refused("provider_unproven")
        self.assertEqual(sorted(self.world.policy()["derived_repositories"]), ["fagenorn/two"])


class ProjectRefusalTest(WorldCase):
    def test_root_unavailable(self):
        plain = self.world.tmp / "plain"
        plain.mkdir()
        self.world.register({"project_id": "fixture/one", "root": str(plain)},
                            {"project_id": "fixture/gone", "root": str(self.world.tmp / "gone")})
        self.refused("root_unavailable")
        self.refused("root_unavailable", "fixture/gone")

    def test_origin_unproven(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        url = "git@github.com:fagenorn/one.git"
        for origin, pushes in (
                ("git@gitlab.com:fagenorn/one.git", None),          # not github.com
                ("https://github.com.evil.example/fagenorn/one", None),
                (url, [url, url]),                                    # two push urls
                (url, []),                                            # no push url
                (url, ["git@github.com:fagenorn/elsewhere.git"]),     # push differs from fetch
        ):
            with self.subTest(origin=origin, pushes=pushes):
                self.world.identity(root, origin, pushes)
                self.refused("origin_unproven")
        self.world.identity(root, None)  # the real origin is a local path
        self.refused("origin_unproven")

    def test_branch_unresolved(self):
        self.world.project("fixture/one", "fagenorn/one", integration_branch="dev",
                           override=True)
        self.world.entries[0]["branch_override"]["branch"] = "gone"
        self.world.register()
        self.refused("branch_unresolved")

    def test_fetch_failed(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        shutil.rmtree(self.world.git(root, "remote", "get-url", "origin").strip())
        self.refused("fetch_failed")

    def test_contract_unresolved(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        broken = self.world.contract("fixture/one", "fagenorn/one")
        del broken["release"]
        self.world.commit_contract(root, broken, "an invalid contract", render=False)
        self.world.publish(root, ["main"])
        self.refused("contract_unresolved")

    def test_identity_mismatch(self):
        root = self.world.project("fixture/actual", "fagenorn/one", register=False)
        self.world.register({"project_id": "fixture/one", "root": str(root)})
        self.refused("identity_mismatch")

    def test_tracker_mismatch(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        for slug in ("fagenorn/elsewhere", "Fagenorn/One"):  # no case folding
            with self.subTest(origin=slug):
                self.world.identity(root, f"git@github.com:{slug}.git")
                self.world.provider(slug)
                self.refused("tracker_mismatch")

    def test_no_forge_target(self):
        def unsupported(contract: dict) -> None:
            contract["release"] = "unsupported"
        self.world.project("fixture/one", "fagenorn/one", mutate=unsupported)
        self.refused("no_forge_target")

    def test_profile_inadmissible(self):
        def inadmissible(contract: dict) -> None:
            contract["release"] = support.release_of(
                "github-release", support.missing_deadline_profile())
        self.world.project("fixture/one", "fagenorn/nix-config", mutate=inadmissible)
        self.refused("profile_inadmissible")

    def test_branch_mismatch(self):
        root = self.world.project("fixture/one", "fagenorn/one")
        self.world.git(root, "branch", "trunk")
        self.world.publish(root, ["main", "trunk"], default="trunk")
        self.refused("branch_mismatch")

    def test_provider_unproven(self):
        self.world.project("fixture/one", "fagenorn/one")
        for answer in ({"full_name": "fagenorn/renamed"}, {"exit": 1}):
            with self.subTest(answer=answer):
                self.world.provider("fagenorn/one", **answer)
                self.refused("provider_unproven")

    def test_duplicate_repository_refuses_both(self):
        self.world.project("fixture/one", "fagenorn/one")
        self.world.project("fixture/two", "fagenorn/one")
        self.world.project("fixture/three", "fagenorn/three")
        self.refused("duplicate_repository")
        self.refused("duplicate_repository", "fixture/two")
        self.assertEqual(sorted(self.world.policy()["derived_repositories"]), ["fagenorn/three"])

    def test_literal_conflict_withholds_both_rows(self):
        self.world.write_base(integration_bases={"fagenorn/one": "dev",
                                                 "fagenorn/arcwave": "dev"})
        self.world.project("fixture/one", "fagenorn/one")
        self.refused("literal_conflict")
        policy = self.world.policy()
        self.assertEqual(policy["integration_bases"], {"fagenorn/arcwave": "dev"})
        self.assertEqual(policy["derived_repositories"], {})


class TargetProfilesTest(unittest.TestCase):
    """Step 8 below the grammar (D15): the members `target_profiles` reads, built by hand."""

    SLUG = "fagenorn/one"
    ENTRY = {"project_id": "fixture/one", "root": "/nonexistent"}

    def snapshot(self, **target: str) -> dict:
        return {"project": {"id": "fixture/one"},
                "bindings": {"vcs": {"default_branch": "main"},
                             "tracker": {"kind": "github", "repo_slug": self.SLUG}},
                "release": {"targets": [
                    {"profile": "forge-main", "adapter": "github-forge", "operations": [],
                     "target": {"handle": "repository", "kind": "github_repository",
                                "repository": self.SLUG, "branch": "main", **target}}]}}

    def test_a_target_for_this_repository_selects_its_profile(self):
        self.assertEqual(guard_policy.target_profiles(self.ENTRY, self.SLUG, self.snapshot()),
                         ["forge-main"])

    def test_a_target_for_another_repository_or_branch_is_refused(self):
        for target in ({"repository": "fagenorn/elsewhere"}, {"branch": "dev"}):
            with self.subTest(target=target):
                with self.assertRaises(guard_policy.ProjectRefused) as caught:
                    guard_policy.target_profiles(self.ENTRY, self.SLUG, self.snapshot(**target))
                self.assertEqual(caught.exception.reason_code, "target_mismatch")


class WholeRefusalTest(WorldCase):
    def assert_refused(self, cause: str, **compile_arguments) -> None:
        output = compile_arguments.get("output", self.world.output)
        code, report, err = self.world.compile(**compile_arguments)
        self.assertEqual((code, report["outcome"]), (2, "refused"), report)
        self.assertEqual(report["cause"]["reason_code"], cause, report)
        self.assertEqual((report["derived"], report["refused"]), ([], []))
        self.assertIn(cause, err)
        self.assertFalse(output.exists())

    def previous_policy(self) -> None:
        """A policy file from an earlier, successful compile."""
        self.world.project("fixture/one", "fagenorn/one")
        self.assertEqual(self.world.compile()[0], 0)
        self.assertTrue(self.world.output.exists())

    def test_an_unusable_base_policy(self):
        self.previous_policy()
        valid = json.loads(self.world.base.read_text("utf-8"))
        cases = {
            "not json": "{",
            "a missing member": {k: v for k, v in valid.items() if k != "jq_bin"},
            "an extra member": {**valid, "extra": 1},
            "a compiled policy": {**valid, "derivation": {}},
            "a derived row": {**valid, "derived_repositories": {"a/b": {}}},
            "owners": {**valid, "authorized_owners": "fagenorn"},
            "bases": {**valid, "integration_bases": {"a/b": ""}},
            "a relative tool": {**valid, "git_bin": "git"},
        }
        for name, document in cases.items():
            with self.subTest(base=name):
                self.world.base.write_text(
                    document if isinstance(document, str) else json.dumps(document), "utf-8")
                self.assert_refused("base_invalid")
                self.world.write_base()
                self.assertEqual(self.world.compile()[0], 0)
        self.assert_refused("base_invalid", base=self.world.tmp / "absent.json")

    def test_a_registry_that_does_not_validate(self):
        self.previous_policy()
        for document in ("{", {"schema_version": 1}, {"schema_version": 1, "projects": [{}]}):
            with self.subTest(registry=document):
                self.world.write_registry(document)
                self.assert_refused("registry_invalid")
                self.world.register()
                self.assertEqual(self.world.compile()[0], 0)

    def test_a_missing_platform_manifest(self):
        self.previous_policy()
        (self.world.home / ".agents/share/platform-manifest.json").unlink()
        self.assert_refused("platform_unavailable")

    def test_an_output_that_cannot_be_written(self):
        blocker = self.world.tmp / "blocker"
        blocker.write_text("a file where a directory is needed", "utf-8")
        self.assert_refused("output_unwritable", output=blocker / "policy.json")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the suite and watch it fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py 2>&1 | tail -6`
Expected: FAIL — `ImportError: cannot import name 'guard_policy' from 'agent_tools'`.

- [ ] **Step 3: Write the minimal implementation**

Write `python/agent_tools/guard_policy.py` to the contract above, with a module docstring that states what the command reads, what it writes and its three exit statuses as implemented. Add the `lib/agent-tools.nix` row and the `justfile` line.

- [ ] **Step 4: Document the command**

Add `## guard-policy` to `python/README.md` after `## Release adapters`, in that file's prose style, each sentence written from the implemented module: what `compile` reads (the base policy, the fleet registry, each registered project's contract on its registered branch of `origin`) and never reads (the checkout's working tree, index and local branches); the twelve proof steps by reason code; the row and its evidence members; the three outcomes with their exit statuses and what happens to the output file; the report's members and the cause codes; that every network child is bounded at 30 seconds and prompt-free and that `gh` runs without the token variables; and the decisions as `issue 126 D<n>`. Do not describe the guard, the activation step or `claude-guard-policy`: Task 4 owns that prose.

- [ ] **Step 5: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py 2>&1 | tail -4`
Expected: `Ran 23 tests` and `OK`.

Run: `env -i PATH="$PATH" HOME=/nonexistent PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py 2>&1 | tail -2`
Expected: `OK` — the suite does not depend on the host's `HOME`, registry or manifest.

Run, as one script:

```bash
set -e
if ! grep -q '"guard-policy"' lib/agent-tools.nix; then exit 1; fi
if ! grep -q 'tests/test_guard_policy.py' justfile; then exit 1; fi
if ! grep -q '^## guard-policy' python/README.md; then exit 1; fi
if grep -n "importlib\|__file__\|sys.path" python/agent_tools/guard_policy.py; then exit 1; fi
git add python/agent_tools/guard_policy.py tests/guard_policy_world.py tests/test_guard_policy.py && just build >/dev/null
git diff --quiet 450f1de3627b -- home/common/claude-code tests/test_claude_permission_guard.py
```

Expected: exit 0. `just build` fails evaluation if the command row names a module that does not exist and fails the import check if the module does not import. At the task's starting commit the first `grep` finds nothing, so the script exits 1.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/guard_policy.py lib/agent-tools.nix justfile tests/guard_policy_world.py tests/test_guard_policy.py python/README.md
```

Commit through `launch-commit` with the message `feat(agent-tools): guard-policy compiles the lifecycle guard's policy from the fleet registry (issue 126)`.
