export const meta = {
  name: 'deliver-standard',
  description: 'Deliver one standard-lane tracker issue: plan, implement and review each task, final review, verify once, ship',
  whenToUse: 'A standard-lane issue the user asked to deliver with this program; args {repo_root, issue, session_id|batch_id, mode?, lane?, decisions?, spec?, cont?}; mode plan stops after plan review, ready after verify with no PR, ship (the default) merges; lane direct has no plan: one implementer following deliver-direct, one fresh reviewer, at most one fix round',
  phases: [
    { title: 'Setup', detail: 'resolve contract, pre-flight, claim, worktree' },
    { title: 'Plan', detail: 'plan outside the tree, then review' },
    { title: 'Tasks', detail: 'implement and review each task' },
    { title: 'Final review', detail: 'whole-range review and fix wave' },
    { title: 'Verify', detail: 'declared verification once, after the fix wave' },
    { title: 'Ship', detail: 'PR, land lock, sync, checks, merge, release, close out' },
  ],
}

// Args: repo_root (the checkout), issue (number), session_id or batch_id (the claim
// holder is <host>/<batch_id> or <host>/session-<session_id>), decisions (owner answers to a
// needs_user stop; decisions also come from a fully ticked decision prompt read after the claim), spec (path of an approved design spec), mode (plan: stop after the plan
// review with { stage: 'planned', plan, cont }; ready: stop after verify with { stage: 'ready',
// head, branch, worktree, verify, tasks, acceptance, fix_waves, cont } and no PR, keeping the claim;
// ship, the default: merge. A ready cont resumed in ship skips the final review and verify when
// the head is unchanged and the tree clean), lane (standard, the default, or direct: no planner, one
// implementer following the deliver-direct skill, one fresh reviewer and at most one fix round; a cont keeps
// its lane and no direct plan mode exists), cont (the `cont` object of an earlier stop, passed
// back unchanged to resume; see RESUME below).
// Every policy value comes from the project contract that setup resolves; this
// file carries no project literal and defaults no policy value.
//
// CLAIM: the claim is a forge-claim claim: acquired before the worktree step, renewed
// before each stage boundary (a renew that finds the claim ended stops with no cont; one
// that gets no answer stops with a cont whose resume acquires again), released at close-out. A renew or acquire that
// answers `error` with `transient` (forge-claim's own transport retries ran out) is re-called once, a folded step whole, before it stops (#740).
//
// A fresh run re-adopts an existing branch or worktree (never resetting it) and stops `dirty` when it holds uncommitted changes.
//
// RESUME: every stop from the claim on returns { stage, ..., cont }, where cont is
// { setup, lane, plan (declared branches, when any, as [{name, worktree, base, head, current, toplevel, common_dir, clean}]), plan_reviewed, plan_findings?, decisions?, done, fix_waves, checks_fixes?, sync_fixes?, verified?, final_reviewed?, partial?, claim_incomplete? }. Passing it back as args.cont
// re-adopts the claimed worktree (setup re-checks it and refuses a dirty tree
// unless cont.partial names the task that left the edits), reuses cont.plan
// (reviewing it first unless plan_reviewed; a plan-review stop keeps the revised plan with plan_findings { rules, findings, rounds }, and the resume reads the owner's answer and, when only rule findings were left and none came from Codex, runs one rules-only revise of it, dropping the plan once rounds reach two; any other finding left has spent the plan's one full revise, so the resume plans again), skips the tasks in cont.done, then
// runs final review, verify and ship again (ship reuses an open PR). Every resume re-reads the facts of each branch cont.plan declares (a missing or wrong one stops setup with branch_heads.<name> missing, but only for a plan whose declarations are valid: an invalid one is dropped by the Plan section first); cont.verified and cont.final_reviewed carry branches { <name>: <head> }, and a resume reuses either only when every declared head the setup re-read is unchanged. When the PR
// is already merged, the re-adopt goes straight to close-out. A resume skips the final review when cont.final_reviewed names the head it
// passed at and the head is unchanged or only gained integration-branch merges with no unreviewed conflict resolution; a stop between a
// sync merge and its acceptance drops the marker. A result also carries dead_agents,
// the labels of agents that returned nothing or threw, when any did. A red check, and a sync-review
// finding, each get one fix wave per delivery (an implementer with a regression test, then a fresh reviewer); a second one stops with cont.
//
// LAND: ship opens the PR at the verified head, takes the cross-host land lock of the integration branch with --wait
// (the CLI does the waiting), then syncs, pushes and moves the lock after every head change, waits for every check on head (issue 756),
// re-checks the lock once, merges and releases it; the lock is released on every stop after it was taken, and a release that
// fails is reported as lock_unreleased on the result (#677).
//
// Lifecycle forms follow the contract (merge strategy, delete_branch, credential
// unsets). A host guard that accepts fewer forms refuses at that command; the
// step then returns its stop with the guard's message instead of working around it.

const REPO = args && args.repo_root
const ISSUE = args && args.issue
if (!REPO || !ISSUE) return { stage: 'args', error: 'repo_root and issue are required' }
const MODE = args.mode === undefined ? 'ship' : args.mode
if (!['plan', 'ready', 'ship'].includes(MODE)) return { stage: 'args', error: 'mode must be plan, ready or ship' }
const CONT = args.cont || null
if (args.lane !== undefined && !['standard', 'direct'].includes(args.lane)) return { stage: 'args', error: 'lane must be standard or direct' }
if (CONT && args.lane && args.lane !== (CONT.lane || 'standard')) return { stage: 'args', error: 'a cont keeps its lane; start again without cont: setup re-adopts the branch and the claim' }
const LANE = args.lane || (CONT && CONT.lane) || 'standard'
if (LANE === 'direct' && MODE === 'plan') return { stage: 'args', error: 'the direct lane has no plan mode' }
// The claim holder: a resume keeps cont.setup.holder; else it is built from the host and an id.
const ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/
const HOLDER_RE = /^[A-Za-z0-9][A-Za-z0-9.-]*\/[A-Za-z0-9][A-Za-z0-9._-]*$/
const HOLDER_ID = args.batch_id ? args.batch_id : args.session_id ? `session-${args.session_id}` : null
if (!(CONT && CONT.setup && CONT.setup.holder)) {
  if (!HOLDER_ID) return { stage: 'args', error: 'session_id or batch_id is required (the claim holder)' }
  if (!ID_RE.test(HOLDER_ID)) return { stage: 'args', error: `the claim holder id ${HOLDER_ID} must match ${ID_RE}` }
}
// A fresh run, or a resume whose claim stopped part way, runs the (idempotent) claim step.
const CLAIMING = !CONT || !!CONT.claim_incomplete

// forge-claim retries a transport error itself (#740), up to 150 s in a hanging outage, above the Bash tool's 120 s default.
const FORGE_TIMEOUT = 'Give each forge-claim command a Bash timeout of 20 minutes (1200000 ms), and land acquire --wait 60 minutes (3600000 ms): forge-claim retries a forge outage itself before it prints its one JSON line.'
const BASE_RULES = `
Hard rules for this step (they override anything else you remember):
- Work only in the worktree path you are given. Never commit in the shared checkout. Never git stash. Never sed -i (use python for edits).
- Do everything in the FOREGROUND inside this one turn: run long commands with a long Bash timeout; never use run_in_background, never end your turn while anything you started is pending, never sleep or use sleep workarounds. Your final message is your return value.
- Do not dispatch subagents unless this step says so.
- File any issue with forge-issue create, each blocking edge as --blocked-by <n> or --blocks <n>; never file one another way. Exit 1 with an issue: repair it with forge-issue link; create_unconfirmed: search for its title before filing again.
- Never run a host activation, deploy or release command.
- Global skills, agents and standards are shared by other projects: never write a project-specific literal (check names, branch names, recipe names, repository paths) into them.
- Run git as git -C <worktree> and name every file by its absolute path; never prefix a command with cd <worktree> &&, except for a tool that must run inside the worktree and has no directory flag (a test runner or a build).`

const SEV = { type: 'string', enum: ['critical', 'important', 'minor'] }
const FINDINGS = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['pass', 'findings'] },
    findings: { type: 'array', items: { type: 'object', properties: { severity: SEV, file: { type: 'string' }, summary: { type: 'string' }, failing_input: { type: 'string' }, relation: { type: 'string', enum: ['narrowing', 'new'] } }, required: ['severity', 'summary'] } },
  },
  required: ['verdict', 'findings'],
}
const PLAN_REVIEW = {
  ...FINDINGS,
  properties: {
    ...FINDINGS.properties,
    findings: { ...FINDINGS.properties.findings, items: { ...FINDINGS.properties.findings.items, properties: { ...FINDINGS.properties.findings.items.properties, rule: { type: 'string', enum: ['R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8', 'R9'] } } } },
  },
}
const CODEX = {
  type: 'object',
  properties: { available: { type: 'boolean' }, verdict: { type: 'string', enum: ['pass', 'findings'] }, findings: FINDINGS.properties.findings, raw_summary: { type: 'string' } },
  required: ['available', 'verdict', 'findings'],
}
const IMPL = {
  type: 'object',
  properties: { status: { type: 'string', enum: ['done', 'blocked'] }, start_head: { type: 'string' }, commit: { type: 'string' }, tests: { type: 'array', items: { type: 'string' } }, mutation_checked: { type: 'boolean' }, notes: { type: 'string' } },
  required: ['status', 'notes'],
}
const IMPL_RETURN = 'Return start_head (git rev-parse HEAD before you change anything) and commit (the full sha of HEAD after your last commit).'
// A wave that may commit on several branches reports the issue worktree's commits only in start_head and commit.
const IMPL_RETURN_AT = w => `Return start_head (git -C ${w} rev-parse HEAD before you change anything) and commit (the full sha of git -C ${w} rev-parse HEAD after your last commit): both name the issue worktree ${w}, never a declared branch's commit (those go in branch_heads); when you commit nothing there, commit equals start_head.`
const STRS = { type: 'array', items: { type: 'string' } }
// A forge or agent may report a short sha; the same head must not read as moved.
const FULL_SHA = { type: 'string', pattern: '^[0-9a-f]{40}$' }
const BRANCH_HEADS = { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, head: FULL_SHA, current: { type: 'string' }, toplevel: { type: 'string' }, common_dir: { type: 'string' } }, required: ['name', 'head'] } }
const FIX_WAVE_IMPL = { ...IMPL, properties: { ...IMPL.properties, branch_heads: BRANCH_HEADS } }
const normSha = x => x.trim().toLowerCase()
const sameSha = (a, b) => {
  if (typeof a !== 'string' || typeof b !== 'string') return false
  const x = normSha(a), y = normSha(b)
  if (x === y) return x !== ''
  const ok = /^[0-9a-f]{7,40}$/
  if (!ok.test(x) || !ok.test(y)) return false
  return x.length >= y.length ? x.startsWith(y) : y.startsWith(x)
}
const fuller = (a, b) => { const x = normSha(a), y = normSha(b); return y.length > x.length ? y : x }
const REVIEW_STATE = { type: 'string', enum: ['available', 'blocked', 'unsupported', 'absent'] }
const SETUP_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' }, reason: { type: 'string' }, details: { type: 'string' },
    host: { type: 'string' }, slug: { type: 'string' }, integration_branch: { type: 'string' }, default_branch: { type: 'string' },
    branch: { type: 'string' }, worktree_path: { type: 'string' }, head: { type: 'string' },
    merged_pr: { type: 'integer' }, dirty: { type: 'boolean' }, duplicate_pr: { type: 'integer' },
    since_reviewed: { type: 'string', enum: ['same', 'merge_only', 'moved'] },
    branch_heads: BRANCH_HEADS,
    existing: { type: 'object', properties: { local_branch: { type: 'boolean' }, remote_branch: { type: 'boolean' }, worktree: { type: 'boolean' }, dirty: { type: 'boolean' }, status: { type: 'string' }, head: { type: 'string' } } },
    unset_env: STRS,
    merge_strategy: { type: 'string' }, delete_branch: { type: 'boolean' },
    review: { type: 'object', properties: { code: { type: 'string' }, plan: { type: 'string' } } },
    review_state: { type: 'object', properties: { code: REVIEW_STATE, plan: REVIEW_STATE } },
    knowledge: { type: 'object', properties: { standards: STRS, hints: STRS, rejections: STRS } },
    verification: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, argv: STRS, cwd: { type: 'string' }, when_changed: STRS, skip_reason: { type: 'string' } }, required: ['id', 'argv', 'cwd'] } },
  },
  required: ['ok'],
}
const CLAIM_SCHEMA = {
  type: 'object',
  properties: { ok: { type: 'boolean' }, reason: { type: 'string' }, worktree: { type: 'string' }, base_sha: { type: 'string' }, plan_dir: { type: 'string' } },
  required: ['ok'],
}
const ACQUIRE_SCHEMA = {
  type: 'object',
  properties: { verdict: { type: 'string', enum: ['acquired', 'already_held', 'held_by', 'lost_to', 'error'] }, by: { type: 'string' }, comment_id: { type: 'integer' }, detail: { type: 'string' }, transient: { type: 'boolean' } },
  required: ['verdict'],
}
const RENEW_SCHEMA = {
  type: 'object',
  properties: { verdict: { type: 'string', enum: ['renewed', 'not_held', 'error'] }, by: { type: 'string' }, detail: { type: 'string' }, transient: { type: 'boolean' } },
  required: ['verdict'],
}
// A folded step (#716) returns its own result plus the claim renew it ran first as a required nested member.
const NULLABLE = s => ({ anyOf: [s, { type: 'null' }] })
// The fresh setup also claims the issue and sets up the worktree (#716): holder, acquire and claim ride beside its own fields.
const SETUP_FOLDED = { ...SETUP_SCHEMA, properties: { ...SETUP_SCHEMA.properties, holder: { type: 'string' }, acquire: NULLABLE(ACQUIRE_SCHEMA), claim: NULLABLE(CLAIM_SCHEMA) } }
const withRenew = (s, extra = {}) => ({ ...s, properties: { ...s.properties, renew: RENEW_SCHEMA, ...extra }, required: ['renew'] })
// A reply is complete when every member the schema requires is present and not null (a folded schema requires only its renew).
const complete = (r, schema) => !!r && schema.required.every(k => r[k] !== undefined && r[k] !== null)
// A renew or acquire that ran out of forge-claim's transport retries is re-called once (#740); the second reply stands whatever it is.
const transientError = r => !!r && r.verdict === 'error' && r.transient === true
const recall = async (make, pick = r => r) => { const r = await make(); return r && transientError(pick(r)) ? make() : r }
const ANSWER_SCHEMA = { type: 'object', properties: { verdict: { type: 'string' }, comment_id: { type: ['integer', 'null'] }, questions: { type: 'array', items: { type: 'object' } }, decisions: { type: 'string' } }, required: ['verdict'] }
const findingsOf = r => r.findings.filter(f => f.severity !== 'minor')
const present = v => v !== undefined && v !== null && v !== ''
// Extra branches a plan declares (#713): validated, then granted non-force pushes in the lifecycle rules.
const own = (o, k) => !!o && typeof o === 'object' && Object.prototype.hasOwnProperty.call(o, k)
const isEntry = b => !!b && typeof b === 'object' && !Array.isArray(b)
const declared = p => (p && Array.isArray(p.branches) ? p.branches.filter(isEntry) : [])
const SHA_RE = /^[0-9a-f]{40}$/
const factOf = (list, name) => (Array.isArray(list) ? list.find(f => isEntry(f) && f.name === name) || null : null)
const headOf = (list, name) => {
  const f = factOf(list, name)
  return f && typeof f.head === 'string' && SHA_RE.test(normSha(f.head)) ? normSha(f.head) : null
}
const REF_RE = /^[A-Za-z0-9][A-Za-z0-9._\/-]*$/
const PATH_RE = /^\/[A-Za-z0-9._\/-]+$/
const REF_NAMESPACES = ['refs', 'heads', 'tags', 'remotes']
const refProblem = s => {
  if (typeof s !== 'string' || !REF_RE.test(s)) return 'is not a plain ref name'
  if (s === 'HEAD' || s.includes('..') || s.split('/').some(c => c === '' || c.startsWith('.') || c.endsWith('.') || c.endsWith('.lock'))) return 'is not a valid ref name'
  return null
}
const canonPath = p => typeof p === 'string' && PATH_RE.test(p) && p.split('/').slice(1).every(c => c !== '' && c !== '.' && c !== '..')
const samePath = (a, b) => typeof a === 'string' && typeof b === 'string' && a.replace(/\/+$/, '').toLowerCase() === b.replace(/\/+$/, '').toLowerCase()
const BRANCH_FACTS = 'head, current, toplevel and common_dir: git -C <its worktree> rev-parse HEAD (the full sha), git -C <its worktree> branch --show-current, git -C <its worktree> rev-parse --show-toplevel and git -C <its worktree> rev-parse --path-format=absolute --git-common-dir'
const REPO_COMMON = typeof REPO === 'string' ? `${REPO.replace(/\/+$/, '')}/.git` : null
const factProblem = (b, f) => {
  if (!isEntry(f)) return 'no facts read'
  if (typeof f.head !== 'string' || !SHA_RE.test(normSha(f.head))) return 'no full head sha'
  if (f.current !== b.name) return `the worktree is on ${JSON.stringify(f.current)}, not ${b.name}`
  if (!samePath(f.toplevel, b.worktree)) return `the worktree is not its own checkout (toplevel ${JSON.stringify(f.toplevel)})`
  if (!samePath(f.common_dir, REPO_COMMON)) return `the worktree belongs to another repository (common dir ${JSON.stringify(f.common_dir)})`
  return null
}

