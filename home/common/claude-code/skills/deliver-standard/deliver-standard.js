export const meta = {
  name: 'deliver-standard',
  description: 'Deliver one standard-lane tracker issue: plan, implement and review each task, final review, verify once, ship',
  whenToUse: 'A standard-lane issue the user asked to deliver with this program; args {repo_root, issue, session_id|batch_id, mode?, lane?, decisions?, spec?, review_sizing?, clerk_model?, cont?, amend?}; mode plan stops after plan review, ready after verify with no PR, ship (the default) merges; lane direct has no plan: one implementer following deliver-direct, one fresh reviewer, at most one fix round; review_sizing true (default off) narrows the Claude plan review to rules, conventions and consistency when the Codex plan review runs, and chunks the final review only above 1500 changed lines; clerk_model sonnet (the default) or haiku sets the model of the status clerk steps (a trial, #803); the setup steps and every step that emits a lifecycle verb stay on sonnet (#813); amend (a resume of a standard-lane cont with a plan) lists {file, find, replace} edits of files in cont.setup.plan_dir, applied by plan-amend before the next task and recorded under an Amendments heading in plan.md; a file outside plan_dir, or a find text that does not occur exactly once, stops at stage amend with the cont unchanged',
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
// needs_user stop, or to a blocked task, #996; decisions also come from a fully ticked decision prompt read after the claim), spec (path of an approved design spec), mode (plan: stop after the plan
// review with { stage: 'planned', plan, cont }; ready: stop after verify with { stage: 'ready',
// head, branch, worktree, verify, flaky? (#972: [{id, summary}], each check that failed outside the branch's changed files and passed on its one rerun), outside_fixes? (#972: [{file, why}], each file outside the branch's diff a verification fix edited, with the cause it established; a done result carries both too), tasks, acceptance, fix_waves, cont } and no PR, keeping the claim;
// ship, the default: merge. A ready cont resumed in ship skips the final review and verify when
// the head is unchanged and the tree clean), lane (standard, the default, or direct: no planner, one
// implementer following the deliver-direct skill, one fresh reviewer and at most one fix round; a cont keeps
// its lane and no direct plan mode exists), cont (the `cont` object of an earlier stop, passed
// back unchanged to resume; see RESUME below), review_sizing (boolean, default off, #747: sized Claude reviews; an argument only, never kept in cont, so a resume passes it again), clerk_model (sonnet, the default, or haiku, #803: the model of every clerk call except the setup steps (setup, worktree) and the steps that emit a lifecycle verb (land-push, pr, land-lock, land-relock, merge, land-unlock, hold), which stay on sonnet, #813; an argument only, never kept in cont, so a resume passes it again), amend (#811: on a resume of a standard-lane cont with a plan, a non-empty list of {file, find, replace} edits of files in cont.setup.plan_dir, file relative to it or absolute under it; a clerk applies them all or none with plan-amend before the next task and records each under Amendments in plan.md; an argument only, never kept in cont, and an applied edit sent again is skipped).
// Every policy value comes from the project contract that setup resolves; this
// file carries no project literal and defaults no policy value.
//
// CLAIM: the claim is a forge-claim claim: acquired before the worktree step, renewed
// before each stage boundary (the tasks boundary's renew rides in the first implementer call, #745; a fresh run's setup acquire, or after an already_held acquire the setup's own renew, stands for the plan boundary's renew, #745; a renew that finds the claim ended stops with no cont; one
// that gets no answer stops with a cont whose resume acquires again), released at close-out. A renew or acquire that
// answers `error` with `transient` (forge-claim's own transport retries ran out) is re-called once, a folded step whole, before it stops (#740).
//
// A fresh run re-adopts an existing branch or worktree (never resetting it) and stops `dirty` when it holds uncommitted changes.
//
// RESUME: every stop from the claim on returns { stage, ..., cont }, where cont is
// { setup, lane, plan (declared branches, when any, as [{name, worktree, base, head, current, toplevel, common_dir, clean}]), plan_reviewed, plan_findings?, prior_findings? (#988: the blocking findings left on each plan this delivery dropped after its review, bounded; carried through every stop until a plan passes review, and shown to the planner that plans again), decisions?, done, pr? (a batch-built close-out cont: the PR the batch merged), fix_waves, fix_findings? (#924: the findings a fix-wave-review stop left open, bounded; the resume's first fix wave gets them with what its fresh final review raises; #940: such a stop also carries diverging: {file, waves} beside cont when the waves spent across runs reached FIX_WAVES_BOUND and a finding it left open is in a file the findings carried into the run named, and deliver-batch then hands the issue to the owner instead of relaunching it), checks_fixes?, sync_fixes?, verified?, final_reviewed?, partial?, blocked? (#996: {task, notes, asked?}, the task whose implementer returned blocked and its notes, kept until that task runs again; an amend with no decision clears it and the implementer runs on the plan files as they then are; see BLOCKED), reordered? (#896: [{task, after, notes}], each a blocked task moved once to just after the later task it named; cont.plan.tasks is already in that order), claim_incomplete? }. Passing it back as args.cont
// re-adopts the claimed worktree (setup re-checks it and refuses a dirty tree
// unless cont.partial names the task that left the edits), reuses cont.plan
// (reviewing it first unless plan_reviewed; a plan-review stop keeps the revised plan with plan_findings { rules, findings, rounds, noted? (#988: the rules reviewer's minor findings on the criteria of rules, context for the revise only) }, and the resume reads the owner's answer and, when every finding left names a rule and none has source codex, runs one rules-only revise of it whatever triggered the full revise (#823), dropping the plan once rounds reach two; any other finding left has spent the plan's one full revise, so the resume plans again), skips the tasks in cont.done, then
// runs final review, verify and ship again (ship reuses an open PR). Every resume re-reads the facts of each branch cont.plan declares (a missing or wrong one stops setup with branch_heads.<name> missing, but only for a plan whose declarations are valid: an invalid one is dropped by the Plan section first); cont.verified and cont.final_reviewed carry branches { <name>: <head> }, and a resume reuses either only when every declared head the setup re-read is unchanged. When the PR
// is already merged, the re-adopt goes straight to close-out; that PR is the delivery's own only when it is cont.pr or carries a commit of cont.done (#752). A resume skips the final review when cont.final_reviewed names the head it
// passed at and the head is unchanged or only gained integration-branch merges with no unreviewed conflict resolution; a stop between a
// sync merge and its acceptance drops the marker. A result also carries dead_agents,
// the labels of agents that returned nothing or threw, when any did. A red check, and a sync-review
// finding, each get one fix wave per delivery (an implementer with a regression test, then a fresh reviewer); a second one stops with cont.
//
// LAND: ship opens the PR at the verified head, takes the cross-host land lock of the integration branch with --wait
// (the CLI does the waiting); the same PR call then waits for the first checks once the lock is held (#801). Later it syncs, pushes and moves the lock after every head change, waits for every check on head (issue 756),
// re-checks the lock once, merges and releases it; the lock is released on every stop after it was taken, and a release that
// fails is reported as lock_unreleased on the result (#677). After a merge the lock is released first thing in the hold call;
// a release that call does not confirm gets one standalone release after close-out (#801). Every stop before the merge still releases it.
// A sync merge that conflicts is aborted and the lock released: its resolution, review and fix wave run outside the lock, and the accepted
// head takes it again with --wait in the next round's checks call (#913, at lockOut).
// Before it asks for the lock, the pr call probes whether the integration branch merges cleanly into the head (#941, PROBE): a conflict found
// there is resolved, reviewed and fixed first, holding and waiting for nothing, and the accepted head then takes the lock for the first time.
//
// FOLDS (#801): consecutive clerk steps with no program decision between them share one call. Folded: the lock release into the hold call,
// the first poll into the pr call, a moved round's renew into its push call, and its lock move into its checks call. Kept separate, each with a program
// decision between the two: checks then merge (the state picks fix, sync, re-poll or merge), merge then release (a refused or retaken merge loops
// instead), hold then close-out (the hold's gates read its reply first); the push then the lock move (the pushed full sha is the value the lock
// command names, so the program must read the push reply first); and the renew before the final review and the verify, which are not consecutive
// (reviewers run between them; the verify call already carries its own renew).
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
if (args.review_sizing !== undefined && typeof args.review_sizing !== 'boolean') return { stage: 'args', error: 'review_sizing must be a boolean' }
const REVIEW_SIZING = args.review_sizing === true
if (args.clerk_model !== undefined && !['sonnet', 'haiku'].includes(args.clerk_model)) return { stage: 'args', error: 'clerk_model must be sonnet or haiku' }
const CLERK_MODEL = args.clerk_model === undefined ? 'sonnet' : args.clerk_model
// #813: a setup step or one that emits a lifecycle verb must reproduce a wide schema or a guard-exact command, so it never takes the trial model.
const DEFAULT_CLERK_MODEL = 'sonnet'
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
const FORGE_TIMEOUT = 'Give each forge-claim command a Bash timeout of 20 minutes (1200000 ms). Only a land acquire command that ends in --wait gets more: the flag takes no value, so write nothing after it, and the command itself waits for up to 50 minutes and then answers land-contended by itself, so give it a Bash timeout of 60 minutes (3600000 ms) and never run it in the background. The reason for both: forge-claim retries a forge outage itself before it prints its one JSON line.'
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
    findings: { ...FINDINGS.properties.findings, items: { ...FINDINGS.properties.findings.items, properties: { ...FINDINGS.properties.findings.items.properties, rule: { type: 'string', enum: ['R1', 'R2', 'R3', 'R4', 'R5', 'R6', 'R7', 'R8', 'R9'] }, ac: { type: 'string' } } } },
  },
}
const CODEX = {
  type: 'object',
  properties: { available: { type: 'boolean' }, verdict: { type: 'string', enum: ['pass', 'findings'] }, findings: FINDINGS.properties.findings, raw_summary: { type: 'string' } },
  required: ['available', 'verdict', 'findings'],
}
// The delivery's changed-line count from the diff-size clerk; measured false means it could not be read.
const SIZE_SCHEMA = { type: 'object', properties: { measured: { type: 'boolean' }, changed_lines: { type: 'integer', minimum: 0 } }, required: ['measured'] }
const IMPL = {
  type: 'object',
  properties: { status: { type: 'string', enum: ['done', 'blocked'] }, start_head: { type: 'string' }, commit: { type: 'string' }, tests: { type: 'array', items: { type: 'string' } }, mutation_checked: { type: 'boolean' }, notes: { type: 'string' }, blocked_on: { type: 'integer' } },
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
// #950: a final-review fix wave and its re-review each also return the files the wave's commits changed in the issue worktree.
const withChanged = schema => ({ ...schema, properties: { ...schema.properties, changed_files: STRS } })
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
    ok: { type: 'boolean' }, reason: { type: 'string' }, details: { type: 'string' }, transient: { type: 'boolean' },
    host: { type: 'string' }, slug: { type: 'string' }, integration_branch: { type: 'string' }, default_branch: { type: 'string' },
    branch: { type: 'string' }, worktree_path: { type: 'string' }, head: { type: 'string' },
    merged_pr: { type: 'integer' }, dirty: { type: 'boolean' }, duplicate_pr: { type: 'integer' },
    merged_refs: { type: 'array', items: { type: 'object', properties: { number: { type: 'integer' }, closes: { type: 'boolean' } }, required: ['number', 'closes'] } },
    merged_heads: { type: 'array', items: { type: 'object', properties: { number: { type: 'integer' }, commits: STRS }, required: ['number', 'commits'] } },
    since_reviewed: { type: 'string', enum: ['same', 'merge_only', 'moved'] },
    branch_heads: BRANCH_HEADS,
    existing: { type: 'object', properties: { local_branch: { type: 'boolean' }, remote_branch: { type: 'boolean' }, worktree: { type: 'boolean' }, dirty: { type: 'boolean' }, status: { type: 'string' }, head: { type: 'string' } } },
    unset_env: STRS,
    merge_strategy: { type: 'string' }, delete_branch: { type: 'boolean' },
    review: { type: 'object', properties: { code: { type: 'string' }, plan: { type: 'string' } } },
    review_state: { type: 'object', properties: { code: REVIEW_STATE, plan: REVIEW_STATE } },
    knowledge: { type: 'object', properties: { standards: STRS, hints: STRS, rejections: STRS } },
    verification: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, argv: STRS, cwd: { type: 'string' }, when_changed: STRS, skip_reason: { type: 'string' }, pre_commit: { type: 'boolean' } }, required: ['id', 'argv', 'cwd'] } },
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
const ANSWER_SCHEMA = { type: 'object', properties: { verdict: { type: 'string' }, comment_id: { type: ['integer', 'null'] }, questions: { type: 'array', items: { type: 'object' } }, decisions: { type: 'string' } }, required: ['verdict'] }
// The fresh setup also claims the issue and sets up the worktree (#716): holder, acquire and claim ride beside its own fields;
// a standard-lane setup also reads the owner's answer and, after an already_held acquire, renews the claim (#745): answer and renew.
// #870: the claim fields are required (null on a refusal before the claim), so a reply cannot leave out a claim it took.
const SETUP_FOLDED = { ...SETUP_SCHEMA, properties: { ...SETUP_SCHEMA.properties, holder: NULLABLE({ type: 'string' }), acquire: NULLABLE(ACQUIRE_SCHEMA), claim: NULLABLE(CLAIM_SCHEMA), answer: NULLABLE(ANSWER_SCHEMA), renew: NULLABLE(RENEW_SCHEMA) }, required: ['ok', 'holder', 'acquire', 'claim'] }
const withRenew = (s, extra = {}) => ({ ...s, properties: { ...s.properties, renew: RENEW_SCHEMA, ...extra }, required: ['renew'] })
// A reply is complete when every member the schema requires is present and not null (a folded schema requires only its renew).
const complete = (r, schema) => !!r && schema.required.every(k => r[k] !== undefined && r[k] !== null)
// A renew or acquire that ran out of forge-claim's transport retries is re-called once (#740); the second reply stands whatever it is.
const transientError = r => !!r && r.verdict === 'error' && r.transient === true
const recall = async (make, pick = r => r) => { const r = await make(); return r && transientError(pick(r)) ? make() : r }
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
      // #864: the delivery's own branch is where an undeclared task commits anyway, so naming it declares nothing.
      if (!isEntry(t) || t.branch === undefined || t.branch === setup.branch) continue
      if (typeof t.branch !== 'string' || !good.some(g => g.name === t.branch)) out.push(`task ${show(t.n)}: branch ${show(t.branch)} is not declared`)
    }
  }
  return out
}

// ---------------- Stop reason (#869) ----------------
// One line saying why a stop stopped: its stage, then the detail the stop already carries, capped. Every stop from the claim on carries it as reason
// (planned and ready are not stops); a setup stop and an ended claim do not, and deliver-batch, which shows the reason in the stopped issue's row, reads those stops' own fields.
const REASON_MAX = 300
const implDone = i => !!(i && i.status === 'done' && present(i.commit) && present(i.start_head))
const stopReason = (stage, x) => {
  const parts = []
  const say = v => { if (typeof v === 'string' && v.trim()) parts.push(v) }
  const names = (k, what) => { if (Array.isArray(x[k]) && x[k].length) say(`${what} ${x[k].map(v => (isEntry(v) ? v.id || v.ac || v.file : v)).join(', ')}`) }
  const task = isEntry(x.task) ? `task ${x.task.n} ` : ''
  // #940: a stop whose fix waves do not converge says so first, so the cap cuts the findings and never the verdict.
  if (isEntry(x.diverging)) say(`the fix waves do not converge on ${String(x.diverging.file).slice(0, 120)} after ${x.diverging.waves} waves; an owner decision on the design is needed`)
  // #988: a criterion whose classification the rules revise changed and that then broke another classification rule; said first, as the diverging verdict is.
  if (isEntry(x.conflict) && Array.isArray(x.conflict.rules)) say(`the acceptance rules ${x.conflict.rules.join(' and ')} conflict for ${x.conflict.ac}: the revise that settled one broke the other; an owner decision on how ${x.conflict.ac} is classified is the expected way out: ${x.conflict.revises_left ? 'a relaunch without one gets the one rules revise left' : 'the plan was dropped, and a relaunch without one plans again'}`)
  say(x.details)
  say(x.error)
  if (Array.isArray(x.branch_problems)) say(`branch problems: ${x.branch_problems.join('; ')}`)
  else if (own(x, 'invalid')) say(`the ${x.step} reply is not a well-formed plan`)
  if (Array.isArray(x.needs_user)) say(`${x.needs_user.length} question(s) for the owner`)
  // #896: why a blocked task was not moved, ahead of the implementer's notes so the cap cuts the notes.
  if (present(x.order)) say(`${task}${x.order}`)
  if (isEntry(x.blocked)) say(`${task}${['blocked', x.blocked.notes].filter(present).join(': ')}`)
  for (const k of ['impl', 'fix', 'fw']) {
    if (own(x, k) && !implDone(x[k])) say(isEntry(x[k]) ? `${task}${[x[k].status, x[k].notes].filter(present).join(': ') || 'the implementer gave no status'}` : `${task}the implementer returned nothing`)
  }
  const reviews = ['review', 'rv'].filter(k => own(x, k)).map(k => x[k])
  const found = Array.isArray(x.rules) && x.rules.length ? x.rules : Array.isArray(x.findings) ? x.findings : reviews.flatMap(r => (isEntry(r) && Array.isArray(r.findings) ? findingsOf(r) : []))
  if (found.length) say(`${task}${found.length} finding(s)${isEntry(found[0]) && present(found[0].summary) ? `: ${found[0].summary}` : ''}`)
  else if (reviews.some(r => !r)) say(`${task}the reviewer returned nothing`)
  if (Array.isArray(x.problems)) say(x.problems.filter(isEntry).map(q => [q.id, q.summary].filter(present).join(': ')).join('; '))
  names('failing', 'failing checks')
  names('pending', 'pending checks')
  names('code_unmet', 'code criteria unmet:')
  names('bad_kinds', 'criteria:')
  names('refused', 'refused:')
  if (present(x.expected)) say(`expected ${x.expected}, head ${present(x.head) ? x.head : 'unread'}`)
  if (own(x, 'lock')) say(`lock ${(isEntry(x.lock) ? x.lock.verdict : x.lock) || 'gave no verdict'}`)
  if (own(x, 'renew')) say(`renew${present(x.at) ? ` at ${x.at}` : ''}: ${isEntry(x.renew) ? x.renew.detail || x.renew.verdict || 'no verdict' : 'no reply'}`)
  if (stage === 'review-blocked') say(`the ${x.review} review is blocked`)
  for (const k of ['result', 'amend', 'merge', 'sync', 'checks', 'close_out', 'hold']) {
    if (!own(x, k) || parts.length) continue
    const v = x[k]
    say(isEntry(v) ? [v.reason, v.verdict, v.status, v.details, v.detail, v.notes].filter(present).join(', ') : `the ${k} step returned nothing`)
  }
  const text = [stage, parts.join('; ')].filter(present).join(': ').replace(/\s+/g, ' ').trim()
  // #996: the ways out of a blocked task end the reason, after the cap, so long notes never cut them.
  const tail = present(x.ways) ? `; ${x.ways}` : ''
  const room = REASON_MAX - tail.length
  return `${text.length > room ? `${text.slice(0, room - 3)}...` : text}${tail}`
}
const why = r => ({ ...r, reason: stopReason(r.stage, r) })

// ---------------- Amend (#811) ----------------
// An owner's amendment of the plan on a resume, checked before any agent runs; every refusal returns the cont unchanged.
const AMEND = args.amend === undefined ? null : args.amend
if (AMEND !== null && !CONT) return { stage: 'args', error: 'amend needs a cont: it amends the plan of a resumed delivery' }
if (AMEND !== null && !(Array.isArray(AMEND) && AMEND.length > 0 && AMEND.every(e => isEntry(e) && typeof e.file === 'string' && e.file !== '' && typeof e.find === 'string' && e.find !== '' && typeof e.replace === 'string'))) {
  return why({ stage: 'amend', error: 'amend must be a non-empty list of {file, find, replace}: file and find non-empty strings, replace a string', cont: CONT })
}
if (AMEND !== null && (LANE !== 'standard' || !isEntry(CONT.plan) || typeof CONT.plan.plan_root !== 'string' || CONT.plan.plan_root === '' || !isEntry(CONT.setup) || typeof CONT.setup.plan_dir !== 'string' || CONT.setup.plan_dir === '')) {
  return why({ stage: 'amend', error: 'amend needs a standard-lane cont whose plan has a plan_root and whose setup has a plan_dir', cont: CONT })
}
const AMEND_DIR = AMEND !== null ? CONT.setup.plan_dir.replace(/\/+$/, '') : null
// The absolute path of an amend file when it is spelled under plan_dir, else null (Task 1's command checks the resolved paths).
const amendTarget = f => {
  if (!canonPath(AMEND_DIR)) return null
  if (f.startsWith('/')) return canonPath(f) && f.startsWith(`${AMEND_DIR}/`) ? f : null
  const parts = f.split('/')
  return parts.every(c => /^[A-Za-z0-9._-]+$/.test(c) && c !== '.' && c !== '..') ? `${AMEND_DIR}/${f}` : null
}
if (AMEND !== null) {
  const refused = AMEND.filter(e => amendTarget(e.file) === null).map(e => ({ file: e.file, reason: 'outside plan_dir' }))
  const root = CONT.plan.plan_root
  if (!root.startsWith('/') || amendTarget(root) === null) refused.push({ file: root, reason: 'outside plan_dir' })
  if (refused.length) return why({ stage: 'amend', refused, details: 'an amend file or the plan root is outside cont.setup.plan_dir; nothing was applied', cont: CONT })
}
// ---------------- Blocked task (#996) ----------------
// A task stop whose implementer returned blocked keeps { task, notes } in cont.blocked. Running that task again with the same task file
// blocks again, so its resume needs something new from the owner: a decision the cont does not hold yet (args.decisions; a planner then
// revises the task file from it and the notes before the implementer runs, and in the direct lane, which has no plan, the implementer
// gets both), or an amend. With neither it stops here, before any agent runs, with the cont unchanged. asked marks a revise whose planner
// asked the owner: that resume reads the decision prompt's answer first. A cont from before this member (partial with no blocked) cannot
// tell a blocked task from a cut-off one, so it resumes as it always did: the implementer runs again.
// The decision whose whole text is rerun is the third way out, for a cause outside the task file (a rejected token the owner repaired):
// it clears blocked and runs the implementer on the unchanged task file with no planner step, and is never kept as a decision.
const NOTES_MAX = 2000
const BLOCKED = CONT && isEntry(CONT.blocked) && Number.isInteger(CONT.blocked.task) && CONT.partial === CONT.blocked.task &&
  !(Array.isArray(CONT.done) && CONT.done.some(d => isEntry(d) && d.n === CONT.blocked.task)) && (LANE === 'direct' || (isEntry(CONT.plan) && CONT.plan_reviewed === true))
  ? { task: CONT.blocked.task, notes: typeof CONT.blocked.notes === 'string' ? CONT.blocked.notes : '', ...(CONT.blocked.asked === true ? { asked: true } : {}) } : null
