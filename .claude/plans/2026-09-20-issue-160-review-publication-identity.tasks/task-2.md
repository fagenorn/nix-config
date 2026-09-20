# Task 2: Retain publication identity and close every owned lifetime

**Files:**

- Modify: `home/common/agent-skills/skills/sdd/scripts/review-package`
- Test: `home/common/agent-skills/tests/test_review_package.py`

**Interfaces:**

- Consumes: Task 1's `publication_fixture(...)`, accepted Ubuntu diagnosis record, existing `_open_directory(path: Path) -> int`, `_identity(path: Path) -> tuple[int, int]`, `_descriptor_identity(descriptor: int) -> tuple[int, int]`, and unchanged `publish_package(...)` signature/callback labels.
- Produces: descriptor-relative member link/stat/unlink behavior inside `publish_package`; named-directory verification against the retained identity; and `PublicationError` whose cause/notes preserve primary and secondary acquisition, mutation, cleanup, restoration, or owned-release failures.

**Invariants:**

- The directory identity becomes authoritative only after post-`mkdir` no-follow stat, `O_DIRECTORY | O_NOFOLLOW` open, descriptor stat, and a second named no-follow stat all describe the same directory. No member callback runs earlier; uncertain acquisition leaves the empty named object in place (D1, D3, D4).
- Replacement before the real open and replacement after the real open but before descriptor return both refuse before any `member:*` or `manifest` callback and close any acquired descriptor (D7).
- Every member link uses its leaf name and `dst_dir_fd=member_fd`; every linked-member stat and unlink uses that descriptor plus `follow_symlinks=False`. A replaced directory or symlink receives no shard, even when replacement occurs inside the real `os.link` boundary (D2).
- Cleanup examines only recorded leaves in the retained directory and removes a leaf only when its identity still matches its staged source. It attempts named `rmdir` only when the name still resolves to the retained directory and descriptor-relative enumeration is empty. Competitor entries always survive (D2, D3, D4).
- `member_fd` and the optional cwd-restoration fd are locally owned; `final_parent_fd` is borrowed. Attempt every owned close/restoration once even after another release error. Never retry a failed close. A release error after manifest publication leaves manifest and shards intact and raises `PublicationError` (D3).
- Member-descriptor closure is identical with and without `final_parent_fd`; restoration failure still closes the saved cwd descriptor. The original publication exception remains the primary cause when cleanup/release also fails, and every secondary failure is visible in exception notes (D3, D7).
- Remaining mkdir/open, check/unlink, and check/rmdir syscall gaps stay documented by behavior and are not represented as atomic (D3, D4).

- [ ] **Step 1: Add the remaining failing syscall and lifetime regressions**

Add these complete methods to `ReviewPackageCliTest`. They use the public mutation seam and narrow real-OS wrappers; do not assert a private helper name or call count.