// The problems with a plan's declared branches (#713); empty when valid. Never throws on any JSON value.
const branchProblems = (p, w = W, int = INT) => {
  const show = JSON.stringify
  const out = [], good = []
  if (p.branches !== undefined) {
    if (!Array.isArray(p.branches)) return ['branches is not a list']
    const protectedNames = [int, setup.default_branch, setup.branch].map(n => String(n).toLowerCase())
    p.branches.forEach((b, i) => {
      if (!isEntry(b)) { out.push(`branches[${i}] is not an object`); return }
      const before = out.length
      const rp = refProblem(b.name)
      if (rp) out.push(`branch ${show(b.name)} ${rp}`)
      else if (b.name.split('/').some(c => REF_NAMESPACES.includes(c.toLowerCase()))) out.push(`branch ${show(b.name)} is a namespaced ref; name the branch directly`)
      else if (protectedNames.includes(b.name.toLowerCase())) out.push(`branch ${b.name} is a protected branch`)
      else if (good.some(g => g.name.toLowerCase() === b.name.toLowerCase())) out.push(`branch ${b.name} is declared twice`)
      if (!canonPath(b.worktree)) out.push(`branch ${show(b.name)}: worktree ${show(b.worktree)} is not a canonical absolute path`)
      else if (samePath(b.worktree, w) || samePath(b.worktree, REPO)) out.push(`branch ${show(b.name)}: worktree ${show(b.worktree)} is the delivery worktree or the shared checkout`)
      else if (good.some(g => samePath(g.worktree, b.worktree))) out.push(`branch ${show(b.name)}: worktree ${show(b.worktree)} is declared twice`)
      const bp = refProblem(b.base)
      if (bp) out.push(`branch ${show(b.name)}: base ${show(b.base)} ${bp}`)
      const fp = factProblem(b, b)
      if (fp) out.push(`branch ${show(b.name)}: ${fp}`)
      // Admission only: a resume may find a task's own uncommitted edits in the worktree, but a plan declares a worktree with none.
      if (b.clean !== true) out.push(`branch ${show(b.name)}: the worktree is not clean (git status --porcelain must print nothing at declaration)`)
      if (out.length === before) good.push(b)
    })
  }
  if (Array.isArray(p.tasks)) {
    for (const t of p.tasks) {
      if (!isEntry(t) || t.branch === undefined) continue
      if (typeof t.branch !== 'string' || !good.some(g => g.name === t.branch)) out.push(`task ${show(t.n)}: branch ${show(t.branch)} is not declared`)
    }
  }
  return out
}

// ---------------- Setup ----------------
phase('Setup')
const CONTRACT_READ = `Run: hostname -s and return its output as host. Run: resolve-project resolve --repo-root ${REPO}
On refusal return ok=false, reason contract, and in details the resolver's error.code, repair_id and ordered violations exactly. From the snapshot return:
- slug: bindings.tracker.repo_slug; unset_env: bindings.tracker.credential_env.unset_before_invocation (run every gh command after unsetting exactly these names, nothing else).
- integration_branch and default_branch: bindings.vcs.integration_branch and bindings.vcs.default_branch; merge_strategy and delete_branch: bindings.vcs.merge.strategy and bindings.vcs.merge.delete_branch.
- review: the command ids at bindings.workflow.review.code and .plan (omit an absent one); review_state: for code and plan, the state of the capability review.code and review.plan (available, blocked or unsupported; absent if the capability is missing).
- knowledge: bindings.paths.standards, bindings.paths.hints and bindings.paths.rejections, each as given (empty when absent).
- verification: for each id in bindings.workflow.verification its bindings.commands argv, its cwd relative to project.root (. for the root), and any bindings.workflow.verification_conditions entry (when_changed globs, skip_reason).`
// Labels of agents that returned nothing or threw: deliver-batch's breaker reads them (#636).
const DEAD = []
const call = async (prompt, opts) => {
  let reply
  try {
    reply = await agent(prompt, opts)
  } catch (error) {
    DEAD.push(opts && opts.label)
    throw error
  }
  if (reply == null) DEAD.push(opts && opts.label)
  return reply
}
const deadOf = () => (DEAD.length ? { dead_agents: DEAD.slice() } : {})

// Shared by the fresh setup and the re-deriving resume of a claim_incomplete cont that lacks its location.
const DERIVE_LOCATION = `Run alone and exactly issue-branch --repo-root ${REPO} --issue ${ISSUE}: it prints one JSON line, and branch and worktree_path are its branch and worktree_path. On a non-zero exit refuse (ok=false) with reason branch and the line it wrote to stderr in details.`
// Only a new child's early cont (a stop after the folded claim, whatever fields are missing) can lack its location; an old cont has both.
const REDERIVE = !!(CONT && CONT.claim_incomplete && !(CONT.setup && present(CONT.setup.branch) && present(CONT.setup.worktree_path)))
const RES_BRANCH = REDERIVE ? '<branch>' : CONT && CONT.setup && CONT.setup.branch
const RES_PATH = REDERIVE ? '<worktree_path>' : CONT && CONT.setup && CONT.setup.worktree_path
// Shared by the fresh setup and the incomplete-claim resume: the facts the worktree step chooses its command from.
const EXISTING_READ = (branch, path) => `Read what already exists for the delivery, and change nothing: never reset, clean, restore or stash, and never delete a branch or worktree. Return existing with local_branch (a local branch named ${branch} exists), remote_branch (origin/${branch} exists), worktree (the path ${path} exists and is on branch ${branch}), dirty (git -C ${path} status --porcelain is non-empty), status (that output, its first 40 lines) and head (git -C ${path} rev-parse HEAD, or the branch tip when there is no worktree). Omit existing when there is no such branch and no such path. Refuse with reason worktree-mismatch and the path when ${path} is on another branch or ${branch} is checked out at another path.`
// The head the final review passed at, when a resume's cont names one: the setup then reports how HEAD relates to it.
const FR_HEAD = CONT && CONT.final_reviewed && present(CONT.final_reviewed.head) ? CONT.final_reviewed.head : null
const FR_ACCEPTED = FR_HEAD && Array.isArray(CONT.final_reviewed.accepted) ? CONT.final_reviewed.accepted.filter(present) : []
const BRANCH_READ = CONT && CONT.plan && declared(CONT.plan).length ? ` For each declared branch of the plan (${declared(CONT.plan).map(b => `${b.name} in ${b.worktree}`).join(', ')}) return branch_heads: one {name, head, current, toplevel, common_dir} each, with ${BRANCH_FACTS}; give a missing worktree no entry.` : ''
const SINCE_REVIEWED = FR_HEAD ? ` The final review passed at ${FR_HEAD}: after git -C <worktree> fetch origin, return since_reviewed: same when HEAD is ${FR_HEAD}; merge_only when git -C <worktree> merge-base --is-ancestor ${FR_HEAD} HEAD succeeds, git -C <worktree> rev-list --no-merges ${FR_HEAD}..HEAD ^origin/<integration_branch> prints nothing (the head only gained integration-branch merges), and every merge in git -C <worktree> rev-list --merges ${FR_HEAD}..HEAD ${FR_ACCEPTED.length ? `is one of ${FR_ACCEPTED.join(', ')} or ` : ''}is a clean two-parent merge, meaning git -C <worktree> merge-tree --write-tree <merge>^1 <merge>^2 exits 0 and prints the tree id that git -C <worktree> rev-parse <merge>^{tree} gives (a conflict resolved by hand, or an octopus merge, gives a different tree; never judge this from git show --cc, which omits a hunk where the merge keeps one parent unchanged); else moved.` : ''
const setup = await call(CONT ? `You re-adopt issue #${ISSUE} of the git repository at ${REPO} for a resumed delivery. Earlier setup: ${JSON.stringify(CONT.setup)}.
1. ${CONTRACT_READ}
2. ${REDERIVE ? `${DERIVE_LOCATION} Then if` : 'If'} a merged PR has head ${RES_BRANCH} (gh pr list --repo <slug> --state merged --head ${RES_BRANCH}), return ok=true with merged_pr set to its number; the worktree may already be gone.
3. Otherwise confirm: ${CONT.claim_incomplete ? `the issue is open (an earlier claim stopped part way; the next step finishes it)` : `the issue is open; the worktree ${CONT.setup && CONT.setup.worktree} exists and is on branch ${CONT.setup && CONT.setup.branch}${CONT.plan ? `; the plan directory ${CONT.setup && CONT.setup.plan_dir} exists` : ''}`}. If any fails, return ok=false with reason not-resumable and the evidence. An open PR whose head is that branch is expected and fine. Set dirty true if git -C <worktree> status --porcelain is non-empty. Return head: git -C <worktree> rev-parse HEAD (the full sha).${SINCE_REVIEWED}${BRANCH_READ}
${CONT.claim_incomplete ? `4. After git -C ${REPO} fetch origin: ${EXISTING_READ(RES_BRANCH, RES_PATH)} An earlier worktree step may have created the branch, the worktree or both before it failed, so report existing afresh.
5.` : '4.'} Return every contract field read fresh, ${REDERIVE ? 'with branch and worktree_path as derived' : 'branch as in the earlier setup'}. Change nothing.
${BASE_RULES}` : `You check issue #${ISSUE} of the git repository at ${REPO} before delivery. Change nothing in this step except one issue comment named below, the claim of step 5 and the worktree of step 6.
1. ${CONTRACT_READ}
2. ${DERIVE_LOCATION} Then gh issue view ${ISSUE} --repo <slug> --json state,labels,title and gh pr list --repo <slug> --state all --search ${ISSUE} --json number,state,headRefName. Refuse (ok=false) with reason closed, parked (label needs-verification or parked), duplicate (a merged PR referencing this issue, a possible duplicate delivery: set duplicate_pr to its number) or open-pr (an open PR referencing this issue whose head is not branch).
3. After git -C ${REPO} fetch origin, re-adopt instead of refusing when the work already exists. ${EXISTING_READ('<branch>', '<worktree_path>')}
4. Read the issue and the code at origin/<integration_branch>: if the issue no longer applies (already fixed or obsolete), comment the evidence on the issue and refuse with reason no-longer-applies. Otherwise return in details, in a few lines, what still applies, where (files and symbols) and what already exists.
5. Only when steps 1 to 4 found no refusal, claim the issue. Run, alone and exactly: forge-claim acquire --repo <slug> --issue ${ISSUE} --holder <host>/${HOLDER_ID} --branch <branch>
It prints one JSON line and adds the in-progress label itself. ${FORGE_TIMEOUT} Return <host>/${HOLDER_ID} as holder, and its verdict (error, with detail, on exit 1 or 2), by, comment_id and transient (true only when its JSON line has transient true) as acquire. When the verdict is neither acquired nor already_held, stop here: run no worktree command and return ok=true with every field above, holder and acquire.
6. Set up the worktree, each command in its own Bash call. An earlier attempt may have done part of this: skip a step already done (the worktree already at <worktree_path> on branch <branch>; the plan directory already there). From the existing you returned: when existing.worktree is true, adopt <worktree_path> as it is and run no worktree command; else when existing.local_branch is true, git -C ${REPO} worktree add <worktree_path> <branch> (adopt the local branch); else when existing.remote_branch is true, git -C ${REPO} worktree add --no-track -b <branch> <worktree_path> origin/<branch> (only the remote branch exists: adopt it); else git -C ${REPO} worktree add --no-track -b <branch> <worktree_path> origin/<integration_branch>. Never reset, clean, restore or stash anything in it. base_sha (full sha) is git -C <worktree_path> merge-base origin/<integration_branch> HEAD for an adopted branch, else the origin/<integration_branch> sha you branched from. plan_dir is <git -C <worktree_path> rev-parse --absolute-git-dir>/deliver-standard; create it. It lives in the worktree's git dir, outside the tree, so the plan never enters a commit.
7. Return ok=true with every field above, holder and acquire, and claim: ok, worktree (<worktree_path>), base_sha and plan_dir. Once the claim step ran, keep ok true: report a worktree failure only as claim with ok=false, the reason and what you already did.
${BASE_RULES}`, { label: 'setup', phase: 'Setup', agentType: 'clerk', model: 'sonnet', effort: 'low', schema: CONT ? SETUP_SCHEMA : SETUP_FOLDED })
// A lost reply carries no cont, fresh or resumed: a fresh reply that never showed the refusal checks pass must not resume past them,
// and a rerun redoes the full fresh setup (the acquire is idempotent for the same holder).
if (!setup) return { stage: 'setup', result: null, ...deadOf() }
// The fresh reply's folded claim, read once and removed so setup (and every cont built from it) keeps its old shape.
const FOLD_ACQ = !CONT && setup.acquire ? setup.acquire : null
const FOLD_CLAIM = !CONT && setup.claim ? setup.claim : null
const FOLD_HOLDER = !CONT ? setup.holder : undefined
if (!CONT) { delete setup.holder; delete setup.acquire; delete setup.claim }
const ACQ_RECALL = !CONT && transientError(FOLD_ACQ)
const CLAIM_TAKEN = !!(FOLD_ACQ && (FOLD_ACQ.verdict === 'acquired' || FOLD_ACQ.verdict === 'already_held'))
const BUILT = present(setup.host) ? `${setup.host}/${HOLDER_ID}` : null
// Every stop after the folded claim was taken keeps a cont that finishes it on resume, whatever fields are missing (stop() is not defined yet).
const earlyCont = () => (CLAIM_TAKEN ? { cont: { setup: { ...setup, ...(BUILT && HOLDER_RE.test(BUILT) ? { holder: BUILT } : {}) }, lane: LANE, plan: null, plan_reviewed: false, done: [], fix_waves: 0, claim_incomplete: true } } : {})
// Held by another holder: nothing of ours exists yet, so the stop carries no cont.
if (FOLD_ACQ && (FOLD_ACQ.verdict === 'held_by' || FOLD_ACQ.verdict === 'lost_to')) return { stage: 'claimed', verdict: FOLD_ACQ.verdict, by: FOLD_ACQ.by }
if (!setup.ok) return { stage: 'setup', result: setup, ...deadOf(), ...earlyCont() }
// A fresh run never closes out a merged PR: it is a possible duplicate delivery, for the owner to judge.
if (!CONT && setup.merged_pr) return { stage: 'setup', result: setup, duplicate: setup.merged_pr, ...deadOf(), ...earlyCont() }
// No policy is defaulted: a field the contract read did not return stops the run (before any claim on a fresh run).
const missing = ['slug', 'integration_branch', 'default_branch', 'branch', 'merge_strategy', 'delete_branch', 'unset_env', 'verification']
  .concat(CONT && !REDERIVE ? [] : ['worktree_path'])  // a resume carries it in cont.setup, unless it re-derives the location
  .concat(CONT && CONT.setup && CONT.setup.holder ? [] : ['host'])  // a resume carries the holder in cont.setup
  .filter(f => !present(setup[f]))
