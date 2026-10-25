# Task 1: Experiment rig and the AC1 capture

This task covers spec § AC1 capture, § Experiment rig and § TLS interception, per D1, D2, D5, D9 and D10. On mbp it builds the scratch rig that every live task reuses, then captures two direct and two proxied sessions. It commits the evidence report's first three sections and the acceptance record. The deadline never skips it (D11).

**Files:**
- Create: `docs/spikes/cache-proxy-ttft-gap.md`
- Create: `.agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md`
- Scratch only: `<S>/i438/rig/`, `<S>/i438/mitm/`, `<S>/i438/cwd/`

**Interfaces:**
- Consumes: `./result` from `just build mbp`. Among its store requisites are exactly one `…-claude-accounts-mod` and exactly one `…-org.nix-community.home.claude-cache-proxy.plist`. The plist's `ProgramArguments` are `/bin/sh`, `-c`, `/bin/wait4path /nix/store && exec <launcher> --port 27183`, and its `EnvironmentVariables` hold `SSL_CERT_FILE`. The launcher's text contains `exec <interp> -I -m agent_tools.cache_proxy`.
- Produces for Tasks 2 and 5 (paths under `<S>/i438/`):
  - `rig/mkrig.sh <worktree> <rig-dir>`: rebuilds the rig from `<worktree>/result`.
  - `rig/bin/claude`: execs the wrapper copy `rig/mod/bin/claude-account run`. The copy's one proxy line is `CACHE_PROXY_URL=http://127.0.0.1:27391`.
  - `rig/run-proxy.sh <log> <pidfile> [cache-proxy args…]`: the built launcher, with the agent's environment, on `--port 27391`.
  - `rig/run-prototype.sh <log> <pidfile> <copy-python-dir> [cache-proxy args…]`: the launcher's interpreter with `-s -P -m agent_tools.cache_proxy --port 27391` and `PYTHONPATH=<copy-python-dir>`.
  - Both server scripts write their own pid, then append stdout and stderr to `<log>`.
  - `rig/scrub.txt`: the variables no run inherits, one per line.
  - `rig/session.sh <out.jsonl> [KEY=VALUE…]`: one session of the timed command line.
  - `mitm/addon.py`, `mitm/reduce.py` and `mitm/ac1-rows.json`.
  - Two report lines: `Missing first-party headers: …` and `Missing first-party headers without a recorded value: …`.
  - The acceptance record, with all five rows.

**Invariants:**
- No mitmproxy flow file is written: `-w` and `save_stream_file` are never set. No credential header value reaches any file (D1).
- In the direct arm, mitmdump intercepts only `api.anthropic.com:443` and tunnels every other host.
- Both arms run `session.sh` with the same command line, cwd and `ENABLE_TOOL_SEARCH=true`. Only the arm variables differ.
- `host` never appears in a diff row.
- The capture ports are 27391 and 27392 only.

- [ ] **Step 1: Confirm the starting state**

Run (timeout 60 s): `test ! -e docs/spikes/cache-proxy-ttft-gap.md && for p in 27391 27392; do if lsof -nP -iTCP:$p -sTCP:LISTEN; then exit 1; fi; done && echo clean`
Expected: `clean`. Then set `ACCOUNT="$(claude-account active)"` and `S=$(launch-scope scratch …)`, and run `mkdir -p "$S/i438/rig" "$S/i438/mitm" "$S/i438/cwd"`.

- [ ] **Step 2: Build and make the rig**

Run (timeout 3600 s): `just build mbp`. Write `<S>/i438/rig/scrub.txt` with these lines: `ANTHROPIC_BASE_URL`, `ENABLE_TOOL_SEARCH`, `CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING`, `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL`, `CLAUDE_CODE_DISPATCH_V2D`, `CLAUDE_CODE_GZIP_REQUEST_BODIES`, `CLAUDE_CACHE_PROXY`, `HTTPS_PROXY`, `https_proxy`, `HTTP_PROXY`, `http_proxy`, `ALL_PROXY`, `all_proxy`, `NO_PROXY`, `no_proxy`, `NODE_EXTRA_CA_CERTS`, `ANTHROPIC_LOG`, `ANTHROPIC_CUSTOM_HEADERS`. Then save `<S>/i438/rig/mkrig.sh`:

```bash
#!/usr/bin/env bash
# mkrig.sh <worktree> <rig-dir>: the #438 experiment rig from <worktree>/result (D2).
set -euo pipefail
W=$1 R=$2
q() { nix-store --query --requisites "$W/result" | grep -- "$1" || true; }
set -- $(q '-claude-accounts-mod$'); test "$#" -eq 1; MOD=$1
set -- $(q '-org.nix-community.home.claude-cache-proxy.plist$'); test "$#" -eq 1; PLIST=$1
rm -rf "$R/mod" "$R/bin"; mkdir -p "$R/bin"
cp -R "$MOD" "$R/mod"; chmod -R u+w "$R/mod"
python3 -I - "$PLIST" "$R" <<'EOF'
import plistlib, re, shlex, sys
from pathlib import Path
plist, rig = sys.argv[1], Path(sys.argv[2])
script = rig / "mod/bin/claude-account"
text = script.read_text()
old, new = "\nCACHE_PROXY_URL=http://127.0.0.1:27183\n", "\nCACHE_PROXY_URL=http://127.0.0.1:27391\n"
assert text.count(old) == 1 and text.count("\nCACHE_PROXY_URL=") == 1, "proxy URL line not unique"
script.write_text(text.replace(old, new))
with open(plist, "rb") as handle:
    agent = plistlib.load(handle)
argv = agent["ProgramArguments"]
found = re.fullmatch(r"/bin/wait4path /nix/store && exec (/nix/store/\S+) --port 27183", argv[-1])
assert argv[:2] == ["/bin/sh", "-c"] and found, argv
launcher = found.group(1)
interp = re.search(r"exec (/nix/store/\S+/bin/python3) -I -m agent_tools\.cache_proxy\b", Path(launcher).read_text())
assert interp, launcher
env = " ".join(f"{k}={shlex.quote(v)}" for k, v in agent["EnvironmentVariables"].items())
base = 'exec env -i HOME="$HOME" PATH=/usr/bin:/bin:/usr/sbin:/sbin ' + env
(rig / "run-proxy.sh").write_text(
    "#!/bin/sh\n# The built agent's launcher and environment on port 27391 (#438 D2).\n"
    'log=$1 pid=$2; shift 2; echo $$ > "$pid"\n'
    f'{base} {launcher} --port 27391 "$@" >>"$log" 2>&1\n')
(rig / "run-prototype.sh").write_text(
    "#!/bin/sh\n# A scratch prototype under the launcher's interpreter and environment (#438 D2).\n"
    'log=$1 pid=$2 copy=$3; shift 3; echo $$ > "$pid"\n'
    f'{base} PYTHONPATH="$copy" {interp.group(1)} -s -P -m agent_tools.cache_proxy --port 27391 "$@" >>"$log" 2>&1\n')
(rig / "bin/claude").write_text(f'#!/bin/sh\nexec {rig}/mod/bin/claude-account run "$@"\n')
(rig / "conditions.txt").write_text(f"launcher {launcher}\ninterp {interp.group(1)}\n")
EOF
echo "mod $MOD" >> "$R/conditions.txt"; echo "plist $PLIST" >> "$R/conditions.txt"
chmod +x "$R/run-proxy.sh" "$R/run-prototype.sh" "$R/bin/claude"
```

Save `<S>/i438/rig/session.sh`:

```sh
#!/bin/sh
# session.sh <out.jsonl> [KEY=VALUE...]: one session of the timed command line through the rig wrapper (#438 D1).
set -eu
rig=$(cd "$(dirname "$0")" && pwd -P); out=$1; shift
unset_args=$(sed 's/^/-u /' "$rig/scrub.txt" | tr '\n' ' ')
cd "$rig/../cwd"
# shellcheck disable=SC2086
exec env $unset_args PATH="$rig/bin:$PATH" ENABLE_TOOL_SEARCH=true "$@" \
  claude -p --model haiku --output-format stream-json --verbose --include-partial-messages "Reply with exactly: ok" > "$out"
```

Run (timeout 120 s): `chmod +x <S>/i438/rig/*.sh && bash <S>/i438/rig/mkrig.sh "$PWD" <S>/i438/rig && grep -c '^CACHE_PROXY_URL=http://127.0.0.1:27391$' <S>/i438/rig/mod/bin/claude-account && CLAUDE_ACCOUNT="$ACCOUNT" <S>/i438/rig/bin/claude --version`
Expected: `1`, then `2.1.302 (Claude Code)`. Nothing listens on 27391 yet, so the probe fails and the launch goes direct.

- [ ] **Step 3: The instrument**