const RERUN_WORD = typeof args.decisions === 'string' && args.decisions.trim() === 'rerun'
const RERUN = !!BLOCKED && RERUN_WORD
const heldDecision = d => !!CONT && Array.isArray(CONT.decisions) && CONT.decisions.includes(d)
// The decision that settles the blocked task: one this resume brings that the cont does not hold.
let newDecision = BLOCKED && !RERUN_WORD && typeof args.decisions === 'string' && args.decisions.trim() && !heldDecision(args.decisions) ? args.decisions : null
const WAYS_OUT = LANE === 'direct' ? 'resume with decisions (the implementer gets it with these notes), or decisions rerun if the cause was outside the task' : 'resume with decisions (a planner revises the task file), amend {file, find, replace}, or decisions rerun if the cause was outside the task file'
const UNSETTLED = { details: 'not run again: this resume brings nothing new from the owner', ways: WAYS_OUT }
if (BLOCKED && !RERUN && newDecision === null && AMEND === null && !(BLOCKED.asked && LANE === 'standard')) return why({ stage: 'task', task: { n: BLOCKED.task }, blocked: BLOCKED, ...UNSETTLED, cont: CONT })
const AMEND_STOP = AMEND === null ? null
  : Number.isInteger(CONT.partial) ? `the stop at task ${CONT.partial}`
  : (() => {
    const next = Array.isArray(CONT.plan.tasks) ? CONT.plan.tasks.find(t => isEntry(t) && !(Array.isArray(CONT.done) && CONT.done.some(d => isEntry(d) && d.n === t.n))) : null
    return next ? `the stop before task ${next.n}` : 'the stop after the last task'
  })()
const AMEND_INPUT = AMEND !== null ? { plan_dir: AMEND_DIR, plan_root: CONT.plan.plan_root, stop: AMEND_STOP, edits: AMEND.map(e => ({ file: amendTarget(e.file), find: e.find, replace: e.replace })) } : null
const AMEND_SCHEMA = { type: 'object', properties: { status: { type: 'string', enum: ['applied', 'refused', 'error'] }, edits: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, exists: { type: 'boolean' }, occurrences: { type: 'integer', minimum: 0 }, already: { type: 'boolean' } }, required: ['file', 'exists', 'occurrences', 'already'] } }, refused: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, reason: { type: 'string' } }, required: ['file', 'reason'] } }, detail: { type: 'string' } }, required: ['status', 'edits', 'refused'] }

// ---------------- Setup ----------------
phase('Setup')
const CONTRACT_READ = `Run: hostname -s and return its output as host. Run: resolve-project resolve --repo-root ${REPO}
On refusal return ok=false, reason contract, and in details the resolver's error.code, repair_id and ordered violations exactly. From the snapshot return:
- slug: bindings.tracker.repo_slug; unset_env: bindings.tracker.credential_env.unset_before_invocation (run every gh command after unsetting exactly these names, nothing else).
- integration_branch and default_branch: bindings.vcs.integration_branch and bindings.vcs.default_branch; merge_strategy and delete_branch: bindings.vcs.merge.strategy and bindings.vcs.merge.delete_branch.
- review: the command ids at bindings.workflow.review.code and .plan (omit an absent one); review_state: for code and plan, the state of the capability review.code and review.plan (available, blocked or unsupported; absent if the capability is missing).
- knowledge: bindings.paths.standards, bindings.paths.hints and bindings.paths.rejections, each as given (empty when absent).
- verification: for each id in bindings.workflow.verification its bindings.commands argv, its cwd relative to project.root (. for the root), and any bindings.workflow.verification_conditions entry (when_changed globs, skip_reason), and pre_commit: true on an entry whose verification_conditions entry has pre_commit true (omit pre_commit otherwise).`
// Labels of agents that returned nothing or threw: deliver-batch's breaker reads them (#636).
const DEAD = []
// #987: every reviewer and implementer step opens with its one-sentence turn procedure. Measured over four runs, both kinds sent one
// tool call in 80 to 100% of their tool messages at up to 183k of context; the planner, under the same wording first in its prompt, 27%.
// Added in call(), not per prompt, so no site of either kind can miss it. reviewer-lite is left out: a median of three turns under 20k.
const ROUNDS = {
  reviewer: `Look things up in rounds: load the files under review in one message, then put every open question's Bash, Grep or Read call in the same message as the others, never one small lookup per turn.`,
  implementer: `Work in rounds: put a round's lookups in one message, send its independent edits as several Edit calls in one message, and run the tests once per round of edits, never one small call per turn.`,
}
const withRounds = (prompt, opts) => (opts && ROUNDS[opts.agentType] ? `${ROUNDS[opts.agentType]}\n${prompt}` : prompt)
// optional: a step whose failure the caller recovers (the diff-size measurement) is not reported as a dead agent.
const call = async (prompt, opts, optional) => {
  let reply
  try {
    reply = await agent(withRounds(prompt, opts), opts)
  } catch (error) {
    if (!optional) DEAD.push(opts && opts.label)
    throw error
  }
  if (reply == null && !optional) DEAD.push(opts && opts.label)
  return reply
}
const deadOf = () => (DEAD.length ? { dead_agents: DEAD.slice() } : {})

// Shared by the fresh setup and the re-deriving resume of a claim_incomplete cont that lacks its location.
const DERIVE_LOCATION = `Run alone and exactly issue-branch --repo-root ${REPO} --issue ${ISSUE}: it prints one JSON line, and branch and worktree_path are its branch and worktree_path. On a non-zero exit refuse (ok=false) with reason branch and the line it wrote to stderr in details. On any refusal set transient true only when the failed command's stderr JSON has transient true anywhere in it.`
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
// Both lanes' fresh setups renew right after the acquire (#745, #799): an already_held acquire refreshes nothing, and the gate below grades the renew
// whichever the lane. A standard-lane setup also reads the owner's answer to the decision prompt (#745).
const RENEW_STEP = `6. Only when step 5's verdict is already_held (an already_held acquire refreshes nothing), renew the claim: run, alone and exactly, forge-claim renew --repo <slug> --issue ${ISSUE} --holder <host>/${HOLDER_ID} --branch <branch>. It prints one JSON line. ${FORGE_TIMEOUT} Return its verdict (error, with detail, on exit 1 or 2), by, detail and transient (true only when its JSON line has transient true) as renew.
`
const FRESH_READS = `${RENEW_STEP}7. Only when step 5's verdict is acquired or already_held, read the owner's answer to the decision prompt: run alone, exactly, forge-claim owner-action status --repo <slug> --issue ${ISSUE} --reason decision. It prints one JSON line. Change nothing: post nothing, edit nothing, end nothing. Return verdict, comment_id, questions and decisions exactly as printed as answer.
`
const WT_STEP = LANE === 'standard' ? 8 : 7
// #752: a merged PR found only by its head name may be a spec merged from a branch of the same name, so a resume closes out only the PR
// it can name (the number a batch built its cont after merging, or a PR whose own commit list holds a commit of cont.done). Identity is by
// number or commit oid, never by ancestry of base_sha: a squash or rebase merge rewrites every commit but the PR's own list.
const closingPr = refs => {
  const hit = Array.isArray(refs) ? refs.find(r => isEntry(r) && r.closes === true && Number.isInteger(r.number)) : undefined
  return hit ? hit.number : null
}
const OWN_PR = CONT && Number.isInteger(CONT.pr) ? CONT.pr : null
const OWN_COMMITS = CONT && Array.isArray(CONT.done) ? CONT.done.filter(d => isEntry(d) && typeof d.commit === 'string' && d.commit !== '').map(d => d.commit) : []
// A recorded cont.pr decides alone: a reused branch can list one commit on several merged PRs, so commits name the PR only when none is recorded.
const ownMerged = heads => {
  const list = (Array.isArray(heads) ? heads : []).filter(h => isEntry(h) && Number.isInteger(h.number))
  if (OWN_PR !== null) return list.find(h => h.number === OWN_PR)
  return list.find(h => Array.isArray(h.commits) && h.commits.some(c => OWN_COMMITS.some(o => sameSha(c, o))))
}
const OWN_ID = OWN_PR !== null ? `#${OWN_PR}` : `a PR whose commits include one of ${OWN_COMMITS.join(', ')}`
const setupCall = () => call(CONT ? `You re-adopt issue #${ISSUE} of the git repository at ${REPO} for a resumed delivery. Earlier setup: ${JSON.stringify(CONT.setup)}.
1. ${CONTRACT_READ}
2. ${REDERIVE ? `${DERIVE_LOCATION} ` : ''}${OWN_PR !== null || OWN_COMMITS.length ? `List the merged PRs whose head is ${RES_BRANCH} (gh pr list --repo <slug> --state merged --head ${RES_BRANCH} --json number) and, for each, its commits (gh pr view <number> --repo <slug> --json commits); return them as merged_heads, one {number, commits} each with every commit oid. This delivery's own merged PR is the one that is ${OWN_ID}: return ok=true with merged_pr set to that PR's number only for it (the worktree may already be gone). Any other merged PR on that head is not this delivery's: leave merged_pr unset for it.` : 'This delivery has no commit and no PR yet, so look for no merged PR and leave merged_pr and merged_heads unset.'}
3. Otherwise confirm: ${CONT.claim_incomplete ? `the issue is open (an earlier claim stopped part way; the next step finishes it)` : `the issue is open; the worktree ${CONT.setup && CONT.setup.worktree} exists and is on branch ${CONT.setup && CONT.setup.branch}${CONT.plan ? `; the plan directory ${CONT.setup && CONT.setup.plan_dir} exists` : ''}`}. If any fails, return ok=false with reason not-resumable and the evidence. An open PR whose head is that branch is expected and fine. Set dirty true if git -C <worktree> status --porcelain is non-empty. Return head: git -C <worktree> rev-parse HEAD (the full sha).${SINCE_REVIEWED}${BRANCH_READ}
${CONT.claim_incomplete ? `4. After git -C ${REPO} fetch origin: ${EXISTING_READ(RES_BRANCH, RES_PATH)} An earlier worktree step may have created the branch, the worktree or both before it failed, so report existing afresh.
5.` : '4.'} Return every contract field read fresh, ${REDERIVE ? 'with branch and worktree_path as derived' : 'branch as in the earlier setup'}. Change nothing.
${BASE_RULES}` : `You check issue #${ISSUE} of the git repository at ${REPO} before delivery. Change nothing in this step except one issue comment named below, the claim of step 5 and the worktree of step ${WT_STEP}.
1. ${CONTRACT_READ}
2. ${DERIVE_LOCATION} Then gh issue view ${ISSUE} --repo <slug> --json state,labels,title and gh pr list --repo <slug> --state all --search ${ISSUE} --json number,state,headRefName,closingIssuesReferences. Return merged_refs: one {number, closes} per merged PR that list holds, closes true only when its closingIssuesReferences lists issue ${ISSUE}. Refuse (ok=false) with reason closed, parked (label needs-verification or parked), duplicate (a merged PR whose closes is true, a possible duplicate delivery: set duplicate_pr to its number; a merged PR that only mentions or Refs the issue, such as an approved spec merged in its own docs PR, is no duplicate) or open-pr (an open PR referencing this issue whose head is not branch).
3. After git -C ${REPO} fetch origin, re-adopt instead of refusing when the work already exists. ${EXISTING_READ('<branch>', '<worktree_path>')}
4. Read the issue and the code at origin/<integration_branch>: if the issue no longer applies (already fixed or obsolete), comment the evidence on the issue and refuse with reason no-longer-applies. Otherwise return in details, in a few lines, what still applies, where (files and symbols) and what already exists.
5. Only when steps 1 to 4 found no refusal, claim the issue. Run, alone and exactly: forge-claim acquire --repo <slug> --issue ${ISSUE} --holder <host>/${HOLDER_ID} --branch <branch>
It prints one JSON line and adds the in-progress label itself. ${FORGE_TIMEOUT} Return <host>/${HOLDER_ID} as holder, and its verdict (error, with detail, on exit 1 or 2), by, comment_id and transient (true only when its JSON line has transient true) as acquire. When the verdict is neither acquired nor already_held, stop here: run no worktree command and return ok=true with every field above, holder and acquire.
${LANE === 'standard' ? FRESH_READS : RENEW_STEP}${WT_STEP}. Set up the worktree, each command in its own Bash call. An earlier attempt may have done part of this: skip a step already done (the worktree already at <worktree_path> on branch <branch>; the plan directory already there). From the existing you returned: when existing.worktree is true, adopt <worktree_path> as it is and run no worktree command; else when existing.local_branch is true, git -C ${REPO} worktree add <worktree_path> <branch> (adopt the local branch); else when existing.remote_branch is true, git -C ${REPO} worktree add --no-track -b <branch> <worktree_path> origin/<branch> (only the remote branch exists: adopt it); else git -C ${REPO} worktree add --no-track -b <branch> <worktree_path> origin/<integration_branch>. Never reset, clean, restore or stash anything in it. base_sha (full sha) is git -C <worktree_path> merge-base origin/<integration_branch> HEAD for an adopted branch, else the origin/<integration_branch> sha you branched from. plan_dir is <git -C <worktree_path> rev-parse --absolute-git-dir>/deliver-standard; create it. It lives in the worktree's git dir, outside the tree, so the plan never enters a commit.
${WT_STEP + 1}. Return ok=true with branch, worktree_path and every other field above, ${LANE === 'standard' ? 'holder, acquire, renew, answer' : 'holder, acquire, renew'}, and claim: ok, worktree (<worktree_path>), base_sha and plan_dir. A refusal before step 5 returns holder, acquire and claim null. Once the claim step ran, keep ok true: report a worktree failure only as claim with ok=false, the reason and what you already did.
${BASE_RULES}`, { label: 'setup', phase: 'Setup', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'low', schema: CONT ? SETUP_SCHEMA : SETUP_FOLDED })
let setup = await setupCall()
// #870: a refusal marked transient (a forge or network failure) whose reply took no claim is asked once more; the second answer stands.
const claimed = r => !!r.acquire && (r.acquire.verdict === 'acquired' || r.acquire.verdict === 'already_held')
if (setup && setup.ok === false && setup.transient === true && !claimed(setup)) setup = await setupCall()
// #870: a fresh reply of ok true that names neither holder nor acquire left its claim fields out, though it may have claimed: the setup is
// asked once more (the acquire and the worktree step are idempotent); a second such reply stops at the holder gate below. A reply that
// names its holder but no acquire stops at claim with a cont, as before.
else if (!CONT && setup && setup.ok === true && !setup.acquire && !present(setup.holder)) setup = await setupCall()
// A lost reply carries no cont, fresh or resumed: a fresh reply that never showed the refusal checks pass must not resume past them,
// and a rerun redoes the full fresh setup (the acquire is idempotent for the same holder).
if (!setup) return { stage: 'setup', result: null, ...deadOf() }
// The fresh reply's folded claim, read once and removed so setup (and every cont built from it) keeps its old shape.
// A batch child's folded acquire answers already_held, because the batch's own acquire claimed first and is kept since it gates the readopt path;
// that acquire refreshes nothing, so the setup renews (issue 745).
const FOLD_ACQ = !CONT && setup.acquire ? setup.acquire : null
const FOLD_CLAIM = !CONT && setup.claim ? setup.claim : null
const FOLD_HOLDER = !CONT ? setup.holder : undefined
const FOLD_ANSWER = !CONT && setup.answer ? setup.answer : null
const FOLD_RENEW = !CONT && setup.renew ? setup.renew : null
if (!CONT) { delete setup.holder; delete setup.acquire; delete setup.claim; delete setup.answer; delete setup.renew }
const ACQ_RECALL = !CONT && transientError(FOLD_ACQ)
const SETUP_HELD = !!(FOLD_ACQ && FOLD_ACQ.verdict === 'already_held')
const RENEW_RECALL = SETUP_HELD && transientError(FOLD_RENEW)
const CLAIM_TAKEN = !!(FOLD_ACQ && (FOLD_ACQ.verdict === 'acquired' || FOLD_ACQ.verdict === 'already_held'))
// #870: a reply that names the worktree only in its folded claim still has its location; a failed claim, or one never taken, names none.
if (CLAIM_TAKEN && FOLD_CLAIM && FOLD_CLAIM.ok === true && !present(setup.worktree_path) && present(FOLD_CLAIM.worktree)) setup.worktree_path = FOLD_CLAIM.worktree
const BUILT = present(setup.host) ? `${setup.host}/${HOLDER_ID}` : null
// Every stop after the folded claim was taken keeps a cont that finishes it on resume, whatever fields are missing (stop() is not defined yet).
const earlyCont = () => (CLAIM_TAKEN ? { cont: { setup: { ...setup, ...(BUILT && HOLDER_RE.test(BUILT) ? { holder: BUILT } : {}) }, lane: LANE, plan: null, plan_reviewed: false, done: [], fix_waves: 0, claim_incomplete: true } } : {})
// Held by another holder: nothing of ours exists yet, so the stop carries no cont.
if (FOLD_ACQ && (FOLD_ACQ.verdict === 'held_by' || FOLD_ACQ.verdict === 'lost_to')) return { stage: 'claimed', verdict: FOLD_ACQ.verdict, by: FOLD_ACQ.by }
// The folded renew after an already_held acquire (#745) is graded before any other setup exit, so a setup failure cannot mask a lost renewal.
// A transient one is left to the owner-answer step, which renews again. Defined before stop(): a stop here carries earlyCont's cont.
const CLAIM_ENDED = 'the claim was ended (released, or honoured as stale by the owner); start again without cont: setup re-adopts the branch and acquire decides'
if (SETUP_HELD && !RENEW_RECALL && !(FOLD_RENEW && FOLD_RENEW.verdict === 'renewed')) {
  return FOLD_RENEW && FOLD_RENEW.verdict === 'not_held'
    ? { stage: 'claim-lost', at: 'plan', renew: FOLD_RENEW, details: CLAIM_ENDED }
    : { stage: 'claim-lost', at: 'plan', renew: FOLD_RENEW, ...deadOf(), ...earlyCont() }
}
if (!setup.ok) return { stage: 'setup', result: setup, ...deadOf(), ...earlyCont() }
// A fresh run never closes out a merged PR: it is a possible duplicate delivery, for the owner to judge.
const DUP = !CONT ? closingPr(setup.merged_refs) : null
if (DUP) return { stage: 'setup', result: setup, duplicate: DUP, ...deadOf(), ...earlyCont() }
// #752: a resume closes out only a merged PR it can name; a reported merged_pr the facts do not confirm stops before any claim or task.
if (CONT) {
  const own = ownMerged(setup.merged_heads)
  if (present(setup.merged_pr) && !(own && own.number === setup.merged_pr)) return { stage: 'setup', result: setup, invalid: 'merged_pr', ...deadOf(), cont: CONT }
  if (own) setup.merged_pr = own.number
}
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
// #993: the program's own finding on a criterion that only restates the declared verification; no rule of the standard, settled like one.
const VERIFY_RULE = 'verify'
// A rules-only revise may settle the findings left when each names a rule and none has source codex, whatever triggered the full
// revise. #823 dropped the PR 718 clause (b7a7a921) that also refused it to every Codex-triggered plan: Codex raises a finding on
// nearly every plan, so the revise never ran, while the findings left were the rules re-reviewer's own.
const rulesOnly = rules => rules.length > 0 && rules.every(f => (RULE_IDS.includes(f.rule) || f.rule === VERIFY_RULE) && f.source !== 'codex')
// The Plan section below drops a kept plan with an invalid declaration, and one a plan-review stop kept with findings no rules-only
// revise may settle; no fact of such a plan is demanded here, or a vanished worktree would stop every resume before the replan.
const keptDropped = !!(CONT && CONT.plan && !CONT.plan_reviewed && CONT.plan_findings && Array.isArray(CONT.plan_findings.rules)
  && !rulesOnly(CONT.plan_findings.rules))
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
let planFindingsKept = KEPT ? { rules: KEPT.rules, findings: Array.isArray(KEPT.findings) ? KEPT.findings : [], rounds: Number.isInteger(KEPT.rounds) ? KEPT.rounds : 0, ...(Array.isArray(KEPT.noted) && KEPT.noted.length ? { noted: KEPT.noted } : {}) } : null
const taskLog = CONT && CONT.done ? CONT.done.slice() : []
let claimIncomplete = !!(CONT && CONT.claim_incomplete) || CLAIM_TAKEN
// A partial task's edits stay claimed through any stop until that task is done.
let partial = CONT && CONT.partial !== undefined ? CONT.partial : undefined
// #896: the blocked tasks this delivery moved behind the later task each named, one move per task; dropped with the plan they reorder.
let reordered = CONT && Array.isArray(CONT.reordered) ? CONT.reordered.filter(r => r && Number.isInteger(r.task) && Number.isInteger(r.after)) : []
// Fix waves already spent, carried through a resume; declared before stop() because early failures call it.
let fixWaves = (CONT && CONT.fix_waves) || 0
// #924: the findings a fix-wave-review stop left open, kept in cont.fix_findings until a resume's first fix wave has taken them.
// Bounded on the way out and on the way in (at most CARRY_MAX findings, each text capped), so a cont cannot grow from stop to stop.
const CARRY_MAX = 10
const clip = v => (v.length > REASON_MAX ? `${v.slice(0, REASON_MAX - 3)}...` : v)
const carryOf = list => (Array.isArray(list) ? list : []).filter(f => isEntry(f) && typeof f.summary === 'string' && f.summary.trim() && f.severity !== 'minor').slice(0, CARRY_MAX)
  .map(f => ({ severity: f.severity === 'critical' ? 'critical' : 'important', ...(typeof f.file === 'string' && f.file ? { file: clip(f.file) } : {}), summary: clip(f.summary), ...(typeof f.failing_input === 'string' && f.failing_input ? { failing_input: clip(f.failing_input) } : {}) }))
const findingKey = f => `${typeof f.file === 'string' ? f.file : ''}\n${clip(String(f.summary)).toLowerCase().replace(/\s+/g, ' ').trim()}`
let carried = carryOf(CONT && CONT.fix_findings)
// #988: the blocking findings left on a plan this delivery dropped after its review (a second failed rules revise, a kept plan no rules
// revise may settle, a revise that came back as questions or not well formed). Kept in cont.prior_findings through every stop until a
// plan passes review, newest first and bounded as the fix findings are, so the next planner does not rediscover them.
const PRIOR_MAX = 20
const priorOf = list => {
  const seen = new Set()
  return (Array.isArray(list) ? list : []).filter(f => isEntry(f) && typeof f.summary === 'string' && f.summary.trim() && f.severity !== 'minor')
    .map(f => ({ severity: f.severity === 'critical' ? 'critical' : 'important', ...Object.fromEntries(['rule', 'ac', 'source', 'file'].filter(k => typeof f[k] === 'string' && f[k]).map(k => [k, clip(f[k])])), summary: clip(f.summary) }))
    .filter(f => { const k = JSON.stringify(f); return seen.has(k) ? false : !!seen.add(k) }).slice(0, PRIOR_MAX)
}
let priorFindings = priorOf(CONT && CONT.prior_findings)
// Every drop of a plan goes through here: left is what its review found when no plan-review stop has kept it yet.
const dropPlan = (left = []) => {
  priorFindings = priorOf(left.concat(planFindingsKept ? planFindingsKept.rules.concat(planFindingsKept.findings) : [], priorFindings))
  plan = null
  planFindingsKept = null
}
const CARRIED_AT_START = carried
// #940: fix waves that do not converge. A fix-wave-review stop that leaves findings open once the waves spent across runs (cont.fix_waves
// and this run's) have reached FIX_WAVES_BOUND, with a finding left in a file the findings carried into this run already named, is marked
// diverging: { file, waves }: more waves on that file are not expected to close it, so the owner decides the design. A first run carries no
// findings in, so it is never marked; neither is a resume whose open findings are all in other files.
const FIX_WAVES_BOUND = 4
// Reviewers name one file as path, ./path, an absolute path under the worktree, path:line, path:line-line, path:line:column or path#L<line>
// (#L<line>-L<line> too): files are compared, and the marker names the file, as the path relative to the worktree without the surrounding
// whitespace, a leading ./ and that trailing position; nothing else is folded, case included.
const fileOf = f => {
  if (typeof f.file !== 'string') return ''
  let p = f.file.trim().replace(/#L\d+(?:-L?\d+)?$/, '').replace(/:\d+(?:[-:]\d+)?$/, '').trim()
  const roots = [setup && setup.worktree, setup && setup.worktree_path].filter(r => typeof r === 'string' && r.startsWith('/')).map(r => r.replace(/\/+$/, ''))
  for (const r of roots) if (r && p.startsWith(`${r}/`)) { p = p.slice(r.length + 1); break }
  return p.replace(/^(?:\.\/)+/, '').trim()
}
// #950: the files a fix wave's commits changed, for admitting a new finding in one of them to the next wave. The program reads no
// repository, so the list is the output of one command it words itself over the range it holds (git diff --no-renames --name-only
// <start_head>..<commit> in the issue worktree, a rename listing both paths), asked of the two steps that already read that range: the
// wave's implementer and its re-reviewer. A file counts only when both list it, so neither one's word admits a wave alone; a missing
// list, an idle wave and a commit on a declared branch count nothing. A wrong list can only earn a wave that MAX_WAVES bounds and a
// re-review follows; it clears no finding.
const CHANGED_CMD = range => `git -C ${W} diff --no-renames --name-only ${range}`
const changedBy = r => (r && Array.isArray(r.changed_files) ? r.changed_files : []).map(file => fileOf({ file })).filter(Boolean)
const divergingOf = left => {
  if (fixWaves < FIX_WAVES_BOUND) return null
  const hit = left.map(fileOf).find(f => f && CARRIED_AT_START.map(fileOf).includes(f))
  return hit ? { file: hit, waves: fixWaves } : null
}
// The head the final review and its fix waves passed at ({ head, accepted? }), carried so a resume on it skips the review.
let finalReviewed = (CONT && CONT.final_reviewed) || null
// The stages between a sync merge and its acceptance: a stop there must not carry a marker over the unreviewed merge.
const SYNC_WINDOW = ['sync', 'sync-review', 'sync-fix']
// Ship fix waves already spent (a red check, a sync-review finding): one each per delivery, carried through a resume.
let checksFixes = (CONT && CONT.checks_fixes) || 0
let syncFixes = (CONT && CONT.sync_fixes) || 0
// The verified head, results and verification contract of a ready stop; carried until a resume finds the head moved; its results are reused only under the same contract.
let verified = (CONT && CONT.verified) || null
// #972: the files outside the branch's diff a verification fix edited, each with the cause the fix step established. Carried in cont on its
// own, not with the verified head: the edit stays on the branch when a resume finds the head moved, so the flag stays too.
const outsideOf = xs => (Array.isArray(xs) ? xs : []).filter(x => isEntry(x) && present(x.file) && present(x.why)).map(x => ({ file: String(x.file), why: String(x.why).slice(0, REASON_MAX) }))
const outsideFixes = outsideOf(CONT && CONT.outside_fixes)
// The owner's binding decisions: distinct non-empty strings, from args, from cont and from the decision prompt read after the claim.
let decisions = []
const addDecision = text => { if (typeof text === 'string' && text.trim() && !decisions.includes(text)) decisions.push(text) }
if (CONT && Array.isArray(CONT.decisions)) CONT.decisions.forEach(addDecision)
if (!RERUN_WORD) addDecision(args.decisions)
// True once plan-amend applied the amend: every later stop says so, so deliver-batch stops sending an amend that no longer needs to be (#811).
let amendApplied = false
// #996: the blocked task a stop carries, until an amend, a revise or a decision-bearing implementer call has answered it; and whether the
// decision that settles it is still unused: a stop before it was used leaves it out of cont.decisions, so the same resume counts it as new again.
let blocked = RERUN ? null : BLOCKED
let decisionPending = newDecision !== null
const keptDecisions = () => (decisionPending ? decisions.filter(d => d !== newDecision) : decisions)
const blockedKept = () => !!blocked && (LANE === 'direct' || !!plan) && !taskLog.some(d => d.n === blocked.task)
const stop = (stage, extra) => {
  const fr = SYNC_WINDOW.includes(stage) ? (finalReviewed = null) : finalReviewed
  return { stage, ...extra, ...(stage === 'planned' || stage === 'ready' ? {} : { reason: stopReason(stage, extra || {}) }), ...(amendApplied ? { amended: true } : {}), ...deadOf(), cont: { setup, lane: LANE, plan, plan_reviewed: planReviewed, ...(plan && !planReviewed && planFindingsKept ? { plan_findings: planFindingsKept } : {}), ...(!planReviewed && priorFindings.length ? { prior_findings: priorFindings } : {}), ...(keptDecisions().length ? { decisions: keptDecisions() } : {}), done: taskLog, ...(OWN_PR !== null ? { pr: OWN_PR } : {}), fix_waves: fixWaves, ...(carried.length ? { fix_findings: carried } : {}), ...(checksFixes ? { checks_fixes: checksFixes } : {}), ...(syncFixes ? { sync_fixes: syncFixes } : {}), ...(verified ? { verified } : {}), ...(outsideFixes.length ? { outside_fixes: outsideFixes } : {}), ...(fr ? { final_reviewed: fr } : {}), ...(claimIncomplete ? { claim_incomplete: true } : {}), ...(partial !== undefined ? { partial } : {}), ...(blockedKept() ? { blocked } : {}), ...(reordered.length ? { reordered } : {}) } }
}

const haltTask = (n, stage, extra) => { const s = stop(stage, extra); return { ...s, cont: { ...s.cont, partial: n } } }
// #996: a task stop on an implementer that returned blocked keeps its notes in the cont and names the ways out in its reason.
const haltImpl = (n, extra) => {
  const said = isEntry(extra.impl) && extra.impl.status === 'blocked'
  if (said) blocked = { task: n, notes: typeof extra.impl.notes === 'string' ? extra.impl.notes.slice(0, NOTES_MAX) : '' }
  return haltTask(n, 'task', said ? { ...extra, ways: WAYS_OUT } : extra)
}

if (CONT && setup.dirty && !setup.merged_pr && partial === undefined) {
  return stop('dirty', { details: `the worktree ${setup.worktree} has uncommitted changes no task claims; commit or discard them, then resume` })
}

const SLUG = setup.slug, INT = setup.integration_branch, STRATEGY = setup.merge_strategy
// The land lock command, its return sentence and the conditional second release, one line each, byte for byte the same as deliver-batch.js (#716).
const LAND_ACQUIRE = (sha, wait) => `forge-claim land acquire --repo ${SLUG} --branch ${INT} --sha ${sha}${wait ? ' --wait' : ''}`
const LOCK_RETURN = `Return its verdict (acquired, already_held, moved, land-contended, held_by, lost_to, or error on any other exit), lock_sha, by, detail, waited_s and waited_on from its output. ${FORGE_TIMEOUT}`
const RELEASE_AGAIN = maybe => `When it prints not_held with lock_sha ${maybe}, run alone and exactly: forge-claim land release --repo ${SLUG} --branch ${INT} --sha ${maybe}, then return the verdict of that second release.\n`
const RELEASE_FIRST = (sha, maybe) => `First, before anything below, release the cross-host landing lock of the branch ${INT}: run alone and exactly: forge-claim land release --repo ${SLUG} --branch ${INT} --sha ${sha}
released and not_held are both fine. ${FORGE_TIMEOUT} Return its verdict and any detail as release.
${maybe ? RELEASE_AGAIN(maybe) : ''}Then, whatever its verdict, go on with the steps below.
`
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
const RELEASE_SCHEMA = { type: 'object', properties: { verdict: { type: 'string' }, detail: { type: 'string' } }, required: ['verdict'] }
const HOLD_SCHEMA = { type: 'object', properties: {
  merge_commit_local: { type: 'boolean' }, code_unmet: STRS, blocks: { type: 'array', items: { type: 'integer' } },
  split: { type: 'array', items: { type: 'object', properties: { ac: { type: 'string' }, issue: { type: 'integer' }, block: { type: 'object' }, lint: LINT_V, verify_run: RUN_V, issue_state: { type: 'string' } }, required: ['ac', 'issue', 'lint', 'verify_run', 'issue_state'] } },
  block: { type: 'object' }, lint: LINT_V, verify_run: RUN_V, issue_state: { type: 'string' }, already_closed: { type: 'boolean' }, notes: { type: 'string' } },
  required: ['merge_commit_local', 'code_unmet', 'issue_state', 'notes'] }
const STATES = ['OPEN', 'CLOSED']

// The criterion ids no check of the block names: a hold must cover every criterion it leaves open, or the issue would close on a partial check.
const covers = (checks, ids) => ids.filter(id => !checks.some(c => c && c.ac === id))

// The folded release reply of this run's hold call, or null (#801).
let landRelease = null
const closeOut = async (PR, mergeCommit, W, prHead, lock = null) => {
  const acceptance = plan ? plan.acceptance : null
  if (!acceptance) return stop('close-out', { pr: PR, details: 'merged, but no plan acceptance to grade the issue against; close out by hand' })
  const unknown = badKinds(acceptance)
  if (unknown.length) return stop('close-out', { pr: PR, details: 'merged, but a plan criterion has a kind that is not code, evidence, human or note; close out by hand', bad_kinds: unknown })
  const noHold = !acceptance.some(isOpen)
  const openCriteria = acceptance.filter(isOpen)
  const notes = acceptance.filter(a => a && a.kind === 'note')
  // Ship regrades the code rows for every plan; a plan with a non-code row is then held by the acceptance-planning rules' "Linting a hold" procedure.
  const merged = mergeCommit ? mergeCommit : `read from gh pr view ${PR} --repo ${SLUG} --json mergeCommit,headRefOid`
  // A PR merged indirectly (its head reached the integration branch through another PR's merge) is MERGED with a null mergeCommit.
  const indirect = mergeCommit ? '' : ` When that mergeCommit is null, read gh pr view ${PR} --repo ${SLUG} --json state: only when it is MERGED (the PR was merged indirectly: its head reached ${INT} through another PR's merge), confirm git -C ${REPO} merge-base --is-ancestor <headRefOid> origin/${INT} succeeds, then run git -C ${REPO} rev-list --first-parent <headRefOid>..origin/${INT} (the first-parent line of origin/${INT}, newest first) and git -C ${REPO} rev-list --ancestry-path <headRefOid>..origin/${INT} (the commits that contain the head): the merge commit is the last commit of the first list that is also in the second (the first commit on the first-parent line that contains the head); when the first list is empty, the tip of origin/${INT} is the head itself and the merge commit is <headRefOid>. When the state is not MERGED or the head is not an ancestor, return merge_commit_local false and stop here.`
  const heldBlock = noHold ? '' : `
4. Read the issues this one blocks: gh api repos/${SLUG}/issues/${ISSUE}/dependencies/blocking (their numbers, returned as blocks).
5. When blocks is non-empty, move each human criterion into its own new issue that blocks no other issue (forge-issue create --repo ${SLUG}, its body naming #${ISSUE}), hold that issue by step 6 with only that criterion's check (no --blocks flag; its once-run uses --issue <child>), and return one split entry per moved criterion with its issue, block, lint, verify_run and issue_state.
6. For the criteria left (evidence or human, not split): none left means close #${ISSUE} with a comment naming the evidence and the split issues. Otherwise assemble one hold comment: a line per criterion, then exactly one \`\`\`verify fence holding {"v": 1, "merge": <the merge commit>, "checks": [...]} built from each criterion's verify member with every occurrence of the base sha ${setup.base_sha} replaced by the merge commit (a criterion without a verify member gets one written per ~/.agents/standards/acceptance-planning.md; an unattended evidence command run must be one of ${JSON.stringify(VERIFY_IDS)}, else use a script or a probe). Write it to a file outside any work tree and run verify-pending lint --input <file> --repo-root ${REPO} --pr-head ${prHead || '<the headRefOid read in step 1>'} --pr-branch ${setup.branch} plus one --pr-workflow <name> per distinct workflow of gh pr checks ${PR} --repo ${SLUG} --json workflow and one --blocks <n> per blocked issue. On refusal post nothing and return its verdict as lint. Otherwise, when no hold comment with a verify fence exists yet, gh issue comment ${ISSUE} --repo ${SLUG} --body-file <file> (when one exists, post nothing: write its fence JSON to the file and lint that, so lint is still returned), add the needs-verification label (create it if missing), then run alone, once, even when an earlier attempt ran it: verify-pending run --host ${setup.host} --repo ${SLUG} --issue ${ISSUE}. Return block (the posted JSON), lint, verify_run (ran, exit) and issue_state read back from the tracker.`
  const held = await call(`Issue #${ISSUE} of ${SLUG}: PR #${PR} is merged into ${INT}. Hold the issue's acceptance after the merge, by ~/.agents/standards/acceptance-planning.md (its "Linting a hold" section is the procedure). Skip the posting steps an earlier attempt already finished (an existing hold comment with a verify fence, the label, a split issue already filed and held for that criterion), but never skip the evidence you return: lint and verify_run are always fresh results of this attempt, so on such a retry take block from the posted verify fence, lint that block, run the once-run, and return all three. Each command in its own Bash call:
${lock ? RELEASE_FIRST(lock.sha, lock.maybe) : ''}1. Run git -C ${REPO} fetch origin. Merge commit: ${merged}${mergeCommit ? '' : ' (and read headRefOid, the PR head)'}.${indirect} Confirm git -C ${REPO} cat-file -e <merge commit>^{commit} succeeds and return the result as merge_commit_local; if it fails, stop here. Criteria: ${JSON.stringify(acceptance)}
2. Regrade each code criterion once against the merge commit and the PR's passed required checks; a note criterion is the orchestrator's own observation and is never regraded, held or checked. Return the unmet ids as code_unmet and, if any, stop here: post nothing and add no label.
3. ${noHold ? 'Every criterion is of kind code or note: post nothing, add no label; return issue_state read from the tracker.' : 'Some criteria are of kind evidence or human. Read gh issue view ' + ISSUE + ' --repo ' + SLUG + ' --json state. When it already shows CLOSED before this attempt posts or runs anything, return already_closed true and issue_state CLOSED, post nothing, add no label and run no verify-pending command for #' + ISSUE + ' itself (step 6 is skipped); steps 4 and 5 still apply, so a split issue an earlier attempt filed is recovered and returned with its lint and a fresh once-run. Otherwise return already_closed false and continue with steps 4 to 6.'}${heldBlock}
${RULES_FOR(W || '<worktree>')}`, { label: 'hold', phase: 'Ship', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'high', schema: lock ? { ...HOLD_SCHEMA, properties: { ...HOLD_SCHEMA.properties, release: NULLABLE(RELEASE_SCHEMA) } } : HOLD_SCHEMA })
  if (lock) landRelease = held ? (held.release ?? null) : null
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
${RULES_FOR(W || '<worktree>')}`, { label: 'close-out', phase: 'Ship', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'low', schema: { type: 'object', properties: { issue_state: { type: 'string' }, branch_deleted: { type: 'boolean' }, released: { type: 'boolean' }, decision_ended: { type: 'boolean' }, notes_posted: { type: 'boolean' }, notes: { type: 'string' } }, required: ['issue_state', 'notes'] } })
  const want = noHold ? 'CLOSED' : held.issue_state
  if (!co || co.issue_state !== want || co.decision_ended !== true || co.released !== true || (notes.length && co.notes_posted !== true)) return stop('close-out', { pr: PR, close_out: co, expected_issue_state: want })
  return { stage: 'done', pr: PR, merged: true, merge_commit: mergeCommit, close_out: co, hold: held, tasks: taskLog, ...(reordered.length ? { reordered } : {}), acceptance, fix_waves: fixWaves }
}

if (CONT && setup.merged_pr) {
  phase('Ship')
  log(`PR #${setup.merged_pr} is already merged; closing out`)
  return await closeOut(setup.merged_pr, null, setup.worktree, null)
}

const RS = setup.review_state || {}
for (const k of ['plan', 'code']) {
  // Before any claim nothing is held, so the stop carries no cont: fix the capability and start again.
  if (RS[k] === 'blocked') return CONT || CLAIM_TAKEN ? stop('review-blocked', { review: k }) : why({ stage: 'review-blocked', review: k })
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
${RULES_FOR(setup.worktree_path)}`, { label: 'acquire', phase: 'Setup', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: ACQUIRE_SCHEMA })
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
${RULES_FOR(setup.worktree_path)}`, { label: 'worktree', phase: 'Setup', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'low', schema: CLAIM_SCHEMA })
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
  if (r && r.verdict === 'not_held') return { stage: 'claim-lost', at, renew: r, details: CLAIM_ENDED }
  claimIncomplete = true
  return stop('claim-lost', { at, renew: r })
}
// Renews the claim before the step it guards. null = renewed; else the stop to return.
const renew = async (at, ph) => renewed(await recall(() => call(`Renew the claim on issue #${ISSUE} of ${SLUG}. Run, alone and exactly: forge-claim renew --repo ${SLUG} --issue ${ISSUE} --holder ${setup.holder} --branch ${setup.branch}
It prints one JSON line. ${FORGE_TIMEOUT} Return its verdict (error, with detail, on exit 1 or 2), by, detail and transient (true only when its JSON line has transient true). Run nothing else and change nothing.
${RULES}`, { label: `renew-${at}`, phase: ph, agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: RENEW_SCHEMA })), at)
const RANGE = `origin/${INT}...HEAD`
const CTX = `Issue #${ISSUE} of ${SLUG}. Worktree: ${W} (branch ${setup.branch}, base ${setup.base_sha}, integration branch ${INT}). The branch's changes are git -C ${W} diff ${RANGE} (fetch origin first).`
const K = setup.knowledge || {}
const list = a => (a && a.length ? a.join(', ') : 'none')
const KNOW = `Ground the review in: ~/.agents/standards/the-bar.md and its stacks/ shards matching the changed file types (when present); the project's standards (${list(K.standards)}), only shards whose globs intersect the change; review hints (${list(K.hints)}); recorded rejections (${list(K.rejections)}): never raise a finding a rejection already settles.`
const spanIn = (wt, i) => `git -C ${wt} diff ${i.start_head}..${i.commit}`
const span = i => spanIn(W, i)
log(`claimed #${ISSUE}, worktree ${W}; review code=${REVIEW_CODE || RS.code || 'none'} plan=${REVIEW_PLAN || RS.plan || 'none'}`)