// Each review capability needs an explicit state, and an available one its command id, or a review could vanish silently.
for (const k of ['code', 'plan']) {
  const st = setup.review_state && setup.review_state[k]
  if (!present(st)) missing.push(`review_state.${k}`)
  else if (st === 'available' && !(setup.review && present(setup.review[k]))) missing.push(`review.${k}`)
}
const RULE_IDS = PLAN_REVIEW.properties.findings.items.properties.rule.enum
// A rules-only revise may settle the findings that triggered it only when none came from Codex: the rules re-reviewer does not
// preserve source or finding identity, so a Codex finding it re-reports under any rule id needs a Codex review, not a Claude one.
const rulesOnly = (rules, triggered) => rules.length > 0 && rules.every(f => RULE_IDS.includes(f.rule) && f.source !== 'codex') && !triggered.some(f => f.source === 'codex')
// The Plan section below drops a kept plan with an invalid declaration, and one a plan-review stop kept with findings no rules-only
// revise may settle; no fact of such a plan is demanded here, or a vanished worktree would stop every resume before the replan.
const keptDropped = !!(CONT && CONT.plan && !CONT.plan_reviewed && CONT.plan_findings && Array.isArray(CONT.plan_findings.rules)
  && !rulesOnly(CONT.plan_findings.rules, Array.isArray(CONT.plan_findings.findings) ? CONT.plan_findings.findings : []))
if (CONT && CONT.plan && !keptDropped && !setup.merged_pr && !missing.length && !branchProblems(CONT.plan, CONT.setup && (CONT.setup.worktree || CONT.setup.worktree_path), setup.integration_branch).length) {
  for (const b of declared(CONT.plan)) if (typeof b.name === 'string' && factProblem(b, factOf(setup.branch_heads, b.name))) missing.push(`branch_heads.${b.name}`)
}
if (missing.length) return { stage: 'setup', result: setup, missing, ...deadOf(), ...(CONT ? { cont: CONT } : earlyCont()) }
if (CONT) Object.assign(setup, { worktree_path: REDERIVE ? setup.worktree_path : CONT.setup.worktree_path, worktree: CONT.setup.worktree, base_sha: CONT.setup.base_sha, plan_dir: CONT.setup.plan_dir, ...(CONT.setup.holder ? { holder: CONT.setup.holder } : {}) })
setup.holder = (CONT && CONT.setup && CONT.setup.holder) || BUILT
// A fresh run's holder is the one it was told to claim with: the setup agent must have used exactly that.
if (!CONT && !(FOLD_HOLDER === BUILT && HOLDER_RE.test(BUILT))) return { stage: 'setup', result: setup, invalid: 'holder', holder: FOLD_HOLDER ?? BUILT, ...deadOf(), ...earlyCont() }
if (!HOLDER_RE.test(setup.holder)) return { stage: 'setup', result: setup, invalid: 'holder', holder: setup.holder, ...deadOf(), ...(CONT ? { cont: CONT } : {}) }

let plan = CONT && CONT.plan ? CONT.plan : null
let planReviewed = !!(CONT && CONT.plan && CONT.plan_reviewed)
// A plan-review stop keeps the revised plan and the findings left on it; a resume runs one rules-only revise on it.
const KEPT = CONT && CONT.plan && !CONT.plan_reviewed && CONT.plan_findings && Array.isArray(CONT.plan_findings.rules) ? CONT.plan_findings : null
let planFindingsKept = KEPT ? { rules: KEPT.rules, findings: Array.isArray(KEPT.findings) ? KEPT.findings : [], rounds: Number.isInteger(KEPT.rounds) ? KEPT.rounds : 0 } : null
const taskLog = CONT && CONT.done ? CONT.done.slice() : []
let claimIncomplete = !!(CONT && CONT.claim_incomplete) || CLAIM_TAKEN
// A partial task's edits stay claimed through any stop until that task is done.
let partial = CONT && CONT.partial !== undefined ? CONT.partial : undefined
// Fix waves already spent, carried through a resume; declared before stop() because early failures call it.
let fixWaves = (CONT && CONT.fix_waves) || 0
// The head the final review and its fix waves passed at ({ head, accepted? }), carried so a resume on it skips the review.
let finalReviewed = (CONT && CONT.final_reviewed) || null
// The stages between a sync merge and its acceptance: a stop there must not carry a marker over the unreviewed merge.
const SYNC_WINDOW = ['sync', 'sync-review', 'sync-fix']
// Ship fix waves already spent (a red check, a sync-review finding): one each per delivery, carried through a resume.
let checksFixes = (CONT && CONT.checks_fixes) || 0
let syncFixes = (CONT && CONT.sync_fixes) || 0
// The verified head, results and verification contract of a ready stop; carried until a resume finds the head moved; its results are reused only under the same contract.
let verified = (CONT && CONT.verified) || null
// The owner's binding decisions: distinct non-empty strings, from args, from cont and from the decision prompt read after the claim.
let decisions = []
const addDecision = text => { if (typeof text === 'string' && text.trim() && !decisions.includes(text)) decisions.push(text) }
if (CONT && Array.isArray(CONT.decisions)) CONT.decisions.forEach(addDecision)
addDecision(args.decisions)
const stop = (stage, extra) => {
  const fr = SYNC_WINDOW.includes(stage) ? (finalReviewed = null) : finalReviewed
  return { stage, ...extra, ...deadOf(), cont: { setup, lane: LANE, plan, plan_reviewed: planReviewed, ...(plan && !planReviewed && planFindingsKept ? { plan_findings: planFindingsKept } : {}), ...(decisions.length ? { decisions } : {}), done: taskLog, fix_waves: fixWaves, ...(checksFixes ? { checks_fixes: checksFixes } : {}), ...(syncFixes ? { sync_fixes: syncFixes } : {}), ...(verified ? { verified } : {}), ...(fr ? { final_reviewed: fr } : {}), ...(claimIncomplete ? { claim_incomplete: true } : {}), ...(partial !== undefined ? { partial } : {}) } }
}

const haltTask = (n, stage, extra) => { const s = stop(stage, extra); return { ...s, cont: { ...s.cont, partial: n } } }

if (CONT && setup.dirty && !setup.merged_pr && partial === undefined) {
  return stop('dirty', { details: `the worktree ${setup.worktree} has uncommitted changes no task claims; commit or discard them, then resume` })
}

const SLUG = setup.slug, INT = setup.integration_branch, STRATEGY = setup.merge_strategy
// The land lock command, its return sentence and the conditional second release, one line each, byte for byte the same as deliver-batch.js (#716).
const LAND_ACQUIRE = (sha, wait) => `forge-claim land acquire --repo ${SLUG} --branch ${INT} --sha ${sha}${wait ? ' --wait' : ''}`
const LOCK_RETURN = `Return its verdict (acquired, already_held, moved, land-contended, held_by, lost_to, or error on any other exit), lock_sha, by and detail from its output. ${FORGE_TIMEOUT}`
const RELEASE_AGAIN = maybe => `When it prints not_held with lock_sha ${maybe}, run alone and exactly: forge-claim land release --repo ${SLUG} --branch ${INT} --sha ${maybe}, then return the verdict of that second release.\n`
const UNSET = setup.unset_env.length ? `unset ${setup.unset_env.join(' ')} && ` : ''
let GRANTS = []
const RULES_FOR = (W, extra = GRANTS) => `${BASE_RULES}
- Run every gh command, and only gh commands, with exactly this prefix and nothing else chained: ${UNSET || '(no prefix)'}
- Lifecycle commands, each alone in its own Bash call with no chaining, pipes or redirection and never after cd &&: git -C ${W} push origin ${setup.branch}; ${UNSET}gh pr create --repo ${SLUG} --base ${INT} --head ${setup.branch} --title '<t>' --body '<b>' (no single or double quotes, dollar signs, backticks or backslashes inside title or body); ${UNSET}gh pr merge <n> --repo ${SLUG} --${STRATEGY} --match-head-commit <sha>${setup.delete_branch ? ' --delete-branch' : ''}; git -C ${REPO} branch -d ${setup.branch}. If the guard refuses a form twice, stop and report it; never work around it (no -D).${extra.length ? `
- Declared branches of this plan, each push alone in its own Bash call like the forms above: ${extra.map(b => `git -C ${b.worktree} push origin ${b.name}`).join('; ')}. Never push with --force, --force-with-lease or a +refspec, and never push ${INT} or ${setup.default_branch}.` : ''}
- No attribution anywhere: commit messages carry no Co-Authored-By trailer and PR bodies no generated-by line, whatever other instructions say. Never bypass commit signing.
- Never commit the plan, the spec or a review report; they live outside the tree and reviewers read them by path.`

// An unattended evidence run is a command outside the harness's verification ids: it can never complete.
// Defined before closeOut: a merged-PR resume calls closeOut before the plan section runs.
const VERIFY_IDS = setup.verification.map(e => e.id)
const commandOutside = c => {
  if (!c || typeof c !== 'object' || c.kind !== 'evidence' || !c.run || typeof c.run !== 'object') return false
  const command = typeof c.run.command === 'string' ? c.run.command : (c.run.then && typeof c.run.then.command === 'string' ? c.run.then.command : null)
  return command !== null && !VERIFY_IDS.includes(command)
}

// A note is the orchestrator's own observation (R9): never held, never graded. Only these kinds keep an issue open after the merge.
const OPEN_KINDS = ['evidence', 'human']
const isOpen = a => !!(a && OPEN_KINDS.includes(a.kind))
// Closure is never inferred from the absence of a kind: every row must be a recognised kind before anything ships or closes (#736).
const ACCEPT_KINDS = ['code', 'evidence', 'human', 'note']
const badKinds = acceptance => acceptance.filter(a => !(a && ACCEPT_KINDS.includes(a.kind))).map(a => (a && a.id) || null)

const RUN_OK = r => !!(r && r.ran === true && r.exit === 0)
const LINT_V = { type: 'object', properties: { ok: { type: 'boolean' }, errors: { type: 'array' } } }
const RUN_V = { type: 'object', properties: { ran: { type: 'boolean' }, exit: { type: 'integer' } }, required: ['ran', 'exit'] }
const HOLD_SCHEMA = { type: 'object', properties: {
  merge_commit_local: { type: 'boolean' }, code_unmet: STRS, blocks: { type: 'array', items: { type: 'integer' } },
  split: { type: 'array', items: { type: 'object', properties: { ac: { type: 'string' }, issue: { type: 'integer' }, block: { type: 'object' }, lint: LINT_V, verify_run: RUN_V, issue_state: { type: 'string' } }, required: ['ac', 'issue', 'lint', 'verify_run', 'issue_state'] } },
  block: { type: 'object' }, lint: LINT_V, verify_run: RUN_V, issue_state: { type: 'string' }, already_closed: { type: 'boolean' }, notes: { type: 'string' } },
  required: ['merge_commit_local', 'code_unmet', 'issue_state', 'notes'] }
const STATES = ['OPEN', 'CLOSED']

// The criterion ids no check of the block names: a hold must cover every criterion it leaves open, or the issue would close on a partial check.
const covers = (checks, ids) => ids.filter(id => !checks.some(c => c && c.ac === id))

