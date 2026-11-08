"""Shared fixtures for the release driver suites (#128 spec, Test seams 2 and 3)."""
import copy
import tempfile
from pathlib import Path

from agent_tools import forge_adapter, release_driver, release_profile
from . import release_test_support as support
from .forge_world import CANONICAL, ROWS

PROJECT_ID = "fagenorn/nix-config"
KEY = "release/fagenorn/nix-config"


class Clock:
    def __init__(self, now: int = 1_790_000_000_000) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now

    def advance(self, ms: int) -> None:
        self.now += ms


class FixtureStore:
    """`fixture-store` for registry injection: describes itself and is never driven."""

    def describe(self):
        return copy.deepcopy(support.FIXTURE_STORE)

    def inspect(self, request):
        raise AssertionError("fixture-store is never inspected")

    def invoke(self, request):
        raise AssertionError("fixture-store is never invoked")


def candidate(**overrides) -> dict:
    return {"version": CANONICAL["tag"], "commit": CANONICAL["commit"],
            "title": CANONICAL["title"], "notes": "notes body", **overrides}


def project(case, *, profiles=None, integration="main", default="main") -> release_driver.Project:
    scratch = tempfile.TemporaryDirectory()
    case.addCleanup(scratch.cleanup)
    root = Path(scratch.name).resolve() / "checkout"
    (root / ".git").mkdir(parents=True)
    profiles = {"github-release": support.forge_profile()} if profiles is None else profiles
    return release_driver.Project(
        project_id=PROJECT_ID, root=root, common_dir=root / ".git",
        integration_branch=integration, default_branch=default,
        contract={**support.base_contract(), "release": {"profiles": profiles}})


def seed(driver, ordinal=1, **overrides) -> str:
    """Create a transaction directly, as `run` would, and return its id."""
    store = driver.store(create=True)
    inputs = release_profile.bind_candidate(driver.compiled, candidate(**overrides))
    return store.create(
        release_driver.creation_key(PROJECT_ID, driver.profile_id, ordinal),
        inputs["subject"], concurrency_keys=inputs["concurrency_keys"],
        proof=inputs["proof"], recovery=inputs["recovery"],
        authority_class=release_driver.AUTHORITY_CLASS).transaction_id


URL = f"https://github.com/{CANONICAL['slug']}/releases/tag/{CANONICAL['tag']}"


class StatefulForge:
    """`github-forge` for registry injection (D20): delegates to the real adapter and,
    after an accepted invoke, makes the provider show what that invoke created."""

    def __init__(self, world) -> None:
        self.world = world
        world.invoke_ready()
        world.not_found("gh", ROWS["tag.ref"]["argv"][1:])
        world.not_found("gh", ROWS["release.view"]["argv"][1:])

    def describe(self):
        return forge_adapter.describe()

    def inspect(self, request):
        return forge_adapter.inspect(request)

    def invoke(self, request):
        result = forge_adapter.invoke(request)
        if result["result"] == "accepted":
            self.land(request)
        return result

    def land(self, request: dict) -> None:
        """Make the provider show what `request` created; a merge lands as a merge commit."""
        operation, candidate = request["operation"], request["parameters"]["candidate"]
        if operation == "pr_merge":
            self.world.respond_json("gh", ROWS["pr_merge.view"]["argv"][1:], {
                "state": "MERGED", "baseRefName": CANONICAL["branch"], "headRefName": "dev",
                "headRefOid": CANONICAL["commit"], "mergeCommit": {"oid": CANONICAL["merge_commit"]},
                "url": f"https://github.com/{CANONICAL['slug']}/pull/{CANONICAL['pr']}",
                "statusCheckRollup": []})
            self.world.respond_json("gh", ROWS["pr_merge.merge_commit"]["argv"][1:], {
                "parents": [{"sha": candidate["merge"]["base_tip"]}, {"sha": candidate["commit"]}]})
        elif operation == "tag":
            peeled = CANONICAL["merge_commit"] if "merge" in candidate else CANONICAL["commit"]
            self.world.respond_json("gh", ROWS["tag.ref"]["argv"][1:],
                                    {"object": {"type": "tag", "sha": CANONICAL["tag_object"]}})
            self.world.respond_json("gh", ROWS["tag.object"]["argv"][1:],
                                    {"object": {"type": "commit", "sha": peeled}})
        elif operation == "release":
            self.world.respond_json("gh", ROWS["release.view"]["argv"][1:],
                                    {"tag_name": CANONICAL["tag"], "draft": False, "html_url": URL})


