"""The legacy `deploy` bridge (#124 D6, D13, D14, D23).

`.claude/skills.config.json` once carried a `deploy` member. A release profile now says
what that member said, so the bridge answers two questions without inventing a value:
which `release` an adoption can propose from a legacy file (`plan_legacy_release`) and what
the legacy file is once the contract's `release` owns the deploy intent
(`project_legacy_deploy`). Both functions are pure; a legacy shape the forge-only profile
cannot represent becomes a question, never a value (D13). Standard library plus
`adopt_inspection.authored_bytes` and `release_adapter`.
"""

import copy
import json

from agent_tools import release_adapter
from agent_tools.adopt_inspection import authored_bytes

BRIDGE_QUESTION_IDS = (
    "release.legacy_unreadable",
    "release.deploy_adapter_unrepresentable",
    "release.watch_doc_to_operations",
    "release.forge_unavailable",
)

FORGE_ADAPTER = "github-forge"
PROFILE_ID = "github-release"
NO_RENDERING = "release profile has no legacy deploy rendering"


def forge_only_profile(contract: dict) -> dict:
    """The spec §4 profile: tag then GitHub Release on the tracker repository, no activation."""
    bindings = contract["bindings"]
    slug = bindings["tracker"]["repo_slug"]
    branch = bindings["vcs"]["default_branch"]
    def action(action_id: str, operation: str, deps: list[str]) -> dict:
        return {"id": action_id, "mode": "index", "adapter": "forge", "operation": operation,
                "target": "repository", "principal": "maintainer", "credential": "forge-keyring",
                "effect": "irreversible", "config_schema_version": 1, "config": {},
                "deps": deps, "observation_deadline_ms": 600000}

    unit = {"posture": "supersedable_only", "anchor": None, "compatibility": None, "edges": []}
    return {
        "profile_version": 1,
        "target": {"environment": "github-" + branch,
                   "concurrency_keys": ["release/" + slug]},
        "requirements": {"adapters": {"forge": {"min_inclusive": "1.0.0",
                                                "max_exclusive": "2.0.0"}}},
        "bindings": {
            "adapters": {"forge": {"adapter": FORGE_ADAPTER}},
            "targets": {"repository": {"adapter": "forge", "kind": "github_repository",
                                       "repository": slug, "branch": branch}},
            "principals": {"maintainer": {"class": "forge_write"}},
            "credentials": {"forge-keyring": {"adapter": "forge", "class": "gh_keyring"}},
        },
        "publication": {"actions": [
            action("tag", "tag", []),
            action("github-release", "release", ["tag"]),
        ]},
        "activation": "none",
        "proof": {"convergence_window_ms": 1800000, "obligations": []},
        "recovery": {"units": {"tag": dict(unit), "github-release": dict(unit)}},
        "limits": {},
    }


def _question(question_id: str, pointer: str) -> dict:
    assert question_id in BRIDGE_QUESTION_IDS
    return {"id": question_id, "pointer": pointer}


def plan_legacy_release(legacy_bytes: bytes | None, contract: dict) -> dict:
    """The `release` an adoption can propose from the legacy file, and what it must ask."""
    unreadable = {"release": None,
                  "questions": [_question("release.legacy_unreadable", "")]}
    if legacy_bytes is None:
        legacy = {}
    else:
        try:
            legacy = json.loads(legacy_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return unreadable
        if not isinstance(legacy, dict):
            return unreadable
    deploy = legacy.get("deploy", {})
    questions = []
    unrepresentable = (not isinstance(deploy, dict)
                       or any(member not in ("adapter", "watchDoc") for member in deploy)
                       or ("adapter" in deploy and deploy["adapter"] != "none"))
    if isinstance(deploy, dict) and "watchDoc" in deploy:
        questions.append(_question("release.watch_doc_to_operations", "/deploy/watchDoc"))
    if unrepresentable:
        questions.append(_question("release.deploy_adapter_unrepresentable", "/deploy"))
    release = None
    if not unrepresentable:
        if contract["bindings"]["tracker"].get("kind") == "github":
            release = {"profiles": {PROFILE_ID: forge_only_profile(contract)}}
        else:
            questions.append(_question("release.forge_unavailable", "/deploy"))
    questions.sort(key=lambda question: question["pointer"])
    return {"release": release, "questions": questions}


def _renders_absent(release: object) -> bool:
    """True when every profile binds only forge adapters and activates nothing."""
    profiles = release.get("profiles") if isinstance(release, dict) else None
    if not isinstance(profiles, dict):
        return False
    for profile in profiles.values():
        if not isinstance(profile, dict) or profile.get("activation") != "none":
            return False
        adapters = (profile.get("bindings") or {}).get("adapters")
        if not isinstance(adapters, dict) or not all(
                isinstance(binding, dict) and binding.get("adapter") == FORGE_ADAPTER
                for binding in adapters.values()):
            return False
    return FORGE_ADAPTER in release_adapter.REGISTRY


def project_legacy_deploy(legacy_bytes: bytes, release: object) -> bytes:
    """The legacy file once `release` owns the deploy intent: the `deploy` member is absent."""
    if release == "unsupported":
        return legacy_bytes
    if not _renders_absent(release):
        raise ValueError(NO_RENDERING)
    try:
        legacy = json.loads(legacy_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("legacy skills config is not UTF-8 JSON") from error
    if not isinstance(legacy, dict):
        raise ValueError("legacy skills config is not a JSON object")
    if "deploy" not in legacy:
        return legacy_bytes
    return authored_bytes({key: value for key, value in copy.deepcopy(legacy).items()
                           if key != "deploy"})