Start mitmproxy from a devenv ad hoc shell, from `<S>/i438/mitm` so that devenv's state stays in scratch. Warm it up (timeout 1800 s): `cd <S>/i438/mitm && launch-scope exec … -- devenv -O packages:pkgs "mitmproxy" shell -- mitmdump --version`. Record the version line. Save `<S>/i438/mitm/addon.py`:

```python
"""mitmproxy addon for #438 (D1, D10): one reduced record per /v1/messages request.

No flow file and no credential value: credential headers keep their name only, allowlisted
headers keep their value, and every other header keeps a 16-hex SHA-256 digest.
"""
import hashlib
import json
from pathlib import Path

from mitmproxy import ctx

ALLOW = {"anthropic-version", "anthropic-beta", "content-type", "user-agent", "x-app",
         "anthropic-dispatch-id", "content-encoding", "accept-encoding"}
CREDENTIAL = {"authorization", "x-api-key", "cookie", "proxy-authorization"}


def load(loader):
    loader.add_option("i438_out", str, "", "directory for reduced records")


def kept(name, value):
    if name in CREDENTIAL:
        return None
    if name in ALLOW or name.startswith("x-stainless-"):
        return value.decode("latin-1")
    return "sha256:" + hashlib.sha256(value).hexdigest()[:16]


def usage_start(flow):
    for line in (flow.response.get_text(strict=False) or "").splitlines():
        if line.startswith("data: ") and '"message_start"' in line:
            return json.loads(line[6:]).get("message", {}).get("usage")
    return None


def response(flow):
    if not flow.request.path.startswith("/v1/messages"):
        return
    out = Path(ctx.options.i438_out)
    out.mkdir(parents=True, exist_ok=True)
    seq = len(list(out.glob("*.record.json"))) + 1
    headers = [[n.decode("latin-1").lower(), kept(n.decode("latin-1").lower(), v)]
               for n, v in flow.request.headers.fields]
    body = flow.request.get_content(strict=False) or b""
    (out / f"{seq}.body.json").write_bytes(body)
    (out / f"{seq}.record.json").write_text(json.dumps({
        "seq": seq, "method": flow.request.method, "path": flow.request.path,
        "status": flow.response.status_code, "headers": headers,
        "raw_body_bytes": len(flow.request.raw_content or b""), "body_bytes": len(body),
        "usage_start": usage_start(flow)}, indent=1))
```

Write `<S>/i438/mitm/reduce.py`, a standard-library script with two subcommands: `python3 -I reduce.py ac1 --direct <dir> <dir> --proxied <dir> <dir> --out-md <file> --out-json <file>`, and `python3 -I reduce.py check --against <ac1-rows.json> --proxied <dir> --out-json <file>`. Its rules are fixed here:

- **Main request.** In each session directory, select the one record with `method` `POST`, a path of `/v1/messages` (a query string is allowed) and a body whose `stream` is `true`. Zero or several such records exit 1 with `main request not unique: <dir>`.
- **Rows per session.** Each session yields a flat map from row to value:
  - `header:<name>`, for every name except `host`: the recorded value or digest, `(credential)` for a `null` value, or absent;
  - `header-order`: the names in order, `host` excluded;
  - `beta-tokens`: the sorted token set of every `anthropic-beta` value, split on commas;
  - `body-encoding`: the `content-encoding` value or `identity`, with `raw_body_bytes`/`body_bytes`;
  - `body:keys`, and `body:<key>` for each scalar top-level value outside `system`, `tools` and `messages` (an object gets its sorted keys instead);
  - `system:count`, plus `system:<i>:len` and `system:<i>:cache_control`;
  - `tools:count`, `tools:names` (in order) and `tools:<name>:keys`;
  - `messages:count` and `messages:<i>:blocks` (each block's type and text length);
  - `usage:<field>`, for each input-side field of `usage_start`.
- **Noise.** A row whose two sessions in one arm disagree is within-arm noise. It is listed under `Within-arm varying rows` and is never a diff row. `check` reads the noise list from `--against`.
- **Diff rows.** A diff row is a row that is constant within each arm and whose value differs between the arms, absence included. A value that is a digest prints as `constant`, never as the digest.
- **Differing text.** List the lines of system blocks and tool descriptions that one arm's first session has and the other arm's lacks, verbatim. A line that contains `$HOME` or matches `sk-ant-|Bearer |oat01` prints as `(<n> lines, <b> bytes withheld)` instead.
- **Missing first-party headers.** A missing first-party header is a `header:` row that is present in every direct session, absent from every proxied session and constant in value (spec § AC1 capture). An allowlisted one prints as `name=value`. One that has only a digest is listed as without a recorded value (D10).
- **`ac1` outputs.** `--out-json` writes `{"direct": {row: v}, "proxied": {row: v}, "rows": [diff rows], "noise": [rows], "missing": {name: value}, "missing_unrecorded": [names]}`. Here `direct` and `proxied` hold every row that is constant within that arm. `--out-md` writes the table `| Row | Direct | Proxied |`, then the lines `Beta tokens only direct: …`, `Beta tokens only proxied: …`, `Within-arm varying rows: …`, the differing text, `Missing first-party headers: <name=value, …|none>` and `Missing first-party headers without a recorded value: <names|none>`.
- **`check` output** (for the wire checks of Tasks 2 and 5). The `--proxied` directory holds one candidate session. `--out-json` writes:
  - `candidate`: that session's row map;
  - `diff`: the non-noise rows whose value differs from `direct`;
  - `removed`: the AC1 `rows` no longer in `diff`;
  - `added`: the rows in `diff` but not in the AC1 `rows`;
  - `body_json_ok`: whether the decoded body parses as a JSON object with `model` and `messages`.

  The encoding rows are `body-encoding`, `header:content-encoding`, `header:content-length` and `header-order`. `check` prints `removed` and `added`, without the encoding rows, as one line each.

- [ ] **Step 4: Direct captures (two sessions)**

Start mitmdump with the Bash tool's `run_in_background: true`: `cd <S>/i438/mitm && launch-scope exec … -- devenv -O packages:pkgs "mitmproxy" shell -- mitmdump -q --listen-host 127.0.0.1 --listen-port 27392 --set confdir=<S>/i438/mitm/conf --set http2=false --allow-hosts '^api\.anthropic\.com:443$' -s <S>/i438/mitm/addon.py --set i438_out=<S>/i438/mitm/records/direct-1`. Wait for it (timeout 60 s): `curl -q --noproxy '*' -s -o /dev/null --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:27392/ && test -s <S>/i438/mitm/conf/mitmproxy-ca-cert.pem`.

Run (timeout 300 s): `launch-scope exec … -- <S>/i438/rig/session.sh <S>/i438/mitm/direct-1.jsonl HTTPS_PROXY=http://127.0.0.1:27392 NODE_EXTRA_CA_CERTS=<S>/i438/mitm/conf/mitmproxy-ca-cert.pem ANTHROPIC_BASE_URL=https://api.anthropic.com CLAUDE_ACCOUNT="$ACCOUNT"`
Expected: exit 0. The output holds a `"type":"result"` line, and `records/direct-1/` holds exactly one main request. Stop mitmdump: `kill "$(lsof -nP -t -iTCP:27392 -sTCP:LISTEN)"`. Step 1 showed the port was free, so this listener is the one this task started. Repeat once with `direct-2` as both the record directory and the output name.

If mitmdump cannot complete a direct session (a TLS refusal or an auth failure), use D1's fallback. Rerun both arms with `ANTHROPIC_LOG=debug` and stderr kept, and take the headers from each `sending request` record. Bodies then come from the proxied reverse captures only. The report must name the fallback and what it could not see.

- [ ] **Step 5: Proxied captures (two sessions)**

Start mitmdump in the background as in Step 4, but with `--mode reverse:https://api.anthropic.com`, without `--allow-hosts`, and with `i438_out=<S>/i438/mitm/records/proxied-1`. Start the stock proxy with `run_in_background: true`: `launch-scope exec … -- sh <S>/i438/rig/run-proxy.sh <S>/i438/mitm/proxy-capture.log <S>/i438/mitm/proxy.pid --upstream http://127.0.0.1:27392`. Its health must answer (timeout 60 s): `curl -q --noproxy '*' -fsS --retry 20 --retry-connrefused --retry-delay 1 http://127.0.0.1:27391/_proxy/health` prints `{"service":"cache-proxy","status":"ok"}`.

Run (timeout 300 s): `launch-scope exec … -- <S>/i438/rig/session.sh <S>/i438/mitm/proxied-1.jsonl CLAUDE_ACCOUNT="$ACCOUNT"`
Expected: exit 0, a `result` line, exactly one main request under `records/proxied-1/`, and `proxy-capture.log` gains a `/v1/messages` request line. Stop mitmdump. Repeat once for `proxied-2`. Then stop the proxy with `kill "$(cat <S>/i438/mitm/proxy.pid)"`.

- [ ] **Step 6: Reduce and write the report and the record**

Run (timeout 120 s): `cd <S>/i438/mitm && python3 -I reduce.py ac1 --direct records/direct-1 records/direct-2 --proxied records/proxied-1 records/proxied-2 --out-md ac1.md --out-json ac1-rows.json`

Create `docs/spikes/cache-proxy-ttft-gap.md`, with these parts in this order:

1. **Title and intro.** The title is `# Cache proxy: the routed time-to-first-token gap — issue 438`. Then one line: `Point-in-time evidence for https://github.com/fagenorn/nix-config/issues/438, by the plan .agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.md; #422's record is docs/spikes/cache-proxy-spike.md.`
2. **`## Conditions`.** The date and host `mbp`; `git rev-parse --short HEAD`; the Claude Code version from Step 2; the store paths from `rig/conditions.txt`; account `$ACCOUNT` by name only; ports 27391 and 27392; the mitmproxy version; the instrument per arm; and the timed command line from `session.sh`.
3. **`## AC1 — direct versus proxied request`.** `ac1.md` verbatim. Its body-encoding row's direct cell gets one note: `derived: the binary's gzip gate turns compression off under HTTPS_PROXY and NODE_EXTRA_CA_CERTS, so a plain direct launch sends this body gzipped (spec § What the pinned binary already says)`. It must contain exactly one line matching `^Missing first-party headers: ` and exactly one matching `^Missing first-party headers without a recorded value: `.
4. **`## TLS interception (written evaluation)`.** Write these sentences: "`HTTPS_PROXY` with a locally trusted interception CA keeps `api.anthropic.com` as the base URL, so the request keeps its first-party shape and Remote Control stays available, but the client's gzip gate turns compression off. The AC1 direct sessions above are exactly such runs: «fill: one sentence naming the AC1 rows in which they differ from a plain direct launch, which is the body-encoding row unless the table shows more». It is not shipped, because a locally trusted CA would intercept the user's OAuth traffic on every launch (D5)."

Create the acceptance record with the schema line `| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |`. It has one row per issue criterion, AC1 to AC5. `Criterion` holds the issue's line verbatim. `Kind` and `Check or command` are copied from the plan root's § Acceptance map, and `Verdict` is `pending` (the controller grades). Row `AC1` gets Observed (the diff-row count, the beta difference and both `Missing first-party headers` values), Commit (`git rev-parse --short HEAD`) and Conditions (as in § Conditions). Rows AC2–AC5 get `pending Task 5`, `pending Task 6`, `pending Task 7` and `pending Task 7`, with `—` in Commit and Conditions.

- [ ] **Step 7: Verify**

Run (timeout 60 s):

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-ttft-gap.md; a=.agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md
test "$(grep -Ec '^Missing first-party headers: (none|[a-z0-9-]+=[^,]+(, [a-z0-9-]+=[^,]+)*)$' "$f")" -eq 1
test "$(grep -Ec '^Missing first-party headers without a recorded value: ' "$f")" -eq 1
for h in '## Conditions' '## AC1 — direct versus proxied request' '## TLS interception (written evaluation)'; do grep -qx "$h" "$f"; done
if grep -n '| header:host ' "$f"; then exit 1; fi
if grep -nE 'sk-ant-|Bearer |oat01' "$f" "$a"; then exit 1; fi
if grep -nF "$HOME" "$f" "$a"; then exit 1; fi
if grep -n '«fill' "$f"; then exit 1; fi
test "$(grep -c '^| AC[1-5] |' "$a")" -eq 5
for p in 27391 27392; do if lsof -nP -iTCP:$p -sTCP:LISTEN; then exit 1; fi; done
echo ac1-recorded
```

Expected: `ac1-recorded`. At the starting commit the first `grep` fails, because the report does not exist.

- [ ] **Step 8: Clean up and commit**

Run (timeout 60 s): `rm -rf <S>/i438/mitm/conf <S>/i438/mitm/records`. Keep `ac1-rows.json`, `addon.py` and `reduce.py`. Then:

```bash
git add docs/spikes/cache-proxy-ttft-gap.md .agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md
git commit -m "docs(issue-438): AC1 capture of the direct and proxied requests"
```

Report DONE with both `Missing first-party headers` values and the diff-row count.