class LandedDespiteExit(StatefulForge):
    """A merge that lands while `gh` exits non-zero: the provider shows it merged although the
    invoke answered `unknown`."""

    def invoke(self, request):
        result = forge_adapter.invoke(request)
        if result["result"] == "accepted" or request["operation"] == "pr_merge":
            self.land(request)
        return result


class NeverVisible(StatefulForge):
    """Publication succeeds, but `publication_visible` never reads satisfied."""

    def inspect(self, request):
        observation = forge_adapter.inspect(request)
        if request.get("kind") == "predicate":
            observation = {**observation, "outcome": "unknown", "reason": "store_unreachable"}
        return observation


def release(driver, candidate_doc=None):
    """Preview, then run with every token the preview lists; returns (preview, run)."""
    shown = driver.preview(candidate_doc)
    return shown, driver.run(candidate_doc, [c["token"] for c in shown["confirmations"]])


BASE_TIP = "5" * 40
MERGED_TIP = "3" * 40


class Crash(Exception):
    """A simulated process death: raised out of an adapter call, never caught by the driver."""


def _fixture_descriptor(name: str, operation: str, entry: dict, predicate: str,
                        target_kind: str, member: str, executable: str) -> dict:
    descriptor = copy.deepcopy(support.FIXTURE_STORE)
    reason = "no_activation_mode" if predicate == "publication_visible" else "no_publication"
    other = ("running_subject_identity" if predicate == "publication_visible"
             else "publication_visible")
    descriptor.update(
        name=name, operations={operation: entry},
        predicates={predicate: {"support": "supported", "reason": None},
                    other: {"support": "unsupported", "reason": reason}},
        target_kinds={target_kind: [member]}, executables=[executable])
    return descriptor


def _operation(mode: str, mutability: str, effect: str) -> dict:
    return {"mode": mode, "support": "supported", "inspect": "supported", "reason": None,
            "mutability": mutability, "config_schema_version": 1,
            "config_schema": {"members": {}, "required": []}, "effects": [effect],
            "recovery_capable": False, "candidate_members": []}


def _effect_observation(outcome: str, reason: str) -> dict:
    return {"outcome": outcome, "reason": reason, "observed_subject": {}, "references": [],
            "observed_at": 1, "facts": {}}


def _predicate_observation(satisfied: bool, absent_reason: str) -> dict:
    return {"outcome": "satisfied" if satisfied else "unsatisfied",
            "reason": "observed" if satisfied else absent_reason, "references": [],
            "observed_at": 1}


class FixtureMerge:
    """`fixture-merge`: a default-branch pointer whose merge is a compare-and-swap."""

    def __init__(self) -> None:
        self.default_tip = BASE_TIP
        self.mutations: list[str] = []

    def describe(self) -> dict:
        return _fixture_descriptor(
            "fixture-merge", "merge", _operation("materialize", "pointer_cas", "irreversible"),
            "publication_visible", "fixture_branch", "branch", "fixture-merge-cli")

    def inspect(self, request) -> dict:
        merged = self.default_tip == MERGED_TIP
        if request["kind"] == "predicate":
            return _predicate_observation(merged, "ref_absent")
        outcome = ("satisfied" if merged else "absent" if self.default_tip == BASE_TIP
                   else "diverged")
        return _effect_observation(outcome, f"default tip {self.default_tip}")

    def invoke(self, request) -> dict:
        if self.default_tip != BASE_TIP:
            return {"result": "rejected", "error_class": "precondition_failed",
                    "reference": "default tip moved"}
        self.default_tip = MERGED_TIP
        self.mutations.append("merge")
        return {"result": "accepted", "error_class": None, "reference": MERGED_TIP}