const closeOut = async (PR, mergeCommit, W, prHead) => {
  const acceptance = plan ? plan.acceptance : null
  if (!acceptance) return stop('close-out', { pr: PR, details: 'merged, but no plan acceptance to grade the issue against; close out by hand' })
  const unknown = badKinds(acceptance)
  if (unknown.length) return stop('close-out', { pr: PR, details: 'merged, but a plan criterion has a kind that is not code, evidence, human or note; close out by hand', bad_kinds: unknown })
  const noHold = !acceptance.some(isOpen)
  const openCriteria = acceptance.filter(isOpen)
  const notes = acceptance.filter(a => a && a.kind === 'note')
  // Ship regrades the code rows for every plan; a plan with a non-code row is then held by the acceptance-planning rules' "Linting a hold" procedure.
  const merged = mergeCommit ? mergeCommit : `read from gh pr view ${PR} --repo ${SLUG} --json mergeCommit,headRefOid`
  const heldBlock = noHold ? '' : `
4. Read the issues this one blocks: gh api repos/${SLUG}/issues/${ISSUE}/dependencies/blocking (their numbers, returned as blocks).
5. When blocks is non-empty, move each human criterion into its own new issue that blocks no other issue (forge-issue create --repo ${SLUG}, its body naming #${ISSUE}), hold that issue by step 6 with only that criterion's check (no --blocks flag; its once-run uses --issue <child>), and return one split entry per moved criterion with its issue, block, lint, verify_run and issue_state.
6. For the criteria left (evidence or human, not split): none left means close #${ISSUE} with a comment naming the evidence and the split issues. Otherwise assemble one hold comment: a line per criterion, then exactly one \`\`\`verify fence holding {"v": 1, "merge": <the merge commit>, "checks": [...]} built from each criterion's verify member with every occurrence of the base sha ${setup.base_sha} replaced by the merge commit (a criterion without a verify member gets one written per ~/.agents/standards/acceptance-planning.md; an unattended evidence command run must be one of ${JSON.stringify(VERIFY_IDS)}, else use a script or a probe). Write it to a file outside any work tree and run verify-pending lint --input <file> --repo-root ${REPO} --pr-head ${prHead || '<the headRefOid read in step 1>'} --pr-branch ${setup.branch} plus one --pr-workflow <name> per distinct workflow of gh pr checks ${PR} --repo ${SLUG} --json workflow and one --blocks <n> per blocked issue. On refusal post nothing and return its verdict as lint. Otherwise, when no hold comment with a verify fence exists yet, gh issue comment ${ISSUE} --repo ${SLUG} --body-file <file> (when one exists, post nothing: write its fence JSON to the file and lint that, so lint is still returned), add the needs-verification label (create it if missing), then run alone, once, even when an earlier attempt ran it: verify-pending run --host ${setup.host} --repo ${SLUG} --issue ${ISSUE}. Return block (the posted JSON), lint, verify_run (ran, exit) and issue_state read back from the tracker.`
  const held = await call(`Issue #${ISSUE} of ${SLUG}: PR #${PR} is merged into ${INT}. Hold the issue's acceptance after the merge, by ~/.agents/standards/acceptance-planning.md (its "Linting a hold" section is the procedure). Skip the posting steps an earlier attempt already finished (an existing hold comment with a verify fence, the label, a split issue already filed and held for that criterion), but never skip the evidence you return: lint and verify_run are always fresh results of this attempt, so on such a retry take block from the posted verify fence, lint that block, run the once-run, and return all three. Each command in its own Bash call:
1. Run git -C ${REPO} fetch origin. Merge commit: ${merged}${mergeCommit ? '' : ' (and read headRefOid, the PR head)'}. Confirm git -C ${REPO} cat-file -e <merge commit>^{commit} succeeds and return the result as merge_commit_local; if it fails, stop here. Criteria: ${JSON.stringify(acceptance)}
2. Regrade each code criterion once against the merge commit and the PR's passed required checks; a note criterion is the orchestrator's own observation and is never regraded, held or checked. Return the unmet ids as code_unmet and, if any, stop here: post nothing and add no label.
3. ${noHold ? 'Every criterion is of kind code or note: post nothing, add no label; return issue_state read from the tracker.' : 'Some criteria are of kind evidence or human. Read gh issue view ' + ISSUE + ' --repo ' + SLUG + ' --json state. When it already shows CLOSED before this attempt posts or runs anything, return already_closed true and issue_state CLOSED, post nothing, add no label and run no verify-pending command for #' + ISSUE + ' itself (step 6 is skipped); steps 4 and 5 still apply, so a split issue an earlier attempt filed is recovered and returned with its lint and a fresh once-run. Otherwise return already_closed false and continue with steps 4 to 6.'}${heldBlock}
${RULES_FOR(W || '<worktree>')}`, { label: 'hold', phase: 'Ship', agentType: 'clerk', model: 'sonnet', effort: 'high', schema: HOLD_SCHEMA })
  if (!held) return stop('hold', { pr: PR })
  if (held.merge_commit_local !== true) return stop('hold', { pr: PR, hold: held })
  if (!Array.isArray(held.code_unmet)) return stop('hold', { pr: PR, hold: held })
  if (held.code_unmet.length) return stop('code-unmet', { pr: PR, code_unmet: held.code_unmet })
  // An issue the clerk found closed before the hold posted or ran anything has no parent evidence to check. One the once-run closed is not that case: its evidence is still validated. Split children are checked either way.
  const closedBefore = held.already_closed === true && held.issue_state === 'CLOSED'
  if (!noHold) {
    if (!Array.isArray(held.blocks) || !Array.isArray(held.split)) return stop('hold', { pr: PR, hold: held })
    const splitIds = held.split.map(x => x && x.ac)
    if (held.blocks.length) {
      const missing = acceptance.filter(a => a.kind === 'human' && !splitIds.includes(a.id)).map(a => a.id)
      if (missing.length) return stop('hold', { pr: PR, hold: held, missing_split: missing })
    }
    const noteIds = notes.map(a => a.id)
    const badSplit = held.split.filter(x => !(x && !noteIds.includes(x.ac) && x.lint && x.lint.ok === true && RUN_OK(x.verify_run) && STATES.includes(x.issue_state) && x.block && Array.isArray(x.block.checks) && covers(x.block.checks, [x.ac]).length === 0 && !x.block.checks.some(c => commandOutside(c) || (c && noteIds.includes(c.ac))))).map(x => (x && x.ac) || null)
    if (badSplit.length) return stop('hold', { pr: PR, hold: held, bad_split: badSplit })
    const remaining = openCriteria.filter(a => !splitIds.includes(a.id))
    if (remaining.length && !closedBefore) {
      if (!(held.lint && held.lint.ok === true) || !RUN_OK(held.verify_run) || !held.block || !Array.isArray(held.block.checks)) return stop('hold', { pr: PR, hold: held })
      const noteChecks = held.block.checks.filter(c => c && noteIds.includes(c.ac)).map(c => c.ac)
      if (noteChecks.length) return stop('hold', { pr: PR, hold: held, note_checks: noteChecks })
      const uncovered = covers(held.block.checks, remaining.map(a => a.id))
      if (uncovered.length) return stop('hold', { pr: PR, hold: held, missing_checks: uncovered })
      const outside = held.block.checks.filter(commandOutside)
      if (outside.length) return stop('hold', { pr: PR, hold: held, unattended: outside.map(c => c.ac) })
    } else if (held.issue_state !== 'CLOSED') return stop('hold', { pr: PR, hold: held })
    if (!STATES.includes(held.issue_state)) return stop('hold', { pr: PR, hold: held })
  }
  const co = await call(`Issue #${ISSUE} of ${SLUG}: PR #${PR} is merged into ${INT}. Close out; skip any step an earlier attempt already finished. Each command in its own Bash call:
1. ${W ? `If ${W} still exists: git -C ${REPO} worktree remove ${W} (it also removes the plan directory). ` : ''}git -C ${REPO} fetch origin; if the checkout ${REPO} is clean and on ${INT}, git -C ${REPO} merge --ff-only origin/${INT}; then, if the local branch ${setup.branch} exists, git -C ${REPO} branch -d ${setup.branch}. If -d refuses, leave the branch and report it (never -D).
2. End the decision prompts: run alone, exactly, forge-claim owner-action end --repo ${SLUG} --issue ${ISSUE} --reason decision (a verdict none is fine); return decision_ended true when it exits 0.
3. Release the claim: run alone, exactly, forge-claim release --repo ${SLUG} --issue ${ISSUE} --holder ${setup.holder} --reason done. It prints one JSON line and removes the in-progress label when no other claim remains; released is true only for verdict released. ${FORGE_TIMEOUT}
${notes.length ? `4. Unless a comment starting Orchestrator notes for PR ${PR} already exists on #${ISSUE} (an earlier attempt), write to a file outside any work tree a comment whose first line is Orchestrator notes for PR ${PR} (observations the orchestrator records itself; not graded, not held): and then one line <id>: <text> per note of ${JSON.stringify(notes.map(a => ({ id: a.id, text: a.text })))}, and post it with gh issue comment ${ISSUE} --repo ${SLUG} --body-file <file>. Return notes_posted true once that comment exists.\n` : ''}${notes.length ? 5 : 4}. ${noHold ? `Every criterion is of kind code or note. Read gh issue view ${ISSUE} --repo ${SLUG} --json state; if it is still open (${INT === setup.default_branch ? 'the closing keyword did not fire' : `${INT} is not the default branch, so no closing keyword fires`}), run gh issue close ${ISSUE} --repo ${SLUG} --comment 'Delivered by PR ${PR} into ${INT}.'` : 'The hold step settled the issue state and labels; change neither.'}
Return issue_state (OPEN or CLOSED, read back from the tracker), branch_deleted, decision_ended, released and notes.
${RULES_FOR(W || '<worktree>')}`, { label: 'close-out', phase: 'Ship', agentType: 'clerk', model: 'sonnet', effort: 'low', schema: { type: 'object', properties: { issue_state: { type: 'string' }, branch_deleted: { type: 'boolean' }, released: { type: 'boolean' }, decision_ended: { type: 'boolean' }, notes_posted: { type: 'boolean' }, notes: { type: 'string' } }, required: ['issue_state', 'notes'] } })
  const want = noHold ? 'CLOSED' : held.issue_state
  if (!co || co.issue_state !== want || co.decision_ended !== true || co.released !== true || (notes.length && co.notes_posted !== true)) return stop('close-out', { pr: PR, close_out: co, expected_issue_state: want })
  return { stage: 'done', pr: PR, merged: true, merge_commit: mergeCommit, close_out: co, hold: held, tasks: taskLog, acceptance, fix_waves: fixWaves }
}

if (CONT && setup.merged_pr) {
  phase('Ship')
  log(`PR #${setup.merged_pr} is already merged; closing out`)
  return await closeOut(setup.merged_pr, null, setup.worktree, null)
}

const RS = setup.review_state || {}
for (const k of ['plan', 'code']) {
  // Before any claim nothing is held, so the stop carries no cont: fix the capability and start again.
  if (RS[k] === 'blocked') return CONT || CLAIM_TAKEN ? stop('review-blocked', { review: k }) : { stage: 'review-blocked', review: k }
}
const REVIEW_CODE = RS.code === 'available' && setup.review && setup.review.code ? setup.review.code : null
const REVIEW_PLAN = RS.plan === 'available' && setup.review && setup.review.plan ? setup.review.plan : null

// A fresh run's setup already ran the claim and the worktree: validate its nested results. A claim_incomplete resume runs them itself,
// and so does a fresh run whose folded acquire was transient (its acquire step runs once more, then the worktree).
if (!CONT && !ACQ_RECALL) {
  if (!CLAIM_TAKEN) { claimIncomplete = true; return stop('claim', { result: FOLD_ACQ }) }
  if (!FOLD_CLAIM || !FOLD_CLAIM.ok || !present(FOLD_CLAIM.worktree) || !present(FOLD_CLAIM.base_sha) || !present(FOLD_CLAIM.plan_dir)) { claimIncomplete = true; return stop('claim', { result: FOLD_CLAIM }) }
  Object.assign(setup, { worktree: FOLD_CLAIM.worktree, base_sha: FOLD_CLAIM.base_sha, plan_dir: FOLD_CLAIM.plan_dir })
  claimIncomplete = false
  const EX = setup.existing || null
  if (EX && EX.dirty && partial === undefined) {
    return stop('dirty', { details: `the adopted worktree ${setup.worktree} has uncommitted changes, left as found; commit or discard them, then resume with cont: ${EX.status}`, status: EX.status })
  }
} else if (CLAIMING) {
  // This run's own setup report, never an earlier run's: a failed worktree step may have left the branch or the worktree behind.
  const EX = setup.existing || null
  const acquireStep = () => call(`Claim issue #${ISSUE} of ${SLUG} for delivery. Run, alone and exactly: forge-claim acquire --repo ${SLUG} --issue ${ISSUE} --holder ${setup.holder} --branch ${setup.branch}
It prints one JSON line and adds the in-progress label itself. ${FORGE_TIMEOUT} Return its verdict (error, with detail, on exit 1 or 2), by, comment_id and transient (true only when its JSON line has transient true). Run nothing else and change nothing.
${RULES_FOR(setup.worktree_path)}`, { label: 'acquire', phase: 'Setup', agentType: 'clerk', model: 'sonnet', effort: 'low', schema: ACQUIRE_SCHEMA })
  const acq = ACQ_RECALL ? await acquireStep() : await recall(acquireStep)
  // Held by another holder: nothing of ours exists yet, so the stop carries no cont.
  if (acq && (acq.verdict === 'held_by' || acq.verdict === 'lost_to')) return { stage: 'claimed', verdict: acq.verdict, by: acq.by }
  if (!acq || (acq.verdict !== 'acquired' && acq.verdict !== 'already_held')) { claimIncomplete = true; return stop('claim', { result: acq }) }
  const WT = EX && EX.worktree
    ? `The worktree ${setup.worktree_path} already exists on branch ${setup.branch}: adopt it as it is and run no worktree command. base_sha is git -C ${setup.worktree_path} merge-base origin/${INT} HEAD.`
    : EX && EX.local_branch
      ? `git -C ${REPO} fetch origin, then git -C ${REPO} worktree add ${setup.worktree_path} ${setup.branch} (the local branch exists: adopt it). base_sha is git -C ${setup.worktree_path} merge-base origin/${INT} HEAD.`
      : EX && EX.remote_branch
        ? `git -C ${REPO} fetch origin, then git -C ${REPO} worktree add --no-track -b ${setup.branch} ${setup.worktree_path} origin/${setup.branch} (only the remote branch exists: adopt it). base_sha is git -C ${setup.worktree_path} merge-base origin/${INT} HEAD.`
        : `git -C ${REPO} fetch origin, then git -C ${REPO} worktree add --no-track -b ${setup.branch} ${setup.worktree_path} origin/${INT}. base_sha is the origin/${INT} sha you branched from.`
  const claim = await call(`Set up the worktree for issue #${ISSUE} of ${SLUG}, each command in its own Bash call. An earlier attempt may have done part of this: skip a step already done (the worktree already at that path on branch ${setup.branch}; the plan directory already there).
1. ${WT} Never reset, clean, restore or stash anything in it.
2. plan_dir is <git -C ${setup.worktree_path} rev-parse --absolute-git-dir>/deliver-standard; create it. It lives in the worktree's git dir, outside the tree, so the plan never enters a commit.
Return ok, worktree (${setup.worktree_path}), base_sha (full sha) and plan_dir; on any failure ok=false with the reason and what you already did.
${RULES_FOR(setup.worktree_path)}`, { label: 'worktree', phase: 'Setup', agentType: 'clerk', model: 'sonnet', effort: 'low', schema: CLAIM_SCHEMA })
  // A claim that stopped part way may hold the claim or the worktree: its cont finishes it on resume.
  if (!claim || !claim.ok || !present(claim.worktree) || !present(claim.base_sha) || !present(claim.plan_dir)) { claimIncomplete = true; return stop('claim', { result: claim }) }
  Object.assign(setup, { worktree: claim.worktree, base_sha: claim.base_sha, plan_dir: claim.plan_dir })
  claimIncomplete = false
  if (EX && EX.dirty && partial === undefined) {
    return stop('dirty', { details: `the adopted worktree ${setup.worktree} has uncommitted changes, left as found; commit or discard them, then resume with cont: ${EX.status}`, status: EX.status })
  }
}

const W = setup.worktree
let RULES = RULES_FOR(W)
// The nested renew instruction a folded prompt starts with.
const RENEW_FIRST = `First renew the claim: run, alone and exactly, forge-claim renew --repo ${SLUG} --issue ${ISSUE} --holder ${setup.holder} --branch ${setup.branch} (it prints one JSON line) and return its verdict (error, with detail, on exit 1 or 2), by, detail and transient (true only when its JSON line has transient true) as renew. When renew's verdict is not renewed, stop there: run nothing else and return only renew. ${FORGE_TIMEOUT}`
// Grades a renew result. null = renewed; else the stop to return.
const renewed = (r, at) => {
  if (r && r.verdict === 'renewed') return null
  // An ended claim never comes back: no cont, a resume could only stop here again.
  if (r && r.verdict === 'not_held') return { stage: 'claim-lost', at, renew: r, details: 'the claim was ended (released, or honoured as stale by the owner); start again without cont: setup re-adopts the branch and acquire decides' }
  claimIncomplete = true
  return stop('claim-lost', { at, renew: r })
}
// Renews the claim before the step it guards. null = renewed; else the stop to return.
const renew = async (at, ph) => renewed(await recall(() => call(`Renew the claim on issue #${ISSUE} of ${SLUG}. Run, alone and exactly: forge-claim renew --repo ${SLUG} --issue ${ISSUE} --holder ${setup.holder} --branch ${setup.branch}
It prints one JSON line. ${FORGE_TIMEOUT} Return its verdict (error, with detail, on exit 1 or 2), by, detail and transient (true only when its JSON line has transient true). Run nothing else and change nothing.
${RULES}`, { label: `renew-${at}`, phase: ph, agentType: 'clerk', model: 'sonnet', effort: 'low', schema: RENEW_SCHEMA })), at)
const RANGE = `origin/${INT}...HEAD`
const CTX = `Issue #${ISSUE} of ${SLUG}. Worktree: ${W} (branch ${setup.branch}, base ${setup.base_sha}, integration branch ${INT}). The branch's changes are git -C ${W} diff ${RANGE} (fetch origin first).`
const K = setup.knowledge || {}
const list = a => (a && a.length ? a.join(', ') : 'none')
const KNOW = `Ground the review in: ~/.agents/standards/the-bar.md and its stacks/ shards matching the changed file types (when present); the project's standards (${list(K.standards)}), only shards whose globs intersect the change; review hints (${list(K.hints)}); recorded rejections (${list(K.rejections)}): never raise a finding a rejection already settles.`
const implDone = i => !!(i && i.status === 'done' && present(i.commit) && present(i.start_head))
const spanIn = (wt, i) => `git -C ${wt} diff ${i.start_head}..${i.commit}`
const span = i => spanIn(W, i)
log(`claimed #${ISSUE}, worktree ${W}; review code=${REVIEW_CODE || RS.code || 'none'} plan=${REVIEW_PLAN || RS.plan || 'none'}`)

// ---------------- Plan ----------------
const PLAN_SCHEMA = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['planned', 'needs_user'] },
    questions: { type: 'array', items: { type: 'object', properties: { question: { type: 'string' }, options: STRS }, required: ['question', 'options'] } },
    plan_root: { type: 'string' },
    acceptance: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, text: { type: 'string' }, kind: { type: 'string', enum: ['code', 'evidence', 'human', 'note'] }, verify: { type: 'object' }, lint: { type: 'object', properties: { ok: { type: 'boolean' }, errors: { type: 'array', items: { type: 'object', properties: { field: { type: 'string' }, code: { type: 'string' }, message: { type: 'string' } } } } } }, metric: { type: 'boolean' } }, required: ['id', 'text', 'kind'] } },
    scripts: STRS,
    tasks: { type: 'array', items: { type: 'object', properties: { n: { type: 'integer' }, title: { type: 'string' }, file: { type: 'string' }, risk: { type: 'string', enum: ['mechanical', 'low', 'standard', 'security'] }, branch: { type: 'string' } }, required: ['n', 'title', 'file', 'risk'] } },
    branches: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, worktree: { type: 'string' }, base: { type: 'string' }, head: FULL_SHA, current: { type: 'string' }, toplevel: { type: 'string' }, common_dir: { type: 'string' }, clean: { type: 'boolean' } }, required: ['name', 'worktree', 'base', 'head', 'current', 'toplevel', 'common_dir', 'clean'] } },
  },
  required: ['status'],
}
const wellFormed = p => !!(p && p.status === 'planned' && present(p.plan_root) && Array.isArray(p.acceptance) && p.acceptance.length && Array.isArray(p.tasks) && p.tasks.length)
const HUMAN_REASONS = ['senses', 'hands', 'credentials', 'money', 'taste']
const RULE_OF = { pre_merge_only: 'R1', approval_ask: 'R2', reason_required: 'R3' }
// The program-checkable violations of the acceptance planning rules (R1 to R5, and R9); the rules file is the source, never copied here.
const planRules = p => {
  const out = []
  const scripts = Array.isArray(p.scripts) ? p.scripts : []
  for (const a of p.acceptance) {
    const hit = (rule, why) => out.push({ severity: 'important', rule, ac: a.id, summary: `${rule} (${a.id}): ${why}` })
    const v = a.verify
    if (a.metric === true && !(a.kind === 'evidence' && v && typeof v === 'object' && v.mode === 'observe')) hit('R5', 'a metric is accepted only as an evidence check with mode observe')
    if (a.kind === 'note') {
      if (a.verify != null || a.script != null) hit('R9', 'a note carries no verify block and no script')
      continue
    }
    if (a.kind !== 'evidence' && a.kind !== 'human') continue
    if (!v || typeof v !== 'object') { hit('R4', 'no verify block'); continue }
    if (v.ac !== a.id || v.kind !== a.kind) { hit('R4', 'the verify block names another criterion or kind'); continue }
    if (a.kind === 'human' && !HUMAN_REASONS.includes(v.reason)) hit('R3', 'the human reason is not one of the listed reasons')
    if (commandOutside(v)) hit('R4', 'the unattended command is not a declared verification id and can never complete')
    const l = a.lint
    if (!l || typeof l !== 'object' || typeof l.ok !== 'boolean') { hit('R4', 'the verify block was not linted'); continue }
    if (l.ok) continue
    const errors = Array.isArray(l.errors) ? l.errors : []
    if (!errors.length) { hit('R4', 'the lint refused with no error'); continue }
    const script = v.run && typeof v.run === 'object' ? (typeof v.run.script === 'string' ? v.run.script : (v.run.then && typeof v.run.then.script === 'string' ? v.run.then.script : null)) : null
    for (const e of errors) {
      if (e.code === 'not_committed' && typeof e.field === 'string' && e.field.endsWith('.script') && script !== null && scripts.includes(script)) continue
      hit(RULE_OF[e.code] || 'R4', `lint ${e.code} at ${e.field}: ${e.message}`)
    }
  }
  return out
}
const SPEC = args.spec ? `\nThe approved design spec for this issue is ${args.spec}: plan from it, its decisions are binding, and never edit or commit it.` : ''
// The planner's code map (#743): beside the plan in plan_dir, so outside the tree and never committed.
const CODE_MAP = `${setup.plan_dir}/context.md`
const MAP_FIRST = `Read the code map ${CODE_MAP} first: open the code only to check one of its claims or where it is silent; when it is missing, read the code; check against HEAD every claim of it that a finding or a change relies on.`
// The plan reviewer's defect list, shared so the planner checks against the review it will get.
const PLAN_RUBRIC = `an acceptance criterion with no task, a task whose test cannot fail, wrong or missing interfaces, a design choice that breaks the project's documented conventions, or a project-specific literal written into global skills or agents`
const FACTS = present(setup.details) ? `\nSetup facts: ${setup.details}` : ''
const KIND_GUIDE = `kind code if a test or command in this repo can show it, evidence if it needs a deploy, an activation or observation over time, human if only the user can judge, note if a decision makes a post-deploy reading the orchestrator's own observation or not a hold (no verify member, no script and no metric, R9 of ~/.agents/standards/acceptance-planning.md)`
const planPrompt = extra => `${CTX}
Plan this issue. Read the issue (gh issue view ${ISSUE} --repo ${SLUG} --json title,body,comments) and the code it touches.${SPEC}${FACTS} Use the writing-plans skill for the plan's form only: its file location, size checks and reports do not apply here. Write the plan to ${setup.plan_dir}/plan.md and one task file per task beside it (${setup.plan_dir}/task-<n>.md); never commit them and never write under the project's artifact directories. Also write the code map ${CODE_MAP} for the agents after you, who read it before the code: per area the plan touches, list the files and symbols with line ranges, their tests and fixtures, the callers that matter and the facts you confirmed (for example a library's behaviour, with its source), each with a pointer (a path:line or a URL). Like the plan, it is never committed. On a revision, read it first and keep it true to the plan and the code. Do not build, prototype or run the change; confirming each task's failing test later is the implementers' job. If the issue needs a decision only the user can make (a preference, an irreversible or scope choice not settled by the issue, the spec, the repo's docs or ADRs), return status needs_user, never for an action that R8 of ~/.agents/standards/acceptance-planning.md says the delivery does itself, with questions, each {question, options}: every option one full sentence naming a real choice, a single option for a yes or no, and stop. Otherwise return status planned with plan_root ${setup.plan_dir}/plan.md, the issue's acceptance criteria (${KIND_GUIDE}) and the task list in execution order with each task's file and a risk: security for authentication, permission or command guards, secrets, CI/CD or deploy config, data migrations; mechanical or low for small contained edits; else standard. When a task commits to a branch other than ${setup.branch}, declare it in branches as {name, worktree, base, head, current, toplevel, common_dir, clean}: only a branch already checked out in its own existing worktree other than ${W}, never ${INT} or ${setup.default_branch}; worktree as git -C <it> rev-parse --show-toplevel prints it, base the ref its changes are measured from, and ${BRANCH_FACTS}, and clean: true only when git -C <its worktree> status --porcelain prints nothing (a worktree with any staged, unstaged or untracked change is not declared); give each task that commits there branch: <name>. Classify and write every acceptance criterion by ~/.agents/standards/acceptance-planning.md (read it); set metric true on a cost, timing or rate threshold of a code, evidence or human criterion, never on a note (R9): an owner-designated observation stays a note even when it reads a cost, a time or a rate. Give every evidence or human criterion a verify member: one check of the verify block grammar with ac its id and kind its kind, writing any sha that will name the merge commit as the base sha ${setup.base_sha} (ship substitutes the merge commit); an unattended evidence command run must be one of ${JSON.stringify(VERIFY_IDS)}, else use a script or a probe. Lint each member alone: write {"v": 1, "merge": "${setup.base_sha}", "checks": [<that member>]} to a file in ${setup.plan_dir} and run verify-pending lint --input <that file> --repo-root ${W} --pr-branch ${setup.branch} plus one --pr-workflow <name> for each CI workflow that runs on this repository's pull requests; return the verdict as that criterion's lint. List in scripts each script path a verify run names that a task of this plan commits. Before you return, check the plan against the review it will get: ${PLAN_RUBRIC}; and every rule ${RULE_IDS[0]}-${RULE_IDS[RULE_IDS.length - 1]} of ~/.agents/standards/acceptance-planning.md (read it).${decisions.length ? `\nThe owner has answered the open decisions for this issue; they are binding: ${decisions.join('\n')} Do not ask them again; record them as decisions in the plan.` : ''}${extra || ''}
${RULES}`
// A planner reply is either questions (the plan is dropped so a resume plans again with decisions) or a well-formed plan.
const takePlan = (p, label) => {
  if (p && p.status === 'needs_user') { plan = null; planReviewed = false; return stop('plan', { needs_user: p.questions }) }
  // A failed revision may have half-edited the files on disk, so the plan is dropped and a resume plans again.
  if (!wellFormed(p)) { plan = null; planReviewed = false; return stop('plan', { step: label, invalid: p }) }
  const bad = branchProblems(p)
  if (bad.length) { plan = null; planReviewed = false; return stop('plan', { step: label, invalid: p, branch_problems: bad }) }
  plan = p
  return null
}

