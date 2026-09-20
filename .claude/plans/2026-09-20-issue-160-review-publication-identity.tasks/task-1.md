# Task 1: Commit the bounded diagnostic contract

**Files:**

- Modify: `home/common/agent-skills/tests/test_review_package.py`

**Interfaces:**

- Consumes: existing `review_package_module.publish_package(...)`, `PublicationError`, and the callback labels `member:shard-001.diff`, `member:shard-002.diff`, and `manifest`.
- Produces: `publication_fixture(directory: Path, members: tuple[bytes, ...] = (...)) -> tuple[Path, Path, Path]`; an allocator-bounded identity diagnostic in `test_publication_rejects_changed_directory_and_link_identities`; and the portable `test_publication_cleanup_stays_with_retained_member_directory` regression for Task 2.

**Invariants:**

- The existing empty-directory removal/recreation assertion remains a refusal assertion and writes competitor bytes after recreation. It gets at most 128 attempts and reports the no-follow `(st_dev, st_ino)` pair immediately before removal and after recreation when the original producer unexpectedly accepts the replacement (D5, D6).
- A non-reuse result on Darwin or Ubuntu is inconclusive. Never manufacture equal identity values or classify a Darwin result as Linux diagnosis (D6).
- The portable cleanup regression uses a real hardlink to a staged shard in the replacement directory. Both that same-inode competitor and a distinct sentinel must survive; the invocation's links in the renamed original directory must be removed (D2, D5).
- This is an intentional test-only red commit. It receives independent review before the issue owner publishes exactly that head; Task 2 must not start until the Ubuntu record is accepted or the design is revised.

- [ ] **Step 1: Add the fixture, portable regression, and bounded diagnostic**

Add this helper and regression to `ReviewPackageCliTest`, then replace the existing `test_publication_rejects_changed_directory_and_link_identities` with the complete method below. Keep the other publication tests unchanged.

```python
    def publication_fixture(
        self,
        directory: Path,
        members: tuple[bytes, ...] = (b"staged-one", b"staged-two"),
    ) -> tuple[Path, Path, Path]:
        stage = directory / "stage"
        stage_members = stage / "review.shards"
        stage_members.mkdir(parents=True)
        stage_root = stage / "review.json"
        stage_root.write_bytes(b"staged-manifest")
        for number, raw in enumerate(members, 1):
            (stage_members / f"shard-{number:03d}.diff").write_bytes(raw)
        final_root = directory / "review.json"
        return stage_root, final_root, directory / "review.shards"

    def test_publication_cleanup_stays_with_retained_member_directory(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stage_root, final_root, final_members = self.publication_fixture(directory)
            stage_members = stage_root.with_suffix(".shards")
            original_members = directory / "review-original"
            competitor = final_members / "shard-001.diff"
            sentinel = final_members / "competitor"

            def replace_at_manifest(label: str, _path: Path):
                if label != "manifest":
                    return
                final_members.rename(original_members)
                final_members.mkdir()
                os.link(stage_members / "shard-001.diff", competitor,
                        follow_symlinks=False)
                sentinel.write_bytes(b"competitor-bytes")

            with self.assertRaises(review_package_module.PublicationError):
                review_package_module.publish_package(
                    stage_root, final_root, replace_at_manifest
                )

            self.assertFalse(final_root.exists())
            self.assertTrue(competitor.exists())
            self.assertEqual(competitor.read_bytes(), b"staged-one")
            self.assertEqual(sentinel.read_bytes(), b"competitor-bytes")
            self.assertEqual(list(original_members.iterdir()), [])

    def test_publication_rejects_changed_directory_and_link_identities(self):
        for mutation in ("directory-before-first", "member-before-second",
                         "directory-before-manifest"):
            attempts = 128 if mutation == "directory-before-first" else 1
            for attempt in range(attempts):
                with (self.subTest(mutation=mutation, attempt=attempt + 1),
                      tempfile.TemporaryDirectory() as raw):
                    directory = Path(raw)
                    stage_root, final_root, final_members = self.publication_fixture(
                        directory
                    )
                    competitor = b"competitor-bytes"
                    competed_path = final_members / "competitor"
                    observed: dict[str, tuple[int, int]] = {}

                    def replace_directory():
                        before = final_members.lstat()
                        observed["before"] = (before.st_dev, before.st_ino)
                        for member in final_members.iterdir():
                            member.unlink()
                        final_members.rmdir()
                        final_members.mkdir()
                        after = final_members.lstat()
                        observed["after"] = (after.st_dev, after.st_ino)
                        competed_path.write_bytes(competitor)

                    def inject(label: str, _path: Path):
                        if (mutation == "directory-before-first"
                                and label == "member:shard-001.diff"):
                            replace_directory()
                        elif (mutation == "member-before-second"
                              and label == "member:shard-002.diff"):
                            prior = final_members / "shard-001.diff"
                            prior.unlink()
                            prior.write_bytes(competitor)
                        elif (mutation == "directory-before-manifest"
                              and label == "manifest"):
                            replace_directory()

                    try:
                        review_package_module.publish_package(
                            stage_root, final_root, inject
                        )
                    except review_package_module.PublicationError:
                        pass
                    else:
                        self.fail(
                            "publication accepted replacement: "
                            f"mutation={mutation} attempt={attempt + 1}/{attempts} "
                            f"platform={sys.platform} before={observed.get('before')} "
                            f"after={observed.get('after')}"
                        )

                    self.assertFalse(final_root.exists())
                    if mutation == "member-before-second":
                        competed_path = final_members / "shard-001.diff"
                    self.assertEqual(competed_path.read_bytes(), competitor)
```

