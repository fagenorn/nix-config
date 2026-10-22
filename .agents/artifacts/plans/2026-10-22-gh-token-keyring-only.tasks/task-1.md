# Task 1: Remove the GitHub token from the shell and the secret store

Spec § Decisions (Shell environment, Secret store, gh authentication), per D2, D3 and D5. The module stops declaring `github_token` and stops exporting `GITHUB_TOKEN`, and `sops unset` removes the value from the encrypted store, all in one commit: sops-nix checks every declared secret against the store when it builds, so a declaration without its value fails `just build`. Then the task measures AC2 and AC3 and opens the acceptance record.

**Files:**
- Modify: `home/common/sops/default.nix`
- Modify: `secrets/secrets.yaml` (only through `sops unset`)
- Create: `.agents/artifacts/plans/2026-10-22-gh-token-keyring-only.acceptance.md`

**Interfaces:**
- Consumes: base `336d9e05`; the age key at `~/.config/sops/age/keys.txt`; `sops` 3.12.1 on `PATH`.
- Produces: `sops.secrets` of `mbp`'s home-manager config named exactly `hf_token`, `my_ssh_private_key`, `my_ssh_public_key`; an encrypted store holding exactly `hf_token`, `my_ssh_private_key`, `my_ssh_public_key`, `omlx_api_key`; the acceptance record with rows `AC1`–`AC7` (Task 2 fills `AC4` and `AC5`).

**Invariants:**
- The module diff against `336d9e05` is exactly two deleted lines and no added line: `"github_token" = { };` and the `export GITHUB_TOKEN=` line. Its `HF_TOKEN` line, the `my_ssh_*` declarations, `age.*`, `defaultSopsFile` and the `package` override are unchanged.
- The store loses exactly `github_token`, and the other four keys decrypt to the same plaintext as at `336d9e05` (D3). `omlx_api_key` is read by `hosts/darwin/eleven-m5/omlx.nix` from this file, so it must survive.
- No decrypted value is printed, logged or written to disk (Global Constraints). The only `sops -d` is inside `task1-check.sh`, which prints names and set differences.
- No new test and no new comment in the module (D5).

- [ ] **Step 1: Write the gate script**

Save this as `<scratch>/i399/task1-check.sh`, where `<scratch>` is the `launch-scope scratch` root. It is this task's failing test:

```bash
#!/usr/bin/env bash
# Task 1 gate (issue 399). Prints key names, counts and set differences only,
# never a decrypted value. Usage, from the worktree root: bash task1-check.sh <scratch dir>
set -euo pipefail
S="$1"
mkdir -p "$S"
export SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt"
fail=0

# AC2: the evaluated zsh init exports no GitHub token, and HF_TOKEN's export survives.
nix eval --raw '.#darwinConfigurations.mbp.config.home-manager.users.anis.programs.zsh.initContent' \
  > "$S/zsh-init.txt"
tokens=$(grep -c -e GITHUB_TOKEN -e GH_TOKEN "$S/zsh-init.txt" || true)
hf=$(grep -c '^export HF_TOKEN="\$(cat /[^ ]*/hf_token)"$' "$S/zsh-init.txt" || true)
echo "AC2 zsh init: token lines $tokens (want 0), HF_TOKEN exports $hf (want 1)"
if [ "$tokens" != 0 ] || [ "$hf" != 1 ]; then fail=1; fi

# AC2 (D5): no Nix module or zsh fragment names a GitHub token.
if git grep -n -e GITHUB_TOKEN -e GH_TOKEN -e github_token -- '*.nix' data; then
  echo "AC2 grep: the lines above still name a GitHub token"; fail=1
else
  echo "AC2 grep: no match in *.nix or data"
fi

# AC3 module: the declared secret names.
names=$(nix eval --json '.#darwinConfigurations.mbp.config.home-manager.users.anis.sops.secrets' \
  --apply builtins.attrNames)
echo "AC3 declared secrets: $names"
if [ "$names" != '["hf_token","my_ssh_private_key","my_ssh_public_key"]' ]; then fail=1; fi

# AC3 store (D3): the base commit's encrypted store against the working file.
git show 336d9e05:secrets/secrets.yaml > "$S/base.enc.yaml"
python3 -I - "$S/base.enc.yaml" secrets/secrets.yaml <<'EOF' || fail=1
import hashlib, json, subprocess, sys

def digests(path):
    out = subprocess.run(["sops", "-d", "--output-type", "json", path],
                         check=True, capture_output=True).stdout
    return {key: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
            for key, value in json.loads(out).items()}

base, head = digests(sys.argv[1]), digests(sys.argv[2])
summary = {"head_keys": sorted(head),
           "removed": sorted(set(base) - set(head)),
           "added": sorted(set(head) - set(base)),
           "changed": sorted(k for k in set(base) & set(head) if base[k] != head[k])}
print("AC3 store: " + json.dumps(summary))
sys.exit(0 if summary["removed"] == ["github_token"] and not summary["added"]
         and not summary["changed"] else 1)
EOF

echo "task1-check exit $fail"
exit "$fail"
```