const FOCUSED = `Run only the tests that cover the files you changed; do not run the full test suite or the project's declared verification (that runs once later). Before committing, run the project's formatter or lint fix on the files you changed, as the project's standards (${list(K.standards)}) name it; when they name none, skip this step.`
let ACS = null, PLAN_REF = null
// The last head this run knows for each declared branch (#713); read only through own().
const branchTips = Object.create(null)
const branchSnap = () => (declared(plan).length ? { branches: { ...branchTips } } : {})
const planRefs = () => {
  GRANTS = declared(plan); RULES = RULES_FOR(W)
  for (const b of declared(plan)) if (!own(branchTips, b.name)) branchTips[b.name] = headOf(setup.branch_heads, b.name) || b.head
  ACS = JSON.stringify(plan.acceptance)
  PLAN_REF = plan.plan_root ? `Plan: ${plan.plan_root} (task files beside it).` : 'No plan: direct lane.'
}
const declaredRanges = () => declared(plan).map(b => `git -C ${b.worktree} diff ${b.base}...${b.name}`)
const EXTRA_RANGES = () => (declared(plan).length ? ` The plan's declared branches belong to this delivery: also review ${declaredRanges().join(' and ')}.` : '')
let chunked = false
// Every declared branch head the setup re-read is the one the record names (no declared branch: always true).
const branchesSame = rec => declared(plan).every(b => !!rec && own(rec.branches, b.name) && sameSha(rec.branches[b.name], headOf(setup.branch_heads, b.name)))
// A ready stop's verified head, unchanged and clean, needs no second review or verify.
const SKIP_REVIEW = !!(verified && plan && sameSha(setup.head, verified.head) && !setup.dirty && plan.tasks.every(t => taskLog.some(d => d.n === t.n)) && branchesSame(verified))
// A passed final review, on the head it passed at (or one that only gained integration-branch merges), is not run again; verify still is.
const SKIP_FINAL = !SKIP_REVIEW && LANE === 'standard' && !!finalReviewed && !!plan && plan.tasks.every(t => taskLog.some(d => d.n === t.n)) && !setup.dirty && (sameSha(setup.head, finalReviewed.head) || setup.since_reviewed === 'merge_only') && branchesSame(finalReviewed)
if (!SKIP_REVIEW) verified = null
if (!SKIP_REVIEW && !SKIP_FINAL) finalReviewed = null
// The last commit the final review will cover.
let tip = setup.head || null
// The verification contract as freshly resolved, key order aside: cached results answer only this contract.
const canon = v => Array.isArray(v) ? `[${v.map(canon).join(',')}]` : v && typeof v === 'object' ? `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canon(v[k])}`).join(',')}}` : JSON.stringify(v)
const VERIFY_CONTRACT = canon(setup.verification)
const VERIFY_CACHED = SKIP_REVIEW && verified.contract === VERIFY_CONTRACT
const DIRECT_IMPL = { ...IMPL, properties: { ...IMPL.properties, acceptance: PLAN_SCHEMA.properties.acceptance, sensitive: { type: 'boolean' }, ineligible: { type: 'boolean' } } }
const DIRECT_FINDINGS = { ...FINDINGS, properties: { ...FINDINGS.properties, escalate: { type: 'boolean' } } }

// ---------------- Direct lane ----------------
if (LANE === 'direct') {
  // The deliver-direct skill stays the single source of the implementer's steps; this block never copies its text.
  let impl = null
  if (!taskLog.some(d => d.n === 1)) {
    phase('Tasks')
    const lost = await renew('tasks', 'Tasks')
    if (lost) return lost
    impl = await call(`${CTX}
Deliver issue #${ISSUE} in the direct lane. Invoke the deliver-direct skill with the Skill tool to read it: it is the single source for this step. Its steps 1 and 2 are done by this program (the claim is held by ${setup.holder}; the worktree is ${W} on branch ${setup.branch}). Check its Eligibility first: if the issue fails it, change nothing and return status blocked with ineligible true and why. Otherwise follow its step 3 exactly and commit. Do not run its steps 4 to 7: review, verification, ship and close-out belong to this program. Return acceptance (the issue's criteria; ${KIND_GUIDE}) and sensitive (true when the diff touches authentication or authorization, permission or command guards, secrets or credentials, CI/CD or deploy config, or data migrations). ${FOCUSED} ${IMPL_RETURN}${CONT && CONT.partial === 1 ? `
An earlier attempt at this task was cut off and may have left uncommitted edits or commits in the worktree (git -C ${W} status, git -C ${W} diff and git -C ${W} log ${RANGE}). Inspect them: keep what matches, finish or redo the rest, and make sure the failing-test-first and mutation checks still hold for the final result; start_head is the head before this task's first commit.` : ''}
${RULES}`, { label: 'direct-impl', phase: 'Tasks', agentType: 'implementer', model: 'sonnet', schema: DIRECT_IMPL })
    if (impl && impl.ineligible) return stop('ineligible', { impl, details: 'rerun in the standard lane without cont; setup re-adopts the worktree and the claim' })
    if (!implDone(impl)) return haltTask(1, 'task', { task: { n: 1 }, impl })
    if (!Array.isArray(impl.acceptance) || !impl.acceptance.length) return haltTask(1, 'task', { task: { n: 1 }, impl, details: 'no acceptance criteria' })
    plan = { status: 'planned', plan_root: null, acceptance: impl.acceptance, tasks: [{ n: 1, title: 'direct', file: null, risk: impl.sensitive ? 'security' : 'low' }] }
    planReviewed = true
    taskLog.push({ n: 1, commit: impl.commit, review_rounds: 0, reviewer: null, reviewed_head: null })
    if (partial === 1) partial = undefined
  }
  planRefs()
  log('direct lane: one implementer, one fresh reviewer')
  const d1 = taskLog.find(d => d.n === 1)
  const reviewHead = impl ? impl.commit : setup.head
  // Implementation completion never skips the fresh review: only a head it already passed does.
  if (!(SKIP_REVIEW || (!impl && present(d1.reviewed_head) && sameSha(d1.reviewed_head, setup.head)))) {
    let fix = null
    phase('Final review')
    const lost = await renew('final-review', 'Final review')
    if (lost) return lost
    const codexP = REVIEW_CODE ? call(`${CTX}
${PLAN_REF} Acceptance criteria: ${ACS}.
Run the project's configured independent code review: the contract's workflow.review.code is the command ${REVIEW_CODE}. Use the codex-collaboration skill (invoke it with the Skill tool) to run that Codex diff review over the delivery range ${RANGE} in the worktree ${W}, with no review package; this step may dispatch the Codex reviewer that skill uses, and must wait for its result in this turn. Return Codex's Important or Critical findings as they are (correctness defects with a concrete failing input, unmet criteria) without adding your own review; verdict pass if none. If Codex cannot be run, return available false with the reason in raw_summary; never substitute your own review.
${RULES}`, { label: 'direct-codex', phase: 'Final review', agentType: 'clerk', model: 'sonnet', effort: 'high', schema: CODEX }) : Promise.resolve(null)
    // The stored plan's risk, not this run's reply, picks the reviewer, so a resumed review keeps the implementer's choice.
    const lite = plan.tasks[0].risk !== 'security'
    const reviewPrompt = isLite => `${CTX}