```python
    def test_member_link_cannot_be_redirected_at_the_syscall_boundary(self):
        for replacement in ("directory", "symlink"):
            with (self.subTest(replacement=replacement),
                  tempfile.TemporaryDirectory() as raw):
                directory = Path(raw)
                stage_root, final_root, final_members = self.publication_fixture(
                    directory, (b"staged-one",)
                )
                stage_members = stage_root.with_suffix(".shards")
                original_members = directory / "review-original"
                outside = directory / "outside"
                outside.mkdir()
                redirected_during_link = False
                real_link = review_package_module.os.link

                def replace_then_link(source, destination, *args, **kwargs):
                    nonlocal redirected_during_link
                    if Path(source).parent == stage_members:
                        final_members.rename(original_members)
                        if replacement == "directory":
                            final_members.mkdir()
                            replacement_root = final_members
                        else:
                            final_members.symlink_to(outside, target_is_directory=True)
                            replacement_root = outside
                        (replacement_root / "competitor").write_bytes(
                            b"competitor-bytes"
                        )
                        result = real_link(source, destination, *args, **kwargs)
                        redirected_during_link = (
                            replacement_root / Path(source).name
                        ).exists()
                        return result
                    return real_link(source, destination, *args, **kwargs)

                with mock.patch.object(
                    review_package_module.os, "link", side_effect=replace_then_link
                ):
                    with self.assertRaises(review_package_module.PublicationError):
                        review_package_module.publish_package(stage_root, final_root)

                replacement_root = (
                    final_members if replacement == "directory" else outside
                )
                self.assertFalse(redirected_during_link)
                self.assertEqual(
                    {path.name for path in replacement_root.iterdir()}, {"competitor"}
                )
                self.assertEqual(
                    (replacement_root / "competitor").read_bytes(),
                    b"competitor-bytes",
                )
                self.assertEqual(list(original_members.iterdir()), [])
                self.assertFalse(final_root.exists())

    def test_member_directory_acquisition_errors_refuse_without_deleting_name(self):
        for fault in ("open", "fstat"):
            with (self.subTest(fault=fault),
                  tempfile.TemporaryDirectory() as raw):
                directory = Path(raw)
                stage_root, final_root, final_members = self.publication_fixture(
                    directory, (b"staged-one",)
                )
                real_open = review_package_module.os.open
                real_fstat = review_package_module.os.fstat
                acquired: list[int] = []

                def open_member(path, flags, *args, **kwargs):
                    if Path(path).name == final_members.name and fault == "open":
                        raise OSError("injected member-directory open failure")
                    descriptor = real_open(path, flags, *args, **kwargs)
                    if Path(path).name == final_members.name:
                        acquired.append(descriptor)
                    return descriptor

                def stat_member(descriptor):
                    if acquired and descriptor == acquired[-1] and fault == "fstat":
                        raise OSError("injected member-directory stat failure")
                    return real_fstat(descriptor)

                with (mock.patch.object(review_package_module.os, "open",
                                        side_effect=open_member),
                      mock.patch.object(review_package_module.os, "fstat",
                                        side_effect=stat_member)):
                    with self.assertRaises(review_package_module.PublicationError):
                        review_package_module.publish_package(stage_root, final_root)

                self.assertTrue(final_members.is_dir())
                self.assertEqual(list(final_members.iterdir()), [])
                self.assertFalse(final_root.exists())
                for descriptor in acquired:
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)

    def test_member_directory_acquisition_rejects_open_boundary_replacement(self):
        for boundary in ("before-open", "after-open"):
            with (self.subTest(boundary=boundary),
                  tempfile.TemporaryDirectory() as raw):
                directory = Path(raw)
                stage_root, final_root, final_members = self.publication_fixture(
                    directory, (b"staged-one",)
                )
                original_members = directory / "review-original"
                sentinel = final_members / "competitor"
                real_open = review_package_module.os.open
                acquired: list[int] = []
                callbacks: list[str] = []

                def observe_callback(label: str, _path: Path):
                    callbacks.append(label)

                def replace_around_open(path, flags, *args, **kwargs):
                    if Path(path) != final_members:
                        return real_open(path, flags, *args, **kwargs)
                    if boundary == "before-open":
                        final_members.rename(original_members)
                        final_members.mkdir()
                        sentinel.write_bytes(b"competitor-bytes")
                        descriptor = real_open(path, flags, *args, **kwargs)
                    else:
                        descriptor = real_open(path, flags, *args, **kwargs)
                        final_members.rename(original_members)
                        final_members.mkdir()
                        sentinel.write_bytes(b"competitor-bytes")
                    acquired.append(descriptor)
                    return descriptor

                with mock.patch.object(
                    review_package_module.os, "open", side_effect=replace_around_open
                ):
                    with self.assertRaises(review_package_module.PublicationError):
                        review_package_module.publish_package(
                            stage_root, final_root, observe_callback
                        )

                self.assertEqual(callbacks, ["member_dir"])
                self.assertEqual(sentinel.read_bytes(), b"competitor-bytes")
                self.assertEqual(list(original_members.iterdir()), [])
                self.assertFalse(final_root.exists())
                self.assertTrue(acquired)
                for descriptor in acquired:
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)

    def test_publication_releases_owned_descriptors_and_preserves_borrowed_parent(self):
        for outcome in ("success", "publication-failure"):
            with (self.subTest(outcome=outcome),
                  tempfile.TemporaryDirectory() as raw):
                directory = Path(raw)
                primary = directory / "primary"
                primary.mkdir()
                chain = review_package_module._ensure_directories(
                    primary, ["destination"], retain=True
                )
                self.assertIsNotNone(chain)
                destination = primary / "destination"
                stage_root, _, _ = self.publication_fixture(
                    directory / "fixture", (b"staged-one",)
                )
                final_root = destination / "review.json"
                starting_cwd = Path.cwd()
                real_open = review_package_module.os.open
                opened: list[int] = []
                member_fds: list[int] = []

                def observe_open(path, flags, *args, **kwargs):
                    descriptor = real_open(path, flags, *args, **kwargs)
                    opened.append(descriptor)
                    if Path(path).name == "review.shards":
                        member_fds.append(descriptor)
                    return descriptor

                def compete_with_manifest(label: str, path: Path):
                    if outcome == "publication-failure" and label == "manifest":
                        path.write_bytes(b"competitor-manifest")

                try:
                    with mock.patch.object(
                        review_package_module.os, "open", side_effect=observe_open
                    ):
                        if outcome == "success":
                            review_package_module.publish_package(
                                stage_root, final_root,
                                final_parent_fd=chain.leaf,
                                verify_final_parent=chain.verify,
                            )
                        else:
                            with self.assertRaises(
                                review_package_module.PublicationError
                            ):
                                review_package_module.publish_package(
                                    stage_root, final_root, compete_with_manifest,
                                    final_parent_fd=chain.leaf,
                                    verify_final_parent=chain.verify,
                                )

                    self.assertEqual(Path.cwd(), starting_cwd)
                    os.fstat(chain.leaf)
                    self.assertTrue(opened)
                    self.assertTrue(member_fds)
                    for descriptor in opened:
                        with self.assertRaises(OSError):
                            os.fstat(descriptor)
                    if outcome == "success":
                        self.assertEqual(final_root.read_bytes(), b"staged-manifest")
                    else:
                        self.assertEqual(
                            final_root.read_bytes(), b"competitor-manifest"
                        )
                finally:
                    chain.close()

    def test_publication_releases_member_descriptor_without_parent_fd(self):
        for outcome in ("success", "publication-failure"):
            with (self.subTest(outcome=outcome),
                  tempfile.TemporaryDirectory() as raw):
                directory = Path(raw)
                stage_root, final_root, final_members = self.publication_fixture(
                    directory, (b"staged-one",)
                )
                starting_cwd = Path.cwd()
                real_open = review_package_module.os.open
                member_fds: list[int] = []

                def observe_open(path, flags, *args, **kwargs):
                    descriptor = real_open(path, flags, *args, **kwargs)
                    if Path(path) == final_members:
                        member_fds.append(descriptor)
                    return descriptor

                def compete_with_manifest(label: str, path: Path):
                    if outcome == "publication-failure" and label == "manifest":
                        path.write_bytes(b"competitor-manifest")

                with mock.patch.object(
                    review_package_module.os, "open", side_effect=observe_open
                ):
                    if outcome == "success":
                        review_package_module.publish_package(stage_root, final_root)
                    else:
                        with self.assertRaises(review_package_module.PublicationError):
                            review_package_module.publish_package(
                                stage_root, final_root, compete_with_manifest
                            )

                self.assertEqual(Path.cwd(), starting_cwd)
                self.assertTrue(member_fds)
                for descriptor in member_fds:
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)
                if outcome == "success":
                    self.assertEqual(final_root.read_bytes(), b"staged-manifest")
                else:
                    self.assertEqual(final_root.read_bytes(), b"competitor-manifest")

    def test_close_failure_after_publication_preserves_package_and_recycled_fd(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            primary = directory / "primary"
            primary.mkdir()
            chain = review_package_module._ensure_directories(
                primary, ["destination"], retain=True
            )
            self.assertIsNotNone(chain)
            destination = primary / "destination"
            stage_root, _, _ = self.publication_fixture(
                directory / "fixture", (b"staged-one",)
            )
            final_root = destination / "review.json"
            final_members = destination / "review.shards"
            starting_cwd = Path.cwd()
            real_open = review_package_module.os.open
            real_close = review_package_module.os.close
            opened: list[int] = []
            member_fds: list[int] = []
            recycled_fd: int | None = None
            injected = False

            def observe_open(path, flags, *args, **kwargs):
                descriptor = real_open(path, flags, *args, **kwargs)
                opened.append(descriptor)
                if Path(path).name == final_members.name:
                    member_fds.append(descriptor)
                return descriptor

            def fail_after_real_close(descriptor):
                nonlocal recycled_fd, injected
                if member_fds and descriptor == member_fds[-1] and not injected:
                    real_close(descriptor)
                    recycled_fd = real_open(os.devnull, os.O_RDONLY)
                    if recycled_fd != descriptor:
                        real_close(recycled_fd)
                        recycled_fd = None
                        raise RuntimeError("fixture could not observe fd reuse")
                    injected = True
                    raise OSError("injected close failure after real close")
                return real_close(descriptor)

            try:
                with (mock.patch.object(review_package_module.os, "open",
                                        side_effect=observe_open),
                      mock.patch.object(review_package_module.os, "close",
                                        side_effect=fail_after_real_close)):
                    with self.assertRaises(review_package_module.PublicationError):
                        review_package_module.publish_package(
                            stage_root, final_root,
                            final_parent_fd=chain.leaf,
                            verify_final_parent=chain.verify,
                        )

                self.assertTrue(injected)
                self.assertIsNotNone(recycled_fd)
                os.fstat(recycled_fd)
                self.assertEqual(Path.cwd(), starting_cwd)
                os.fstat(chain.leaf)
                for descriptor in opened:
                    if descriptor != recycled_fd:
                        with self.assertRaises(OSError):
                            os.fstat(descriptor)
                self.assertEqual(final_root.read_bytes(), b"staged-manifest")
                self.assertEqual(
                    (final_members / "shard-001.diff").read_bytes(), b"staged-one"
                )
            finally:
                if recycled_fd is not None:
                    real_close(recycled_fd)
                chain.close()

    def test_restoration_failure_still_closes_saved_cwd_descriptor(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            primary = directory / "primary"
            primary.mkdir()
            chain = review_package_module._ensure_directories(
                primary, ["destination"], retain=True
            )
            self.assertIsNotNone(chain)
            destination = primary / "destination"
            stage_root, _, _ = self.publication_fixture(
                directory / "fixture", (b"staged-one",)
            )
            final_root = destination / "review.json"
            starting_cwd = Path.cwd()
            real_open = review_package_module.os.open
            real_close = review_package_module.os.close
            real_fchdir = review_package_module.os.fchdir
            rescue_fd = real_open(
                starting_cwd,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            previous_fds: list[int] = []
            member_fds: list[int] = []

            def observe_open(path, flags, *args, **kwargs):
                descriptor = real_open(path, flags, *args, **kwargs)
                if Path(path) == starting_cwd:
                    previous_fds.append(descriptor)
                if Path(path).name == "review.shards":
                    member_fds.append(descriptor)
                return descriptor

            def fail_restoration(descriptor):
                if previous_fds and descriptor == previous_fds[-1]:
                    raise OSError("injected cwd restoration failure")
                return real_fchdir(descriptor)

            try:
                try:
                    with (mock.patch.object(review_package_module.os, "open",
                                            side_effect=observe_open),
                          mock.patch.object(review_package_module.os, "fchdir",
                                            side_effect=fail_restoration)):
                        with self.assertRaises(review_package_module.PublicationError):
                            review_package_module.publish_package(
                                stage_root, final_root,
                                final_parent_fd=chain.leaf,
                                verify_final_parent=chain.verify,
                            )
                finally:
                    real_fchdir(rescue_fd)
                    real_close(rescue_fd)

                self.assertEqual(Path.cwd(), starting_cwd)
                self.assertTrue(previous_fds)
                self.assertTrue(member_fds)
                for descriptor in previous_fds + member_fds:
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)
                os.fstat(chain.leaf)
                self.assertEqual(final_root.read_bytes(), b"staged-manifest")
            finally:
                chain.close()

    def test_publication_failure_remains_primary_when_release_also_fails(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            stage_root, final_root, final_members = self.publication_fixture(
                directory, (b"staged-one",)
            )
            stage_members = stage_root.with_suffix(".shards")
            real_open = review_package_module.os.open
            real_link = review_package_module.os.link
            real_close = review_package_module.os.close
            member_fds: list[int] = []
            release_failed = False

            def observe_open(path, flags, *args, **kwargs):
                descriptor = real_open(path, flags, *args, **kwargs)
                if Path(path) == final_members:
                    member_fds.append(descriptor)
                return descriptor

            def fail_member_link(source, destination, *args, **kwargs):
                if Path(source).parent == stage_members:
                    raise OSError("injected publication failure")
                return real_link(source, destination, *args, **kwargs)

            def fail_member_release(descriptor):
                nonlocal release_failed
                if member_fds and descriptor == member_fds[-1] and not release_failed:
                    real_close(descriptor)
                    release_failed = True
                    raise OSError("injected member release failure")
                return real_close(descriptor)

            with (mock.patch.object(review_package_module.os, "open",
                                    side_effect=observe_open),
                  mock.patch.object(review_package_module.os, "link",
                                    side_effect=fail_member_link),
                  mock.patch.object(review_package_module.os, "close",
                                    side_effect=fail_member_release)):
                with self.assertRaises(
                    review_package_module.PublicationError
                ) as raised:
                    review_package_module.publish_package(stage_root, final_root)

            failure = raised.exception
            self.assertEqual(str(failure), "exclusive package publication failed")
            self.assertIsInstance(failure.__cause__, OSError)
            self.assertEqual(str(failure.__cause__), "injected publication failure")
            self.assertTrue(release_failed)
            self.assertTrue(any(
                "injected member release failure" in note
                for note in getattr(failure, "__notes__", [])
            ))
            for descriptor in member_fds:
                with self.assertRaises(OSError):
                    os.fstat(descriptor)
            self.assertFalse(final_root.exists())
```

