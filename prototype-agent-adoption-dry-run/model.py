"""Pure adoption-plan model for the issue #79 throwaway prototype."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class Evidence:
    path: str
    provenance: str
    lifecycle_class: str
    action: str | None
    target: str | None
    count: int
    fingerprint: str | None
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "provenance": self.provenance,
            "lifecycle_class": self.lifecycle_class,
            "action": self.action,
            "target": self.target,
            "count": self.count,
            "fingerprint": self.fingerprint,
            "note": self.note,
        }


def aggregate_fingerprint(entries: Iterable[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for path, object_id in sorted(entries):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(object_id.encode("ascii"))
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def tracked_group(path: str) -> str | None:
    if path == "CLAUDE.md":
        return "CLAUDE.md"
    if path == "AGENTS.md":
        return "AGENTS.md"
    if path == ".claude/skills.config.json":
        return ".claude/skills.config.json"
    if path.startswith(".claude/specs/"):
        return ".claude/specs/**"
    if path.startswith(".claude/plans/"):
        return ".claude/plans/**"
    if path.startswith(".out-of-scope/"):
        return ".out-of-scope/**"
    if path.startswith("home/common/agent-skills/"):
        return "home/common/agent-skills/**"
    if path.startswith("home/common/agent-guidance/"):
        return "home/common/agent-guidance/**"
    if path.startswith("home/common/claude-code/"):
        return "home/common/claude-code/**"
    if path.startswith("patches/agent-plugins/") or path == "lib/agent-plugins.nix":
        return "shared native-adapter sources"
    if path in {
        ".github/branch-protection.json",
        ".github/workflows/ci.yaml",
        "justfile",
    }:
        return path
    return None


def evidence_for_tracked_group(
    group: str, entries: list[tuple[str, str]]
) -> Evidence:
    fingerprint = aggregate_fingerprint(entries)
    count = len(entries)
    if group == "CLAUDE.md":
        return Evidence(
            group,
            "tracked",
            "canonical-tracked",
            "move-canonical",
            ".agents/instructions/bootstrap.md + selected knowledge/command bindings",
            count,
            fingerprint,
            "Authored project truth currently mixes standing instructions, architecture, commands, and scoped guidance.",
        )
    if group == "AGENTS.md":
        return Evidence(
            group,
            "tracked",
            "native-projection",
            "generate-projection",
            "AGENTS.md",
            count,
            fingerprint,
            "Existing native entrypoint must become a byte-verified projection.",
        )
    if group == ".claude/skills.config.json":
        return Evidence(
            group,
            "tracked",
            "canonical-tracked",
            "move-canonical",
            ".agents/project.json",
            count,
            fingerprint,
            "Authored orchestration values move into the explicit source contract; detected/defaulted policy becomes explicit.",
        )
    if group == ".claude/specs/**":
        return Evidence(
            group,
            "tracked",
            "durable-artifact",
            "move-canonical",
            ".agents/artifacts/specs/**",
            count,
            fingerprint,
            "Accepted point-in-time records move with Git history and retain their bytes.",
        )
    if group == ".claude/plans/**":
        return Evidence(
            group,
            "tracked",
            "durable-artifact",
            "move-canonical",
            ".agents/artifacts/plans/**",
            count,
            fingerprint,
            "Accepted point-in-time records move with Git history and retain their bytes.",
        )
    if group == ".out-of-scope/**":
        return Evidence(
            group,
            "tracked",
            "canonical-tracked",
            "move-canonical",
            ".agents/knowledge/rejections/**",
            count,
            fingerprint,
            "The existing rejection knowledge base already matches the named canonical class.",
        )
    if group.startswith("home/common/") or group == "shared native-adapter sources":
        return Evidence(
            group,
            "tracked",
            "product-source",
            "retain-product",
            group,
            count,
            fingerprint,
            "This repository builds the shared platform; it is product source, not repo-local project truth.",
        )
    return Evidence(
        group,
        "tracked",
        "binding-evidence",
        None,
        None,
        count,
        fingerprint,
        "Observable evidence for explicit commands, workflow policy, or verification bindings; not a migration candidate itself.",
    )


def input_digest(base_revision: str, evidence: list[Evidence]) -> str:
    normalized = {
        "base_revision": base_revision,
        "evidence": [item.as_dict() for item in evidence],
    }
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def proposed_project(project_id: str) -> dict[str, Any]:
    return {
        "project_schema_version": 1,
        "project": {"id": project_id},
        "platform": {
            "min_inclusive": "<active-platform-version>",
            "max_exclusive": "<next-platform-major>",
        },
        "bindings": {
            "vcs": {
                "integration_branch": "main",
                "default_branch": "main",
                "branch_pattern": "issue-<num>-<slug>",
                "worktree_prefix": "worktree-",
                "co_authored_by": True,
            },
            "tracker": {
                "kind": "github",
                "cli": "gh",
                "repo_slug": "fagenorn/nix-config",
                "credential_environment": ["GH_TOKEN", "GITHUB_TOKEN"],
            },
            "paths": {
                "specs": ".agents/artifacts/specs",
                "plans": ".agents/artifacts/plans",
                "evidence": ".agents/artifacts/evidence",
                "rejections": ".agents/knowledge/rejections",
                "architecture": ".agents/knowledge/guides/architecture.md",
                "standards": ".agents/knowledge/standards",
            },
            "commands": {
                "verify.agent_workflow": {
                    "argv": ["just", "agent-workflow-tests"],
                    "cwd": ".",
                    "env_names": [],
                },
                "verify.nix": {
                    "argv": ["just", "build"],
                    "cwd": ".",
                    "env_names": [],
                },
                "deploy.switch": {
                    "argv": ["just", "switch"],
                    "cwd": ".",
                    "env_names": [],
                },
            },
            "workflow": {
                "agent_budget_minutes": 180,
                "max_parallel": 2,
                "review": "required",
                "release": "unsupported",
            },
            "deploy": {"adapter": "nix-switch", "target": "host-detected"},
        },
        "capabilities": {
            "tracker": "supported",
            "worktrees": "supported",
            "orchestration": "supported",
            "knowledge.context": "supported",
            "knowledge.standards": "supported",
            "knowledge.architecture": "supported",
            "knowledge.hints": "unsupported",
            "verification": "supported",
            "review.plan": "supported",
            "review.code": "supported",
            "release": "unsupported",
            "deploy": "supported",
        },
        "instructions": {"bootstrap": ".agents/instructions/bootstrap.md", "scopes": []},
        "native_projections": [
            "AGENTS.md",
            "CLAUDE.md",
            ".claude/settings.json",
            ".codex/config.toml",
        ],
    }


def build_plan(snapshot: dict[str, Any]) -> dict[str, Any]:
    evidence = snapshot["evidence"]
    blockers = list(snapshot["blockers"])
    project_id = snapshot["project_id"]
    project_preview = proposed_project(project_id)
    if snapshot["untracked_agent_paths"]:
        blockers.append(
            {
                "id": "dirty-agent-development-overlap",
                "repair_id": "adopt.reconcile-working-tree",
                "facts": snapshot["untracked_agent_paths"],
            }
        )
    blockers.append(
        {
            "id": "platform-manifest-not-yet-published",
            "repair_id": "platform.publish-manifest",
            "facts": ["platform_version", "supported project schemas", "ResolvedProject schema"],
        }
    )

    return {
        "schema_version": 1,
        "plan": {
            "state": "draft",
            "mode": "reconcile",
            "repo": snapshot["root"],
            "base_revision": snapshot["base_revision"],
            "platform": "prototype-unavailable",
            "input_digest": input_digest(snapshot["base_revision"], evidence),
            "blockers": blockers,
            "proposed_project_json": project_preview,
        },
        "evidence": [item.as_dict() for item in evidence],
        "decisions": {
            "recommended": [
                {
                    "id": "project-id",
                    "value": project_id,
                    "basis": "single unambiguous primary GitHub remote",
                },
                {
                    "id": "legacy-guidance-routing",
                    "value": "decompose CLAUDE.md into bootstrap, knowledge, command, and scoped policy homes",
                    "basis": "section roles and the closed .agents taxonomy",
                },
            ],
            "answered": [],
            "open": [],
            "gap_verdict": {
                "missing_bindings": [],
                "missing_capabilities": [],
                "missing_artifact_classes": [],
                "covered_edge_cases": [
                    "shared platform source is retain-product",
                    "ignored native permission policy is canonical adapter input plus tracked projection",
                    "legacy workflow state and worktrees are metadata-only runtime residue routed to doctor",
                    "untracked research specs are durable-artifact inputs that block readiness until reconciled",
                    "orchestration is the neutral capability already named by decision #64",
                ],
                "prototype_answer": "none",
                "human_verdict": "pending",
            },
        },
        "changes": [
            {
                "type": "author-contract",
                "sources": [".claude/skills.config.json", "Git metadata", "CLAUDE.md", "justfile"],
                "targets": [".agents/project.json"],
                "approval_class": "normal",
            },
            {
                "type": "route-canonical-guidance",
                "sources": ["CLAUDE.md", ".out-of-scope/**"],
                "targets": [
                    ".agents/instructions/bootstrap.md",
                    ".agents/knowledge/guides/**",
                    ".agents/knowledge/standards/**",
                    ".agents/knowledge/rejections/**",
                ],
                "approval_class": "normal",
            },
            {
                "type": "git-move-durable-artifacts",
                "sources": [".claude/specs/**", ".claude/plans/**"],
                "targets": [".agents/artifacts/specs/**", ".agents/artifacts/plans/**"],
                "approval_class": "normal",
            },
            {
                "type": "canonicalize-native-policy",
                "sources": [".claude/settings.local.json"],
                "targets": [".agents/adapters/claude/**", ".claude/settings.json"],
                "approval_class": "normal",
            },
            {
                "type": "generate-native-projections",
                "sources": [".agents/project.json", ".agents/instructions/**", ".agents/adapters/**"],
                "targets": ["AGENTS.md", "CLAUDE.md", ".claude/**", ".codex/**"],
                "approval_class": "normal",
            },
            {
                "type": "establish-runtime-sentinel",
                "sources": [],
                "targets": [".agents/runtime/.gitignore"],
                "approval_class": "normal",
            },
            {
                "type": "preserve-product-source",
                "sources": ["home/common/agent-*/**", "home/common/claude-code/**", "patches/agent-plugins/**"],
                "targets": ["same paths"],
                "approval_class": "normal",
            },
        ],
        "verification": {
            "purpose": "adoption",
            "checks": [
                {"id": "inventory-bounds", "status": "passed"},
                {"id": "agent-development-classification", "status": "passed"},
                {"id": "working-tree-overlap", "status": "failed" if snapshot["untracked_agent_paths"] else "passed"},
                {"id": "platform-compatibility", "status": "not_run", "repair_id": "platform.publish-manifest"},
                {"id": "projection-byte-conformance", "status": "suppressed", "blocked_by": "platform-compatibility"},
                {"id": "tracked-only-cold-clone", "status": "suppressed", "blocked_by": "platform-compatibility"},
                {"id": "resolved-project", "status": "suppressed", "blocked_by": "platform-compatibility"},
                {"id": "verify.agent_workflow", "status": "not_run"},
                {"id": "verify.nix", "status": "not_run"},
            ],
        },
        "handoff": {
            "state": "prototype_review_required",
            "artifact": "prototype-agent-adoption-dry-run",
            "next_command": f"just prototype-agent-adoption-dry-run {snapshot['root']}",
            "review_questions": [
                "Does every current surface have a truthful classification and destination?",
                "Does the empty binding/capability/artifact-class gap verdict match what the concrete inventory shows?",
            ],
        },
    }


VIEW_KEYS = {
    "s": "summary",
    "p": "project",
    "c": "classifications",
    "q": "questions",
    "o": "operations",
    "v": "verification",
    "h": "handoff",
    "g": "gaps",
}


def reduce_view(current: str, key: str) -> tuple[str, bool]:
    if key == "x":
        return current, True
    return VIEW_KEYS.get(key, current), False