${isLite ? 'lane: direct. ' : ''}Review the delivery diff git -C ${W} diff ${RANGE} for issue #${ISSUE} against its acceptance criteria ${ACS}. ${KNOW} Report Important or Critical correctness defects and unmet criteria only, each with a concrete failing input. ${isLite ? 'If the diff touches authentication or authorization, permission or command guards, secrets or credentials, CI/CD or deploy config, or data migrations, set escalate true. ' : ''}Do not edit anything.`
    let review = await call(reviewPrompt(lite), { label: 'direct-review', phase: 'Final review', agentType: lite ? 'reviewer-lite' : 'reviewer', schema: DIRECT_FINDINGS })
    let passedBy = lite ? 'reviewer-lite' : 'reviewer'
    if (lite && review && review.escalate === true) {
      review = await call(reviewPrompt(false), { label: 'direct-review-full', phase: 'Final review', agentType: 'reviewer', schema: FINDINGS })
      passedBy = 'reviewer'
    }
    const codexR = await codexP
    if (!review) return stop('direct-review', { review: null })
    if (REVIEW_CODE && (!codexR || !codexR.available)) return stop('codex-unavailable', { step: 'code', codex: codexR })
    const findings = findingsOf(review).concat(REVIEW_CODE ? findingsOf(codexR).map(f => ({ ...f, source: 'codex' })) : [])
    if (REVIEW_CODE) log(`codex review: ${findingsOf(codexR).length} blocking findings`)
    if (findings.length) {
      log(`direct review: ${findings.length} blocking findings, one fix round`)
      fix = await call(`${CTX}\n${PLAN_REF} Fix these review findings in the worktree, with a regression test for each real defect, then commit: ${JSON.stringify(findings)}. If a finding is wrong, say so in notes with evidence instead of changing code. ${FOCUSED} ${IMPL_RETURN}\n${RULES}`, { label: 'direct-fix', phase: 'Final review', agentType: 'implementer', model: 'sonnet', schema: IMPL })
      if (!implDone(fix)) return stop('direct-fix', { fix })
      const rereview = await call(`${CTX}
Re-review only these previously reported findings against the fix: ${span(fix)}; the implementer's notes: ${fix.notes}. Findings: ${JSON.stringify(findings)}. Report any finding still unresolved and any new Important or Critical defect the fix introduced.`, { label: 'direct-rereview', phase: 'Final review', agentType: 'reviewer-lite', schema: FINDINGS })
      if (!rereview || findingsOf(rereview).length) return stop('direct-review', { review: rereview, findings })
      passedBy = 'reviewer-lite'
    }
    Object.assign(d1, { reviewed_head: fix ? fix.commit : reviewHead, review_rounds: fix ? 1 : 0, reviewer: passedBy })
  }
} else {
phase('Plan')
if (plan) {
  const bad = branchProblems(plan)
  if (bad.length) { plan = null; planReviewed = false; planFindingsKept = null; return stop('plan', { step: 'resume', invalid: CONT.plan, branch_problems: bad }) }
}
// The owner's answer is read when there is no plan or a kept plan awaits it; that read carries the plan's claim renew.
const RESUME_KEPT = !!(plan && !planReviewed && planFindingsKept)
const ANSWER_NEEDED = !plan || RESUME_KEPT
if ((!plan || !planReviewed) && !ANSWER_NEEDED) {
  const lost = await renew('plan', 'Plan')
  if (lost) return lost
}
const readAnswer = async () => {
  const answer = await recall(() => call(`${CTX}
${RENEW_FIRST}
Then read the owner's answer to the decision prompt of issue #${ISSUE}: run alone, exactly, forge-claim owner-action status --repo ${SLUG} --issue ${ISSUE} --reason decision. It prints one JSON line. Change nothing: post nothing, edit nothing, end nothing. Return verdict, comment_id, questions and decisions exactly as printed.`, { label: 'owner-answer', phase: 'Plan', agentType: 'clerk', model: 'sonnet', effort: 'low', schema: withRenew(ANSWER_SCHEMA) }), r => r.renew)
  if (!answer) return stop('owner-answer', { result: answer })
  const lost = renewed(answer.renew, 'plan')
  if (lost) return lost
  if (!complete(answer, ANSWER_SCHEMA) || !['none', 'open', 'answered'].includes(answer.verdict)) return stop('owner-answer', { result: answer })
  if (answer.verdict === 'answered') {
    // An answered prompt with no decision text would let planning go on without the owner's choices.
    if (typeof answer.decisions !== 'string' || !answer.decisions.trim()) return stop('owner-answer', { result: answer })
    addDecision(answer.decisions)
  }
  return null
}
// Only findings the rules-only revise may touch resume as one. A kept plan with any other finding left has spent its one full
// revise, so it is dropped and planned again with the owner's answer; the kept state stays in the cont until that answer is read.
const RESUME_RULES = RESUME_KEPT && rulesOnly(planFindingsKept.rules, planFindingsKept.findings)
if (ANSWER_NEEDED) {
  const stopped = await readAnswer()
  if (stopped) return stopped
}
if (RESUME_KEPT && !RESUME_RULES) { plan = null; planFindingsKept = null }
if (!plan) {
  const halted = takePlan(await call(planPrompt(), { label: 'plan', phase: 'Plan', agentType: 'planner', schema: PLAN_SCHEMA }), 'plan')
  if (halted) return halted
}
const rulesReview = async triggered => {
  return call(`${CTX}
Re-check only the acceptance criteria of the revised plan at ${plan.plan_root} against every rule of ~/.agents/standards/acceptance-planning.md (read it). The findings that triggered the revision were ${JSON.stringify(triggered)}. Report each criterion that still or newly breaks a rule, with the broken rule's id in the finding's rule. Do not edit anything.`, { label: 'plan-rules-review', phase: 'Plan', agentType: 'reviewer', schema: PLAN_REVIEW })
}
// One targeted planner call fixing only the given findings, then the program's rule check and the rules re-review (D4-D6).
const rulesRevise = async findings => {
  const root = plan.plan_root
  const halted = takePlan(await call(planPrompt(`\nFix only these rule findings in your plan at ${root} in place, change nothing else, and return the full result again: ${JSON.stringify(findings)}`), { label: 'plan-rules-revise', phase: 'Plan', agentType: 'planner', schema: PLAN_SCHEMA }), 'plan-rules-revise')
  if (halted) return { halted }
  const still = planRules(plan)
  const rr = await rulesReview(findings)
  if (!rr) return { silent: true }
  return { rules: still.concat(findingsOf(rr)) }
}
// A plan-review stop keeps the revised plan unless this was the second failed rules revise (D5).
const reviewStop = (rules, findings, rounds, extra) => {
  planReviewed = false
  if (rounds >= 2) { plan = null; planFindingsKept = null } else planFindingsKept = { rules, findings, rounds }
  return stop('plan-review', { ...(extra || {}), rules, findings })
}
const SILENT = { details: 'the rules re-reviewer returned nothing' }
if (RESUME_RULES) {
  const { rules, findings, rounds } = planFindingsKept
  const r = await rulesRevise(rules)
  if (r.halted) return { ...r.halted, findings }
  if (r.silent) return reviewStop(rules, findings, rounds + 1, SILENT)
  if (r.rules.length) return reviewStop(r.rules, findings, rounds + 1)
  planFindingsKept = null
  planReviewed = true
}
if (!planReviewed) {
  const ACS0 = JSON.stringify(plan.acceptance)
  const planCodexP = REVIEW_PLAN ? call(`${CTX}
Plan: ${plan.plan_root} (task files beside it). Acceptance criteria: ${ACS0}.${SPEC}
Run the project's configured independent plan review: the contract's workflow.review.plan is the command ${REVIEW_PLAN}. Use the codex-collaboration skill (invoke it with the Skill tool) to run that Codex plan review over the plan at that path against issue #${ISSUE} in the worktree ${W}, giving it the code map ${CODE_MAP} as its code map input; this step may dispatch the Codex reviewer that skill uses, and must wait for its result in this turn. Return Codex's Important or Critical findings as they are without adding your own review; verdict pass if none. If Codex cannot be run, return available false with the reason in raw_summary; never substitute your own review.
${RULES}`, { label: 'plan-codex', phase: 'Plan', agentType: 'clerk', model: 'sonnet', effort: 'high', schema: CODEX }) : Promise.resolve(null)
  const ruleFindings = planRules(plan)
  const planReviewClaude = await call(`${CTX}
Review the implementation plan at ${plan.plan_root} (and its task files) against issue #${ISSUE} (gh issue view ${ISSUE} --repo ${SLUG} --json title,body,comments).${SPEC} ${KNOW} ${MAP_FIRST} Report only Important or Critical defects: ${PLAN_RUBRIC}, or an acceptance criterion that breaks a rule of ~/.agents/standards/acceptance-planning.md (read it; put the broken rule's id in the finding's rule). No style notes. Do not edit anything.`, { label: 'plan-review', phase: 'Plan', agentType: 'reviewer', schema: PLAN_REVIEW })
  const planCodexR = await planCodexP
  if (!planReviewClaude) return stop('plan-review', { details: 'the plan reviewer returned nothing' })
  let planFindings = ruleFindings.concat(findingsOf(planReviewClaude))
  if (REVIEW_PLAN) {
    if (!planCodexR || !planCodexR.available) return stop('codex-unavailable', { step: 'plan', codex: planCodexR })
    planFindings = planFindings.concat(findingsOf(planCodexR).map(f => ({ ...f, source: 'codex' })))
    log(`codex plan review: ${findingsOf(planCodexR).length} blocking findings`)
  }
  if (planFindings.length) {
    log(`plan review: ${planFindings.length} blocking findings, revising once`)
    const revised = await call(planPrompt(`\n${MAP_FIRST} A reviewer found these defects in your plan at ${plan.plan_root}; fix them in place and return the full result again: ${JSON.stringify(planFindings)}`), { label: 'plan-revise', phase: 'Plan', agentType: 'planner', schema: PLAN_SCHEMA })
    const halted = takePlan(revised, 'plan-revise')
    if (halted) return { ...halted, findings: planFindings }
    const still = planRules(plan)
    const rr = await rulesReview(planFindings)
    if (!rr) return reviewStop(planFindings, planFindings, 0, SILENT)
    let rules = still.concat(findingsOf(rr)), rounds = 0
    if (rulesOnly(rules, planFindings)) {
      rounds++
      const r = await rulesRevise(rules)
      if (r.halted) return { ...r.halted, findings: planFindings }
      if (r.silent) return reviewStop(rules, planFindings, rounds, SILENT)
      rules = r.rules
    }
    if (rules.length) return reviewStop(rules, planFindings, rounds)
  }
  planFindingsKept = null
  planReviewed = true
}
planRefs()
log(`plan: ${plan.tasks.length} tasks`)
if (MODE === 'plan') return stop('planned', { plan })

// ---------------- Tasks ----------------
phase('Tasks')
let tasksRenewed = false
for (const t of plan.tasks) {
  if (taskLog.some(d => d.n === t.n)) continue
  if (!tasksRenewed) {
    tasksRenewed = true
    const lost = await renew('tasks', 'Tasks')
    if (lost) return lost
  }
  const B = typeof t.branch === 'string' ? declared(plan).find(b => b.name === t.branch) || null : null
  const TW = B ? B.worktree : W
  const start = `${CTX}\n${PLAN_REF}${B ? `\nTask ${t.n} commits to the declared branch ${B.name} in the worktree ${TW} (base ${B.base}), not to ${setup.branch}: run this task's commands there (git -C ${TW}).` : ''}`
  const PUSH_HERE = B ? ` After each commit, push it alone with git -C ${TW} push origin ${B.name}.` : ''
  const halt = (stage, extra) => haltTask(t.n, stage, extra)
  let impl = await call(`${start}
Implement task ${t.n} (${t.title}) exactly as its task file ${t.file} specifies: write the failing test first and see it fail, implement, see it pass, run the task's focused test commands, then for each new test temporarily remove the code it pins and confirm it fails, restore, and commit only this task's files in the worktree. ${MAP_FIRST} ${FOCUSED} ${IMPL_RETURN}${PUSH_HERE} Return status blocked with notes if the task file is wrong or impossible.${CONT && CONT.partial === t.n ? `
An earlier attempt at this task was cut off and may have left uncommitted edits or commits in the worktree (git -C ${TW} status, git -C ${TW} diff and git -C ${TW} log ${B ? `${B.base}..HEAD` : RANGE}). Inspect them: keep what matches the task file, finish or redo the rest, and make sure the failing-test-first and mutation checks still hold for the final result; start_head is the head before this task's first commit.` : ''}
${RULES}`, { label: `impl-${t.n}`, phase: 'Tasks', agentType: 'implementer', model: 'sonnet', schema: IMPL })
  if (!implDone(impl)) return halt('task', { task: t, impl })
  const taskSpan = spanIn(TW, impl)
  const reviewer = (t.risk === 'mechanical' || t.risk === 'low') ? 'reviewer-lite' : 'reviewer'
  // reviewer-lite first-passes only a task whose declared lane is mechanical or low (its lane verification mode).
  let review = await call(`${start}
${reviewer === 'reviewer-lite' ? `lane: ${t.risk}. ` : ''}Review the diff of task ${t.n} only: ${taskSpan} (and the task file ${t.file} as its contract). ${KNOW} Report Important or Critical correctness defects and unmet task requirements only, each with a concrete failing input. No style notes. Do not edit anything.`, { label: `review-${t.n}`, phase: 'Tasks', agentType: reviewer, schema: FINDINGS })
  if (!review) return halt('task-review', { task: t, review: null })
  let rounds = 0
  while (findingsOf(review).length && rounds < 2) {
    rounds++
    const fix = await call(`${start}
Fix these review findings for task ${t.n} (${t.file}) in the worktree, with a regression test for each real defect, then commit: ${JSON.stringify(findingsOf(review))}. If a finding is wrong, say so in notes with evidence instead of changing code. ${MAP_FIRST} ${FOCUSED} ${IMPL_RETURN}${PUSH_HERE}
${RULES}`, { label: `fix-${t.n}-${rounds}`, phase: 'Tasks', agentType: 'implementer', model: 'sonnet', schema: IMPL })
    if (!implDone(fix)) return halt('task-fix', { task: t, impl: fix })
    impl = fix
    review = await call(`${start}
Re-review only these previously reported findings for task ${t.n} against the fix: ${spanIn(TW, fix)}; the implementer's notes: ${fix.notes}. Findings: ${JSON.stringify(findingsOf(review))}. Report any finding still unresolved and any new Important or Critical defect the fix introduced.`, { label: `rereview-${t.n}-${rounds}`, phase: 'Tasks', agentType: 'reviewer-lite', schema: FINDINGS })
    if (!review) return halt('task-review', { task: t, review: null })
  }
  if (findingsOf(review).length) return halt('task-review', { task: t, review })
  taskLog.push({ n: t.n, commit: impl.commit, review_rounds: rounds, reviewer, ...(B ? { branch: B.name } : {}) })
  if (B) branchTips[B.name] = impl.commit
  else tip = impl.commit
  if (partial === t.n) partial = undefined
}

// ---------------- Final review ----------------
phase('Final review')
const groups = []
const PER = 3
for (let i = 0; i < plan.tasks.length; i += PER) groups.push(plan.tasks.slice(i, i + PER))
chunked = groups.length > 1
if (SKIP_FINAL) log(`final review passed at ${finalReviewed.head}; skipped`)
if (!SKIP_REVIEW && !SKIP_FINAL) {
{
  const lost = await renew('final-review', 'Final review')
  if (lost) return lost
}
const codexP = REVIEW_CODE ? call(`${CTX}
${PLAN_REF} Acceptance criteria: ${ACS}.
Run the project's configured independent code review: the contract's workflow.review.code is the command ${REVIEW_CODE}. Use the codex-collaboration skill (invoke it with the Skill tool) to run that Codex diff review over the delivery range ${RANGE} in the worktree ${W}, with no review package;${EXTRA_RANGES()} this step may dispatch the Codex reviewer that skill uses, and must wait for its result in this turn. Return Codex's Important or Critical findings as they are (correctness defects with a concrete failing input, unmet criteria) without adding your own review; verdict pass if none. If Codex cannot be run, return available false with the reason in raw_summary; never substitute your own review.
${RULES}`, { label: 'final-codex', phase: 'Final review', agentType: 'clerk', model: 'sonnet', effort: 'high', schema: CODEX }) : Promise.resolve(null)
const finals = await parallel(groups.map((g, gi) => () => call(`${CTX}
${PLAN_REF} Acceptance criteria: ${ACS}.
Final review${chunked ? ` of chunk ${gi + 1}/${groups.length}: tasks ${g.map(t => t.n).join(', ')} only (their files: ${g.map(t => t.file).join(', ')}); grade only these tasks` : ' of the whole delivery'}: git -C ${W} diff ${RANGE}${chunked ? ' restricted to the paths these tasks own' : ''}.${EXTRA_RANGES()} ${KNOW} Two axes: correctness (real defects with a concrete failing input) and conformance (each task and each acceptance criterion of kind code is actually met, with the test or command that shows it). Report Important or Critical findings only. Do not edit anything.`, { label: `final-${gi + 1}`, phase: 'Final review', agentType: 'reviewer', schema: FINDINGS })))
const codexR = await codexP
if (finals.some(r => !r)) return stop('final-review', { details: 'a final reviewer returned nothing', finals })
let finalFindings = finals.flatMap(findingsOf)
if (REVIEW_CODE) {
  if (!codexR || !codexR.available) return stop('codex-unavailable', { step: 'code', codex: codexR })
  finalFindings = finalFindings.concat(findingsOf(codexR).map(f => ({ ...f, source: 'codex' })))
  log(`codex review: ${findingsOf(codexR).length} blocking findings`)
}
if (chunked) {
  const integ = await call(`${CTX}
${PLAN_REF} Integration review. The delivery was reviewed in ${groups.length} chunks by task; their verdicts: ${JSON.stringify(finals)}. Read the full changed-file list (git -C ${W} diff --stat ${RANGE}) and the head tree as needed.${EXTRA_RANGES()} ${KNOW} Check the interfaces between chunks and grade every acceptance criterion: ${ACS}. Report Important or Critical findings only.`, { label: 'final-integration', phase: 'Final review', agentType: 'reviewer', schema: FINDINGS })
  if (!integ) return stop('final-review', { details: 'the integration reviewer returned nothing' })
  finalFindings = finalFindings.concat(findingsOf(integ))
}
if (finalFindings.length) {
  // At most two waves: the second runs only when the first re-review's findings all narrow the first round (same kind of defect on another path); a new kind stops.
  let waveFindings = finalFindings
  const hasBranches = declared(plan).length > 0
  for (let k = 1; k <= 2; k++) {
    const fwLabel = k === 1 ? 'fix-wave' : `fix-wave-${k}`
    const rvLabel = k === 1 ? 'fix-wave-review' : `fix-wave-review-${k}`
    log(`final review: ${waveFindings.length} blocking findings, fix wave ${k}`)
    fixWaves++
    const fw = await call(`${CTX}\n${PLAN_REF} Fix these final-review findings, each real defect with a regression test, then commit: ${JSON.stringify(waveFindings)}.${k === 2 ? ` They narrow these first-round findings: ${JSON.stringify(finalFindings)}.` : ''} If a finding is wrong, explain with evidence in notes. ${FOCUSED} ${hasBranches ? IMPL_RETURN_AT(W) : IMPL_RETURN}${hasBranches ? ` A finding on a declared branch is fixed in that branch's worktree and pushed with its push form. Return branch_heads: one {name, head} per declared branch (${declared(plan).map(b => b.name).join(', ')}), head being git -C <its worktree> rev-parse HEAD after your last commit.` : ''}\n${RULES}`, { label: fwLabel, phase: 'Final review', agentType: 'implementer', model: 'sonnet', schema: hasBranches ? FIX_WAVE_IMPL : IMPL })
    if (!implDone(fw)) return stop('fix-wave', { fw, finalFindings: waveFindings, fix_waves: fixWaves })
    const collected = []
    for (const b of declared(plan)) {
      const h = headOf(fw.branch_heads, b.name)
      if (!h) return stop('fix-wave', { fw, finalFindings: waveFindings, fix_waves: fixWaves, details: `no head for the declared branch ${b.name}` })
      if (!sameSha(h, branchTips[b.name])) collected.push(`git -C ${b.worktree} diff ${branchTips[b.name]}..${h}`)
      branchTips[b.name] = h
    }
    tip = fw.commit
    const rv = await call(`${CTX}\nRe-review these final-review findings against the fix (${span(fw)}${collected.length ? ` and ${collected.join(' and ')}` : ''}); implementer notes: ${fw.notes}. Findings: ${JSON.stringify(waveFindings)}. Report any still unresolved and any new Important or Critical defect. For each finding you still report, set relation: narrowing when it is the same kind of defect as one of the findings above reached on another path, input or call site; new when it is a different kind. Unsure is new.`, { label: rvLabel, phase: 'Final review', agentType: 'reviewer', schema: FINDINGS })
    if (!rv) return stop('fix-wave-review', { rv, fix_waves: fixWaves })
    const next = findingsOf(rv)
    if (!next.length) break
    if (k === 2 || next.some(f => f.relation !== 'narrowing')) return stop('fix-wave-review', { rv, fix_waves: fixWaves })
    waveFindings = next
  }
}
if (present(tip)) finalReviewed = { head: tip, ...branchSnap() }
}
}

// ---------------- Verify ----------------
phase('Verify')
const VERIFY = {
  type: 'object',
  properties: { head: FULL_SHA, clean: { type: 'boolean' }, results: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, status: { type: 'string', enum: ['pass', 'fail', 'skipped'] }, summary: { type: 'string' } }, required: ['id', 'status', 'summary'] } } },
  required: ['head', 'clean', 'results'],
}
const verifyBodyFor = entries => `Run the project's declared verification once on the worktree head, in the foreground, each command with a Bash timeout of up to 60 minutes: ${JSON.stringify(entries)}. Run each argv with <worktree>/<its cwd> as working directory. If an entry has when_changed globs and none of the files changed (git -C ${W} diff --no-renames --name-only ${RANGE}, so a rename lists both paths) match, mark it skipped with its skip_reason. Return head (git -C ${W} rev-parse HEAD, the full sha), clean (git -C ${W} status --porcelain is empty, checked before and after the runs) and one result per id; for failures, summarize the failing tests or errors precisely. Do not change any file.
${RULES}`
const verifyBody = verifyBodyFor(setup.verification)
const verifyPrompt = `${CTX}\n${verifyBody}`
// The first verification also renews the claim (#716); the reruns do not.
const verifyFirst = `${CTX}\n${RENEW_FIRST}\n${verifyBody}`
// Every declared id needs exactly one result; skipped only where the contract gives when_changed globs; and a clean tree.
const verifyProblems = v => {
  if (!v) return [{ id: '?', summary: 'verification returned nothing' }]
  const out = v.results.filter(r => r.status === 'fail')
  for (const e of setup.verification) {
    const rs = v.results.filter(r => r.id === e.id)
    if (rs.length !== 1) out.push({ id: e.id, summary: `expected exactly one result, got ${rs.length}` })
    else if (rs[0].status === 'skipped' && !(e.when_changed && e.when_changed.length)) out.push({ id: e.id, summary: 'skipped without when_changed globs' })
  }
  if (!v.clean) out.push({ id: '?', summary: 'the worktree has uncommitted changes, so the verified tree is not the pushed head' })
  return out
}
// #741: `git diff -b --ignore-blank-lines` and the extension allow-list are a prefilter only. Carrying passes
// forward also needs the reviewer's attestation, because whitespace inside a literal can change behaviour.
const WS_INSENSITIVE = /\.(c|cc|cpp|cxx|h|hh|hpp|cs|css|scss|less|dart|go|java|js|jsx|mjs|cjs|ts|tsx|mts|cts|json|kt|kts|rs|scala|swift|php|html|xml|vue|svelte|sql|proto)$/i
const WS_CHECK = { type: 'object', properties: { whitespace_exit: { type: 'integer' }, changed_paths: STRS }, required: ['whitespace_exit', 'changed_paths'] }
const WS_REVIEW = { ...FINDINGS, properties: { ...FINDINGS.properties, whitespace_insignificant: { type: 'boolean' }, whitespace_evidence: { type: 'string' } }, required: [...FINDINGS.required, 'whitespace_insignificant', 'whitespace_evidence'] }
const wsOnly = c => !!c && c.whitespace_exit === 0 && Array.isArray(c.changed_paths) && c.changed_paths.length > 0 && c.changed_paths.every(p => typeof p === 'string' && WS_INSENSITIVE.test(p.trim()))
const attested = fr => !!fr && fr.whitespace_insignificant === true && typeof fr.whitespace_evidence === 'string' && fr.whitespace_evidence.trim().length > 0
const rerunIds = (v, fix) => {
  if (!v || !v.clean || !sameSha(v.head, fix.start_head)) return null
  if (!verifyProblems(v).every(p => p.status === 'fail' && VERIFY_IDS.includes(p.id))) return null
  const statusOf = id => { const rs = v.results.filter(r => r.id === id); return rs.length === 1 ? rs[0].status : null }
  if (!VERIFY_IDS.some(id => statusOf(id) === 'pass')) return null
  return VERIFY_IDS.filter(id => statusOf(id) !== 'pass')
}
const carry = (prev, next, rerun) => {
  const carried = prev.results.filter(r => r.status === 'pass' && !rerun.includes(r.id) && !next.results.some(n => n.id === r.id)).map(r => ({ ...r, carried_from: r.carried_from || prev.head }))
  return { ...next, results: [...next.results, ...carried] }
}
const wsCheckPrompt = f => `${CTX}
Report two facts about the verification fix ${f.start_head}..${f.commit} and change nothing. Run, alone:
git -C ${W} diff -b --ignore-blank-lines --quiet ${f.start_head} ${f.commit}
Return its exit status as whitespace_exit (0 means the fix changes only whitespace amounts and blank lines). Then run, alone:
git -C ${W} diff --no-renames --name-only ${f.start_head} ${f.commit}
Return its output lines as changed_paths. Run nothing else.
${RULES}`
const wsAsk = ws => ` The fix changes only whitespace amounts and blank lines, in ${ws.changed_paths.map(p => p.trim()).join(', ')}. Also judge whether each of its whitespace changes is insignificant: outside every string, template, character and regex literal, heredoc and raw block, and in no construct where whitespace changes behaviour or output. Return whitespace_insignificant true only when you read every hunk and that holds, with whitespace_evidence naming each changed path and why it holds there; otherwise return false, with whitespace_evidence naming the hunk where the whitespace matters.`
let verify = VERIFY_CACHED ? { head: verified.head, clean: true, results: verified.results } : null
if (!VERIFY_CACHED) {
verify = await recall(() => call(verifyFirst, { label: 'verify', phase: 'Verify', agentType: 'clerk', model: 'sonnet', effort: 'low', schema: withRenew(VERIFY) }), r => r.renew)
if (verify) {
  const lost = renewed(verify.renew, 'verify')
  if (lost) return lost
  if (!complete(verify, VERIFY)) verify = null
}
let vRounds = 0
while (verify && verifyProblems(verify).length && vRounds < 2) {
  vRounds++
  const fix = await call(`${CTX}\n${PLAN_REF} The project's verification failed: ${JSON.stringify(verifyProblems(verify))}. Find the cause in this branch's changes (git -C ${W} diff ${RANGE}), fix it with the smallest change, commit. Never weaken, skip or delete a test to make it pass. ${FOCUSED} ${IMPL_RETURN}\n${RULES}`, { label: `verify-fix-${vRounds}`, phase: 'Verify', agentType: 'implementer', model: 'sonnet', schema: IMPL })
  if (!implDone(fix)) return stop('verify-fix', { verify, fix })
  const pre = rerunIds(verify, fix)
  const ws = pre ? await call(wsCheckPrompt(fix), { label: `ws-check-${vRounds}`, phase: 'Verify', agentType: 'clerk', model: 'sonnet', effort: 'low', schema: WS_CHECK }) : null
  const asked = pre && wsOnly(ws) ? pre : null
  const fr = await call(`${CTX}\nReview this verification fix: ${span(fix)}; the failure it answers: ${JSON.stringify(verifyProblems(verify))}; implementer notes: ${fix.notes}. Report Important or Critical defects only, above all a weakened, skipped or deleted test or check.${asked ? wsAsk(ws) : ''}`, { label: `verify-fix-review-${vRounds}`, phase: 'Verify', agentType: 'reviewer', schema: asked ? WS_REVIEW : FINDINGS })
  if (!fr || findingsOf(fr).length) return stop('verify-fix-review', { review: fr })
  const rerun = asked && attested(fr) ? asked : null
  const next = await call(rerun ? `${CTX}\nA whitespace-only fix followed the verification at ${verify.head}; the declared ids not listed below passed there and are carried forward, so run only the listed ones.\n${verifyBodyFor(setup.verification.filter(e => rerun.includes(e.id)))}` : verifyPrompt, { label: `verify-${vRounds + 1}`, phase: 'Verify', agentType: 'clerk', model: 'sonnet', effort: 'low', schema: VERIFY })
  if (rerun && next && !sameSha(next.head, fix.commit)) return stop('verify', { verify: next, problems: [{ id: '?', summary: `the narrowed verification ran at ${next.head}, not at the whitespace-only fix ${fix.commit}, so no result was carried` }] })
  verify = rerun && next && Array.isArray(next.results) ? carry(verify, next, rerun) : next
}
}
if (verifyProblems(verify).length) return stop('verify', { verify, problems: verifyProblems(verify) })
if (MODE === 'ready') {
  verified = { head: verify.head, results: verify.results, contract: VERIFY_CONTRACT, ...branchSnap() }
  return stop('ready', { head: verify.head, branch: setup.branch, worktree: W, verify: verify.results, tasks: taskLog, acceptance: plan.acceptance, fix_waves: fixWaves })
}