- [ ] **Step 2: Run the new contract against the original producer**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_review_package.py -k publication`

Expected before implementation: FAIL in Task 1's cleanup regression and the new link/acquisition/release regressions. The link wrapper observes a shard in the replacement target; acquisition replacement/fault wrappers are never reached; no retained member descriptor is available to close; restoration short-circuits saved-fd close; and no secondary release note is present. Existing collision and parent-swap tests remain green.

- [ ] **Step 3: Implement the retained member-directory lifetime**

Keep the public signature unchanged and make these changes inside the producer:

1. After the existing exclusive `final_members.mkdir()`, take a no-follow named stat and require a directory. Open `final_members` through `_open_directory`, then require `fstat(member_fd)` and a second no-follow named stat to be directories with the same `(st_dev, st_ino)`. This order must reject replacement both before the real open and after it returns a descriptor to the original directory; the descriptor identity is authoritative only after all checks succeed. On any acquisition error, close an acquired descriptor once, raise `PublicationError`, and do not delete the uncertain named directory. Keep the earlier `member_dir` callback before exclusive creation; run no `member:*` callback before acquisition completes (D1, D3, D4, D7).
2. Store linked ownership as `(leaf_name: str, staged_identity: tuple[int, int])`. Rework `_verify_published_identities` (or replace it with an equally focused internal helper) so it first compares the named member directory to the retained descriptor identity, then uses `os.stat(leaf_name, dir_fd=member_fd, follow_symlinks=False)` for every recorded member. Missing, non-regular, changed, symlink, or syscall-error entries raise `PublicationError` (D1, D2).
3. After each existing callback and parent-chain verification, run the named/descriptor checks. Link with `os.link(source, source.name, dst_dir_fd=member_fd, follow_symlinks=False)`, record the staged source identity, and recheck. Keep the manifest as the final exclusive pathname link only after all parent, directory, and member checks pass (D2).
4. On publication failure, inspect recorded leaf names only through `member_fd`; unlink a leaf with `os.unlink(leaf, dir_fd=member_fd)` only when its no-follow descriptor-relative identity still equals the staged identity. After cleanup, enumerate through the retained descriptor. Attempt pathname `rmdir` only if enumeration is empty and a fresh named no-follow stat still equals the retained identity. Treat missing/mismatched entries as safe refusal, collect unexpected cleanup syscall failures as secondary notes, and never inspect the replacement's members (D2–D4, D7).
5. Track whether the manifest link completed. Keep `member_fd` alive through all cleanup and close it on success/failure whether `final_parent_fd` is present or `None`. In the release phase, attempt its close exactly once, then independently attempt cwd restoration and the previous-cwd fd close when present; a restoration error must not skip that close, and `final_parent_fd` remains borrowed. If publication failed, raise `PublicationError("exclusive package publication failed")` from the original publication exception and attach each secondary cleanup/release failure with `add_note`, including the exception type and message. If no publication failure exists, raise `PublicationError` from the first release/restoration failure, note later failures, and do not cleanup a completed manifest/package. Do not retry any close (D3, D7).

The implementation must not add a lock, sleep, timestamp heuristic, platform-specific rename syscall, whole-directory replacement, or stronger atomicity claim.

- [ ] **Step 4: Verify the complete Darwin behavior and commit**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_review_package.py`

