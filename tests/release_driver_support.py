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


def project(case, *, profiles=None, integration="main", default="main",
            deploy_adapter="none") -> release_driver.Project:
    scratch = tempfile.TemporaryDirectory()
    case.addCleanup(scratch.cleanup)
    root = Path(scratch.name).resolve() / "checkout"
    (root / ".git").mkdir(parents=True)
    profiles = {"github-release": support.forge_profile()} if profiles is None else profiles
    return release_driver.Project(
        project_id=PROJECT_ID, root=root, common_dir=root / ".git",
        integration_branch=integration, default_branch=default,
        deploy_adapter=deploy_adapter,
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
            self.land(request["operation"])
        return result

    def land(self, operation: str) -> None:
        if operation == "tag":
            self.world.respond_json("gh", ROWS["tag.ref"]["argv"][1:],
                                    {"object": {"type": "tag", "sha": CANONICAL["tag_object"]}})
            self.world.respond_json("gh", ROWS["tag.object"]["argv"][1:],
                                    {"object": {"type": "commit", "sha": CANONICAL["commit"]}})
        elif operation == "release":
            self.world.respond_json("gh", ROWS["release.view"]["argv"][1:],
                                    {"tag_name": CANONICAL["tag"], "draft": False, "html_url": URL})


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