// ---------------- Ship ----------------
phase('Ship')
{
  const unknown = badKinds(plan.acceptance)
  if (unknown.length) return stop('plan', { details: 'a plan criterion has a kind that is not code, evidence, human or note', bad_kinds: unknown })
}
const noHold = !plan.acceptance.some(isOpen)
const closesLine = noHold && INT === setup.default_branch ? `Closes #${ISSUE}` : `Refs #${ISSUE}`
const PR_SCHEMA = { type: 'object', properties: { pr: { type: 'integer' }, head: FULL_SHA, notes: { type: 'string' } }, required: ['pr', 'head'] }
const MERGE_SCHEMA = { type: 'object', properties: { merged: { type: 'boolean' }, behind: { type: 'boolean' }, merge_commit: { type: 'string' }, notes: { type: 'string' } }, required: ['merged', 'notes'] }
const CHECKS = { type: 'object', properties: { state: { type: 'string', enum: ['passed', 'failed', 'pending', 'behind'] }, head: FULL_SHA, required: STRS, passed: STRS, failing: STRS, pending: STRS, details: { type: 'string' } }, required: ['state', 'head'] }
const SYNC = { type: 'object', properties: { status: { type: 'string', enum: ['done', 'blocked'] }, conflicted: { type: 'boolean' }, merge_commit: FULL_SHA, resolved_files: STRS, tests: STRS, notes: { type: 'string' } }, required: ['status', 'conflicted', 'notes'] }
const LOCK_SCHEMA = {
  type: 'object',
  properties: { verdict: { type: 'string', enum: ['acquired', 'already_held', 'moved', 'held_by', 'lost_to', 'land-contended', 'error'] }, lock_sha: { type: 'string' }, pr: { type: 'integer' }, by: { type: 'string' }, detail: { type: 'string' } },
  required: ['verdict'],
}
const RELEASE_SCHEMA = { type: 'object', properties: { verdict: { type: 'string' }, detail: { type: 'string' } }, required: ['verdict'] }
let PR = null
let expected = verify.head
let head = expected
let syncs = 0
let round = 0
const PENDING_WAITS = 3
let pendingWaits = 0
let mg = null
let mergeRefusals = 0
let raced = false
let contended = 0
// The cross-host land lock of the integration branch (#677): taken with --wait right after the PR opens, before any sync,
// moved with a one-shot acquire after every head change, re-checked once before the merge, released after the merge and on every stop.
// lockSha is the last sha this run owned or may own: set before the pr call, whose lock may be taken before its reply is lost, then after each holding verdict to the head that acquire named.
let lockHeld = false
let lockSha = null
// The sha a move acquire may have left held when its answer was lost (#716); cleared by a definitive answer.
let lockMaybe = null
let locks = 0
let retakes = 0
const HOLDING = ['acquired', 'already_held', 'moved']
// The verdict string, or null when the agent returned nothing.
const lock = async wait => {
  locks++
  const r = await call(`Take the cross-host landing lock of the branch ${INT} for PR #${PR} of issue #${ISSUE} of ${SLUG} at the head ${expected}.
Run alone and exactly: ${LAND_ACQUIRE(expected, wait)}
${LOCK_RETURN} Run nothing else.
${RULES}`, { label: `land-lock-${locks}`, phase: 'Ship', agentType: 'clerk', model: 'sonnet', effort: 'low', schema: LOCK_SCHEMA })
  return r ? r.verdict : null
}
// Releases the last held sha once; {} when nothing was held or it was released, else lock_unreleased (and a fresh dead_agents) for the result to carry. Never throws.
const unlock = async () => {
  if (!lockHeld) return {}
  lockHeld = false
  let r = null
  let error = null
  try {
    r = await call(`Release the cross-host landing lock of the branch ${INT} held for issue #${ISSUE} of ${SLUG}.
Run alone and exactly: forge-claim land release --repo ${SLUG} --branch ${INT} --sha ${lockSha}
released and not_held are both fine. ${FORGE_TIMEOUT} Return its verdict and any detail. Run nothing else.
${lockMaybe && !sameSha(lockMaybe, lockSha) ? RELEASE_AGAIN(lockMaybe) : ''}${RULES}`, { label: 'land-unlock', phase: 'Ship', agentType: 'clerk', model: 'sonnet', effort: 'low', schema: RELEASE_SCHEMA })
  } catch (e) {
    error = String((e && e.message) || e)
    log(`land-unlock failed: ${error}`)
  }
  if (r && (r.verdict === 'released' || r.verdict === 'not_held')) return {}
  return { lock_unreleased: { sha: lockSha, ...(lockMaybe ? { maybe: lockMaybe } : {}), verdict: r ? r.verdict : null, ...(error ? { error } : {}) }, ...deadOf() }
}
// One bounded Ship fix wave: an implementer commits a fix on top of the current head (not pushed), then a fresh reviewer re-reviews it.
// The repair must start from the head the caller accepted (start_head), or the reviewer would see only its own diff and miss an unreviewed commit beneath it.
// Returns { fix, ok: false } when the fix failed, started elsewhere, or added no commit (unless rebuttal allows an answer with evidence and no commit),
// else { fix, review, moved } for the caller to grade; moved is false for an accepted rebuttal, and the head stays expected.
const shipFix = async ({ label, reviewLabel, fixPrompt, reviewPrompt, rebuttal = false }) => {
  const fix = await call(fixPrompt, { label, phase: 'Ship', agentType: 'implementer', model: 'sonnet', schema: IMPL })
  if (!implDone(fix) || !sameSha(fix.start_head, expected)) return { fix, ok: false }
  const moved = !sameSha(fix.commit, expected)
  if (!moved && !(rebuttal && present(fix.notes))) return { fix, ok: false }
  const review = await call(reviewPrompt(fix, moved), { label: reviewLabel, phase: 'Ship', agentType: 'reviewer', schema: FINDINGS })
  return { fix, review, moved, ok: true }
}
const landBody = async () => {
  // The pr call may take the lock (--wait) after opening the PR: mark the verified head as possibly held before it, so a lost reply still reaches the release.
  locks++
  lockHeld = true
  lockSha = expected
  const prR = await recall(() => call(`${CTX}
${RENEW_FIRST}
Then open the pull request for this branch. Push the branch (git -C ${W} push origin ${setup.branch}). If an open PR with head ${setup.branch} already exists (a resumed delivery), reuse it; else open one against ${INT}. Title: a short summary of the issue. Body, plain prose, no single or double quotes, dollar signs, backticks or backslashes: sections Why, What changes, Acceptance (a table with one row per criterion: id, criterion, kind, and the test or command that shows it; criteria ${ACS}), Evidence (verification ${JSON.stringify(verify.results)}; ${taskLog.length} tasks reviewed; ${LANE === 'direct' ? 'direct-lane review' : 'final review ' + (chunked ? 'chunked' : 'whole')}${REVIEW_CODE ? ' plus the configured independent review' : ''}), Merge danger; then the line ${closesLine} as the last line, with no attribution or generated-by line. Never attach or link the plan or the spec. Return pr (number) and head (full sha of the pushed head).
Then take the cross-host landing lock of the branch ${INT} for that PR at the verified head ${expected}: run alone and exactly: ${LAND_ACQUIRE(expected, true)}
${LOCK_RETURN} Return it as lock; when no PR was opened or reused, run no lock command and return lock null.
${RULES}`, { label: 'pr', phase: 'Ship', agentType: 'clerk', model: 'sonnet', effort: 'high', schema: withRenew(PR_SCHEMA, { lock: NULLABLE(LOCK_SCHEMA) }) }), r => r.renew)
  if (!prR) return stop('pr', { result: null })
  // A renew that ended, or a refused lock, means the prompt ran no lock command that holds anything.
  if (prR.renew && prR.renew.verdict !== 'renewed') lockHeld = false
  const v = prR.lock ? prR.lock.verdict : null
  const refused = v === 'land-contended' || v === 'held_by' || v === 'lost_to'
  if (refused) lockHeld = false
  const lostClaim = renewed(prR.renew, 'ship')
  if (lostClaim) return lostClaim
  if (!complete(prR, PR_SCHEMA)) return stop('pr', { result: prR })
  PR = prR.pr
  // The shipped head must be the verified head; after a sync, the reviewed merge commit.
  if (!sameSha(prR.head, verify.head)) return stop('head-moved', { pr: PR, expected: verify.head, head: prR.head })
  expected = fuller(verify.head, prR.head)
  head = expected
  if (!HOLDING.includes(v)) return stop(refused ? 'land-contended' : 'land-lock', { pr: PR, lock: v })
  for (;;) {
    round++
    // A sync merge, sync fix or CI fix moved the head: renew, push it and move the lock to it before the checks wait on it.
    const moved = !sameSha(lockSha, expected)
    if (moved) {
      const lost = await renew(`checks-${round}`, 'Ship')
      if (lost) return lost
      const pu = await call(`${CTX}
Push the branch ${setup.branch} of PR #${PR} at the head ${expected}: run alone git -C ${W} push origin ${setup.branch}, then return head (git -C ${W} rev-parse HEAD, the full sha).
${RULES}`, { label: `land-push-${round}`, phase: 'Ship', agentType: 'clerk', model: 'sonnet', effort: 'low', schema: { type: 'object', properties: { head: FULL_SHA, notes: { type: 'string' } }, required: ['head'] } })
      if (!pu) return stop('push', { pr: PR })
      if (!sameSha(pu.head, expected)) return stop('head-moved', { pr: PR, expected, head: pu.head })
      expected = fuller(expected, pu.head)
      lockMaybe = expected
      const mv = await lock(false)
      if (HOLDING.includes(mv)) {
        lockSha = expected
        lockMaybe = null
      } else if (mv === 'land-contended' || mv === 'held_by' || mv === 'lost_to') lockMaybe = null
      if (!HOLDING.includes(mv)) return stop('land-contended', { pr: PR, lock: mv })
    }
    const ck = await recall(() => call(`${CTX}
${moved ? 'Wait' : `${RENEW_FIRST}\nThen wait`} for PR #${PR} to be mergeable. 1. git -C ${W} fetch origin; if the local branch is ahead of origin/${setup.branch}, push it. head is git -C ${W} rev-parse HEAD (full sha). 2. If origin/${INT} is not an ancestor of HEAD (git -C ${W} merge-base --is-ancestor origin/${INT} HEAD fails), return state behind at once. 3. Otherwise wait in this turn until every check on head has completed, required or not: branch protection's required checks are the floor, not the bar. List every check with gh pr checks ${PR} --repo ${SLUG} --json name,bucket,link (never --required) and wait with gh pr checks ${PR} --repo ${SLUG} --watch (Bash timeout up to 60 minutes; rerun while any is pending). It can return early and a list can be partial: never treat a partial list as green, and read the list again before you answer. Bucket pass has passed; fail or cancel has failed; pending is still running; skipping never started and is ignored. Report as required the required check names from gh api repos/${SLUG}/rules/branches/${INT} (its required_status_checks rules) or else classic branch protection, none when neither answers. Return passed only when no check on head is pending, failing or cancelled, with required and passed (the names passing at head). Return failed when any check failed, required or not, with failing (every failing or cancelled name) and details (for each failing check, the last 60 lines of its failed log: gh run view <run id> --repo ${SLUG} --log-failed). Return pending with pending (the names still running) only when the wait ran out and no check failed.
${RULES}`, { label: `checks-${round}`, phase: 'Ship', agentType: 'clerk', model: 'sonnet', effort: 'low', schema: moved ? CHECKS : withRenew(CHECKS) }), r => (moved ? null : r.renew))
    if (ck && !moved) {
      const lost = renewed(ck.renew, `checks-${round}`)
      if (lost) return lost
    }
    if (!complete(ck, CHECKS)) return stop('checks', { pr: PR, checks: null })
    if (!sameSha(ck.head, expected)) return stop('head-moved', { pr: PR, expected, head: ck.head })
    expected = fuller(expected, ck.head)
    head = expected
    const failingNames = Array.isArray(ck.failing) ? ck.failing : []
    const pendingNames = Array.isArray(ck.pending) ? ck.pending : []
    const state = ck.state === 'behind' ? 'behind' : ck.state === 'failed' || failingNames.length ? 'failed' : ck.state === 'pending' || pendingNames.length ? 'pending' : ck.state
    if (state === 'pending') {
      if (++pendingWaits >= PENDING_WAITS) return stop('checks-pending', { pr: PR, pending: pendingNames, checks: ck })
      continue
    }
    if (state === 'failed') {
      if (checksFixes >= 1) return stop('checks', { pr: PR, failing: failingNames, checks: ck })
      checksFixes++
      const failing = JSON.stringify(failingNames)
      const w = await shipFix({
        label: 'fix-ci', reviewLabel: 'fix-ci-review',
        fixPrompt: `${CTX}\n${PLAN_REF} The checks of PR #${PR} failed at ${expected}: ${failing}. Log tail: ${ck.details || 'none given'}. Find the cause in this branch's changes (git -C ${W} diff ${RANGE}), fix it with the smallest change and a regression test that fails without the fix, then commit. Do not push: the next checks step pushes. Never weaken, skip or delete a test or check to make it pass. ${FOCUSED} ${IMPL_RETURN}\n${RULES}`,
        reviewPrompt: fix => `${CTX}\nReview this fix for failing checks: ${span(fix)}; the failure it answers: ${failing} (${ck.details || 'no log'}); implementer notes: ${fix.notes}. Report Important or Critical defects only, above all a weakened, skipped or deleted test or check, or a fix with no regression test. Do not edit anything.`,
      })
      if (!w.ok) return stop('checks-fix', { pr: PR, checks: ck, fix: w.fix })
      if (!w.review || findingsOf(w.review).length) return stop('checks-fix-review', { pr: PR, checks: ck, review: w.review })
      expected = w.fix.commit
      continue
    }
    if (state === 'passed') {
      // One call: renew, the pre-merge lock check (still held or moved merges; retaken after a loss rechecks first, once), then the merge.
      locks++
      mg = await recall(() => call(`${CTX}
${RENEW_FIRST}
Then re-check the cross-host landing lock of the branch ${INT} for PR #${PR}: run alone and exactly: ${LAND_ACQUIRE(expected, false)}
${LOCK_RETURN} Return it as lock.
Only when lock's verdict is already_held or moved, merge PR #${PR}: run, alone and exactly: ${UNSET}gh pr merge ${PR} --repo ${SLUG} --${STRATEGY} --match-head-commit ${head}${setup.delete_branch ? ' --delete-branch' : ''}
Then read gh pr view ${PR} --repo ${SLUG} --json state,mergeCommit: merged is true only when state is MERGED. Never retry with another form; on a guard refusal or a head mismatch return merged false with the exact message, and behind true only when the refusal says the head branch is not up to date with the base branch (the integration branch moved), else false. On any other lock verdict run nothing else and return merged false with the verdict in notes.
${RULES}`, { label: 'merge', phase: 'Ship', agentType: 'clerk', model: 'sonnet', effort: 'low', schema: withRenew(MERGE_SCHEMA, { lock: NULLABLE(LOCK_SCHEMA) }) }), r => r.renew)
      if (!mg) return stop('merge', { pr: PR, merge: null })
      const pre = mg.lock ? mg.lock.verdict : null
      if (HOLDING.includes(pre)) lockSha = expected
      const lost = renewed(mg.renew, 'merge')
      if (lost) return lost
      if (!HOLDING.includes(pre)) return stop('land-contended', { pr: PR, lock: pre })
      if (pre === 'acquired') {
        if (++retakes >= 2) return stop('land-contended', { pr: PR, lock: pre })
        continue
      }
      // The folded schema requires only the renew, and a merged PR needs no notes: only merged decides.
      if (typeof mg.merged !== 'boolean') return stop('merge', { pr: PR, merge: mg })
      if (mg.merged) return null
      // Refused as not up to date: the next round's checks step fetches, reports behind and syncs; three refusals, or any other, stop.
      // That sync is bounded by the refusal budget alone, so syncs made before the first merge attempt never consume it.
      if (!mg || mg.behind !== true || ++mergeRefusals >= 3) return stop('merge', { pr: PR, merge: mg })
      raced = true
      continue
    }
    if (!raced) {
      if (contended >= 2) return stop('sync-contention', { pr: PR, syncs })
      contended++
    }
    raced = false
    syncs++
    const sy = await call(`${CTX}
The branch is behind ${INT}. Merge origin/${INT} into it in the worktree (git -C ${W} merge origin/${INT}). If it conflicts, resolve each conflict keeping both sides' intent, commit the merge, and run only the tests covering the files the resolution touched. Do not push. Return conflicted, merge_commit (full sha), resolved_files and the tests you ran; status blocked with notes if you cannot resolve it safely.
${RULES}`, { label: `sync-${syncs}`, phase: 'Ship', agentType: 'implementer', model: 'sonnet', schema: SYNC })
    if (!sy || sy.status !== 'done' || !present(sy.merge_commit)) return stop('sync', { pr: PR, sync: sy })
    expected = sy.merge_commit
    if (sy.conflicted) {
      const sr = await call(`${CTX}
Review the conflict resolution in merge commit ${sy.merge_commit}: git -C ${W} show --cc ${sy.merge_commit} and the resolved files ${JSON.stringify(sy.resolved_files || [])}; the tests run: ${JSON.stringify(sy.tests || [])}. Report Important or Critical defects only: a dropped change from either side, a broken merge of intent, a resolved file whose tests were not run.`, { label: `sync-review-${syncs}`, phase: 'Ship', agentType: 'reviewer', schema: FINDINGS })
      if (!sr) return stop('sync-review', { pr: PR, review: sr })
      if (findingsOf(sr).length) {
        if (syncFixes >= 1) return stop('sync-review', { pr: PR, review: sr })
        syncFixes++
        const w = await shipFix({
          label: `fix-sync-${syncs}`, reviewLabel: `fix-sync-review-${syncs}`,
          rebuttal: true,
          fixPrompt: `${CTX}\nA reviewer found defects in the conflict resolution of merge commit ${sy.merge_commit} (git -C ${W} show --cc ${sy.merge_commit}): ${JSON.stringify(findingsOf(sr))}. Fix each real defect on top of the merge with a regression test (never redo or rewrite the merge), then commit; if a finding is wrong, commit nothing for it and say so with evidence in notes. Do not push. ${FOCUSED} ${IMPL_RETURN}\n${RULES}`,
          reviewPrompt: (fix, moved) => `${CTX}\nRe-review these conflict-resolution findings against ${moved ? `the fix (${span(fix)}) made on top of` : 'the implementer\'s rebuttal (no new commit) of'} merge commit ${sy.merge_commit}: ${JSON.stringify(findingsOf(sr))}; implementer notes: ${fix.notes}. ${moved ? '' : `Check each rebuttal against the code yourself (git -C ${W} show --cc ${sy.merge_commit}); a finding the evidence does not refute is still unresolved. `}Report any still unresolved and any new Important or Critical defect. Do not edit anything.`,
        })
        if (!w.ok) return stop('sync-fix', { pr: PR, review: sr, fix: w.fix })
        if (!w.review || findingsOf(w.review).length) return stop('sync-review', { pr: PR, review: w.review, sync_review: sr, fix: w.fix })
        if (w.moved) expected = w.fix.commit
      } else if (finalReviewed) {
        finalReviewed = { ...finalReviewed, accepted: [...(finalReviewed.accepted || []), sy.merge_commit] }
      }
    }
  }
}
let landed
let released = {}
try {
  landed = await landBody()
} finally {
  released = await unlock()
}
if (landed) return { ...landed, ...released }

const finished = await closeOut(PR, mg.merge_commit, W, head)
return finished.stage === 'done' ? { ...finished, chunked, syncs, verify: verify.results, ...released } : { ...finished, ...released }