- [ ] **Step 2: Run the gate and watch it fail**

Run (timeout 900 s): `launch-scope exec … -- bash <scratch>/i399/task1-check.sh <scratch>/i399/t1`

Expected: exit 1, with these lines among nix's evaluation warnings:

```
AC2 zsh init: token lines 1 (want 0), HF_TOKEN exports 1 (want 1)
home/common/sops/default.nix:32:      "github_token" = { };
home/common/sops/default.nix:38:    export GITHUB_TOKEN="$(cat ${config.sops.secrets.github_token.path})"
AC2 grep: the lines above still name a GitHub token
AC3 declared secrets: ["github_token","hf_token","my_ssh_private_key","my_ssh_public_key"]
AC3 store: {"head_keys": ["github_token", "hf_token", "my_ssh_private_key", "my_ssh_public_key", "omlx_api_key"], "removed": [], "added": [], "changed": []}
task1-check exit 1
```

- [ ] **Step 3: Edit the module**

In `home/common/sops/default.nix`, delete line 32 (`      "github_token" = { };`) and line 38 (`    export GITHUB_TOKEN="$(cat ${config.sops.secrets.github_token.path})"`). Nothing else changes. The two blocks then read:

```nix
    secrets = {
      "my_ssh_private_key" = {
        path = "${config.home.homeDirectory}/.ssh/id_ed25519";
      };
      "my_ssh_public_key" = {
        path = "${config.home.homeDirectory}/.ssh/id_ed25519.pub";
      };
      "hf_token" = { };
    };
  };

  programs.zsh.initContent = ''
    export HF_TOKEN="$(cat ${config.sops.secrets.hf_token.path})"
  '';
```

Check: `git diff --numstat 336d9e05 -- home/common/sops/default.nix` prints `0	2	home/common/sops/default.nix`.

- [ ] **Step 4: Remove the value from the store**

Run from the worktree root:

```bash
SOPS_AGE_KEY_FILE="$HOME/.config/sops/age/keys.txt" sops unset secrets/secrets.yaml '["github_token"]'
```

Expected: exit 0 (an `[info] a new version of sops` line on stderr is harmless). The command is not idempotent: to retry, first restore the file with `git checkout -- secrets/secrets.yaml`. Then run `git diff --numstat -- secrets/secrets.yaml`. A scratch trial printed `2	3	secrets/secrets.yaml`: the `github_token:` line removed and the `sops` block's `lastmodified` and `mac` rewritten. Note the numbers for Step 8. A different count is not by itself a failure, because Step 5's store check decides (D3).

- [ ] **Step 5: Run the gate and watch it pass**

Run (timeout 900 s): `launch-scope exec … -- bash <scratch>/i399/task1-check.sh <scratch>/i399/t1`

Expected: exit 0 and

