# Cross-repository parent transactions — not sliced in the #59 build

**Idea:** slice decision #87 (release sets, sealed version-set manifests, durable claims, common-cutoff aggregate proof) into an implementation issue alongside the rest of the #59 breakdown.

**Deferred (not rejected):** 2026-08-24, while breaking map #59 into issues. #87 is the deepest leaf in the decision graph and has no forcing function in the rollout — no cross-repository release ran in the preceding two weeks, and the capability exists once the transaction core (#123) and profiles (#124) ship. An issue filed now would sit blocked for months and rot. Revive by slicing #87 against the shipped core once one real cross-repo change needs it; the decision itself stands unchanged.

**Links:** https://github.com/fagenorn/nix-config/issues/87 (the decision), https://github.com/fagenorn/nix-config/issues/59 (the map), https://github.com/fagenorn/nix-config/issues/123 (the core it would build on).