- [ ] **Step 2: Prove the contract discriminates on Darwin without treating it as Linux diagnosis**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_review_package.py -k cleanup_stays_with_retained_member_directory`

Expected on the original producer: FAIL because pathname cleanup removes the replacement's same-inode hardlink and leaves invocation-owned links in `review-original`.

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_review_package.py -k rejects_changed_directory_and_link_identities`

Expected on Darwin: PASS after at most 128 attempts. This confirms the strengthened fixture remains portable; it does not establish or refute Linux reuse.

Run: `git diff --check -- home/common/agent-skills/tests/test_review_package.py`

Expected: exit 0. Any other edited file is scope leakage.

- [ ] **Step 3: Commit the intentional red diagnostic head**

Stage only the test file and commit without weakening either failing assertion:

```bash
git add home/common/agent-skills/tests/test_review_package.py
git commit -S -m "test(review-package): diagnose directory identity reuse (#160)" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```

Expected: the commit is signed, changes only the named test file, retains the original producer blob `4c912551ebdc81000b7d4627c249825a1171da11`, and is intentionally red only because it exposes the known cleanup defect.

- [ ] **Step 4: Pause for independent review and root-owned Ubuntu evidence**

The issue owner sends the diagnostic commit to an independent Astra mutation-boundary reviewer. The reviewer must confirm the fixture uses real filesystem identities and a real hardlink, preserves the refusal assertion and competitor writes, caps the allocator-dependent variant at 128 attempts, and makes no workflow/product change.

After acceptance, the issue owner alone revalidates launch identity, publishes exactly this feature-branch head, and invokes the existing `.github/workflows/ci.yaml` with `workflow_dispatch`. The dispatch API response supplies the run ID and URLs directly; pass that returned ID to the collector without a search or polling workaround:

```bash
python3 /private/tmp/issue-160-ci-observe.py \
  "$run_id" "$diagnostic_head" workflow_dispatch diagnostic
```

The accepted record must bind the workflow run and advisory job to the diagnostic commit, `workflow_dispatch`, `ubuntu-24.04`, and the raw suite outcome. It must retain the assertion text with `platform`, `before`, and `after`, plus the producer blob identity. Do not edit the workflow, replace any of issue 37's three runs, or treat the advisory job conclusion as the suite outcome.

- [ ] **Step 5: Apply the diagnosis gate**

Expected unlock: the old producer unexpectedly accepts a `directory-before-first` replacement and the diagnostic reports equal `before` and `after` `(st_dev, st_ino)` values. That establishes the Ubuntu ABA mechanism; the portable regression independently establishes redirected cleanup.

If 128 Ubuntu attempts show no reuse, the result is inconclusive: retain the record and repeat no more than one separately reviewed diagnostic variant of at most 128 attempts. If Ubuntu reports a different mechanism, stop before Task 2 and amend/review the design. Only an accepted mechanism record allows the issue owner to hand Task 2 to a fresh Terra implementer.