```
AC2 zsh init: token lines 0 (want 0), HF_TOKEN exports 1 (want 1)
AC2 grep: no match in *.nix or data
AC3 declared secrets: ["hf_token","my_ssh_private_key","my_ssh_public_key"]
AC3 store: {"head_keys": ["hf_token", "my_ssh_private_key", "my_ssh_public_key", "omlx_api_key"], "removed": ["github_token"], "added": [], "changed": []}
task1-check exit 0
```

A non-empty `changed` or `added`, or a `removed` other than `["github_token"]`, means the store edit went wrong: restore `secrets/secrets.yaml` from git and redo Step 4. Never inspect values to debug it.

- [ ] **Step 6: Build checks**

Run (timeout 3600 s): `launch-scope exec … -- just build`. Expected: exit 0. sops-nix checks the declared secrets against the edited store during this build.

Run (timeout 900 s): `launch-scope exec … -- nix eval --raw .#darwinConfigurations.eleven-m5.config.system.build.toplevel.drvPath`. Expected: exit 0, printing one `/nix/store/…-darwin-system-….drv` path (D5).

- [ ] **Step 7: Commit the change**

`git status --short` must list exactly ` M home/common/sops/default.nix` and ` M secrets/secrets.yaml`.

```bash
git add home/common/sops/default.nix secrets/secrets.yaml
launch-commit … -- -m "fix(sops): stop exporting GITHUB_TOKEN and delete its secret (#399)" \
  -m "gh now authenticates only through its gh auth login credential. HF_TOKEN's export is unchanged." \
  -m "<session trailers>"
```

- [ ] **Step 8: Measure at the commit and open the acceptance record**

With a clean tree (`git status --short -- home secrets data` prints nothing), run Step 5's command again. Expected: the same five lines, exit 0. These are the AC2 and AC3 evidence for this commit.

Create `.agents/artifacts/plans/2026-10-22-gh-token-keyring-only.acceptance.md`. It holds the heading `# Acceptance record — issue #399`, then the sentence `Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/399).`, then one table with the columns `AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict` and seven rows, `AC1` to `AC7` in order:
- `Criterion`: the issue's acceptance-criterion line verbatim, without its `- [ ] ` checkbox (read it with `gh issue view 399 --repo fagenorn/nix-config --json body --jq .body`).
- `Kind` and `Check or command`: copied from the plan root's Acceptance map.
- `AC2`: `Observed` holds the two `AC2` lines from this step. `Commit` is the short SHA of Step 7's commit. `Conditions` holds `mbp`, and says the eval read the committed tree.
- `AC3`: `Observed` holds the `AC3 declared secrets` and `AC3 store` lines. `Commit` is the same SHA. `Conditions` names `SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt`, the base store `336d9e05:secrets/secrets.yaml`, Step 4's numstat, and that no value was printed.
- `AC1`: `Observed` is `in final verification`, and `Commit` is `—`. `Conditions` holds Step 6's results with the commit they ran on: the `just build` exit, and the `eleven-m5` drvPath eval exit. It also says that CI `Nix Eval` of `anis-desktop` reports on the PR.
- `AC4`, `AC5`: `—` in `Observed`, `Commit` and `Conditions` (Task 2 fills them).
- `AC6`, `AC7`: `—` in `Observed`, `Commit` and `Conditions` (human rows).
- `Verdict`: `—` in every row; the sdd controller writes it.

- [ ] **Step 9: Commit the record**

```bash
git add .agents/artifacts/plans/2026-10-22-gh-token-keyring-only.acceptance.md
launch-commit … -- -m "docs(plan): acceptance record, AC2 and AC3 evidence (#399)" -m "<session trailers>"
```

Verify: `grep -c '^| AC[1-7] |' .agents/artifacts/plans/2026-10-22-gh-token-keyring-only.acceptance.md` prints `7`. `git status --short` prints nothing. `git diff --stat 336d9e05..HEAD -- home secrets` lists exactly `home/common/sops/default.nix` and `secrets/secrets.yaml`.
