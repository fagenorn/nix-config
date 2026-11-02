# Task 8: Guard arms, the D5 repair, `PATH` wiring and ship-release 4.5f

**Files:**
- Modify: `home/common/claude-code/lifecycle_guard.py`
- Modify: `home/common/claude-code/default.nix` (`home.packages` gains `lifecycleGuard`)
- Modify: `home/common/claude-code/README.md` (`## Adjudicated verbs`)
- Test: `tests/test_claude_permission_guard.py`
- Modify: `home/common/agent-skills/skills/ship-release/SKILL.md` (§4.5f code block and its next sentence only) and `home/common/agent-skills/tests/test_ship_release_contracts.py`

Decisions: D9, D10, D12, D21, D22. Spec §8. AC4 is owned here.

**Interfaces:**
- Consumes: `tests/fixtures/forge-adapter-spellings.json` (Tasks 6–7: `canonical` + 11 rows); the guard's existing `GUARDED_LITERALS`, `GUARDED_TOKEN_LITERALS`, `OPERATION_LABELS`, `validate_push`, `validate_merge`, `free_text_problem`, `ownership_problem`, `UNSAFE_BRANCH_CHARS`, `UNSAFE_TEXT_CHARS`.
- Produces: guarded operation `"release"` (label `"release creation"`); the tag-push arm inside `validate_push`; `claude-bash-lifecycle-guard` on `PATH` after switch (the adapter and the resolver find it by name).

