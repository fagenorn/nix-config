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
    return {"bindings": {"tracker": {"kind": "github", "repo_slug": "fagenorn/nix-config"},
                         "vcs": {"default_branch": "main"}},
            "capabilities": {"deploy": {"support": "unsupported"}}}


def forge_profile() -> dict:
    return _load("github-release-profile.json")


def restorable_profile() -> dict:
    return _load("restorable-profile.json")


def destroyed_anchor_profile() -> dict:
    return _load("destroyed-anchor-profile.json")


def release_of(profile_id: str, profile: dict) -> dict:
    return {"profiles": {profile_id: copy.deepcopy(profile)}}