// ---------------- Plan ----------------
const PLAN_SCHEMA = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['planned', 'needs_user'] },
    questions: { type: 'array', items: { type: 'object', properties: { question: { type: 'string' }, options: STRS, recommended: { type: 'string' } }, required: ['question', 'options'] } },
    plan_root: { type: 'string' },
    acceptance: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, text: { type: 'string' }, kind: { type: 'string', enum: ['code', 'evidence', 'human', 'note'] }, verify: { type: 'object' }, lint: { type: 'object', properties: { ok: { type: 'boolean' }, errors: { type: 'array', items: { type: 'object', properties: { field: { type: 'string' }, code: { type: 'string' }, message: { type: 'string' } } } } } }, metric: { type: 'boolean' } }, required: ['id', 'text', 'kind'] } },
    scripts: STRS,
    // #819: on a revise, the ids of the criteria whose wording the planner changed; never kept in the plan.
    criteria_edited: STRS,
    tasks: { type: 'array', items: { type: 'object', properties: { n: { type: 'integer' }, title: { type: 'string' }, file: { type: 'string' }, risk: { type: 'string', enum: ['mechanical', 'low', 'standard', 'security'] }, branch: { type: 'string' } }, required: ['n', 'title', 'file', 'risk'] } },
    branches: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, worktree: { type: 'string' }, base: { type: 'string' }, head: FULL_SHA, current: { type: 'string' }, toplevel: { type: 'string' }, common_dir: { type: 'string' }, clean: { type: 'boolean' } }, required: ['name', 'worktree', 'base', 'head', 'current', 'toplevel', 'common_dir', 'clean'] } },
  },
  required: ['status'],
}
const wellFormed = p => !!(p && p.status === 'planned' && present(p.plan_root) && Array.isArray(p.acceptance) && p.acceptance.length && Array.isArray(p.tasks) && p.tasks.length)
const HUMAN_REASONS = ['senses', 'hands', 'credentials', 'money', 'taste']
const RULE_OF = { pre_merge_only: 'R1', approval_ask: 'R2', reason_required: 'R3' }
// #988: every message names each way out the rules allow, so a planner that follows it is not led into another rule's violation
// (a message that named only the evidence check turned a locally enforced cap into a post-merge hold, an R1 violation).
const HUMAN_FIX = `name the one of ${HUMAN_REASONS.join(', ')} that applies, or, when none does, make the criterion code or evidence`
const CODE_FIX = `make it a code criterion when a test, CI or a local evaluation shows it before merge (R1)`
const LINT_FIX = {
  pre_merge_only: `: make it a code criterion, graded at ship, or, when only a deploy or a later observation shows it, trigger the check on that`,
  approval_ask: `: the approval is given on the pull request, so drop the post-merge ask; keep a human check only for what a person must sense or do after the merge (R3)`,
  reason_required: `: ${HUMAN_FIX}`,
}
// #993: a code criterion whose every word is a declared verification id, a word of its argv or filler names no test of its own: the
// verify step already runs and proves it, and reviewers asked to show it ran the whole suite again. Anything else is left to review.
const VERIFY_NAMES = setup.verification.flatMap(e => [e.id].concat(Array.isArray(e.argv) ? e.argv : [])).filter(v => typeof v === 'string' && v).map(v => v.toLowerCase())
const VERIFY_FILLER = ['a', 'all', 'and', 'are', 'at', 'both', 'branch', 'check', 'checks', 'clean', 'command', 'commands', 'declared', 'exit', 'exits', 'green', 'head', 'in', 'is', 'of', 'on', 'or', 'pass', 'passes', 'passing', 'run', 'runs', 'still', 'succeed', 'succeeds', 'suite', 'the', 'tip', 'verification', 'with', 'zero', '0']
const restatesVerify = text => {
  const words = (typeof text === 'string' ? text : '').toLowerCase().split(/[^a-z0-9:_./-]+/).map(w => w.replace(/^[.:/-]+|[.:/-]+$/g, '')).filter(w => w !== '')
  return words.some(w => VERIFY_NAMES.includes(w)) && words.every(w => VERIFY_NAMES.includes(w) || VERIFY_FILLER.includes(w))
}
// The program-checkable violations of the acceptance planning rules (R1 to R5, and R9); the rules file is the source, never copied here.
const planRules = p => {
  const out = []
  const scripts = Array.isArray(p.scripts) ? p.scripts : []
  // #993: dropping is the fix, and a plan with no criterion is not well formed: when every criterion restates the verification
  // none is refused, or the revise would empty the plan, drop it and the relaunch would plan the same thing again.
  const restates = a => a.kind === 'code' && restatesVerify(a.text)
  const droppable = p.acceptance.some(a => !restates(a))
  for (const a of p.acceptance) {
    const hit = (rule, why) => out.push({ severity: 'important', rule, ac: a.id, summary: `${rule} (${a.id}): ${why}` })
    const v = a.verify
    if (restates(a) && droppable) hit(VERIFY_RULE, `the criterion only restates the declared verification, which the verify step runs and proves: drop the criterion`)
    if (a.metric === true && !(a.kind === 'evidence' && v && typeof v === 'object' && v.mode === 'observe')) hit('R5', a.kind === 'note'
      ? `a note carries no metric: drop metric (R9), or, when no decision makes the reading the orchestrator's own, make it an evidence check with mode observe`
      : `metric is set on a criterion that is not an evidence check with mode observe: make it one when only a deploy or observation over time shows the threshold, or drop metric and ${CODE_FIX}`)
    if (a.kind === 'note') {
      if (a.verify != null || a.script != null) hit('R9', `a note carries no verify block and no script: drop them, or, when no decision makes the reading the orchestrator's own observation, make the criterion evidence (R4) or, if a test shows it before merge, code (R1)`)
      continue
    }
    if (a.kind !== 'evidence' && a.kind !== 'human') continue
    if (!v || typeof v !== 'object') { hit('R4', `no verify block: add one, or ${CODE_FIX}`); continue }
    if (v.ac !== a.id || v.kind !== a.kind) { hit('R4', `the verify block names another criterion or kind: set its ac and kind to this criterion's`); continue }
    if (a.kind === 'human' && !HUMAN_REASONS.includes(v.reason)) hit('R3', `the human reason is not one of the listed reasons: ${HUMAN_FIX}`)
    if (commandOutside(v)) hit('R4', `the unattended command is not a declared verification id and can never complete: use ${VERIFY_IDS.length ? `one of ${JSON.stringify(VERIFY_IDS)}, ` : ''}a committed script or a probe, or ${CODE_FIX}`)
    const l = a.lint
    if (!l || typeof l !== 'object' || typeof l.ok !== 'boolean') { hit('R4', 'the verify block was not linted'); continue }
    if (l.ok) continue
    const errors = Array.isArray(l.errors) ? l.errors : []
    if (!errors.length) { hit('R4', 'the lint refused with no error'); continue }
    const script = v.run && typeof v.run === 'object' ? (typeof v.run.script === 'string' ? v.run.script : (v.run.then && typeof v.run.then.script === 'string' ? v.run.then.script : null)) : null
    for (const e of errors) {
      if (e.code === 'not_committed' && typeof e.field === 'string' && e.field.endsWith('.script') && script !== null && scripts.includes(script)) continue
      hit(RULE_OF[e.code] || 'R4', `lint ${e.code} at ${e.field}: ${e.message}${LINT_FIX[e.code] || ''}`)
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
// #747: the narrowed Claude plan review when the Codex plan review runs; the acceptance-planning clause stays the shared one in the prompt, and the Codex sentence is a separate suffix after it.
const PLAN_RUBRIC_SIZED = `an acceptance criterion with no task, a design choice that breaks the project's documented conventions, standards or docs (name the document it breaks), a project-specific literal written into global skills or agents, or an internal inconsistency (a task, interface, file or decision that the plan root or another task contradicts, or that no task defines)`
const PLAN_CODEX_OWNS = `The Codex plan review running beside you owns code correctness (whether a task's code, tests and interfaces will work): do not sweep for it.`
// #819: the planner's own half of that check, the finding classes a planner can settle itself; never part of the reviewer's rubric.
const PLAN_SELF_CHECK = `Also before you return: run every grep or deny gate a task prescribes against the text this plan requires and confirm it does not reject that text; for each invariant, threshold and decision a task states, name the test case that fails when that one rule is removed; one with no such case needs a test; and list for each new test or doc the CI workflow test list, the generated index and the project gate that must also change.`
// The plan step's turn structure (#737, #819), first in the prompt: at least four lookups a message and writing by the twelfth, then one message of writes.
// #967: the review-findings revise gets its own pace instead (one message that checks every finding, at most two more), never both.
// No subagent grant: the Agent tool does not exist inside a workflow agent.
const PLAN_PACE = `send at least four lookups in each exploration message and start writing by your twelfth message`
const REVISE_PACE = `check every finding's claim in the first lookup message after the load below, one call per finding, and send at most two follow-up lookup messages before editing`
const PLAN_LOOKUPS = pace => `Procedure for this step. Look things up in rounds: put every open question's Bash or Read call in the same message as the others (several tool calls per message, never one small lookup per turn), ${pace}. No subagent can be dispatched: the Agent tool does not exist in this step. Check against the tree yourself every path and symbol you write into a task.`
const PLAN_WRITES = `Then write the code map, plan.md and every task file as parallel Write calls in one message (a second message only if the output limit forces it), then run any checks in one message.`
// #967: parallel Read calls, since one cat of the plan directory overflows the Bash output cap.
const PLAN_EDITS = `This is a revision: first list ${setup.plan_dir}/*.md and load them all as parallel Read calls in one message, then fix the findings with Edit in place, the independent Edit calls in one message; rewrite a whole file only when most of it changes; leave each acceptance criterion's text unchanged unless fixing a finding requires changing it. Then run any checks in one message.`
const FACTS = present(setup.details) ? `\nSetup facts: ${setup.details}` : ''
const KIND_GUIDE = `kind code if a test or command in this repo can show it, evidence if it needs a deploy, an activation or observation over time, human if only the user can judge, note if a decision makes a post-deploy reading the orchestrator's own observation or not a hold (no verify member, no script and no metric, R9 of ~/.agents/standards/acceptance-planning.md)`
// #746 trial: only this plan step asks for test cases; writing-plans keeps full test code for its other callers until the trial reports.
const TEST_CASES = `Task files of this plan step state each failing test as a case, not as code: its name, the arrange, the act, the exact assertion and the expected failure. This replaces writing-plans' "Write failing tests out in full." here; full test code stays only under its carve-out, where prose cannot preserve a decision (an exact wire format). The implementer writes the test code from the case.`
const planPrompt = (extra, pace = PLAN_PACE) => `${PLAN_LOOKUPS(pace)} ${extra ? PLAN_EDITS : PLAN_WRITES}
${CTX}
${TEST_CASES}
Plan this issue. Read the issue (gh issue view ${ISSUE} --repo ${SLUG} --json title,body,comments) and the code it touches.${SPEC}${FACTS} Use the writing-plans skill for the plan's form only: its file location, size checks and reports do not apply here. Write the plan to ${setup.plan_dir}/plan.md and one task file per task beside it (${setup.plan_dir}/task-<n>.md); never commit them and never write under the project's artifact directories. Also write the code map ${CODE_MAP} for the agents after you, who read it before the code: per area the plan touches, list the files and symbols with line ranges, their tests and fixtures, the callers that matter and the facts you confirmed (for example a library's behaviour, with its source), each with a pointer (a path:line or a URL). Like the plan, it is never committed. On a revision, read it first and keep it true to the plan and the code. Do not build, prototype or run the change; confirming each task's failing test later is the implementers' job. If the issue needs a decision only the user can make (a preference, an irreversible or scope choice not settled by the issue, the spec, the repo's docs or ADRs), return status needs_user, never for an action that R8 of ~/.agents/standards/acceptance-planning.md says the delivery does itself, with questions, each {question, options}: every option one full sentence naming a real choice, a single option for a yes or no, and, when you would choose one option, recommended: its exact text; then stop. Otherwise return status planned with plan_root ${setup.plan_dir}/plan.md, the issue's acceptance criteria (${KIND_GUIDE}) and the task list in execution order with each task's file and a risk: security for authentication, permission or command guards, secrets, CI/CD or deploy config, data migrations; mechanical or low for small contained edits; else standard. When a task commits to a branch other than ${setup.branch}, declare it in branches as {name, worktree, base, head, current, toplevel, common_dir, clean}: only a branch already checked out in its own existing worktree other than ${W}, never ${INT} or ${setup.default_branch}; worktree as git -C <it> rev-parse --show-toplevel prints it, base the ref its changes are measured from, and ${BRANCH_FACTS}, and clean: true only when git -C <its worktree> status --porcelain prints nothing (a worktree with any staged, unstaged or untracked change is not declared); give each task that commits there branch: <name>. Classify and write every acceptance criterion by ~/.agents/standards/acceptance-planning.md (read it); set metric true only on an evidence criterion, never on a note (R9: an owner-designated observation stays a note even when it reads a cost, a time or a rate), whose threshold is a cost, a time or a rate that only a deploy or observation over time shows, and give its verify member mode observe (R5); a bound that a test or a run before merge enforces belongs to a code criterion with metric false (R1). Return no criterion that only restates a declared verification command passing: the verify step proves it. Give every evidence or human criterion a verify member: one check of the verify block grammar with ac its id and kind its kind, writing any sha that will name the merge commit as the base sha ${setup.base_sha} (ship substitutes the merge commit); an unattended evidence command run must be one of ${JSON.stringify(VERIFY_IDS)}, else use a script or a probe. Lint each member alone: write {"v": 1, "merge": "${setup.base_sha}", "checks": [<that member>]} to a file in ${setup.plan_dir} and run verify-pending lint --input <that file> --repo-root ${W} --pr-branch ${setup.branch} plus one --pr-workflow <name> for each CI workflow that runs on this repository's pull requests; return the verdict as that criterion's lint. List in scripts each script path a verify run names that a task of this plan commits. Before you return, check the plan against the review it will get: ${PLAN_RUBRIC}; and every rule ${RULE_IDS[0]}-${RULE_IDS[RULE_IDS.length - 1]} of ~/.agents/standards/acceptance-planning.md (read it). ${PLAN_SELF_CHECK}${decisions.length ? `\nThe owner has answered the open decisions for this issue; they are binding: ${decisions.join('\n')} Do not ask them again; record them as decisions in the plan.` : ''}${!extra && priorFindings.length ? `\nAn earlier plan of this issue was dropped at plan review with these findings left on it; write this plan so that none of them recurs: ${JSON.stringify(priorFindings)}` : ''}${extra || ''}
${RULES}`
// A planner reply is either questions (the plan is dropped so a resume plans again with decisions) or a well-formed plan.
// #869: a well-formed plan refused only for its declared branches gets one revise in place first, so a naming fault does not cost the whole plan.
// #819: the accepted reply's criteria_edited, taken off the plan so it reaches no cont and no stop.
let planEdited
const takePlan = async (p, label, left) => {
  if (wellFormed(p) && branchProblems(p).length) {
    const faults = branchProblems(p)
    log(`${label}: ${faults.length} branch problems, revising once`)
    label = 'plan-branch-revise'
    p = await call(planPrompt(`\nYour plan at ${p.plan_root} declares its branches wrongly; fix only these problems in place, change nothing else, and return the full result again: ${JSON.stringify(faults)}`), { label: 'plan-branch-revise', phase: 'Plan', agentType: 'planner', schema: PLAN_SCHEMA })
  }
  reordered = []
  if (p && p.status === 'needs_user') { dropPlan(left); planReviewed = false; return stop('plan', { needs_user: p.questions }) }
  // A failed revision may have half-edited the files on disk, so the plan is dropped and a resume plans again.
  if (!wellFormed(p)) { dropPlan(left); planReviewed = false; return stop('plan', { step: label, invalid: p }) }
  const bad = branchProblems(p)
  if (bad.length) { dropPlan(left); planReviewed = false; return stop('plan', { step: label, invalid: p, branch_problems: bad }) }
  const { criteria_edited: listed, ...rest } = p
  plan = rest
  planEdited = listed
  return null
}

// #771: the contract's fast pre-commit ids (verification_conditions pre_commit: true), named with argv and cwd; none keeps the generic sentence.
const PRE_COMMIT = setup.verification.filter(e => e && e.pre_commit === true).map(e => ({ id: e.id, argv: e.argv, cwd: e.cwd }))
const FMT = PRE_COMMIT.length
  ? `Before committing, run the fast pre-commit checks of that verification: each of ${JSON.stringify(PRE_COMMIT)} (its argv with <worktree>/<its cwd> as working directory), and fix what it reports.`
  : `Before committing, run any formatter or lint fix the project's standards (${list(K.standards)}) name on the files you changed.`
const FOCUSED = `Run only the tests covering the files you changed, not the full suite or the declared verification (it runs once later). ${FMT}`
// #787: whole test files after the task loop; one class missed a failing sibling test three times.
const WHOLE = files => `run in full every test file among or covering ${files} (never a single test class) and any fast suite the project declares, not the declared verification; return tests: each command and its result`
const FIX_TESTS = `Before returning, ${WHOLE('the files you changed')}. ${FMT}`
// #963: the fix wave and the verification fix are each followed by the verify step, so they run no suite: it ran twice per wave.
const OWN_TESTS = `Before returning, run in full every test file among or covering the files you changed (never a single test class) and no suite: the verify step runs it next; return tests: each command and its result. ${FMT}`
// #941: what the resolution of a conflicted sync merge tests, the same text in deliver-batch.js: the files it resolved, not everything the merge brought in.
const RESOLVE_SCOPE = 'the checks of the pull request cover everything else the merge brought in, so run no test for a file that merged cleanly'
// A fix agent once committed a lock file a tool had generated beside its fix; every fix prompt carries this.
const COMMIT_SCOPE = 'Before committing, read git status in the worktree you commit in and stage by path only the files the fix itself changed or created; never run git add -A, git commit -a or git add on a directory (the dot included); a lock file, a generated file or an untracked file the fix did not need is left unstaged and named in notes.'
// #907: the conflicted-sync wording, the same text in deliver-batch.js. The marker check runs before the merge is committed, when HEAD is still the
// branch's own head: git diff --check HEAD compares the whole working tree with it, so it reads every line the merge brings in, in a file
// resolved by hand as in one merged cleanly, staged or not (the plain form goes silent once a file is staged, --cached misses a later edit).
// It also reports content the integration branch brought in (a setext or RST underline of seven =, a fixture with markers, whitespace), so the same
// check runs against origin's head too: a line both report, by file and line number, is in neither parent, so it is a real leftover, wherever else
// such a line stands. Removal is limited to those lines in hand-resolved files; markers_checked says both checks ran, whatever they reported.
const MARKER_CHECK = (wt, int) => `run git -C ${wt} diff --check HEAD and git -C ${wt} diff --check origin/${int} before committing and remove each leftover conflict marker both report (same file and line) in a file you resolved by hand; every other line they report is content and stays`
const MARKERS_UNCHECKED = ' The merge was not checked for leftover conflict markers: report any left in the files it changed.'
const SYNC_FIX = (wt, mc, findings, after = '') => `A reviewer found defects in the conflict resolution of merge commit ${mc} (git -C ${wt} show --cc ${mc})${after}: ${JSON.stringify(findings)}. Fix each real defect on top of ${after ? 'that head' : 'the merge'} with a regression test (never redo or rewrite the merge), then commit; if a finding is wrong, commit nothing for it and say so with evidence in notes.`
const SYNC_REREVIEW = (wt, mc, findings, fix, moved, after = '') => `Re-review these conflict-resolution findings against ${moved ? `the fix (git -C ${wt} diff ${fix.start_head}..${fix.commit}) made on top of` : 'the rebuttal (no new commit) of'} merge commit ${mc}${after}: ${JSON.stringify(findings)}; notes: ${fix.notes}. ${moved ? '' : `Check each rebuttal against the code yourself (git -C ${wt} show --cc ${mc}); a finding the evidence does not refute is still unresolved. `}Report any still unresolved and any new Important or Critical defect. Do not edit anything.`
// #986: a resolution may carry plain commits on top of its merge commit (a fix its tests asked for once the merge was committed). The
// program cannot read git, so the sync review proves the ancestry itself (DESCENDS) and reads the merge and the range from it to the head;
// the fix round and the re-review name the same range (SYNC_AFTER). A head that does not descend from its merge commit never lands.
// The same text in both programs, like the wording above.
const SYNC_AFTER = (wt, mc, head) => ` and the commits made on top of it up to the head ${head} (git -C ${wt} diff ${mc}..${head})`
const DESCENDS = (wt, mc, head) => ` The resolution's head ${head} is not its merge commit: first run git -C ${wt} merge-base --is-ancestor ${mc} ${head} and git -C ${wt} rev-list --count --min-parents=2 ${mc}..${head}, and return descends true only when the first exits 0 and the second prints 0 (the head is the merge commit with plain commits on top of it), else descends false and no finding. When it descends, review those commits as well (git -C ${wt} diff ${mc}..${head}), above all for a test or check they weaken, skip or delete, and report any conflict marker git -C ${wt} diff --check ${mc} ${head} shows in them.`
const RESOLVE_ORDER = 'Fix in the resolution itself what those tests show and commit the merge only once they pass. When a defect shows only after the merge is committed, never amend or redo the merge: fix it in a commit on top of it, run those tests again, and report the merge commit and the head as they are'
// #986: a rerun covers every failed run of the head. Each check is its own workflow run, so a gate or aggregate check that failed only
// because another check failed keeps its old failure unless its own run is rerun too; a gate that waits for the head's other runs then
// goes green with them, so the reruns need no order.
const RERUN_ALL = (unset, slug, sha) => `rerun the failed jobs once, with ${unset}gh run rerun <run-id> --repo ${slug} --failed for each failed run of the head: list them with ${unset}gh run list --repo ${slug} --commit ${sha} --json databaseId,workflowName,conclusion, keep the newest run of each workflowName (the highest databaseId; never an older run that one superseded) and rerun each of those whose conclusion is failure, cancelled or timed_out, not only the run of the check that broke first. Every check is its own run, so a gate or aggregate check that failed only because another check failed is rerun too, with the same command`
// #986: the backstop for a gate that was not rerun, or was rerun before the checks it reports on finished: in the one poll that follows a
// rerun, the checks step reruns such a gate and names its runs as stale. The program then polls once more and does not count that poll
// as red; the poll after it carries no such instruction, so a check that is red there ends the landing as any second red poll does.
const STALE_RERUN = (unset, slug) => `This poll follows a rerun of failed jobs at this head. When checks still fail once none is pending, decide whether every failing check is stale: a check that only reports on other checks (a gate or aggregate job) is stale when every check it reports on now passes at head and its own run finished before theirs did (compare updatedAt from ${unset}gh run view <run-id> --repo ${slug} --json updatedAt; it was not rerun, or it was rerun too early). Only when every failing check is stale, rerun each of their runs once with ${unset}gh run rerun <run-id> --repo ${slug} --failed (the run id is in the check's link), do not wait for them, and answer failed with failing and with stale: the run ids you reran. In every other case rerun nothing and return no stale.`
const WITH_STALE = s => ({ ...s, properties: { ...s.properties, stale: { type: 'array', items: { type: 'integer' } } } })
const staleOf = ck => (Array.isArray(ck.stale) ? ck.stale.filter(Number.isInteger) : [])
const CX_USE = 'Use the codex-collaboration skill (invoke it with the Skill tool) to run that Codex'
const CX_WAIT = 'this step may dispatch the Codex reviewer that skill uses, and must wait for its result in this turn.'
const CX_NONE = 'If Codex cannot be run, return available false with the reason in raw_summary; never substitute your own review.'
// #790: a codex-unavailable stop says why (a usage limit and its reset time), so no diagnosis run is needed.
const codexWhy = r => (!r ? 'the Codex review step returned nothing' : typeof r.raw_summary === 'string' && r.raw_summary.trim() ? r.raw_summary : 'the Codex review step gave no reason')
// #996: a Codex refusal whose message is the provider's usage or quota limit (codex-collaboration returns the message verbatim, with the
// reset time; the provider's wording is matched, so "not a quota limit" or "Disk quota exceeded" is no quota stop)
// carries retry_after: the reset time the message gives after "try again at" or "resets at" (up to the sentence's end, an a.m. or p.m. kept whole), null when it gives none. The limit does not
// lift by a relaunch, so deliver-batch hands such a stop to the owner; any other codex-unavailable stop carries no retry_after and is unchanged.
// The message is read, not a schema member: CODEX's keys are the codex-collaboration skill's contract, and no review prompt grows.
const codexStop = (step, r) => {
  const said = r && typeof r.raw_summary === 'string' ? r.raw_summary : ''
  const quota = /hit your usage limit|exceeded your (?:current )?quota|(?<!disk )quota exceeded|usage limit reached/i.test(said)
  const reset = quota ? ((/\b(?:try again|resets?) (?:at|in|on) ([^.\n]{0,60}?[ap]\.m\.|[^.\n]{1,60})/i.exec(said) || [])[1] || '').trim() : ''
  return stop('codex-unavailable', { step, details: codexWhy(r), codex: r, ...(quota ? { retry_after: reset || null } : {}) })
}
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
let SKIP_REVIEW = !!(verified && plan && sameSha(setup.head, verified.head) && !setup.dirty && plan.tasks.every(t => taskLog.some(d => d.n === t.n)) && branchesSame(verified))
// A passed final review, on the head it passed at (or one that only gained integration-branch merges), is not run again; verify still is.
let SKIP_FINAL = !SKIP_REVIEW && LANE === 'standard' && !!finalReviewed && !!plan && plan.tasks.every(t => taskLog.some(d => d.n === t.n)) && !setup.dirty && (sameSha(setup.head, finalReviewed.head) || setup.since_reviewed === 'merge_only') && branchesSame(finalReviewed)
if (!SKIP_REVIEW) verified = null
if (!SKIP_REVIEW && !SKIP_FINAL) finalReviewed = null
// The last commit the final review will cover.
let tip = setup.head || null
// The verification contract as freshly resolved, key order aside: cached results answer only this contract.
const canon = v => Array.isArray(v) ? `[${v.map(canon).join(',')}]` : v && typeof v === 'object' ? `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canon(v[k])}`).join(',')}}` : JSON.stringify(v)
const VERIFY_CONTRACT = canon(setup.verification)
let VERIFY_CACHED = SKIP_REVIEW && verified.contract === VERIFY_CONTRACT
const DIRECT_IMPL = { ...IMPL, properties: { ...IMPL.properties, acceptance: PLAN_SCHEMA.properties.acceptance, sensitive: { type: 'boolean' }, ineligible: { type: 'boolean' } } }
// The direct lane's first-pass review grades each criterion: met, and the test (name, file:line) or command that shows it.
const GRADED_FINDINGS = {
  ...FINDINGS,
  properties: { ...FINDINGS.properties, acceptance: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, met: { type: 'boolean' }, evidence: { type: 'string' } }, required: ['id', 'met', 'evidence'] } } },
  required: [...FINDINGS.required, 'acceptance'],
}
const DIRECT_FINDINGS = { ...GRADED_FINDINGS, properties: { ...GRADED_FINDINGS.properties, escalate: { type: 'boolean' } } }
// A code criterion the review did not grade met with evidence is an Important finding; a human or evidence criterion cannot be shown by a test or command here, so it is not held to this.
const ungradedFindings = (review, criteria) => criteria.filter(a => a.kind === 'code').flatMap(a => {
  const g = (Array.isArray(review.acceptance) ? review.acceptance : []).find(x => x && x.id === a.id)
  if (g && g.met === true && typeof g.evidence === 'string' && g.evidence.trim()) return []
  return [{ severity: 'important', summary: `Acceptance criterion ${a.id} (${a.text}) is not shown met with evidence: ${g ? (g.met === true ? 'the review gave no evidence' : 'the review graded it unmet') : 'the review did not grade it'}. Assert it with a test, or show the command that proves it.` }]
})
// #935: a criterion restating the declared verification had no evidence before verify (the direct lane runs focused tests only), so it stopped the delivery.
const NO_VERIFY_AC = 'Do not write the declared verification commands as an acceptance criterion: the verify step gates on them.'
// #935: a fix round whose findings are all ungraded criteria produces their evidence; FOCUSED would forbid the command a criterion names.
const EVIDENCE_FIX = `Produce the evidence each criterion asks for: run the command it names (or the test that asserts it, written first when none exists) in the worktree, and report in notes, per criterion id, the command, its exit status and its last lines. The focused-tests-only rule does not apply to a command a criterion names. If it fails, fix the cause with a regression test and commit; when nothing has to change, commit nothing and return commit equal to start_head. ${FMT}`
const EVIDENCE_REREVIEW = ' These findings are acceptance criteria the review did not see shown met, and the notes carry the evidence produced for each (the command, its exit status and last lines; the diff is empty when nothing had to change): a criterion that evidence shows met is resolved, and one without it, or whose command failed, is still unresolved.'

// ---------------- Direct lane ----------------
if (LANE === 'direct') {
  // The deliver-direct skill stays the single source of the implementer's steps; this block never copies its text.
  let impl = null
  if (!taskLog.some(d => d.n === 1)) {
    phase('Tasks')
    impl = await recall(() => call(`${CTX}