Expected: all review-package tests pass; any missing competitor, shard in a replacement target, usable owned descriptor, unusable borrowed descriptor, changed cwd, deleted successful package, or unreported release failure fails the task.

Run: `just agent-workflow-tests`

Expected: exit 0 with 845 tests and no failures. This covers the unchanged CLI/report, caps, coverage, collision, no-follow parent, and exclusive-publication contracts.

Run: `just build`

Expected: exit 0. No activation is performed.

Run: `git diff --check -- home/common/agent-skills/skills/sdd/scripts/review-package home/common/agent-skills/tests/test_review_package.py`

Expected: exit 0, and `git diff --name-only 4ec9cd53ffcbbc5e7385efa1fec01be8bca352ec..HEAD --` contains no product/test path beyond the two named files (plan/spec artifacts are excluded from this product-scope judgment).

Stage only the producer and test file and commit:

```bash
git add home/common/agent-skills/skills/sdd/scripts/review-package \
  home/common/agent-skills/tests/test_review_package.py
git commit -S -m "fix(review-package): retain publication directory identity (#160)" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```

- [ ] **Step 5: Complete the mutation review and actual Ubuntu gate**

Before any final publication, an independent Astra reviewer inspects the Task 1 and Task 2 commits against D1–D7, with explicit rulings on both open-boundary acquisition replacements, descriptor-relative mutation, same-inode competitor preservation, cleanup ownership, borrowed/owned descriptor separation, the no-parent production call shape, post-manifest close failure, restoration failure with saved-fd closure, primary publication cause plus secondary release notes, and the remaining non-atomic syscall gaps. Resolve every Blocking or Major finding and rerun Step 4 after any edit.

Once review is accepted, the issue owner revalidates launch identity, publishes the reviewed feature head, and dispatches the unchanged existing CI workflow. The dispatch API response supplies the run ID and URLs directly; capture that exact run without a search or polling workaround:

```bash
python3 /private/tmp/issue-160-ci-observe.py \
  "$run_id" "$implementation_head" workflow_dispatch final
```

Final acceptance requires the checkout SHA to equal the reviewed implementation head, event `workflow_dispatch`, the `ubuntu-24.04` advisory job to complete, and raw `checkout`, `install_nix`, `provision_just`, and `suite` outcomes all to be `success`. The ordinary suite log must show the expanded suite passing; a green advisory conclusion with raw suite failure, an inconclusive setup outcome, or a different head is not acceptance.