**Invariants:**
- Standard library only; no `agent_tools` import; no fixture read at run time (D9).
- **Tag-push arm** (judged inside `validate_push` before the branch arm): argv exactly `["git", "push", "origin", "refs/tags/<tag>"]`, `<tag>` matching `^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$`, owner authorized, and `git cat-file -t refs/tags/<tag>` (policy `git_bin`, cwd = payload cwd, child timeout) printing exactly `tag`; otherwise blocked `unsafe push: …`. Other namespaced pushes keep today's refusal; the branch arm (incl. the legacy `git push origin <tag>`) is unchanged.
- **Release-creation arm**: `("gh release create", "release")` and `(["gh", "release", "create"], "release")` join the literal tables; it judges the **whole command** like `validate_merge` (D24): after stripping the optional `UNSET_GITHUB_TOKEN_PREFIX`, it must be exactly `gh release create <tag> --repo <detected slug> --verify-tag --title "<title>" --notes-file <path>` — flags in that order, nothing after, `shlex.split(segment)` equal to the argv rebuilt from the parsed parts, `<tag>` SemVer as above, owner authorized, `free_text_problem(title, False) is None`, `<path>` absolute with no character of `UNSAFE_BRANCH_CHARS` and no whitespace. Nothing else may precede or follow.
- **D5 repair (#116 D5)**: on the feature arm (`--delete-branch`), after the existing PR lookup, a `headRefName` equal to the default branch or to the repository's declared integration base blocks `unsafe merge: --delete-branch would delete the permanent branch <head>`, before any protection lookup.
- `home.packages` adds the existing `lifecycleGuard` derivation; the registered hook path and the allow surface are unchanged (`EXPECTED_ALLOW` stays green).

- [ ] **Step 1: Write the failing tests** in `tests/test_claude_permission_guard.py` (inside `ClaudePermissionGuardTest`):

```python
    SPELLINGS = json.loads((Path(__file__).parent / "fixtures/forge-adapter-spellings.json")
                           .read_text(encoding="utf-8"))
    CANONICAL_SLUG = SPELLINGS["canonical"]["slug"]
    REPOSITORY_CLASSES = (  # (class, slug, authorized, env), D22
        ("default-only", "fagenorn/nix-config", True, {}),
        ("distinct-integration", "elevenyellow/nodocom", True, {}),
        ("protection-inaccessible", "fagenorn/nix-config", True, {"FAKE_PROTECTION_MODE": "nonzero"}),
        ("other-owner", "someone-else/nix-config", False, {}),
    )

    def tagged_repo(self, slug, tag="v1.2.3", annotated=True):
        repo = self.make_repo(f"git@github.com:{slug}.git")
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet",
                        "--allow-empty", "-m", "init"], cwd=repo, check=True, capture_output=True)
        argv = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "tag"]
        argv += ["-a", tag, "-m", "release"] if annotated else [tag]
        subprocess.run(argv, cwd=repo, check=True, capture_output=True)
        return repo

    def test_every_adapter_spelling_is_an_allowed_row(self):
        """AC4, D12: one fixture drives the adapter suite and this table."""
        for name, slug, authorized, env in self.REPOSITORY_CLASSES:
            repo = self.tagged_repo(slug)
            for row in self.SPELLINGS["rows"]:
                raw = row["raw"].replace(self.CANONICAL_SLUG, slug)
                with self.subTest(repository=name, row=row["id"]):
                    result = self.run_guard(raw, cwd=repo, env=env)
                    expect_allowed = authorized or row["kind"] == "read"
                    self.assertEqual(0 if expect_allowed else 2, result.returncode, result.stderr)

    def test_tag_push_near_misses_are_refused(self):
        repo = self.tagged_repo("fagenorn/nix-config")
        lightweight = self.tagged_repo("fagenorn/nix-config", tag="v2.0.0", annotated=False)
        for command, cwd in (
                ("git push origin refs/tags/v2.0.0", lightweight),
                ("git push origin refs/tags/v1.2", repo),
                ("git push origin refs/tags/release-1", repo),
                ("git push origin refs/heads/v1.2.3", repo),
                ("git push origin +refs/tags/v1.2.3", repo),
                ("git push origin refs/tags/v1.2.3 extra", repo),
                ("git push --force origin refs/tags/v1.2.3", repo),
                ("git push origin refs/tags/v9.9.9", repo)):
            with self.subTest(command=command):
                self.assertEqual(2, self.run_guard(command, cwd=cwd).returncode)
        other = self.tagged_repo("someone-else/nix-config")
        self.assertEqual(2, self.run_guard("git push origin refs/tags/v1.2.3", cwd=other).returncode)

    def test_release_create_near_misses_are_refused(self):
        repo = self.tagged_repo("fagenorn/nix-config")
        base = 'gh release create v1.2.3 --repo fagenorn/nix-config --verify-tag --title "v1.2.3 — r" --notes-file /tmp/n.md'
        self.assertEqual(0, self.run_guard(base, cwd=repo).returncode)
        self.assertEqual(0, self.run_guard("unset GITHUB_TOKEN && " + base, cwd=repo).returncode)
        for command in (
                base.replace(" --verify-tag", ""),
                base.replace("--verify-tag --title", "--title").replace("/tmp/n.md", "/tmp/n.md --verify-tag"),
                base.replace("--verify-tag", "--target main"),
                base.replace("--repo fagenorn/nix-config", "--repo fagenorn/other"),
                base.replace('"v1.2.3 — r"', '"v1.2.3 $(id)"'),
                base.replace("/tmp/n.md", "notes.md"),
                base + "; true",
                "true; " + base,
                base + " && true",
                base.replace("create v1.2.3", "create 1.2.3")):
            with self.subTest(command=command):
                result = self.run_guard(command, cwd=repo)
                self.assertEqual(2, result.returncode, command)

    def test_feature_arm_never_deletes_a_permanent_branch(self):
        """#116 D5: dev -> main and main -> dev both refuse --delete-branch."""
        repo = self.make_repo("git@github.com:elevenyellow/nodocom.git")
        merge = "gh pr merge 7 --repo elevenyellow/nodocom --merge --delete-branch"
        for head, base in (("dev", "main"), ("main", "dev")):
            with self.subTest(head=head, base=base):
                env = {"FAKE_PR_JSON": json.dumps({
                    "state": "OPEN", "baseRefName": base, "headRefName": head,
                    "url": "https://github.com/elevenyellow/nodocom/pull/7",
                    "statusCheckRollup": []})}
                result = self.run_guard(merge, cwd=repo, env=env)
                self.assertEqual(2, result.returncode)
                self.assertIn("permanent branch", result.stderr)
```

In `test_ship_release_contracts.py` add `test_release_creation_uses_the_guarded_spelling`: the 4.5f code block contains the line `${GH_PREFIX}gh release create <vX.Y.Z> --repo <repo-slug> --verify-tag --title "<vX.Y.Z> — <one-line scope from PR title>" --notes-file <release-notes-path>` and contains neither `--target` nor `$NEXT_VERSION` nor a trailing backslash.

- [ ] **Step 2: Run and watch them fail**

Run: `just build` (3600 s), then the guard suite command from the root's Global Constraints, filtered with `-k spelling -k near_misses -k permanent_branch`.
Expected: FAIL — `refs/tags/…` pushes are refused as namespaced refs, `gh release create` is unguarded (near-misses exit 0), and the `dev → main` feature merge passes.

- [ ] **Step 3: Implement** the guard changes, the `home.packages` line, and the README (`## Adjudicated verbs` gains the two arms and the D5 refusal, as implemented). In ship-release §4.5f replace the multi-line block with the one-line spelling above, and say in the next sentence that the tag and slug are written in literally, like the merge line (D21). `SKILL.md` must not grow.

- [ ] **Step 4: Verify**

Run: `just build` (3600 s); the full guard suite (600 s) — PASS, no failures; `unittest home/common/agent-skills/tests/test_{ship_release_contracts,shell_example_contracts,workflow_skill_contracts}.py` — PASS; `just agent-instruction-budget` (600 s) prints `check: pass`; `git diff --stat origin/main -- home/common/claude-code/lifecycle_guard.py` shows the file changed and `if rg -q 'agent_tools' home/common/claude-code/lifecycle_guard.py; then exit 1; fi` exits 0.

- [ ] **Step 5: Commit** exactly the **Files** above as `feat(guard): tag-push and release-creation arms, permanent-branch delete repair (#124)`.