class FixtureDeploy:
    """`fixture-deploy`: a service that is either deployed or not."""

    def __init__(self) -> None:
        self.deployed = False
        self.mutations: list[str] = []

    def describe(self) -> dict:
        return _fixture_descriptor(
            "fixture-deploy", "deploy",
            _operation("provider_deploy", "in_place", "reversible_no_incremental_spend"),
            "running_subject_identity", "fixture_service", "service", "fixture-deploy-cli")

    def inspect(self, request) -> dict:
        if request["kind"] == "predicate":
            return _predicate_observation(self.deployed, "subject_absent")
        return _effect_observation("satisfied" if self.deployed else "absent",
                                   "deployed" if self.deployed else "not deployed")

    def invoke(self, request) -> dict:
        self.deployed = True
        self.mutations.append("deploy")
        return {"result": "accepted", "error_class": None, "reference": "deployed"}


class CrashAt:
    """Wraps a registry entry: the first invoke of `operation` delegates (after=True) or not
    (after=False), then raises Crash; describe, inspect and later invokes pass through."""

    def __init__(self, inner, operation: str, *, after: bool = True) -> None:
        self.inner = inner
        self.operation = operation
        self.after = after
        self.crashed = False

    def describe(self):
        return self.inner.describe()

    def inspect(self, request):
        return self.inner.inspect(request)

    def invoke(self, request):
        if self.crashed or request["operation"] != self.operation:
            return self.inner.invoke(request)
        self.crashed = True
        if self.after:
            self.inner.invoke(request)
        raise Crash(self.operation)


def fixture_profile() -> dict:
    """merge -> tag -> github-release, then an activation unit `deploy`."""
    profile = support.forge_profile()
    ranges = {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0"}
    profile["requirements"]["adapters"].update(merge=ranges, deploy=ranges)
    bindings = profile["bindings"]
    bindings["adapters"].update(merge={"adapter": "fixture-merge"},
                                deploy={"adapter": "fixture-deploy"})
    bindings["targets"].update(
        trunk={"adapter": "merge", "kind": "fixture_branch", "branch": "main"},
        service={"adapter": "deploy", "kind": "fixture_service", "service": "site"})
    bindings["principals"]["deployer"] = {"class": "fixture_deployer"}
    bindings["credentials"].update(
        **{"merge-token": {"adapter": "merge", "class": "fixture_token"},
           "deploy-token": {"adapter": "deploy", "class": "fixture_token"}})

    def node(identity, mode, adapter, operation, target, credential, effect, deps):
        return {"id": identity, "mode": mode, "adapter": adapter, "operation": operation,
                "target": target, "principal": "deployer", "credential": credential,
                "effect": effect, "config_schema_version": 1, "config": {}, "deps": deps,
                "observation_deadline_ms": 600000}

    actions = profile["publication"]["actions"]
    actions[0]["deps"] = ["merge"]
    actions.insert(0, node("merge", "materialize", "merge", "merge", "trunk", "merge-token",
                           "irreversible", []))
    profile["activation"] = {"units": [node(
        "deploy", "provider_deploy", "deploy", "deploy", "service", "deploy-token",
        "reversible_no_incremental_spend", [])]}
    unit = {"posture": "supersedable_only", "anchor": None, "compatibility": None, "edges": []}
    profile["recovery"]["units"].update(merge=dict(unit), deploy=dict(unit))
    return profile


def forge_merge_profile() -> dict:
    """`fixture_profile()` with its `merge` node on the forge's `pr_merge`; `deploy` stays."""
    profile = fixture_profile()
    for node in profile["publication"]["actions"]:
        if node["id"] == "merge":
            node.update(adapter="forge", operation="pr_merge", target="repository",
                        principal="maintainer", credential="forge-keyring")
    requirements, bindings = profile["requirements"]["adapters"], profile["bindings"]
    del requirements["merge"], bindings["adapters"]["merge"], bindings["targets"]["trunk"]
    del bindings["credentials"]["merge-token"]
    return profile
