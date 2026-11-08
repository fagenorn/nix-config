"""Shared fixtures for the release profile suites (#124).

Every function returns a fresh deep copy, so a test may mutate what it receives.
The JSON files under `fixtures/release/` are loaded by path, so the suites under
`home/common/agent-skills/tests/` read the same data.
"""
import copy
import json
from pathlib import Path

from agent_tools import forge_adapter

FIXTURES = Path(__file__).parent / "fixtures/release"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


FIXTURE_STORE = _load("fixture-store-descriptor.json")


def descriptors() -> dict:
    return {"github-forge": forge_adapter.describe(), "fixture-store": copy.deepcopy(FIXTURE_STORE)}


def base_contract() -> dict:
    return {"bindings": {"tracker": {"kind": "github", "repo_slug": "fagenorn/nix-config",
                                 "credential_env": {"unset_before_invocation": []}},
                         "vcs": {"default_branch": "main"}},
            "capabilities": {"deploy": {"support": "unsupported"}}}


def forge_profile() -> dict:
    return _load("github-release-profile.json")


MERGE = {"pr": 336, "base_tip": "5" * 40}


def merge_profile() -> dict:
    """The JarBird shape: `pr_merge` -> `tag` -> `github-release` on one forge target."""
    profile = forge_profile()
    actions = profile["publication"]["actions"]
    actions[0]["deps"] = ["merge"]
    actions.insert(0, {
        "id": "merge", "mode": "materialize", "adapter": "forge", "operation": "pr_merge",
        "target": "repository", "principal": "maintainer", "credential": "forge-keyring",
        "effect": "irreversible", "config_schema_version": 1, "config": {}, "deps": [],
        "observation_deadline_ms": 600000})
    units = profile["recovery"]["units"]
    units["merge"] = copy.deepcopy(units["tag"])
    return profile


WATCH_CONFIG = {"workflow": "deploy.yml", "branch": "main", "services": ["site"],
                "health_url": "https://example.com/health", "health_commit_field": "commit"}


def _watch(profile: dict, config: dict) -> dict:
    """`profile` plus a github-actions-health activation unit `deploy` on alias `watch` (issue 555)."""
    profile["requirements"]["adapters"]["watch"] = {"min_inclusive": "1.1.0",
                                                    "max_exclusive": "2.0.0"}
    bindings = profile["bindings"]
    bindings["adapters"]["watch"] = {"adapter": "github-actions-health"}
    bindings["targets"]["site"] = {"adapter": "watch", "kind": "github_repository",
                                   "repository": "fagenorn/nix-config", "branch": "main"}
    bindings["credentials"]["gh-cli"] = {"adapter": "watch", "class": "gh_cli"}
    profile["activation"] = {"units": [{
        "id": "deploy", "mode": "publication_triggered", "adapter": "watch",
        "operation": "deploy", "target": "site", "principal": "maintainer",
        "credential": "gh-cli", "effect": "reversible_no_incremental_spend",
        "config_schema_version": 1, "config": {**copy.deepcopy(WATCH_CONFIG), **config},
        "deps": [], "observation_deadline_ms": 600000}]}
    profile["recovery"]["units"]["deploy"] = {"posture": "supersedable_only", "anchor": None,
                                              "compatibility": None, "edges": []}
    return profile


def watched_profile(**config: object) -> dict:
    """The forge profile whose deploy is a github-actions-health watch (issue 555)."""
    return _watch(forge_profile(), config)


def watched_merge_profile(**config: object) -> dict:
    """The JarBird shape: `pr_merge` -> `tag` -> `github-release`, then the watch (issue 555)."""
    return _watch(merge_profile(), config)


RAILWAY_CONFIG = {"project": "nodo-prod", "environment": "production",
                  "services": ["api", "admin"]}


def _railway(profile: dict) -> dict:
    """`profile` plus a railway-deploy activation unit `deploy` on alias `railway` (issue 582)."""
    profile["requirements"]["adapters"]["railway"] = {"min_inclusive": "1.0.0",
                                                      "max_exclusive": "2.0.0"}
    bindings = profile["bindings"]
    bindings["adapters"]["railway"] = {"adapter": "railway-deploy"}
    bindings["targets"]["railway-site"] = {"adapter": "railway", "kind": "github_repository",
                                           "repository": "fagenorn/nix-config", "branch": "main"}
    bindings["credentials"]["railway-cli"] = {"adapter": "railway", "class": "railway_cli"}
    profile["activation"] = {"units": [{
        "id": "deploy", "mode": "publication_triggered", "adapter": "railway",
        "operation": "deploy", "target": "railway-site", "principal": "maintainer",
        "credential": "railway-cli", "effect": "reversible_no_incremental_spend",
        "config_schema_version": 1, "config": copy.deepcopy(RAILWAY_CONFIG), "deps": [],
        "observation_deadline_ms": 600000}]}
    profile["recovery"]["units"]["deploy"] = {"posture": "supersedable_only", "anchor": None,
                                              "compatibility": None, "edges": []}
    return profile


def railway_watched_profile() -> dict:
    """The forge profile whose deploy is a railway-deploy watch (issue 582)."""
    return _railway(forge_profile())


def railway_watched_merge_profile() -> dict:
    """The JarBird shape (`pr_merge` -> `tag` -> `github-release`), then the Railway watch."""
    return _railway(merge_profile())


def publication_free_profile() -> dict:
    return _load("publication-free-profile.json")


def argus_shaped_profile() -> dict:
    return _load("argus-shaped-profile.json")


def restorable_profile() -> dict:
    return _load("restorable-profile.json")


def destroyed_anchor_profile() -> dict:
    return _load("destroyed-anchor-profile.json")


CANDIDATE = {"version": "v1.2.3", "commit": "1" * 40, "title": "v1.2.3 \u2014 release",
             "notes": "notes body"}


def derived_class_profile() -> dict:
    profile = forge_profile()
    profile["proof"]["obligations"].append({
        "id": "visible", "semantic": "published_artifact_identity", "form": "event",
        "predicate": "release_visible", "collector": "forge", "required": True, "deps": [],
        "parameters": {}})
    return profile


def missing_deadline_profile() -> dict:
    profile = forge_profile()
    del profile["publication"]["actions"][0]["observation_deadline_ms"]
    return profile


def unreachable_rollback_profile() -> dict:
    profile = restorable_profile()
    profile["recovery"]["units"]["publish-artifact"] = {
        "posture": "supersedable_only", "anchor": None, "compatibility": None, "edges": []}
    return profile


def release_of(profile_id: str, profile: dict) -> dict:
    return {"profiles": {profile_id: copy.deepcopy(profile)}}
