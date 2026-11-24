export const meta = {
  name: 'deliver-standard',
  description: 'Deliver one standard-lane tracker issue: plan, implement and review each task, final review, verify once, ship',
  whenToUse: 'A standard-lane issue the user asked to deliver with this program; args {repo_root, issue, session_id|batch_id, mode?, lane?, decisions?, spec?, look? (with cont: {answer: approve, head, message?}, {answer: fix, head, words, message?} to approve that head with one fix, or {answer: changes, words}), review_sizing?, clerk_model?, cont?, amend?}; mode plan stops after plan review, ready after verify with no PR, ship (the default) merges; with no lane and no cont, outside plan mode, setup takes the direct or standard lane of the lane rule (issue-setup lane), and a standing live-fault declaration still makes it live; lane direct has no plan: one implementer following deliver-direct, one fresh reviewer, at most one fix round; lane live, chosen by a standing live-fault declaration of the issue (sprint recap), has no plan: one implementer that shows a test failing before its change and passing after it, one reviewer; review_sizing true (default off) narrows the Claude plan review to rules, conventions and consistency when the Codex plan review runs, and chunks the final review only above 1500 changed lines; clerk_model sonnet (the default) or haiku sets the model of the status clerk steps (a trial, #803); the setup steps and every step that emits a lifecycle verb stay on sonnet (#813); amend (a resume of a standard-lane cont with a plan) lists {file, find, replace} edits of files in cont.setup.plan_dir, applied by plan-amend before the next task and recorded under an Amendments heading in plan.md; a file outside plan_dir, or a find text that does not occur exactly once, stops at stage amend with the cont unchanged',
  phases: [
    { title: 'Setup', detail: 'resolve contract, pre-flight, claim, worktree' },
    { title: 'Plan', detail: 'plan outside the tree, then review' },
    { title: 'Tasks', detail: 'implement and review each task' },
    { title: 'Final review', detail: 'whole-range review and fix wave' },
    { title: 'Verify', detail: 'declared verification once, after the fix wave' },
    { title: 'Ship', detail: 'PR, land lock, sync, checks, merge, release, close out' },
  ],
}

// Args: repo_root (the checkout), issue, session_id or batch_id (the claim holder is <host>/<batch_id> or
// <host>/session-<session_id>), decisions (owner answers to a needs_user stop or a blocked task), spec (path of an
// approved design spec) and cont (an earlier stop's cont, passed back unchanged to resume; see RESUME).

// mode: plan stops after plan review with { stage: 'planned', plan, cont }; ready stops after verify with no PR and the
// claim kept; ship, the default, merges. A ready cont resumed in ship skips the final review and verify when the head
// is unchanged and the tree clean.

// lane: with none given (and no cont, outside plan mode) setup reads the lane rule (issue-setup lane): direct, else
// standard, the default; a standing live-fault declaration still wins. direct has no planner, one implementer following deliver-direct, one fresh reviewer and
// at most one fix round; live, chosen by a standing live-fault declaration of the issue, has one implementer that shows
// a test failing then passing and one reviewer. A cont keeps its lane; direct and live have no plan mode.

// amend: {file, find, replace} edits of files in cont.setup.plan_dir, applied all or none by plan-amend before the next
// task. look (with cont, in ship mode): the owner's answer to an awaiting-look stop, {answer: approve|fix|changes,
// head, words?, message?}; a head lands only under an approval that look-approval status records for it. review_sizing
// and clerk_model are arguments only, never kept in cont, so a resume passes them again.

// Every policy value comes from the project contract that setup resolves; this file carries no project literal and
// defaults no policy value.

// CLAIM: the claim is a forge-claim claim, acquired before the worktree step, renewed before each stage boundary and
// released at close-out. A renew that finds the claim ended stops with no cont; one that gets no answer stops with a
// cont whose resume acquires again. A renew or acquire that answers `error` with `transient` is re-called once before
// it stops.

// RESUME: every stop from the claim on returns { stage, ..., cont }. Passing it back as args.cont re-adopts the claimed
// worktree (a dirty tree is refused unless cont.partial names the task that left the edits), reuses cont.plan, skips
// the tasks in cont.done, then runs final review, verify and ship again; ship reuses an open PR. Every resume re-reads
// the facts of each branch the plan declares, and reuses cont.verified or cont.final_reviewed only when every declared
// head is unchanged. A final review is skipped when cont.final_reviewed names the head it passed at and the head is

// unchanged or only gained integration-branch merges with no unreviewed conflict resolution.

// A merged PR is the delivery's own only when it is cont.pr or carries a commit of cont.done. A result also carries
// dead_agents (labels of agents that returned nothing or threw) and lost_reviews (reviews that answered twice with no
// usable review). A red check and a sync-review finding each get one fix wave per delivery; a second one stops with
// cont.

// LAND: ship opens the PR at the verified head and takes the cross-host land lock of the integration branch with --wait
// (the CLI does the waiting). Later it syncs, pushes and moves the lock after every head change, waits for every check
// on head, re-checks the lock once, merges and releases it. The lock is released on every stop after it was taken; a
// release that fails is reported as lock_unreleased on the result.

// A sync merge that conflicts is aborted and the lock released: its resolution, review and fix wave run outside the
// lock, and the accepted head takes it again with --wait (lockOut). Before it asks for the lock, the pr call probes
// whether the integration branch merges cleanly into the head (PROBE), and a red check the branch itself caused is
// fixed outside the lock too (OWN_RED).

// LOOK: the setup reads once per run whether the issue is marked for the owner's look. A marked delivery runs no land
// command before the owner answers: after verify it pushes the branch, opens or reuses the PR (look-pr, no lock), syncs
// a branch that is behind outside any lock, and stops at awaiting-look with cont.look = {pr, head}. Every such stop
// follows a look-checks wait that read every check passed. A landing under a recorded approval ticks the look marker
// and leaves that criterion out of the hold; a resync that moves the head past the approved one is verified and carried

// (look-carry) or shown to the owner again. The program never posts an approval.

// FOLDS: consecutive clerk steps with no program decision between them share one call. Kept separate, each with a
// program decision between the two: checks then merge, merge then release, hold then close-out, the push then the lock
// move (the lock command names the pushed full sha) and the renew before the final review and the verify.

// Lifecycle forms follow the contract (merge strategy, delete_branch, credential unsets). A host guard that accepts
// fewer forms refuses at that command; the step then returns its stop with the guard's message instead of working
// around it.

const REPO = args && args.repo_root
const ISSUE = args && args.issue
if (!REPO || !ISSUE) return { stage: 'args', error: 'repo_root and issue are required' }
const MODE = args.mode === undefined ? 'ship' : args.mode
if (!['plan', 'ready', 'ship'].includes(MODE)) return { stage: 'args', error: 'mode must be plan, ready or ship' }
let CONT = args.cont || null
if (args.lane !== undefined && !['standard', 'direct', 'live'].includes(args.lane)) return { stage: 'args', error: 'lane must be standard, direct or live' }
if (CONT && args.lane && args.lane !== (CONT.lane || 'standard')) return { stage: 'args', error: 'a cont keeps its lane; start again without cont: setup re-adopts the branch and the claim' }
// A lane-less fresh run reads the live-fault declaration and the lane rule in its setup and may switch lane there, so LANE is a let.
let LANE = args.lane || (CONT && CONT.lane) || 'standard'
if (LANE === 'direct' && MODE === 'plan') return { stage: 'args', error: 'the direct lane has no plan mode' }
if (LANE === 'live' && MODE === 'plan') return { stage: 'args', error: 'the live-fault lane has no plan mode' }
const LIVE_ASKED = args.lane === 'live' || !!(CONT && CONT.lane === 'live')
const LIVE_AUTO = !CONT && args.lane === undefined
const LIVE_READING = LIVE_ASKED || LIVE_AUTO
// The lane rule is read by a lane-less fresh run outside plan mode only; an explicit lane, a cont and plan mode read none.
// A fresh run given a spec or decisions keeps the standard lane too: only the planner and the plan and final reviews are told them.
const RULE_AUTO = !CONT && args.lane === undefined && MODE !== 'plan' && !args.spec && !(typeof args.decisions === 'string' && args.decisions.trim())
if (args.review_sizing !== undefined && typeof args.review_sizing !== 'boolean') return { stage: 'args', error: 'review_sizing must be a boolean' }
const REVIEW_SIZING = args.review_sizing === true
if (args.clerk_model !== undefined && !['sonnet', 'haiku'].includes(args.clerk_model)) return { stage: 'args', error: 'clerk_model must be sonnet or haiku' }
const CLERK_MODEL = args.clerk_model === undefined ? 'sonnet' : args.clerk_model
// The owner's answer to an awaiting-look stop, valid only with a cont and in ship mode.
const LOOK_ANSWER = args.look === undefined ? null : args.look
if (LOOK_ANSWER !== null) {
  if (!CONT) return { stage: 'args', error: 'look needs a cont: it answers an awaiting-look stop' }
  if (MODE !== 'ship') return { stage: 'args', error: 'look needs mode ship' }
  const held = CONT.look
  const heldLook = !!held && typeof held === 'object' && Number.isInteger(held.pr) && held.pr > 0 && /^[0-9a-f]{40}$/.test(held.head)
  if (LOOK_ANSWER && LOOK_ANSWER.answer === 'approve' && !heldLook) return { stage: 'args', error: 'look approve needs a cont that stopped at awaiting-look' }
  const wordsOk = typeof (LOOK_ANSWER && LOOK_ANSWER.words) === 'string' && LOOK_ANSWER.words.trim() !== '' && LOOK_ANSWER.words.length <= 2000
  const headOk = typeof (LOOK_ANSWER && LOOK_ANSWER.head) === 'string' && /^[0-9a-f]{40}$/.test(LOOK_ANSWER.head) && (LOOK_ANSWER.message === undefined || (typeof LOOK_ANSWER.message === 'string' && /^[A-Za-z0-9._:\/@+-]+$/.test(LOOK_ANSWER.message)) || (Number.isInteger(LOOK_ANSWER.message) && LOOK_ANSWER.message >= 1))
  const sound = !!LOOK_ANSWER && typeof LOOK_ANSWER === 'object' && !Array.isArray(LOOK_ANSWER) && (LOOK_ANSWER.answer === 'approve' ? headOk
    : LOOK_ANSWER.answer === 'fix' ? headOk && wordsOk
    : LOOK_ANSWER.answer === 'changes' && wordsOk)
  if (!sound) return { stage: 'args', error: 'look must be {answer: approve, head, message?}, {answer: fix, head, words, message?} or {answer: changes, words}' }
  if (LOOK_ANSWER.answer === 'fix' && !heldLook) return { stage: 'args', error: 'look fix needs a cont that stopped at awaiting-look' }
}
// A changes or fix answer rejects the approved head, so the approval leaves the cont here, before any stop: every stop
// of this resume carries a cont with no approval, and a resume with no look cannot land that head.
if (LOOK_ANSWER && (LOOK_ANSWER.answer === 'changes' || LOOK_ANSWER.answer === 'fix') && CONT && CONT.look && typeof CONT.look === 'object' && CONT.look.approved !== undefined) {
  const { approved: _revoked, ...unapproved } = CONT.look
  CONT = { ...CONT, look: unapproved }
}
// A setup step or one that emits a lifecycle verb must reproduce a wide schema or a guard-exact command, so it never
// takes the trial model.
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

// forge-claim retries a transport error itself, up to 150 s in a hanging outage, above the Bash tool's 120 s default.
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

// A StructuredOutput call sent beside another tool call is taken as the final answer before that call's result exists,
// so a pending lookup's placeholder would become the reply. This sentence is added last in call(), the same line in
// deliver-batch.js, so no step can miss it; it is about the reply alone.
const REPLY_ALONE = 'Call StructuredOutput alone in its own message, never beside another tool call, only after every other tool result has come back: the first accepted call is final and ends the step.'
// A reviewer that detaches the worktree to run a script at the commit under review leaves the next setup a detached
// HEAD. This sentence is added in readReview(), the same line in deliver-batch.js, so no review step can miss it.
const READ_ONLY = 'Never check out, switch, reset or stash in the worktree: read another commit with git show.'

const SEV = { type: 'string', enum: ['critical', 'important', 'minor'] }
// incomplete is the verdict of a review that could not finish; readReview() below reads every reply of this schema.
const FINDINGS = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['pass', 'findings', 'incomplete'], description: 'incomplete: the review is not finished; never a placeholder finding' },
    findings: { type: 'array', items: { type: 'object', description: 'a critical or important finding names its file or its failing_input', properties: { severity: SEV, file: { type: 'string' }, summary: { type: 'string' }, failing_input: { type: 'string' }, relation: { type: 'string', enum: ['narrowing', 'new'] } }, required: ['severity', 'summary'] } },
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
const FULL_SHA = { type: 'string', pattern: '^[0-9a-f]{40}$' }
// start_head and commit are full shas or absent (a blocked reply names none), so the harness refuses a placeholder.
const IMPL = {
  type: 'object',
  properties: { status: { type: 'string', enum: ['done', 'blocked'] }, start_head: FULL_SHA, commit: FULL_SHA, tests: { type: 'array', items: { type: 'string' } }, notes: { type: 'string' }, blocked_on: { type: 'integer' } },
  required: ['status', 'notes'],
}
// The sync review's schema; with followup it also returns descends. Every FINDINGS schema is one readReview() reads.
const SYNC_REVIEW_SCHEMA = followup => (followup ? { ...FINDINGS, properties: { ...FINDINGS.properties, descends: { type: 'boolean' } }, required: [...FINDINGS.required, 'descends'] } : FINDINGS)
// How a removal check is run: one per criterion bounds their number, the filter and incremental build bound each cost.
const REMOVALS = "For a removal run only the tests that pin it, through the runner's filter, as an incremental build: never the suite, never a clean rebuild; removals that are independent may be made and checked in one script, and a run of zero tests confirms nothing."
const IMPL_RETURN = 'Return start_head (git rev-parse HEAD before you change anything) and commit (the full sha of HEAD after your last commit).'
// A wave that may commit on several branches reports the issue worktree's commits only in start_head and commit.
const IMPL_RETURN_AT = w => `Return start_head (git -C ${w} rev-parse HEAD before you change anything) and commit (the full sha of git -C ${w} rev-parse HEAD after your last commit): both name the issue worktree ${w}, never a declared branch's commit (those go in branch_heads); when you commit nothing there, commit equals start_head.`
const STRS = { type: 'array', items: { type: 'string' } }
// A forge or agent may report a short sha; the same head must not read as moved.
const BRANCH_HEADS = { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, head: FULL_SHA, current: { type: 'string' }, toplevel: { type: 'string' }, common_dir: { type: 'string' } }, required: ['name', 'head'] } }
const FIX_WAVE_IMPL = { ...IMPL, properties: { ...IMPL.properties, branch_heads: BRANCH_HEADS } }
// A fix-wave review and its re-review each return the files the wave's commits changed in the issue worktree.
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
// The look-approval marked verdict the setup reads once per run; error carries the detail of its failure.
const LOOK_SCHEMA = { type: 'object', properties: { verdict: { type: 'string', enum: ['marked', 'unmarked', 'error'] }, covers: STRS, acs: STRS, detail: { type: 'string' } }, required: ['verdict'] }
const LIVE_READ = { type: 'object', properties: { verdict: { type: 'string', enum: ['declared', 'none', 'no-sprint', 'error'] }, sprint_id: { type: 'string' }, fault: { type: 'object', properties: { id: { type: 'integer' }, issue: { type: 'integer' }, observed: { type: 'string' }, when: { type: 'string' }, proven: { type: 'string' }, at: { type: 'string' } } }, detail: { type: 'string' } }, required: ['verdict'] }
// The lane rule's verdict the setup reads once per fresh lane-less run; error carries the failure as reason.
const LANE_RULE_READ = { type: 'object', properties: { verdict: { type: 'string', enum: ['direct', 'standard', 'error'] }, reason: { type: 'string' } }, required: ['verdict'] }
const SETUP_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' }, reason: { type: 'string' }, details: { type: 'string' }, transient: { type: 'boolean' },
    host: { type: 'string' }, slug: { type: 'string' }, integration_branch: { type: 'string' }, default_branch: { type: 'string' },
    branch: { type: 'string' }, worktree_path: { type: 'string' }, head: { type: 'string' },
    merged_pr: { type: 'integer' }, dirty: { type: 'boolean' }, reattached: { type: 'boolean' }, duplicate_pr: { type: 'integer' },
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
    verification_before_pull_request: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, argv: STRS, cwd: { type: 'string' }, when_changed: STRS, skip_reason: { type: 'string' } }, required: ['id', 'argv', 'cwd'] } },
    look: LOOK_SCHEMA,
    live_fault: LIVE_READ,
    lane_rule: LANE_RULE_READ,
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
// A folded step returns its own result plus the claim renew it ran first as a required nested member.
const NULLABLE = s => ({ anyOf: [s, { type: 'null' }] })
const ANSWER_SCHEMA = { type: 'object', properties: { verdict: { type: 'string' }, comment_id: { type: ['integer', 'null'] }, questions: { type: 'array', items: { type: 'object' } }, decisions: { type: 'string' } }, required: ['verdict'] }
// The fresh setup also claims the issue and sets up the worktree: holder, acquire and claim ride beside its own fields,
// and a standard-lane setup also reads the owner's answer and, after an already_held acquire, renews the claim. The
// claim fields are required (null on a refusal before the claim), so a reply cannot leave out a claim it took.
const SETUP_FOLDED = { ...SETUP_SCHEMA, properties: { ...SETUP_SCHEMA.properties, holder: NULLABLE({ type: 'string' }), acquire: NULLABLE(ACQUIRE_SCHEMA), claim: NULLABLE(CLAIM_SCHEMA), answer: NULLABLE(ANSWER_SCHEMA), renew: NULLABLE(RENEW_SCHEMA) }, required: ['ok', 'holder', 'acquire', 'claim'] }
const withRenew = (s, extra = {}) => ({ ...s, properties: { ...s.properties, renew: RENEW_SCHEMA, ...extra }, required: ['renew'] })
const complete = (r, schema) => !!r && schema.required.every(k => r[k] !== undefined && r[k] !== null)
// A renew or acquire that ran out of forge-claim's transport retries is re-called once; the second reply stands.
const transientError = r => !!r && r.verdict === 'error' && r.transient === true
const recall = async (make, pick = r => r) => { const r = await make(); return r && transientError(pick(r)) ? make() : r }
const findingsOf = r => r.findings.filter(f => f.severity !== 'minor')
// A finding naming an acceptance criterion blocks at any severity; a full round's filter is findingsOf plus a minor one
// naming one.
const namesAc = f => typeof f.ac === 'string' && f.ac.trim() !== ''
const blockingOf = r => r.findings.filter(f => isEntry(f) && (f.severity !== 'minor' || namesAc(f)))
const present = v => v !== undefined && v !== null && v !== ''
// Extra branches a plan declares are validated, then granted non-force pushes in the lifecycle rules.
const own = (o, k) => !!o && typeof o === 'object' && Object.prototype.hasOwnProperty.call(o, k)
const isEntry = b => !!b && typeof b === 'object' && !Array.isArray(b)
const declared = p => (p && Array.isArray(p.branches) ? p.branches.filter(isEntry) : [])
const SHA_RE = /^[0-9a-f]{40}$/
// A commit id read back from a cont or a reviewer's reply is used in a git command only when 4 to 40 hex digits.
const isCommit = v => typeof v === 'string' && /^[0-9a-f]{4,40}$/.test(normSha(v))
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

// The problems with a plan's declared branches; empty when valid. Never throws on any JSON value.
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
      // Admission only: a resume may find a task's own uncommitted edits in the worktree, but a plan declares a
      // worktree with none.
      if (b.clean !== true) out.push(`branch ${show(b.name)}: the worktree is not clean (git status --porcelain must print nothing at declaration)`)
      if (out.length === before) good.push(b)
    })
  }
  if (Array.isArray(p.tasks)) {
    for (const t of p.tasks) {
      // The delivery's own branch is where an undeclared task commits anyway, so naming it declares nothing.
      if (!isEntry(t) || t.branch === undefined || t.branch === setup.branch) continue
      if (typeof t.branch !== 'string' || !good.some(g => g.name === t.branch)) out.push(`task ${show(t.n)}: branch ${show(t.branch)} is not declared`)
    }
  }
  return out
}

// ---------------- Stop reason ----------------
// One line saying why a stop stopped: its stage, then the detail the stop already carries, capped. Every stop from the
// claim on carries it as reason (planned and ready are not stops); a setup stop and an ended claim do not, and
// deliver-batch shows the reason in the stopped issue's row, reading those stops' own fields.
const REASON_MAX = 300
const implDone = i => !!(i && i.status === 'done' && present(i.commit) && present(i.start_head))
const stopReason = (stage, x) => {
  const parts = []
  const say = v => { if (typeof v === 'string' && v.trim()) parts.push(v) }
  const names = (k, what) => { if (Array.isArray(x[k]) && x[k].length) say(`${what} ${x[k].map(v => (isEntry(v) ? v.id || v.ac || v.file : v)).join(', ')}`) }
  const task = isEntry(x.task) ? `task ${x.task.n} ` : ''
  // A stop whose fix waves do not converge says so first, so the cap cuts the findings and never the verdict.
  if (isEntry(x.diverging)) say(`the fix waves do not converge on ${String(x.diverging.file).slice(0, 120)} after ${x.diverging.waves} waves; an owner decision on the design is needed`)
  // So does a stop on a file two fixes in a row each drew a new finding in.
  if (isEntry(x.oscillating)) say(`the fix waves go back and forth on ${String(x.oscillating.file).slice(0, 120)}: two fixes of it in a row each drew a new finding there; an owner decision on the approach is needed`)
  // The round cap, said after the verdicts above it (a stop may carry them too).
  if (isEntry(x.round_cap) && Array.isArray(x.round_cap.findings)) say(`the review round cap is reached after ${x.round_cap.rounds} rounds (one full and two scoped); an owner decision is needed on the ${x.round_cap.findings.length} finding(s) still open: ${x.round_cap.findings.join('; ')}`)
  if (isEntry(x.conflict) && Array.isArray(x.conflict.rules)) say(`the acceptance rules ${x.conflict.rules.join(' and ')} conflict for ${x.conflict.ac}: the revise that settled one broke the other; an owner decision on how ${x.conflict.ac} is classified is the expected way out: ${x.conflict.revises_left ? 'a relaunch without one gets the one rules revise left' : 'the plan was dropped, and a relaunch without one plans again'}`)
  say(x.details)
  say(x.error)
  if (Array.isArray(x.branch_problems)) say(`branch problems: ${x.branch_problems.join('; ')}`)
  else if (own(x, 'invalid')) say(`the ${x.step} reply is not a well-formed plan`)
  if (Array.isArray(x.needs_user)) say(`${x.needs_user.length} question(s) for the owner`)
  // Why a blocked task was not moved, ahead of the implementer's notes so the cap cuts the notes.
  if (present(x.order)) say(`${task}${x.order}`)
  if (isEntry(x.blocked)) say(`${task}${['blocked', x.blocked.notes].filter(present).join(': ')}`)
  for (const k of ['impl', 'fix', 'fw']) {
    if (own(x, k) && !implDone(x[k])) say(isEntry(x[k]) ? `${task}${[x[k].status, x[k].notes].filter(present).join(': ') || 'the implementer gave no status'}` : `${task}the implementer returned nothing`)
  }
  const reviews = ['review', 'rv'].filter(k => own(x, k)).map(k => x[k])
  const found = Array.isArray(x.rules) && x.rules.length ? x.rules : Array.isArray(x.findings) ? x.findings : reviews.flatMap(r => (isEntry(r) && Array.isArray(r.findings) ? findingsOf(r) : []))
  if (found.length) say(`${task}${found.length} finding(s)${isEntry(found[0]) && present(found[0].summary) ? `: ${found[0].summary}` : ''}`)
  else if (reviews.some(r => !r)) say(`${task}the reviewer ${silence()}`)
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
  // The ways out of a blocked task end the reason, after the cap, so long notes never cut them.
  const tail = present(x.ways) ? `; ${x.ways}` : ''
  const room = REASON_MAX - tail.length
  return `${text.length > room ? `${text.slice(0, room - 3)}...` : text}${tail}`
}
const why = r => ({ ...r, reason: stopReason(r.stage, r) })

// ---------------- Amend ----------------
const AMEND = args.amend === undefined ? null : args.amend
if (AMEND !== null && !CONT) return { stage: 'args', error: 'amend needs a cont: it amends the plan of a resumed delivery' }
if (AMEND !== null && !(Array.isArray(AMEND) && AMEND.length > 0 && AMEND.every(e => isEntry(e) && typeof e.file === 'string' && e.file !== '' && typeof e.find === 'string' && e.find !== '' && typeof e.replace === 'string'))) {
  return why({ stage: 'amend', error: 'amend must be a non-empty list of {file, find, replace}: file and find non-empty strings, replace a string', cont: CONT })
}
if (AMEND !== null && (LANE !== 'standard' || !isEntry(CONT.plan) || typeof CONT.plan.plan_root !== 'string' || CONT.plan.plan_root === '' || !isEntry(CONT.setup) || typeof CONT.setup.plan_dir !== 'string' || CONT.setup.plan_dir === '')) {
  return why({ stage: 'amend', error: 'amend needs a standard-lane cont whose plan has a plan_root and whose setup has a plan_dir', cont: CONT })
}
const AMEND_DIR = AMEND !== null ? CONT.setup.plan_dir.replace(/\/+$/, '') : null
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
// ---------------- Blocked task ----------------
// A task stop whose implementer returned blocked keeps { task, notes } in cont.blocked. Running that task again with
// the same task file blocks again, so its resume needs something new from the owner: a decision the cont does not hold
// (a planner revises the task file from it; the direct lane gives the implementer both) or an amend. With neither it
// stops here, before any agent, with the cont unchanged. asked marks a revise whose planner asked the owner.

// The decision whose whole text is rerun clears blocked and reruns the implementer on the unchanged task file, for a
// cause outside the task file, and is never kept as a decision.
const NOTES_MAX = 2000
const BLOCKED = CONT && isEntry(CONT.blocked) && Number.isInteger(CONT.blocked.task) && CONT.partial === CONT.blocked.task &&
  !(Array.isArray(CONT.done) && CONT.done.some(d => isEntry(d) && d.n === CONT.blocked.task)) && (LANE !== 'standard' || (isEntry(CONT.plan) && CONT.plan_reviewed === true))
  ? { task: CONT.blocked.task, notes: typeof CONT.blocked.notes === 'string' ? CONT.blocked.notes : '', ...(CONT.blocked.asked === true ? { asked: true } : {}) } : null
const RERUN_WORD = typeof args.decisions === 'string' && args.decisions.trim() === 'rerun'
const RERUN = !!BLOCKED && RERUN_WORD
const heldDecision = d => !!CONT && Array.isArray(CONT.decisions) && CONT.decisions.includes(d)
// The decision that settles the blocked task: one this resume brings that the cont does not hold.
let newDecision = BLOCKED && !RERUN_WORD && typeof args.decisions === 'string' && args.decisions.trim() && !heldDecision(args.decisions) ? args.decisions : null
// Read at call time: the lane of a lane-less fresh run is decided after the setup.
const waysOut = () => LANE !== 'standard' ? 'resume with decisions (the implementer gets it with these notes), or decisions rerun if the cause was outside the task' : 'resume with decisions (a planner revises the task file), amend {file, find, replace}, or decisions rerun if the cause was outside the task file'
const UNSETTLED = { details: 'not run again: this resume brings nothing new from the owner', ways: waysOut() }
if (BLOCKED && !RERUN && newDecision === null && AMEND === null && !(BLOCKED.asked && LANE === 'standard')) return why({ stage: 'task', task: { n: BLOCKED.task }, blocked: BLOCKED, ...UNSETTLED, cont: CONT })
const CARRY_MAX = 10
const clip = v => (v.length > REASON_MAX ? `${v.slice(0, REASON_MAX - 3)}...` : v)
const carryable = list => (Array.isArray(list) ? list : []).filter(f => isEntry(f) && typeof f.summary === 'string' && f.summary.trim() && (f.severity !== 'minor' || namesAc(f)))
const carryOf = list => carryable(list).slice(0, CARRY_MAX)
  .map(f => ({ severity: f.severity === 'critical' ? 'critical' : 'important', ...(typeof f.file === 'string' && f.file ? { file: clip(f.file) } : {}), summary: clip(f.summary), ...(typeof f.failing_input === 'string' && f.failing_input ? { failing_input: clip(f.failing_input) } : {}), ...(namesAc(f) ? { ac: clip(f.ac) } : {}) }))
// A cont stopped on a file its fix waves went back and forth on resumes only on something new from the owner, as a
// blocked task does: a decision the cont does not hold (the first fix wave and its re-review get it as binding) or an
// amend.
const OSC_KEPT = CONT && isEntry(CONT.oscillating) && typeof CONT.oscillating.file === 'string' && CONT.oscillating.file.trim() && Array.isArray(CONT.oscillating.rounds) && Array.isArray(CONT.fix_findings) && CONT.fix_findings.length ? CONT.oscillating : null
const oscDecision = OSC_KEPT && !RERUN_WORD && typeof args.decisions === 'string' && args.decisions.trim() && !heldDecision(args.decisions) ? args.decisions : null
const OSC_WAYS = `resume with decisions (the approach)${LANE !== 'standard' ? '' : ', or amend'}`
if (OSC_KEPT && oscDecision === null && AMEND === null) return why({ stage: 'fix-wave-review', oscillating: OSC_KEPT, details: UNSETTLED.details, ways: OSC_WAYS, fix_waves: CONT.fix_waves || 0, cont: CONT })
// A verdict that leaves findings open after ROUND_CAP rounds stops before any fix wave and keeps round_cap in cont. A
// resume of that cont goes on only on something new from the owner, as an oscillating one does. The gate reads the
// persisted marker, never review_rounds: a stop the cap did not make (a lost wave, a lost re-review) is no cap stop.
const ROUND_CAP = 3
const CAP_MARK = LANE === 'standard' && CONT && isEntry(CONT.round_cap) && Number.isInteger(CONT.round_cap.rounds) && CONT.round_cap.rounds >= 1
  ? { rounds: CONT.round_cap.rounds, findings: (Array.isArray(CONT.round_cap.findings) ? CONT.round_cap.findings : []).filter(v => typeof v === 'string').slice(0, CARRY_MAX).map(clip) } : null
const CAP_KEPT = CAP_MARK !== null && carryOf(CONT.fix_findings).length > 0
const capDecision = CAP_KEPT && !RERUN_WORD && typeof args.decisions === 'string' && args.decisions.trim() && !heldDecision(args.decisions) ? args.decisions : null
const CAP_WAYS = 'resume with decisions (how to settle the open findings), or amend'
if (CAP_KEPT && capDecision === null && AMEND === null) return why({ stage: 'fix-wave-review', round_cap: CAP_MARK, details: UNSETTLED.details, ways: CAP_WAYS, fix_waves: CONT.fix_waves || 0, cont: CONT })
let capMark = CAP_MARK
const AMEND_STOP = AMEND === null ? null
  : Number.isInteger(CONT.partial) ? `the stop at task ${CONT.partial}`
  : (() => {
    const next = Array.isArray(CONT.plan.tasks) ? CONT.plan.tasks.find(t => isEntry(t) && !(Array.isArray(CONT.done) && CONT.done.some(d => isEntry(d) && d.n === t.n))) : null
    return next ? `the stop before task ${next.n}` : 'the stop after the last task'
  })()
const AMEND_INPUT = AMEND !== null ? { plan_dir: AMEND_DIR, plan_root: CONT.plan.plan_root, stop: AMEND_STOP, edits: AMEND.map(e => ({ file: amendTarget(e.file), find: e.find, replace: e.replace })) } : null
const AMEND_SCHEMA = { type: 'object', properties: { status: { type: 'string', enum: ['applied', 'refused', 'error'] }, edits: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, exists: { type: 'boolean' }, occurrences: { type: 'integer', minimum: 0 }, already: { type: 'boolean' } }, required: ['file', 'exists', 'occurrences', 'already'] } }, refused: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, reason: { type: 'string' } }, required: ['file', 'reason'] } }, detail: { type: 'string' } }, required: ['status', 'edits', 'refused'] }

// A full round whose end commit the program does not know asks its reviewers for the head they read; a scoped round's
// reviewer also returns closed, the numbers of the carried findings the head shows closed.

// The final reviewers' findings may name the acceptance criterion they find unmet (ac); a scoped finding also names its
// file and the full sha it was read at.
const withItems = (schema, item) => ({ ...schema, properties: { ...schema.properties, findings: { ...schema.properties.findings, items: item } } })
const FINAL_ITEM = { ...FINDINGS.properties.findings.items, properties: { ...FINDINGS.properties.findings.items.properties, ac: { type: 'string' } } }
const SCOPED_ITEM = { ...FINAL_ITEM, properties: { ...FINAL_ITEM.properties, commit: FULL_SHA }, required: ['severity', 'summary', 'file', 'commit'] }
const FINAL_FINDINGS = withItems(FINDINGS, FINAL_ITEM)
const FINDINGS_HEAD = { ...FINAL_FINDINGS, properties: { ...FINAL_FINDINGS.properties, head: FULL_SHA }, required: [...FINDINGS.required, 'head'] }
const SCOPED_FINDINGS = withItems({ ...FINDINGS, properties: { ...FINDINGS.properties, closed: { type: 'array', items: { type: 'integer' } }, head: { type: 'string' } } }, SCOPED_ITEM)
// final-codex reports unmet criteria by ac like the other final reviewers.
const FINAL_CODEX = { ...CODEX, properties: { ...CODEX.properties, findings: FINAL_FINDINGS.properties.findings } }
const FOLLOW_UPS = { type: 'object', properties: { filed: { type: 'array', items: { type: 'object', properties: { n: { type: 'integer', minimum: 1 }, issue: { type: 'integer', minimum: 1 } }, required: ['n', 'issue'] } } }, required: ['filed'] }
// What critical means to every final reviewer, and what a scoped round blocks on.
const CRITICAL_MEANS = 'A finding is critical only when it is a security defect, a data loss, or an acceptance criterion of the issue that is not met; every other blocking finding is important.'
const SCOPED_BLOCKS = 'After the first full review only a critical finding, or one whose ac names the acceptance criterion it finds unmet, blocks the merge: every other finding you report is filed as a follow-up issue and the delivery goes on, so never mark a hardening point critical to make it block.'
// The ask of a scoped reviewer: where each finding was read and which criterion it finds unmet.
const COMMIT_ASK = at => `Set file and commit on each finding, commit being the full sha of the commit you read it at (for a file of a branch checked out in another worktree, that branch's head there; else ${at}), and set ac to the id of the acceptance criterion it finds unmet when it finds one.`
// ---------------- Setup ----------------
phase('Setup')
const CONTRACT_READ = `Run: hostname -s and return its output as host. Run: resolve-project resolve --repo-root ${REPO}
On refusal return ok=false, reason contract, and in details the resolver's error.code, repair_id and ordered violations exactly. From the snapshot return:
- slug: bindings.tracker.repo_slug; unset_env: bindings.tracker.credential_env.unset_before_invocation (run every gh command after unsetting exactly these names, nothing else).
- integration_branch and default_branch: bindings.vcs.integration_branch and bindings.vcs.default_branch; merge_strategy and delete_branch: bindings.vcs.merge.strategy and bindings.vcs.merge.delete_branch.
- review: the command ids at bindings.workflow.review.code and .plan (omit an absent one); review_state: for code and plan, the state of the capability review.code and review.plan (available, blocked or unsupported; absent if the capability is missing).
- knowledge: bindings.paths.standards, bindings.paths.hints and bindings.paths.rejections, each as given (empty when absent).
- verification: for each id in bindings.workflow.verification its bindings.commands argv, its cwd relative to project.root (. for the root), and any bindings.workflow.verification_conditions entry (when_changed globs, skip_reason), and pre_commit: true on an entry whose verification_conditions entry has pre_commit true (omit pre_commit otherwise).
- verification_before_pull_request: only when bindings.workflow.verification_before_pull_request is a list, for each of its ids its bindings.commands argv, its cwd relative to project.root (. for the root), and any bindings.workflow.verification_conditions entry for that id (when_changed globs, skip_reason); omit verification_before_pull_request when the binding is absent or null.
Then run alone and exactly: look-approval marked --repo <slug> --issue ${ISSUE} and return its verdict (marked or unmarked), covers and acs (the array of its acs, [] when it names none) as look; on a non-zero exit return look with verdict error and the error and detail of its JSON line as detail.`
const LIVE_STEP = LIVE_READING ? `
Also run alone and exactly: sprint recap, before you return any refusal, and return live_fault on every reply, a refusal included. When it exits 0 its one JSON line gives sprint_id: return verdict declared, that sprint_id and fault (the entry of its live_faults whose issue is ${ISSUE}, every member as printed) when there is one, and verdict none when it lists none for issue ${ISSUE}. When it exits 2 printing sprint: no sprint id, return verdict no-sprint; on any other non-zero exit return verdict error and the stderr line as detail. Change nothing.` : ''
const LANE_RULE_STEP = RULE_AUTO ? `
Also run alone and exactly: issue-setup lane --repo-root ${REPO} --repo <slug> --issue ${ISSUE} and return its verdict and reason as lane_rule; on a non-zero exit return lane_rule with verdict error and the error and detail of its JSON line as reason. Change nothing.` : ''
const DEAD = []
const LOST = []
// What a review that gave the program nothing did: with no label, any review of this run.
const silence = (...labels) => ((labels.length ? labels.some(l => LOST.includes(l)) : LOST.length) ? 'answered twice with no usable review' : 'returned nothing')
// Every reviewer and implementer step opens with its one-sentence turn procedure: both kinds otherwise sent one tool
// call in only 80 to 100% of their tool messages at up to 183k of context. Added in call(), not per prompt, so no site
// can miss it. reviewer-lite is left out: its median is three turns under 20k.
const ROUNDS = {
  reviewer: `Look things up in rounds: load the files under review in one message, then put every open question's Bash, Grep or Read call in the same message as the others, never one small lookup per turn.`,
  implementer: `Work in rounds: put a round's lookups in one message, send its independent edits as several Edit calls in one message, and run the tests once per round of edits, never one small call per turn.`,
}
const withRounds = (prompt, opts) => (opts && ROUNDS[opts.agentType] ? `${ROUNDS[opts.agentType]}\n${prompt}` : prompt)
// Every step that replies through a schema ends with the one sentence about that reply.
const withReply = (prompt, opts) => (opts && opts.schema ? `${prompt}\n${REPLY_ALONE}` : prompt)
// optional: a step whose failure the caller recovers (the diff-size measurement) is not reported as a dead agent.
const call = async (prompt, opts, optional) => {
  let reply
  try {
    reply = await agent(withRounds(withReply(prompt, opts), opts), opts)
  } catch (error) {
    if (!optional) DEAD.push(opts && opts.label)
    throw error
  }
  if (reply == null && !optional) DEAD.push(opts && opts.label)
  return reply
}
const deadOf = () => ({ ...(DEAD.length ? { dead_agents: DEAD.slice() } : {}), ...(LOST.length ? { lost_reviews: LOST.slice() } : {}) })
// Every FINDINGS reply is read through readReview(). A reply whose verdict is incomplete, or that carries a blocking
// finding naming neither a file nor a failing input, is a lost review, never a finding: the step runs once more as
// <label>-again, a second such reply is returned as null, and it spends no fix round. It is no dead agent: DEAD is left
// alone, LOST names it.

// Two exceptions are held to less: ruled (the two plan reviews, where a finding naming its criterion (ac) or the rule
// (rule) names its subject) and fileless (the reviews of a task that first ended with no commit), held to the verdict
// only.
const AGAIN = '-again'
const unusable = (r, { fileless = false, ruled = false } = {}) => {
  if (!r) return ''
  if (r.verdict === 'incomplete') return 'its verdict was incomplete'
  const blocking = (Array.isArray(r.findings) ? r.findings : []).filter(f => f && f.severity !== 'minor')
  const named = f => present(f.file) || present(f.failing_input) || (ruled && (present(f.ac) || present(f.rule)))
  return !fileless && blocking.some(f => !named(f)) ? 'a blocking finding named neither a file nor a failing input' : ''
}
const readReview = async (asked, opts, { fileless = false, ruled = false, optional = false, once = false } = {}) => {
  const lax = { fileless, ruled }
  const prompt = `${asked}${BEFORE_PR ? `\n${REVIEW_TESTS}` : ''}\n${READ_ONLY}`
  const first = await call(prompt, opts, optional)
  const why = unusable(first, lax)
  if (!why) return first
  // A step that may run once only (the live-fault lane's one review) is never asked again: its unusable reply is a lost
  // review.
  if (once) {
    log(`${opts.label}: the reply is no review (${why}); the review is lost`)
    LOST.push(opts.label)
    return null
  }
  log(`${opts.label}: the reply is no review (${why}); the step runs once more`)
  const again = await call(`${prompt}\nAn earlier reply to this step was discarded: ${why}. Finish the review before you reply.`, { ...opts, label: opts.label + AGAIN }, optional)
  if (!unusable(again, lax)) return again
  log(`${opts.label}: the second reply is no review either; the review is lost`)
  LOST.push(opts.label)
  return null
}

// Shared by the fresh setup and the re-deriving resume of a claim_incomplete cont that lacks its location.
const DERIVE_LOCATION = `Run alone and exactly issue-branch --repo-root ${REPO} --issue ${ISSUE}: it prints one JSON line, and branch and worktree_path are its branch and worktree_path. On a non-zero exit refuse (ok=false) with reason branch and the line it wrote to stderr in details. On any refusal set transient true only when the failed command's stderr JSON has transient true anywhere in it.`
// Only a new child's early cont (a stop after the folded claim, whatever fields are missing) can lack its location.
const REDERIVE = !!(CONT && CONT.claim_incomplete && !(CONT.setup && present(CONT.setup.branch) && present(CONT.setup.worktree_path)))
const RES_BRANCH = REDERIVE ? '<branch>' : CONT && CONT.setup && CONT.setup.branch
const RES_PATH = REDERIVE ? '<worktree_path>' : CONT && CONT.setup && CONT.setup.worktree_path
// A worktree left on a detached HEAD at its branch's own tip, with a clean tree, lost nothing: the setup puts it back
// on the branch (a switch, never a reset) and goes on. Any other detached HEAD is left as found and refused.
const REATTACH = (branch, path) => `When HEAD in ${path} is detached (git -C ${path} symbolic-ref -q HEAD fails), put it back on ${branch} first, only when git -C ${path} rev-parse HEAD and git -C ${path} rev-parse refs/heads/${branch} print the same sha and git -C ${path} status --porcelain prints nothing: run git -C ${path} switch ${branch}, alone, and return reattached true. It is the one change this read may make; never reset, and leave any other detached HEAD as it is.`
// Shared by the fresh setup and the incomplete-claim resume: the facts the worktree step chooses its command from.
const EXISTING_READ = (branch, path) => `Read what already exists for the delivery, and change nothing: never reset, clean, restore or stash, and never delete a branch or worktree. ${REATTACH(branch, path)} Return existing with local_branch (a local branch named ${branch} exists), remote_branch (origin/${branch} exists), worktree (the path ${path} exists and is on branch ${branch}), dirty (git -C ${path} status --porcelain is non-empty), status (that output, its first 40 lines) and head (git -C ${path} rev-parse HEAD, or the branch tip when there is no worktree). Omit existing when there is no such branch and no such path. Refuse with reason worktree-mismatch and the path when ${path} is on another branch or ${branch} is checked out at another path.`
// The head the final review passed at, when a resume's cont names one: the setup then reports how HEAD relates to it.
// Both go into the setup's Git commands, so each is a commit id before it is read (a marker that fails is no marker).
const FR_HEAD = CONT && CONT.final_reviewed && isCommit(CONT.final_reviewed.head) ? normSha(CONT.final_reviewed.head) : null
const FR_ACCEPTED = FR_HEAD && Array.isArray(CONT.final_reviewed.accepted) ? CONT.final_reviewed.accepted.filter(isCommit).map(normSha) : []
const BRANCH_READ = CONT && CONT.plan && declared(CONT.plan).length ? ` For each declared branch of the plan (${declared(CONT.plan).map(b => `${b.name} in ${b.worktree}`).join(', ')}) return branch_heads: one {name, head, current, toplevel, common_dir} each, with ${BRANCH_FACTS}; give a missing worktree no entry.` : ''
const SINCE_REVIEWED = FR_HEAD ? ` The final review passed at ${FR_HEAD}: after git -C <worktree> fetch origin, return since_reviewed: same when HEAD is ${FR_HEAD}; merge_only when git -C <worktree> merge-base --is-ancestor ${FR_HEAD} HEAD succeeds, git -C <worktree> rev-list --no-merges ${FR_HEAD}..HEAD ^origin/<integration_branch> prints nothing (the head only gained integration-branch merges), and every merge in git -C <worktree> rev-list --merges ${FR_HEAD}..HEAD ${FR_ACCEPTED.length ? `is one of ${FR_ACCEPTED.join(', ')} or ` : ''}is a clean two-parent merge, meaning git -C <worktree> merge-tree --write-tree <merge>^1 <merge>^2 exits 0 and prints the tree id that git -C <worktree> rev-parse <merge>^{tree} gives (a conflict resolved by hand, or an octopus merge, gives a different tree; never judge this from git show --cc, which omits a hunk where the merge keeps one parent unchanged); else moved.` : ''
// Both lanes' fresh setups renew right after the acquire: an already_held acquire refreshes nothing, and the gate below
// grades the renew whichever the lane. A standard-lane setup also reads the owner's answer to the decision prompt.
const RENEW_STEP = `6. Only when step 5's verdict is already_held (an already_held acquire refreshes nothing), renew the claim: run, alone and exactly, forge-claim renew --repo <slug> --issue ${ISSUE} --holder <host>/${HOLDER_ID} --branch <branch>. It prints one JSON line. ${FORGE_TIMEOUT} Return its verdict (error, with detail, on exit 1 or 2), by, detail and transient (true only when its JSON line has transient true) as renew.
`
const FRESH_READS = `${RENEW_STEP}7. Only when step 5's verdict is acquired or already_held, read the owner's answer to the decision prompt: run alone, exactly, forge-claim owner-action status --repo <slug> --issue ${ISSUE} --reason decision. It prints one JSON line. Change nothing: post nothing, edit nothing, end nothing. Return verdict, comment_id, questions and decisions exactly as printed as answer.
`
const WT_STEP = LANE === 'standard' ? 8 : 7
// A merged PR found only by its head name may be a spec merged from a branch of the same name, so a resume closes out
// only the PR it can name (the number a batch built its cont after merging, or a PR whose own commit list holds a
// commit of cont.done). Identity is by number or commit oid, never by ancestry of base_sha: a squash or rebase merge
// rewrites every commit.
const closingPr = refs => {
  const hit = Array.isArray(refs) ? refs.find(r => isEntry(r) && r.closes === true && Number.isInteger(r.number)) : undefined
  return hit ? hit.number : null
}
const OWN_PR = CONT && Number.isInteger(CONT.pr) ? CONT.pr : null
const OWN_COMMITS = CONT && Array.isArray(CONT.done) ? CONT.done.filter(d => isEntry(d) && typeof d.commit === 'string' && d.commit !== '').map(d => d.commit) : []
// A recorded cont.pr decides alone: a reused branch can list one commit on several merged PRs.
const ownMerged = heads => {
  const list = (Array.isArray(heads) ? heads : []).filter(h => isEntry(h) && Number.isInteger(h.number))
  if (OWN_PR !== null) return list.find(h => h.number === OWN_PR)
  return list.find(h => Array.isArray(h.commits) && h.commits.some(c => OWN_COMMITS.some(o => sameSha(c, o))))
}
const OWN_ID = OWN_PR !== null ? `#${OWN_PR}` : `a PR whose commits include one of ${OWN_COMMITS.join(', ')}`
const setupCall = () => call(CONT ? `You re-adopt issue #${ISSUE} of the git repository at ${REPO} for a resumed delivery. Earlier setup: ${JSON.stringify(CONT.setup)}.
1. ${CONTRACT_READ}${LIVE_STEP}
2. ${REDERIVE ? `${DERIVE_LOCATION} ` : ''}${OWN_PR !== null || OWN_COMMITS.length ? `List the merged PRs whose head is ${RES_BRANCH} (gh pr list --repo <slug> --state merged --head ${RES_BRANCH} --json number) and, for each, its commits (gh pr view <number> --repo <slug> --json commits); return them as merged_heads, one {number, commits} each with every commit oid. This delivery's own merged PR is the one that is ${OWN_ID}: return ok=true with merged_pr set to that PR's number only for it (the worktree may already be gone). Any other merged PR on that head is not this delivery's: leave merged_pr unset for it.` : 'This delivery has no commit and no PR yet, so look for no merged PR and leave merged_pr and merged_heads unset.'}
3. Otherwise confirm: ${CONT.claim_incomplete ? `the issue is open (an earlier claim stopped part way; the next step finishes it)` : `the issue is open; the worktree ${CONT.setup && CONT.setup.worktree} exists and is on branch ${CONT.setup && CONT.setup.branch}${CONT.plan ? `; the plan directory ${CONT.setup && CONT.setup.plan_dir} exists` : ''}. ${REATTACH(CONT.setup && CONT.setup.branch, CONT.setup && CONT.setup.worktree)}`} If any fails, return ok=false with reason not-resumable and the evidence. An open PR whose head is that branch is expected and fine. Set dirty true if git -C <worktree> status --porcelain is non-empty. Return head: git -C <worktree> rev-parse HEAD (the full sha).${SINCE_REVIEWED}${BRANCH_READ}
${CONT.claim_incomplete ? `4. After git -C ${REPO} fetch origin: ${EXISTING_READ(RES_BRANCH, RES_PATH)} An earlier worktree step may have created the branch, the worktree or both before it failed, so report existing afresh.
5.` : '4.'} Return every contract field read fresh, ${REDERIVE ? 'with branch and worktree_path as derived' : 'branch as in the earlier setup'}. Change nothing but that re-attach.
${BASE_RULES}` : `You check issue #${ISSUE} of the git repository at ${REPO} before delivery. Change nothing in this step except one issue comment named below, the claim of step 5 and the worktree of step ${WT_STEP}.
1. ${CONTRACT_READ}${LIVE_STEP}${LANE_RULE_STEP}
2. ${DERIVE_LOCATION} Then gh issue view ${ISSUE} --repo <slug> --json state,labels,title and gh pr list --repo <slug> --state all --search ${ISSUE} --json number,state,headRefName,closingIssuesReferences. Return merged_refs: one {number, closes} per merged PR that list holds, closes true only when its closingIssuesReferences lists issue ${ISSUE}. Refuse (ok=false) with reason closed, parked (label needs-verification or parked), duplicate (a merged PR whose closes is true, a possible duplicate delivery: set duplicate_pr to its number; a merged PR that only mentions or Refs the issue, such as an approved spec merged in its own docs PR, is no duplicate) or open-pr (an open PR referencing this issue whose head is not branch).
3. After git -C ${REPO} fetch origin, re-adopt instead of refusing when the work already exists. ${EXISTING_READ('<branch>', '<worktree_path>')}
4. Read the issue and the code at origin/<integration_branch>: if the issue no longer applies (already fixed or obsolete), comment the evidence on the issue and refuse with reason no-longer-applies. Otherwise return in details, in a few lines, what still applies, where (files and symbols) and what already exists.
5. Only when steps 1 to 4 found no refusal, claim the issue. Run, alone and exactly: forge-claim acquire --repo <slug> --issue ${ISSUE} --holder <host>/${HOLDER_ID} --branch <branch>
It prints one JSON line and adds the in-progress label itself. ${FORGE_TIMEOUT} Return <host>/${HOLDER_ID} as holder, and its verdict (error, with detail, on exit 1 or 2), by, comment_id and transient (true only when its JSON line has transient true) as acquire. When the verdict is neither acquired nor already_held, stop here: run no worktree command and return ok=true with every field above, holder and acquire.
${LANE === 'standard' ? FRESH_READS : RENEW_STEP}${WT_STEP}. Set up the worktree, each command in its own Bash call. An earlier attempt may have done part of this: skip a step already done (the worktree already at <worktree_path> on branch <branch>; the plan directory already there). From the existing you returned: when existing.worktree is true, adopt <worktree_path> as it is and run no worktree command; else when existing.local_branch is true, git -C ${REPO} worktree add <worktree_path> <branch> (adopt the local branch); else when existing.remote_branch is true, git -C ${REPO} worktree add --no-track -b <branch> <worktree_path> origin/<branch> (only the remote branch exists: adopt it); else git -C ${REPO} worktree add --no-track -b <branch> <worktree_path> origin/<integration_branch>. Never reset, clean, restore or stash anything in it. base_sha (full sha) is git -C <worktree_path> merge-base origin/<integration_branch> HEAD for an adopted branch, else the origin/<integration_branch> sha you branched from. plan_dir is <git -C <worktree_path> rev-parse --absolute-git-dir>/deliver-standard; create it. It lives in the worktree's git dir, outside the tree, so the plan never enters a commit.
${WT_STEP + 1}. Return ok=true with branch, worktree_path and every other field above, ${LANE === 'standard' ? 'holder, acquire, renew, answer' : 'holder, acquire, renew'}, and claim: ok, worktree (<worktree_path>), base_sha and plan_dir. A refusal before step 5 returns holder, acquire and claim null. Once the claim step ran, keep ok true: report a worktree failure only as claim with ok=false, the reason and what you already did.
${BASE_RULES}`, { label: 'setup', phase: 'Setup', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'low', schema: CONT ? SETUP_SCHEMA : SETUP_FOLDED })
let setup = await setupCall()
// A refusal marked transient (a forge or network failure) whose reply took no claim is asked once more; the second
// answer stands.
const claimed = r => !!r.acquire && (r.acquire.verdict === 'acquired' || r.acquire.verdict === 'already_held')
if (setup && setup.ok === false && setup.transient === true && !claimed(setup)) setup = await setupCall()
// A fresh reply of ok true that names neither holder nor acquire left its claim fields out, though it may have claimed:
// the setup is asked once more (the acquire and the worktree step are idempotent); a second such reply stops at the
// holder gate below. A reply that names its holder but no acquire stops at claim with a cont.
else if (!CONT && setup && setup.ok === true && !setup.acquire && !present(setup.holder)) setup = await setupCall()
// A lost reply carries no cont, fresh or resumed: a fresh reply that never showed the refusal checks pass must not
// resume past them, and a rerun redoes the full fresh setup (the acquire is idempotent for the same holder).
if (!setup) return { stage: 'setup', result: null, ...deadOf() }
// A marked look read that names no acs array is incomplete: the setup is asked once more, and a second such reply is a
// failed read.
const lookIncomplete = r => !!r && r.ok !== false && isEntry(r.look) && r.look.verdict === 'marked' && !Array.isArray(r.look.acs)
if (lookIncomplete(setup)) setup = await setupCall()
if (!setup) return { stage: 'setup', result: null, ...deadOf() }
if (lookIncomplete(setup)) setup.look = { verdict: 'error', detail: 'look-approval marked named no acs' }
// Said once in the log, never kept: the cont's setup must not claim it for a later run.
if (setup.reattached === true) log('setup: the worktree was on a detached HEAD at its branch tip with a clean tree; it is back on its branch')
delete setup.reattached
// The live-fault read is taken out of setup so no cont keeps it. A standing entry is a declaration of this issue with a
// positive id, a time and a sprint id. A lane-less fresh run becomes live on a standing entry, on a failed read and on
// an ok reply with no usable read, so a declared issue is never planned by mistake. The lane is fixed here, before the
// first exit that builds a cont.
const LIVE_RAW = setup.live_fault
delete setup.live_fault
const RULE_RAW = setup.lane_rule
delete setup.lane_rule
const liveStanding = r => isEntry(r) && r.verdict === 'declared' && typeof r.sprint_id === 'string' && /^[0-9a-f]{16}$/.test(r.sprint_id) && isEntry(r.fault)
  && Number.isInteger(r.fault.issue) && r.fault.issue === Number(ISSUE) && typeof r.fault.at === 'string' && r.fault.at.trim() !== '' && Number.isInteger(r.fault.id) && r.fault.id > 0
const liveText = v => (typeof v === 'string' ? v : '')
const LIVE = liveStanding(LIVE_RAW)
  ? { id: LIVE_RAW.fault.id, sprint_id: LIVE_RAW.sprint_id, issue: LIVE_RAW.fault.issue, observed: liveText(LIVE_RAW.fault.observed), when: liveText(LIVE_RAW.fault.when), proven: liveText(LIVE_RAW.fault.proven), at: LIVE_RAW.fault.at }
  : null
const LIVE_USABLE = liveStanding(LIVE_RAW) || (isEntry(LIVE_RAW) && (LIVE_RAW.verdict === 'none' || LIVE_RAW.verdict === 'no-sprint'))
const LIVE_UNREAD = isEntry(LIVE_RAW) && LIVE_RAW.verdict === 'error' ? true : !LIVE_USABLE && setup.ok === true
if (LIVE_AUTO && (LIVE || LIVE_UNREAD)) LANE = 'live'
else if (RULE_AUTO && isEntry(RULE_RAW) && RULE_RAW.verdict === 'direct') LANE = 'direct'
if (RULE_AUTO && LANE !== 'live') log(`lane: ${LANE} by the lane rule${isEntry(RULE_RAW) && typeof RULE_RAW.reason === 'string' && RULE_RAW.reason.trim() ? `: ${RULE_RAW.reason.split(/\s+/).join(' ')}` : ''}`)
const LIVE_REC = CONT && isEntry(CONT.live_fault) ? { id: CONT.live_fault.id, sprint_id: CONT.live_fault.sprint_id, issue: CONT.live_fault.issue, at: CONT.live_fault.at }
  : LIVE ? { id: LIVE.id, sprint_id: LIVE.sprint_id, issue: LIVE.issue, at: LIVE.at } : null
const liveSame = (a, b) => isEntry(a) && isEntry(b) && a.id === b.id && a.sprint_id === b.sprint_id && a.at === b.at
const LIVE_FINAL = ['live-evidence', 'live-refused', 'live-review', 'live-bound']
const LIVE_WAY = 'deliver the fault in an ordinary delivery: rerun with lane standard and no cont'
// The fresh reply's folded claim, read once and removed so setup (and every cont built from it) keeps its old shape. A
// batch child's folded acquire answers already_held, because the batch's own acquire claimed first and gates the
// readopt path; that acquire refreshes nothing, so the setup renews.
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
if (CLAIM_TAKEN && FOLD_CLAIM && FOLD_CLAIM.ok === true && !present(setup.worktree_path) && present(FOLD_CLAIM.worktree)) setup.worktree_path = FOLD_CLAIM.worktree
const BUILT = present(setup.host) ? `${setup.host}/${HOLDER_ID}` : null
// Every stop after the folded claim was taken keeps a cont that finishes it on resume, whatever fields are missing.
const earlyCont = () => (CLAIM_TAKEN ? { cont: { setup: { ...setup, ...(BUILT && HOLDER_RE.test(BUILT) ? { holder: BUILT } : {}) }, lane: LANE, ...(LANE === 'live' && LIVE_REC ? { live_fault: LIVE_REC } : {}), plan: null, plan_reviewed: false, done: [], fix_waves: 0, claim_incomplete: true } } : {})
// Held by another holder: nothing of ours exists yet, so the stop carries no cont.
if (FOLD_ACQ && (FOLD_ACQ.verdict === 'held_by' || FOLD_ACQ.verdict === 'lost_to')) return { stage: 'claimed', verdict: FOLD_ACQ.verdict, by: FOLD_ACQ.by }
// The folded renew after an already_held acquire is graded before any other setup exit, so a setup failure cannot mask
// a lost renewal. A transient one is left to the owner-answer step, which renews again. Defined before stop(): a stop
// here carries earlyCont's cont.
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
// A resume closes out only a merged PR it can name; a reported merged_pr the facts do not confirm stops before any
// claim or task.
if (CONT) {
  const own = ownMerged(setup.merged_heads)
  if (present(setup.merged_pr) && !(own && own.number === setup.merged_pr)) return { stage: 'setup', result: setup, invalid: 'merged_pr', ...deadOf(), cont: CONT }
  if (own) setup.merged_pr = own.number
}
// No policy is defaulted: a field the contract read did not return stops the run (before any claim on a fresh run).
const missing = ['slug', 'integration_branch', 'default_branch', 'branch', 'merge_strategy', 'delete_branch', 'unset_env', 'verification']
  .concat(CONT && !REDERIVE ? [] : ['worktree_path'])  // a resume's cont.setup holds it unless it re-derives it
  .concat(CONT && CONT.setup && CONT.setup.holder ? [] : ['host'])  // a resume carries the holder in cont.setup
  .filter(f => !present(setup[f]))
for (const k of ['code', 'plan']) {
  const st = setup.review_state && setup.review_state[k]
  if (!present(st)) missing.push(`review_state.${k}`)
  else if (st === 'available' && !(setup.review && present(setup.review[k]))) missing.push(`review.${k}`)
}
const RULE_IDS = PLAN_REVIEW.properties.findings.items.properties.rule.enum
const VERIFY_RULE = 'verify'
// A rules-only revise may settle the findings left when each names a rule and none has source codex, whatever triggered
// the full revise: Codex raises a finding on nearly every plan, so refusing it to every Codex-triggered plan meant the
// revise never ran, while the findings left were the rules re-reviewer's own.
const rulesOnly = rules => rules.length > 0 && rules.every(f => (RULE_IDS.includes(f.rule) || f.rule === VERIFY_RULE) && f.source !== 'codex')
// The Plan section below drops a kept plan with an invalid declaration, and one a plan-review stop kept with findings
// no rules-only revise may settle; no fact of such a plan is demanded here, or a vanished worktree would stop every
// resume.
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
// The Codex plan review was skipped for this unreviewed plan's size (codexSkipped), or is owed on it (codexOwed): an
// applied amend, a late review a revise made due, or a review that stopped before it passed. Both stay in cont while
// the plan is unreviewed, and codexOwed stays set until a Codex plan review comes back available.
let codexSkipped = !!(CONT && CONT.plan && !CONT.plan_reviewed && CONT.codex_plan_skipped === true)
let codexOwed = !!(CONT && CONT.plan && !CONT.plan_reviewed && CONT.codex_plan_owed === true)
const taskLog = CONT && CONT.done ? CONT.done.slice() : []
let claimIncomplete = !!(CONT && CONT.claim_incomplete) || CLAIM_TAKEN
// A partial task's edits stay claimed through any stop until that task is done.
let partial = CONT && CONT.partial !== undefined ? CONT.partial : undefined
let reordered = CONT && Array.isArray(CONT.reordered) ? CONT.reordered.filter(r => r && Number.isInteger(r.task) && Number.isInteger(r.after)) : []
// Fix waves already spent, carried through a resume; declared before stop() because early failures call it.
let fixWaves = (CONT && CONT.fix_waves) || 0
// The final-review rounds that reached a verdict, counted across runs (a lost reviewer, a Codex stop and a skipped
// review count none), and the commit the last review read: {head, branches?, amended?}, each commit id validated on the
// way in (a marker that fails is no marker, and its round is a full review). A cont with neither counts its
// final_reviewed head as one round.
const reviewedOf = r => {
  if (!isEntry(r) || !isCommit(r.head)) return null
  const branches = isEntry(r.branches) ? Object.fromEntries(Object.entries(r.branches).filter(([k, v]) => REF_RE.test(k) && isCommit(v)).map(([k, v]) => [k, normSha(v)])) : {}
  return { head: normSha(r.head), ...(Object.keys(branches).length ? { branches } : {}), ...(r.amended === true ? { amended: true } : {}) }
}
const LEGACY_ROUND = !!CONT && !own(CONT, 'review_rounds') && isEntry(CONT.final_reviewed) && isCommit(CONT.final_reviewed.head)
let reviewRounds = CONT && Number.isInteger(CONT.review_rounds) && CONT.review_rounds > 0 ? CONT.review_rounds : LEGACY_ROUND ? 1 : 0
let reviewed = reviewedOf(CONT && CONT.reviewed) || (LEGACY_ROUND ? reviewedOf({ head: CONT.final_reviewed.head, branches: CONT.final_reviewed.branches }) : null)
// The findings a stop after a review verdict left open, kept in cont.fix_findings until a fix wave's re-review has
// judged them (a wave that answered and failed, and a lost re-review, keep them too; the next round re-checks each
// against the head).
const findingKey = f => `${typeof f.file === 'string' ? f.file : ''}\n${clip(String(f.summary)).toLowerCase().replace(/\s+/g, ' ').trim()}`
let carried = carryOf(CONT && CONT.fix_findings)
// The open findings the bound cut (those of the stop that wrote the cont, and any a hand-edited fix_findings holds
// beyond it): nothing but a full review can find them again, so a round with any is a full one. Every stop that keeps
// open findings goes through keep().
let dropped = (CONT && Number.isInteger(CONT.fix_findings_dropped) && CONT.fix_findings_dropped > 0 ? CONT.fix_findings_dropped : 0) + carryable(CONT && CONT.fix_findings).length - carried.length
const keep = list => { carried = carryOf(list); dropped = carryable(list).length - carried.length }
const markReviewed = head => { if (head) reviewed = { head: normSha(head), ...branchSnap() } }
// The follow-up issues filed for the findings of a scoped round that do not block (followUps), and those whose filing
// was not confirmed (pending); both ride through every stop. An entry needs a file, a summary and the full sha its
// reviewer read it at.
const fullSha = v => typeof v === 'string' && SHA_RE.test(normSha(v))
const textOf = v => (typeof v === 'string' && v.trim() ? clip(v) : '')
const hashOf = s => {
  let a = 0xdeadbeef
  let b = 0x41c6ce57
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i)
    a = Math.imul(a ^ c, 2654435761)
    b = Math.imul(b ^ c, 1597334677)
  }
  a = Math.imul(a ^ (a >>> 16), 2246822507) ^ Math.imul(b ^ (b >>> 13), 3266489909)
  b = Math.imul(b ^ (b >>> 16), 2246822507) ^ Math.imul(a ^ (a >>> 13), 3266489909)
  return (4294967296 * (2097151 & b) + (a >>> 0)).toString(36)
}
const keyOf = f => {
  if (typeof f.key === 'string' && f.key) return f.key
  const full = [f.file, f.summary, f.failing_input].map(v => (typeof v === 'string' ? v.trim() : ''))
  return full.some(v => v.length > REASON_MAX) ? hashOf(full.join('\n')) : ''
}
const followUpOf = (f, filed) => {
  if (!isEntry(f) || !textOf(f.file) || !textOf(f.summary) || !fullSha(f.commit)) return null
  const key = keyOf(f)
  const rest = { file: textOf(f.file), summary: textOf(f.summary), ...(textOf(f.failing_input) ? { failing_input: textOf(f.failing_input) } : {}), commit: normSha(f.commit), ...(key ? { key } : {}), ...(textOf(f.lead) ? { lead: textOf(f.lead) } : {}) }
  if (filed) return Number.isInteger(f.issue) && f.issue > 0 ? { issue: f.issue, ...rest } : null
  return ['critical', 'important', 'minor'].includes(f.severity) ? { severity: f.severity, ...rest } : null
}
let followUps = (CONT && Array.isArray(CONT.follow_ups) ? CONT.follow_ups : []).map(f => followUpOf(f, true)).filter(Boolean)
let pending = (CONT && Array.isArray(CONT.follow_ups_pending) ? CONT.follow_ups_pending : []).map(f => followUpOf(f, false)).filter(Boolean)
let followUpCalls = 0
const followUpKey = f => (f.key ? `${textOf(f.file)}\n${f.key}` : `${textOf(f.file)}\n${clip(String(f.summary))}\n${textOf(f.failing_input)}`)
// The follow-up issues of the findings a scoped round does not block on: one clerk call files one issue per entry. The
// program builds each title (no shell quote character in it) and body; an entry is confirmed only by exactly one issue
// number of its own, so a lost, partial or shared reply leaves it pending, and the gate before Verify files it again.
const titleOf = f => `Follow-up of #${ISSUE}: ${f.file}: ${f.summary}`.replace(/['"`$\\]/g, '').replace(/\s+/g, ' ').slice(0, 120)
const bodyOf = f => [f.lead || `Follow-up of #${ISSUE}: a scoped review round of its delivery raised this ${f.severity} finding, which does not block that delivery.`, '', `File: ${f.file}`, `Commit: ${f.commit}`, `Finding: ${f.summary}`, ...(f.failing_input ? [`Failing input: ${f.failing_input}`] : []), ...(f.key ? [`Identity: ${f.key}`] : [])].join('\n')
const LOOKUP_LIMIT = 1000
const fileFollowUps = async list => {
  const m = ++followUpCalls
  const entries = list.map((f, i) => ({ n: i + 1, title: titleOf(f), body: bodyOf(f) }))
  let r = null
  try {
    r = await call(`Issue #${ISSUE} of ${SLUG}. ${list.every(f => f.lead) ? 'The live-fault lane of this issue left the items below out of the fix or raised them in its diff review; they do not block the merge' : 'A review round after the first full review raised the findings below, which do not block the merge'}: file one follow-up issue for each, changing nothing in any worktree.
Follow-ups: ${JSON.stringify(entries)}
First run once ${UNSET}gh issue list --repo ${SLUG} --state all --search "Follow-up of #${ISSUE} in:title" --limit ${LOOKUP_LIMIT} --json number,body
When that list holds ${LOOKUP_LIMIT} issues it may be cut short: then, before creating any issue, look for each entry on its own with ${UNSET}gh issue list --repo ${SLUG} --state all --search "<the entry's title> in:title" --limit ${LOOKUP_LIMIT} --json number,body, and leave out an entry whose own list also holds ${LOOKUP_LIMIT} issues instead of creating it.
Then, for each entry in order: when an issue of that list has a body equal to the entry's body (trailing whitespace aside), return that issue for the entry and file nothing. Otherwise write the entry's body exactly, as given (its \\n are line breaks), to a new file outside any work tree with a shell command (a heredoc whose delimiter is quoted), then run alone forge-issue create --repo ${SLUG} --title '<the entry's title>' --body-file <that file>, the title being one single-quoted argument exactly as given (it holds no quote, dollar sign, backtick or backslash) and no blocking-edge flag, since the body names the parent.
Return filed: one {n, issue} per entry you filed or found, leaving out one you could not file or confirm.
${RULES}`, { label: `follow-ups-${m}`, phase: 'Final review', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: FOLLOW_UPS })
  } catch (e) {
    r = null
  }
  const got = r && Array.isArray(r.filed) ? r.filed.filter(x => isEntry(x) && Number.isInteger(x.n) && Number.isInteger(x.issue) && x.issue > 0) : []
  let left = 0
  list.forEach((f, i) => {
    const mine = got.filter(x => x.n === i + 1)
    const issue = mine.length === 1 ? mine[0].issue : null
    if (issue !== null && got.filter(x => x.issue === issue).length === 1 && !followUps.some(g => g.issue === issue)) {
      const { severity, ...rest } = f
      followUps.push({ issue, ...rest })
    } else {
      pending.push(f)
      left++
    }
  })
  log(`final review: ${list.length - left} follow-up issue(s) filed for findings that do not block`)
  if (left) log(`final review: ${left} follow-up(s) not confirmed filed; they are kept and filed before verify`)
}
// The history of a file the fix waves went back and forth on, kept in cont.oscillating beside the findings that stop
// left open; bounded on the way out and on the way in (the last ROUNDS_MAX entries, each round's findings and every
// text capped).
const ROUNDS_MAX = 12
const roundsOf = list => list.filter(isEntry).slice(-ROUNDS_MAX).map(x => ({ ...(Number.isInteger(x.round) ? { round: x.round } : {}), ...(Number.isInteger(x.wave) ? { wave: x.wave } : {}), ...(Array.isArray(x.findings) ? { findings: x.findings.filter(v => typeof v === 'string').slice(0, CARRY_MAX).map(clip) } : {}), ...(typeof x.notes === 'string' && x.notes ? { notes: clip(x.notes) } : {}), ...(typeof x.range === 'string' && x.range ? { range: clip(x.range) } : {}) }))
let osc = OSC_KEPT ? { file: clip(OSC_KEPT.file.trim()), rounds: roundsOf(OSC_KEPT.rounds) } : null
let oscPending = oscDecision !== null
let capPending = capDecision !== null
// The blocking findings left on a plan this delivery dropped after its review (a second failed rules revise, a kept
// plan no rules revise may settle, a revise that came back as questions or not well formed). Kept in
// cont.prior_findings until a plan passes review, newest first and bounded as the fix findings are, so the next planner
// does not rediscover them.
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
  codexSkipped = false
  codexOwed = false
}
const CARRIED_AT_START = carried
// Fix waves that do not converge: a fix-wave-review stop that leaves findings open once the waves spent across runs
// have reached FIX_WAVES_BOUND, with a finding left in a file the findings carried into this run already named, is
// marked diverging: { file, waves }, so the owner decides the design. A first run carries no findings in, so it is
// never marked; neither is a resume whose open findings are all in other files.
const FIX_WAVES_BOUND = 4
// Reviewers name one file as path, ./path, an absolute path under the worktree, path:line, path:line-line,
// path:line:column or path#L<line> (#L<line>-L<line> too): the marker names the file as the path relative to the
// worktree without the surrounding whitespace, a leading ./ and that trailing position; nothing else is folded, case
// included.
const fileOf = f => {
  if (typeof f.file !== 'string') return ''
  let p = f.file.trim().replace(/#L\d+(?:-L?\d+)?$/, '').replace(/:\d+(?:[-:]\d+)?$/, '').trim()
  const roots = [setup && setup.worktree, setup && setup.worktree_path].filter(r => typeof r === 'string' && r.startsWith('/')).map(r => r.replace(/\/+$/, ''))
  for (const r of roots) if (r && p.startsWith(`${r}/`)) { p = p.slice(r.length + 1); break }
  return p.replace(/^(?:\.\/)+/, '').trim()
}
// The files a fix wave's commits changed, for admitting a new finding in one of them to the next wave. The program
// reads no repository, so the list is one git diff --no-renames --name-only <start_head>..<commit> in the issue
// worktree, asked of the wave's implementer and its re-reviewer. A file counts only when both list it, so neither one's
// word admits a wave alone. A wrong list can only earn a wave that MAX_WAVES bounds and a re-review follows.
const CHANGED_CMD = range => `git -C ${W} diff --no-renames --name-only ${range}`
const changedBy = r => (r && Array.isArray(r.changed_files) ? r.changed_files : []).map(file => fileOf({ file })).filter(Boolean)
const divergingOf = left => {
  if (fixWaves < FIX_WAVES_BOUND) return null
  const hit = left.map(fileOf).find(f => f && CARRIED_AT_START.map(fileOf).includes(f))
  return hit ? { file: hit, waves: fixWaves } : null
}
let finalReviewed = (CONT && CONT.final_reviewed) || null
// The stages between a sync merge and its acceptance: a stop there must not carry a marker over the unreviewed merge.
const SYNC_WINDOW = ['sync', 'sync-review', 'sync-fix']
// Ship fix waves already spent (a red check, a sync-review finding): one each per delivery, carried through a resume.
let checksFixes = (CONT && CONT.checks_fixes) || 0
let syncFixes = (CONT && CONT.sync_fixes) || 0
let verified = (CONT && CONT.verified) || null
const UNTESTED_STAGES = ['checks-fix', 'sync-fix', 'look-fix']
const untestedOf = u => (isEntry(u) && UNTESTED_STAGES.includes(u.stage) && present(u.head) && present(u.start_head) ? { stage: u.stage, start_head: String(u.start_head), head: String(u.head) } : null)
let untested = untestedOf(CONT && CONT.untested)
// A push-bound fix reply that moved the head and records no test command is carried in cont.untested so a resume
// retests it before any push; true when it recorded one. The commit is compared with before, the head the program knew
// when it asked for the fix, never with the start_head the reply names, which can name another head all the same. A
// range already pending keeps its start: the retest covers everything since the earliest untested commit.
const noteUntested = (stage, f, before) => {
  const from = present(before) ? before : f && present(f.start_head) ? f.start_head : null
  if (!f || !present(f.commit) || !present(from) || sameSha(f.commit, from) || tested(f)) return false
  untested = { stage, start_head: untested ? untested.start_head : String(from), head: String(f.commit) }
  return true
}
const LOOK = isEntry(setup.look) ? setup.look : null
const LOOK_READ = !!LOOK && (LOOK.verdict === 'marked' || LOOK.verdict === 'unmarked')
const MARKED = LOOK_READ && LOOK.verdict === 'marked'
const COVERS = MARKED && Array.isArray(LOOK.covers) ? LOOK.covers.filter(c => typeof c === 'string' && c.trim()) : []
const acsOf = xs => (Array.isArray(xs) ? xs : []).filter(a => typeof a === 'string' && a.trim()).map(a => a.trim().toUpperCase())
const LOOK_ACS = MARKED ? acsOf(LOOK.acs) : []
let lookAcs = CONT && CONT.plan && Array.isArray(CONT.look_acs) ? acsOf(CONT.look_acs) : LOOK_ACS
const LOOK_REASON = `issue ${ISSUE} needs the owner's look before merge`
const LOOK_WAYS = `Resume with cont and look {answer: approve, head: <head>, message?} to land on the approval recorded for that head (the owner records it where they answered; this program never posts one, so an approve with none recorded stops), or look {answer: fix, head: <head>, words: <the owner's words>, message?} to approve that head with one fix, or look {answer: changes, words: <the owner's words>} to ask for a change.`
// The head the owner's approval was recorded for (an approved cont carries it); a marked delivery stops at
// awaiting-look until it holds one. The pull request and head the stop left for the owner ride in cont.look; a resume
// keeps it only when well formed.
const lookOf = l => (isEntry(l) && Number.isInteger(l.pr) && l.pr > 0 && typeof l.head === 'string' && SHA_RE.test(l.head) ? { pr: l.pr, head: l.head, ...(typeof l.approved === 'string' && SHA_RE.test(l.approved) ? { approved: l.approved, ...(typeof l.owner === 'string' && SHA_RE.test(l.owner) ? { owner: l.owner } : {}) } : {}) } : null)
let lookAt = lookOf(CONT && CONT.look)
let approvedHead = lookAt && lookAt.approved ? lookAt.approved : null
let ownerHead = approvedHead && lookAt.owner ? lookAt.owner : approvedHead
// The look entry of cont for an approved head: owner is there only when the approved head is not the owner's own.
const approvedLook = (pr, head) => ({ pr, head, approved: head, ...(ownerHead && ownerHead !== head ? { owner: ownerHead } : {}) })
let LOOK_STOP = MARKED && approvedHead === null
const outsideOf = xs => (Array.isArray(xs) ? xs : []).filter(x => isEntry(x) && present(x.file) && present(x.why)).map(x => ({ file: String(x.file), why: String(x.why).slice(0, REASON_MAX) }))
const outsideFixes = outsideOf(CONT && CONT.outside_fixes)
let decisions = []
const addDecision = text => { if (typeof text === 'string' && text.trim() && !decisions.includes(text)) decisions.push(text) }
if (CONT && Array.isArray(CONT.decisions)) CONT.decisions.forEach(addDecision)
if (!RERUN_WORD) addDecision(args.decisions)
let amendApplied = false
let blocked = RERUN ? null : BLOCKED
let decisionPending = newDecision !== null
const keptDecisions = () => decisions.filter(d => !(decisionPending && d === newDecision) && !(oscPending && d === oscDecision) && !(capPending && d === capDecision))
const blockedKept = () => !!blocked && (LANE !== 'standard' || !!plan) && !taskLog.some(d => d.n === blocked.task)
// Why an owner's approval was not recorded, naming the approved head and the head found; once set, every later stop's
// reason starts with it.
let lookWhy = null
// A live stop that names the ordinary delivery as its way on is final: its cont says so, and a resume stops at once. A
// live-review stop is final only when it carries findings or the review answered with no usable review.
const liveFinalOf = (stage, extra) => (LIVE_FINAL.includes(stage) && (stage !== 'live-review' || !!(extra && extra.findings) || LOST.includes('live-review')) ? stage
  : CONT && isEntry(CONT.live_fault) && LIVE_FINAL.includes(CONT.live_fault.final) ? CONT.live_fault.final : null)
const stop = (stage, extra) => {
  const fr = SYNC_WINDOW.includes(stage) ? (finalReviewed = null) : finalReviewed
  const liveFinal = LANE === 'live' && LIVE_REC ? liveFinalOf(stage, extra) : null
  return { stage, ...extra, ...(stage === 'planned' || stage === 'ready' ? {} : { reason: lookWhy ? `${lookWhy}; ${stopReason(stage, extra || {})}` : stopReason(stage, extra || {}) }), ...(amendApplied ? { amended: true } : {}), ...deadOf(), cont: { setup, lane: LANE, ...(LANE === 'live' && LIVE_REC ? { live_fault: { ...LIVE_REC, ...(liveFinal ? { final: liveFinal } : {}) } } : {}), plan, plan_reviewed: planReviewed, ...(plan && !planReviewed && planFindingsKept ? { plan_findings: planFindingsKept } : {}), ...(plan && !planReviewed && codexSkipped ? { codex_plan_skipped: true } : {}), ...(plan && !planReviewed && codexOwed ? { codex_plan_owed: true } : {}), ...(!planReviewed && priorFindings.length ? { prior_findings: priorFindings } : {}), ...(keptDecisions().length ? { decisions: keptDecisions() } : {}), done: taskLog, ...(OWN_PR !== null ? { pr: OWN_PR } : {}), fix_waves: fixWaves, ...(carried.length ? { fix_findings: carried } : {}), ...(carried.length && osc ? { oscillating: osc } : {}), ...(carried.length && capMark ? { round_cap: capMark } : {}), ...(dropped > 0 && carried.length ? { fix_findings_dropped: dropped } : {}), ...(reviewRounds > 0 ? { review_rounds: reviewRounds } : {}), ...(reviewRounds > 0 && reviewed ? { reviewed } : {}), ...(followUps.length ? { follow_ups: followUps } : {}), ...(pending.length ? { follow_ups_pending: pending } : {}), ...(checksFixes ? { checks_fixes: checksFixes } : {}), ...(syncFixes ? { sync_fixes: syncFixes } : {}), ...(verified ? { verified } : {}), ...(untested ? { untested } : {}), ...(lookAt ? { look: lookAt } : {}), ...(plan && lookAcs.length ? { look_acs: lookAcs } : {}), ...(outsideFixes.length ? { outside_fixes: outsideFixes } : {}), ...(fr ? { final_reviewed: fr } : {}), ...(claimIncomplete ? { claim_incomplete: true } : {}), ...(partial !== undefined ? { partial } : {}), ...(blockedKept() ? { blocked } : {}), ...(reordered.length ? { reordered } : {}) } }
}

const liveCommit = () => taskLog.find(d => d.n === 1).commit
const liveBound = (details, extra) => stop('live-bound', { ...extra, details: details + '; ' + LIVE_WAY })

// The plan directory is a checkout path and may hold spaces, quotes or shell metacharacters, so the clerk's two
// commands name it shell-quoted (bare when every character is plain, else in single quotes with each embedded one
// written '\'').
const shq = text => /^[A-Za-z0-9_\/.:@%+=,-]+$/.test(text) ? text : `'${text.replace(/'/g, `'\\''`)}'`
const LOOK_UNREAD = () => stop('look', { details: clip(`the look marker of issue ${ISSUE} was not read: ${LOOK && present(LOOK.detail) ? LOOK.detail : 'no verdict'}`) })

const haltTask = (n, stage, extra) => { const s = stop(stage, extra); return { ...s, cont: { ...s.cont, partial: n } } }
// A task stop on an implementer that returned blocked keeps its notes in the cont and names the ways out in its reason.
const haltImpl = (n, extra) => {
  const said = isEntry(extra.impl) && extra.impl.status === 'blocked'
  if (said) blocked = { task: n, notes: typeof extra.impl.notes === 'string' ? extra.impl.notes.slice(0, NOTES_MAX) : '' }
  return haltTask(n, 'task', said ? { ...extra, ways: waysOut() } : extra)
}

if (CONT && setup.dirty && !setup.merged_pr && partial === undefined) {
  return stop('dirty', { details: `the worktree ${setup.worktree} has uncommitted changes no task claims; commit or discard them, then resume` })
}

const SLUG = setup.slug, INT = setup.integration_branch, STRATEGY = setup.merge_strategy
const LAND_ACQUIRE = (sha, wait) => `forge-claim land acquire --repo ${SLUG} --branch ${INT} --sha ${sha}${wait ? ' --wait' : ''}`
const LOCK_RETURN = `Return its verdict (acquired, already_held, moved, land-contended, held_by, lost_to, or error on any other exit), lock_sha, by, detail, waited_s and waited_on from its output, and position and ahead when it prints them. ${FORGE_TIMEOUT}`
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
// Before a pull request exists, every local verification runs the pre-pull-request list when the contract sets one;
// the pull request's required checks gate landing. VERIFY_IDS and PRE_COMMIT keep reading the declared verification.
// A missing, empty or non-array member is absent, so the declared verification runs.
const BEFORE_PR = Array.isArray(setup.verification_before_pull_request) && setup.verification_before_pull_request.length > 0
const LOCAL = BEFORE_PR ? setup.verification_before_pull_request : setup.verification
const LOCAL_IDS = LOCAL.map(e => e.id)
// The same text in deliver-batch.js.
const PRE_PR_EVIDENCE = 'the verification above ran the pre-pull-request list, and CI on this pull request runs the full declared verification'
// With the list set, every step that runs tests names its commands: the same texts in deliver-batch.js. An
// implementer's pre-commit checks or formatter (FMT) stay in force beside them, so each sentence that limits the
// commands run says only what this prompt asks before committing stays.
const LOCAL_CMDS = JSON.stringify(LOCAL.map(e => ({ id: e.id, argv: e.argv, cwd: e.cwd })))
const ONLY_PRE_COMMIT = 'only what this prompt says to run before committing'
const RUN_LATER = `the delivery runs its pre-pull-request commands ${LOCAL_CMDS} itself, and the pull request's checks run the rest`
const REVIEW_TESTS = `Run only the targeted tests a finding needs and no command the project declares: ${RUN_LATER}.`
const PLAN_TESTS = `Run no command the project declares: ${RUN_LATER}.`
const PR_TESTS = `Run no test and no command the project declares: ${RUN_LATER}.`
const SYNC_TESTS = (wt, int, from) => `For a clean merge that changes none of the pull request's files (no path that git -C ${wt} diff --no-renames --name-only ${from} HEAD prints is among the paths git -C ${wt} diff --no-renames --name-only origin/${int}...HEAD prints), run no test and, of the commands the project declares, ${ONLY_PRE_COMMIT}; for any other, run the pre-pull-request commands ${LOCAL_CMDS} as well.`
const commandOutside = c => {
  if (!c || typeof c !== 'object' || c.kind !== 'evidence' || !c.run || typeof c.run !== 'object') return false
  const command = typeof c.run.command === 'string' ? c.run.command : (c.run.then && typeof c.run.then.command === 'string' ? c.run.then.command : null)
  return command !== null && !VERIFY_IDS.includes(command)
}

const OPEN_KINDS = ['evidence', 'human']
const isOpen = a => !!(a && OPEN_KINDS.includes(a.kind))
const ACCEPT_KINDS = ['code', 'evidence', 'human', 'note']
const badKinds = acceptance => acceptance.filter(a => !(a && ACCEPT_KINDS.includes(a.kind))).map(a => (a && a.id) || null)
const SHA40 = /^[0-9a-f]{40}$/
const asksOwner = v => !!v && typeof v === 'object' && (v.kind === 'human' || (!!v.run && typeof v.run === 'object' && (Object.prototype.hasOwnProperty.call(v.run, 'ask') || Object.prototype.hasOwnProperty.call(v.run, 'act'))))
const HUMAN_REFUSED = (ids, issues) => `${ids.join(', ')} ${ids.length === 1 ? 'is a criterion' : 'are criteria'} of kind code or evidence, and a hold never makes one a human check (kind human, an ask or an act run): hold an evidence criterion as a kind evidence check the runner settles by itself (a verification command, a committed script or a probe)` + (issues.length ? `. The verify fence of the hold comment on ${issues.map(n => '#' + n).join(', ')} already holds such a check: remove it from that fence, or delete that comment and remove the needs-verification label, by hand before resuming, since a resume reads the posted fence again` : '') + ', then resume'

// The invocation the runner makes for a check that runs a committed script: the path, the commit it checks out (run.at,
// else the block's merge) and the ordered args. Two checks run the same script only when all three match.
const scriptRun = (check, merge) => {
  const run = check && typeof check === 'object' ? check.run : null
  if (!run || typeof run !== 'object' || typeof run.script !== 'string') return null
  return JSON.stringify([run.script, typeof run.at === 'string' ? run.at : merge, Array.isArray(run.args) ? run.args : []])
}
const OWNER_REFUSED = (ids, issues) => `${ids.join(', ')} ${ids.length === 1 ? 'is a human criterion' : 'are human criteria'} and only a check that asks the owner (kind human, an ask or an act run) settles one: hold it as such a check, never one a machine settles` + (issues.length ? `. The verify fence of the hold comment on ${issues.map(n => '#' + n).join(', ')} already holds another check for it: remove that check from the fence, or delete that comment and remove the needs-verification label, by hand before resuming, since a resume reads the posted fence again` : '') + ', then resume'
const SCRIPT_REFUSED = (ids, issues) => `${ids.join(', ')} ${ids.length === 1 ? 'is' : 'are'} held without the committed verification script ${ids.length === 1 ? 'its' : 'their'} verify member runs (the same path, commit and args): hold each as a kind evidence check running that script unchanged` + (issues.length ? `. Fix the verify fence of the hold comment on ${issues.map(n => '#' + n).join(', ')} by hand before resuming` : '') + ', then resume'

const RUN_OK = r => !!(r && r.ran === true && r.exit === 0)
const LINT_V = { type: 'object', properties: { ok: { type: 'boolean' }, errors: { type: 'array' } } }
const RUN_V = { type: 'object', properties: { ran: { type: 'boolean' }, exit: { type: 'integer' } }, required: ['ran', 'exit'] }
const RELEASE_SCHEMA = { type: 'object', properties: { verdict: { type: 'string' }, detail: { type: 'string' } }, required: ['verdict'] }
const LOOK_TICK_SCHEMA = { type: 'object', properties: { verdict: { type: 'string' }, ticked: { type: 'integer' }, detail: { type: 'string' } }, required: ['verdict'] }
const HOLD_SCHEMA = { type: 'object', properties: {
  merge_commit_local: { type: 'boolean' }, code_unmet: STRS, blocks: { type: 'array', items: { type: 'integer' } },
  split: { type: 'array', items: { type: 'object', properties: { ac: { type: 'string' }, issue: { type: 'integer' }, block: { type: 'object' }, lint: LINT_V, verify_run: RUN_V, issue_state: { type: 'string' } }, required: ['ac', 'issue', 'lint', 'verify_run', 'issue_state'] } },
  block: { type: 'object' }, lint: LINT_V, verify_run: RUN_V, issue_state: { type: 'string' }, already_closed: { type: 'boolean' }, notes: { type: 'string' } },
  required: ['merge_commit_local', 'code_unmet', 'issue_state', 'notes'] }
// The reply of the read-only hold-draft call: the merge commit, the fences already posted and the checks written for
// the criteria that carry no verify member. Declared above closeOut: the merged-PR resume calls it before later consts
// run.
const HOLD_DRAFT_SCHEMA = { type: 'object', properties: { complete: { type: 'boolean' }, merge: { type: 'string' }, written: { type: 'array', items: { type: 'object' } }, posted: { type: 'array', items: { type: 'object', properties: { issue: { type: 'integer' }, merge: { type: 'string' }, checks: { type: 'array' } }, required: ['issue', 'checks'] } }, detail: { type: 'string' } }, required: ['complete', 'written', 'posted'] }
const LOOK_STALE_SCHEMA = { type: 'object', properties: { complete: { type: 'boolean' }, stale: { type: 'array', items: { type: 'object', properties: { issue: { type: 'integer' }, acs: STRS, results: { type: 'boolean' } }, required: ['issue', 'acs', 'results'] } }, detail: { type: 'string' } }, required: ['complete', 'stale'] }
const STATES = ['OPEN', 'CLOSED']

const covers = (checks, ids) => ids.filter(id => !checks.some(c => c && c.ac === id))

const INDIRECT_FOR = (PR, fail, same = false) => ` When that mergeCommit is null${same ? ', or when its oid equals headRefOid (the forge records a PR merged indirectly with its own head as the merge commit too)' : ''}, read gh pr view ${PR} --repo ${SLUG} --json state: only when it is MERGED (the PR was merged indirectly: its head reached ${INT} through another PR's merge), confirm git -C ${REPO} merge-base --is-ancestor <headRefOid> origin/${INT} succeeds, then run git -C ${REPO} rev-list --first-parent <headRefOid>..origin/${INT} (the first-parent line of origin/${INT}, newest first) and git -C ${REPO} rev-list --ancestry-path <headRefOid>..origin/${INT} (the commits that contain the head): ${same ? `when the last commit of the first list has <headRefOid> as its first parent (git -C ${REPO} rev-parse <that commit>^1), whatever mergeCommit is (null or the head's own oid), the head itself is on the first-parent line, so it landed as itself (a fast-forward): no commit before the head names the tip of ${INT} before the landing, and the first commit that contains the head is the head's own child, never a landing commit, so return ${fail} and stop here; otherwise ` : ''}the merge commit is the last commit of the first list that is also in the second (the first commit on the first-parent line that contains the head); when the first list is empty, the tip of origin/${INT} is the head itself and ${same ? `it landed as itself: return ${fail} and stop here` : 'the merge commit is <headRefOid>'}. When the state is not MERGED or the head is not an ancestor, return ${fail} and stop here.`
// The folded release reply of this run's hold call, or null.
let landRelease = null
// The landing commit a merged replay resolved before it judged the approval; its tick names it too.
let landedCommit = null
// The declaration the live-fault lane's pull request names; it holds no quote, dollar sign, backtick or backslash.
const LIVE_LINE = () => `Live-fault lane: declaration ${LIVE_REC.id} of sprint ${LIVE_REC.sprint_id} for issue #${LIVE_REC.issue}, declared ${LIVE_REC.at}`
// The seconds from the declaration to the green time, kept to the microsecond (the first-use verifier compares them
// unrounded), or null when either is unreadable or green is before the declaration. The timing is reported, never a
// gate: an unread, failed or pending green time still lands the delivery.
const secondsBetween = (declaredAt, greenAt) => {
  const us = v => {
    const m = typeof v === 'string' ? /^([^.]*?)(?:\.(\d+))?(Z|[+-]\d\d:?\d\d)?$/.exec(v.trim()) : null
    const whole = m ? Date.parse(m[1] + (m[3] || '')) : NaN
    return Number.isFinite(whole) ? BigInt(whole) * 1000n + BigInt(((m[2] || '') + '000000').slice(0, 6)) : null
  }
  const d = us(declaredAt), g = us(greenAt)
  return d !== null && g !== null && g >= d ? Number(g - d) / 1e6 : null
}
const LIVE_GREEN = { type: 'object', properties: { state: { enum: ['green', 'failed', 'pending', 'error'] }, head: FULL_SHA, green_at: { type: ['string', 'null'] }, detail: { type: 'string' } }, required: ['state'] }
// The timing is reported, never a gate: an unread, failed or pending green time still lands the delivery.
const liveTiming = async PR => {
  let green = null
  try {
    green = await call(`Issue #${ISSUE} of ${SLUG}: read when the pull request #${PR} went green, changing nothing: post, edit, label and run nothing else. Run alone and exactly: pr-green --repo ${SLUG} --pr ${PR}
It prints one JSON line. Return its state, head and green_at (error as state, with the stderr line as detail, on exit 2). Run nothing else.
${RULES_FOR(setup.worktree || '<worktree>')}`, { label: 'live-green', phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: LIVE_GREEN }, true)
  } catch (error) {
    green = null
  }
  const read = isEntry(green) && green.state === 'green' && sameSha(green.head, liveCommit()) && typeof green.green_at === 'string' ? green.green_at : null
  const seconds = read === null ? null : secondsBetween(LIVE_REC.at, read)
  const within = seconds !== null && seconds <= 3600
  log(read === null || seconds === null ? `live fault ${LIVE_REC.id}: no green time was read (${isEntry(green) && typeof green.state === 'string' ? green.state : 'no reply'})` : `live fault ${LIVE_REC.id}: declared ${LIVE_REC.at}, green ${read}: ${seconds} s, ${within ? 'within' : 'over'} the hour`)
  return { id: LIVE_REC.id, sprint_id: LIVE_REC.sprint_id, issue: LIVE_REC.issue, declared_at: LIVE_REC.at, pr: PR, green_at: read, seconds, within_hour: within }
}

const closeOut = async (PR, mergeCommit, W, prHead, lock = null) => {
  const planned = plan ? plan.acceptance : null
  const acceptance = planned && MARKED && approvedHead ? planned.filter(a => !(a && typeof a.id === 'string' && lookAcs.includes(a.id.toUpperCase()))) : planned
  if (!acceptance) return stop('close-out', { pr: PR, details: 'merged, but no plan acceptance to grade the issue against; close out by hand' })
  const unknown = badKinds(acceptance)
  if (unknown.length) return stop('close-out', { pr: PR, details: 'merged, but a plan criterion has a kind that is not code, evidence, human or note; close out by hand', bad_kinds: unknown })
  const answered = planned.filter(a => !acceptance.includes(a)).map(a => a && a.id)
  const upId = v => typeof v === 'string' ? v.toUpperCase() : v
  const isAnswered = v => answered.some(a => upId(a) === upId(v))
  const noHold = !acceptance.some(isOpen)
  const openCriteria = acceptance.filter(isOpen)
  const notes = acceptance.filter(a => a && a.kind === 'note')
  const machine = acceptance.filter(a => a && (a.kind === 'code' || a.kind === 'evidence') && typeof a.id === 'string')
  const machineOf = v => { const a = machine.find(m => upId(m.id) === upId(v)); return a ? a.id : null }
  const humanFor = checks => [...new Set(checks.filter(c => asksOwner(c)).map(c => machineOf(c.ac)).filter(id => id !== null))]
  const humans = acceptance.filter(a => a && a.kind === 'human' && typeof a.id === 'string')
  const humanOf = v => { const a = humans.find(m => upId(m.id) === upId(v)); return a ? a.id : null }
  const notOwnerFor = checks => [...new Set(checks.filter(c => c && typeof c === 'object' && !asksOwner(c)).map(c => humanOf(c.ac)).filter(id => id !== null))]
  // Ship regrades the code rows for every plan; a plan with a non-code row is then held by the acceptance-planning
  // rules' "Linting a hold" procedure. A replay of a PR merged indirectly has already resolved the landing commit
  // (landedCommit), so the hold and the look-stale read are given it, not asked to resolve it again.
  const known = mergeCommit || landedCommit
  const merged = known ? known : `read from gh pr view ${PR} --repo ${SLUG} --json mergeCommit,headRefOid`
  const indirect = known ? '' : INDIRECT_FOR(PR, 'merge_commit_local false')
  const heldBlock = authorized => noHold ? '' : `
4. Read the issues this one blocks: gh api repos/${SLUG}/issues/${ISSUE}/dependencies/blocking (their numbers, returned as blocks).
5. When blocks is non-empty, move each human criterion into its own new issue that blocks no other issue (forge-issue create --repo ${SLUG}, its body naming #${ISSUE}), hold that issue by step 6 with only that criterion's check (no --blocks flag; its once-run uses --issue <child>${answered.length ? `; no child's verify fence may hold a check for ${answered.join(', ')}: when a hold of that child already exists and its fence names any of them, edit that comment in place as step 6 does, before that child's once-run` : ''}), and return one split entry per moved criterion with its issue, block, lint, verify_run and issue_state.
6. For the criteria left (evidence or human, not split): none left means close #${ISSUE} with a comment naming the evidence and the split issues. Otherwise assemble one hold comment: a line per criterion, then exactly one \`\`\`verify fence holding {"v": 1, "merge": <the merge commit>, "checks": [...]} built from each criterion's verify member with every occurrence of the base sha ${setup.base_sha} replaced by the merge commit (a criterion without a verify member gets one written per ~/.agents/standards/acceptance-planning.md; an unattended evidence command run must be one of ${JSON.stringify(VERIFY_IDS)}, else use a script or a probe). Write it to a file outside any work tree and run verify-pending lint --input <file> --repo-root ${REPO} --pr-head ${prHead || '<the headRefOid read in step 1>'} --pr-branch ${setup.branch} plus one --pr-workflow <name> per distinct workflow of gh pr checks ${PR} --repo ${SLUG} --json workflow and one --blocks <n> per blocked issue. On refusal post nothing and return its verdict as lint. Otherwise, when no hold comment with a verify fence exists yet, gh issue comment ${ISSUE} --repo ${SLUG} --body-file <file> (when one exists, post nothing: write its fence JSON to the file and lint that, so lint is still returned), add the needs-verification label (create it if missing), then run alone, once, even when an earlier attempt ran it: verify-pending run --host ${setup.host} --repo ${SLUG} --issue ${ISSUE}. ${answered.length ? `The owner's look approval answers ${answered.join(', ')}, so no check for it may stand in the verify fence: when a hold comment with a verify fence already exists and its checks name any of them, remove those checks (an id compared ignoring case) from the fence JSON and their lines from the comment text, edit that comment in place (gh api --method PATCH repos/${SLUG}/issues/comments/<comment id> --field body=@<file>), then lint the reduced fence and run the once-run, never before the edit. ` : ''}Return block (the posted JSON, as it stands in the comment after any such edit), lint, verify_run (ran, exit) and issue_state read back from the tracker. The program has built and checked those checks: post exactly the checks of the Checks line below, unchanged, never one of your own; this issue's fence holds those of the criteria not split, a split child's fence only its own criterion's check.
Checks: ${JSON.stringify(authorized)}`
  // A hold posted before the approval was read (by an earlier landing, or on a child it split) may still check a
  // criterion the approval answers, so it is read before the hold call. A cross-referencing issue counts as a split
  // child only when its fence's merge is this PR's merge commit, since AC ids are local to each issue. A check on a
  // split child, or on this issue with nothing left to hold, is not the hold's to remove, so the landing stops; so does
  // one whose hold has recorded results, because rewriting that block discards them. Otherwise step 6 removes it in

  // place.
  const FENCE_READ = `1. Run gh issue view ${ISSUE} --repo ${SLUG} --json state. Only when it is OPEN, run gh api repos/${SLUG}/issues/${ISSUE}/comments --paginate and select the comment the verification runner would use: the newest by id whose author_association is OWNER or MEMBER, whose first line is not a marker (a marker comment's first line, without a trailing carriage return, is exactly <!-- agent:KIND v1, then zero or more space-separated key=value fields, then -->, KIND being lowercase letters, digits and hyphens that start with a letter) and whose body holds a \`\`\`verify fence.
2. Run gh api repos/${SLUG}/issues/${ISSUE}/timeline --paginate. For each cross-referenced event whose source issue is an issue (it has no pull_request key) of ${SLUG} and is OPEN, run gh api repos/${SLUG}/issues/<that issue>/comments --paginate and make the same selection. Such an issue is a split of #${ISSUE} only when its selected fence's merge member is the merge commit of PR ${PR} (${merged}); an issue whose fence names any other merge only mentions #${ISSUE}, is none of this landing's holds, and is left out.`
  if (answered.length) {
    const st = await call(`Issue #${ISSUE} of ${SLUG}: PR #${PR} is merged into ${INT}, and the owner's look approval answers ${answered.join(', ')}. Read whether an earlier hold still checks any of those criteria, changing nothing: post, edit, label and run nothing else, and run no verify-pending command. Each command in its own Bash call:
${FENCE_READ}
For each selected fence also read whether the runner has recorded or asked anything for that block: a trusted marker comment (author_association OWNER or MEMBER, a marker by the first-line rule above, a greater id than the selected comment) whose block field starts with the selected comment's id and a dot (block=<selected comment id>.<digest>) counts, whatever its kind: a verify-result and a prompt to the owner for one of its checks both do, since rewriting that block would change its version and discard those results and the owner's pending answers. A comment that is not such a marker, is not trusted, or names another block (or none) counts for nothing. That is results for that issue.
Return stale: one {issue, acs, results} per issue whose selected fence has a check whose ac is one of ${answered.join(', ')} (compared ignoring case; acs are those ids as the fence spells them, an id compared ignoring case: ac2 is AC2; results true or false as just read), or [] when none does. Return complete true only when every read above succeeded and every page was read; when any failed, return complete false and the failure as detail.
${RULES_FOR(W || '<worktree>')}`, { label: 'look-stale', phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: LOOK_STALE_SCHEMA })
    const entries = st && st.complete === true && Array.isArray(st.stale) ? st.stale : null
    if (entries === null || !entries.every(e => isEntry(e) && Number.isInteger(e.issue) && Array.isArray(e.acs) && typeof e.results === 'boolean')) return stop('hold', { pr: PR, stale: st, details: 'whether an earlier hold still checks the criteria the look approval answers could not be read; nothing was held' })
    const blocking = entries.filter(e => e.acs.some(isAnswered) && (e.issue !== ISSUE || noHold || e.results === true))
    if (blocking.length) {
      const ids = answered.filter(a => blocking.some(e => e.acs.some(x => upId(x) === upId(a))))
      return stop('hold', { pr: PR, look_checks: ids, stale: blocking, details: `a hold posted before the approval was read still checks ${ids.join(', ')} on ${blocking.map(e => '#' + e.issue).join(', ')}: remove those checks (or close that issue) by hand, then resume (a hold of this issue with recorded results is never rewritten here: that would discard the results of its other checks)` })
    }
  }
  // Before the call that posts, labels and runs once, read every check that call would leave standing (the fences
  // already posted) and write the ones the plan lacks, so a check that asks the owner for a code or evidence criterion
  // is refused before anything is posted.
  let authorized = []
  // The invocation each evidence criterion that runs a committed script is held with, read off the authorized check
  // (the verify member with the base sha replaced by the merge commit, or the check the draft wrote), keyed by the
  // criterion's id in upper case.
  const wantedRun = new Map()
  if (!noHold) {
    const draft = await call(`Issue #${ISSUE} of ${SLUG}: PR #${PR} is merged into ${INT}. Draft the hold of the issue's acceptance, changing nothing: post, edit, label, file and run nothing, and run no verify-pending command. Each command in its own Bash call:
Step A. Run git -C ${REPO} fetch origin. Merge commit: ${merged}.${known ? '' : INDIRECT_FOR(PR, 'complete false')} Return it as merge.
Step B. Read the hold fences already posted, in two reads:
${FENCE_READ}
Return posted: one {issue, merge, checks} per selected fence (its merge member and its checks array as the fence spells them), or [] when none.
Step C. Write, per ~/.agents/standards/acceptance-planning.md and with every occurrence of the base sha ${setup.base_sha} replaced by the merge commit, one check for each criterion of the line below: a code or evidence criterion gets a check of kind evidence and never an ask or an act run; an unattended evidence command run must be one of ${JSON.stringify(VERIFY_IDS)}, else use a committed script or a probe. Return them as written.
Criteria without a verify member: ${JSON.stringify(openCriteria.filter(a => !(a.verify && typeof a.verify === 'object')))}
Return complete true only when every read above succeeded and every page was read; when any failed, return complete false and the failure as detail.
${RULES_FOR(W || '<worktree>')}`, { label: 'hold-draft', phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: HOLD_DRAFT_SCHEMA })
    const posted = draft && Array.isArray(draft.posted) ? draft.posted : null
    if (!(isEntry(draft) && draft.complete === true && Array.isArray(draft.written) && posted !== null && posted.every(e => isEntry(e) && Number.isInteger(e.issue) && Array.isArray(e.checks)) && (known || (typeof draft.merge === 'string' && SHA40.test(draft.merge))))) return stop('hold', { pr: PR, draft, details: 'the hold could not be drafted: the posted fences and the merge commit could not be read; nothing was held' })
    const mergeSha = known || draft.merge
    const subMerge = v => JSON.parse(JSON.stringify(v).split(setup.base_sha).join(mergeSha))
    authorized = openCriteria.map(a => a.verify && typeof a.verify === 'object' ? subMerge(a.verify) : draft.written.find(c => isEntry(c) && upId(c.ac) === upId(a.id)))
    const lacking = openCriteria.filter((a, i) => !isEntry(authorized[i]) || (a.kind === 'human' && !asksOwner(authorized[i]))).map(a => a.id)
    if (lacking.length) return stop('hold', { pr: PR, draft, missing_checks: lacking })
    const ids = [...new Set([...humanFor(authorized), ...posted.flatMap(e => humanFor(e.checks))])]
    const posted_holds = posted.filter(e => humanFor(e.checks).length).map(e => e.issue)
    if (ids.length) return stop('hold', { pr: PR, draft, human_checks: ids, posted_holds, details: HUMAN_REFUSED(ids, posted_holds) })
    const outsideDrafted = authorized.filter(commandOutside)
    if (outsideDrafted.length) return stop('hold', { pr: PR, draft, unattended: outsideDrafted.map(c => c.ac) })
    const ownerIds = [...new Set(posted.flatMap(e => notOwnerFor(e.checks)))]
    const ownerIssues = posted.filter(e => notOwnerFor(e.checks).length).map(e => e.issue)
    if (ownerIds.length) return stop('hold', { pr: PR, draft, owner_checks: ownerIds, posted_holds: ownerIssues, details: OWNER_REFUSED(ownerIds, ownerIssues) })
    openCriteria.forEach((a, i) => {
      const run = a.kind === 'evidence' ? scriptRun(authorized[i], mergeSha) : null
      if (run !== null) wantedRun.set(upId(a.id), run)
    })
    const scriptIds = []
    const scriptIssues = []
    const flag = (a, issue) => {
      if (!scriptIds.includes(a.id)) scriptIds.push(a.id)
      if (!scriptIssues.includes(issue)) scriptIssues.push(issue)
    }
    for (const e of posted) {
      const at = typeof e.merge === 'string' ? e.merge : mergeSha
      for (const c of e.checks) {
        const a = c && openCriteria.find(m => wantedRun.has(upId(m.id)) && upId(m.id) === upId(c.ac))
        if (a && scriptRun(c, at) !== wantedRun.get(upId(a.id))) flag(a, e.issue)
      }
      // The parent's own fence stands in the once-run that follows, which closes the issue when its checks pass: every
      // scripted criterion must be in it, or the once-run could close the issue without running the script.
      if (e.issue === ISSUE) for (const a of openCriteria) {
        if (wantedRun.has(upId(a.id)) && !e.checks.some(c => c && upId(c.ac) === upId(a.id))) flag(a, e.issue)
      }
    }
    if (scriptIds.length) return stop('hold', { pr: PR, draft, script_checks: scriptIds, posted_holds: scriptIssues, details: SCRIPT_REFUSED(scriptIds, scriptIssues) })
    // The same once-run closes the issue on the parent's posted fence, so every open criterion must be in it; a human
    // criterion may be absent only when a posted fence of another issue for this merge holds it (a split child).
    const parentFence = posted.find(e => e.issue === ISSUE)
    if (parentFence) {
      const absent = openCriteria.filter(a => !parentFence.checks.some(c => c && upId(c.ac) === upId(a.id)) && !(a.kind === 'human' && posted.some(e => e.issue !== ISSUE && e.merge === mergeSha && e.checks.some(c => c && upId(c.ac) === upId(a.id))))).map(a => a.id)
      if (absent.length) return stop('hold', { pr: PR, draft, missing_checks: absent })
    }
  }
  const held = await call(`Issue #${ISSUE} of ${SLUG}: PR #${PR} is merged into ${INT}. Hold the issue's acceptance after the merge, by ~/.agents/standards/acceptance-planning.md (its "Linting a hold" section is the procedure).${noHold ? ' Nothing of this issue is held: post, edit and run nothing beyond the steps below.' : ` Skip the posting steps an earlier attempt already finished (an existing hold comment with a verify fence, the label, a split issue already filed and held for that criterion), but never skip the evidence you return: lint and verify_run are always fresh results of this attempt, so on such a retry take block from the posted verify fence${answered.length ? ' after step 6 has removed every check the owner\'s look approval answers' : ''}, lint that block with verify-pending lint as step 6 says, run the once-run, and return all three.`} Each command in its own Bash call:
${lock ? RELEASE_FIRST(lock.sha, lock.maybe) : ''}1. Run git -C ${REPO} fetch origin. Merge commit: ${merged}${mergeCommit ? '' : ' (and read headRefOid, the PR head)'}.${indirect} Confirm git -C ${REPO} cat-file -e <merge commit>^{commit} succeeds and return the result as merge_commit_local; if it fails, stop here. Criteria: ${JSON.stringify(acceptance)}
2. Regrade each code criterion once against the merge commit and the PR's passed required checks; a note criterion is the orchestrator's own observation and is never regraded, held or checked. Return the unmet ids as code_unmet and, if any, stop here: post nothing and add no label.
3. ${noHold ? 'Every criterion is of kind code or note: post nothing, add no label; return issue_state read from the tracker.' : 'Some criteria are of kind evidence or human. Read gh issue view ' + ISSUE + ' --repo ' + SLUG + ' --json state. When it already shows CLOSED before this attempt posts or runs anything, return already_closed true and issue_state CLOSED, post nothing, add no label and run no verify-pending command for #' + ISSUE + ' itself (step 6 is skipped); steps 4 and 5 still apply, so a split issue an earlier attempt filed is recovered and returned with its lint and a fresh once-run. Otherwise return already_closed false and continue with steps 4 to 6.'}${heldBlock(authorized)}
${RULES_FOR(W || '<worktree>')}`, { label: 'hold', phase: 'Ship', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'high', schema: lock ? { ...HOLD_SCHEMA, properties: { ...HOLD_SCHEMA.properties, release: NULLABLE(RELEASE_SCHEMA) } } : HOLD_SCHEMA })
  if (lock) landRelease = held ? (held.release ?? null) : null
  if (!held) return stop('hold', { pr: PR })
  if (held.merge_commit_local !== true) return stop('hold', { pr: PR, hold: held })
  if (!Array.isArray(held.code_unmet)) return stop('hold', { pr: PR, hold: held })
  if (held.code_unmet.length) return stop('code-unmet', { pr: PR, code_unmet: held.code_unmet })
  // The reply's own block and each split entry's block are read once more, whatever the draft said: a hold that made a
  // code or evidence criterion a human check is refused here, before close-out.
  const heldChecks = [
    ...(isEntry(held.block) && Array.isArray(held.block.checks) ? [{ issue: ISSUE, checks: held.block.checks }] : []),
    ...(Array.isArray(held.split) ? held.split.filter(x => isEntry(x) && Number.isInteger(x.issue) && isEntry(x.block) && Array.isArray(x.block.checks)).map(x => ({ issue: x.issue, checks: x.block.checks })) : []),
  ]
  const heldHuman = heldChecks.filter(e => humanFor(e.checks).length)
  if (heldHuman.length) {
    const ids = [...new Set(heldHuman.flatMap(e => humanFor(e.checks)))]
    const issues = heldHuman.map(e => e.issue)
    return stop('hold', { pr: PR, hold: held, human_checks: ids, posted_holds: issues, details: HUMAN_REFUSED(ids, issues) })
  }
  // An issue the clerk found closed before the hold posted or ran anything has no parent evidence to check. One the
  // once-run closed is not that case: its evidence is still validated. Split children are checked either way.
  const closedBefore = held.already_closed === true && held.issue_state === 'CLOSED'
  if (!noHold) {
    if (!Array.isArray(held.blocks) || !Array.isArray(held.split)) return stop('hold', { pr: PR, hold: held })
    const splitIds = held.split.map(x => x && x.ac)
    if (held.blocks.length) {
      const missing = acceptance.filter(a => a.kind === 'human' && !splitIds.includes(a.id)).map(a => a.id)
      if (missing.length) return stop('hold', { pr: PR, hold: held, missing_split: missing })
    }
    const noteIds = notes.map(a => a.id)
    const splitLook = [...new Set(held.split.flatMap(x => (x && x.block && Array.isArray(x.block.checks) ? x.block.checks : []).filter(c => c && isAnswered(c.ac)).map(c => upId(c.ac))))]
    if (splitLook.length) return stop('hold', { pr: PR, hold: held, look_checks: splitLook })
    const humanIds = acceptance.filter(a => a.kind === 'human').map(a => upId(a.id))
    const badSplit = held.split.filter(x => !(x && humanIds.includes(upId(x.ac)) && !noteIds.includes(x.ac) && x.lint && x.lint.ok === true && RUN_OK(x.verify_run) && STATES.includes(x.issue_state) && x.block && Array.isArray(x.block.checks) && covers(x.block.checks, [x.ac]).length === 0 && x.block.checks.some(c => c && upId(c.ac) === upId(x.ac) && asksOwner(c)) && !x.block.checks.some(c => commandOutside(c) || (c && noteIds.includes(c.ac))))).map(x => (x && x.ac) || null)
    if (badSplit.length) return stop('hold', { pr: PR, hold: held, bad_split: badSplit })
    const remaining = openCriteria.filter(a => !splitIds.includes(a.id))
    if (remaining.length && !closedBefore) {
      if (!(held.lint && held.lint.ok === true) || !RUN_OK(held.verify_run) || !held.block || !Array.isArray(held.block.checks)) return stop('hold', { pr: PR, hold: held })
      const noteChecks = held.block.checks.filter(c => c && noteIds.includes(c.ac)).map(c => c.ac)
      if (noteChecks.length) return stop('hold', { pr: PR, hold: held, note_checks: noteChecks })
      const lookChecks = [...new Set(held.block.checks.filter(c => c && isAnswered(c.ac)).map(c => upId(c.ac)))]
      if (lookChecks.length) return stop('hold', { pr: PR, hold: held, look_checks: lookChecks })
      const uncovered = covers(held.block.checks, remaining.map(a => a.id))
      if (uncovered.length) return stop('hold', { pr: PR, hold: held, missing_checks: uncovered })
      const outside = held.block.checks.filter(commandOutside)
      if (outside.length) return stop('hold', { pr: PR, hold: held, unattended: outside.map(c => c.ac) })
      const ownerOnly = notOwnerFor(held.block.checks)
      const ownerMissing = remaining.filter(a => a.kind === 'human' && !held.block.checks.some(c => c && upId(c.ac) === upId(a.id) && asksOwner(c))).map(a => a.id)
      if (ownerOnly.length || ownerMissing.length) return stop('hold', { pr: PR, hold: held, owner_checks: [...new Set([...ownerOnly, ...ownerMissing])], posted_holds: [ISSUE], details: OWNER_REFUSED([...new Set([...ownerOnly, ...ownerMissing])], [ISSUE]) })
      const unscripted = remaining.filter(a => wantedRun.has(upId(a.id))).filter(a => {
        const own = held.block.checks.filter(c => c && upId(c.ac) === upId(a.id))
        return !own.length || !own.every(c => c.kind === 'evidence' && scriptRun(c, held.block.merge) === wantedRun.get(upId(a.id)))
      }).map(a => a.id)
      if (unscripted.length) return stop('hold', { pr: PR, hold: held, script_checks: unscripted, posted_holds: [ISSUE], details: SCRIPT_REFUSED(unscripted, [ISSUE]) })
    } else if (held.issue_state !== 'CLOSED') return stop('hold', { pr: PR, hold: held })
    if (!STATES.includes(held.issue_state)) return stop('hold', { pr: PR, hold: held })
  }
  const tickStep = MARKED && approvedHead ? `0. Tick the look marker's box in the issue body under the owner's approval of the merged head. Run alone and exactly: look-approval tick --repo ${SLUG} --issue ${ISSUE} --pr ${PR} --head ${approvedHead}${landedCommit ? ` --merge-commit ${landedCommit}` : ''}
It prints one JSON line; return its verdict, ticked and any detail as look_tick. Run it on a retry too (a box already ticked answers already). Whatever it answers, go on with step 1.
` : ''
  const co = await call(`Issue #${ISSUE} of ${SLUG}: PR #${PR} is merged into ${INT}. Close out; skip any step an earlier attempt already finished. Each command in its own Bash call:
${tickStep}1. ${W ? `If ${W} still exists: git -C ${REPO} worktree remove ${W} (it also removes the plan directory). ` : ''}git -C ${REPO} fetch origin; if the checkout ${REPO} is clean and on ${INT}, git -C ${REPO} merge --ff-only origin/${INT}; then, if the local branch ${setup.branch} exists, git -C ${REPO} branch -d ${setup.branch}. If -d refuses, leave the branch and report it (never -D).
2. End the decision prompts: run alone, exactly, forge-claim owner-action end --repo ${SLUG} --issue ${ISSUE} --reason decision (a verdict none is fine); return decision_ended true when it exits 0.
3. Release the claim: run alone, exactly, forge-claim release --repo ${SLUG} --issue ${ISSUE} --holder ${setup.holder} --reason done. It prints one JSON line and removes the in-progress label when no other claim remains; released is true only for verdict released. ${FORGE_TIMEOUT}
${notes.length ? `4. Unless a comment starting Orchestrator notes for PR ${PR} already exists on #${ISSUE} (an earlier attempt), write to a file outside any work tree a comment whose first line is Orchestrator notes for PR ${PR} (observations the orchestrator records itself; not graded, not held): and then one line <id>: <text> per note of ${JSON.stringify(notes.map(a => ({ id: a.id, text: a.text })))}, and post it with gh issue comment ${ISSUE} --repo ${SLUG} --body-file <file>. Return notes_posted true once that comment exists.\n` : ''}${notes.length ? 5 : 4}. ${noHold ? `Every criterion is of kind code or note. Read gh issue view ${ISSUE} --repo ${SLUG} --json state; if it is still open (${INT === setup.default_branch ? 'the closing keyword did not fire' : `${INT} is not the default branch, so no closing keyword fires`}), run gh issue close ${ISSUE} --repo ${SLUG} --comment 'Delivered by PR ${PR} into ${INT}.'` : 'The hold step settled the issue state and labels; change neither.'}
Return issue_state (OPEN or CLOSED, read back from the tracker), branch_deleted, decision_ended, released and notes.
${RULES_FOR(W || '<worktree>')}`, { label: 'close-out', phase: 'Ship', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'low', schema: { type: 'object', properties: { issue_state: { type: 'string' }, branch_deleted: { type: 'boolean' }, released: { type: 'boolean' }, decision_ended: { type: 'boolean' }, notes_posted: { type: 'boolean' }, notes: { type: 'string' }, look_tick: LOOK_TICK_SCHEMA }, required: ['issue_state', 'notes'] } })
  const want = noHold ? 'CLOSED' : held.issue_state
  if (!co || co.issue_state !== want || co.decision_ended !== true || co.released !== true || (notes.length && co.notes_posted !== true)) return stop('close-out', { pr: PR, close_out: co, expected_issue_state: want })
  const lookTick = tickStep ? (co.look_tick || null) : null
  if (tickStep && !(lookTick && ['ticked', 'already', 'unmarked'].includes(lookTick.verdict))) log(`close-out: the look marker of issue ${ISSUE} was not ticked: ${lookTick ? lookTick.verdict : 'no reply'}`)
  const liveFault = LANE === 'live' && LIVE_REC ? await liveTiming(PR) : null
  return { stage: 'done', pr: PR, merged: true, merge_commit: mergeCommit, close_out: co, hold: held, ...(liveFault ? { live_fault: liveFault } : {}), ...(tickStep ? { look_tick: lookTick } : {}), tasks: taskLog, ...(reordered.length ? { reordered } : {}), ...(followUps.length ? { follow_ups: followUps } : {}), acceptance: planned, fix_waves: fixWaves }
}

if (CONT && setup.merged_pr) {
  phase('Ship')
  log(`PR #${setup.merged_pr} is already merged; closing out`)
  // A replay after the approved PR merged reads the recorded approval against the merged head before the hold is built,
  // whatever approval the cont kept (an awaiting-look cont carries none, a merge stop's names the head before the
  // merge): an approved one is ticked and its criterion left out of the hold; a look the setup could not read stops
  // here.
  if (!LOOK_READ) return LOOK_UNREAD()
  if (MARKED) {
    const MR = setup.merged_pr
    const mergedHead = await recall(() => call(`Issue #${ISSUE} of ${SLUG}: read the head and the landing commit of the merged PR #${MR}, changing nothing but the refs of the checkout: first run git -C ${REPO} fetch origin, then run ${UNSET}gh pr view ${MR} --repo ${SLUG} --json state,headRefOid,mergeCommit and return state, head (headRefOid, the full sha) and merge (the landing commit, the full sha: the oid of mergeCommit, resolved as below when that is null or the head itself).${INDIRECT_FOR(MR, 'merge null', true)} Run nothing else.
${RULES_FOR(setup.worktree || '<worktree>')}`, { label: 'look-head', phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: { type: 'object', properties: { state: { type: 'string' }, head: { type: 'string' }, merge: { type: ['string', 'null'] } }, required: ['state', 'head', 'merge'] } }))
    if (!mergedHead || typeof mergedHead.head !== 'string' || !SHA_RE.test(mergedHead.head) || typeof mergedHead.merge !== 'string' || !SHA_RE.test(mergedHead.merge)) return stop('look-approve', { details: `the approval could not be checked: the head and the landing commit of merged PR #${MR} could not be read`, result: mergedHead })
    landedCommit = mergedHead.merge
    const recorded = await call(`Issue #${ISSUE} of ${SLUG}: read the owner's look approval of the merged head; it was recorded where the owner answered, so post nothing. Run alone and exactly: look-approval status --repo ${SLUG} --issue ${ISSUE} --pr ${MR} --head ${mergedHead.head} --merge-commit ${landedCommit}
It prints one JSON line. Return its verdict, kept_from and any detail. Run nothing else.
${RULES_FOR(setup.worktree || '<worktree>')}`, { label: 'look-read', phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: { type: 'object', properties: { verdict: { type: 'string' }, kept_from: { type: ['string', 'null'] }, detail: { type: 'string' } }, required: ['verdict'] } })
    if (!recorded || typeof recorded.verdict !== 'string' || recorded.verdict === 'error') return stop('look-approve', { details: `the approval could not be checked: look-approval status answered ${recorded ? (recorded.verdict || 'no verdict') : 'nothing'} for the merged head ${mergedHead.head}`, result: recorded })
    if (recorded.verdict === 'approved') {
      approvedHead = mergedHead.head
      lookAt = { pr: MR, head: approvedHead, approved: approvedHead }
    } else {
      approvedHead = null
      lookAt = lookAt ? { pr: lookAt.pr, head: lookAt.head } : null
    }
  }
  return await closeOut(setup.merged_pr, null, setup.worktree, null)
}

// ---------------- Live-fault gate ----------------
let LIVE_ENDED = null
// The live lane acts on the declaration it started under, before any agent: first hit wins. A stop here before the
// claim was validated keeps claim_incomplete, so its resume finishes the claim.
if (LANE === 'live') {
  const unreadWhy = LIVE_RAW === undefined || LIVE_RAW === null ? 'the setup returned no live_fault' : isEntry(LIVE_RAW) && LIVE_RAW.verdict === 'error' ? (present(LIVE_RAW.detail) ? String(LIVE_RAW.detail).slice(0, 80) : 'the read failed') : 'the read was no usable live_fault'
  const liveStop = (stage, details) => { if (!CONT) claimIncomplete = true; return stop(stage, { details }) }
  const seen = CONT && isEntry(CONT.live_fault) ? CONT.live_fault : null
  if (seen && LIVE_FINAL.includes(seen.final)) {
    const ended = () => liveStop(seen.final, `this live-fault delivery already stopped at ${seen.final}; ${LIVE_WAY}`)
    if (!pending.length) return ended()
    LIVE_ENDED = ended
  }
  if (!LIVE_ENDED) {
    if (LIVE_UNREAD) return liveStop('live-fault', `the live-fault declaration of issue #${ISSUE} could not be read (${unreadWhy}); resume once the console answers, or ${LIVE_WAY}`)
    if (!LIVE) return liveStop('live-fault', `issue #${ISSUE} has no standing live-fault declaration (${LIVE_RAW.verdict}); ${LIVE_WAY}`)
    if (seen && !liveSame(seen, LIVE)) return liveStop('live-fault', `the live-fault declaration this delivery started under (${seen.id}) was withdrawn or replaced; ${LIVE_WAY}`)
    if (MODE === 'plan') return liveStop('live-fault', `issue #${ISSUE} is a declared live fault and the live-fault lane has no plan mode: run it in ready or ship mode`)
  }
}

const RS = setup.review_state || {}
// The live lane runs no Codex review of any kind, so its capability state stops nothing.
for (const k of LANE === 'live' ? [] : ['plan', 'code']) {
  // Before any claim nothing is held, so the stop carries no cont: fix the capability and start again.
  if (RS[k] === 'blocked') return CONT || CLAIM_TAKEN ? stop('review-blocked', { review: k }) : why({ stage: 'review-blocked', review: k })
}
const REVIEW_CODE = LANE !== 'live' && RS.code === 'available' && setup.review && setup.review.code ? setup.review.code : null
const REVIEW_PLAN = LANE !== 'live' && RS.plan === 'available' && setup.review && setup.review.plan ? setup.review.plan : null

// A fresh run's setup already ran the claim and the worktree: validate its nested results. A claim_incomplete resume
// runs them itself, and so does a fresh run whose folded acquire was transient (its acquire step runs once more, then
// the worktree).
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
if (LIVE_ENDED) {
  const again = pending
  pending = []
  await fileFollowUps(again)
  return LIVE_ENDED()
}
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
    // On a revise, the ids of the criteria whose wording the planner changed; never kept in the plan.
    criteria_edited: STRS,
    tasks: { type: 'array', items: { type: 'object', properties: { n: { type: 'integer' }, title: { type: 'string' }, file: { type: 'string' }, risk: { type: 'string', enum: ['mechanical', 'low', 'standard', 'security'] }, branch: { type: 'string' } }, required: ['n', 'title', 'file', 'risk'] } },
    branches: { type: 'array', items: { type: 'object', properties: { name: { type: 'string' }, worktree: { type: 'string' }, base: { type: 'string' }, head: FULL_SHA, current: { type: 'string' }, toplevel: { type: 'string' }, common_dir: { type: 'string' }, clean: { type: 'boolean' } }, required: ['name', 'worktree', 'base', 'head', 'current', 'toplevel', 'common_dir', 'clean'] } },
  },
  required: ['status'],
}
const wellFormed = p => !!(p && p.status === 'planned' && present(p.plan_root) && Array.isArray(p.acceptance) && p.acceptance.length && Array.isArray(p.tasks) && p.tasks.length)
const HUMAN_REASONS = ['senses', 'hands', 'credentials', 'money', 'taste']
const RULE_OF = { pre_merge_only: 'R1', approval_ask: 'R2', reason_required: 'R3' }
// Every message names each way out the rules allow, so a planner that follows it is not led into another rule's
// violation (a message that named only the evidence check turned a locally enforced cap into a post-merge hold).
const HUMAN_FIX = `name the one of ${HUMAN_REASONS.join(', ')} that applies, or, when none does, make the criterion code or evidence`
const CODE_FIX = `make it a code criterion when a test, CI or a local evaluation shows it before merge (R1)`
const LINT_FIX = {
  pre_merge_only: `: make it a code criterion, graded at ship, or, when only a deploy or a later observation shows it, trigger the check on that`,
  approval_ask: `: the approval is given on the pull request, so drop the post-merge ask; keep a human check only for what a person must sense or do after the merge (R3)`,
  reason_required: `: ${HUMAN_FIX}`,
}
// A code criterion whose every word is a declared verification id, a word of its argv or filler names no test of its
// own: the verify step already runs and proves it, and reviewers asked to show it ran the whole suite again. Anything
// else is left to review.
const VERIFY_NAMES = (BEFORE_PR ? [...setup.verification, ...LOCAL] : setup.verification).flatMap(e => [e.id].concat(Array.isArray(e.argv) ? e.argv : [])).filter(v => typeof v === 'string' && v).map(v => v.toLowerCase())
const VERIFY_FILLER = ['a', 'all', 'and', 'are', 'at', 'both', 'branch', 'check', 'checks', 'clean', 'command', 'commands', 'declared', 'exit', 'exits', 'green', 'head', 'in', 'is', 'of', 'on', 'or', 'pass', 'passes', 'passing', 'run', 'runs', 'still', 'succeed', 'succeeds', 'suite', 'the', 'tip', 'verification', 'with', 'zero', '0']
const restatesVerify = text => {
  const words = (typeof text === 'string' ? text : '').toLowerCase().split(/[^a-z0-9:_./-]+/).map(w => w.replace(/^[.:/-]+|[.:/-]+$/g, '')).filter(w => w !== '')
  return words.some(w => VERIFY_NAMES.includes(w)) && words.every(w => VERIFY_NAMES.includes(w) || VERIFY_FILLER.includes(w))
}
const planRules = p => {
  const out = []
  const scripts = Array.isArray(p.scripts) ? p.scripts : []
  // Dropping is the fix, and a plan with no criterion is not well formed: when every criterion restates the
  // verification none is refused, or the revise would empty the plan, drop it and the relaunch would plan the same
  // thing again.
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
// The planner's code map, beside the plan in plan_dir, so outside the tree and never committed.
const CODE_MAP = `${setup.plan_dir}/context.md`
const MAP_FIRST = `Read the code map ${CODE_MAP} first: open the code only to check one of its claims or where it is silent; when it is missing, read the code; check against HEAD every claim of it that a finding or a change relies on.`
// The plan reviewer's defect list, shared so the planner checks against the review it will get.
const PLAN_RUBRIC = `an acceptance criterion with no task, a task whose test cannot fail, wrong or missing interfaces, a design choice that breaks the project's documented conventions, or a project-specific literal written into global skills or agents`
const PLAN_RUBRIC_SIZED = `an acceptance criterion with no task, a design choice that breaks the project's documented conventions, standards or docs (name the document it breaks), a project-specific literal written into global skills or agents, or an internal inconsistency (a task, interface, file or decision that the plan root or another task contradicts, or that no task defines)`
const PLAN_CODEX_OWNS = `The Codex plan review running beside you owns code correctness (whether a task's code, tests and interfaces will work): do not sweep for it.`
// A plan of at most this many tasks, none of risk security, skips the Codex plan review; the Claude plan review still
// runs. An applied amend makes the planner's risk labels stale, so it marks the Codex review owed (codexOwed) until one
// passes; a revise that leaves the plan no longer small runs the review on the revised plan.
const SMALL_PLAN_TASKS = 3
const smallPlan = p => p.tasks.length <= SMALL_PLAN_TASKS && !p.tasks.some(t => t.risk === 'security')
const PLAN_SELF_CHECK = `Also before you return: run every grep or deny gate a task prescribes against the text this plan requires and confirm it does not reject that text; for each invariant, threshold and decision a task states, name the test case that fails when that one rule is removed; one with no such case needs a test; and list for each new test or doc the CI workflow test list, the generated index and the project gate that must also change.`
// The plan step's turn structure, first in the prompt: at least four lookups a message and writing by the twelfth, then
// one message of writes. The review-findings revise gets its own pace instead (one message that checks every finding,
// at most two more), never both. No subagent grant: the Agent tool does not exist inside a workflow agent.
const PLAN_PACE = `send at least four lookups in each exploration message and start writing by your twelfth message`
const REVISE_PACE = `check every finding's claim in the first lookup message after the load below, one call per finding, and send at most two follow-up lookup messages before editing`
const PLAN_LOOKUPS = pace => `Procedure for this step. Look things up in rounds: put every open question's Bash or Read call in the same message as the others (several tool calls per message, never one small lookup per turn), ${pace}. No subagent can be dispatched: the Agent tool does not exist in this step. Check against the tree yourself every path and symbol you write into a task.`
const PLAN_WRITES = `Then write the code map, plan.md and every task file as parallel Write calls in one message (a second message only if the output limit forces it), then run any checks in one message.`
// Parallel Read calls, since one cat of the plan directory overflows the Bash output cap.
const PLAN_EDITS = `This is a revision: first list ${setup.plan_dir}/*.md and load them all as parallel Read calls in one message, then fix the findings with Edit in place, the independent Edit calls in one message; rewrite a whole file only when most of it changes; leave each acceptance criterion's text unchanged unless fixing a finding requires changing it. Then run any checks in one message.`
const FACTS = present(setup.details) ? `\nSetup facts: ${setup.details}` : ''
const KIND_GUIDE = `kind code if a test or command in this repo can show it, evidence if it needs a deploy, an activation or observation over time, human if only the user can judge, note if a decision makes a post-deploy reading the orchestrator's own observation or not a hold (no verify member, no script and no metric, R9 of ~/.agents/standards/acceptance-planning.md)`
// Only this plan step asks for test cases; writing-plans keeps full test code for its other callers.
const TEST_CASES = `Task files of this plan step state each failing test as a case, not as code: its name, the arrange, the act, the exact assertion and the expected failure. This replaces writing-plans' "Write failing tests out in full." here; full test code stays only under its carve-out, where prose cannot preserve a decision (an exact wire format). The implementer writes the test code from the case.`
// The planner names each task's one proving test first, and the plan review checks it.
const PROVING_TEST = `Each task file names first, before any other test, the one test that proves its slice: the case that fails until the slice works and passes once it does.`
const PROVING_FINDING = `a task that does not name first, before any other test, the one test that proves its slice`
const planPrompt = (extra, pace = PLAN_PACE) => `${PLAN_LOOKUPS(pace)} ${extra ? PLAN_EDITS : PLAN_WRITES}
${CTX}
${TEST_CASES} ${PROVING_TEST}
Plan this issue. Read the issue (gh issue view ${ISSUE} --repo ${SLUG} --json title,body,comments) and the code it touches.${SPEC}${FACTS} Use the writing-plans skill for the plan's form only: its file location, size checks and reports do not apply here. Write the plan to ${setup.plan_dir}/plan.md and one task file per task beside it (${setup.plan_dir}/task-<n>.md); never commit them and never write under the project's artifact directories. Also write the code map ${CODE_MAP} for the agents after you, who read it before the code: per area the plan touches, list the files and symbols with line ranges, their tests and fixtures, the callers that matter and the facts you confirmed (for example a library's behaviour, with its source), each with a pointer (a path:line or a URL). Like the plan, it is never committed. On a revision, read it first and keep it true to the plan and the code. Do not build, prototype or run the change; confirming each task's failing test later is the implementers' job. If the issue needs a decision only the user can make (a preference, an irreversible or scope choice not settled by the issue, the spec, the repo's docs or ADRs), return status needs_user, never for an action that R8 of ~/.agents/standards/acceptance-planning.md says the delivery does itself, with questions, each {question, options}: every option one full sentence naming a real choice, a single option for a yes or no, and, when you would choose one option, recommended: its exact text; then stop. Otherwise return status planned with plan_root ${setup.plan_dir}/plan.md, the issue's acceptance criteria (${KIND_GUIDE}) and the task list in execution order with each task's file and a risk: security for authentication, permission or command guards, secrets, CI/CD or deploy config, data migrations; mechanical or low for small contained edits; else standard. When a task commits to a branch other than ${setup.branch}, declare it in branches as {name, worktree, base, head, current, toplevel, common_dir, clean}: only a branch already checked out in its own existing worktree other than ${W}, never ${INT} or ${setup.default_branch}; worktree as git -C <it> rev-parse --show-toplevel prints it, base the ref its changes are measured from, and ${BRANCH_FACTS}, and clean: true only when git -C <its worktree> status --porcelain prints nothing (a worktree with any staged, unstaged or untracked change is not declared); give each task that commits there branch: <name>. Classify and write every acceptance criterion by ~/.agents/standards/acceptance-planning.md (read it); set metric true only on an evidence criterion, never on a note (R9: an owner-designated observation stays a note even when it reads a cost, a time or a rate), whose threshold is a cost, a time or a rate that only a deploy or observation over time shows, and give its verify member mode observe (R5); a bound that a test or a run before merge enforces belongs to a code criterion with metric false (R1). Return no criterion that only restates a declared verification command passing: the verify step proves it. Give every evidence or human criterion a verify member: one check of the verify block grammar with ac its id and kind its kind, writing any sha that will name the merge commit as the base sha ${setup.base_sha} (ship substitutes the merge commit); an unattended evidence command run must be one of ${JSON.stringify(VERIFY_IDS)}, else use a script or a probe. Lint each member alone: write {"v": 1, "merge": "${setup.base_sha}", "checks": [<that member>]} to a file in ${setup.plan_dir} and run verify-pending lint --input <that file> --repo-root ${W} --pr-branch ${setup.branch} plus one --pr-workflow <name> for each CI workflow that runs on this repository's pull requests; return the verdict as that criterion's lint. List in scripts each script path a verify run names that a task of this plan commits. Before you return, check the plan against the review it will get: ${PLAN_RUBRIC}, or ${PROVING_FINDING}; and every rule ${RULE_IDS[0]}-${RULE_IDS[RULE_IDS.length - 1]} of ~/.agents/standards/acceptance-planning.md (read it). ${PLAN_SELF_CHECK}${BEFORE_PR ? ` ${PLAN_TESTS}` : ''}${decisions.length ? `\nThe owner has answered the open decisions for this issue; they are binding: ${decisions.join('\n')} Do not ask them again; record them as decisions in the plan.` : ''}${!extra && priorFindings.length ? `\nAn earlier plan of this issue was dropped at plan review with these findings left on it; write this plan so that none of them recurs: ${JSON.stringify(priorFindings)}` : ''}${extra || ''}
${RULES}`
// A planner reply is either questions (the plan is dropped so a resume plans again with decisions) or a well-formed
// plan. A well-formed plan refused only for its declared branches gets one revise in place first, so a naming fault
// does not cost the whole plan. The accepted reply's criteria_edited is taken off the plan so it reaches no cont and no
// stop.
let planEdited
const takePlan = async (p, label, left) => {
  const fresh = label === 'plan'
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
  if (fresh) lookAcs = LOOK_ACS
  planEdited = listed
  return null
}

const PRE_COMMIT = setup.verification.filter(e => e && e.pre_commit === true).map(e => ({ id: e.id, argv: e.argv, cwd: e.cwd }))
const FMT = PRE_COMMIT.length
  ? `Before committing, run the fast pre-commit checks of that verification: each of ${JSON.stringify(PRE_COMMIT)} (its argv with <worktree>/<its cwd> as working directory), and fix what it reports.`
  : `Before committing, run any formatter or lint fix the project's standards (${list(K.standards)}) name on the files you changed.`
const FOCUSED = `${BEFORE_PR ? `Run only the tests covering the files you changed and, of the commands the project declares, ${ONLY_PRE_COMMIT}: the verify step runs the pre-pull-request commands ${LOCAL_CMDS} once later.` : 'Run only the tests covering the files you changed, not the full suite or the declared verification (it runs once later).'} ${FMT}`
// Whole test files after the task loop: running one class alone missed a failing sibling test.
const WHOLE = files => BEFORE_PR
  ? `run in full every test file among or covering ${files} (never a single test class) and the pre-pull-request commands ${LOCAL_CMDS} (each argv with <worktree>/<its cwd> as working directory) and, of the other commands the project declares, ${ONLY_PRE_COMMIT}; return tests: each command and its result`
  : `run in full every test file among or covering ${files} (never a single test class) and any fast suite the project declares, not the declared verification; return tests: each command and its result`
const PUSH_TESTS = (guards, onFailure = 'fix-and-rerun') => `If you made a commit, then before pushing, run in full every test file among or covering the files you changed (never a single test class), the test files of their direct callers and checkers, and the declared cheap guards ${BEFORE_PR ? `(with none declared, the pre-pull-request commands ${LOCAL_CMDS}, each argv with <worktree>/<its cwd> as working directory) and, of the other commands the project declares, ${ONLY_PRE_COMMIT},` : '(with none declared, any fast suite the project declares), not the declared verification,'} as this payload lists them: ${JSON.stringify({ push_tests: { when: 'committed', scopes: ['touched', 'callers', 'guards'], guards, on_failure: onFailure, report: 'tests' } })}. touched: every test file among or covering the files you changed; callers: for each function, constant, option, command or file name the commit changed, added or removed, git grep the tree and take the test files of every file that uses or checks it; guards: each entry's argv, run with <worktree>/<its cwd> as working directory. on_failure fix-and-rerun: fix a run that fails and run it again; report: change nothing and return status blocked with the failing command in notes; either way a failing or unrun commit is never pushed. Then return tests: each command and its result, one entry per command; a commit whose report records no test command is refused`
const tested = f => !!f && Array.isArray(f.tests) && f.tests.some(t => typeof t === 'string' && t.trim() !== '')
const FIX_TESTS = `The program pushes this fix to the open pull request next. ${PUSH_TESTS(PRE_COMMIT)}. ${FMT}`
const UNTESTED = 'the fix report records no test command, so its commit is not pushed'
// The retest's reply also says whether the worktree is still clean once its tests ran: a guard may rewrite a tracked
// file, and the tested contents would then differ from the commit.
const RETEST = { ...IMPL, properties: { ...IMPL.properties, clean: { type: 'boolean' } } }
const RETEST_DIRTY = 'the retest left the worktree changed, so the tested contents are not the commit and it is not pushed'
const OWN_TESTS = `Before returning, run in full every test file among or covering the files you changed (never a single test class)${BEFORE_PR ? ` and, of the commands the project declares, ${ONLY_PRE_COMMIT}: the verify step runs the pre-pull-request commands ${LOCAL_CMDS} next` : ' and no suite: the verify step runs it next'}; return tests: each command and its result. ${FMT}`
const RESOLVE_SCOPE = 'the checks of the pull request cover everything else the merge brought in, so run no test for a file that merged cleanly'
// A fix agent once committed a lock file a tool had generated beside its fix; every fix prompt carries this.
const COMMIT_SCOPE = 'Before committing, read git status in the worktree you commit in and stage by path only the files the fix itself changed or created; never run git add -A, git commit -a or git add on a directory (the dot included); a lock file, a generated file or an untracked file the fix did not need is left unstaged and named in notes.'
// The conflicted-sync wording, the same text in deliver-batch.js. The marker check runs before the merge is committed,
// when HEAD is still the branch's own head: git diff --check HEAD reads every line the merge brings in, in a file
// resolved by hand as in one merged cleanly, staged or not (the plain form goes silent once staged, --cached misses a
// later edit).

// It also reports content the integration branch brought in, so the same check runs against origin's head too: a line
// both report is in neither parent, so it is a real leftover. Removal is limited to those lines in hand-resolved files.
const MARKER_CHECK = (wt, int) => `run git -C ${wt} diff --check HEAD and git -C ${wt} diff --check origin/${int} before committing and remove each leftover conflict marker both report (same file and line) in a file you resolved by hand; every other line they report is content and stays`
const MARKERS_UNCHECKED = ' The merge was not checked for leftover conflict markers: report any left in the files it changed.'
const SYNC_FIX = (wt, mc, findings, after = '') => `A reviewer found defects in the conflict resolution of merge commit ${mc} (git -C ${wt} show --cc ${mc})${after}: ${JSON.stringify(findings)}. Fix each real defect on top of ${after ? 'that head' : 'the merge'} with a regression test (never redo or rewrite the merge), then commit; if a finding is wrong, commit nothing for it and say so with evidence in notes.`
const SYNC_REREVIEW = (wt, mc, findings, fix, moved, after = '') => `Re-review these conflict-resolution findings against ${moved ? `the fix (git -C ${wt} diff ${fix.start_head}..${fix.commit}) made on top of` : 'the rebuttal (no new commit) of'} merge commit ${mc}${after}: ${JSON.stringify(findings)}; notes: ${fix.notes}. ${moved ? '' : `Check each rebuttal against the code yourself (git -C ${wt} show --cc ${mc}); a finding the evidence does not refute is still unresolved. `}Report any still unresolved and any new Important or Critical defect. Do not edit anything.`
// A resolution may carry plain commits on top of its merge commit (a fix its tests asked for once the merge was
// committed). The program cannot read git, so the sync review proves the ancestry itself (DESCENDS) and reads the merge
// and the range from it to the head; the fix round and the re-review name the same range (SYNC_AFTER). A head that does
// not descend from its merge commit never lands. The same text in both programs, like the wording above.
const SYNC_AFTER = (wt, mc, head) => ` and the commits made on top of it up to the head ${head} (git -C ${wt} diff ${mc}..${head})`
const DESCENDS = (wt, mc, head) => ` The resolution's head ${head} is not its merge commit: first run git -C ${wt} merge-base --is-ancestor ${mc} ${head} and git -C ${wt} rev-list --count --min-parents=2 ${mc}..${head}, and return descends true only when the first exits 0 and the second prints 0 (the head is the merge commit with plain commits on top of it), else descends false and no finding. When it descends, review those commits as well (git -C ${wt} diff ${mc}..${head}), above all for a test or check they weaken, skip or delete, and report any conflict marker git -C ${wt} diff --check ${mc} ${head} shows in them.`
const RESOLVE_ORDER = 'Fix in the resolution itself what those tests show and commit the merge only once they pass. When a defect shows only after the merge is committed, never amend or redo the merge: fix it in a commit on top of it, run those tests again, and report the merge commit and the head as they are'
// A rerun covers every failed run of the head. Each check is its own workflow run, so a gate or aggregate check that
// failed only because another check failed keeps its old failure unless its own run is rerun too; a gate that waits for
// the head's other runs then goes green with them, so the reruns need no order.
const RERUN_ALL = (unset, slug, sha) => `rerun the failed jobs once, with ${unset}gh run rerun <run-id> --repo ${slug} --failed for each failed run of the head: list them with ${unset}gh run list --repo ${slug} --commit ${sha} --json databaseId,workflowName,conclusion, keep the newest run of each workflowName (the highest databaseId; never an older run that one superseded) and rerun each of those whose conclusion is failure, cancelled or timed_out, not only the run of the check that broke first. Every check is its own run, so a gate or aggregate check that failed only because another check failed is rerun too, with the same command`
// The backstop for a gate that was not rerun, or was rerun before the checks it reports on finished: in the one poll
// that follows a rerun, the checks step reruns such a gate and names its runs as stale. The program then polls once
// more and does not count that poll as red; the poll after it carries no such instruction, so a red check there ends
// the landing.
const STALE_RERUN = (unset, slug) => `This poll follows a rerun of failed jobs at this head. When checks still fail once none is pending, decide whether every failing check is stale: a check that only reports on other checks (a gate or aggregate job) is stale when every check it reports on now passes at head and its own run finished before theirs did (compare updatedAt from ${unset}gh run view <run-id> --repo ${slug} --json updatedAt; it was not rerun, or it was rerun too early). Only when every failing check is stale, rerun each of their runs once with ${unset}gh run rerun <run-id> --repo ${slug} --failed (the run id is in the check's link), do not wait for them, and answer failed with failing and with stale: the run ids you reran. In every other case rerun nothing and return no stale.`
const WITH_STALE = s => ({ ...s, properties: { ...s.properties, stale: { type: 'array', items: { type: 'integer' } } } })
const staleOf = ck => (Array.isArray(ck.stale) ? ck.stale.filter(Number.isInteger) : [])
const CX_USE = 'Use the codex-collaboration skill (invoke it with the Skill tool) to run that Codex'
const CX_WAIT = 'this step may dispatch the Codex reviewer that skill uses, and must wait for its result in this turn.'
const CX_NONE = 'If Codex cannot be run, return available false with the reason in raw_summary; never substitute your own review.'
// A codex-unavailable stop says why (a usage limit and its reset time), so no diagnosis run is needed.
const codexWhy = r => (!r ? 'the Codex review step returned nothing' : typeof r.raw_summary === 'string' && r.raw_summary.trim() ? r.raw_summary : 'the Codex review step gave no reason')
// A Codex refusal whose message is the provider's usage or quota limit (the provider's wording is matched, so "Disk
// quota exceeded" is no quota stop) carries retry_after: the reset time the message gives after "try again at" or
// "resets at", null when it gives none. The limit does not lift by a relaunch, so deliver-batch hands such a stop to
// the owner. The message is read, not a schema member: CODEX's keys are the codex-collaboration skill's contract.
const codexStop = (step, r) => {
  const said = r && typeof r.raw_summary === 'string' ? r.raw_summary : ''
  const quota = /hit your usage limit|exceeded your (?:current )?quota|(?<!disk )quota exceeded|usage limit reached/i.test(said)
  const reset = quota ? ((/\b(?:try again|resets?) (?:at|in|on) ([^.\n]{0,60}?[ap]\.m\.|[^.\n]{1,60})/i.exec(said) || [])[1] || '').trim() : ''
  return stop('codex-unavailable', { step, details: codexWhy(r), codex: r, ...(quota ? { retry_after: reset || null } : {}) })
}
let ACS = null, PLAN_REF = null
// The last head this run knows for each declared branch; read only through own().
const branchTips = Object.create(null)
const branchSnap = () => (declared(plan).length ? { branches: { ...branchTips } } : {})
const planRefs = () => {
  GRANTS = declared(plan); RULES = RULES_FOR(W)
  for (const b of declared(plan)) if (!own(branchTips, b.name)) branchTips[b.name] = headOf(setup.branch_heads, b.name) || b.head
  ACS = JSON.stringify(plan.acceptance)
  PLAN_REF = plan.plan_root ? `Plan: ${plan.plan_root} (task files beside it).` : `No plan: ${LANE === 'live' ? 'live-fault' : 'direct'} lane.`
}
const declaredRanges = () => declared(plan).map(b => `git -C ${b.worktree} diff ${b.base}...${b.name}`)
const EXTRA_RANGES = () => (declared(plan).length ? ` The plan's declared branches belong to this delivery: also review ${declaredRanges().join(' and ')}.` : '')
let chunked = false
// Every declared branch head the setup re-read is the one the record names (no declared branch: always true).
const branchesSame = rec => declared(plan).every(b => !!rec && own(rec.branches, b.name) && sameSha(rec.branches[b.name], headOf(setup.branch_heads, b.name)))
// A ready stop's verified head, unchanged and clean, needs no second review or verify.
let SKIP_REVIEW = !!(verified && plan && sameSha(setup.head, verified.head) && !setup.dirty && plan.tasks.every(t => taskLog.some(d => d.n === t.n)) && branchesSame(verified))
let SKIP_FINAL = !SKIP_REVIEW && LANE === 'standard' && !!finalReviewed && isCommit(finalReviewed.head) && !!plan && plan.tasks.every(t => taskLog.some(d => d.n === t.n)) && !setup.dirty && (sameSha(setup.head, finalReviewed.head) || setup.since_reviewed === 'merge_only') && branchesSame(finalReviewed)
if (!SKIP_REVIEW) verified = null
if (!SKIP_REVIEW && !SKIP_FINAL) finalReviewed = null
// The last commit the final review will cover.
let tip = setup.head || null
// The verification contract as freshly resolved, key order aside: cached results answer only this contract.
const canon = v => Array.isArray(v) ? `[${v.map(canon).join(',')}]` : v && typeof v === 'object' ? `{${Object.keys(v).sort().map(k => `${JSON.stringify(k)}:${canon(v[k])}`).join(',')}}` : JSON.stringify(v)
const VERIFY_CONTRACT = canon(LOCAL)
let VERIFY_CACHED = SKIP_REVIEW && verified.contract === VERIFY_CONTRACT
const DIRECT_IMPL = { ...IMPL, properties: { ...IMPL.properties, acceptance: PLAN_SCHEMA.properties.acceptance, sensitive: { type: 'boolean' }, ineligible: { type: 'boolean' } } }
const GRADED_FINDINGS = {
  ...FINDINGS,
  properties: { ...FINDINGS.properties, acceptance: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, met: { type: 'boolean' }, evidence: { type: 'string' } }, required: ['id', 'met', 'evidence'] } } },
  required: [...FINDINGS.required, 'acceptance'],
}
const DIRECT_FINDINGS = { ...GRADED_FINDINGS, properties: { ...GRADED_FINDINGS.properties, escalate: { type: 'boolean' } } }
// A code criterion the review did not grade met with evidence is an Important finding; a human or evidence criterion
// cannot be shown by a test or command here, so it is not held to this.
const ungradedFindings = (review, criteria) => criteria.filter(a => a.kind === 'code').flatMap(a => {
  const g = (Array.isArray(review.acceptance) ? review.acceptance : []).find(x => x && x.id === a.id)
  if (g && g.met === true && typeof g.evidence === 'string' && g.evidence.trim()) return []
  // The criterion is the finding's subject, so a re-review that restates the finding is a usable review.
  return [{ severity: 'important', failing_input: `criterion ${a.id}`, summary: `Acceptance criterion ${a.id} (${a.text}) is not shown met with evidence: ${g ? (g.met === true ? 'the review gave no evidence' : 'the review graded it unmet') : 'the review did not grade it'}. Assert it with a test, or show the command that proves it.` }]
})
const NO_VERIFY_AC = 'Do not write the declared verification commands as an acceptance criterion: the verify step gates on them.'
const EVIDENCE_FIX = `Produce the evidence each criterion asks for: run the command it names (or the test that asserts it, written first when none exists) in the worktree, and report in notes, per criterion id, the command, its exit status and its last lines. The focused-tests-only rule does not apply to a command a criterion names. If it fails, fix the cause with a regression test and commit; when nothing has to change, commit nothing and return commit equal to start_head. ${FMT}`
const EVIDENCE_REREVIEW = ' These findings are acceptance criteria the review did not see shown met, and the notes carry the evidence produced for each (the command, its exit status and last lines; the diff is empty when nothing had to change): a criterion that evidence shows met is resolved, and one without it, or whose command failed, is still unresolved.'

// The live-fault lane's one implementer returns the test it ran twice: failing at start_head, passing at its commit.
const RUN = { type: 'object', properties: { command: { type: 'string' }, exit: { type: 'integer' }, head: FULL_SHA, failed: STRS, passed: STRS, output: { type: 'string' } }, required: ['command', 'exit', 'head'] }
// A finding of the live-fault review blocks only when it is critical, names a criterion of the issue the review did not
// grade met with evidence, is an ungraded code criterion, or cannot be filed; every other finding is a follow-up issue,
// as is each item the implementer left out.
const LIVE_FINDING_LEAD = f => `Follow-up of #${ISSUE}: the live-fault lane's diff review raised this ${f.severity} finding, which does not block that delivery.`
const LIVE_BEYOND_LEAD = `Follow-up of #${ISSUE}: the live-fault lane left this out of the fix, which stops the harm and nothing more.`
const metWithEvidence = (review, id) => (Array.isArray(review.acceptance) ? review.acceptance : []).some(x => isEntry(x) && x.id === id && x.met === true && typeof x.evidence === 'string' && x.evidence.trim() !== '')
const liveSplit = (review, criteria) => {
  const blocking = []
  const filed = []
  for (const f of review.findings.filter(isEntry)) {
    const entry = f.severity === 'critical' || (namesAc(f) && criteria.some(a => a.id === f.ac) && !metWithEvidence(review, f.ac)) ? null : followUpOf({ ...f, lead: LIVE_FINDING_LEAD(f) }, false)
    if (entry) filed.push(entry)
    else blocking.push(f)
  }
  return { blocking: blocking.concat(ungradedFindings(review, criteria)), filed }
}
const LIVE_IMPL = {
  ...IMPL,
  properties: {
    ...IMPL.properties,
    acceptance: PLAN_SCHEMA.properties.acceptance,
    fault_test: { type: 'object', properties: { name: { type: 'string' }, file: { type: 'string' }, red: RUN, green: RUN }, required: ['name', 'file', 'red', 'green'] },
    beyond: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, summary: { type: 'string' } }, required: ['file', 'summary'] } },
  },
}
const LIVE_FINDINGS = withItems({ ...GRADED_FINDINGS, properties: { ...GRADED_FINDINGS.properties, head: FULL_SHA }, required: [...GRADED_FINDINGS.required, 'head'] }, SCOPED_ITEM)
// The diff the one live-fault review reads is bounded and read for sensitivity first; the rows are those of git diff
// --numstat --no-renames, so a rename is a deletion row for its old path and an addition row for its new one.
const LIVE_MAX_LINES = 80
const LIVE_MAX_FILES = 3
const TEST_PATH = /(^|\/)(tests?|__tests__|specs?)\/|(^|\/)test_[^/]*$|[^/]*(_test\.|\.test\.|\.spec\.)[^/]*$/
const isTestPath = path => TEST_PATH.test(path)
const LIVE_SIZE = { type: 'object', properties: { measured: { type: 'boolean' }, head: FULL_SHA, files: { type: 'array', items: { type: 'object', properties: { path: { type: 'string' }, added: { type: 'integer', minimum: 0 }, deleted: { type: 'integer', minimum: 0 } }, required: ['path', 'added', 'deleted'] } }, sensitive: { type: 'array', items: { type: 'object', properties: { path: { type: 'string' }, why: { type: 'string' } }, required: ['path', 'why'] } } }, required: ['measured'] }
const countOf = v => Number.isInteger(v) && v >= 0
const liveMeasured = size => isEntry(size) && size.measured === true && Array.isArray(size.files) && Array.isArray(size.sensitive)
  && size.files.every(f => isEntry(f) && typeof f.path === 'string' && f.path.trim() !== '' && countOf(f.added) && countOf(f.deleted))
  && size.sensitive.every(f => isEntry(f) && typeof f.path === 'string' && typeof f.why === 'string')
// null, or the one reason a measured diff is refused; the first check that fails wins.
const liveRefusal = size => {
  const rows = new Map()
  for (const f of size.files) rows.set(f.path, (rows.get(f.path) || 0) + f.added + f.deleted)
  let lines = 0
  for (const [k, n] of rows) if (!isTestPath(k)) lines += n
  if (lines > LIVE_MAX_LINES) return `the diff changes ${lines} lines outside tests, over the live lane's ${LIVE_MAX_LINES}`
  if (rows.size > LIVE_MAX_FILES) return `the diff changes ${rows.size} files, over the live lane's ${LIVE_MAX_FILES}`
  if (size.sensitive.length) return `the diff touches ${size.sensitive[0].why} in ${size.sensitive[0].path}`
  return null
}
// The evidence is structural: one command runs at start_head and fails (not 126 or 127: it ran), the runner names the
// test failed and gives its failure line; the same command at the commit passes and the runner names the test passed.
// null, or a short text naming the first missing piece.
const faultTestProblem = impl => {
  const ft = impl && impl.fault_test
  if (!isEntry(ft)) return 'no fault_test was returned'
  const text = v => typeof v === 'string' && v.trim() !== ''
  const { red, green } = ft
  if (!text(ft.name) || !text(ft.file)) return 'the test has no name or file'
  if (!isEntry(red) || !isEntry(green) || !text(red.command) || !text(green.command)) return 'a run names no command'
  if (red.command.trim() !== green.command.trim()) return 'the two runs are not the same command'
  if (!Number.isInteger(red.exit) || [0, 126, 127].includes(red.exit)) return 'the first run did not fail'
  if (!Array.isArray(red.failed) || !red.failed.includes(ft.name)) return 'the runner did not report the test failed'
  if (!text(red.output)) return 'the first run gave no failure line'
  if (green.exit !== 0) return 'the second run did not pass'
  if (!Array.isArray(green.passed) || !green.passed.includes(ft.name)) return 'the runner did not report the test passed'
  if (!sameSha(red.head, impl.start_head)) return 'the first run was not at start_head'
  if (!sameSha(green.head, impl.commit)) return 'the second run was not at the commit'
  if (sameSha(impl.commit, impl.start_head)) return 'the implementer committed nothing: its commit is start_head, so the two runs show no change'
  return null
}

// ---------------- Direct lane ----------------
if (LANE === 'direct') {
  // The deliver-direct skill stays the single source of the implementer's steps; this block never copies its text.
  let impl = null
  if (!taskLog.some(d => d.n === 1)) {
    phase('Tasks')
    impl = await recall(() => call(`${CTX}
${RENEW_FIRST}
Then deliver issue #${ISSUE} in the direct lane. Invoke the deliver-direct skill with the Skill tool to read it: it is the single source for this step. Its steps 1 and 2 are done by this program (the claim is held by ${setup.holder}; the worktree is ${W} on branch ${setup.branch}). Check its Eligibility first: if the issue fails it, change nothing and return status blocked with ineligible true and why. Otherwise follow its step 3 exactly and commit. Do not run its steps 4 to 7: review, verification, ship and close-out belong to this program. Return acceptance (the issue's criteria; ${KIND_GUIDE}) and sensitive (true when the diff touches authentication or authorization, permission or command guards, secrets or credentials, CI/CD or deploy config, or data migrations). ${NO_VERIFY_AC} ${FOCUSED} ${IMPL_RETURN}${CONT && CONT.partial === 1 ? `
An earlier attempt at this task was cut off and may have left uncommitted edits or commits in the worktree (git -C ${W} status, git -C ${W} diff and git -C ${W} log ${RANGE}). Inspect them: keep what matches, finish or redo the rest, and make sure every test was seen failing first; of the removals, make only those not already made against the final result; start_head is the head before this task's first commit.` : ''}${newDecision !== null ? `
That attempt returned blocked: ${JSON.stringify(BLOCKED.notes)}. The owner's decision settles it and is binding: ${JSON.stringify(newDecision)}` : ''}
${RULES}`, { label: 'direct-impl', phase: 'Tasks', agentType: 'implementer', model: 'sonnet', schema: withRenew(DIRECT_IMPL) }), r => r.renew)
    // A reply means the decision reached the implementer; a blocked one below records its own notes.
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
    lookAcs = LOOK_ACS
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
    // The stored plan's risk, not this run's reply, picks the reviewer, so a resumed review keeps the implementer's
    // choice.
    const lite = plan.tasks[0].risk !== 'security'
    const reviewPrompt = isLite => `${CTX}
${isLite ? 'lane: direct. ' : ''}Review the delivery diff git -C ${W} diff ${RANGE} for issue #${ISSUE} against its acceptance criteria ${ACS}. ${KNOW} Report Important or Critical correctness defects and unmet code criteria only, each with a concrete failing input. Return acceptance with one entry per criterion id: met, and evidence, which is the test name and file:line that asserts the criterion, or the command that shows it; a code criterion that is not met, or has no evidence, is an Important finding, and criteria of other kinds are not findings (grade them and give what you observed). ${isLite ? 'If the diff touches authentication or authorization, permission or command guards, secrets or credentials, CI/CD or deploy config, or data migrations, set escalate true. ' : ''}Do not edit anything.`
    let review = await readReview(reviewPrompt(lite), { label: 'direct-review', phase: 'Final review', agentType: lite ? 'reviewer-lite' : 'reviewer', schema: DIRECT_FINDINGS })
    let passedBy = lite ? 'reviewer-lite' : 'reviewer'
    if (lite && review && review.escalate === true) {
      review = await readReview(reviewPrompt(false), { label: 'direct-review-full', phase: 'Final review', agentType: 'reviewer', schema: GRADED_FINDINGS })
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
      const rereview = await readReview(`${CTX}
Re-review only these previously reported findings against the fix: ${span(fix)}; the implementer's notes: ${fix.notes}. Findings: ${JSON.stringify(findings)}. Report any finding still unresolved and any new Important or Critical defect the fix introduced.${evidenceOnly ? EVIDENCE_REREVIEW : ''}`, { label: 'direct-rereview', phase: 'Final review', agentType: 'reviewer-lite', schema: FINDINGS })
      if (!rereview || findingsOf(rereview).length) return stop('direct-review', { review: rereview, findings })
      passedBy = 'reviewer-lite'
    }
    Object.assign(d1, { reviewed_head: fix ? fix.commit : reviewHead, review_rounds: fix ? 1 : 0, reviewer: passedBy })
  }
} else if (LANE === 'live') {
  let impl = null
  if (!taskLog.some(d => d.n === 1)) {
    phase('Tasks')
    const lostRenew = await renew('tasks', 'Tasks')
    if (lostRenew) return lostRenew
    impl = await call(`${CTX}
Deliver issue #${ISSUE} in the live-fault lane: no plan; you are its one implementer. The issue is a declared live fault, as the owner's sprint recorded it: ${JSON.stringify({ observed: LIVE.observed, when: LIVE.when, proven: LIVE.proven })}.
Make the smallest change that stops the harm, and nothing more. A schema, a query, a decision record or any follow-through is never part of it: list each in beyond as {file, summary}, and it is filed as a follow-up issue. The change is at most 80 changed lines outside tests and at most 3 files in all, tests included; it never touches authentication, authorization, secrets, credentials or a permission or command guard: when the fix needs more or touches one, change nothing and return status blocked with the reason in notes.
Work in this order. First write one test that reproduces the harm, and run it before you change any other file, with a command that selects that test alone: it must fail, and the runner must report it failed. Return the command, its exit status, the failed test names and the failure line as fault_test.red, with head the output of git -C ${W} rev-parse HEAD at that run, which is start_head; commit nothing before that run. Then make the change and commit the test and the change. Then, with a clean tree, run the same command again at the committed head: it must pass, and the runner must report it passed. When it fails, fix, commit again and run the same command again. Return that run as fault_test.green (command, exit status, the passed test names), with head the commit. Return fault_test with name, file (its path from the worktree root, as git diff prints it), red and green.
Return acceptance (the issue's criteria; ${KIND_GUIDE}) and beyond. ${NO_VERIFY_AC} ${FOCUSED} ${IMPL_RETURN}${CONT && CONT.partial === 1 ? `
An earlier attempt at this task was cut off and may have left uncommitted edits or commits in the worktree (git -C ${W} status, git -C ${W} diff and git -C ${W} log ${RANGE}). Inspect them: keep what matches, finish or redo the rest, and make sure every test was seen failing first; of the removals, make only those not already made against the final result; start_head is the head before this task's first commit.` : ''}
${RULES}`, { label: 'live-impl', phase: 'Tasks', agentType: 'implementer', model: 'sonnet', schema: LIVE_IMPL })
    if (impl && impl.status === 'blocked') return stop('live-bound', { details: `the live-fault implementer returned blocked: ${clip(typeof impl.notes === 'string' ? impl.notes : '').slice(0, 100)}; ${LIVE_WAY}` })
    if (!implDone(impl)) return haltTask(1, 'task', { task: { n: 1 }, impl })
    // The commit exists: asking again would be a second implementer, so a reply without criteria is final here, never a
    // partial task.
    if (!Array.isArray(impl.acceptance) || !impl.acceptance.length) { partial = undefined; return liveBound(`the live-fault implementer committed ${impl.commit} and returned no acceptance criteria, and asking again would be a second implementer`) }
    const problem = faultTestProblem(impl)
    if (problem !== null) {
      partial = undefined
      return stop('live-evidence', { impl, details: `the change carries no test shown failing before it and passing after it: ${problem}; ${LIVE_WAY}` })
    }
    plan = { status: 'planned', plan_root: null, acceptance: impl.acceptance, tasks: [{ n: 1, title: 'live', file: null, risk: 'standard' }] }
    planReviewed = true
    lookAcs = LOOK_ACS
    const beyond = (Array.isArray(impl.beyond) ? impl.beyond : []).filter(isEntry).map(b => ({ file: textOf(b.file), summary: textOf(b.summary) })).filter(b => b.file && b.summary)
    taskLog.push({ n: 1, commit: impl.commit, review_rounds: 0, reviewer: null, reviewed_head: null, fault_test: impl.fault_test, beyond })
    if (partial === 1) partial = undefined
  }
  planRefs()
  log('live-fault lane: one implementer, one reviewer')
  const d1 = taskLog.find(d => d.n === 1)
  let liveReview = null
  let liveSplitOf = { blocking: [], filed: [] }
  if (!(SKIP_REVIEW || (!impl && present(d1.reviewed_head) && sameSha(d1.reviewed_head, setup.head)))) {
    phase('Final review')
    const lost = await renew('final-review', 'Final review')
    if (lost) return lost
    const size = await call(`${CTX}
Measure the live-fault diff before its review. Run git -C ${W} fetch origin, then return head (git -C ${W} rev-parse HEAD).
Run git -C ${W} diff --numstat --no-renames ${RANGE} and return measured true and files: one {path, added, deleted} per line it prints, where a binary file's - counts are 0, and a rename appears as two lines, its old path and its new path.
Read git -C ${W} diff --no-renames ${RANGE} and return sensitive: one {path, why} per changed path whose change touches authentication or authorization, secrets or credentials, or a permission or command guard (a hook, policy or rule that allows or refuses commands or actions), or [] when none.
On a non-zero exit, return measured false. Run nothing else and change nothing.
${RULES}`, { label: 'live-size', phase: 'Final review', agentType: 'clerk', model: CLERK_MODEL, effort: 'medium', schema: LIVE_SIZE })
    if (!liveMeasured(size)) return stop('live-size', { details: 'the live-fault diff could not be measured' })
    if (!sameSha(size.head, d1.commit)) return liveBound(`the diff was measured at ${typeof size.head === 'string' ? size.head : 'no head'}, not the delivered commit ${d1.commit}`)
    const refusal = liveRefusal(size)
    if (refusal !== null) return stop('live-refused', { details: `${refusal}; ${LIVE_WAY}` })
    // The evidence test must be one this diff changes: a run of a test the diff leaves alone shows nothing about this
    // change.
    const testFile = d1.fault_test.file.trim().replace(/^\.\//, '')
    if (!size.files.some(f => f.path === testFile)) return stop('live-evidence', { details: `the change carries no test shown failing before it and passing after it: the test file ${testFile} is not a path the diff changes; ${LIVE_WAY}` })
    const review = await readReview(`${CTX}
lane: live. Review git -C ${W} diff ${RANGE} for issue #${ISSUE}, the fix of the live fault ${JSON.stringify({ observed: LIVE.observed, when: LIVE.when, proven: LIVE.proven })}: it must stop the harm and nothing more. Acceptance criteria: ${ACS}. The implementer's failing-then-passing test: ${JSON.stringify(d1.fault_test)}. Confirm the test is in the diff and that the failure line of its first run is the observed harm. Return head (git -C ${W} rev-parse HEAD). ${KNOW} ${CRITICAL_MEANS} ${COMMIT_ASK(d1.commit)} Return acceptance with one entry per criterion id: met, and evidence, which is the test name and file:line that asserts the criterion, or the command that shows it; a code criterion that is not met, or has no evidence, is an Important finding, and criteria of other kinds are not findings (grade them and give what you observed). Do not edit anything.`, { label: 'live-review', phase: 'Final review', agentType: 'reviewer', schema: LIVE_FINDINGS }, { once: true })
    // An answered review that was no review is spent (the lane asks once): that stop is final. A reviewer that answered
    // nothing is the one step a resume runs again.
    if (!review) return LOST.includes('live-review') ? stop('live-review', { review: null, details: `the live-fault review answered with no usable review, and asking again would be a second reviewer; ${LIVE_WAY}` }) : stop('live-review', { review: null })
    if (!sameSha(review.head, d1.commit)) return stop('live-bound', { details: `the review read ${typeof review.head === 'string' ? review.head : 'no head'}, not the delivered commit ${d1.commit}; ${LIVE_WAY}` })
    liveReview = review
    liveSplitOf = liveSplit(review, plan.acceptance)
  }
  // Every filing comes first, whatever the outcome: the filed findings and the items the implementer left out, then
  // d1.beyond is gone, and only then does a blocking finding stop the lane.
  const liveEntries = liveSplitOf.filed.concat((Array.isArray(d1.beyond) ? d1.beyond : []).map(b => followUpOf({ severity: 'minor', file: b.file, summary: b.summary, commit: d1.commit, lead: LIVE_BEYOND_LEAD }, false)).filter(Boolean))
  if (liveEntries.length) await fileFollowUps(liveEntries)
  delete d1.beyond
  if (liveSplitOf.blocking.length) return stop('live-review', { review: liveReview, findings: liveSplitOf.blocking, details: `a critical finding blocks the live-fault lane; ${LIVE_WAY}` })
  if (liveReview) Object.assign(d1, { reviewed_head: d1.commit, reviewer: 'reviewer' })
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
  // After a transient setup renew this step is the one retry: it is not re-called, as the acquire fallback is not.
  const askAnswer = () => call(`${CTX}
${RENEW_FIRST}
Then read the owner's answer to the decision prompt of issue #${ISSUE}: run alone, exactly, forge-claim owner-action status --repo ${SLUG} --issue ${ISSUE} --reason decision. It prints one JSON line. Change nothing: post nothing, edit nothing, end nothing. Return verdict, comment_id, questions and decisions exactly as printed.`, { label: 'owner-answer', phase: 'Plan', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: withRenew(ANSWER_SCHEMA) })
  const answer = RENEW_RECALL ? await askAnswer() : await recall(askAnswer, r => r.renew)
  if (!answer) return stop('owner-answer', { result: answer })
  const lost = renewed(answer.renew, 'plan')
  if (lost) return lost
  return takeAnswer(answer)
}
// Only findings the rules-only revise may touch resume as one, a Codex-triggered plan's included. A kept plan with any
// other finding left has spent its one full revise, so it is dropped and planned again with the owner's answer; the
// kept state stays in the cont until that answer is read.
const RESUME_RULES = RESUME_KEPT && rulesOnly(planFindingsKept.rules)
if (ANSWER_NEEDED) {
  const stopped = !CONT && !ACQ_RECALL && !RENEW_RECALL ? takeAnswer(FOLD_ANSWER) : await readAnswer()
  if (stopped) return stopped
}
if (RESUME_KEPT && !RESUME_RULES) dropPlan()
if (AMEND !== null) {
  if (!plan) return why({ stage: 'amend', error: 'this resume plans the kept plan again, which would overwrite the amendment; resume without amend, then amend the new plan after its stop', ...deadOf(), cont: CONT })
  if (planReviewed) {
    const lost = await renew('amend', 'Plan')
    if (lost) return lost
  }
  const am = await call(`${CTX}
Apply the owner's amendment to the plan at ${AMEND_INPUT.plan_root} with one plan-amend run and nothing else. (1) Make a fresh directory with mktemp -d and write the JSON of the Input line below, byte for byte, to a file in it. (2) Run alone and exactly: plan-amend apply --input <that file>. It prints one JSON line; return its status, edits, refused and detail exactly as printed. On a non-zero exit with no JSON line, return status error, empty edits and refused, and its stderr as detail. Edit no file yourself and commit nothing.
Input: ${JSON.stringify(AMEND_INPUT)}
${RULES}`, { label: 'amend', phase: 'Plan', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: AMEND_SCHEMA })
  // The clerk may have written the plan before its reply was lost or came back uncertain, so a stop here cannot hand
  // back results cached before the amend: a relaunch would find every edit already recorded and skip the review and
  // verify of the amended plan. Only a refusal the helper reported itself is known to have written nothing, and it
  // keeps the cont as it came.
  const STALE = (({ verified: _v, final_reviewed: _f, ...rest }) => ({ ...rest, ...(isEntry(CONT.reviewed) ? { reviewed: { ...CONT.reviewed, amended: true } } : {}) }))(CONT)
  if (!am) return why({ stage: 'amend', result: null, ...deadOf(), cont: STALE })
  const graded = am.status === 'applied' && Array.isArray(am.edits) && am.edits.length === AMEND_INPUT.edits.length &&
    am.edits.every((g, i) => isEntry(g) && g.file === AMEND_INPUT.edits[i].file && (g.already === true || (g.exists === true && g.occurrences === 1)))
  if (!graded) return why({ stage: 'amend', amend: am, details: 'plan-amend did not apply every edit; a refused or error status wrote nothing', ...deadOf(), cont: am.status === 'refused' ? CONT : STALE })
  log(`amend: applied ${AMEND_INPUT.edits.length} edit(s) to the plan`)
  amendApplied = true
  // The amended plan's risk labels may be stale, so an unreviewed plan owes the Codex plan review, however small it
  // reads, until one comes back.
  if (!planReviewed) codexOwed = true
  // The amendment is graded by the next round's verdict only; a stop before it (a lost scoped reviewer, a blocked task)
  // hands the mark back, and markReviewed drops it.
  if (reviewed) reviewed = { ...reviewed, amended: true }
  // The amended task file is the owner's answer to a blocked task, unless a decision is still to be worked in below.
  if (newDecision === null && !(BLOCKED && BLOCKED.asked)) blocked = null
  // An applied amend makes every cached result stale, even when every edit was recorded already: an earlier run may
  // have died after the clerk wrote the plan and before any stop said so, leaving only a cont from before the amend.
  // The final review and verify run again.
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
  // A rule finding may name its criterion and its rule and no file: ruled, as the plan review is.
  return readReview(`${CTX}
Re-check only the acceptance criteria of the revised plan at ${plan.plan_root} against every rule of ~/.agents/standards/acceptance-planning.md (read it). The findings that triggered the revision were ${JSON.stringify(triggered)}. Report each criterion that still or newly breaks a rule, with the broken rule's id in the finding's rule and the criterion's id in its ac (on a minor finding too).${decisions.length ? ` The owner's decisions for this issue are binding, so a criterion classified as one of them says breaks no rule: ${decisions.join('\n')}` : ''} Do not edit anything.`, { label: 'plan-rules-review', phase: 'Plan', agentType: 'reviewer', schema: PLAN_REVIEW }, { ruled: true })
}
const ruleFacts = p => canon(p.acceptance.map(a => [a.id, a.text === undefined ? null : a.text, a.kind, a.metric === true, a.verify === undefined ? null : a.verify]))
// The criterion text lives only in the issue and the planner's reply (plan.md maps ids and holds no text), and a
// planner retypes every criterion it returns. The candidate gives each criterion that existed before and that the
// revise does not list as edited its earlier text; the caller takes it whole or not at all. A finding that names a
// criterion no longer keeps its retyped text: that was often the only blocker.
const keepUnlistedText = (before, after, edited) => after.map(a => {
  const was = a && typeof a.id === 'string' && a.id ? before.find(b => b && b.id === a.id) : null
  if (!was || typeof was.text !== 'string' || was.text === a.text || edited.includes(a.id.toLowerCase())) return a
  return { ...a, text: was.text }
})
// The rules reviewer's minor findings on a criterion that also has a blocking finding (the program's or the
// reviewer's), matched by the ac member alone (case and spaces aside, never by reading the summary). They go to the
// rules revise as context: they are no part of rules, so they neither block nor count toward a stop. A minor finding
// with no ac, or on another criterion, stays dropped.
const acKey = f => (isEntry(f) && typeof f.ac === 'string' ? f.ac.replace(/\s+/g, '').toLowerCase() : '')
const notedOn = (found, blocking) => {
  const keys = blocking.map(acKey).filter(k => k !== '')
  return (Array.isArray(found) ? found : []).filter(f => isEntry(f) && f.severity === 'minor' && keys.includes(acKey(f))).slice(0, 8)
}
// One targeted planner call fixing only the given findings, then the program's rule check and the rules re-review. Its
// findings all carry a rule, so its re-review always runs.

// A criterion whose classification the rules pull two ways: a classification rule (R1, R3, R5, R9) blocked it before
// the rules revise, that rule is gone after it, and another one it did not break before blocks it now. A rule that
// survives its revise, and R4, are mechanical: they stay plain plan-review stops.
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
const rulesRevise = async (findings, noted, left = []) => {
  const root = plan.plan_root, was = plan.acceptance
  const also = noted.length ? ` The rules reviewer also noted these minor findings on the same criteria; they are context for choosing the fix, not findings to fix by themselves: ${JSON.stringify(noted)}` : ''
  const halted = await takePlan(await call(planPrompt(`\nFix only these rule findings in your plan at ${root} in place, change nothing else, and return the full result again: ${JSON.stringify(findings)}${also}`), { label: 'plan-rules-revise', phase: 'Plan', agentType: 'planner', schema: PLAN_SCHEMA }), 'plan-rules-revise', findings.concat(left))
  if (halted) return { halted }
  const still = planRules(plan)
  const rr = await rulesReview(findings)
  if (!rr) return { silent: true }
  const rules = still.concat(findingsOf(rr))
  const conflict = conflictOf(findings, rules)
  // The criteria this revise was asked to fix and did change, by the members the rules judge (ruleFacts), as acKey
  // spells an id. A planner retypes every criterion it returns, so one it was not asked about is never read as changed,
  // whatever its wording.
  const facts = a => ruleFacts({ acceptance: [a] })
  const asked = findings.map(acKey).filter(k => k !== '')
  const changed = plan.acceptance.filter(a => !was.some(b => facts(b) === facts(a))).map(a => acKey({ ac: a.id })).filter(k => asked.includes(k))
  return { rules, changed, noted: notedOn(rr.findings, rules), ...(conflict ? { extra: { conflict } } : {}) }
}
// The rules revises of one run, two at most across the delivery (spent: those an earlier stop already counted). The
// second runs without a stop only when every finding the first re-review left is on a criterion that revise was asked
// to fix and changed. A finding on another criterion, one that names none, one no rules revise may touch, or a conflict
// between classification rules stops, and so does whatever the second re-review leaves.

// before and was: the findings and notes the last revise was given, for a stop whose re-review said nothing.
const rulesRounds = async (rules, noted, spent, left = []) => {
  let r = await rulesRevise(rules, noted, left), rounds = spent + 1, before = rules, was = noted
  if (rounds < 2 && !r.halted && !r.silent && !r.extra && rulesOnly(r.rules) && r.rules.every(f => r.changed.includes(acKey(f)))) {
    log(`plan-rules-revise: the ${r.rules.length} finding(s) left are all on criteria the revise changed; one more rules revise`)
    before = r.rules
    was = r.noted
    r = await rulesRevise(before, was, left)
    rounds++
  }
  return { ...r, rounds, before, was }
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
const SILENT = () => ({ details: `the rules re-reviewer ${silence('plan-rules-review')}` })
const settleRevise = async (revised, planFindings, reviewedFacts, reviewedCriteria) => {
  const halted = await takePlan(revised, 'plan-revise', planFindings)
  if (halted) return { ...halted, findings: planFindings }
  // The restored candidate replaces the reply only when it makes the skip below fire; a renumbered, reused or
  // duplicated id, or any other change, leaves the reply exactly as returned. A plan-revise reply with no
  // criteria_edited is unknown: no restore. A branch revise that takePlan ran after it adds its own list to the
  // plan-revise reply's.
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
  const sameRules = !planFindings.some(f => present(f.rule)) && !still.length && ruleFacts(plan) === reviewedFacts
  if (sameRules) log('plan rules re-review skipped: no finding named a rule and the acceptance criteria are unchanged')
  const rr = sameRules ? { findings: [] } : await rulesReview(planFindings)
  if (!rr) return reviewStop(planFindings, planFindings, 0, SILENT())
  let rules = still.concat(findingsOf(rr)), rounds = 0, noted = notedOn(rr.findings, rules), extra
  if (rulesOnly(rules)) {
    const r = await rulesRounds(rules, noted, rounds, planFindings)
    if (r.halted) return { ...r.halted, findings: planFindings }
    rounds = r.rounds
    if (r.silent) return reviewStop(r.before, planFindings, rounds, SILENT(), r.was)
    rules = r.rules
    noted = r.noted
    extra = r.extra
  }
  if (rules.length) return reviewStop(rules, planFindings, rounds, extra, noted)
  return null
}
// The task revise: a resume of a task-blocked cont with a new decision has a planner amend that task's file from the
// decision and the implementer's notes before the implementer runs again. A revise that does not end in an accepted
// plan (questions, a malformed reply, rule findings left, a done task dropped or re-pointed, a criterion removed) keeps
// the cont's plan and its blocked member. The decision stays unused so the same resume tries again, except after
// questions, where it is kept; a rules conflict's stop carries the conflict for deliver-batch's owner action.
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
  if (!renewedHere) {
    const lost = await renew('plan', 'Plan')
    if (lost) return lost
  }
  const prior = { plan, reordered }
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
    planReviewed = true
    planFindingsKept = null
    // The decision reached the planner, which asked on: it is kept, so the resume with the answer shows the planner
    // both.
    if (Array.isArray(failed.needs_user)) { blocked = { ...blocked, asked: true }; decisionPending = false }
    if (isEntry(failed.conflict)) decisionPending = false
    const said = Object.fromEntries(['needs_user', 'invalid', 'branch_problems', 'rules', 'conflict', 'details'].filter(k => own(failed, k)).map(k => [k, failed[k]]))
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
const codexPlanCall = () => call(`${CTX}
Plan: ${plan.plan_root} (task files beside it). Acceptance criteria: ${JSON.stringify(plan.acceptance)}.${SPEC}
Run the project's configured independent plan review: the contract's workflow.review.plan is the command ${REVIEW_PLAN}. ${CX_USE} plan review over the plan at that path against issue #${ISSUE} in the worktree ${W}, giving it the code map ${CODE_MAP} as its code map input; ${CX_WAIT} Return Codex's Important or Critical findings as they are without adding your own review; verdict pass if none. ${CX_NONE}
${RULES}`, { label: 'plan-codex', phase: 'Plan', agentType: 'clerk', model: CLERK_MODEL, effort: 'high', schema: CODEX })
// The skip was decided on the plan before a revise or an amend; a plan that is no longer small gets the Codex plan
// review it skipped, before it is marked reviewed. Owed from the first call, so a stop of it keeps the review due on a
// resume. null = nothing owed or it passed.
const lateCodexPlan = async () => {
  if (!(REVIEW_PLAN && (codexOwed || (codexSkipped && !smallPlan(plan))))) return null
  log('codex plan review: owed (the plan is no longer small or was amended), running it on the plan as it stands')
  codexOwed = true
  const late = await codexPlanCall()
  if (!late || !late.available) return codexStop('plan', late)
  codexSkipped = false
  codexOwed = false
  const lateFindings = findingsOf(late).map(f => ({ ...f, source: 'codex' }))
  log(`codex plan review: ${lateFindings.length} blocking findings`)
  return lateFindings.length ? reviewStop([], lateFindings, 1) : null
}
if (RESUME_RULES) {
  const { rules, findings, rounds } = planFindingsKept
  const noted = notedOn(planFindingsKept.noted, rules)
  const r = await rulesRounds(rules, noted, rounds)
  if (r.halted) return { ...r.halted, findings }
  if (r.silent) return reviewStop(r.before, findings, r.rounds, SILENT(), r.was)
  if (r.rules.length) return reviewStop(r.rules, findings, r.rounds, r.extra, r.noted)
  planFindingsKept = null
  const lateStop = await lateCodexPlan()
  if (lateStop) return lateStop
  planReviewed = true
}
if (!planReviewed) {
  const PLAN_CODEX = REVIEW_PLAN && (!smallPlan(plan) || codexOwed) ? REVIEW_PLAN : null
  // Owed stays set through every stop below until the review comes back available; with none configured nothing is
  // owed.
  if (!PLAN_CODEX) codexOwed = false
  codexSkipped = !!REVIEW_PLAN && !PLAN_CODEX
  if (REVIEW_PLAN && !PLAN_CODEX) log(`codex plan review: skipped, a small plan (${plan.tasks.length} of at most ${SMALL_PLAN_TASKS} tasks, none of risk security)`)
  const planCodexP = PLAN_CODEX ? codexPlanCall() : Promise.resolve(null)
  const ruleFindings = planRules(plan)
  const narrow = REVIEW_SIZING && !!PLAN_CODEX
  const planReviewClaude = await readReview(`${CTX}
Review the implementation plan at ${plan.plan_root} (and its task files) against issue #${ISSUE} (gh issue view ${ISSUE} --repo ${SLUG} --json title,body,comments).${SPEC} ${KNOW} ${MAP_FIRST} Report only Important or Critical defects: ${narrow ? PLAN_RUBRIC_SIZED : PLAN_RUBRIC}, ${PROVING_FINDING}, or an acceptance criterion that breaks a rule of ~/.agents/standards/acceptance-planning.md (read it; put the broken rule's id in the finding's rule).${narrow ? ` ${PLAN_CODEX_OWNS}` : ''} No style notes. Do not edit anything.`, { label: 'plan-review', phase: 'Plan', agentType: 'reviewer', schema: PLAN_REVIEW }, { ruled: true })
  const planCodexR = await planCodexP
  if (!planReviewClaude) return stop('plan-review', { details: `the plan reviewer ${silence('plan-review')}` })
  let planFindings = ruleFindings.concat(findingsOf(planReviewClaude))
  if (PLAN_CODEX) {
    if (!planCodexR || !planCodexR.available) return codexStop('plan', planCodexR)
    codexOwed = false
    planFindings = planFindings.concat(findingsOf(planCodexR).map(f => ({ ...f, source: 'codex' })))
    log(`codex plan review: ${findingsOf(planCodexR).length} blocking findings`)
  }
  if (planFindings.length) {
    log(`plan review: ${planFindings.length} blocking findings, revising once`)
    const reviewedFacts = ruleFacts(plan), reviewedCriteria = plan.acceptance
    const revised = await call(planPrompt(`\n${MAP_FIRST} A reviewer found these defects in your plan at ${plan.plan_root}; fix them in place and return the full result again, with criteria_edited: the ids of the criteria whose text you changed to fix a finding (typing the same criterion again in other words is not a change; an empty list when you changed none): ${JSON.stringify(planFindings)}`, REVISE_PACE), { label: 'plan-revise', phase: 'Plan', agentType: 'planner', schema: PLAN_SCHEMA })
    const unsettled = await settleRevise(revised, planFindings, reviewedFacts, reviewedCriteria)
    if (unsettled) return unsettled
    const lateStop = await lateCodexPlan()
    if (lateStop) return lateStop
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
// A blocked task that names a later task of the plan (blocked_on) is moved once to just after it, so every other task
// keeps its place. A plan declares no dependencies between tasks, so the move is refused, and the task stops with why,
// when the task was moved before, another moved task still waits, or the named task is not a later unfinished one or
// commits in another worktree. No done task runs again.
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
  const implPrompt = `${first ? `${start}\n${RENEW_FIRST}\nThen implement` : `${start}\nImplement`} task ${t.n} (${t.title}) exactly as its task file ${t.file} specifies: write the failing test first and see it fail, implement, see it pass, run the task's focused test commands, then once for each acceptance criterion the task covers (not for each test or branch; at least once when the task adds a test) temporarily remove the code that satisfies it and confirm the tests that pin it fail, restore, and commit only this task's files in the worktree. ${REMOVALS} ${MAP_FIRST} ${FOCUSED} ${IMPL_RETURN}${PUSH_HERE} Return status blocked with notes if the task file is wrong or impossible, and blocked_on: the number of the later task of this plan it needs first, if that is why; when you name it, first undo every uncommitted edit you made, leaving the worktree as you found it.${KEEP_WAITING}${moved ? ` Task ${moved.after}, which this task was blocked on, is done now.` : ''}${(CONT && CONT.partial === t.n) || moved ? `
An earlier attempt at this task was cut off and may have left uncommitted edits or commits in the worktree (git -C ${TW} status, git -C ${TW} diff and git -C ${TW} log ${B ? `${B.base}..HEAD` : RANGE}). Inspect them: keep what matches the task file, finish or redo the rest, and make sure every test was seen failing first; of the removals, make only those not already made against the final result; start_head is ${moved ? 'HEAD as this attempt starts' : "the head before this task's first commit"}.` : ''}
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
  // A task that ends with no new commit (an issue comment, a check that needs no edit) has no diff, and a review of the
  // empty range head..head is refused. Its first pass is a no-change check instead: a reviewer judges from the task
  // file whether a tracked file must change (then it is not done) and confirms each required output. reviewer-lite
  // reads only a bounded diff, so such reviews run on reviewer.

  // Whether a reply added a commit is read against a head the program holds, never its own start_head: for a task, the
  // head its worktree was accepted at (for a partial task, the last done task of that worktree, else the worktree's
  // base); for a fix, the head just reviewed. A start above it would hide commits.
  const lastDone = taskLog.filter(d => (B ? d.branch === B.name : !present(d.branch))).pop()
  const tracked = partial === t.n ? null : B ? branchTips[B.name] : tip
  const accepted = present(tracked) ? tracked : lastDone && present(lastDone.commit) ? lastDone.commit : B ? B.base : setup.base_sha
  const taskStart = sameSha(impl.start_head, accepted) ? impl.start_head : accepted
  const liteLane = t.risk === 'mechanical' || t.risk === 'low'
  // False until the task's diff had its first pass; a task with no commit has none to review.
  let diffReviewed = !sameSha(impl.commit, accepted)
  // A no-change check names the head the program holds (the fuller spelling), never the reply's short or uppercase one.
  // IMPL's pattern refuses such a spelling, so no IMPL reply reaches this with one; kept for a reply the harness let
  // through.
  let held = diffReviewed ? impl.commit : fuller(accepted, impl.commit)
  // reviewer-lite first-passes only a task whose declared lane is mechanical or low (its lane verification mode).
  let reviewer = liteLane && diffReviewed ? 'reviewer-lite' : 'reviewer'
  const fileless = !diffReviewed
  const diffReview = (range, label, answers) => readReview(`${start}
${reviewer === 'reviewer-lite' ? `lane: ${t.risk}. ` : ''}Review the diff of task ${t.n} only: ${range} (and the task file ${t.file} as its contract). ${KNOW} Report Important or Critical correctness defects and unmet task requirements only, each with a concrete failing input. No style notes. Do not edit anything.${answers ? ` The task first ended with no commit, and this diff answers these findings: ${JSON.stringify(answers)}; report any still unresolved.` : ''}`, { label, phase: 'Tasks', agentType: reviewer, schema: FINDINGS }, { fileless })
  // Tracked files only: an untracked file (a build output, a tool's cache) is no edit of the task, and a waiting task's
  // kept edits are not this task's.
  const HEAD_UNMOVED = h => `First confirm that git -C ${TW} rev-parse HEAD prints ${h} and git -C ${TW} status --porcelain --untracked-files=no prints nothing: another head or an uncommitted change to a tracked file is a finding.${waiting ? `${WAITS}those are not a finding.` : ''}`
  const CONFIRM = `with read-only commands that change nothing, the task file's own verification commands or a lookup (run a gh command as ${UNSET}gh ...)`
  let review = diffReviewed ? await diffReview(`git -C ${TW} diff ${taskStart}..${impl.commit}`, `review-${t.n}`) : await readReview(`${start}
Task ${t.n} ended with no new commit: the head of ${TW} is still ${held}. There is no diff to review and none is missing; do not ask for a range. Judge the task from its task file ${t.file} (the contract) and the implementer's report: notes: ${impl.notes}; checks run: ${JSON.stringify(Array.isArray(impl.tests) ? impl.tests : [])}. ${HEAD_UNMOVED(held)} Then decide two things. 1. Does the task file require a tracked file to be created, changed or deleted? If it does, the task is not done: report one Critical finding naming the files it requires. 2. If it requires none, is every output the task file asks for in place? Confirm each yourself, ${CONFIRM}; the implementer's word alone is not evidence, and an output you cannot confirm is a finding. Report Important or Critical findings only, each with what is missing. Do not edit anything.`, { label: `review-${t.n}`, phase: 'Tasks', agentType: 'reviewer', schema: FINDINGS }, { fileless })
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
      review = await readReview(`${start}
Re-review only these previously reported findings for task ${t.n} against the implementer's answer. The fix made no new commit (the head of ${TW} is still ${held}), so there is no fix diff to review and none is missing; do not ask for a range. The implementer's notes: ${fix.notes}. Findings: ${JSON.stringify(findingsOf(review))}. ${HEAD_UNMOVED(held)} Then check each answer yourself against the task file ${t.file}${diffReviewed ? `, the task's diff (git -C ${TW} diff ${taskStart}..${fix.commit})` : ''} and the evidence the notes name, ${CONFIRM}; a finding the evidence does not refute is still unresolved. Report any finding still unresolved. Do not edit anything.`, { label, phase: 'Tasks', agentType: 'reviewer', schema: FINDINGS }, { fileless })
    } else if (!diffReviewed) {
      reviewer = liteLane ? 'reviewer-lite' : 'reviewer'
      review = await diffReview(`git -C ${TW} diff ${taskStart}..${fix.commit}`, label, findingsOf(review))
      diffReviewed = true
    } else {
      review = await readReview(`${start}
Re-review only these previously reported findings for task ${t.n} against the fix: git -C ${TW} diff ${reviewed}..${fix.commit}; the implementer's notes: ${fix.notes}. Findings: ${JSON.stringify(findingsOf(review))}. Report any finding still unresolved and any new Important or Critical defect the fix introduced.`, { label, phase: 'Tasks', agentType: 'reviewer-lite', schema: FINDINGS }, { fileless })
    }
    if (!review) return halt('task-review', { task: t, review: null })
  }
  if (findingsOf(review).length) return halt('task-review', { task: t, review })
  taskLog.push({ n: t.n, commit: impl.commit, review_rounds: rounds, reviewer, ...(B ? { branch: B.name } : {}), ...(diffReviewed ? {} : { no_change: true }) })
  if (B) branchTips[B.name] = impl.commit
  else tip = impl.commit
  if (partial === t.n) partial = undefined
}
// When every task ended with no commit, the branch holds nothing to review, verify or land: the final review would get
// an empty range and the pull request no commit. Read from the done record (no_change), which a resume carries, never
// from a head. The tasks' outputs are in place and recorded; the owner closes the issue.
if (plan.tasks.length && plan.tasks.every(t => taskLog.some(d => d.n === t.n && d.no_change === true))) {
  return stop('no-changes', { details: `every task ended with no commit: the branch ${setup.branch} holds nothing to review or land. The tasks' outputs are in place; close the issue by hand, or amend the plan if a file change was meant` })
}

// ---------------- Final review ----------------
phase('Final review')
const SIZED_CHUNK_LINES = 1500
let groups = []
let sizedWhole = false
const PER = 3
for (let i = 0; i < plan.tasks.length; i += PER) groups.push(plan.tasks.slice(i, i + PER))
chunked = groups.length > 1
// A resume that skips the final review reports the shape it had.
if ((SKIP_REVIEW || SKIP_FINAL) && finalReviewed && finalReviewed.whole === true) chunked = false
if (SKIP_FINAL) log(`final review passed at ${finalReviewed.head}; skipped`)
if (!SKIP_REVIEW && !SKIP_FINAL) {
{
  const lost = await renew('final-review', 'Final review')
  if (lost) return lost
}
// The first round reviews the whole delivery; a later one reviews only what changed since the commit the last review
// read, with the findings still open re-checked at the head. Findings the bound cut from the cont (dropped) can only be
// found again by a full review.
if (dropped > 0) log(`final review: ${dropped} open finding(s) were not kept in cont: this round reviews the whole delivery`)
const SCOPED = LANE === 'standard' && reviewRounds > 0 && reviewed !== null && dropped === 0
// The round's end commit: the tip when the run knows one, else the head a reviewer of the round read.
const endOf = replies => (isCommit(tip) ? normSha(tip) : ((replies.find(r => isEntry(r) && isCommit(r.head)) || {}).head || null))
const FINAL_SCHEMA = isCommit(tip) ? FINAL_FINDINGS : FINDINGS_HEAD
const HEAD_ASK = ` Return head: the full sha git -C ${W} rev-parse HEAD prints, run before you read anything.`
// Shared by the chunk, the integration and the scoped review.
const VERIFY_OWNED = BEFORE_PR ? `The verify step runs the pre-pull-request commands after the review.` : `The verify step runs the declared verification: run only the targeted tests a finding needs, never the whole suite.`
const TWO_AXES = `Two axes: correctness (real defects with a concrete failing input) and conformance (each task and each acceptance criterion of kind code is met, with the test or command that shows it).`
// The binding sentence of a round the owner admitted after the cap; an oscillating resume says its own (DECIDED).
const CAP_BINDING = osc !== null ? '' : capDecision !== null ? ` The owner decided how to settle the findings left open at the review round cap, and the decision is binding: ${JSON.stringify(capDecision)}.`
  : CAP_KEPT && amendApplied ? ' The owner amended the plan after the review round cap (plan.md, Amendments): it is binding.' : ''
const AMENDED = ' The owner amended the plan since the last review (plan.md, Amendments): grade the head against the amended tasks and acceptance criteria, not only the commits above.'
// An oscillating resume's decision binds the scoped reviewer too, which judges the disputed behavior again before any
// fix wave does; the cap's own sentence is CAP_BINDING.
const SCOPED_BINDING = osc !== null ? (oscDecision !== null ? ` The owner decided the approach for ${osc.file}, and the decision is binding: ${JSON.stringify(oscDecision)}.` : amendApplied ? ` The owner amended the plan for ${osc.file} (plan.md, Amendments): it is binding.` : '') : CAP_BINDING
let finalFindings = []
let closedNums = []
if (SCOPED) {
  chunked = false
  const O = reviewed.head
  const N = isCommit(tip) ? normSha(tip) : 'HEAD'
  const since = (wt, o, n, up) => `First run git -C ${wt} merge-base --is-ancestor ${o} ${n}. When it succeeds, read the branch's own commits, git -C ${wt} log -p --no-merges ${o}..${n} ^${up}, and for each merge git -C ${wt} rev-list --merges ${o}..${n} ^${up} lists, only what it changes beyond a clean merge: git -C ${wt} show --remerge-diff <merge>. When it fails, the history was rewritten: read git -C ${wt} diff ${o} ${n} instead.`
  const ranges = declared(plan).map((b, i) => (own(reviewed.branches, b.name)
    ? ` For the declared branch ${b.name} in ${b.worktree}, review only what changed since ${reviewed.branches[b.name]}. ${since(b.worktree, reviewed.branches[b.name], isCommit(branchTips[b.name]) ? normSha(branchTips[b.name]) : b.name, b.base)}`
    : ` Also review ${declaredRanges()[i]}.`)).join('')
  const open = carried.length ? ` These findings were left open by the last round, numbered from 1: ${JSON.stringify(carried.map((f, i) => ({ n: i + 1, ...f })))}. Check each against the code at the head: report again each one the head still shows open, and return closed: the numbers of those it shows closed. One you neither report nor close stays open.` : ''
  const scoped = await readReview(`Issue #${ISSUE} of ${SLUG}. Worktree: ${W} (branch ${setup.branch}, base ${setup.base_sha}, integration branch ${INT}).
${PLAN_REF} Acceptance criteria: ${ACS}.
Scoped review round ${reviewRounds + 1}: review only what changed since ${O}, the commit the last review read. Fetch origin first (git -C ${W} fetch origin). ${since(W, O, N, `origin/${INT}`)} Never read the delivery's whole range: earlier rounds reviewed it.${ranges}${N === 'HEAD' ? HEAD_ASK : ''}${open}${amendApplied || reviewed.amended === true ? AMENDED : ''}${SCOPED_BINDING ? `${SCOPED_BINDING} Report no finding that only disputes it.` : ''} ${KNOW} ${TWO_AXES} ${VERIFY_OWNED} ${CRITICAL_MEANS} ${SCOPED_BLOCKS} ${COMMIT_ASK(N === 'HEAD' ? 'the head you return' : N)} Report Important or Critical findings only, each in those commits${amendApplied || reviewed.amended === true ? ', among the findings above or in a requirement of the amended plan the head does not meet' : ' or among the findings above'}. Do not edit anything.`, { label: 'final-scoped', phase: 'Final review', agentType: 'reviewer', schema: SCOPED_FINDINGS })
  if (!scoped) return stop('final-review', { details: `the scoped reviewer ${silence('final-scoped')}` })
  finalFindings = scoped.findings.filter(isEntry)
  closedNums = Array.isArray(scoped.closed) ? scoped.closed.filter(Number.isInteger) : []
  reviewRounds++
  markReviewed(endOf([scoped]))
  log(`final review: scoped round ${reviewRounds}: ${carried.filter((c, i) => closedNums.includes(i + 1)).length} carried finding(s) closed at the head`)
} else {
if (REVIEW_SIZING && chunked) {
  let sizeReply = null
  let sizeWhy = 'no usable reply'
  try {
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
${PLAN_REF} Acceptance criteria: ${ACS}. Pass this definition to Codex with those criteria, as the caller's input: ${CRITICAL_MEANS} Set ac on a finding that names an unmet criterion, at any severity.
Run the project's configured independent code review: the contract's workflow.review.code is the command ${REVIEW_CODE}. ${CX_USE} diff review over the delivery range ${RANGE} in the worktree ${W}, with no review package;${EXTRA_RANGES()} ${CX_WAIT} Return Codex's Important or Critical findings as they are (correctness defects with a concrete failing input, unmet criteria) without adding your own review; verdict pass if none. ${CX_NONE}
${RULES}`, { label: 'final-codex', phase: 'Final review', agentType: 'clerk', model: CLERK_MODEL, effort: 'high', schema: FINAL_CODEX }) : Promise.resolve(null)
const finals = await parallel(groups.map((g, gi) => () => readReview(`${CTX}
${PLAN_REF} Acceptance criteria: ${ACS}.
Final review${chunked ? ` of chunk ${gi + 1}/${groups.length}: tasks ${g.map(t => t.n).join(', ')} only (their files: ${g.map(t => t.file).join(', ')}); grade only these tasks` : ' of the whole delivery'}: git -C ${W} diff ${RANGE}${chunked ? ' restricted to the paths these tasks own' : ''}.${EXTRA_RANGES()} ${KNOW} Two axes: correctness (real defects with a concrete failing input) and conformance (each task and each acceptance criterion of kind code is met, with the test or command that shows it). ${VERIFY_OWNED} ${CRITICAL_MEANS} Report Important or Critical findings only. Do not edit anything.${isCommit(tip) ? '' : HEAD_ASK}`, { label: `final-${gi + 1}`, phase: 'Final review', agentType: 'reviewer', schema: FINAL_SCHEMA })))
if (finals.some(r => !r)) {
  await codexP
  return stop('final-review', { details: `a final reviewer ${silence(...groups.map((g, gi) => `final-${gi + 1}`))}`, finals })
}
// The integration review reads only the chunk verdicts, so it runs beside Codex. It counts as dead only where its reply
// is read: a Codex stop leaves it unused, and still running unread, on purpose: waiting for it would cost wall time for
// nothing.
const integP = chunked ? readReview(`${CTX}
${PLAN_REF} Integration review. The delivery was reviewed in ${groups.length} chunks by task; their verdicts: ${JSON.stringify(finals)}. Read the full changed-file list (git -C ${W} diff --stat ${RANGE}) and the head tree as needed.${EXTRA_RANGES()} ${KNOW} Check the interfaces between chunks and grade every acceptance criterion: ${ACS}. ${VERIFY_OWNED} ${CRITICAL_MEANS} Report Important or Critical findings only.${isCommit(tip) ? '' : HEAD_ASK}`, { label: 'final-integration', phase: 'Final review', agentType: 'reviewer', schema: FINAL_SCHEMA }, { optional: true }) : null
if (integP) integP.catch(() => {})
const codexR = await codexP
finalFindings = finals.flatMap(blockingOf)
if (REVIEW_CODE) {
  if (!codexR || !codexR.available) return codexStop('code', codexR)
  finalFindings = finalFindings.concat(blockingOf(codexR).map(f => ({ ...f, source: 'codex' })))
  log(`codex review: ${blockingOf(codexR).length} blocking findings`)
}
let integ = null
if (integP) {
  integ = await integP
  if (!integ) {
    if (!LOST.includes('final-integration')) DEAD.push('final-integration')
    return stop('final-review', { details: `the integration reviewer ${silence('final-integration')}` })
  }
  finalFindings = finalFindings.concat(blockingOf(integ))
}
// The round reached its verdict: it is counted, and a full one has found again whatever the bound once cut.
reviewRounds++
dropped = 0
markReviewed(endOf(finals.concat(integ ? [integ] : [])))
}
// What an earlier stop left open joins the fresh findings, a repeat (same file and summary) once; a scoped reviewer
// drops the ones it closed. A reported finding stands for one carried finding only: two carried ones alike in file and
// summary but not in failing input are two findings, and a repeat of one is not the other.
const taken = new Set()
const fromStop = carried.filter((c, i) => {
  if (closedNums.includes(i + 1)) return false
  const j = finalFindings.findIndex((f, at) => !taken.has(at) && findingKey(f) === findingKey(c))
  if (j >= 0) taken.add(j)
  return j < 0
})
if (fromStop.length) log(`final review: ${fromStop.length} finding(s) carried from the earlier fix-wave-review stop`)
// A scoped round blocks only on a critical finding or one naming an unmet criterion. Closures are reconciled above, and
// a report that stands for an open carried finding blocks; each other report is blocking or filed as a follow-up,
// before any severity filter, so a minor one is filed too. A finding that cannot be filed (no file or no full commit)
// blocks when non-minor and is dropped when minor.
const triage = async list => {
  const blocking = []
  const toFile = []
  for (const f of list) {
    if (f.severity === 'critical' || namesAc(f)) { blocking.push(f); continue }
    const entry = followUpOf(f, false)
    if (!entry) {
      if (f.severity !== 'minor') blocking.push(f)
      log(`final review: a ${f.severity} finding names no file or commit and cannot be filed; ${f.severity !== 'minor' ? 'it blocks' : 'it is dropped'}`)
      continue
    }
    if (followUps.concat(pending, toFile).some(g => followUpKey(g) === followUpKey(entry))) {
      log(`final review: a ${entry.severity} finding in ${entry.file} is already filed or pending; it is not filed again`)
      continue
    }
    toFile.push(entry)
  }
  if (toFile.length) await fileFollowUps(toFile)
  return blocking
}
if (SCOPED) finalFindings = finalFindings.filter((f, at) => taken.has(at)).concat(await triage(finalFindings.filter((f, at) => !taken.has(at))))
finalFindings = finalFindings.concat(fromStop)
// A round that leaves findings open at the cap stops here, before any fix wave, unless the owner brought something new
// to this resume. Set once a fix wave starts away from the reviewed head: the passed marker then never records the tip,
// below which lie commits no review has read.
let gapSeen = false
const ownerNew = capDecision !== null || oscDecision !== null || amendApplied
if (!finalFindings.length) capMark = null
if (finalFindings.length && reviewRounds >= ROUND_CAP && !ownerNew) {
  keep(finalFindings)
  capMark = { rounds: reviewRounds, findings: carried.map(f => f.summary) }
  log(`final review: the review round cap (${ROUND_CAP} rounds) is reached with ${carried.length} finding(s) open; no fix wave`)
  return stop('fix-wave-review', { round_cap: capMark, fix_waves: fixWaves })
}
if (finalFindings.length) {
  // At most MAX_WAVES waves. The second runs only when the first re-review's findings all narrow the first round (same
  // kind of defect on another path); a new kind stops. The third runs only when the second's findings all narrow, are
  // all important and no more than the first left. A finding not marked narrowing counts as narrowing when its file is
  // one the wave just re-reviewed changed: a regression inside the fix's own diff.

  // A fix that draws a new finding where it was made is the oscillation signal. Its first firing gives the next wave
  // that file's history with the request to change the approach or rebut; its second stops at fix-wave-review with
  // oscillating: { file, rounds }, which survives in cont so a resume starts at the stopped count. The diverging bound
  // still counts waves across runs.

  // Waves after the first get only the first-round findings that may still be open, all of them when a finding names no
  // file or its parent cannot be told. Every wave is told to change only what its findings need.
  const MAX_WAVES = 3
  const rounds = [finalFindings]
  const fixes = []
  const RESUMED = osc
  // A resumed file starts as already fired twice (the count its stop reached), so its next firing stops again.
  const fired = RESUMED ? { [RESUMED.file]: 2 } : {}
  let turning = RESUMED ? [RESUMED.file] : []
  const onFile = (list, file) => list.filter(f => fileOf(f) === file).slice(0, CARRY_MAX).map(f => clip(String(f.summary)))
  const before = file => (RESUMED && RESUMED.file === file ? RESUMED.rounds.slice(0, RESUMED.rounds.length && own(RESUMED.rounds[RESUMED.rounds.length - 1], 'round') ? -1 : undefined) : [])
  const historyOf = file => {
    const kept = before(file)
    const base = kept.filter(x => own(x, 'wave')).length
    return kept.concat(fixes.flatMap((x, j) => [{ round: base + j, findings: onFile(rounds[j], file) }, { wave: base + j + 1, ...(x.files.length === 1 && x.files[0] === file && x.notes ? { notes: clip(x.notes) } : {}), range: x.range }]))
  }
  const DECIDED = !RESUMED ? '' : oscDecision !== null ? ` The owner decided the approach for ${RESUMED.file}, and the decision is binding: ${JSON.stringify(oscDecision)}.` : amendApplied ? ` The owner amended the plan for ${RESUMED.file} (plan.md, Amendments): it is binding.` : ''
  const FOLLOW = oscDecision !== null ? 'follow that decision' : 'follow that amendment'
  let waveFindings = finalFindings
  // A scoped round's re-review blocks on a report that stands for one of the wave's findings (one each: its exact
  // repeat, else one in its file), a critical one and one naming an unmet criterion; the other reports are filed. The
  // full round's re-review keeps its rule.
  const rereviewed = async (rv, wave) => {
    const reports = rv.findings.filter(isEntry)
    // Each wave finding is stood for by at most one report, and each report stands for at most one: an exact repeat
    // first, then, for a finding left without one, a report in its file (marked narrowing first), whatever its
    // relation, since a reviewer may reword a finding it still holds. A minor report that names no criterion and is not
    // marked narrowing is a note of its own, not a rewording of a blocker: it never stands for one, and triage files
    // it.
    const stands = new Map()
    const open = []
    wave.forEach((w, i) => {
      const j = reports.findIndex((f, at) => !stands.has(at) && findingKey(f) === findingKey(w))
      if (j >= 0) stands.set(j, w)
      else open.push(i)
    })
    for (const i of open) {
      const w = wave[i]
      if (!fileOf(w)) continue
      const same = reports.map((f, at) => at).filter(at => !stands.has(at) && fileOf(reports[at]) === fileOf(w) && (reports[at].severity !== 'minor' || namesAc(reports[at]) || reports[at].relation === 'narrowing'))
      const j = same.find(at => reports[at].relation === 'narrowing')
      if (j !== undefined || same.length) stands.set(j !== undefined ? j : same[0], w)
    }
    // A report that stands for a wave finding blocks, as an important or critical one always did. A minor repeat of a
    // critical finding or one naming a criterion keeps the finding's severity and ac: it is still open until a review
    // resolves it. A minor repeat of any other finding is dropped.
    const held = [...stands.keys()].sort((x, y) => x - y).flatMap(at => {
      const f = reports[at]
      const w = stands.get(at)
      if (f.severity !== 'minor' || namesAc(f)) return [f]
      return w.severity === 'critical' || namesAc(w) ? [{ ...f, severity: w.severity, ...(namesAc(w) ? { ac: w.ac } : {}) }] : []
    })
    return held.concat(await triage(reports.filter((f, at) => !stands.has(at))))
  }
  let afterFirst = 0
  let regressions = 0
  const hasBranches = declared(plan).length > 0
  for (let k = 1; k <= MAX_WAVES; k++) {
    const fwLabel = k === 1 ? 'fix-wave' : `fix-wave-${k}`
    const rvLabel = k === 1 ? 'fix-wave-review' : `fix-wave-review-${k}`
    log(`final review: ${waveFindings.length} blocking findings, fix wave ${k}`)
    fixWaves++
    const orphan = waveFindings.some(f => f.relation === 'narrowing' && fileOf(f) && !finalFindings.some(g => fileOf(g) === fileOf(f)))
    const unplaced = orphan || waveFindings.some(f => !fileOf(f))
    const resumedHere = !!RESUMED && (k === 1 || waveFindings.some(f => fileOf(f) === RESUMED.file))
    if (resumedHere && !turning.includes(RESUMED.file)) turning = turning.concat(RESUMED.file)
    const decided = file => (resumedHere && file === RESUMED.file ? DECIDED : '')
    const stillOpen = k === 1 ? [] : finalFindings.filter(f => !turning.includes(fileOf(f)) && (unplaced || !fileOf(f) || waveFindings.some(w => fileOf(w) === fileOf(f))))
    const settled = finalFindings.filter(f => !turning.includes(fileOf(f))).length - stillOpen.length
    const classWide = k === 3 && waveFindings.some(f => !turning.includes(fileOf(f)))
    const fw = await call(`${CTX}\n${PLAN_REF} Fix these final-review findings, each real defect with a regression test, then commit: ${JSON.stringify(waveFindings)}.${k === 1 && fromStop.length ? ` The last ${fromStop.length} were left open by an earlier run's fix waves and may repeat the ones before them: check each against the current head, and explain one that no longer holds in notes; when you commit nothing, return commit equal to start_head.` : ''}${k === 1 ? CAP_BINDING : ''}${k >= 2 && (stillOpen.length || !orphan) ? ` They ${regressions ? 'follow the fix of' : 'narrow'} ${stillOpen.length ? 'these' : 'the'} first-round findings${regressions ? ' (any not marked narrowing is a defect in a file the previous fix wave changed)' : ''}${stillOpen.length ? `: ${JSON.stringify(stillOpen)}.${settled ? ` The other ${settled} ${settled === 1 ? 'is' : 'are'} settled.` : ''}` : '; none of those is still open.'}` : ''}${turning.map(file => ` ${file} has now been judged more than once in the same place: the fix of one finding drew the next.${decided(file)} Its history, oldest first: ${JSON.stringify(historyOf(file).slice(-ROUNDS_MAX))}. Read each range (git -C ${W} diff <range> -- ${file}), then ${decided(file) ? FOLLOW : 'change the approach or rebut the finding with evidence in notes'}; do not move the same lines back.`).join('')}${classWide ? ` Fix the class of defect: enumerate every path of the same kind as each reported one and close them all, not only the reported instance.${turning.length ? ` Not in ${turning.join(' or ')}: fix only what is reported there.` : ''}` : ''} If a finding is wrong, explain with evidence in notes. Change only what ${classWide ? 'closing that class needs, its' : 'fixing these findings needs, their'} regression tests included. ${OWN_TESTS} ${COMMIT_SCOPE} ${hasBranches ? IMPL_RETURN_AT(W) : IMPL_RETURN} Also return changed_files: the output lines of ${CHANGED_CMD('<start_head>..<commit>')}, run alone after your last commit.${hasBranches ? ` A finding on a declared branch is fixed in that branch's worktree and pushed with its push form. Return branch_heads: one {name, head} per declared branch (${declared(plan).map(b => b.name).join(', ')}), head being git -C <its worktree> rev-parse HEAD after your last commit.` : ''}\n${RULES}`, { label: fwLabel, phase: 'Final review', agentType: 'implementer', model: 'sonnet', schema: withChanged(hasBranches ? FIX_WAVE_IMPL : IMPL) })
    // A stop after a review verdict keeps the findings still open, a wave that answered and failed included: the next
    // round re-checks each against the head. An answered failed wave left no oscillating marker, so that goes.
    if (fw) { oscPending = false; capPending = false; capMark = null }
    const spent = details => {
      keep(waveFindings)
      // A wave after the first ran on the findings its run's own re-review raised, not on the ones the marker was kept
      // for.
      if (fw || k > 1) osc = null
      if (fw && carried.length) log(`fix-wave: ${carried.length} open finding(s) kept in cont after a wave that failed`)
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
    // The head the last review read: a wave's re-review reads only start_head..commit, so it may advance the reviewed
    // head only from there. A wave that started elsewhere leaves a gap, and the reviewed head stays below it: the next
    // wave starts at that wave's commit, never at the reviewed head.
    const waveBase = reviewed ? reviewed.head : null
    tip = fw.commit
    const idle = k === 1 && fromStop.length > 0 && sameSha(fw.commit, fw.start_head) && !collected.length
    if (!idle) carried = []
    const rv = await readReview(`${CTX}\nRe-review these findings against ${idle ? `the current head of ${W}${hasBranches ? ` and of each declared branch's worktree (${declared(plan).map(b => `${b.name} in ${b.worktree}`).join(', ')})` : ''} (the fix wave committed nothing, so there is no diff to read). Nothing changed since these were raised, so each finding stands unless the code at the head shows it does not hold. The notes are the implementer's claims: check each against the code and never clear a finding on the notes alone` : `the fix (${span(fw)}${collected.length ? ` and ${collected.join(' and ')}` : ''})`}; notes: ${fw.notes}. Findings: ${JSON.stringify(waveFindings)}.${k === 1 && fromStop.length && !idle ? ` The last ${fromStop.length} were left open by an earlier run and may repeat the ones before them: check each against the head, not only the diff.` : ''}${k === 1 && CAP_BINDING ? `${CAP_BINDING} Report no finding that only disputes it.` : ''}${resumedHere ? `${DECIDED ? `${DECIDED} Report no finding that only disputes it.` : ''} ${RESUMED.file} was judged more than once in the same place before this fix; its history, oldest first: ${JSON.stringify(historyOf(RESUMED.file).slice(-ROUNDS_MAX))}.` : ''} ${CRITICAL_MEANS}${SCOPED ? ` ${SCOPED_BLOCKS} ${COMMIT_ASK(fw.commit)}` : ''} Report any still unresolved and any new Important or Critical defect, setting relation on each finding you still report: narrowing when it is the same kind of defect as one above, reached on another path, input or call site; else new. Unsure is new.${idle ? '' : ` Also return changed_files: the output lines of ${CHANGED_CMD(`${fw.start_head}..${fw.commit}`)}, run alone.`}`, { label: rvLabel, phase: 'Final review', agentType: 'reviewer', schema: withChanged(SCOPED ? withItems(FINDINGS, SCOPED_ITEM) : FINAL_FINDINGS) })
    if (!rv) {
      keep(waveFindings)
      if (!idle) osc = null
      return stop('fix-wave-review', { rv, fix_waves: fixWaves })
    }
    carried = []
    if (waveBase === null || sameSha(fw.start_head, waveBase)) markReviewed(isCommit(tip) ? tip : null)
    else {
      gapSeen = true
      log(`fix-wave-review: fix wave ${k} reports it started at ${fw.start_head}, not at ${waveBase}: the commits between were not re-reviewed, so the reviewed head stays`)
    }
    const next = SCOPED ? await rereviewed(rv, waveFindings) : blockingOf(rv)
    if (!next.length) break
    const inFix = changedBy(fw).filter(p => changedBy(rv).includes(p))
    const fresh = next.filter(f => f.relation !== 'narrowing')
    const narrow = fresh.every(f => fileOf(f) && inFix.includes(fileOf(f)))
    fixes.push({ notes: String(fw.notes || ''), range: `${fw.start_head}..${fw.commit}`, files: changedBy(fw) })
    rounds.push(next)
    turning = [...new Set(fresh.map(fileOf).filter(p => p && inFix.includes(p) && waveFindings.some(w => fileOf(w) === p)))]
    for (const p of turning) fired[p] = (fired[p] || 0) + 1
    const twice = turning.find(p => fired[p] > 1)
    const oscillating = twice ? { file: clip(twice), rounds: roundsOf(historyOf(twice).concat({ round: historyOf(twice).filter(x => own(x, 'wave')).length, findings: onFile(next, twice) })) } : null
    // A wave that committed nothing earns no further wave: what its re-review still holds stops.
    const again = k === 1 ? narrow && !idle : k === 2 && narrow && next.every(f => f.severity === 'important') && next.length <= afterFirst
    if (!again || oscillating) {
      keep(next)
      osc = oscillating
      if (carried.length < next.length) log(`fix-wave-review: ${next.length - carried.length} of ${next.length} open finding(s) not carried in cont`)
      const diverging = divergingOf(carried)
      if (diverging) log(`fix-wave-review: the fix waves do not converge on ${diverging.file} after ${diverging.waves} waves`)
      if (oscillating) log(`fix-wave-review: fix waves ${k - 1} and ${k} each drew a new finding in ${oscillating.file}`)
      if (reviewRounds >= ROUND_CAP) {
        capMark = { rounds: reviewRounds, findings: carried.map(f => f.summary) }
        log(`fix-wave-review: the review round cap (${ROUND_CAP} rounds) is reached with ${carried.length} finding(s) open`)
      }
      return stop('fix-wave-review', { rv, fix_waves: fixWaves, ...(diverging ? { diverging } : {}), ...(oscillating ? { oscillating } : {}), ...(capMark ? { round_cap: capMark } : {}) })
    }
    if (k === 1) afterFirst = next.length
    regressions = fresh.length
    if (fresh.length) log(`fix-wave-review: ${fresh.length} finding(s) not marked narrowing are in files fix wave ${k} changed; they get the next wave`)
    waveFindings = next
  }
} else carried = []
if (present(tip) && !gapSeen) finalReviewed = { head: tip, ...branchSnap(), ...(sizedWhole ? { whole: true } : {}) }
}
}

if (pending.length) {
  const again = pending
  pending = []
  await fileFollowUps(again)
  if (pending.length) return stop('final-review', { details: clip(`${pending.length} follow-up issue(s) for findings that do not block were not confirmed filed: ${pending.map(f => f.summary).join('; ')}`) })
}

// ---------------- Verify ----------------
phase('Verify')
const VERIFY = {
  type: 'object',
  properties: { head: FULL_SHA, clean: { type: 'boolean' }, results: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, status: { type: 'string', enum: ['pass', 'fail', 'skipped'] }, summary: { type: 'string' }, outside_diff: { type: 'boolean' }, no_slot: { type: 'boolean' } }, required: ['id', 'status', 'summary'] } }, pictures: { type: 'array', items: { type: 'object', properties: { kind: { type: 'string', enum: ['before', 'after'] }, path: { type: 'string' } }, required: ['kind', 'path'] } } },
  required: ['head', 'clean', 'results'],
}
// The before and after pictures a verification command wrote, kept when well formed.
const picturesOf = v => (v && Array.isArray(v.pictures) ? v.pictures.filter(p => isEntry(p) && (p.kind === 'before' || p.kind === 'after') && typeof p.path === 'string' && p.path.trim()).map(p => ({ kind: p.kind, path: p.path })) : [])
const SLOT_WAIT_SECONDS = 600
const SLOT_ATTEMPTS = 12
const slotted = e => ({ ...e, argv: ['verify-slot', 'run', '--wait-limit', String(SLOT_WAIT_SECONDS), ...(LANE === 'live' ? ['--live'] : []), '--', ...e.argv] })
const verifyBodyFor = entries => `Run the project's declared verification once on the worktree head, in the foreground, each command with a Bash timeout of up to 60 minutes: ${JSON.stringify(entries.map(slotted))}. Run each argv with <worktree>/<its cwd> as working directory. Each argv runs its declared command inside one of the host's verify slots: verify-slot run holds the slot while the command runs and gives it back when it ends. An attempt that prints verify-slot: no verify slot came free within ${SLOT_WAIT_SECONDS}s; nothing ran and exits 75 ran nothing and does not count as a run of that command: run the same argv again, up to ${SLOT_ATTEMPTS} attempts in all, and after the last return that id as fail with the summary no verify slot came free in ${SLOT_ATTEMPTS} attempts and no_slot: true (no_slot is true on that result only, never on a command that ran). Every other exit is the command's own result. If an entry has when_changed globs and none of the files changed (git -C ${W} diff --no-renames --name-only ${RANGE}, so a rename lists both paths) match, mark it skipped with its skip_reason. Return head (git -C ${W} rev-parse HEAD, the full sha), clean (git -C ${W} status --porcelain is empty, checked before and after the runs) and one result per id; for failures, summarize the failing tests or errors precisely. On each failure also return outside_diff: true only when no failing test file and no erroring file is in that git diff --name-only list, else false. When a command's output names image files it wrote as before or after pictures of the change, return them as pictures, one {kind: before or after, path: its absolute path} each; otherwise return no pictures. Do not change any file.
${RULES}`
const noSlot = v => !!v && Array.isArray(v.results) && v.results.some(r => isEntry(r) && r.status === 'fail' && r.no_slot === true)
const verifyBody = verifyBodyFor(LOCAL)
const verifyPrompt = `${CTX}\n${verifyBody}`
// The first verification also renews the claim; the reruns do not.
const verifyFirst = `${CTX}\n${RENEW_FIRST}\n${verifyBody}`
// Every declared id needs exactly one result; skipped only where the contract gives when_changed globs; and a clean
// tree.
const verifyProblems = v => {
  if (!v) return [{ id: '?', summary: 'verification returned nothing' }]
  const out = v.results.filter(r => r.status === 'fail')
  for (const e of LOCAL) {
    const rs = v.results.filter(r => r.id === e.id)
    if (rs.length !== 1) out.push({ id: e.id, summary: `expected exactly one result, got ${rs.length}` })
    else if (rs[0].status === 'skipped' && !(e.when_changed && e.when_changed.length)) out.push({ id: e.id, summary: 'skipped without when_changed globs' })
  }
  if (!v.clean) out.push({ id: '?', summary: 'the worktree has uncommitted changes, so the verified tree is not the pushed head' })
  return out
}
// `git diff -b --ignore-blank-lines` and the extension allow-list are a prefilter only. Carrying passes forward also
// needs the reviewer's attestation, because whitespace inside a literal can change behaviour.
const WS_INSENSITIVE = /\.(c|cc|cpp|cxx|h|hh|hpp|cs|css|scss|less|dart|go|java|js|jsx|mjs|cjs|ts|tsx|mts|cts|json|kt|kts|rs|scala|swift|php|html|xml|vue|svelte|sql|proto)$/i
const WS_CHECK = { type: 'object', properties: { whitespace_exit: { type: 'integer' }, changed_paths: STRS }, required: ['whitespace_exit', 'changed_paths'] }
const WS_REVIEW = { ...FINDINGS, properties: { ...FINDINGS.properties, whitespace_insignificant: { type: 'boolean' }, whitespace_evidence: { type: 'string' } }, required: [...FINDINGS.required, 'whitespace_insignificant', 'whitespace_evidence'] }
const wsOnly = c => !!c && c.whitespace_exit === 0 && Array.isArray(c.changed_paths) && c.changed_paths.length > 0 && c.changed_paths.every(p => typeof p === 'string' && WS_INSENSITIVE.test(p.trim()))
const attested = fr => !!fr && fr.whitespace_insignificant === true && typeof fr.whitespace_evidence === 'string' && fr.whitespace_evidence.trim().length > 0
const rerunIds = (v, fix) => {
  if (!v || !v.clean || !sameSha(v.head, fix.start_head)) return null
  if (!verifyProblems(v).every(p => p.status === 'fail' && LOCAL_IDS.includes(p.id))) return null
  const statusOf = id => { const rs = v.results.filter(r => r.id === id); return rs.length === 1 ? rs[0].status : null }
  if (!LOCAL_IDS.some(id => statusOf(id) === 'pass')) return null
  return LOCAL_IDS.filter(id => statusOf(id) !== 'pass')
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
// A failure the clerk places wholly outside the branch's changed files is rerun once, the failed ids only, before any
// fix step. The rerun is each failed id's whole command, never a selection of its tests: a test the branch made
// order-dependent passes alone. A pass there keeps the first failure as flaky; one that fails again stays the first
// failure. A reply counts only at the same clean head.
const flakySeen = []
let rerunFailed = false
const noteFlaky = rs => { for (const r of Array.isArray(rs) ? rs : []) if (isEntry(r) && present(r.flaky) && !flakySeen.some(f => f.id === r.id && f.summary === r.flaky)) flakySeen.push({ id: r.id, summary: r.flaky }) }
const rerunOnce = async (v, n) => {
  rerunFailed = false
  if (!v || !v.clean || !Array.isArray(v.results) || noSlot(v)) return v
  const fails = verifyProblems(v)
  if (!fails.length || !fails.every(p => p.status === 'fail' && p.outside_diff === true && LOCAL_IDS.includes(p.id))) return v
  const ids = fails.map(p => p.id)
  log(`verify: ${ids.join(', ')} failed outside the branch's changed files; one rerun before any fix`)
  const again = await call(`${CTX}\nThe verification at ${v.head} failed, outside the files this branch changed: ${JSON.stringify(fails.map(p => ({ id: p.id, summary: p.summary })))}. Rerun each failed command below once, whole and exactly as its argv below is written, and never a second time once it has run, whatever its outcome; an attempt that exits 75 with the no-slot line ran nothing, so it is not that rerun and is retried as below.\n${verifyBodyFor(LOCAL.filter(e => ids.includes(e.id)))}`, { label: `verify-rerun-${n}`, phase: 'Verify', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: VERIFY })
  // A rerun that never started is not a reproduced failure: the verification stops on it, with no fix step.
  if (complete(again, VERIFY) && noSlot(again)) return { ...v, results: v.results.map(r => again.results.find(a => a.id === r.id && a.status === 'fail' && a.no_slot === true) || r) }
  if (!complete(again, VERIFY) || !again.clean || !Array.isArray(again.results) || !sameSha(again.head, v.head)) return v
  const passed = id => { const rs = again.results.filter(r => r.id === id); return rs.length === 1 && rs[0].status === 'pass' ? rs[0] : null }
  rerunFailed = ids.some(id => !passed(id))
  const results = v.results.map(r => (ids.includes(r.id) && passed(r.id) ? { id: r.id, status: 'pass', summary: passed(r.id).summary, flaky: r.summary } : r))
  for (const r of results) if (ids.includes(r.id) && present(r.flaky)) log(`verify: flaky, ${r.id} failed and passed on the one rerun: ${r.flaky}`)
  noteFlaky(results)
  return { ...v, results }
}
const FIX_OR_UNRELATED = { ...IMPL, properties: { ...IMPL.properties, outside_diff: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, why: { type: 'string' } }, required: ['file', 'why'] } }, unrelated: { type: 'object', properties: { test: { type: 'string' }, evidence: { type: 'string' } }, required: ['test', 'evidence'] } } }
let verify = null
const lookStop = (pr, sha) => {
  lookAt = { pr, head: sha }
  // A fix answer stops here before its verify has run: the cont's own verified record stays and speaks for the stop.
  if (verify) verified = { head: verify.head, results: verify.results, contract: VERIFY_CONTRACT, ...branchSnap(), ...(picturesOf(verify).length ? { pictures: picturesOf(verify) } : {}) }
  const shown = picturesOf(verify || verified)
  return { ...stop('awaiting-look', { issue: ISSUE, pr, head: sha, covers: COVERS, ...(shown.length ? { pictures: shown } : {}), ...(flakySeen.length ? { flaky: flakySeen } : {}), ...(outsideFixes.length ? { outside_fixes: outsideFixes } : {}), ways: LOOK_WAYS }), reason: lookWhy ? `${lookWhy}; ${LOOK_REASON}` : LOOK_REASON }
}
// The minutes a checks poll waits for the first check to be reported on a head (gh pr checks --watch returns at once
// while none is, so quick pending answers would spend the pending waits before the runs register); TRAIN_NO_CHECKS_MIN
// in deliver-batch.js, and the wait sentence is the same text there.
const NO_CHECKS_MIN = 5
// The pending polls a wait spends before it stops at checks-pending: the landing's and the look's alike.
const PENDING_WAITS = 3
const LOOK_CHECKS = { type: 'object', properties: { state: { type: 'string', enum: ['passed', 'failed', 'pending'] }, head: FULL_SHA, behind: { type: 'boolean' }, required: STRS, passed: STRS, failing: STRS, pending: STRS, details: { type: 'string' } }, required: ['state', 'head', 'behind'] }
// The look's own wait, never CHECKS_WAIT: it pushes nothing (a head another writer pushed is read as it is), answers
// from one read of the pull request made after the watch, and reports the base's ancestry of that head after that read.
const LOOK_CHECKS_WAIT = (pr, sha) => `for the checks of PR #${pr} at the head ${sha}, changing nothing. 1. Wait once with ${UNSET}gh pr checks ${pr} --repo ${SLUG} --watch (Bash timeout up to 60 minutes): that is this poll's one deadline, so never run it a second time here, whether it returned early, returned with a check still pending or timed out; this program polls again. Its list can be partial, so its output is never the answer. While no check is reported on the pull request at all, do not answer yet: read ${UNSET}gh pr checks ${pr} --repo ${SLUG} --json name,bucket,link about once a minute, running alone timeout 60 tail -f /dev/null between two reads (this step's own wait, which ends by itself with exit 124), and answer pending only when none is reported ${NO_CHECKS_MIN} minutes after your first read. 2. Then read the pull request once: ${UNSET}gh pr view ${pr} --repo ${SLUG} --json headRefOid,statusCheckRollup. head is its headRefOid (the full sha), even when it is not ${sha}. Its rollup names no app, so read the app of each check run from the check runs of that same head, once: ${UNSET}gh api repos/${SLUG}/commits/<its headRefOid>/check-runs --paginate (each run's name, status, conclusion, started_at and app.id). Answer from these two reads alone and read nothing again. 3. Collect the required checks from both sources and never one in place of the other: the required_status_checks rules of ${UNSET}gh api repos/${SLUG}/rules/branches/${INT} (each with its integration_id when it names one) and the required_status_checks checks of classic branch protection, ${UNSET}gh api repos/${SLUG}/branches/${INT}/protection (each with its app_id when it names one). Return their union as required, always, even as an empty list (an empty list only when neither source lists any; a reply with no required is read as pending). 4. Classify from the reads of step 2: the check runs from the check-runs read (a run's app is its app.id), the commit statuses from the rollup (a status names no app, so it counts only for a required name that names none). Take the newest run (the latest started_at) of each pair of check name and app. A required check is judged by its runs of the app its rule or protection entry names (any app when it names none): a newer run of another app never replaces that app's run, so a green run of another app never hides a failed run of the required app and never counts as the required check passing. A check run whose status is not completed (COMPLETED in the rollup), or a status whose state is PENDING or EXPECTED, is pending; a check run whose conclusion is success, neutral or skipped (any case), or a status whose state is SUCCESS, has passed; any other conclusion, or a status whose state is FAILURE or ERROR, has failed. 5. Then run git -C ${W} fetch origin and return behind true when git -C ${W} merge-base --is-ancestor origin/${INT} <that headRefOid> fails (the base moved past the head, during the wait or before it), else false. Return state passed only when that read shows no check pending, failed or cancelled, with required and passed (every name passing at that head, of the required app for a required name); failed when any check failed, required or not, with failing (every failed name) and details (for each failed check, the last 60 lines of its failed log: ${UNSET}gh run view <run id> --repo ${SLUG} --log-failed); otherwise pending, with pending (the names still running) and the observed state when the wait ran out.`
const namesOf = v => (Array.isArray(v) ? v.filter(x => typeof x === 'string' && x !== '') : [])
// The required names no passing run covers (a passed reply that leaves one out proves nothing for it).
const missingOf = ck => namesOf(ck.required).filter(x => !namesOf(ck.passed).includes(x))
// A required list the reply omits is a list nobody read: a required build that has not reported is invisible in it, so
// a passed reply without one proves nothing.
const unproven = ck => !Array.isArray(ck.required) || missingOf(ck).length > 0
const lookRead = ck => {
  const failing = namesOf(ck.failing)
  const pending = [...new Set([...namesOf(ck.pending), ...missingOf(ck)])]
  const state = ck.state === 'failed' || failing.length ? 'failed' : ck.state !== 'passed' || pending.length || unproven(ck) || !namesOf(ck.passed).length ? 'pending' : 'passed'
  return { state, failing, pending }
}
let lookPolls = 0
let lookWaits = 0
const lookPoll = async (pr, sha, stale) => {
  const label = `look-checks-${++lookPolls}`
  const ck = await recall(() => call(`${CTX}
${RENEW_FIRST}
Then wait ${LOOK_CHECKS_WAIT(pr, sha)}${stale ? ` ${STALE_RERUN(UNSET, SLUG)}` : ''}
Issue #${ISSUE} waits for the owner's look at the head ${sha} before it merges: run no lock command, push nothing and merge nothing.
${RULES}`, { label, phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: withRenew(stale ? WITH_STALE(LOOK_CHECKS) : LOOK_CHECKS) }), r => r.renew)
  const lost = ck ? renewed(ck.renew, label) : null
  const row = lost || (!complete(ck, LOOK_CHECKS) ? stop('checks', { pr, checks: null }) : !sameSha(ck.head, sha) ? stop('head-moved', { pr, expected: sha, head: ck.head }) : null)
  return { ck, row }
}
const lookWaitStop = async (pr, sha) => {
  for (;;) {
    const { ck, row } = await lookPoll(pr, sha, false)
    if (row) return row
    const rd = lookRead(ck)
    if (rd.state === 'failed') return stop('checks', { pr, failing: rd.failing, checks: ck })
    if (rd.state === 'pending') {
      if (++lookWaits >= PENDING_WAITS) return stop('checks-pending', { pr, pending: rd.pending, checks: ck })
      continue
    }
    return lookStop(pr, fuller(sha, ck.head))
  }
}
const LOOK_HEAD_SCHEMA = { type: 'object', properties: { state: { type: 'string' }, head: { type: 'string' } }, required: ['state', 'head'] }
const LOOK_VERIFY = { ...VERIFY, properties: { ...VERIFY.properties, merge_only: { type: 'boolean' }, ahead: { type: 'boolean' }, untouched: { type: 'boolean' } }, required: [...VERIFY.required, 'merge_only', 'ahead'] }
const LOOK_POST_SCHEMA = { type: 'object', properties: { verdict: { type: 'string' }, comment_id: { type: 'integer' }, detail: { type: 'string' } }, required: ['verdict'] }
// The owner's fix answer approves the head it was given for with one fix. The approval is recorded before the fix, only
// while the pull request is open and its head is both the head the owner saw and the head the awaiting-look stop left;
// anything else posts nothing and stops at awaiting-look with the head just read.
const FIX_WORDS_FILE = `${setup.plan_dir}/look-fix-words.txt`
// The clerk has no Write tool, so the program encodes the owner's words (UTF-8, then base64: only A-Z a-z 0-9 + / =)
// and the clerk decodes them into the file with one Bash command, byte for byte whatever quotes, dollar signs,
// backticks or newlines they hold.
const B64_DIGITS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
const base64Utf8 = text => {
  const escaped = encodeURIComponent(text)
  const bytes = []
  for (let i = 0; i < escaped.length; i++) {
    if (escaped[i] === '%') { bytes.push(parseInt(escaped.slice(i + 1, i + 3), 16)); i += 2 } else bytes.push(escaped.charCodeAt(i))
  }
  let out = ''
  for (let i = 0; i < bytes.length; i += 3) {
    const n = (bytes[i] << 16) | ((bytes[i + 1] || 0) << 8) | (bytes[i + 2] || 0)
    out += B64_DIGITS[(n >> 18) & 63] + B64_DIGITS[(n >> 12) & 63] + (i + 1 < bytes.length ? B64_DIGITS[(n >> 6) & 63] : '=') + (i + 2 < bytes.length ? B64_DIGITS[n & 63] : '=')
  }
  return out
}
if (!LOOK_READ && LOOK_ANSWER && LOOK_ANSWER.answer === 'fix') return LOOK_UNREAD()
if (LANE === 'live' && LOOK_ANSWER && (LOOK_ANSWER.answer === 'changes' || LOOK_ANSWER.answer === 'fix')) return liveBound('the owner asked for a change at the look, and a fix would be a second implementer')
if (MARKED && LOOK_ANSWER && LOOK_ANSWER.answer === 'fix') {
  const hd = await recall(() => call(`${CTX}
${RENEW_FIRST}
Then read the head of PR #${lookAt.pr}, changing nothing: run ${UNSET}gh pr view ${lookAt.pr} --repo ${SLUG} --json state,headRefOid and return state and head (headRefOid, the full sha). Run nothing else.
${RULES}`, { label: 'look-head', phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: withRenew(LOOK_HEAD_SCHEMA) }), r => r.renew)
  if (!hd) return stop('look-approve', { result: null })
  const lostLook = renewed(hd.renew, 'look-approve')
  if (lostLook) return lostLook
  if (!complete(hd, LOOK_HEAD_SCHEMA) || !SHA_RE.test(hd.head)) return stop('look-approve', { result: hd })
  if (hd.state !== 'OPEN') return stop('look-approve', { details: `PR #${lookAt.pr} is ${hd.state}, not open, so the approval of ${LOOK_ANSWER.head} was not recorded` })
  if (!sameSha(hd.head, LOOK_ANSWER.head) || !sameSha(LOOK_ANSWER.head, lookAt.head)) return lookWaitStop(lookAt.pr, hd.head)
  const posted = await call(`${CTX}
Record the owner's look approval of issue #${ISSUE} of ${SLUG} with one fix. First write the owner's words as the whole content of ${FIX_WORDS_FILE}: run alone and exactly: printf %s '${base64Utf8(LOOK_ANSWER.words)}' | base64 -d > ${shq(FIX_WORDS_FILE)}
The base64 text decodes to the owner's words byte for byte; type it as printed and change nothing. If that command exits non-zero, run nothing else and return verdict write-failed with its error as detail: a half-written words file is never posted. Otherwise run alone and exactly: look-approval post --repo ${SLUG} --issue ${ISSUE} --pr ${lookAt.pr} --head ${LOOK_ANSWER.head} --answer fix --message ${LOOK_ANSWER.message || String(setup.holder).split('/').pop()} --words-file ${shq(FIX_WORDS_FILE)}
It prints one JSON line. Return its verdict, comment_id and any detail. Run nothing else.
${RULES}`, { label: 'look-post', phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: LOOK_POST_SCHEMA })
  if (!posted || posted.verdict !== 'posted') return stop('look-approve', { result: posted })
}
// The owner looked and asked for changes (or approved with one fix): one fix round on their words, then a fresh verify;
// a review that finds a defect stops.
if (LOOK_ANSWER && (LOOK_ANSWER.answer === 'changes' || LOOK_ANSWER.answer === 'fix')) {
  const asked = [{ severity: 'important', source: 'owner', summary: LOOK_ANSWER.words, failing_input: `the owner's look at head ${lookAt ? lookAt.head : setup.head}` }]
  LOOK_STOP = MARKED
  // The fix edits and commits on the branch, so the claim is renewed first: a holder that lost it stops before any
  // edit.
  const lostClaim = await renew('look-fix', 'Verify')
  if (lostClaim) return lostClaim
  const lookFix = await call(`${CTX}\n${PLAN_REF} The owner looked at the pull request head and asked for changes; the owner's words are the one finding of this fix round: ${JSON.stringify(asked)}. Fix it in the worktree, with a regression test for each real defect, then commit. ${FIX_TESTS} ${COMMIT_SCOPE} ${IMPL_RETURN}\n${RULES}`, { label: 'look-fix', phase: 'Verify', agentType: 'implementer', model: 'sonnet', schema: IMPL })
  if (noteUntested('look-fix', lookFix, setup.head)) return stop('look-fix', { fix: lookFix, details: UNTESTED })
  if (!implDone(lookFix) || sameSha(lookFix.commit, lookFix.start_head)) return stop('look-fix', { fix: lookFix })
  const lookReview = await readReview(`${CTX}\nRe-review only this owner finding against the fix: ${span(lookFix)}; the implementer's notes: ${lookFix.notes}. Findings: ${JSON.stringify(asked)}. Report the finding if it is still unresolved and any new Important or Critical defect the fix introduced.`, { label: 'look-fix-review', phase: 'Verify', agentType: 'reviewer', schema: FINDINGS })
  if (!lookReview || findingsOf(lookReview).length) return stop('look-fix-review', { review: lookReview })
  VERIFY_CACHED = false
  verified = null
  if (MARKED && LOOK_ANSWER.answer === 'fix') {
    approvedHead = LOOK_ANSWER.head
    ownerHead = approvedHead
    lookAt = approvedLook(lookAt.pr, approvedHead)
    LOOK_STOP = false
  }
}
verify = VERIFY_CACHED ? { head: verified.head, clean: true, results: verified.results, ...(picturesOf(verified).length ? { pictures: picturesOf(verified) } : {}) } : null
if (VERIFY_CACHED) noteFlaky(verified.results)
if (!VERIFY_CACHED) {
verify = await recall(() => call(verifyFirst, { label: 'verify', phase: 'Verify', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: withRenew(VERIFY) }), r => r.renew)
if (verify) {
  const lost = renewed(verify.renew, 'verify')
  if (lost) return lost
  if (!complete(verify, VERIFY)) verify = null
}
verify = await rerunOnce(verify, 1)
if (LANE === 'live' && verify) {
  if (!sameSha(verify.head, liveCommit())) return liveBound(`the verification read ${typeof verify.head === 'string' ? verify.head : 'no head'}, not the delivered commit ${liveCommit()}`)
  const failed = verifyProblems(verify)
  if (failed.length) return liveBound(`the verification failed at ${liveCommit()} (${failed.map(p => p.id).join(', ')}), and a fix would be a second implementer`, { verify })
}
let vRounds = 0
while (verify && !noSlot(verify) && verifyProblems(verify).length && vRounds < 2) {
  vRounds++
  const fix = await call(`${CTX}\n${PLAN_REF} The project's verification failed: ${JSON.stringify(verifyProblems(verify).map(p => ({ id: p.id, status: p.status, summary: p.summary })))}.${rerunFailed ? ' It failed again on the one rerun at the same head, so it is not flaky.' : ''} Find the cause in this branch's changes (git -C ${W} diff ${RANGE}), fix it with the smallest change, commit. Never weaken, skip or delete a test to make it pass. When what fails lies outside that diff, first establish with evidence why it fails here: this branch's change, or this delivery's environment (the worktree path, the branch name). Only with that cause shown may you edit a file outside the diff, and then return outside_diff: [{file, why}], one entry per such file with the cause. With no cause established (it fails without this branch${rerunFailed ? '' : ', or it is flaky'}), change and commit nothing and return status blocked with unrelated {test, evidence}, evidence being what you ran or read: establish it by reading, or by running the test, never by checking out another commit in the worktree. ${OWN_TESTS} ${COMMIT_SCOPE} ${IMPL_RETURN}\n${RULES}`, { label: `verify-fix-${vRounds}`, phase: 'Verify', agentType: 'implementer', model: 'sonnet', schema: FIX_OR_UNRELATED })
  // A failure for which the fix step can establish no cause here (the branch's change or the delivery's environment) is
  // not edited green: the delivery stops naming the test, and nothing ships. A fix outside the diff with a stated cause
  // goes on, flagged (outsideFixes).
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
  const fr = await readReview(`${CTX}\nReview this verification fix: ${span(fix)}; the failure it answers: ${JSON.stringify(verifyProblems(verify))}; notes: ${fix.notes}. Report Important or Critical defects only, above all a weakened, skipped or deleted test or check.${outside.length ? ` It edits files outside the branch's diff, each for a stated cause: ${JSON.stringify(outside)}; a cause the code or the failure does not bear out is an Important defect.` : ''}${asked ? wsAsk(ws) : ''}`, { label: `verify-fix-review-${vRounds}`, phase: 'Verify', agentType: 'reviewer', schema: asked ? WS_REVIEW : FINDINGS })
  if (!fr || findingsOf(fr).length) return stop('verify-fix-review', { review: fr })
  const rerun = asked && attested(fr) ? asked : null
  const next = await call(rerun ? `${CTX}\nA whitespace-only fix followed the verification at ${verify.head}; the declared ids not listed below passed there and are carried forward, so run only the listed ones.\n${verifyBodyFor(LOCAL.filter(e => rerun.includes(e.id)))}` : verifyPrompt, { label: `verify-${vRounds + 1}`, phase: 'Verify', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: VERIFY })
  if (rerun && next && !sameSha(next.head, fix.commit)) return stop('verify', { verify: next, problems: [{ id: '?', summary: `the narrowed verification ran at ${next.head}, not at the whitespace-only fix ${fix.commit}, so no result was carried` }] })
  verify = await rerunOnce(rerun && next && Array.isArray(next.results) ? carry(verify, next, rerun) : next, vRounds + 1)
}
}
if (verifyProblems(verify).length) return stop('verify', { verify, problems: verifyProblems(verify) })
const PICTURES = picturesOf(verify)
// A look read with neither verdict is not read as unmarked: nothing is pushed or landed until the marker is read.
if (!LOOK_READ) return LOOK_UNREAD()
if (untested) {
  const rt = await call(`${CTX}\n${PLAN_REF} The commits in git -C ${W} diff ${untested.start_head}..${verify.head} are a fix committed with no test command recorded; treat them as the commit you made. The program pushes this head to the open pull request next. ${PUSH_TESTS(PRE_COMMIT, 'report')}. Commit nothing: return status done with start_head and commit both ${verify.head} (git -C ${W} rev-parse HEAD), and clean true only when git -C ${W} status --porcelain prints nothing after the last test, else clean false.\n${RULES}`, { label: 'fix-retest', phase: 'Verify', agentType: 'implementer', model: 'sonnet', schema: RETEST })
  if (!implDone(rt) || !sameSha(rt.start_head, verify.head) || !sameSha(rt.commit, verify.head) || !tested(rt)) return stop(untested.stage, { fix: rt, details: UNTESTED })
  if (rt.clean !== true) return stop(untested.stage, { fix: rt, details: RETEST_DIRTY })
  untested = null
}
if (MODE === 'ready') {
  verified = { head: verify.head, results: verify.results, contract: VERIFY_CONTRACT, ...branchSnap(), ...(PICTURES.length ? { pictures: PICTURES } : {}) }
  return stop('ready', { head: verify.head, branch: setup.branch, worktree: W, verify: verify.results, ...(BEFORE_PR ? { verify_scope: 'before_pull_request' } : {}), look: { verdict: LOOK.verdict, covers: COVERS }, ...(flakySeen.length ? { flaky: flakySeen } : {}), ...(outsideFixes.length ? { outside_fixes: outsideFixes } : {}), tasks: taskLog, ...(reordered.length ? { reordered } : {}), acceptance: plan.acceptance, fix_waves: fixWaves })
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
const CHECKS_WAIT = pr => `for PR #${pr} to be mergeable. 1. git -C ${W} fetch origin; if the local branch is ahead of origin/${setup.branch}, push it. head is git -C ${W} rev-parse HEAD (full sha). 2. If origin/${INT} is not an ancestor of HEAD (git -C ${W} merge-base --is-ancestor origin/${INT} HEAD fails), return state behind at once. 3. Otherwise wait in this turn until every check on head has completed, required or not. List every check with gh pr checks ${pr} --repo ${SLUG} --json name,bucket,link (never --required) and wait with gh pr checks ${pr} --repo ${SLUG} --watch (Bash timeout up to 60 minutes; rerun while any is pending). It can return early and a list can be partial: never treat a partial list as green, and read the list again before you answer. Bucket pass has passed; fail or cancel has failed; pending is still running; skipping never started and is ignored. Report as required the required check names from gh api repos/${SLUG}/rules/branches/${INT} (its required_status_checks rules) and, whenever that reply lists no required status checks, from classic branch protection. Return required always, even as an empty list (an empty list only when neither lists any): a passed answer that leaves it out is not trusted. A head with no check reported at all is pending, never passed: runs can register minutes after a push. While no check is reported on head, do not answer yet: read the list again about once a minute, running alone timeout 60 tail -f /dev/null between two reads (this step's own wait, which ends by itself with exit 124), and answer pending only when none is reported ${NO_CHECKS_MIN} minutes after your first read of the list. Return passed only when no check on head is pending, failing or cancelled, with required and passed (every name passing at head; a passed answer naming none is read as pending). Return failed when any check failed, required or not, with failing (every failing or cancelled name) and details (for each failing check, the last 60 lines of its failed log: gh run view <run id> --repo ${SLUG} --log-failed). Return pending with pending (the names still running) only when the wait ran out and no check failed.`
const SYNC = { type: 'object', properties: { status: { type: 'string', enum: ['done', 'conflicted', 'blocked'] }, conflicted: { type: 'boolean' }, merge_commit: FULL_SHA, head: FULL_SHA, resolved_files: STRS, markers_checked: { type: 'boolean' }, tests: STRS, notes: { type: 'string' } }, required: ['status', 'conflicted', 'notes'] }
const LOCK_SCHEMA = {
  type: 'object',
  properties: { verdict: { type: 'string', enum: ['acquired', 'already_held', 'moved', 'held_by', 'lost_to', 'land-contended', 'error'] }, lock_sha: { type: 'string' }, pr: { type: 'integer' }, by: { type: 'string' }, detail: { type: 'string' }, waited_s: { type: 'integer' }, waited_on: { type: 'array', items: { type: 'integer' } }, position: { anyOf: [{ type: 'integer' }, { type: 'null' }] }, ahead: { type: 'array', items: { type: 'integer' } } },
  required: ['verdict'],
}
const LOCK_WAIT_LOG_S = 300
const logWait = (label, lock) => {
  if (!lock || !(lock.waited_s >= LOCK_WAIT_LOG_S)) return
  const on = Array.isArray(lock.waited_on) ? lock.waited_on : []
  log(`${label}: waited ${Math.round(lock.waited_s / 60)} min for the land lock of ${INT}${on.length ? ` behind PR ${on.map(p => `#${p}`).join(', ')}` : ''}`)
}
// A red check the branch itself caused is found and fixed outside the land lock, the same rules in deliver-batch.js.
// Before the lock is asked for, a pull request that already existed is read once (OWN_RED): a check that already failed
// at the head sends the delivery to its fix wave with no lock. Under the lock, the fix step of a red poll at a head no
// sync has changed releases the lock itself once it knows the fix needs a commit (FIX_OFF_LOCK); the fix, its tests and
// its review run outside it, and the next round takes the lock again, waiting. A failure with no cause in the code

// keeps the lock and reruns its jobs. One fix wave per delivery either way (checksFixes).

// A check that failed at a head behind its base counts in that read only while another landing holds the lock: the
// branch is brought up to date before the lock is asked for.
const OWN_RED = (wt, prRef, sha) => `Otherwise, and only when an open PR already existed and was reused (a PR this step opened has no finished check, so skip this read), read the checks of the pushed head once before any lock command: ${UNSET}gh pr view ${prRef} --repo ${SLUG} --json headRefOid,statusCheckRollup, one read, never a watch and never a wait. A head that was just pushed can still show the checks of the head before it, so the read counts only when its headRefOid is ${sha}. Only when it is and a check there has failed (count only the newest run of each check name, the one with the latest startedAt, so a failed attempt whose re-run passed does not count; a check run whose conclusion is FAILURE or TIMED_OUT, or a status whose state is FAILURE or ERROR; a cancelled check does not count), see whether origin/${INT} is an ancestor of HEAD (git -C ${wt} merge-base --is-ancestor origin/${INT} HEAD succeeds). When it is not, the head is behind its base and gets new checks once it is synced, so the failure counts only while another landing holds the lock and this one would wait: read the lock once, run alone and exactly: forge-claim land status --repo ${SLUG} --branch ${INT} --sha ${sha} (a Bash timeout of 20 minutes), and it counts only on the verdict held_by with a lock_sha other than ${sha}. When the failure counts, run no other lock command and wait for no check: return own_red with head (the headRefOid you read), failing (the name of every failed check), details (their links) and behind (true when the head is behind its base, else false), and lock null and checks null, because a later step fixes the branch before the lock is asked for, after it brought a head that is behind up to date. In every other case (another head, a head behind its base while no other landing holds the lock, no failed check, checks still running, none reported, or a read failed) return own_red null and go on.`
const OWN_RED_SCHEMA = { type: 'object', properties: { head: { type: 'string' }, failing: STRS, details: { type: 'string' }, behind: { type: 'boolean' } }, required: ['head', 'failing'] }
// The program checks the head itself: a reply that names another head, or none, diverts nothing.
const ownRed = (r, sha) => !!r && typeof r === 'object' && !Array.isArray(r) && sameSha(r.head, sha) && Array.isArray(r.failing) && r.failing.some(x => typeof x === 'string' && x !== '')
// The diagnosis is the one part of the fix that stays under the lock, so it is bounded: reading only, and a release
// when in doubt.
const FIX_OFF_LOCK = sha => `The landing lock of the branch ${INT} is held for this pull request at ${sha}, and other landings wait for it. So decide first, quickly and changing nothing, whether the fix needs a commit: read only the failed job log, the check details and the branch's diff, and run no build and no test before the release. When the cause is in this branch's changes, or you cannot tell, release the lock before you edit any file: run alone and exactly: forge-claim land release --repo ${SLUG} --branch ${INT} --sha ${sha}
released and not_held are both fine (give it a Bash timeout of 20 minutes). Return lock_released true once it answered either; the program takes the lock again after the review (that costs this landing one wait; holding the lock costs every waiter). Only when the failure clearly has no cause in the code (no commit is needed), keep the lock: run no forge-claim command and return lock_released false.`
const FIX_NO_LOCK = `The landing lock of the branch ${INT} is not held and was not asked for yet: run no forge-claim command.`
// The probe a landing runs before it asks for the land lock, the same text in deliver-batch.js. git merge-tree
// --write-tree (git 2.38 or later) merges in memory, touching neither the worktree nor the index, and its exit status
// alone says whether the merge is clean (0) or conflicts (1). It also exits 1, with nothing on stdout, when a ref is
// missing, so a conflict is exit 1 with the merged tree's id as the first line; the program checks that id itself.
// Anything else proves nothing and reads as not conflicted: the sync under the lock then finds the conflict.
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
// A passed reply that names no passing check is a head no check has reported on yet (runs register up to minutes after
// a push), so it is read as pending and counts against the pending waits. This program reads no required checks from
// the contract, and the contract cannot declare an empty list anyway, so the rule has no opt-out.
const noCheckYet = ck => ck.state === 'passed' && !(Array.isArray(ck.passed) ? ck.passed : []).some(x => typeof x === 'string' && x !== '')
const POLICY_REFUSAL = m => !!m && m.merged === false && m.behind !== true && /base branch policy/i.test(String(m.notes || ''))
let policyPolls = 0
const LAND_WAIT_RETRIES = 3
// Retries are spent only by a wait that made no progress: a wait that ended first in line, or at a better place than
// the one before, is made again for nothing. The ceiling bounds what progress alone cannot: waits of 100 to 200 minutes
// were normal with three ahead, so a wait is made again only when it can end within six hours, at the CLI's bound of 50
// minutes a call (LAND_WAIT_CALL_S).
const LAND_WAIT_MAX_S = 6 * 3600
const LAND_WAIT_CALL_S = 3000
// One ceiling per landing and one count of retries per run of waits: waitBudget() is made once for a landing, and each
// run of waits asks it for a function, which is asked with the lock reply of the wait that just ran out (null when the
// program asks for a first wait itself) and answers whether to wait again. A wait that ran out counts as a whole call
// at least, whatever its reply says it waited, so no reply can lift the ceiling.
const waitBudget = () => {
  let total = 0
  return () => {
    let spent = 0, place = null
    return lock => {
      const at = lock && Number.isInteger(lock.position) && lock.position >= 1 ? lock.position : null
      if (lock) total += Math.max(Number.isFinite(lock.waited_s) ? lock.waited_s : 0, LAND_WAIT_CALL_S)
      if (!(at === 1 || (at !== null && place !== null && at < place))) spent++
      place = at
      return spent <= LAND_WAIT_RETRIES && total + LAND_WAIT_CALL_S <= LAND_WAIT_MAX_S
    }
  }
}
let pendingWaits = 0
let mg = null
let mergeRefusals = 0
let raced = false
let contended = 0
// True after a rerun of failed jobs at an unchanged head, until the poll that follows it answered.
let reran = false
// The cross-host land lock of the integration branch: taken with --wait right after the PR opens, before any sync,
// moved with a one-shot acquire after every head change, re-checked once before the merge, released after the merge and
// on every stop. lockSha is the last sha this run owned or may own: set before the pr call, whose lock may be taken
// before its reply is lost.
let lockHeld = false
let lockSha = null
// The sha a move acquire may have left held when its answer was lost; cleared by a definitive answer.
let lockMaybe = null
// True from the release of the lock for a conflicted sync merge until the reviewed head takes it again. A merge that
// conflicts is aborted under the lock, the lock is released, and the resolution, its tests, its review and its fix wave
// run outside it. The next round pushes the accepted head and takes the lock again with --wait in its checks call; a
// stop in between holds no lock.
let lockOut = false
let lockFirst = false
// True while lockOut stands for a red check of the branch that is fixed outside the lock, not for a conflict.
let fixedOut = false
// True while lockOut stands for a branch that was only brought up to date before the lock was asked for.
let syncedOut = false
// The sync merges made under the lock; while there is none, a red poll shows the branch's own failure.
let lockSyncs = 0
let relocks = 0
const waits = waitBudget()
let retakes = 0
const HOLDING = ['acquired', 'already_held', 'moved']
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
// One bounded Ship fix wave: an implementer commits a fix on top of the current head (not pushed), then a fresh
// reviewer re-reviews it. The repair must start from the head the caller accepted (start_head), or the reviewer would
// miss an unreviewed commit beneath it. Returns { fix, ok: false } when the fix failed, started elsewhere or added no
// commit (unless rebuttal allows evidence and no commit), else { fix, review, moved }; with rerun, done at the
// unchanged head is a rerun of jobs that failed for no cause in the code. A committed fix with no test command recorded

// is refused before its review and push.
const shipFix = async ({ stage, label, reviewLabel, fixPrompt, reviewPrompt, rebuttal = false, rerun = false, schema = IMPL, committed = null }) => {
  // The live-fault lane has no second implementer: its caller stops, bound, before any fix or review.
  if (LANE === 'live') return { fix: null, ok: false, bound: true }
  const fix = await call(fixPrompt, { label, phase: 'Ship', agentType: 'implementer', model: 'sonnet', schema })
  if (noteUntested(stage, fix, expected)) return { fix, ok: false, details: UNTESTED }
  if (!implDone(fix) || !sameSha(fix.start_head, expected)) return { fix, ok: false }
  const moved = !sameSha(fix.commit, expected)
  if (!moved && rerun) return { fix, ok: true, rerun: true, moved }
  if (!moved && !(rebuttal && present(fix.notes))) return { fix, ok: false }
  if (moved && committed) await committed(fix)
  const review = await readReview(reviewPrompt(fix, moved), { label: reviewLabel, phase: 'Ship', agentType: 'reviewer', schema: FINDINGS })
  return { fix, review, moved, ok: true }
}
const prOpen = (reusePr = null) => reusePr !== null ? `Then reuse the open pull request #${reusePr} of this branch: the owner approved its head ${expected}, which is already pushed, so push nothing, open no pull request and edit none. Return pr (${reusePr}) and head (git -C ${W} rev-parse HEAD, the full sha).` : `Then open the pull request for this branch. Push the branch (git -C ${W} push origin ${setup.branch}). If an open PR with head ${setup.branch} already exists (a resumed delivery), reuse it; else open one against ${INT}. Title: a short summary of the issue. Body, plain prose, no single or double quotes, dollar signs, backticks or backslashes: sections Why, What changes, Acceptance (a table with one row per criterion: id, criterion, kind, and the test or command that shows it; criteria ${ACS}), Evidence (verification ${JSON.stringify(verify.results)}${BEFORE_PR ? `; ${PRE_PR_EVIDENCE}` : ''}${outsideFixes.length ? `; verification fixes outside the branch's diff, each with its cause: ${JSON.stringify(outsideFixes)}` : ''}; ${taskLog.length} tasks reviewed; ${LANE === 'direct' ? 'direct-lane review' : LANE === 'live' ? 'live-fault lane review: one reviewer, no plan' : 'final review ' + (chunked ? 'chunked' : 'whole')}${REVIEW_CODE ? ' plus the configured independent review' : ''}${LANE === 'live' && LIVE_REC ? `; the Evidence section also holds, on a line of its own, exactly: ${LIVE_LINE()}` : ''}), Merge danger; then the line ${closesLine} as the last line, with no attribution or generated-by line. Never attach or link the plan or the spec. Return pr (number) and head (full sha of the pushed head).`
const LOOK_STATUS_SCHEMA = { type: 'object', properties: { verdict: { type: 'string' }, kept_from: { type: ['string', 'null'] }, detail: { type: 'string' } }, required: ['verdict'] }
// A landing resync that moved a marked head past the owner's approved head. LOOK_CARRY_VERIFY adds merge_only to the
// verification reply; the carry command's JSON line is LOOK_CARRY_SCHEMA.
const LOOK_CARRY_VERIFY = { ...VERIFY, properties: { ...VERIFY.properties, merge_only: { type: 'boolean' }, untouched: { type: 'boolean' } }, required: [...VERIFY.required, 'merge_only'] }
const LOOK_REVERIFY = { ...VERIFY, properties: { ...VERIFY.properties, merge_only: { type: 'boolean' }, untouched: { type: 'boolean' } } }
const LOOK_CARRY_SCHEMA = { type: 'object', properties: { verdict: { type: 'string' }, from: { type: ['string', 'null'] }, reason: { type: ['string', 'null'] }, rule: { type: ['string', 'null'] }, comment_id: { type: ['integer', 'null'] }, detail: { type: 'string' } }, required: ['verdict'] }
// The reasons look-approval carry gives for a needed answer; any other reason is an unreadable reply.
const CARRY_REASONS = ['no-approval', 'source-differs', 'pictures-unreadable', 'pictures-missing', 'pictures-differ', 'not-merges', 'no-look-files', 'look-files-differ']
// The rules a carried reply may name; with no picture passed it must be look-files.
const CARRY_RULES = ['pictures', 'look-files']
const USABLE_PICTURE = /^\/[^\0\r\n]+$/
const CLEAN_MERGE = `a clean two-parent merge, meaning git -C ${W} merge-tree --write-tree <merge>^1 <merge>^2 exits 0 and prints the tree id that git -C ${W} rev-parse <merge>^{tree} gives (a conflict resolved by hand, or an octopus merge, gives a different tree; never judge this from git show --cc, which omits a hunk where the merge keeps one parent unchanged)`
const onlyMerges = (from, to) => `git -C ${W} rev-list --no-merges ${from}..${to} ^origin/${INT} prints nothing, and every merge in git -C ${W} rev-list --merges ${from}..${to} ^origin/${INT} is ${CLEAN_MERGE}`
// A sync that moved the head without touching any file of the pull request needs no new local verification: the
// reply says so with merge_only and untouched together, and the earlier results then carry to the new head, named
// by carried_from, and so do the pictures the earlier verification wrote: the owner still has them to look at.
const UNTOUCHED = (from, to) => `untouched is true only when merge_only is true and no path that git -C ${W} diff --no-renames --name-only ${from} ${to} prints is among the paths git -C ${W} diff --no-renames --name-only origin/${INT}...${to} prints (the pull request's files); else false. When untouched is true, run no verification command and return results [].`
const skipsVerify = (lv, at) => !!lv && lv.merge_only === true && lv.untouched === true && lv.clean === true && Array.isArray(lv.results) && lv.results.length === 0 && !!verify && Array.isArray(verify.results) && sameSha(verify.head, at)
const carriedTo = head => ({ head, clean: true, results: verify.results.map(r => ({ ...r, carried_from: r.carried_from || verify.head })), ...(picturesOf(verify).length ? { pictures: picturesOf(verify) } : {}) })
// A stop row, or null when the owner's approval of ownerHead carries to H (look-approval carry recorded the carry
// line). since is the head the worktree was last verified at, and how names what brought the PR to H. The verification
// of H always runs. outside is true when H was not made by this delivery: H is then recorded as verified only when it
// is clean merges of the integration branch past the owner's head, so a commit nobody here reviewed never reads as a
// reviewed one.
const carryLook = async (pr, H, since = ownerHead, how = 'the landing', outside = false) => {
  const S = ownerHead
  // The results carry from the head they were verified at, so the untouched diff starts there.
  const from = verify && SHA_RE.test(verify.head) ? verify.head : since
  // With the verified head not the owner's, the check reaches back to whichever of the two is earlier.
  const merges = sameSha(since, S) ? `merge_only is true only when git -C ${W} merge-base --is-ancestor ${S} ${H} succeeds, ${onlyMerges(S, H)}; else false.`
    : `merge_only is true only when git -C ${W} merge-base --is-ancestor ${S} ${H} succeeds and one of these holds: (a) git -C ${W} merge-base --is-ancestor ${since} ${S} succeeds (the verified head is at or before the owner's head, so the check reaches back to it), and ${onlyMerges(since, H)}; (b) otherwise, git -C ${W} merge-base --is-ancestor ${S} ${since} succeeds (the verified head is past the owner's head: the worktree already holds the merge, or ${S} is an earlier kept head), and ${onlyMerges(S, H)}; else false.`
  const lv = await call(`${CTX}
The owner approved head ${S} of PR #${pr}; ${how} brought it to ${H}. Run only git commands and the declared verification, in this order:
1. git -C ${W} fetch origin. When git -C ${W} rev-parse HEAD is not ${H} and git -C ${W} merge-base --is-ancestor HEAD ${H} succeeds, run git -C ${W} merge --ff-only ${H}; never any other merge, reset, checkout or push. When HEAD is then not ${H}, run nothing more and return head (git -C ${W} rev-parse HEAD), clean, results [] and merge_only false.
2. ${merges}
3. ${UNTOUCHED(from, H)} Otherwise, whatever merge_only is: ${verifyBody}`, { label: 'look-carry-verify', phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: LOOK_CARRY_VERIFY })
  // A worktree that could not be brought to H (a force-push replaced the head with one the worktree does not contain)
  // answers with its own head, merge_only false and no results: H was never verified, so the owner is asked for a look
  // at it.
  if (complete(lv, LOOK_CARRY_VERIFY) && SHA_RE.test(lv.head) && !sameSha(lv.head, H) && lv.merge_only === false && lv.results.length === 0) {
    lookWhy = `the approval of ${S} does not carry to ${H}: the worktree head ${lv.head} cannot be brought to it`
    return lookWaitStop(pr, H)
  }
  if (!complete(lv, LOOK_CARRY_VERIFY) || !SHA_RE.test(lv.head) || !sameSha(lv.head, H)) return stop('look-carry', { pr: pr, head: H, details: `the verification of ${H} returned no usable reply for it`, result: lv })
  const skipped = skipsVerify(lv, from)
  if (skipped) {
    log(`look-carry-verify: the sync to ${H} changes none of the pull request's files; the verification at ${verify.head} carries to it`)
    verify = carriedTo(fuller(H, lv.head))
  } else {
    if (verifyProblems(lv).length) return stop('look-carry', { pr: pr, head: H, problems: verifyProblems(lv) })
    if (!outside || lv.merge_only === true) verify = { head: fuller(H, lv.head), clean: true, results: lv.results, ...(picturesOf(lv).length ? { pictures: picturesOf(lv) } : {}) }
  }
  if (lv.merge_only !== true) {
    lookWhy = `the approval of ${S} does not carry to ${H}: it adds commits that are not clean merges of ${INT}`
    return lookWaitStop(pr, H)
  }
  const pics = skipped ? picturesOf(verify) : picturesOf(lv)
  if (pics.some(x => !USABLE_PICTURE.test(x.path))) {
    lookWhy = `the approval of ${S} does not carry to ${H}: the verification wrote no pictures it can compare`
    return lookWaitStop(pr, H)
  }
  const reply = await call(`${CTX}
Record whether the owner's look approval of issue #${ISSUE} of ${SLUG} carries from ${S} to the head ${H} of PR #${pr}. Run alone and exactly: look-approval carry --repo ${SLUG} --issue ${ISSUE} --pr ${pr} --from ${S} --head ${H}${pics.map(x => ` --${x.kind} ${shq(x.path)}`).join('')}
It prints one JSON line. Return its verdict, from, reason, rule, comment_id and any detail. Run nothing else.
${RULES}`, { label: 'look-carry', phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: LOOK_CARRY_SCHEMA })
  if (isEntry(reply) && reply.verdict === 'approved') {
    log(`look-carry: the owner approved ${H} itself; nothing to carry`)
    ownerHead = H
    return null
  }
  if (isEntry(reply) && reply.verdict === 'carried' && typeof reply.from === 'string' && SHA_RE.test(reply.from) && sameSha(reply.from, S) && Number.isInteger(reply.comment_id) && reply.comment_id > 0 && CARRY_RULES.includes(reply.rule) && (pics.length > 0 || reply.rule === 'look-files')) {
    log(`look-carry: the approval of ${S} carried to ${H} by the ${reply.rule} rule (comment ${reply.comment_id})`)
    return null
  }
  if (isEntry(reply) && reply.verdict === 'needed' && CARRY_REASONS.includes(reply.reason)) {
    lookWhy = `the approval of ${S} does not carry to ${H}: ${reply.reason}`
    return lookWaitStop(pr, H)
  }
  return stop('look-carry', { pr: pr, head: H, result: reply })
}
// The owner's approve answer is always validated here, never from a cached approval: the answer clears it, the pull
// request head is read, and the approval is read back (look-approval status; this program never posts one) for the head
// the owner saw. When that is not the verified head it is verified first (look-verify) and recorded only when it gained
// nothing but clean merges of the integration branch and its verification passes. A head that moved outside the
// delivery is verified and carried under the landing's carry rules. Anything else merges nothing and stops naming the

// approved head and the head found.
if (MARKED && LOOK_ANSWER && LOOK_ANSWER.answer === 'approve') {
  const A = LOOK_ANSWER.head
  const V0 = verify.head
  const P = lookAt.pr
  const NOT_RECORDED = `the approval of ${A} was not recorded`
  approvedHead = null
  lookAt = { pr: P, head: lookAt.head }
  const hd = await recall(() => call(`${CTX}
${RENEW_FIRST}
Then read the head of PR #${P}, changing nothing: run ${UNSET}gh pr view ${P} --repo ${SLUG} --json state,headRefOid and return state and head (headRefOid, the full sha). Run nothing else.
${RULES}`, { label: 'look-head', phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: withRenew(LOOK_HEAD_SCHEMA) }), r => r.renew)
  // A failed read says nothing about whether the owner recorded the approval: report the read, never a missing
  // approval.
  const UNREAD = { details: `the approval of ${A} could not be checked: PR #${P}'s head could not be read; the verified head is ${V0}`, result: hd }
  if (!hd) return stop('look-approve', UNREAD)
  const lostLook = renewed(hd.renew, 'look-approve')
  if (lostLook) return lostLook
  if (!complete(hd, LOOK_HEAD_SCHEMA) || !SHA_RE.test(hd.head)) return stop('look-approve', UNREAD)
  if (hd.state !== 'OPEN') return stop('look-approve', { details: `${NOT_RECORDED}: PR #${P} is ${hd.state}, not open, at head ${hd.head}` })
  const lookRead = () => call(`${CTX}
Read the owner's look approval of issue #${ISSUE} of ${SLUG}; it was recorded where the owner answered, so post nothing. Run alone and exactly: look-approval status --repo ${SLUG} --issue ${ISSUE} --pr ${P} --head ${A}
It prints one JSON line. Return its verdict, kept_from and any detail. Run nothing else.
${RULES}`, { label: 'look-read', phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: LOOK_STATUS_SCHEMA })
  const answeredOf = read => `look-approval status answered ${read ? (read.verdict || 'no verdict') : 'nothing'}${read && present(read.detail) ? `: ${read.detail}` : ''}`
  if (!sameSha(hd.head, A)) {
    // Only a stop for a new look says the approval was not recorded: a read that failed, a carry and every later stop
    // speak for themselves.
    const MOVED = `${NOT_RECORDED}: PR #${P}'s head is now ${hd.head}`
    // The live lane lands only the commit its one reviewer read: a moved head is never read or carried there.
    if (LANE === 'live') {
      lookWhy = MOVED
      return lookWaitStop(P, hd.head)
    }
    // The approval is read for A; a head moved outside the delivery (a merge made by hand) is verified, then carried
    // under the landing's rules.
    const read = await lookRead()
    const answered = answeredOf(read)
    if (!read || typeof read.verdict !== 'string' || read.verdict === 'error') return stop('look-approve', { details: `the approval of ${A} could not be checked: PR #${P}'s head is now ${hd.head} and ${answered}`, result: read })
    if (read.verdict === 'needed') {
      lookWhy = MOVED
      return lookWaitStop(P, hd.head)
    }
    if (read.verdict !== 'approved') return stop('look-approve', { details: `${MOVED} and ${answered}`, result: read })
    ownerHead = typeof read.kept_from === 'string' && SHA_RE.test(read.kept_from) ? read.kept_from : A
    const row = await carryLook(P, hd.head, V0, 'a merge made outside this delivery', true)
    if (row) return row
    expected = verify.head
    head = expected
    approvedHead = expected
    lookAt = approvedLook(P, expected)
  } else {
    // The live lane lands only the commit its one reviewer read: an approved head that moved (an integration merge, a
    // push) is never verified, recorded or merged here.
    if (LANE === 'live' && !sameSha(A, liveCommit())) return liveBound(`the owner approved ${A}, not the delivered commit ${liveCommit()}, and landing it would merge a commit the live review never read`)
    let recordable = sameSha(A, V0)
    if (!recordable) {
      const lv = await call(`${CTX}
  The owner approved head ${A} of PR #${P}, which is the pull request's head; the last verified head is ${V0}. Run only git commands and the declared verification, in this order:
  1. git -C ${W} fetch origin. When git -C ${W} rev-parse HEAD is not ${A} and git -C ${W} merge-base --is-ancestor HEAD ${A} succeeds, run git -C ${W} merge --ff-only ${A}; never any other merge, reset, checkout or push. When HEAD is then not ${A}, run nothing more and return head (git -C ${W} rev-parse HEAD), clean, results [], merge_only false, and ahead true only when git -C ${W} merge-base --is-ancestor ${A} HEAD succeeds (the worktree contains ${A}), else false.
  2. Otherwise (HEAD is ${A}) return ahead false, and merge_only true only when git -C ${W} merge-base --is-ancestor ${V0} ${A} succeeds, git -C ${W} rev-list --no-merges ${V0}..${A} ^origin/${INT} prints nothing (the head only gained integration-branch merges), and every merge in git -C ${W} rev-list --merges ${V0}..${A} ^origin/${INT} (a merge the integration branch already holds, such as one resolved by hand there, is not the head's own) is a clean two-parent merge, meaning git -C ${W} merge-tree --write-tree <merge>^1 <merge>^2 exits 0 and prints the tree id that git -C ${W} rev-parse <merge>^{tree} gives (a conflict resolved by hand, or an octopus merge, gives a different tree; never judge this from git show --cc, which omits a hunk where the merge keeps one parent unchanged); else false, and then run no verification and return results [].
  3. ${UNTOUCHED(V0, A)} Otherwise: ${verifyBody}`, { label: 'look-verify', phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: LOOK_VERIFY })
      if (!lv || !complete(lv, LOOK_VERIFY) || !SHA_RE.test(lv.head)) return stop('look-approve', { details: `${NOT_RECORDED}: its verification returned no usable reply; the verified head is ${V0}`, result: lv })
      if (!sameSha(lv.head, A)) {
        // The worktree could not be brought to the approved head. One that contains it pushes as an ordinary
        // fast-forward over it; any other cannot be pushed.
        if (lv.ahead !== true) return stop('look-approve', { details: `${NOT_RECORDED}: the worktree head ${lv.head} neither fast-forwards to it nor contains it, so it cannot be pushed over it` })
        lookWhy = `${NOT_RECORDED}: the worktree head ${lv.head} is ahead of it`
      } else if (lv.merge_only !== true) {
        return stop('look-approve', { details: `${NOT_RECORDED}: it adds commits after the verified head ${V0} that are not clean merges of ${INT}, so it needs a review first` })
      } else if (!skipsVerify(lv, V0) && verifyProblems(lv).length) {
        return stop('look-approve', { details: `${NOT_RECORDED}: its verification failed, so the verified head stays ${V0}`, problems: verifyProblems(lv) })
      } else {
        verify = skipsVerify(lv, V0) ? carriedTo(fuller(A, lv.head)) : { head: fuller(A, lv.head), clean: true, results: lv.results, ...(picturesOf(lv).length ? { pictures: picturesOf(lv) } : {}) }
        expected = verify.head
        head = expected
        recordable = true
      }
    }
    if (recordable) {
      const read = await lookRead()
      const answered = answeredOf(read)
      // An outage, an empty reply or an error verdict says nothing about whether the owner recorded the approval:
      // report that it could not be checked, never that it is missing.
      if (!read || typeof read.verdict !== 'string' || read.verdict === 'error') return stop('look-approve', { details: `the approval of ${A} could not be checked: the verified head was ${V0} and ${answered}`, result: read })
      if (read.verdict !== 'approved') return stop('look-approve', { details: `${NOT_RECORDED}: the verified head was ${V0} and ${answered}`, result: read })
      approvedHead = A
      ownerHead = A
      lookAt = approvedLook(P, approvedHead)
    }
  }
  LOOK_STOP = MARKED && approvedHead === null
}
const landBody = async () => {
  // The pr call may take the lock (--wait) after opening the PR: mark the verified head as possibly held before it, so
  // a lost reply still reaches the release. A marked delivery takes no lock: its look-pr call is the same step without
  // one.
  if (!LOOK_STOP) {
    lockHeld = true
    lockSha = expected
  }
  const prR = await recall(() => LOOK_STOP ? call(`${CTX}
${RENEW_FIRST}
${prOpen()}
Then, ${PROBE(W, INT)}
Then return behind: true when git -C ${W} merge-base --is-ancestor origin/${INT} HEAD fails (the head is behind ${INT}), else false. Issue #${ISSUE} waits for the owner's look before it merges: run no lock command, wait for no check and merge nothing.
${BEFORE_PR ? `${PR_TESTS}\n` : ''}${RULES}`, { label: 'look-pr', phase: 'Ship', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'high', schema: withRenew(PR_SCHEMA, { probe: NULLABLE(PROBE_SCHEMA), behind: { type: 'boolean' } }) }) : call(`${CTX}
${RENEW_FIRST}
${prOpen(MARKED && approvedHead && sameSha(approvedHead, expected) ? lookAt.pr : null)}
Then, ${PROBE(W, INT)}
${OWN_RED(W, '<the PR number>', expected)}
Otherwise take the cross-host landing lock of the branch ${INT} for that PR at the verified head ${expected}: run alone and exactly: ${LAND_ACQUIRE(expected, true)}
${LOCK_RETURN} Return it as lock; when no PR was opened or reused, run neither the probe nor a lock command and return probe null and lock null. Then, only when lock's verdict is acquired, already_held or moved and the pushed head is ${expected}, wait ${CHECKS_WAIT('<the PR number>')} Return those fields as checks; otherwise run nothing more and return checks null.
${BEFORE_PR ? `${PR_TESTS}\n` : ''}${RULES}`, { label: 'pr', phase: 'Ship', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'high', schema: withRenew(PR_SCHEMA, { probe: NULLABLE(PROBE_SCHEMA), own_red: NULLABLE(OWN_RED_SCHEMA), lock: NULLABLE(LOCK_SCHEMA), checks: NULLABLE(CHECKS) }) }), r => r.renew)
  if (!prR) return stop('pr', { result: null })
  // The probe found a conflict, so the call ran no lock command: nothing is held and nothing was waited for. A reply
  // that names a lock verdict all the same, or no tree id, is read as before the probe existed (the sync under the lock
  // finds the conflict).
  const early = probeConflict(prR.probe) && !prR.lock ? prR.probe : null
  // A check had already failed at the head, so the call ran no lock command either. A reply that names a lock verdict
  // all the same is read as before (the first poll under the lock finds the red check).
  const preRed = !early && !prR.lock && ownRed(prR.own_red, expected) ? prR.own_red : null
  if (early || preRed) lockHeld = false
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
  // land-contended is the wait running out at the CLI's bound behind other landings, so the claim is renewed and the
  // same acquire waits again, within the budget of waitBudget (a wait that ended first in line or at a better place
  // spends no retry). Each call is marked as possibly holding the lock first, as the pr call is.
  let waited = false
  const more = waits()
  let ranOut = prR.lock || null
  for (let k = 1; !early && !preRed && v === 'land-contended' && more(ranOut); k++) {
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
    ranOut = lk.lock || null
    logWait(`land-lock-${k}`, lk.lock)
    if (refusal(v)) lockHeld = false
    const lost = renewed(lk.renew, `land-lock-${k}`)
    if (lost) return lost
  }
  // One sync merge of the integration branch into the branch; a row ends the landing, null goes on to the next round.
  // With early (the probe's reply), the pr call found the conflict before the lock was asked for, so no sync step runs:
  // the resolution, its review and its fix wave are the same steps, the next round takes the lock for the first time,
  // and that merge spends none of the sync-contention budget. With prelock, a failed check at a head behind ${INT}
  // while another landing held the lock runs the same sync step before the lock is asked for, and spends none of that

  // budget either.
  const syncRound = async (early, prelock = false) => {
    if (LANE === 'live') return liveBound(`the branch is behind ${INT} or conflicts with it, and a sync merge would be a second implementer`, { pr: PR })
    if (!early && !prelock && !raced) {
      if (contended >= 2) return stop('sync-contention', { pr: PR, syncs })
      contended++
    }
    raced = false
    syncs++
    if (!early && !prelock) lockSyncs++
    const sy = early ? { status: 'conflicted', conflicted: true, notes: `the probe before the land lock found a conflict with ${INT}${(early.files || []).length ? ` in ${early.files.join(', ')}` : ''}` } : await call(`${CTX}
The branch is behind ${INT}. Merge origin/${INT} into it in the worktree (git -C ${W} merge origin/${INT}). If it conflicts, do not resolve it: run git merge --abort inside ${W}, confirm no merge is left in progress (git -C ${W} rev-parse -q --verify MERGE_HEAD fails), and return status conflicted with conflicted true and the conflicting files in notes; a later step resolves it. ${FMT}${BEFORE_PR ? ` ${SYNC_TESTS(W, INT, expected)}` : ''} Do not push. For a clean merge return conflicted false, merge_commit (full sha) and head (the full sha of HEAD after the merge: the merge commit itself, unless you committed on top of it); status blocked with notes if the merge cannot be made.
${RULES}`, { label: `sync-${syncs}`, phase: 'Ship', agentType: 'implementer', model: 'sonnet', schema: SYNC })
    // A blocked answer that names a conflict is the aborted merge under another name.
    const aborted = !!sy && (sy.status === 'conflicted' || (sy.status === 'blocked' && sy.conflicted === true))
    // The reply that names the merge to land: the sync step's own, or the resolution's.
    let merge = sy
    if (aborted || (sy && sy.status === 'done' && sy.conflicted)) {
      lockOut = true
      lockFirst = !!early || prelock
      fixedOut = false
      // A release that failed stays marked held, so the release of the next stop tries it again.
      if ((await unlock()).lock_unreleased) lockHeld = true
      if (aborted) {
        merge = await call(`${CTX}
Merging origin/${INT} into the branch conflicts. Resolve it in the worktree; the landing lock is not held while you work. If a merge is in progress (git -C ${W} rev-parse -q --verify MERGE_HEAD succeeds), run git merge --abort inside ${W} first. Then git -C ${W} fetch origin and git -C ${W} merge origin/${INT}. If it conflicts, resolve each conflict keeping both sides' intent, ${MARKER_CHECK(W, INT)}, and, still before committing, ${WHOLE('the files you resolved by hand')}; ${RESOLVE_SCOPE}. ${RESOLVE_ORDER}. ${FMT} Do not push. Return conflicted (false when the merge was clean this time; it is reviewed all the same), merge_commit (full sha), head (the full sha of HEAD: the merge commit, or the last commit you made on top of it), resolved_files and markers_checked (true when both checks ran); status blocked with notes if you cannot resolve it safely.
${RULES}`, { label: `sync-resolve-${syncs}`, phase: 'Ship', agentType: 'implementer', model: 'sonnet', schema: SYNC })
      }
    }
    if (!merge || merge.status !== 'done' || !present(merge.merge_commit)) return stop('sync', { pr: PR, sync: merge })
    // The head the landing goes on with is the merge commit, or the resolution's head when it made plain commits on top
    // of the merge. The sync review then proves that ancestry and reads the range between them too; any other head
    // stops at the sync stage.
    const mc = merge.merge_commit
    const followup = present(merge.head) && !sameSha(merge.head, mc)
    const after = followup ? SYNC_AFTER(W, mc, merge.head) : ''
    expected = followup ? merge.head : mc
    // A merge that conflicted is reviewed whatever its resolution says of itself: the sync step saw the conflict. A
    // head that is not the merge commit is reviewed too, whatever the merge was: nothing else would read the commits on
    // top of it.
    if (aborted || merge.conflicted || followup) {
      const sr = await readReview(`${CTX}
Review the conflict resolution in merge commit ${merge.merge_commit}: git -C ${W} show --cc ${merge.merge_commit} and the resolved files ${JSON.stringify(merge.resolved_files || [])}; the tests run: ${JSON.stringify(merge.tests || [])}. Report Important or Critical defects only: a dropped change from either side, a broken merge of intent, a resolved file whose tests were not run.${merge.markers_checked === true ? '' : MARKERS_UNCHECKED}${followup ? DESCENDS(W, mc, merge.head) : ''}`, { label: `sync-review-${syncs}`, phase: 'Ship', agentType: 'reviewer', schema: SYNC_REVIEW_SCHEMA(followup) })
      if (!sr) return stop('sync-review', { pr: PR, review: sr })
      // Only the review's own proof accepts a head that is not the merge commit; a missing answer is no proof.
      if (followup && sr.descends !== true) return stop('sync', { pr: PR, sync: merge, details: `the resolution names the head ${merge.head} and the merge commit ${mc}, and the head does not descend from it: only a reviewed merge commit lands` })
      if (findingsOf(sr).length) {
        if (syncFixes >= 1) return stop('sync-review', { pr: PR, review: sr })
        syncFixes++
        const w = await shipFix({
          stage: 'sync-fix', label: `fix-sync-${syncs}`, reviewLabel: `fix-sync-review-${syncs}`,
          rebuttal: true,
          fixPrompt: `${CTX}\n${SYNC_FIX(W, merge.merge_commit, findingsOf(sr), after)} Do not push. ${FIX_TESTS} ${COMMIT_SCOPE} ${IMPL_RETURN}\n${RULES}`,
          reviewPrompt: (fix, moved) => `${CTX}\n${SYNC_REREVIEW(W, merge.merge_commit, findingsOf(sr), fix, moved, after)}`,
        })
        if (!w.ok) return stop('sync-fix', { pr: PR, review: sr, fix: w.fix, ...(w.details ? { details: w.details } : {}) })
        if (!w.review || findingsOf(w.review).length) return stop('sync-review', { pr: PR, review: w.review, sync_review: sr, fix: w.fix })
        if (w.moved) expected = w.fix.commit
      } else if (finalReviewed) {
        finalReviewed = { ...finalReviewed, accepted: [...(finalReviewed.accepted || []), merge.merge_commit] }
      }
    }
    return null
  }
  // A stop before the first take: a pr call that answered conflicted may have taken the lock at the verified head all
  // the same, against its prompt, so that head is marked possibly held and the stop's release names it once (not_held
  // normally).
  const readyHead = expected
  const unheld = row => {
    if ((early || preRed) && lockFirst) {
      lockHeld = true
      lockSha = readyHead
      lockMaybe = null
    }
    return row
  }
  // The one fix wave of a red check (checksFixes bounds it). mode says where the lock is. held: under the lock (a red
  // check after a sync under it). first: the lock is held at a head no sync has changed, so the red check was the
  // branch's own: the fix step releases the lock itself once it knows the fix needs a commit (FIX_OFF_LOCK), a release
  // it did not report is made before the review, and the review runs outside the lock. unasked: the pr call read the
  // red check and asked for no lock. The lock stays marked held at its last sha on the fix step's word alone, so a stop

  // releases it once more.
  const ciFix = (ck, failingNames, mode) => {
    const failing = JSON.stringify(failingNames)
    return shipFix({
      stage: 'checks-fix', label: 'fix-ci', reviewLabel: 'fix-ci-review',
      rerun: true,
      schema: mode === 'first' ? { ...IMPL, properties: { ...IMPL.properties, lock_released: { type: 'boolean' } } } : IMPL,
      committed: mode === 'first' ? async fix => {
        log(`${failingNames.join(', ') || 'a check'} failed at the head the lock was taken at; its fix is reviewed outside the land lock`)
        // A release that failed stays marked held, so the release of the next stop tries it again.
        if (fix.lock_released !== true && (await unlock()).lock_unreleased) lockHeld = true
      } : null,
      fixPrompt: `${CTX}\n${PLAN_REF} The checks of PR #${PR} failed at ${expected}: ${failing}. Log tail: ${ck.details || 'none given'}.${mode === 'first' ? `\n${FIX_OFF_LOCK(lockSha)}\n` : mode === 'unasked' ? `\n${FIX_NO_LOCK}\n` : ' '}Find the cause in this branch's changes (git -C ${W} diff ${RANGE}), fix it with the smallest change and a regression test that fails without it, then commit. Do not push: the next checks step pushes. Never weaken, skip or delete a test or check to make it pass. ${FIX_TESTS} ${COMMIT_SCOPE} ${IMPL_RETURN}
When the failure has no cause in the code (an infrastructure, cache or network error in a setup step), change and commit nothing: ${RERUN_ALL(UNSET, SLUG, expected)}, do not wait for them, and return status done with the head unchanged (commit equal to start_head, ${expected}) and the error you saw in notes; the program then polls the checks itself.\n${RULES}`,
      reviewPrompt: fix => `${CTX}\nReview this fix for failing checks: ${span(fix)}; the failure it answers: ${failing} (${ck.details || 'no log'}); notes: ${fix.notes}. Report Important or Critical defects only, above all a weakened, skipped or deleted test or check, or a fix with no regression test. Do not edit anything.`,
    })
  }
  if (LOOK_STOP) {
    const stopped = early ? await syncRound(early) : prR.behind === true ? await syncRound(null, true) : null
    if (stopped) return stopped
    const lookPush = async () => {
      const pu = await recall(() => call(`${CTX}
${RENEW_FIRST}
Then push the branch ${setup.branch} of PR #${PR} at the head ${expected}: run alone git -C ${W} push origin ${setup.branch}, then return head (git -C ${W} rev-parse HEAD, the full sha).
${RULES}`, { label: 'look-push', phase: 'Ship', agentType: 'clerk', model: DEFAULT_CLERK_MODEL, effort: 'low', schema: withRenew(PUSH_SCHEMA) }), r => r.renew)
      if (!pu) return stop('push', { pr: PR })
      const lost = renewed(pu.renew, 'look-push')
      if (lost) return lost
      if (!sameSha(pu.head, expected)) return stop('head-moved', { pr: PR, expected, head: pu.head })
      expected = fuller(expected, pu.head)
      return null
    }
    if (!sameSha(expected, readyHead)) {
      const pushed = await lookPush()
      if (pushed) return pushed
    }
    for (;;) {
      const stalePoll = reran
      const { ck, row } = await lookPoll(PR, expected, stalePoll)
      if (row) return row
      expected = fuller(expected, ck.head)
      head = expected
      const rd = lookRead(ck)
      if (ck.behind !== true && rd.state === 'pending') {
        if (++lookWaits >= PENDING_WAITS) return stop('checks-pending', { pr: PR, pending: rd.pending, checks: ck })
        continue
      }
      reran = false
      if (ck.behind === true) {
        if (contended >= 2) return stop('sync-contention', { pr: PR, syncs })
        contended++
        const prior = expected
        const s = await syncRound(null, true)
        if (s) return s
        if (!sameSha(expected, prior)) {
          const pushed = await lookPush()
          if (pushed) return pushed
        }
        continue
      }
      if (rd.state === 'failed') {
        if (stalePoll && staleOf(ck).length) {
          log(`${'look-checks-' + lookPolls} reran ${staleOf(ck).length === 1 ? 'a stale gate run' : `${staleOf(ck).length} stale gate runs`} (${staleOf(ck).join(', ')}); polling once more`)
          continue
        }
        if (checksFixes >= 1) return stop('checks', { pr: PR, failing: rd.failing, checks: ck })
        checksFixes++
        const w = await ciFix(ck, rd.failing, 'unasked')
        if (w.bound) return liveBound(`a check failed at ${expected}, and a fix would be a second implementer`, { pr: PR })
        if (!w.ok) return stop('checks-fix', { pr: PR, checks: ck, fix: w.fix })
        if (w.rerun) {
          reran = true
          continue
        }
        if (!w.review || findingsOf(w.review).length) return stop('checks-fix-review', { pr: PR, checks: ck, review: w.review })
        expected = w.fix.commit
        head = expected
        const pushed = await lookPush()
        if (pushed) return pushed
        continue
      }
      // A head a fix or a sync moved is verified before the owner sees it, so the stop, its verified record and its
      // pictures name one head. The verification runs after the poll's forge read, so the wait reads the forge again
      // (the pull request head, its checks, the base's ancestry) before the stop.
      if (!sameSha(verify.head, expected)) {
        const rv = await call(`${CTX}\nThe branch of PR #${PR} moved to the head ${expected} after its verification at ${verify.head}. First return merge_only: true only when git -C ${W} merge-base --is-ancestor ${verify.head} ${expected} succeeds and ${onlyMerges(verify.head, expected)}; else false. Then ${UNTOUCHED(verify.head, expected)} Otherwise verify that head before the owner looks at it.\n${verifyBody}`, { label: 'look-reverify', phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: LOOK_REVERIFY })
        if (!complete(rv, VERIFY) || !sameSha(rv.head, expected)) return stop('verify', { pr: PR, verify: rv, problems: [{ id: '?', summary: `the verification of ${expected} returned no usable reply for it` }] })
        if (sameSha(rv.head, expected) && skipsVerify(rv, verify.head)) {
          verify = carriedTo(fuller(expected, rv.head))
          continue
        }
        if (verifyProblems(rv).length) return stop('verify', { pr: PR, verify: rv, problems: verifyProblems(rv) })
        verify = { head: fuller(expected, rv.head), clean: true, results: rv.results, ...(picturesOf(rv).length ? { pictures: picturesOf(rv) } : {}) }
        continue
      }
      break
    }
    return lookStop(PR, expected)
  }
  if (early) {
    log(`${INT} conflicts with the head; resolving before the land lock is asked for`)
    const stopped = await syncRound(early)
    if (stopped) return unheld(stopped)
  } else if (preRed) {
    let failingNames = preRed.failing.filter(present)
    let ck = { state: 'failed', head: expected, failing: failingNames, details: preRed.details }
    let red = true
    lockOut = true
    lockFirst = true
    if (preRed.behind === true) {
      // The failed check was read at a head behind its base while another landing held the lock, so the sync under the
      // lock would rerun that check with every other landing waiting behind it. The branch is brought up to date now,
      // outside the lock, and the checks of the new head are waited for with no lock asked for. Still red: the fix wave
      // below runs before the lock. Anything else: the next round takes the lock, waiting. A green head that is behind
      // is never synced early.
      log(`${failingNames.join(', ')} had failed at a head behind ${INT} and the land lock is held; bringing the branch up to date before the lock is asked for`)
      lockOut = false
      const stopped = await syncRound(null, true)
      if (stopped) return unheld(stopped)
      // syncRound sets lockOut only for a conflict it resolved: the round that takes the lock then says so.
      const resolved = lockOut
      lockOut = true
      lockFirst = true
      const pk = await recall(() => call(`${CTX}
${RENEW_FIRST}
Then wait ${CHECKS_WAIT(PR)}
${RULES}`, { label: `checks-${round}`, phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: withRenew(CHECKS) }), r => r.renew)
      const lost = pk ? renewed(pk.renew, `checks-${round}`) : null
      if (lost) return unheld(lost)
      if (!complete(pk, CHECKS)) return unheld(stop('checks', { pr: PR, checks: null }))
      if (!sameSha(pk.head, expected)) return unheld(stop('head-moved', { pr: PR, expected, head: pk.head }))
      expected = fuller(expected, pk.head)
      head = expected
      failingNames = (Array.isArray(pk.failing) ? pk.failing : []).filter(present)
      // As in the loop below: behind (the base moved again) is not a red poll, and the poll under the lock answers it.
      red = pk.state !== 'behind' && (pk.state === 'failed' || failingNames.length > 0)
      ck = { state: 'failed', head: expected, failing: failingNames, details: pk.details }
      syncedOut = !red && !resolved
    }
    if (red) {
      log(`${failingNames.join(', ')} had already failed at the head; fixing before the land lock is asked for`)
      fixedOut = true
      if (checksFixes >= 1) return unheld(stop('checks', { pr: PR, failing: failingNames, checks: ck }))
      checksFixes++
      const w = await ciFix(ck, failingNames, 'unasked')
      if (w.bound) return unheld(liveBound(`a check failed at ${expected}, and a fix would be a second implementer`, { pr: PR }))
      if (!w.ok) return unheld(stop('checks-fix', { pr: PR, checks: ck, fix: w.fix, ...(w.details ? { details: w.details } : {}) }))
      if (w.rerun) reran = true
      else {
        if (!w.review || findingsOf(w.review).length) return unheld(stop('checks-fix-review', { pr: PR, checks: ck, review: w.review }))
        expected = w.fix.commit
      }
    }
  } else if (!HOLDING.includes(v)) return stop(refusal(v) ? 'land-contended' : 'land-lock', { pr: PR, lock: v })
  for (;;) {
    round++
    // A sync merge, sync fix or CI fix moved the head: the push call renews and pushes it, then the checks call moves
    // the lock to it before it waits. When the lock was released for a conflicted sync, this round takes it again at
    // the accepted head, waiting.
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
      // A first take holds nothing at an earlier head, so the accepted head is the one sha a release names.
      if (retake && lockFirst) {
        lockSha = expected
        lockMaybe = null
      }
    }
    // Round 1 reads the poll the pr call carried (its renew covered the claim), unless a retried wait took the lock,
    // which polled no checks; a moved round moves the lock then polls, one call; every other unmoved round polls on its
    // own with a renew.
    const folded = round === 1 && !moved && !waited
    // The poll that follows a rerun of failed jobs is the only one that may answer stale; a poll whose wait ran out
    // keeps it for the next. A rerun made while the lock was not held is followed by a round that takes the lock at the
    // unchanged head, so that round asks the stale question too. reran is cleared by the first poll that is not
    // pending.
    const stalePoll = reran && !folded
    let ck
    if (folded) ck = prR.checks || null
    else {
      ck = await recall(() => call(`${CTX}
${moved ? `${retake && lockFirst ? `Take the cross-host landing lock of the branch ${INT} for PR #${PR} at the head ${expected}; ${fixedOut ? 'a failing check of the branch was fixed' : syncedOut ? `the branch was brought up to date with ${INT}` : `a conflict with ${INT} was resolved`} before the lock was asked for` : retake ? `Take the cross-host landing lock of the branch ${INT} for PR #${PR} again, at the head ${expected}; it was released while ${fixedOut ? 'a failing check of the branch was fixed' : 'a conflict was resolved'}` : `Move the cross-host landing lock of the branch ${INT} for PR #${PR} to the head ${expected}`}: run alone and exactly: ${LAND_ACQUIRE(expected, retake)}
${LOCK_RETURN} Return it as lock. Only when lock's verdict is acquired, already_held or moved, wait ${CHECKS_WAIT(PR)}${stalePoll ? ` ${STALE_RERUN(UNSET, SLUG)}` : ''} Otherwise run nothing else and return only lock.` : `${RENEW_FIRST}\nThen wait ${CHECKS_WAIT(PR)}${stalePoll ? ` ${STALE_RERUN(UNSET, SLUG)}` : ''}`}
${RULES}`, { label: `checks-${round}`, phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: moved ? { ...(stalePoll ? WITH_STALE(CHECKS) : CHECKS), properties: { ...(stalePoll ? WITH_STALE(CHECKS) : CHECKS).properties, lock: NULLABLE(LOCK_SCHEMA) }, required: ['lock'] } : withRenew(stalePoll ? WITH_STALE(CHECKS) : CHECKS) }), r => (moved ? null : r.renew))
      if (moved) {
        let mv = ck && ck.lock ? ck.lock.verdict : null
        if (ck) logWait(`checks-${round}`, ck.lock)
        let relocked = false
        const more = waits()
        let ranOut = ck ? ck.lock || null : null
        for (; retake && mv === 'land-contended' && more(ranOut);) {
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
          ranOut = lk.lock || null
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
          fixedOut = false
          syncedOut = false
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
    const state = ck.state === 'behind' ? 'behind' : ck.state === 'failed' || failingNames.length ? 'failed' : ck.state === 'pending' || pendingNames.length || noCheckYet(ck) || (MARKED && unproven(ck)) ? 'pending' : ck.state
    if (state === 'pending') {
      if (++pendingWaits >= PENDING_WAITS) return stop('checks-pending', { pr: PR, pending: pendingNames, checks: ck })
      continue
    }
    reran = false
    if (state === 'failed') {
      if (stalePoll && staleOf(ck).length) {
        log(`checks-${round} reran ${staleOf(ck).length === 1 ? 'a stale gate run' : `${staleOf(ck).length} stale gate runs`} (${staleOf(ck).join(', ')}); polling once more`)
        continue
      }
      if (checksFixes >= 1) return stop('checks', { pr: PR, failing: failingNames, checks: ck })
      checksFixes++
      // No sync has changed the head under the lock, so the red check is the branch's own: its fix goes outside the
      // lock.
      const first = lockSyncs === 0
      const w = await ciFix(ck, failingNames, first ? 'first' : 'held')
      if (w.bound) return liveBound(`a check failed at ${expected}, and a fix would be a second implementer`, { pr: PR })
      if (!w.ok) return stop('checks-fix', { pr: PR, checks: ck, fix: w.fix, ...(w.details ? { details: w.details } : {}) })
      if (w.rerun) {
        reran = true
        // A step that released the lock for a rerun, against its prompt: the next round takes it again, waiting.
        if (first && w.fix.lock_released === true) { lockOut = true; lockFirst = false; fixedOut = true }
        continue
      }
      // The lock is released (or its release is still owed, lockHeld): the next round takes it again at the reviewed
      // head.
      if (first) { lockOut = true; lockFirst = false; fixedOut = true }
      if (!w.review || findingsOf(w.review).length) return stop('checks-fix-review', { pr: PR, checks: ck, review: w.review })
      expected = w.fix.commit
      continue
    }
    if (state === 'passed') {
      // A marked delivery merges only a head the owner's approval covers. A head that moved since lands when
      // look-approval status says the approval is kept; needed stops for a new look, the lock released, and any other
      // reply stops without asking the owner (a forge failure is no reason for a look).
      if (MARKED && approvedHead && !sameSha(head, approvedHead)) {
        const ls = await call(`${CTX}
Read whether the owner's look approval of issue #${ISSUE} of ${SLUG} still covers the head ${head} of PR #${PR}. Run alone and exactly: look-approval status --repo ${SLUG} --issue ${ISSUE} --pr ${PR} --head ${head}
It prints one JSON line. Return its verdict, kept_from and any detail. Run nothing else.
${RULES}`, { label: 'look-status', phase: 'Ship', agentType: 'clerk', model: CLERK_MODEL, effort: 'low', schema: LOOK_STATUS_SCHEMA })
        if (!complete(ls, LOOK_STATUS_SCHEMA) || (ls.verdict !== 'approved' && ls.verdict !== 'needed')) return stop('look-status', { pr: PR, head, result: ls })
        if (ls.verdict === 'needed') {
          const row = await carryLook(PR, head)
          if (row) return row
        }
        if (ls.verdict === 'approved') ownerHead = typeof ls.kept_from === 'string' && SHA_RE.test(ls.kept_from) ? ls.kept_from : head
        approvedHead = head
        lookAt = approvedLook(PR, head)
      }
      mg = await recall(() => call(`${CTX}
${RENEW_FIRST}
Then re-check the cross-host landing lock of the branch ${INT} for PR #${PR}: run alone and exactly: ${LAND_ACQUIRE(expected, false)}
${LOCK_RETURN} Return it as lock.
Only when lock's verdict is already_held or moved, merge PR #${PR}: run, alone and exactly: ${UNSET}gh pr merge ${PR} --repo ${SLUG} --${STRATEGY} --match-head-commit ${head}${setup.delete_branch ? ' --delete-branch' : ''}
Then read gh pr view ${PR} --repo ${SLUG} --json state,mergeCommit: merged is true only when state is MERGED. Never retry with another form; on a guard refusal or a head mismatch return merged false with the exact message in notes, and behind true only when the refusal says the head branch is not up to date with the base branch, or the guard says the PR is behind its base (the integration branch moved), else false. On any other lock verdict run nothing else and return merged false with the verdict in notes.
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
      // Refused as not up to date: the next round's checks step fetches, reports behind and syncs; three refusals, or
      // any other, stop. That sync is bounded by the refusal budget alone, so syncs made before the first merge attempt
      // never consume it. Refused by the base branch's policy and not behind: the next round polls the checks once
      // more, and that poll picks the merge, the fix or the stop. A second such refusal stops, as every other refusal
      // does.
      if (POLICY_REFUSAL(mg) && policyPolls < 1) {
        policyPolls++
        log(`the merge was refused by the policy of ${INT}; polling the checks once more`)
        continue
      }
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
// suppress-standard:B17 the program's phases share module state (setup, verify, the look loop), so it stays one file
