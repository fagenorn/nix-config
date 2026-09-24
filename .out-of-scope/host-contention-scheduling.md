# Host-capacity contention scheduling — outside the #59 build

**Idea:** fold host-resource scheduling into the #59 project-system build — throttling concurrent agent runs on nix-daemon and test-host load, so wall-clock attempt budgets are not consumed by build contention rather than by work.

**Deferred (not rejected):** 2026-08-24, while breaking map #59 into issues. The pain is real and documented — parallel worktree builds ran 3–13 minutes each under nix-daemon contention and consumed whole attempt windows; a concurrent sweep drove load to 71 on 10 cores and poisoned neighbouring runs into flaking. But it is a fleet-operations problem, not a project-contract problem: nothing in the #59 decisions models host capacity, and adding it would blur a scope the wayfind kept deliberately narrow. Revive as its own wayfind decision ticket (host truth domain in the conformance engine plus an orchestration admission control), grounded in the conformance engine's `host` domain once #122 ships.

**Boundary with #150 (2026-09-24):** issue #150 adds admission over declared *agent slots* only: how many concurrent agents a root session may run. It schedules no CPU, memory, Nix-daemon or test-host load, so this deferral still stands in full. A revival may read the #150 host declaration, but it must not make that declaration a load scheduler.

**Links:** https://github.com/fagenorn/nix-config/issues/150 (agent-slot admission), https://github.com/fagenorn/nix-config/issues/59 (the map), https://github.com/fagenorn/nix-config/issues/122 (the conformance engine's host domain), https://github.com/fagenorn/nix-config/issues/69 (host truth domain decision).