${RENEW_FIRST}
Then deliver issue #${ISSUE} in the direct lane. Invoke the deliver-direct skill with the Skill tool to read it: it is the single source for this step. Its steps 1 and 2 are done by this program (the claim is held by ${setup.holder}; the worktree is ${W} on branch ${setup.branch}). Check its Eligibility first: if the issue fails it, change nothing and return status blocked with ineligible true and why. Otherwise follow its step 3 exactly and commit. Do not run its steps 4 to 7: review, verification, ship and close-out belong to this program. Return acceptance (the issue's criteria; ${KIND_GUIDE}) and sensitive (true when the diff touches authentication or authorization, permission or command guards, secrets or credentials, CI/CD or deploy config, or data migrations). ${NO_VERIFY_AC} ${FOCUSED} ${IMPL_RETURN}${CONT && CONT.partial === 1 ? `
An earlier attempt at this task was cut off and may have left uncommitted edits or commits in the worktree (git -C ${W} status, git -C ${W} diff and git -C ${W} log ${RANGE}). Inspect them: keep what matches, finish or redo the rest, and make sure the failing-test-first and mutation checks still hold for the final result; start_head is the head before this task's first commit.` : ''}${newDecision !== null ? `
That attempt returned blocked: ${JSON.stringify(BLOCKED.notes)}. The owner's decision settles it and is binding: ${JSON.stringify(newDecision)}` : ''}
${RULES}`, { label: 'direct-impl', phase: 'Tasks', agentType: 'implementer', model: 'sonnet', schema: withRenew(DIRECT_IMPL) }), r => r.renew)
    // #996: a reply means the decision reached the implementer; a blocked one below records its own notes.
    if (impl) { decisionPending = false; blocked = null }
    if (impl) {
      const lost = renewed(impl.renew, 'tasks')
      if (lost) return lost
    }
    if (impl && impl.ineligible) return stop('ineligible', { impl, details: 'rerun in the standard lane without cont; setup re-adopts the worktree and the claim' })
    if (!implDone(impl)) return haltImpl(1, { task: { n: 1 }, impl })
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
Run the project's configured independent code review: the contract's workflow.review.code is the command ${REVIEW_CODE}. ${CX_USE} diff review over the delivery range ${RANGE} in the worktree ${W}, with no review package; ${CX_WAIT} Return Codex's Important or Critical findings as they are (correctness defects with a concrete failing input, unmet criteria) without adding your own review; verdict pass if none. ${CX_NONE}
${RULES}`, { label: 'direct-codex', phase: 'Final review', agentType: 'clerk', model: CLERK_MODEL, effort: 'high', schema: CODEX }) : Promise.resolve(null)
    // The stored plan's risk, not this run's reply, picks the reviewer, so a resumed review keeps the implementer's choice.
    const lite = plan.tasks[0].risk !== 'security'
    const reviewPrompt = isLite => `${CTX}
${isLite ? 'lane: direct. ' : ''}Review the delivery diff git -C ${W} diff ${RANGE} for issue #${ISSUE} against its acceptance criteria ${ACS}. ${KNOW} Report Important or Critical correctness defects and unmet code criteria only, each with a concrete failing input. Return acceptance with one entry per criterion id: met, and evidence, which is the test name and file:line that asserts the criterion, or the command that shows it; a code criterion that is not met, or has no evidence, is an Important finding, and criteria of other kinds are not findings (grade them and give what you observed). ${isLite ? 'If the diff touches authentication or authorization, permission or command guards, secrets or credentials, CI/CD or deploy config, or data migrations, set escalate true. ' : ''}Do not edit anything.`
    let review = await call(reviewPrompt(lite), { label: 'direct-review', phase: 'Final review', agentType: lite ? 'reviewer-lite' : 'reviewer', schema: DIRECT_FINDINGS })
    let passedBy = lite ? 'reviewer-lite' : 'reviewer'
    if (lite && review && review.escalate === true) {
      review = await call(reviewPrompt(false), { label: 'direct-review-full', phase: 'Final review', agentType: 'reviewer', schema: GRADED_FINDINGS })
      passedBy = 'reviewer'
    }
    const codexR = await codexP
    if (!review) return stop('direct-review', { review: null })
    if (REVIEW_CODE && (!codexR || !codexR.available)) return codexStop('code', codexR)
    const ungraded = ungradedFindings(review, plan.acceptance)
    const findings = findingsOf(review).concat(ungraded, REVIEW_CODE ? findingsOf(codexR).map(f => ({ ...f, source: 'codex' })) : [])
    if (REVIEW_CODE) log(`codex review: ${findingsOf(codexR).length} blocking findings`)
    if (findings.length) {
      log(`direct review: ${findings.length} blocking findings, one fix round`)
      // No reviewer or Codex finding among them: only evidence is missing.
      const evidenceOnly = findings.length === ungraded.length
      if (evidenceOnly) log('direct review: only ungraded criteria, the fix round produces their evidence')
      fix = await call(evidenceOnly ? `${CTX}\n${PLAN_REF} The review did not see these acceptance criteria shown met: ${JSON.stringify(findings)}. ${EVIDENCE_FIX} ${COMMIT_SCOPE} ${IMPL_RETURN}\n${RULES}` : `${CTX}\n${PLAN_REF} Fix these review findings in the worktree, with a regression test for each real defect, then commit: ${JSON.stringify(findings)}. If a finding is wrong, say so in notes with evidence instead of changing code. ${FOCUSED} ${COMMIT_SCOPE} ${IMPL_RETURN}\n${RULES}`, { label: 'direct-fix', phase: 'Final review', agentType: 'implementer', model: 'sonnet', schema: IMPL })
      if (!implDone(fix)) return stop('direct-fix', { fix })
      const rereview = await call(`${CTX}
Re-review only these previously reported findings against the fix: ${span(fix)}; the implementer's notes: ${fix.notes}. Findings: ${JSON.stringify(findings)}. Report any finding still unresolved and any new Important or Critical defect the fix introduced.${evidenceOnly ? EVIDENCE_REREVIEW : ''}`, { label: 'direct-rereview', phase: 'Final review', agentType: 'reviewer-lite', schema: FINDINGS })
      if (!rereview || findingsOf(rereview).length) return stop('direct-review', { review: rereview, findings })
      passedBy = 'reviewer-lite'
    }
    Object.assign(d1, { reviewed_head: fix ? fix.commit : reviewHead, review_rounds: fix ? 1 : 0, reviewer: passedBy })
  }
} else {
phase('Plan')
if (plan) {
  const bad = branchProblems(plan)
  if (bad.length) { dropPlan(); planReviewed = false; return stop('plan', { step: 'resume', invalid: CONT.plan, branch_problems: bad }) }
}
// The owner's answer is read when there is no plan or a kept plan awaits it; that read carries the plan's claim renew.
const RESUME_KEPT = !!(plan && !planReviewed && planFindingsKept)
const ANSWER_NEEDED = !plan || RESUME_KEPT
if ((!plan || !planReviewed) && !ANSWER_NEEDED) {
  const lost = await renew('plan', 'Plan')
  if (lost) return lost
}
// Grades an answer to the decision prompt. null = usable (an answered one has joined the decisions); else the stop to return.
const takeAnswer = answer => {
  if (!complete(answer, ANSWER_SCHEMA) || !['none', 'open', 'answered'].includes(answer.verdict)) return stop('owner-answer', { result: answer })
  if (answer.verdict === 'answered') {
    // An answered prompt with no decision text would let planning go on without the owner's choices.
    if (typeof answer.decisions !== 'string' || !answer.decisions.trim()) return stop('owner-answer', { result: answer })
    addDecision(answer.decisions)
  }
  return null
}
const readAnswer = async () => {
  // After a transient setup renew this step is the one retry (#740): it is not re-called, as the acquire fallback is not.
  const askAnswer = () => call(`${CTX}
${RENEW_FIRST}
Then read the owner's answer to the decision prompt of issue #${ISSUE}: run alone, exactly, forge-claim owner-action status --repo ${SLUG} --issue ${ISSUE} --reason decision. It prints one JSON line. Change nothing: post nothing, edit nothing, end nothing. Return verdict, comment_id, questions and decisions exactly as printed.`, { label: 'owner-answer', phase: 'Plan', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: withRenew(ANSWER_SCHEMA) })
  const answer = RENEW_RECALL ? await askAnswer() : await recall(askAnswer, r => r.renew)
  if (!answer) return stop('owner-answer', { result: answer })
  const lost = renewed(answer.renew, 'plan')
  if (lost) return lost
  return takeAnswer(answer)
}
// Only findings the rules-only revise may touch resume as one, a Codex-triggered plan's included (#823). A kept plan with any other
// finding left has spent its one full revise, so it is dropped and planned again with the owner's answer; the kept state stays in the cont until that answer is read.
const RESUME_RULES = RESUME_KEPT && rulesOnly(planFindingsKept.rules)
if (ANSWER_NEEDED) {
  // A fresh run's setup already read the answer, and renewed after an already_held acquire; a resume or a transient fold reads it again.
  const stopped = !CONT && !ACQ_RECALL && !RENEW_RECALL ? takeAnswer(FOLD_ANSWER) : await readAnswer()
  if (stopped) return stopped
}
if (RESUME_KEPT && !RESUME_RULES) dropPlan()
if (AMEND !== null) {
  if (!plan) return why({ stage: 'amend', error: 'this resume plans the kept plan again, which would overwrite the amendment; resume without amend, then amend the new plan after its stop', ...deadOf(), cont: CONT })
  // A plan not yet reviewed was renewed above; a reviewed plan's renew would ride in the first implementer call, which runs after this step.
  if (planReviewed) {
    const lost = await renew('amend', 'Plan')
    if (lost) return lost
  }
  const am = await call(`${CTX}
Apply the owner's amendment to the plan at ${AMEND_INPUT.plan_root} with one plan-amend run and nothing else. (1) Make a fresh directory with mktemp -d and write the JSON of the Input line below, byte for byte, to a file in it. (2) Run alone and exactly: plan-amend apply --input <that file>. It prints one JSON line; return its status, edits, refused and detail exactly as printed. On a non-zero exit with no JSON line, return status error, empty edits and refused, and its stderr as detail. Edit no file yourself and commit nothing.
Input: ${JSON.stringify(AMEND_INPUT)}
${RULES}`, { label: 'amend', phase: 'Plan', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: AMEND_SCHEMA })
  // The clerk may have written the plan before its reply was lost or came back uncertain, so a stop here cannot hand back results cached before
  // the amend: a relaunch would find every edit already recorded and skip the review and verify of the amended plan. Only a refusal the helper
  // reported itself is known to have written nothing, and it keeps the cont as it came.
  const STALE = (({ verified: _v, final_reviewed: _f, ...rest }) => rest)(CONT)
  if (!am) return why({ stage: 'amend', result: null, ...deadOf(), cont: STALE })
  const graded = am.status === 'applied' && Array.isArray(am.edits) && am.edits.length === AMEND_INPUT.edits.length &&
    am.edits.every((g, i) => isEntry(g) && g.file === AMEND_INPUT.edits[i].file && (g.already === true || (g.exists === true && g.occurrences === 1)))
  if (!graded) return why({ stage: 'amend', amend: am, details: 'plan-amend did not apply every edit; a refused or error status wrote nothing', ...deadOf(), cont: am.status === 'refused' ? CONT : STALE })
  log(`amend: applied ${AMEND_INPUT.edits.length} edit(s) to the plan`)
  amendApplied = true
  // #996: the amended task file is the owner's answer to a blocked task, unless a decision is still to be worked in below.
  if (newDecision === null && !(BLOCKED && BLOCKED.asked)) blocked = null
  // An applied amend makes every cached result stale, even when every edit was recorded already: an earlier run may have died after the clerk
  // wrote the plan and before any stop said so, leaving only a cont from before the amend. The final review and verify run again.
  SKIP_REVIEW = false
  SKIP_FINAL = false
  VERIFY_CACHED = false
  verified = null
  finalReviewed = null
}
if (!plan) {
  const halted = await takePlan(await call(planPrompt(), { label: 'plan', phase: 'Plan', agentType: 'planner', schema: PLAN_SCHEMA }), 'plan')
  if (halted) return halted
}
const rulesReview = async triggered => {
  return call(`${CTX}
Re-check only the acceptance criteria of the revised plan at ${plan.plan_root} against every rule of ~/.agents/standards/acceptance-planning.md (read it). The findings that triggered the revision were ${JSON.stringify(triggered)}. Report each criterion that still or newly breaks a rule, with the broken rule's id in the finding's rule and the criterion's id in its ac (on a minor finding too).${decisions.length ? ` The owner's decisions for this issue are binding, so a criterion classified as one of them says breaks no rule: ${decisions.join('\n')}` : ''} Do not edit anything.`, { label: 'plan-rules-review', phase: 'Plan', agentType: 'reviewer', schema: PLAN_REVIEW })
}
// #819: the members of a criterion the rules judge (its wording among them), key order aside; a revise that leaves them as reviewed needs no rules re-review.
const ruleFacts = p => canon(p.acceptance.map(a => [a.id, a.text === undefined ? null : a.text, a.kind, a.metric === true, a.verify === undefined ? null : a.verify]))
// #819: the criterion text lives only in the issue and the planner's reply (plan.md maps ids, it holds no text), and a planner retypes
// every criterion it returns. The candidate gives each criterion that existed before and that the revise does not list as edited
// (ids compared without case) its earlier text; the caller takes it whole or not at all. #951: the revise is asked about the member
// that is restored, the criterion's text (plan.md's rows hold none), and for a change made to fix a finding, not a retyping; a text
// rewritten to fix a finding is listed and so kept. A finding that names a criterion no longer keeps its retyped text (in 6 of 9
// measured re-reviews that was the only blocker, with no wording changed).
const keepUnlistedText = (before, after, edited) => after.map(a => {
  const was = a && typeof a.id === 'string' && a.id ? before.find(b => b && b.id === a.id) : null
  if (!was || typeof was.text !== 'string' || was.text === a.text || edited.includes(a.id.toLowerCase())) return a
  return { ...a, text: was.text }
})
// #988: the rules reviewer's minor findings on a criterion that also has a blocking finding (the program's or the reviewer's), matched by
// the ac member alone (case and spaces aside, never by reading the summary). They go to the rules revise as context: they are no part
// of rules, so they neither block nor count toward a stop. A minor finding with no ac, or on another criterion, stays dropped.
const acKey = f => (isEntry(f) && typeof f.ac === 'string' ? f.ac.replace(/\s+/g, '').toLowerCase() : '')
const notedOn = (found, blocking) => {
  const keys = blocking.map(acKey).filter(k => k !== '')
  return (Array.isArray(found) ? found : []).filter(f => isEntry(f) && f.severity === 'minor' && keys.includes(acKey(f))).slice(0, 8)
}
// One targeted planner call fixing only the given findings, then the program's rule check and the rules re-review (D4-D6).
// Its findings all carry a rule, so its re-review always runs.
// #988: a criterion (by its ac member) whose classification the rules pull two ways: a classification rule (R1, R3, R5, R9) blocked it
// before the rules revise, that rule is gone after it, and another classification rule the criterion did not break before blocks it
// now. A rule that survives its revise, and R4 (a verify block still to get right), are mechanical: they stay plain plan-review stops.
const CLASS_RULES = ['R1', 'R3', 'R5', 'R9']
const conflictOf = (before, after) => {
  for (const f of after) {
    const k = acKey(f)
    if (!k || !CLASS_RULES.includes(f.rule)) continue
    const was = before.filter(b => acKey(b) === k).map(b => b.rule)
    const now = after.filter(b => acKey(b) === k).map(b => b.rule)
    const gone = [...new Set(was.filter(r => CLASS_RULES.includes(r) && !now.includes(r)))]
    if (gone.length && !was.includes(f.rule)) return { ac: f.ac.trim(), rules: gone.concat(f.rule) }
  }
  return null
}
// left: the review findings to keep as prior findings when this revise drops a plan that no plan-review stop has kept yet.
const rulesRevise = async (findings, noted, left = []) => {
  const root = plan.plan_root
  const also = noted.length ? ` The rules reviewer also noted these minor findings on the same criteria; they are context for choosing the fix, not findings to fix by themselves: ${JSON.stringify(noted)}` : ''
  const halted = await takePlan(await call(planPrompt(`\nFix only these rule findings in your plan at ${root} in place, change nothing else, and return the full result again: ${JSON.stringify(findings)}${also}`), { label: 'plan-rules-revise', phase: 'Plan', agentType: 'planner', schema: PLAN_SCHEMA }), 'plan-rules-revise', findings.concat(left))
  if (halted) return { halted }
  const still = planRules(plan)
  const rr = await rulesReview(findings)
  if (!rr) return { silent: true }
  const rules = still.concat(findingsOf(rr))
  const conflict = conflictOf(findings, rules)
  return { rules, noted: notedOn(rr.findings, rules), ...(conflict ? { extra: { conflict } } : {}) }
}
// A plan-review stop keeps the revised plan unless this was the second failed rules revise (D5).
const reviewStop = (rules, findings, rounds, given, noted = []) => {
  planReviewed = false
  // The conflict says how many rules revises a resume of this stop still has, so its reason claims nothing false.
  const extra = given && given.conflict ? { ...given, conflict: { ...given.conflict, revises_left: rounds >= 2 ? 0 : 1 } } : given
  if (rounds >= 2) dropPlan(rules.concat(findings))
  else planFindingsKept = { rules, findings, rounds, ...(noted.length ? { noted } : {}) }
  return stop('plan-review', { ...(extra || {}), rules, findings })
}
const SILENT = { details: 'the rules re-reviewer returned nothing' }
// What follows a full revise (the plan review's, and #996's task revise): the reply through takePlan, then the program's rule check and
// the rules re-review. null = the revised plan stands; else the stop to return.
const settleRevise = async (revised, planFindings, reviewedFacts, reviewedCriteria) => {
  const halted = await takePlan(revised, 'plan-revise', planFindings)
  if (halted) return { ...halted, findings: planFindings }
  // #819: the restored candidate replaces the reply only when it makes the skip below fire; a renumbered, reused or duplicated id,
  // or any other change, leaves the reply exactly as returned. A plan-revise reply with no criteria_edited is unknown: no restore.
  // A branch revise that takePlan ran after it adds its own list to the plan-revise reply's.
  if (Array.isArray(revised.criteria_edited) && !planFindings.some(f => present(f.rule))) {
    const edited = [revised.criteria_edited, planEdited].flatMap(l => (Array.isArray(l) ? l : [])).filter(x => typeof x === 'string').map(x => x.toLowerCase())
    const candidate = { ...plan, acceptance: keepUnlistedText(reviewedCriteria, plan.acceptance, edited) }
    const restored = candidate.acceptance.filter((a, i) => a !== plan.acceptance[i]).length
    if (restored && !planRules(candidate).length && ruleFacts(candidate) === reviewedFacts) {
      log(`plan-revise: kept the earlier text of ${restored} criteria the revise does not list as edited`)
      plan = candidate
    }
  }
  const still = planRules(plan)
  // #819: no trigger named a rule, the program's rule check is clean and no criterion's id, text, kind, metric or verify changed.
  const sameRules = !planFindings.some(f => present(f.rule)) && !still.length && ruleFacts(plan) === reviewedFacts
  if (sameRules) log('plan rules re-review skipped: no finding named a rule and the acceptance criteria are unchanged')
  const rr = sameRules ? { findings: [] } : await rulesReview(planFindings)
  if (!rr) return reviewStop(planFindings, planFindings, 0, SILENT)
  let rules = still.concat(findingsOf(rr)), rounds = 0, noted = notedOn(rr.findings, rules), extra
  if (rulesOnly(rules)) {
    rounds++
    const r = await rulesRevise(rules, noted, planFindings)
    if (r.halted) return { ...r.halted, findings: planFindings }
    if (r.silent) return reviewStop(rules, planFindings, rounds, SILENT, noted)
    rules = r.rules
    noted = r.noted
    extra = r.extra
  }
  if (rules.length) return reviewStop(rules, planFindings, rounds, extra, noted)
  return null
}
// #996: the task revise. A resume of a task-blocked cont with a new decision has a planner amend that task's file from the decision and
// the implementer's notes before the implementer runs again, through the plan-revise path above. A revise that does not end in an
// accepted plan (questions, a malformed reply, rule findings left (a rules conflict among them), a done task dropped or given another file or branch, a criterion
// removed: restating a criterion's text is allowed, removing one stays an owner amend) keeps the cont's plan, its prior findings and its blocked member; the
// task files on disk may hold its edits. The decision stays unused, so the same resume tries again, except after questions: then it is
// kept, and the resume that brings the answer shows the planner both.
const BLOCKED_TASK = BLOCKED && !RERUN && plan && planReviewed ? plan.tasks.find(t => isEntry(t) && t.n === BLOCKED.task) || null : null
// A decision for a blocked task the plan no longer lists has nothing to revise: it is kept as any other.
if (!BLOCKED_TASK) decisionPending = false
let renewedHere = AMEND !== null
if (BLOCKED_TASK) {
  if (newDecision === null && BLOCKED.asked) {
    // The revise asked the owner: the answer is on the decision prompt (that read carries the claim renew).
    const had = decisions.slice()
    const stopped = await readAnswer()
    if (stopped) return stopped
    renewedHere = true
    newDecision = decisions.find(d => !had.includes(d)) || null
    decisionPending = newDecision !== null
  }
  if (newDecision === null && !amendApplied) return stop('task', { task: { n: BLOCKED.task }, blocked: BLOCKED, ...UNSETTLED })
  if (newDecision === null) blocked = null
}
if (BLOCKED_TASK && newDecision !== null) {
  const t = BLOCKED_TASK
  // The implementer's first call would renew, but it runs after this step (as after an amend, whose own renew stands for this one).
  if (!renewedHere) {
    const lost = await renew('plan', 'Plan')
    if (lost) return lost
  }
  const prior = { plan, reordered, priorFindings }
  const facts = ruleFacts(plan), criteria = plan.acceptance
  const asked = [{ severity: 'important', file: t.file, summary: `the implementer of task ${t.n} returned blocked: ${BLOCKED.notes}` }]
  const revised = await call(planPrompt(`\n${MAP_FIRST} Task ${t.n} (${t.title}) of your plan at ${plan.plan_root} stopped: its implementer returned blocked on its task file ${t.file}, and the owner then decided: ${JSON.stringify(newDecision)}. Treat the implementer's notes as the finding and that decision as binding: fix only that task file in place (and plan.md, the code map or another task file only where the decision requires it), keep every task's number, and return the full result again, with criteria_edited: the ids of the criteria whose text you changed to follow the decision (typing the same criterion again in other words is not a change; an empty list when you changed none). The notes: ${JSON.stringify(BLOCKED.notes)}`, REVISE_PACE), { label: 'plan-task-revise', phase: 'Plan', agentType: 'planner', schema: PLAN_SCHEMA })
  let failed = await settleRevise(revised, asked, facts, criteria)
  if (!failed) {
    const touched = taskLog.filter(d => { const was = prior.plan.tasks.find(o => o.n === d.n), now = plan.tasks.find(o => o.n === d.n); return !now || (!!was && (now.file !== was.file || now.branch !== was.branch)) }).map(d => d.n)
    const gone = criteria.filter(a => !plan.acceptance.some(b => b.id === a.id)).map(a => a.id)
    if (touched.length) failed = { invalid: plan, details: `the task revise dropped or changed the done task(s) ${touched.join(', ')} (number, file or branch)` }
    else if (gone.length) failed = { invalid: plan, details: `the task revise removed the criteria ${gone.join(', ')}; removing a criterion is an owner amend` }
  }
  if (failed) {
    plan = prior.plan
    reordered = prior.reordered
    priorFindings = prior.priorFindings
    planReviewed = true
    planFindingsKept = null
    // The decision reached the planner, which asked on: it is kept, so the resume with the answer shows the planner both.
    if (Array.isArray(failed.needs_user)) { blocked = { ...blocked, asked: true }; decisionPending = false }
    const said = Object.fromEntries(['needs_user', 'invalid', 'branch_problems', 'rules', 'details'].filter(k => own(failed, k)).map(k => [k, failed[k]]))
    return stop(Array.isArray(failed.needs_user) || own(failed, 'invalid') ? 'plan' : 'plan-review', { step: 'plan-task-revise', ...said })
  }
  log(`task ${t.n}: its task file was revised from the owner's decision`)
  blocked = null
  decisionPending = false
  // As after an applied amend: the plan changed, so no cached final review or verify stands.
  SKIP_REVIEW = false
  SKIP_FINAL = false
  VERIFY_CACHED = false
  verified = null
  finalReviewed = null
}
if (RESUME_RULES) {
  const { rules, findings, rounds } = planFindingsKept
  const noted = notedOn(planFindingsKept.noted, rules)
  const r = await rulesRevise(rules, noted)
  if (r.halted) return { ...r.halted, findings }
  if (r.silent) return reviewStop(rules, findings, rounds + 1, SILENT, noted)
  if (r.rules.length) return reviewStop(r.rules, findings, rounds + 1, r.extra, r.noted)
  planFindingsKept = null
  planReviewed = true
}
if (!planReviewed) {
  const ACS0 = JSON.stringify(plan.acceptance)
  const planCodexP = REVIEW_PLAN ? call(`${CTX}
Plan: ${plan.plan_root} (task files beside it). Acceptance criteria: ${ACS0}.${SPEC}
Run the project's configured independent plan review: the contract's workflow.review.plan is the command ${REVIEW_PLAN}. ${CX_USE} plan review over the plan at that path against issue #${ISSUE} in the worktree ${W}, giving it the code map ${CODE_MAP} as its code map input; ${CX_WAIT} Return Codex's Important or Critical findings as they are without adding your own review; verdict pass if none. ${CX_NONE}
${RULES}`, { label: 'plan-codex', phase: 'Plan', agentType: 'clerk', model: CLERK_MODEL, effort: 'high', schema: CODEX }) : Promise.resolve(null)
  const ruleFindings = planRules(plan)
  const narrow = REVIEW_SIZING && !!REVIEW_PLAN
  const planReviewClaude = await call(`${CTX}
Review the implementation plan at ${plan.plan_root} (and its task files) against issue #${ISSUE} (gh issue view ${ISSUE} --repo ${SLUG} --json title,body,comments).${SPEC} ${KNOW} ${MAP_FIRST} Report only Important or Critical defects: ${narrow ? PLAN_RUBRIC_SIZED : PLAN_RUBRIC}, or an acceptance criterion that breaks a rule of ~/.agents/standards/acceptance-planning.md (read it; put the broken rule's id in the finding's rule).${narrow ? ` ${PLAN_CODEX_OWNS}` : ''} No style notes. Do not edit anything.`, { label: 'plan-review', phase: 'Plan', agentType: 'reviewer', schema: PLAN_REVIEW })
  const planCodexR = await planCodexP
  if (!planReviewClaude) return stop('plan-review', { details: 'the plan reviewer returned nothing' })
  let planFindings = ruleFindings.concat(findingsOf(planReviewClaude))
  if (REVIEW_PLAN) {
    if (!planCodexR || !planCodexR.available) return codexStop('plan', planCodexR)
    planFindings = planFindings.concat(findingsOf(planCodexR).map(f => ({ ...f, source: 'codex' })))
    log(`codex plan review: ${findingsOf(planCodexR).length} blocking findings`)
  }
  if (planFindings.length) {
    log(`plan review: ${planFindings.length} blocking findings, revising once`)
    const reviewedFacts = ruleFacts(plan), reviewedCriteria = plan.acceptance
    const revised = await call(planPrompt(`\n${MAP_FIRST} A reviewer found these defects in your plan at ${plan.plan_root}; fix them in place and return the full result again, with criteria_edited: the ids of the criteria whose text you changed to fix a finding (typing the same criterion again in other words is not a change; an empty list when you changed none): ${JSON.stringify(planFindings)}`, REVISE_PACE), { label: 'plan-revise', phase: 'Plan', agentType: 'planner', schema: PLAN_SCHEMA })
    const unsettled = await settleRevise(revised, planFindings, reviewedFacts, reviewedCriteria)
    if (unsettled) return unsettled
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
const taskDone = n => taskLog.some(d => d.n === n)
const worktreeOf = t => { const b = typeof t.branch === 'string' ? declared(plan).find(d => d.name === t.branch) : null; return b ? b.worktree : W }
// #896: a blocked task that names a later task of the plan (blocked_on) is moved once to just after it, so every other task keeps its
// place. A plan declares no dependencies between tasks, only their order and each task's branch, so the move is refused, and the task
// stops with why, when the task was moved before, another moved task still waits, or the named task is not a later unfinished one or commits
// in another worktree. A task that needed the moved one blocks in its turn and stops there. No done task runs again.
const reorder = (i, impl) => {
  const t = plan.tasks[i]
  if (!impl || impl.status !== 'blocked') return {}
  const was = reordered.find(r => r.task === t.n)
  if (was) return { why: `blocked again after it was moved behind task ${was.after}` }
  if (!Number.isInteger(impl.blocked_on)) return {}
  const k = impl.blocked_on
  const waits = reordered.find(r => !taskDone(r.task))
  if (waits) return { why: `not moved behind task ${k}: task ${waits.task} still waits for task ${waits.after}` }
  const at = plan.tasks.findIndex((o, j) => j > i && o.n === k)
  if (at < 0 || taskDone(k)) return { why: `not moved: task ${k} is not a later unfinished task of the plan` }
  if (worktreeOf(plan.tasks[at]) !== worktreeOf(t)) return { why: `not moved: task ${k} commits in another worktree` }
  return { order: [...plan.tasks.slice(0, i), ...plan.tasks.slice(i + 1, at + 1), t, ...plan.tasks.slice(at + 1)], after: k }
}
for (let ti = 0; ti < plan.tasks.length; ti++) {
  const t = plan.tasks[ti]
  if (taskDone(t.n)) continue
  const moved = reordered.find(r => r.task === t.n)
  const waiting = reordered.find(r => r.task !== t.n && !taskDone(r.task))
  const first = !tasksRenewed
  tasksRenewed = true
  const B = typeof t.branch === 'string' ? declared(plan).find(b => b.name === t.branch) || null : null
  const TW = B ? B.worktree : W
  const start = `${CTX}\n${PLAN_REF}${B ? `\nTask ${t.n} commits to the declared branch ${B.name} in the worktree ${TW} (base ${B.base}), not to ${setup.branch}: run this task's commands there (git -C ${TW}).` : ''}`
  const PUSH_HERE = B ? ` After each commit, push it alone with git -C ${TW} push origin ${B.name}.` : ''
  const halt = (stage, extra) => haltTask(t.n, stage, extra)
  const WAITS = waiting ? ` Task ${waiting.task} waits for task ${waiting.after} and may have left uncommitted edits: ` : ''
  const KEEP_WAITING = waiting ? `${WAITS}leave them as they are.` : ''
  const implPrompt = `${first ? `${start}\n${RENEW_FIRST}\nThen implement` : `${start}\nImplement`} task ${t.n} (${t.title}) exactly as its task file ${t.file} specifies: write the failing test first and see it fail, implement, see it pass, run the task's focused test commands, then for each new test temporarily remove the code it pins and confirm it fails, restore, and commit only this task's files in the worktree. ${MAP_FIRST} ${FOCUSED} ${IMPL_RETURN}${PUSH_HERE} Return status blocked with notes if the task file is wrong or impossible, and blocked_on: the number of the later task of this plan it needs first, if that is why; when you name it, first undo every uncommitted edit you made, leaving the worktree as you found it.${KEEP_WAITING}${moved ? ` Task ${moved.after}, which this task was blocked on, is done now.` : ''}${(CONT && CONT.partial === t.n) || moved ? `
An earlier attempt at this task was cut off and may have left uncommitted edits or commits in the worktree (git -C ${TW} status, git -C ${TW} diff and git -C ${TW} log ${B ? `${B.base}..HEAD` : RANGE}). Inspect them: keep what matches the task file, finish or redo the rest, and make sure the failing-test-first and mutation checks still hold for the final result; start_head is ${moved ? 'HEAD as this attempt starts' : "the head before this task's first commit"}.` : ''}
${RULES}`
  const callImpl = () => call(implPrompt, { label: `impl-${t.n}`, phase: 'Tasks', agentType: 'implementer', model: 'sonnet', schema: first ? withRenew(IMPL) : IMPL })
  let impl = first ? await recall(callImpl, r => r.renew) : await callImpl()
  if (first && impl) {
    const lost = renewed(impl.renew, 'tasks')
    if (lost) return lost
  }
  if (!implDone(impl)) {
    const fix = reorder(ti, impl)
    if (!fix.order) return haltImpl(t.n, { task: t, impl, ...(fix.why ? { order: fix.why } : {}) })
    plan = { ...plan, tasks: fix.order }
    reordered = [...reordered, { task: t.n, after: fix.after, notes: typeof impl.notes === 'string' ? impl.notes.slice(0, REASON_MAX) : '' }]
    // Its edits, if any, stay claimed while the tasks before it run.
    partial = t.n
    log(`task ${t.n} is blocked on task ${fix.after}: moved to run just after it, once (order ${plan.tasks.map(o => o.n).join(', ')})`)
    ti--
    continue
  }
  // #923: a task that ends with no new commit (its output is not a file change: an issue comment, a check that needs no edit) has no
  // diff, and a review of the empty range head..head is refused as a missing diff boundary. Its first pass is a no-change check
  // instead: a reviewer judges from the task file whether the task needs a tracked file changed (then it is not done, and the finding
  // goes back to the implementer as any other) and confirms each required output itself. reviewer-lite reviews only a bounded diff,
  // so every review without one runs on reviewer, whatever the task's risk. Once such a task does commit (a fix round), that diff gets
  // the first pass a task diff always gets; a fix that answers with evidence and no commit is re-reviewed as a rebuttal, with no range.
  // Whether a reply added a commit is never taken from its own start_head: it is read against a head the program holds. For the
  // task, that is the head its worktree was accepted at: the tip this run tracks, or, for the task a stop left partial (the setup's
  // head then already holds the cut-off attempt's commits), the last done task of that worktree, else the worktree's base. A reply
  // whose commit is another head gets a diff review from the accepted head, whatever start it names (#923: a start above it would hide commits). For a fix, it is the head just reviewed.
  const lastDone = taskLog.filter(d => (B ? d.branch === B.name : !present(d.branch))).pop()
  const tracked = partial === t.n ? null : B ? branchTips[B.name] : tip
  const accepted = present(tracked) ? tracked : lastDone && present(lastDone.commit) ? lastDone.commit : B ? B.base : setup.base_sha
  // An honest reply starts at the accepted head and keeps its own spelling of it; any other start would hide the commits beneath it.
  const taskStart = sameSha(impl.start_head, accepted) ? impl.start_head : accepted
  const liteLane = t.risk === 'mechanical' || t.risk === 'low'
  // False until the task's diff had its first pass; a task with no commit has none to review.
  let diffReviewed = !sameSha(impl.commit, accepted)
  // #932: a no-change check names the head the program holds (the fuller spelling), never the reply's short or uppercase one.
  let held = diffReviewed ? impl.commit : fuller(accepted, impl.commit)
  // reviewer-lite first-passes only a task whose declared lane is mechanical or low (its lane verification mode).
  let reviewer = liteLane && diffReviewed ? 'reviewer-lite' : 'reviewer'
  const diffReview = (range, label, answers) => call(`${start}
${reviewer === 'reviewer-lite' ? `lane: ${t.risk}. ` : ''}Review the diff of task ${t.n} only: ${range} (and the task file ${t.file} as its contract). ${KNOW} Report Important or Critical correctness defects and unmet task requirements only, each with a concrete failing input. No style notes. Do not edit anything.${answers ? ` The task first ended with no commit, and this diff answers these findings: ${JSON.stringify(answers)}; report any still unresolved.` : ''}`, { label, phase: 'Tasks', agentType: reviewer, schema: FINDINGS })
  // Tracked files only: an untracked file (a build output, a tool's cache) is no edit of the task, and a waiting task's kept edits are not this task's.
  const HEAD_UNMOVED = h => `First confirm that git -C ${TW} rev-parse HEAD prints ${h} and git -C ${TW} status --porcelain --untracked-files=no prints nothing: another head or an uncommitted change to a tracked file is a finding.${waiting ? `${WAITS}those are not a finding.` : ''}`
  const CONFIRM = `with read-only commands that change nothing, the task file's own verification commands or a lookup (run a gh command as ${UNSET}gh ...)`
  let review = diffReviewed ? await diffReview(`git -C ${TW} diff ${taskStart}..${impl.commit}`, `review-${t.n}`) : await call(`${start}
Task ${t.n} ended with no new commit: the head of ${TW} is still ${held}. There is no diff to review and none is missing; do not ask for a range. Judge the task from its task file ${t.file} (the contract) and the implementer's report: notes: ${impl.notes}; checks run: ${JSON.stringify(Array.isArray(impl.tests) ? impl.tests : [])}. ${HEAD_UNMOVED(held)} Then decide two things. 1. Does the task file require a tracked file to be created, changed or deleted? If it does, the task is not done: report one Critical finding naming the files it requires. 2. If it requires none, is every output the task file asks for in place? Confirm each yourself, ${CONFIRM}; the implementer's word alone is not evidence, and an output you cannot confirm is a finding. Report Important or Critical findings only, each with what is missing. Do not edit anything.`, { label: `review-${t.n}`, phase: 'Tasks', agentType: 'reviewer', schema: FINDINGS })
  if (!review) return halt('task-review', { task: t, review: null })
  let rounds = 0
  while (findingsOf(review).length && rounds < 2) {
    rounds++
    const fix = await call(`${start}
Fix these review findings for task ${t.n} (${t.file}) in the worktree, with a regression test for each real defect, then commit: ${JSON.stringify(findingsOf(review))}. If a finding is wrong, say so in notes with evidence instead of changing code. ${MAP_FIRST} ${FOCUSED} ${COMMIT_SCOPE} ${IMPL_RETURN}${PUSH_HERE}${KEEP_WAITING}
${RULES}`, { label: `fix-${t.n}-${rounds}`, phase: 'Tasks', agentType: 'implementer', model: 'sonnet', schema: IMPL })
    if (!implDone(fix)) return halt('task-fix', { task: t, impl: fix })
    // The head the last review saw: the fix added a commit only when its commit is another one.
    const reviewed = impl.commit
    impl = fix
    held = sameSha(fix.commit, reviewed) ? fuller(held, fix.commit) : fix.commit
    const label = `rereview-${t.n}-${rounds}`
    if (sameSha(fix.commit, reviewed)) {
      review = await call(`${start}
Re-review only these previously reported findings for task ${t.n} against the implementer's answer. The fix made no new commit (the head of ${TW} is still ${held}), so there is no fix diff to review and none is missing; do not ask for a range. The implementer's notes: ${fix.notes}. Findings: ${JSON.stringify(findingsOf(review))}. ${HEAD_UNMOVED(held)} Then check each answer yourself against the task file ${t.file}${diffReviewed ? `, the task's diff (git -C ${TW} diff ${taskStart}..${fix.commit})` : ''} and the evidence the notes name, ${CONFIRM}; a finding the evidence does not refute is still unresolved. Report any finding still unresolved. Do not edit anything.`, { label, phase: 'Tasks', agentType: 'reviewer', schema: FINDINGS })
    } else if (!diffReviewed) {
      reviewer = liteLane ? 'reviewer-lite' : 'reviewer'
      review = await diffReview(`git -C ${TW} diff ${taskStart}..${fix.commit}`, label, findingsOf(review))
      diffReviewed = true
    } else {
      review = await call(`${start}
Re-review only these previously reported findings for task ${t.n} against the fix: git -C ${TW} diff ${reviewed}..${fix.commit}; the implementer's notes: ${fix.notes}. Findings: ${JSON.stringify(findingsOf(review))}. Report any finding still unresolved and any new Important or Critical defect the fix introduced.`, { label, phase: 'Tasks', agentType: 'reviewer-lite', schema: FINDINGS })
    }
    if (!review) return halt('task-review', { task: t, review: null })
  }
  if (findingsOf(review).length) return halt('task-review', { task: t, review })
  taskLog.push({ n: t.n, commit: impl.commit, review_rounds: rounds, reviewer, ...(B ? { branch: B.name } : {}), ...(diffReviewed ? {} : { no_change: true }) })
  if (B) branchTips[B.name] = impl.commit
  else tip = impl.commit
  if (partial === t.n) partial = undefined
}
// #923: when every task ended with no commit, the branch holds nothing to review, verify or land: the final review would get an
// empty range and the pull request no commit. Read from the done record (no_change), which a resume carries, never from a head. The tasks' outputs are in place and recorded; the owner closes the issue.
if (plan.tasks.length && plan.tasks.every(t => taskLog.some(d => d.n === t.n && d.no_change === true))) {
  return stop('no-changes', { details: `every task ended with no commit: the branch ${setup.branch} holds nothing to review or land. The tasks' outputs are in place; close the issue by hand, or amend the plan if a file change was meant` })
}

// ---------------- Final review ----------------
phase('Final review')
// #747: with review_sizing on, a delivery of more tasks than one chunk holds is split for review only above this many changed lines.
const SIZED_CHUNK_LINES = 1500
let groups = []
let sizedWhole = false
const PER = 3
for (let i = 0; i < plan.tasks.length; i += PER) groups.push(plan.tasks.slice(i, i + PER))
chunked = groups.length > 1
// A resume that skips the final review reports the shape it had (#747).
if ((SKIP_REVIEW || SKIP_FINAL) && finalReviewed && finalReviewed.whole === true) chunked = false
if (SKIP_FINAL) log(`final review passed at ${finalReviewed.head}; skipped`)
if (!SKIP_REVIEW && !SKIP_FINAL) {
{
  const lost = await renew('final-review', 'Final review')
  if (lost) return lost
}
if (REVIEW_SIZING && chunked) {
  let sizeReply = null
  let sizeWhy = 'no usable reply'
  try {
    // optional call: a failed measurement is recovered here and must not be reported as a dead agent (deliver-batch's breaker reads those).
    sizeReply = await call(`${CTX}
Measure the delivery's diff size. Run git -C ${W} fetch origin, then git -C ${W} diff --shortstat ${RANGE}${declared(plan).map(b => `, then git -C ${b.worktree} diff --shortstat ${b.base}...${b.name}`).join('')}. Each prints at most one line (N files changed, X insertions(+), Y deletions(-)); an empty output or a missing count is 0. Return measured true and changed_lines: the sum of the insertions and deletions over those lines. If any of these commands exits non-zero or prints an error, return measured false and no changed_lines; never return a partial sum. Run nothing else and change nothing.
${RULES}`, { label: 'diff-size', phase: 'Final review', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: SIZE_SCHEMA }, true)
  } catch (e) {
    // The measurement is optional: an agent exception must never abort the delivery.
    sizeReply = null
    sizeWhy = `the size step threw: ${e && e.message}`
  }
  const lines = sizeReply && typeof sizeReply === 'object' && sizeReply.measured === true && Number.isInteger(sizeReply.changed_lines) && sizeReply.changed_lines >= 0 ? sizeReply.changed_lines : null
  if (lines === null) log(`final review size not read (${sizeWhy}); keeping the task chunks`)
  else if (lines <= SIZED_CHUNK_LINES) {
    groups = [plan.tasks.slice()]
    chunked = false
    sizedWhole = true
    log(`final review: ${lines} changed lines, at most ${SIZED_CHUNK_LINES}; one whole-delivery review`)
  } else log(`final review: ${lines} changed lines, above ${SIZED_CHUNK_LINES}; keeping the task chunks`)
}
const codexP = REVIEW_CODE ? call(`${CTX}
${PLAN_REF} Acceptance criteria: ${ACS}.
Run the project's configured independent code review: the contract's workflow.review.code is the command ${REVIEW_CODE}. ${CX_USE} diff review over the delivery range ${RANGE} in the worktree ${W}, with no review package;${EXTRA_RANGES()} ${CX_WAIT} Return Codex's Important or Critical findings as they are (correctness defects with a concrete failing input, unmet criteria) without adding your own review; verdict pass if none. ${CX_NONE}
${RULES}`, { label: 'final-codex', phase: 'Final review', agentType: 'clerk', model: CLERK_MODEL, effort: 'high', schema: CODEX }) : Promise.resolve(null)
// #993: shared by the chunk and the integration review.
const VERIFY_OWNED = `The verify step runs the declared verification: run only the targeted tests a finding needs, never the whole suite.`
const finals = await parallel(groups.map((g, gi) => () => call(`${CTX}
${PLAN_REF} Acceptance criteria: ${ACS}.
Final review${chunked ? ` of chunk ${gi + 1}/${groups.length}: tasks ${g.map(t => t.n).join(', ')} only (their files: ${g.map(t => t.file).join(', ')}); grade only these tasks` : ' of the whole delivery'}: git -C ${W} diff ${RANGE}${chunked ? ' restricted to the paths these tasks own' : ''}.${EXTRA_RANGES()} ${KNOW} Two axes: correctness (real defects with a concrete failing input) and conformance (each task and each acceptance criterion of kind code is met, with the test or command that shows it). ${VERIFY_OWNED} Report Important or Critical findings only. Do not edit anything.`, { label: `final-${gi + 1}`, phase: 'Final review', agentType: 'reviewer', schema: FINDINGS })))
if (finals.some(r => !r)) {
  await codexP
  return stop('final-review', { details: 'a final reviewer returned nothing', finals })
}
// #967: the integration review reads only the chunk verdicts, so it runs beside Codex. It counts as dead only where its reply is read:
// a Codex stop leaves it unused, and still running unread, on purpose: waiting for it would cost wall time for nothing.
const integP = chunked ? call(`${CTX}
${PLAN_REF} Integration review. The delivery was reviewed in ${groups.length} chunks by task; their verdicts: ${JSON.stringify(finals)}. Read the full changed-file list (git -C ${W} diff --stat ${RANGE}) and the head tree as needed.${EXTRA_RANGES()} ${KNOW} Check the interfaces between chunks and grade every acceptance criterion: ${ACS}. ${VERIFY_OWNED} Report Important or Critical findings only.`, { label: 'final-integration', phase: 'Final review', agentType: 'reviewer', schema: FINDINGS }, true) : null
if (integP) integP.catch(() => {})
const codexR = await codexP
let finalFindings = finals.flatMap(findingsOf)
if (REVIEW_CODE) {
  if (!codexR || !codexR.available) return codexStop('code', codexR)
  finalFindings = finalFindings.concat(findingsOf(codexR).map(f => ({ ...f, source: 'codex' })))
  log(`codex review: ${findingsOf(codexR).length} blocking findings`)
}
if (integP) {
  const integ = await integP
  if (!integ) {
    DEAD.push('final-integration')
    return stop('final-review', { details: 'the integration reviewer returned nothing' })
  }
  finalFindings = finalFindings.concat(findingsOf(integ))
}
// #924: what an earlier fix-wave-review stop left open joins the fresh findings, a repeat (same file and summary) once.
const fromStop = carried.filter(c => !finalFindings.some(f => findingKey(f) === findingKey(c)))
if (fromStop.length) log(`final review: ${fromStop.length} finding(s) carried from the earlier fix-wave-review stop`)
finalFindings = finalFindings.concat(fromStop)
if (finalFindings.length) {
  // At most MAX_WAVES waves. The second runs only when the first re-review's findings all narrow the first round (same kind of defect on
  // another path); a new kind stops. The third (#924) runs only when the second re-review's findings all narrow, all are important
  // (none critical, none without a severity) and they are no more than the first re-review left. #950: a finding that is not marked
  // narrowing (new, or with no relation: unknown is new) counts as narrowing in both admissions when its file is one the wave just
  // re-reviewed changed, a regression inside the fix's own diff; with no file, or in a file the fix left alone, it stops as before.
  const MAX_WAVES = 3
  let waveFindings = finalFindings
  let afterFirst = 0
  let regressions = 0
  const hasBranches = declared(plan).length > 0
  for (let k = 1; k <= MAX_WAVES; k++) {
    const fwLabel = k === 1 ? 'fix-wave' : `fix-wave-${k}`
    const rvLabel = k === 1 ? 'fix-wave-review' : `fix-wave-review-${k}`
    log(`final review: ${waveFindings.length} blocking findings, fix wave ${k}`)
    fixWaves++
    const fw = await call(`${CTX}\n${PLAN_REF} Fix these final-review findings, each real defect with a regression test, then commit: ${JSON.stringify(waveFindings)}.${k === 1 && fromStop.length ? ` The last ${fromStop.length} were left open by an earlier run's fix waves and may repeat the ones before them: check each against the current head, and explain one that no longer holds in notes; when you commit nothing, return commit equal to start_head.` : ''}${k >= 2 ? ` They ${regressions ? 'follow the fix of' : 'narrow'} these first-round findings${regressions ? ' (any not marked narrowing is a defect in a file the previous fix wave changed)' : ''}: ${JSON.stringify(finalFindings)}.` : ''}${k === 3 ? ' Fix the class of defect: enumerate every path of the same kind as each reported one and close them all, not only the reported instance.' : ''} If a finding is wrong, explain with evidence in notes. ${OWN_TESTS} ${COMMIT_SCOPE} ${hasBranches ? IMPL_RETURN_AT(W) : IMPL_RETURN} Also return changed_files: the output lines of ${CHANGED_CMD('<start_head>..<commit>')}, run alone after your last commit.${hasBranches ? ` A finding on a declared branch is fixed in that branch's worktree and pushed with its push form. Return branch_heads: one {name, head} per declared branch (${declared(plan).map(b => b.name).join(', ')}), head being git -C <its worktree> rev-parse HEAD after your last commit.` : ''}\n${RULES}`, { label: fwLabel, phase: 'Final review', agentType: 'implementer', model: 'sonnet', schema: withChanged(hasBranches ? FIX_WAVE_IMPL : IMPL) })
    // The carried findings outlive only a wave that gave no reply: one that answered and failed has had them, and the resume's fresh review decides.
    const spent = details => {
      if (fw && carried.length) { log(`fix-wave: ${carried.length} carried finding(s) dropped after a wave that answered and failed`); carried = [] }
      return stop('fix-wave', { fw, finalFindings: waveFindings, fix_waves: fixWaves, ...(details ? { details } : {}) })
    }
    if (!implDone(fw)) return spent()
    const collected = []
    for (const b of declared(plan)) {
      const h = headOf(fw.branch_heads, b.name)
      if (!h) return spent(`no head for the declared branch ${b.name}`)
      if (!sameSha(h, branchTips[b.name])) collected.push(`git -C ${b.worktree} diff ${branchTips[b.name]}..${h}`)
      branchTips[b.name] = h
    }
    tip = fw.commit
    // A wave that had carried findings and committed nothing found them closed already: its re-review reads the head, with no diff range.
    const idle = k === 1 && fromStop.length > 0 && sameSha(fw.commit, fw.start_head) && !collected.length
    if (!idle) carried = []
    const rv = await call(`${CTX}\nRe-review these findings against ${idle ? `the current head of ${W}${hasBranches ? ` and of each declared branch's worktree (${declared(plan).map(b => `${b.name} in ${b.worktree}`).join(', ')})` : ''} (the fix wave committed nothing, so there is no diff to read). Nothing changed since these were raised, so each finding stands unless the code at the head shows it does not hold. The notes are the implementer's claims: check each against the code and never clear a finding on the notes alone` : `the fix (${span(fw)}${collected.length ? ` and ${collected.join(' and ')}` : ''})`}; notes: ${fw.notes}. Findings: ${JSON.stringify(waveFindings)}.${k === 1 && fromStop.length && !idle ? ` The last ${fromStop.length} were left open by an earlier run and may repeat the ones before them: check each against the head, not only the diff.` : ''} Report any still unresolved and any new Important or Critical defect, setting relation on each finding you still report: narrowing when it is the same kind of defect as one above, reached on another path, input or call site; else new. Unsure is new.${idle ? '' : ` Also return changed_files: the output lines of ${CHANGED_CMD(`${fw.start_head}..${fw.commit}`)}, run alone.`}`, { label: rvLabel, phase: 'Final review', agentType: 'reviewer', schema: withChanged(FINDINGS) })
    if (!rv) return stop('fix-wave-review', { rv, fix_waves: fixWaves })
    carried = []
    const next = findingsOf(rv)
    if (!next.length) break
    const inFix = changedBy(fw).filter(p => changedBy(rv).includes(p))
    const fresh = next.filter(f => f.relation !== 'narrowing')
    const narrow = fresh.every(f => fileOf(f) && inFix.includes(fileOf(f)))
    // A wave that committed nothing earns no further wave: what its re-review still holds stops.
    const again = k === 1 ? narrow && !idle : k === 2 && narrow && next.every(f => f.severity === 'important') && next.length <= afterFirst
    if (!again) {
      carried = carryOf(next)
      if (carried.length < next.length) log(`fix-wave-review: ${next.length - carried.length} of ${next.length} open finding(s) not carried in cont`)
      const diverging = divergingOf(carried)
      if (diverging) log(`fix-wave-review: the fix waves do not converge on ${diverging.file} after ${diverging.waves} waves`)
      return stop('fix-wave-review', { rv, fix_waves: fixWaves, ...(diverging ? { diverging } : {}) })
    }
    if (k === 1) afterFirst = next.length
    regressions = fresh.length
    if (fresh.length) log(`fix-wave-review: ${fresh.length} finding(s) not marked narrowing are in files fix wave ${k} changed; they get the next wave`)
    waveFindings = next
  }
}
if (present(tip)) finalReviewed = { head: tip, ...branchSnap(), ...(sizedWhole ? { whole: true } : {}) }
}
}

// ---------------- Verify ----------------
phase('Verify')
const VERIFY = {
  type: 'object',
  properties: { head: FULL_SHA, clean: { type: 'boolean' }, results: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, status: { type: 'string', enum: ['pass', 'fail', 'skipped'] }, summary: { type: 'string' }, outside_diff: { type: 'boolean' } }, required: ['id', 'status', 'summary'] } } },
  required: ['head', 'clean', 'results'],
}
const verifyBodyFor = entries => `Run the project's declared verification once on the worktree head, in the foreground, each command with a Bash timeout of up to 60 minutes: ${JSON.stringify(entries)}. Run each argv with <worktree>/<its cwd> as working directory. If an entry has when_changed globs and none of the files changed (git -C ${W} diff --no-renames --name-only ${RANGE}, so a rename lists both paths) match, mark it skipped with its skip_reason. Return head (git -C ${W} rev-parse HEAD, the full sha), clean (git -C ${W} status --porcelain is empty, checked before and after the runs) and one result per id; for failures, summarize the failing tests or errors precisely. On each failure also return outside_diff: true only when no failing test file and no erroring file is in that git diff --name-only list, else false. Do not change any file.
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
const wsAsk = ws => ` The fix changes only whitespace amounts and blank lines, in ${ws.changed_paths.map(p => p.trim()).join(', ')}. Also judge whether each of its whitespace changes is insignificant: outside every string, template, character and regex literal, heredoc and raw block, and in no construct where whitespace changes behaviour or output. Return whitespace_insignificant true only when you read every hunk and that holds, with whitespace_evidence naming each changed path and why it holds there; otherwise false, with whitespace_evidence naming the hunk where it matters.`
// #972: a failure the clerk places wholly outside the branch's changed files is rerun once, the failed ids only, before any fix step.
// The rerun is each failed id's whole command, never a selection of its tests: a test the branch made order-dependent passes alone, and
// a selection that matches nothing passes too.
// A result that passes there is a pass that keeps the first failure as flaky; one that fails again stays the first failure.
// Each verification gets at most this one rerun, and its reply counts only at the same clean head.
const flakySeen = []
// True when the last verification's one rerun ran at the same clean head and a failed id did not pass there: the failure is not a flake.
let rerunFailed = false
const noteFlaky = rs => { for (const r of Array.isArray(rs) ? rs : []) if (isEntry(r) && present(r.flaky) && !flakySeen.some(f => f.id === r.id && f.summary === r.flaky)) flakySeen.push({ id: r.id, summary: r.flaky }) }
const rerunOnce = async (v, n) => {
  rerunFailed = false
  if (!v || !v.clean || !Array.isArray(v.results)) return v
  const fails = verifyProblems(v)
  if (!fails.length || !fails.every(p => p.status === 'fail' && p.outside_diff === true && VERIFY_IDS.includes(p.id))) return v
  const ids = fails.map(p => p.id)
  log(`verify: ${ids.join(', ')} failed outside the branch's changed files; one rerun before any fix`)
  const again = await call(`${CTX}\nThe verification at ${v.head} failed, outside the files this branch changed: ${JSON.stringify(fails.map(p => ({ id: p.id, summary: p.summary })))}. Rerun each failed command below once, whole and exactly as declared, and never a second time, whatever the outcome.\n${verifyBodyFor(setup.verification.filter(e => ids.includes(e.id)))}`, { label: `verify-rerun-${n}`, phase: 'Verify', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: VERIFY })
  if (!complete(again, VERIFY) || !again.clean || !Array.isArray(again.results) || !sameSha(again.head, v.head)) return v
  const passed = id => { const rs = again.results.filter(r => r.id === id); return rs.length === 1 && rs[0].status === 'pass' ? rs[0] : null }
  rerunFailed = ids.some(id => !passed(id))
  const results = v.results.map(r => (ids.includes(r.id) && passed(r.id) ? { id: r.id, status: 'pass', summary: passed(r.id).summary, flaky: r.summary } : r))
  for (const r of results) if (ids.includes(r.id) && present(r.flaky)) log(`verify: flaky, ${r.id} failed and passed on the one rerun: ${r.flaky}`)
  noteFlaky(results)
  return { ...v, results }
}
const FIX_OR_UNRELATED = { ...IMPL, properties: { ...IMPL.properties, outside_diff: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, why: { type: 'string' } }, required: ['file', 'why'] } }, unrelated: { type: 'object', properties: { test: { type: 'string' }, evidence: { type: 'string' } }, required: ['test', 'evidence'] } } }
let verify = VERIFY_CACHED ? { head: verified.head, clean: true, results: verified.results } : null
if (VERIFY_CACHED) noteFlaky(verified.results)
if (!VERIFY_CACHED) {
verify = await recall(() => call(verifyFirst, { label: 'verify', phase: 'Verify', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: withRenew(VERIFY) }), r => r.renew)
if (verify) {
  const lost = renewed(verify.renew, 'verify')
  if (lost) return lost
  if (!complete(verify, VERIFY)) verify = null
}
verify = await rerunOnce(verify, 1)
let vRounds = 0
while (verify && verifyProblems(verify).length && vRounds < 2) {
  vRounds++
  const fix = await call(`${CTX}\n${PLAN_REF} The project's verification failed: ${JSON.stringify(verifyProblems(verify).map(p => ({ id: p.id, status: p.status, summary: p.summary })))}.${rerunFailed ? ' It failed again on the one rerun at the same head, so it is not flaky.' : ''} Find the cause in this branch's changes (git -C ${W} diff ${RANGE}), fix it with the smallest change, commit. Never weaken, skip or delete a test to make it pass. When what fails lies outside that diff, first establish with evidence why it fails here: this branch's change, or this delivery's environment (the worktree path, the branch name). Only with that cause shown may you edit a file outside the diff, and then return outside_diff: [{file, why}], one entry per such file with the cause. With no cause established (it fails without this branch${rerunFailed ? '' : ', or it is flaky'}), change and commit nothing and return status blocked with unrelated {test, evidence}, evidence being what you ran or read: establish it by reading, or by running the test, never by checking out another commit in the worktree. ${OWN_TESTS} ${COMMIT_SCOPE} ${IMPL_RETURN}\n${RULES}`, { label: `verify-fix-${vRounds}`, phase: 'Verify', agentType: 'implementer', model: 'sonnet', schema: FIX_OR_UNRELATED })
  // #972: a failure for which the fix step can establish no cause here (the branch's change or the delivery's environment) is not edited
  // green: the delivery stops naming the test, and nothing ships. A fix outside the diff with a stated cause goes on, flagged (outsideFixes).
  if (fix && isEntry(fix.unrelated) && present(fix.unrelated.test) && present(fix.unrelated.evidence)) {
    const stray = present(fix.commit) && present(fix.start_head) && !sameSha(fix.commit, fix.start_head) ? fix.commit : null
    return stop('verify-unrelated', { details: `${String(fix.unrelated.test).slice(0, 120)} fails outside this branch's diff, so ${stray ? `it is not shipped (the fix step still committed ${stray}, unreviewed)` : 'no fix was made'}: ${fix.unrelated.evidence}`, unrelated: { test: fix.unrelated.test, evidence: fix.unrelated.evidence }, ...(stray ? { commit: stray } : {}), verify })
  }
  if (!implDone(fix)) return stop('verify-fix', { verify, fix })
  const outside = outsideOf(fix.outside_diff)
  for (const o of outside) { if (!outsideFixes.some(x => x.file === o.file && x.why === o.why)) outsideFixes.push(o); log(`verify-fix-${vRounds}: edited ${o.file}, outside the branch's diff: ${o.why}`) }
  const pre = rerunIds(verify, fix)
  const ws = pre ? await call(wsCheckPrompt(fix), { label: `ws-check-${vRounds}`, phase: 'Verify', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: WS_CHECK }) : null
  const asked = pre && wsOnly(ws) ? pre : null
  const fr = await call(`${CTX}\nReview this verification fix: ${span(fix)}; the failure it answers: ${JSON.stringify(verifyProblems(verify))}; notes: ${fix.notes}. Report Important or Critical defects only, above all a weakened, skipped or deleted test or check.${outside.length ? ` It edits files outside the branch's diff, each for a stated cause: ${JSON.stringify(outside)}; a cause the code or the failure does not bear out is an Important defect.` : ''}${asked ? wsAsk(ws) : ''}`, { label: `verify-fix-review-${vRounds}`, phase: 'Verify', agentType: 'reviewer', schema: asked ? WS_REVIEW : FINDINGS })
  if (!fr || findingsOf(fr).length) return stop('verify-fix-review', { review: fr })
  const rerun = asked && attested(fr) ? asked : null
  const next = await call(rerun ? `${CTX}\nA whitespace-only fix followed the verification at ${verify.head}; the declared ids not listed below passed there and are carried forward, so run only the listed ones.\n${verifyBodyFor(setup.verification.filter(e => rerun.includes(e.id)))}` : verifyPrompt, { label: `verify-${vRounds + 1}`, phase: 'Verify', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: VERIFY })
  if (rerun && next && !sameSha(next.head, fix.commit)) return stop('verify', { verify: next, problems: [{ id: '?', summary: `the narrowed verification ran at ${next.head}, not at the whitespace-only fix ${fix.commit}, so no result was carried` }] })
  verify = await rerunOnce(rerun && next && Array.isArray(next.results) ? carry(verify, next, rerun) : next, vRounds + 1)
}
}
if (verifyProblems(verify).length) return stop('verify', { verify, problems: verifyProblems(verify) })
if (MODE === 'ready') {
  verified = { head: verify.head, results: verify.results, contract: VERIFY_CONTRACT, ...branchSnap() }
  return stop('ready', { head: verify.head, branch: setup.branch, worktree: W, verify: verify.results, ...(flakySeen.length ? { flaky: flakySeen } : {}), ...(outsideFixes.length ? { outside_fixes: outsideFixes } : {}), tasks: taskLog, ...(reordered.length ? { reordered } : {}), acceptance: plan.acceptance, fix_waves: fixWaves })
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
const PUSH_SCHEMA = { type: 'object', properties: { head: FULL_SHA, notes: { type: 'string' } }, required: ['head'] }
const CHECKS_WAIT = pr => `for PR #${pr} to be mergeable. 1. git -C ${W} fetch origin; if the local branch is ahead of origin/${setup.branch}, push it. head is git -C ${W} rev-parse HEAD (full sha). 2. If origin/${INT} is not an ancestor of HEAD (git -C ${W} merge-base --is-ancestor origin/${INT} HEAD fails), return state behind at once. 3. Otherwise wait in this turn until every check on head has completed, required or not. List every check with gh pr checks ${pr} --repo ${SLUG} --json name,bucket,link (never --required) and wait with gh pr checks ${pr} --repo ${SLUG} --watch (Bash timeout up to 60 minutes; rerun while any is pending). It can return early and a list can be partial: never treat a partial list as green, and read the list again before you answer. Bucket pass has passed; fail or cancel has failed; pending is still running; skipping never started and is ignored. Report as required the required check names from gh api repos/${SLUG}/rules/branches/${INT} (its required_status_checks rules) or else classic branch protection, none when neither answers. Return passed only when no check on head is pending, failing or cancelled, with required and passed (the names passing at head). Return failed when any check failed, required or not, with failing (every failing or cancelled name) and details (for each failing check, the last 60 lines of its failed log: gh run view <run id> --repo ${SLUG} --log-failed). Return pending with pending (the names still running) only when the wait ran out and no check failed.`
const SYNC = { type: 'object', properties: { status: { type: 'string', enum: ['done', 'conflicted', 'blocked'] }, conflicted: { type: 'boolean' }, merge_commit: FULL_SHA, head: FULL_SHA, resolved_files: STRS, markers_checked: { type: 'boolean' }, tests: STRS, notes: { type: 'string' } }, required: ['status', 'conflicted', 'notes'] }
const LOCK_SCHEMA = {
  type: 'object',
  properties: { verdict: { type: 'string', enum: ['acquired', 'already_held', 'moved', 'held_by', 'lost_to', 'land-contended', 'error'] }, lock_sha: { type: 'string' }, pr: { type: 'integer' }, by: { type: 'string' }, detail: { type: 'string' }, waited_s: { type: 'integer' }, waited_on: { type: 'array', items: { type: 'integer' } } },
  required: ['verdict'],
}
// #913: a wait for the land lock of this many seconds or more is logged with the pull requests it waited on (forge-claim's waited_on).
const LOCK_WAIT_LOG_S = 300
const logWait = (label, lock) => {
  if (!lock || !(lock.waited_s >= LOCK_WAIT_LOG_S)) return
  const on = Array.isArray(lock.waited_on) ? lock.waited_on : []
  log(`${label}: waited ${Math.round(lock.waited_s / 60)} min for the land lock of ${INT}${on.length ? ` behind PR ${on.map(p => `#${p}`).join(', ')}` : ''}`)
}
// #941: the probe a landing runs before it asks for the land lock, the same text in deliver-batch.js. git merge-tree --write-tree (git 2.38
// or later) merges in memory: it writes no commit and touches neither the worktree nor the index, and its exit status alone says whether
// the merge is clean (0, a head that is already current included) or conflicts (1). It also exits 1, with nothing on stdout, when a ref
// is missing, so a conflict is exit 1 with the merged tree's id as the first line of output; the program checks that id itself. Anything
// else proves nothing, so it reads as not conflicted and the landing goes on as it did before the probe existed: the sync under the lock
// then finds the conflict (#913).
const PROBE = (wt, int) => `before any lock command, probe whether ${int} merges cleanly into the pushed head, changing nothing: run git -C ${wt} fetch origin, then alone and exactly: git -C ${wt} merge-tree --write-tree --name-only --no-messages HEAD origin/${int}
Only its exit status and the first line of its output count: exit 0 is a clean merge; exit 1 is a conflict only when the first line of its output is a tree id (40 hexadecimal characters), and the conflicting files follow that line. Exit 1 with any other output (a missing ref prints nothing there) and every other exit are errors, not conflicts. It commits nothing and touches neither the worktree nor the index; never run git merge in this step. Return it as probe: conflicted (true only for that conflict), tree (the first line of the output, exactly as printed, when exit is 1), files (the conflicting files) and, on an error, conflicted false with the error in detail.
When probe's conflicted is true, run no lock command and wait for no check: return lock null and checks null, because a later step resolves the conflict before the lock is asked for.`
const PROBE_SCHEMA = { type: 'object', properties: { conflicted: { type: 'boolean' }, tree: { type: 'string' }, files: STRS, detail: { type: 'string' } }, required: ['conflicted'] }
// A probe reply that proves a conflict: exit 1 alone does not, the tree id does.
const probeConflict = p => !!p && typeof p === 'object' && p.conflicted === true && typeof p.tree === 'string' && /^[0-9a-f]{40}$/.test(p.tree.trim())
let PR = null
let expected = verify.head
let head = expected
let syncs = 0
let round = 0
const PENDING_WAITS = 3
// #818: the extra waits a landing spends on the land lock after its first acquire --wait answered land-contended at the CLI's own bound.
const LAND_WAIT_RETRIES = 3
let pendingWaits = 0
let mg = null
let mergeRefusals = 0
let raced = false
let contended = 0
// True after a rerun of failed jobs at an unchanged head, until the poll that follows it answered (#986).
let reran = false
// The cross-host land lock of the integration branch (#677): taken with --wait right after the PR opens, before any sync,
// moved with a one-shot acquire after every head change, re-checked once before the merge, released after the merge and on every stop;
// a conflicted sync merge releases it and its accepted resolution takes it again, waiting (lockOut below, #913).
// lockSha is the last sha this run owned or may own: set before the pr call, whose lock may be taken before its reply is lost, then after each holding verdict to the head that acquire named.
let lockHeld = false
let lockSha = null
// The sha a move acquire may have left held when its answer was lost (#716); cleared by a definitive answer.
let lockMaybe = null
// #913: true from the release of the lock for a conflicted sync merge until the reviewed head takes it again. The sync step runs under the
// lock and only merges cleanly: a merge that conflicts is aborted there, the lock is released, and the resolution, its tests, its review and
// its fix wave run outside it. The next round pushes the accepted head and takes the lock again with --wait in its checks call, whose poll
// answers behind when the integration branch moved meanwhile: the loop then syncs again, a clean merge under the lock and a conflicted one
// outside it once more, within the sync bounds below (sync-contention, the merge refusal budget). A stop in between holds no lock.
let lockOut = false
// #941: true while lockOut stands for a conflict the probe found before the lock was ever asked for: the take is then the landing's first.
let lockFirst = false
let relocks = 0
let retakes = 0
const HOLDING = ['acquired', 'already_held', 'moved']
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
${lockMaybe && !sameSha(lockMaybe, lockSha) ? RELEASE_AGAIN(lockMaybe) : ''}${RULES}`, { label: 'land-unlock', phase: 'Ship', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'low', schema: RELEASE_SCHEMA })
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
// With rerun (the CI fix alone, #818), done at the unchanged head is a rerun of jobs that failed for no cause in the code: { fix, ok: true, rerun: true }, with no review.
const shipFix = async ({ label, reviewLabel, fixPrompt, reviewPrompt, rebuttal = false, rerun = false }) => {
  const fix = await call(fixPrompt, { label, phase: 'Ship', agentType: 'implementer', model: 'sonnet', schema: IMPL })
  if (!implDone(fix) || !sameSha(fix.start_head, expected)) return { fix, ok: false }
  const moved = !sameSha(fix.commit, expected)
  if (!moved && rerun) return { fix, ok: true, rerun: true, moved }
  if (!moved && !(rebuttal && present(fix.notes))) return { fix, ok: false }
  const review = await call(reviewPrompt(fix, moved), { label: reviewLabel, phase: 'Ship', agentType: 'reviewer', schema: FINDINGS })
  return { fix, review, moved, ok: true }
}
const landBody = async () => {
  // The pr call may take the lock (--wait) after opening the PR: mark the verified head as possibly held before it, so a lost reply still reaches the release.
  lockHeld = true
  lockSha = expected
  const prR = await recall(() => call(`${CTX}
${RENEW_FIRST}
Then open the pull request for this branch. Push the branch (git -C ${W} push origin ${setup.branch}). If an open PR with head ${setup.branch} already exists (a resumed delivery), reuse it; else open one against ${INT}. Title: a short summary of the issue. Body, plain prose, no single or double quotes, dollar signs, backticks or backslashes: sections Why, What changes, Acceptance (a table with one row per criterion: id, criterion, kind, and the test or command that shows it; criteria ${ACS}), Evidence (verification ${JSON.stringify(verify.results)}${outsideFixes.length ? `; verification fixes outside the branch's diff, each with its cause: ${JSON.stringify(outsideFixes)}` : ''}; ${taskLog.length} tasks reviewed; ${LANE === 'direct' ? 'direct-lane review' : 'final review ' + (chunked ? 'chunked' : 'whole')}${REVIEW_CODE ? ' plus the configured independent review' : ''}), Merge danger; then the line ${closesLine} as the last line, with no attribution or generated-by line. Never attach or link the plan or the spec. Return pr (number) and head (full sha of the pushed head).
Then, ${PROBE(W, INT)}
Otherwise take the cross-host landing lock of the branch ${INT} for that PR at the verified head ${expected}: run alone and exactly: ${LAND_ACQUIRE(expected, true)}
${LOCK_RETURN} Return it as lock; when no PR was opened or reused, run neither the probe nor a lock command and return probe null and lock null. Then, only when lock's verdict is acquired, already_held or moved and the pushed head is ${expected}, wait ${CHECKS_WAIT('<the PR number>')} Return those fields as checks; otherwise run nothing more and return checks null.
${RULES}`, { label: 'pr', phase: 'Ship', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'high', schema: withRenew(PR_SCHEMA, { probe: NULLABLE(PROBE_SCHEMA), lock: NULLABLE(LOCK_SCHEMA), checks: NULLABLE(CHECKS) }) }), r => r.renew)
  if (!prR) return stop('pr', { result: null })
  // #941: the probe found a conflict, so the call ran no lock command: nothing is held and nothing was waited for. A reply that names a
  // lock verdict all the same, or no tree id, is read as before the probe existed (the sync under the lock finds the conflict, #913).
  const early = probeConflict(prR.probe) && !prR.lock ? prR.probe : null
  if (early) lockHeld = false
  // A renew that ended, or a refused lock, means the prompt ran no lock command that holds anything.
  if (prR.renew && prR.renew.verdict !== 'renewed') lockHeld = false
  let v = prR.lock ? prR.lock.verdict : null
  logWait('pr', prR.lock)
  const refusal = x => x === 'land-contended' || x === 'held_by' || x === 'lost_to'
  if (refusal(v)) lockHeld = false
  const lostClaim = renewed(prR.renew, 'ship')
  if (lostClaim) return lostClaim
  if (!complete(prR, PR_SCHEMA)) return stop('pr', { result: prR })
  PR = prR.pr
  // The shipped head must be the verified head; after a sync, the reviewed merge commit.
  if (!sameSha(prR.head, verify.head)) return stop('head-moved', { pr: PR, expected: verify.head, head: prR.head })
  expected = fuller(verify.head, prR.head)
  head = expected
  // #818: land-contended is the wait running out at the CLI's bound behind other landings, so the claim is renewed and the same acquire
  // waits again, LAND_WAIT_RETRIES times at most. Each call is marked as possibly holding the lock first, as the pr call is.
  let waited = false
  for (let k = 1; !early && v === 'land-contended' && k <= LAND_WAIT_RETRIES; k++) {
    waited = true
    lockHeld = true
    const lk = await recall(() => call(`${CTX}
${RENEW_FIRST}
Then take the cross-host landing lock of the branch ${INT} for PR #${PR} at the verified head ${expected}; an earlier wait for it ran out behind other landings. Run alone and exactly: ${LAND_ACQUIRE(expected, true)}
${LOCK_RETURN} Return it as lock. Run nothing else.
${RULES}`, { label: `land-lock-${k}`, phase: 'Ship', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'low', schema: withRenew({ type: 'object', properties: {} }, { lock: NULLABLE(LOCK_SCHEMA) }) }), r => r.renew)
    if (!lk) return stop('land-lock', { pr: PR, lock: null })
    // As for the pr call: a renew that ended ran no lock command, and a refused lock holds nothing.
    if (lk.renew && lk.renew.verdict !== 'renewed') lockHeld = false
    v = lk.lock ? lk.lock.verdict : null
    logWait(`land-lock-${k}`, lk.lock)
    if (refusal(v)) lockHeld = false
    const lost = renewed(lk.renew, `land-lock-${k}`)
    if (lost) return lost
  }
  // One sync merge of the integration branch into the branch; a row ends the landing, null goes on to the next round.
  // #941: with early (the probe's reply), the pr call found the conflict before it asked for the lock, so no sync step runs and nothing is
  // held or waited for: the resolution, its review and its fix wave are the same steps, and the next round pushes the accepted head and
  // takes the lock for the first time, waiting. That merge is no answer to a behind poll, so it spends none of the sync-contention budget.
  const syncRound = async early => {
    if (!early && !raced) {
      if (contended >= 2) return stop('sync-contention', { pr: PR, syncs })
      contended++
    }
    raced = false
    syncs++
    const sy = early ? { status: 'conflicted', conflicted: true, notes: `the probe before the land lock found a conflict with ${INT}${(early.files || []).length ? ` in ${early.files.join(', ')}` : ''}` } : await call(`${CTX}
The branch is behind ${INT}. Merge origin/${INT} into it in the worktree (git -C ${W} merge origin/${INT}). If it conflicts, do not resolve it: run git merge --abort inside ${W}, confirm no merge is left in progress (git -C ${W} rev-parse -q --verify MERGE_HEAD fails), and return status conflicted with conflicted true and the conflicting files in notes; a later step resolves it. ${FMT} Do not push. For a clean merge return conflicted false, merge_commit (full sha) and head (the full sha of HEAD after the merge: the merge commit itself, unless you committed on top of it); status blocked with notes if the merge cannot be made.
${RULES}`, { label: `sync-${syncs}`, phase: 'Ship', agentType: 'implementer', model: 'sonnet', schema: SYNC })
    // A blocked answer that names a conflict is the aborted merge under another name.
    const aborted = !!sy && (sy.status === 'conflicted' || (sy.status === 'blocked' && sy.conflicted === true))
    // The reply that names the merge to land: the sync step's own, or the resolution's.
    let merge = sy
    // #913: a conflict is resolved outside the lock. A sync step that resolved it itself, against its prompt, is released and reviewed the same way.
    if (aborted || (sy && sy.status === 'done' && sy.conflicted)) {
      lockOut = true
      lockFirst = !!early
      // A release that failed stays marked held, so the release of the next stop tries it again.
      if ((await unlock()).lock_unreleased) lockHeld = true
      if (aborted) {
        merge = await call(`${CTX}
Merging origin/${INT} into the branch conflicts. Resolve it in the worktree; the landing lock is not held while you work. If a merge is in progress (git -C ${W} rev-parse -q --verify MERGE_HEAD succeeds), run git merge --abort inside ${W} first. Then git -C ${W} fetch origin and git -C ${W} merge origin/${INT}. If it conflicts, resolve each conflict keeping both sides' intent, ${MARKER_CHECK(W, INT)}, and, still before committing, ${WHOLE('the files you resolved by hand')}; ${RESOLVE_SCOPE}. ${RESOLVE_ORDER}. ${FMT} Do not push. Return conflicted (false when the merge was clean this time; it is reviewed all the same), merge_commit (full sha), head (the full sha of HEAD: the merge commit, or the last commit you made on top of it), resolved_files and markers_checked (true when both checks ran); status blocked with notes if you cannot resolve it safely.
${RULES}`, { label: `sync-resolve-${syncs}`, phase: 'Ship', agentType: 'implementer', model: 'sonnet', schema: SYNC })
      }
    }
    if (!merge || merge.status !== 'done' || !present(merge.merge_commit)) return stop('sync', { pr: PR, sync: merge })
    // #986: the head the landing goes on with is the merge commit, or the resolution's head when it made plain commits on top of the merge.
    // The sync review then proves that ancestry and reads the range between them too; any other head stops at the sync stage.
    const mc = merge.merge_commit
    const followup = present(merge.head) && !sameSha(merge.head, mc)
    const after = followup ? SYNC_AFTER(W, mc, merge.head) : ''
    expected = followup ? merge.head : mc
    // A merge that conflicted is reviewed whatever its resolution says of itself: the sync step saw the conflict. A head that is not the
    // merge commit is reviewed too, whatever the merge was: nothing else would read the commits on top of it.
    if (aborted || merge.conflicted || followup) {
      const sr = await call(`${CTX}
Review the conflict resolution in merge commit ${merge.merge_commit}: git -C ${W} show --cc ${merge.merge_commit} and the resolved files ${JSON.stringify(merge.resolved_files || [])}; the tests run: ${JSON.stringify(merge.tests || [])}. Report Important or Critical defects only: a dropped change from either side, a broken merge of intent, a resolved file whose tests were not run.${merge.markers_checked === true ? '' : MARKERS_UNCHECKED}${followup ? DESCENDS(W, mc, merge.head) : ''}`, { label: `sync-review-${syncs}`, phase: 'Ship', agentType: 'reviewer', schema: followup ? { ...FINDINGS, properties: { ...FINDINGS.properties, descends: { type: 'boolean' } }, required: [...FINDINGS.required, 'descends'] } : FINDINGS })
      if (!sr) return stop('sync-review', { pr: PR, review: sr })
      // Only the review's own proof accepts a head that is not the merge commit; a missing answer is no proof.
      if (followup && sr.descends !== true) return stop('sync', { pr: PR, sync: merge, details: `the resolution names the head ${merge.head} and the merge commit ${mc}, and the head does not descend from it: only a reviewed merge commit lands` })
      if (findingsOf(sr).length) {
        if (syncFixes >= 1) return stop('sync-review', { pr: PR, review: sr })
        syncFixes++
        const w = await shipFix({
          label: `fix-sync-${syncs}`, reviewLabel: `fix-sync-review-${syncs}`,
          rebuttal: true,
          fixPrompt: `${CTX}\n${SYNC_FIX(W, merge.merge_commit, findingsOf(sr), after)} Do not push. ${FIX_TESTS} ${COMMIT_SCOPE} ${IMPL_RETURN}\n${RULES}`,
          reviewPrompt: (fix, moved) => `${CTX}\n${SYNC_REREVIEW(W, merge.merge_commit, findingsOf(sr), fix, moved, after)}`,
        })
        if (!w.ok) return stop('sync-fix', { pr: PR, review: sr, fix: w.fix })
        if (!w.review || findingsOf(w.review).length) return stop('sync-review', { pr: PR, review: w.review, sync_review: sr, fix: w.fix })
        if (w.moved) expected = w.fix.commit
      } else if (finalReviewed) {
        finalReviewed = { ...finalReviewed, accepted: [...(finalReviewed.accepted || []), merge.merge_commit] }
      }
    }
    return null
  }
  // A stop before the first take (#941): a pr call that answered conflicted may have taken the lock at the verified head all the same,
  // against its prompt, so that head is marked possibly held and the stop's release names it once (not_held normally).
  const readyHead = expected
  const unheld = row => {
    if (early && lockFirst) {
      lockHeld = true
      lockSha = readyHead
      lockMaybe = null
    }
    return row
  }
  if (early) {
    log(`${INT} conflicts with the head; resolving before the land lock is asked for`)
    const stopped = await syncRound(early)
    if (stopped) return unheld(stopped)
  } else if (!HOLDING.includes(v)) return stop(refusal(v) ? 'land-contended' : 'land-lock', { pr: PR, lock: v })
  for (;;) {
    round++
    // A sync merge, sync fix or CI fix moved the head: the push call renews and pushes it, then the checks call moves the lock to it before it waits (#801).
    // #913: the lock was released for a conflicted sync; this round takes it again at the accepted head, waiting.
    const retake = lockOut
    const moved = retake || !sameSha(lockSha, expected)
    if (moved) {
      const pu = await recall(() => call(`${CTX}
${RENEW_FIRST}
Then push the branch ${setup.branch} of PR #${PR} at the head ${expected}: run alone git -C ${W} push origin ${setup.branch}, then return head (git -C ${W} rev-parse HEAD, the full sha).
${RULES}`, { label: `land-push-${round}`, phase: 'Ship', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'low', schema: withRenew(PUSH_SCHEMA) }), r => r.renew)
      if (!pu) return unheld(stop('push', { pr: PR }))
      const lost = renewed(pu.renew, `checks-${round}`)
      if (lost) return unheld(lost)
      if (!sameSha(pu.head, expected)) return unheld(stop('head-moved', { pr: PR, expected, head: pu.head }))
      expected = fuller(expected, pu.head)
      lockMaybe = expected
      // As for the pr call: the waiting acquire may take the lock before its reply is lost.
      if (retake) lockHeld = true
      // #941: a first take holds nothing at an earlier head, so the accepted head is the one sha a release names.
      if (retake && lockFirst) {
        lockSha = expected
        lockMaybe = null
      }
    }
    // Round 1 reads the poll the pr call carried (its renew covered the claim), unless a retried wait took the lock, which polled no checks;
    // a moved round moves the lock then polls, one call; every other unmoved round polls on its own with a renew.
    const folded = round === 1 && !moved && !waited
    // #986: the poll that follows a rerun of failed jobs (the head is unchanged, so it is an unmoved poll), the only one that may answer
    // stale; a poll whose wait ran out keeps it for the next.
    const stalePoll = reran && !moved && !folded
    let ck
    if (folded) ck = prR.checks || null
    else {
      ck = await recall(() => call(`${CTX}
${moved ? `${retake && lockFirst ? `Take the cross-host landing lock of the branch ${INT} for PR #${PR} at the head ${expected}; a conflict with ${INT} was resolved before the lock was asked for` : retake ? `Take the cross-host landing lock of the branch ${INT} for PR #${PR} again, at the head ${expected}; it was released while a conflict was resolved` : `Move the cross-host landing lock of the branch ${INT} for PR #${PR} to the head ${expected}`}: run alone and exactly: ${LAND_ACQUIRE(expected, retake)}
${LOCK_RETURN} Return it as lock. Only when lock's verdict is acquired, already_held or moved, wait ${CHECKS_WAIT(PR)} Otherwise run nothing else and return only lock.` : `${RENEW_FIRST}\nThen wait ${CHECKS_WAIT(PR)}${stalePoll ? ` ${STALE_RERUN(UNSET, SLUG)}` : ''}`}
${RULES}`, { label: `checks-${round}`, phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: moved ? { ...CHECKS, properties: { ...CHECKS.properties, lock: NULLABLE(LOCK_SCHEMA) }, required: ['lock'] } : withRenew(stalePoll ? WITH_STALE(CHECKS) : CHECKS) }), r => (moved ? null : r.renew))
      if (moved) {
        let mv = ck && ck.lock ? ck.lock.verdict : null
        if (ck) logWait(`checks-${round}`, ck.lock)
        // #913: the retake's wait ran out behind other landings, so another holder has the lock: renew the claim and wait again,
        // LAND_WAIT_RETRIES times at most, as the first wait does. Each call is marked as possibly holding the lock first.
        let relocked = false
        for (let k = 1; retake && mv === 'land-contended' && k <= LAND_WAIT_RETRIES; k++) {
          relocks++
          lockHeld = true
          const lk = await recall(() => call(`${CTX}
${RENEW_FIRST}
Then take the cross-host landing lock of the branch ${INT} again for PR #${PR} at the head ${expected}; an earlier wait for it ran out behind other landings. Run alone and exactly: ${LAND_ACQUIRE(expected, true)}
${LOCK_RETURN} Return it as lock. Run nothing else.
${RULES}`, { label: `land-relock-${relocks}`, phase: 'Ship', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'low', schema: withRenew({ type: 'object', properties: {} }, { lock: NULLABLE(LOCK_SCHEMA) }) }), r => r.renew)
          if (!lk) return stop('land-lock', { pr: PR, lock: null })
          if (lk.renew && lk.renew.verdict !== 'renewed') lockHeld = false
          mv = lk.lock ? lk.lock.verdict : null
          logWait(`land-relock-${relocks}`, lk.lock)
          if (refusal(mv)) lockHeld = false
          const lost = renewed(lk.renew, `land-relock-${relocks}`)
          if (lost) return lost
          relocked = true
        }
        if (HOLDING.includes(mv)) {
          lockSha = expected
          lockMaybe = null
          lockOut = false
          lockFirst = false
        } else if (mv === 'land-contended' || mv === 'held_by' || mv === 'lost_to') {
          lockMaybe = null
          // A refused retake holds nothing: the lock of the earlier head was released before the conflict was resolved.
          if (retake) lockHeld = false
        }
        if (!HOLDING.includes(mv)) return stop('land-contended', { pr: PR, lock: mv })
        // A retried wait polled no checks: the next round polls them, with the lock at the head.
        if (relocked) continue
      } else {
        const lost = ck ? renewed(ck.renew, `checks-${round}`) : null
        if (lost) return lost
      }
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
    reran = false
    if (state === 'failed') {
      // #986: every failing check was a gate on an old result and the checks step reran it: not a red poll. Once per landing, since
      // only the one poll after the one rerun is asked; the next poll counts whatever it shows.
      if (stalePoll && staleOf(ck).length) {
        log(`checks-${round} reran ${staleOf(ck).length === 1 ? 'a stale gate run' : `${staleOf(ck).length} stale gate runs`} (${staleOf(ck).join(', ')}); polling once more`)
        continue
      }
      if (checksFixes >= 1) return stop('checks', { pr: PR, failing: failingNames, checks: ck })
      checksFixes++
      const failing = JSON.stringify(failingNames)
      const w = await shipFix({
        label: 'fix-ci', reviewLabel: 'fix-ci-review',
        rerun: true,
        fixPrompt: `${CTX}\n${PLAN_REF} The checks of PR #${PR} failed at ${expected}: ${failing}. Log tail: ${ck.details || 'none given'}. Find the cause in this branch's changes (git -C ${W} diff ${RANGE}), fix it with the smallest change and a regression test that fails without it, then commit. Do not push: the next checks step pushes. Never weaken, skip or delete a test or check to make it pass. ${FIX_TESTS} ${COMMIT_SCOPE} ${IMPL_RETURN}
When the failure has no cause in the code (an infrastructure, cache or network error in a setup step), change and commit nothing: ${RERUN_ALL(UNSET, SLUG, expected)}, do not wait for them, and return status done with the head unchanged (commit equal to start_head, ${expected}) and the error you saw in notes; the program then polls the checks itself.\n${RULES}`,
        reviewPrompt: fix => `${CTX}\nReview this fix for failing checks: ${span(fix)}; the failure it answers: ${failing} (${ck.details || 'no log'}); notes: ${fix.notes}. Report Important or Critical defects only, above all a weakened, skipped or deleted test or check, or a fix with no regression test. Do not edit anything.`,
      })
      if (!w.ok) return stop('checks-fix', { pr: PR, checks: ck, fix: w.fix })
      // #818: the failed jobs were rerun at the unchanged head. The loop polls again; checksFixes still ends a second red poll at the checks stop.
      // #986: that next poll alone may rerun a stale gate (STALE_RERUN).
      if (w.rerun) {
        reran = true
        continue
      }
      if (!w.review || findingsOf(w.review).length) return stop('checks-fix-review', { pr: PR, checks: ck, review: w.review })
      expected = w.fix.commit
      continue
    }
    if (state === 'passed') {
      // One call: renew, the pre-merge lock check (still held or moved merges; retaken after a loss rechecks first, once), then the merge.
      mg = await recall(() => call(`${CTX}
${RENEW_FIRST}
Then re-check the cross-host landing lock of the branch ${INT} for PR #${PR}: run alone and exactly: ${LAND_ACQUIRE(expected, false)}
${LOCK_RETURN} Return it as lock.
Only when lock's verdict is already_held or moved, merge PR #${PR}: run, alone and exactly: ${UNSET}gh pr merge ${PR} --repo ${SLUG} --${STRATEGY} --match-head-commit ${head}${setup.delete_branch ? ' --delete-branch' : ''}
Then read gh pr view ${PR} --repo ${SLUG} --json state,mergeCommit: merged is true only when state is MERGED. Never retry with another form; on a guard refusal or a head mismatch return merged false with the exact message, and behind true only when the refusal says the head branch is not up to date with the base branch, or the guard says the PR is behind its base (the integration branch moved), else false. On any other lock verdict run nothing else and return merged false with the verdict in notes.
${RULES}`, { label: 'merge', phase: 'Ship', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'low', schema: withRenew(MERGE_SCHEMA, { lock: NULLABLE(LOCK_SCHEMA) }) }), r => r.renew)
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
    const stopped = await syncRound(null)
    if (stopped) return stopped
  }
}
let landed
let released = {}
let mergedNow = false
try {
  landed = await landBody()
  mergedNow = landed === null
} finally {
  if (!mergedNow) released = await unlock()
}
if (landed) return { ...landed, ...released }

let finished
try {
  finished = await closeOut(PR, mg.merge_commit, W, head, lockHeld ? { sha: lockSha, maybe: lockMaybe && !sameSha(lockMaybe, lockSha) ? lockMaybe : null } : null)
} finally {
  if (landRelease && (landRelease.verdict === 'released' || landRelease.verdict === 'not_held')) lockHeld = false
  released = await unlock()
}
return finished.stage === 'done' ? { ...finished, chunked, syncs, verify: verify.results, ...(flakySeen.length ? { flaky: flakySeen } : {}), ...(outsideFixes.length ? { outside_fixes: outsideFixes } : {}), ...released } : { ...finished, ...released }
