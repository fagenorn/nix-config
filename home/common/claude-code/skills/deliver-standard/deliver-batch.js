export const meta = {
  name: 'deliver-batch',
  description: 'Deliver a batch of tracker issues in one repository: intake, just-in-time claims, deliver-standard children in ready mode, a serial land queue under the cross-host land lock, one table',
  whenToUse: 'A batch of issues of one repository the user asked to deliver together; args {repo_root, batch_id (<host>-<yyyymmdd-hhmm>), child_script (the absolute path of deliver-standard.js), issues (numbers) or label (every open issue carrying it), decisions? (owner answers by issue), conts? (a previous run forwarded child continuations), unattended? (true only for a run no session watches: its questions are then posted as box prompts)}; returns one table and, when any issue is unfinished, the relaunch args for a new run',
  phases: [
    { title: 'Setup', detail: 'resolve the project contract once' },
    { title: 'Intake', detail: 'read every issue facts behind one barrier, decide eligibility in code' },
    { title: 'Deliver', detail: 'lane per eligible issue, then the delivery children' },
    { title: 'Land', detail: 'serial land queue under the cross-host land lock' },
  ],
}

// Args: repo_root (the checkout), batch_id (the caller-supplied id; the claim holder is
// <host>/<batch_id>, so a relaunch with the same batch_id re-adopts its own claims), child_script
// (the absolute path of deliver-standard.js: this program has no filesystem access, D8), issues
// (positive integers, distinct) or label (every open issue carrying it; exactly one of the two),
// decisions ({"<issue>": owner answer}), conts ({"<issue>": a previous run's forwarded child
// continuation}, only for listed issues, D9), unattended (boolean, default false: true only for a run
// no session watches, D12).
// Result: { stage: args|setup|done|breaker, batch_id, table, questions, owner_actions, relaunch }.
// An already-fixed row is final and reported in owner_actions with its commit; the batch closes nothing.
// A closed issue whose claim this batch holds is released (at intake, or by the settle step after a stop with a cont
// that is not post-merge) and its row is final with released; a release that failed leaves the row stopped for a relaunch.
// A questions row is {issue, outcome: 'questions', lane?, questions, marker}: marker is the box prompt's
// comment id when an unattended run posted it, null when nothing was posted (a session-launched run
// returns the questions to its session). A session-launched conflict or needs-label row carries
// owner_ask: {reason, items} (what the marker would have held) and nothing is posted for it. The batch
// never reads or ends a decision prompt outside its land close-out: the child reads the answer itself.
// The lead runs a non-null relaunch as a NEW run, never with resumeFromRunId (D1): the new run
// re-reads the tracker (an owner reply, a closed blocker, a released lock) and every side effect
// re-adopts. Only a run cut off before it returned is resumed with its own original args.
// Every tracker effect goes through forge-claim (claims and the land lock, D2). Every policy
// value comes from the project contract that setup resolves; this file carries no project
// literal and defaults no policy value (D3).

const ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]*$/
const HOLDER_RE = /^[A-Za-z0-9][A-Za-z0-9.-]*\/[A-Za-z0-9][A-Za-z0-9._-]*$/
const isObj = v => v !== null && typeof v === 'object' && !Array.isArray(v)
const isPosInt = v => Number.isInteger(v) && v > 0
const bad = error => ({ stage: 'args', error })

// --- Args, checked before any agent ---
const REPO = args && args.repo_root
if (!REPO || typeof REPO !== 'string') return bad('repo_root is required')
const BATCH = args.batch_id
if (typeof BATCH !== 'string' || !ID_RE.test(BATCH)) return bad(`batch_id must match ${ID_RE}`)
const CHILD = args.child_script
if (!CHILD || typeof CHILD !== 'string') return bad('child_script is required')
const HAS_ISSUES = args.issues !== undefined
const HAS_LABEL = args.label !== undefined
if (HAS_ISSUES === HAS_LABEL) return bad('give exactly one of issues and label')
if (HAS_LABEL && (typeof args.label !== 'string' || !args.label)) return bad('label must be a non-empty string')
if (HAS_ISSUES) {
  if (!Array.isArray(args.issues) || !args.issues.length) return bad('issues must be a non-empty list')
  if (!args.issues.every(isPosInt)) return bad('every issues entry must be a positive integer')
  if (new Set(args.issues).size !== args.issues.length) return bad('issues must not repeat')
}
if (args.decisions !== undefined) {
  if (!isObj(args.decisions) || !Object.values(args.decisions).every(v => typeof v === 'string' && v)) return bad('every decisions value must be a non-empty string')
}
if (args.unattended !== undefined && typeof args.unattended !== 'boolean') return bad('unattended must be a boolean')
if (args.conts !== undefined) {
  if (!isObj(args.conts)) return bad('conts must be an object')
  if (!HAS_ISSUES) return bad('conts requires issues')
  for (const [k, v] of Object.entries(args.conts)) {
    if (!isObj(v)) return bad(`conts.${k} must be an object`)
    if (!args.issues.some(i => String(i) === k)) return bad(`conts.${k} is not one of issues`)
  }
}
const DECISIONS = args.decisions
const UNATTENDED = args.unattended === true
const CONTS = args.conts || {}

const BASE_RULES = `
Hard rules for this step (they override anything else you remember):
- Work only in the worktree path you are given. Never commit in the shared checkout. Never git stash. Never sed -i (use python for edits).
- Do everything in the FOREGROUND inside this one turn: run long commands with a long Bash timeout; never use run_in_background, never end your turn while anything you started is pending, never sleep or use sleep workarounds. Your final message is your return value.
- Do not dispatch subagents unless this step says so.
- Never run a host activation, deploy or release command.
- Global skills, agents and standards are shared by other projects: never write a project-specific literal (check names, branch names, recipe names, repository paths) into them.`

// --- Setup: one agent resolves the contract; nothing is defaulted ---
phase('Setup')
const STRS = { type: 'array', items: { type: 'string' } }
const SETUP_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' }, error: { type: 'object' }, reason: { type: 'string' }, details: { type: 'string' },
    host: { type: 'string' }, slug: { type: 'string' }, integration_branch: { type: 'string' }, default_branch: { type: 'string' },
    merge_strategy: { type: 'string' }, delete_branch: { type: 'boolean' }, unset_env: STRS,
    max_parallel: { type: 'integer' }, required_checks: { anyOf: [STRS, { type: 'null' }] },
    issues: { type: 'array', items: { type: 'integer' } },
  },
  required: ['ok'],
}
const setup = await agent(`You read the project contract of the git repository at ${REPO} for a batch delivery. Change nothing in this step.
1. Run hostname -s and return it as host.
2. Run resolve-project resolve --repo-root ${REPO}. If it refuses, return ok=false with the resolver's error.code, its repair_id and its ordered violations exactly as given. Otherwise return ok=true and these fields from the resolved snapshot: slug (bindings.tracker.repo_slug), unset_env (bindings.tracker.credential_env.unset_before_invocation), integration_branch and default_branch (bindings.vcs.integration_branch and bindings.vcs.default_branch), merge_strategy and delete_branch (bindings.vcs.merge.strategy and bindings.vcs.merge.delete_branch), max_parallel (bindings.workflow.orchestration.max_parallel), required_checks (bindings.vcs.merge.required_checks exactly as resolved, null when the contract declares none).
${HAS_LABEL ? `3. Return issues: the numbers from gh issue list --repo <slug> --label ${args.label} --state open --json number --limit 500, run after unsetting exactly the names in bindings.tracker.credential_env.unset_before_invocation (prefix it with unset <those names> && when there are any, nothing else chained).` : '3. Do not list issues.'}
${BASE_RULES}`, { label: 'setup', phase: 'Setup', model: 'sonnet', effort: 'low', schema: SETUP_SCHEMA })
if (setup === null || setup === undefined) return { stage: 'setup', result: null }
if (!setup.ok) return { stage: 'setup', result: setup }
const nonEmpty = v => typeof v === 'string' && v !== ''
const CHECKS = {
  host: nonEmpty, slug: nonEmpty, integration_branch: nonEmpty, default_branch: nonEmpty, merge_strategy: nonEmpty,
  delete_branch: v => typeof v === 'boolean', unset_env: v => Array.isArray(v), max_parallel: isPosInt,
}
const missing = Object.keys(CHECKS).filter(f => !CHECKS[f](setup[f]))
if (missing.length) return { stage: 'setup', result: setup, missing }
// required_checks must be returned: null when the contract declares none, else a non-empty list of distinct non-empty strings (D11); an absent field is never defaulted.
const RC = setup.required_checks
if (RC === undefined || (RC !== null && !(Array.isArray(RC) && RC.length && RC.every(nonEmpty) && new Set(RC).size === RC.length))) {
  return { stage: 'setup', result: setup, invalid: 'required_checks' }
}
const SETUP = setup
const DECLARED = SETUP.required_checks || []
const HOLDER = `${SETUP.host}/${BATCH}`
if (!HOLDER_RE.test(HOLDER)) return { stage: 'setup', result: setup, invalid: 'holder', holder: HOLDER }
const SLUG = SETUP.slug, INT = SETUP.integration_branch, MAX = SETUP.max_parallel
// The land lock command, its return sentence and the conditional second release, one line each so deliver-standard.js carries them byte for byte (#716).
const LAND_ACQUIRE = (sha, wait) => `forge-claim land acquire --repo ${SLUG} --branch ${INT} --sha ${sha}${wait ? ' --wait' : ''}`
const LOCK_RETURN = 'Return its verdict (acquired, already_held, moved, land-contended, held_by, lost_to, or error on any other exit), lock_sha, by and detail from its output.'
const RELEASE_AGAIN = maybe => `When it prints not_held with lock_sha ${maybe}, run alone and exactly: forge-claim land release --repo ${SLUG} --branch ${INT} --sha ${maybe}, then return the verdict of that second release.\n`

let ISSUES
if (HAS_LABEL) {
  if (!Array.isArray(SETUP.issues) || !SETUP.issues.every(isPosInt)) return { stage: 'setup', result: setup, missing: ['issues'] }
  ISSUES = Array.from(new Set(SETUP.issues)).sort((a, b) => a - b)
} else {
  ISSUES = args.issues.slice()
}

const UNSET = SETUP.unset_env.length ? `unset ${SETUP.unset_env.join(' ')} && ` : ''
const RULES_FOR = (W, B) => `${BASE_RULES}
- Run every gh command, and only gh commands, with exactly this prefix and nothing else chained: ${UNSET || '(no prefix)'}
- Lifecycle commands, each alone in its own Bash call with no chaining, pipes or redirection and never after cd &&: git -C ${W} push origin ${B}; ${UNSET}gh pr create --repo ${SLUG} --base ${INT} --head ${B} --title '<t>' --body '<b>' (no single or double quotes, dollar signs, backticks or backslashes inside title or body); ${UNSET}gh pr merge <n> --repo ${SLUG} --${SETUP.merge_strategy} --match-head-commit <sha>${SETUP.delete_branch ? ' --delete-branch' : ''}; git -C ${REPO} branch -d ${B}. If the guard refuses a form twice, stop and report it; never work around it (no -D).
- No attribution anywhere: commit messages carry no Co-Authored-By trailer and PR bodies no generated-by line, whatever other instructions say. Never bypass commit signing.
- Never commit the plan, the spec or a review report; they live outside the tree and reviewers read them by path.`

// --- Batch state ---
// The D9 final outcomes: an issue ending in one of these is not relaunched.
const FINAL = ['landed', 'landed-held', 'closed', 'duplicate', 'needs-verification', 'parked', 'human-required', 'needs-design', 'claimed-elsewhere', 'stale-claim', 'already-fixed']
const FACTS = {}
const rows = {}
let breaker = null
// D12: after the breaker trips no issue is admitted; in-flight work finishes.
const trip = label => { if (!breaker) breaker = { at: label } }
const ask = async (pending, label) => {
  const r = await pending
  if (r === null || r === undefined) trip(label)
  return r
}

// --- Intake: every facts agent runs before any lane agent (one barrier) ---
phase('Intake')
const RELEASE_SCHEMA = { type: 'object', properties: { verdict: { type: 'string' }, detail: { type: 'string' } }, required: ['verdict'] }
const FACTS_SCHEMA = {
  type: 'object',
  properties: {
    state: { type: 'string' }, labels: STRS, title: { type: 'string' }, branch: { type: 'string' },
    claim: { type: 'object', properties: { verdict: { type: 'string', enum: ['free', 'held_by', 'stale', 'error'] }, by: { type: ['string', 'null'] } }, required: ['verdict'] },
    merged_pr: { type: ['integer', 'null'] },
    already_fixed: { anyOf: [{ type: 'object', properties: { commit: { type: 'string' }, evidence: { type: 'string' } }, required: ['commit', 'evidence'] }, { type: 'null' }] },
    open_pr: { anyOf: [{ type: 'object', properties: { number: { type: 'integer' }, head_branch: { type: 'string' } } }, { type: 'null' }] },
    blockers: { type: 'array', items: { type: 'object', properties: { issue: { type: 'integer' }, state: { type: 'string' } }, required: ['issue', 'state'] } },
    decision: { type: 'object', properties: { verdict: { type: 'string' }, comment_id: { type: ['integer', 'null'] }, questions: { type: 'array', items: {} } } },
  },
  required: ['state', 'labels', 'claim', 'blockers'],
}
const factsPrompt = n => `You read the facts of issue #${n} of ${SLUG} (the git repository at ${REPO}) for a batch delivery with claim holder ${HOLDER}. Change nothing (a git fetch is fine), apart from what forge-claim status itself posts.
1. gh issue view ${n} --repo ${SLUG} --json state,labels,title,body,createdAt: return state, the label names as labels, and title; keep createdAt for step 7 (it is not returned).
2. branch: derive it for this issue from bindings.vcs.branch_pattern (read with resolve-project resolve --repo-root ${REPO}), the slug taken from the title.
3. claim: run alone and exactly forge-claim status --repo ${SLUG} --issue ${n} --holder ${HOLDER} and return its verdict (free, held_by or stale) and by; on exit 1 or 2 return verdict error.
4. merged_pr: the number of a merged PR referencing the issue (gh pr list --repo ${SLUG} --state merged --search ${n} --json number,body,title), else null. open_pr: {number, head_branch} of an open PR referencing the issue, else null.
5. blockers: the issues this one is blocked by, from the body's "Blocked by" list and the tracker's issue dependencies, each as {issue, state} with the state from gh issue view.
6. decision: run alone and exactly forge-claim owner-action status --repo ${SLUG} --issue ${n} --reason decision and return its verdict, comment_id and questions.
7. already_fixed: name the issue's concrete symptom as one literal string taken from its body (an error string, a quoted code literal, or the quoted output of a failing command; never run the failing command). Run git -C ${REPO} fetch origin ${INT}, then git -C ${REPO} grep -n -F '<literal>' origin/${INT} and git -C ${REPO} log origin/${INT} -S'<literal>' --since=<createdAt> --format='%H %s'. Return already_fixed {commit (the full sha of the commit since the issue opened that removed the literal), evidence (the literal and what both commands printed)} only when the grep finds the literal nowhere at origin/${INT} and the log names such a commit; otherwise, or with no concrete literal, return already_fixed null.
${RULES_FOR(REPO, '<branch>')}`
const releaseClosedPrompt = n => `Issue #${n} of ${SLUG} (the git repository at ${REPO}) is closed and this batch still holds its claim. Release it.
Run alone and exactly: forge-claim release --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason closed
Return its verdict (released on exit 0, not_held (exit 3) when the claim is already gone, or error on any other exit) and any detail. Run nothing else.
${RULES_FOR(REPO, (FACTS[n] || {}).branch || '<branch>')}`

await parallel(ISSUES.map(n => async () => {
  FACTS[n] = await ask(agent(factsPrompt(n), { label: `facts-${n}`, phase: 'Intake', model: 'sonnet', effort: 'low', schema: FACTS_SCHEMA }), `facts-${n}`)
}))

// Eligibility is plain JS over the facts, first match wins; null means eligible.
// A forwarded cont names a landing this batch started; its PR now reads as merged and the claim is still ours (or already released):
// the merge happened after the cont was forwarded, so the issue is re-adopted for its close-out, never skipped as a duplicate or closed.
const mergedReadopt = (n, f) => {
  const claim = f.claim || {}
  return !!(CONTS[n] && f.merged_pr && (claim.verdict === 'free' || claim.by === HOLDER))
}
const eligibility = (n, f) => {
  const readopt = mergedReadopt(n, f)
  // A closed issue whose claim lookup failed is not final: its claim may be this batch's, and only the release gives it back.
  if (f.state === 'CLOSED' && !readopt) {
    if ((f.claim || { verdict: 'error' }).verdict === 'error') return { issue: n, outcome: 'stopped', detail: 'claim status' }
    return { issue: n, outcome: 'closed' }
  }
  const labels = f.labels || []
  for (const [label, outcome] of [['needs-verification', 'needs-verification'], ['parked', 'parked'], ['agent:human-required', 'human-required']]) {
    if (labels.includes(label) && !(readopt && label === 'needs-verification')) return { issue: n, outcome }
  }
  if (f.merged_pr && !readopt) return { issue: n, outcome: 'duplicate', pr: f.merged_pr }
  // A failed claim lookup proves nothing about ownership: it falls through to the claim-error stop below, never to a final row.
  const fixed = f.already_fixed
  if (isObj(fixed) && nonEmpty(fixed.commit) && !CONTS[n] && (f.claim || {}).by !== HOLDER && (f.claim || {}).verdict !== 'error') {
    return { issue: n, outcome: 'already-fixed', commit: fixed.commit, evidence: fixed.evidence }
  }
  const claim = f.claim || { verdict: 'error' }
  if (claim.verdict === 'held_by' && claim.by !== HOLDER) return { issue: n, outcome: 'claimed-elsewhere', by: claim.by }
  if (claim.verdict === 'stale' && claim.by !== HOLDER) return { issue: n, outcome: 'stale-claim', by: claim.by }
  if (claim.verdict === 'error') return { issue: n, outcome: 'stopped', detail: 'claim status' }
  const outside = (f.blockers || []).filter(b => b.state === 'OPEN' && !ISSUES.includes(b.issue)).map(b => b.issue)
  if (outside.length) return { issue: n, outcome: 'blocked', blocker: Math.min(...outside) }
  // Only a questioned issue waits: no lane, no claim, no child until the owner answers.
  const decision = f.decision || {}
  if (decision.verdict === 'open' && !(DECISIONS && DECISIONS[String(n)])) {
    return { issue: n, outcome: 'questions', questions: decision.questions || [], marker: decision.comment_id }
  }
  return null
}

const eligible = []
for (const n of ISSUES) {
  const f = FACTS[n]
  if (f === null || f === undefined) { rows[n] = { issue: n, outcome: 'stopped', detail: `facts-${n} returned nothing` }; continue }
  const skip = eligibility(n, f)
  if (skip) rows[n] = skip
  else eligible.push(n)
}

// A closed issue whose claim this batch holds, or that reads free, gives the claim back at intake (#714).
// A free claim is retried too: forge-claim ends the claim before it edits the marker and removes the label, so a release that failed
// after that point leaves a free claim and unfinished cleanup, which only the release itself finishes (it answers not_held when none is owed).
// A live claim of another holder is never touched.
const releasable = f => { const c = (f && f.claim) || {}; return c.verdict === 'free' || ((c.verdict === 'held_by' || c.verdict === 'stale') && c.by === HOLDER) }
await parallel(ISSUES.filter(n => rows[n] && rows[n].outcome === 'closed' && releasable(FACTS[n])).map(n => async () => {
  const rel = await ask(agent(releaseClosedPrompt(n), { label: `release-${n}`, phase: 'Intake', model: 'sonnet', effort: 'low', schema: RELEASE_SCHEMA }), `release-${n}`)
  if (rel && (rel.verdict === 'released' || rel.verdict === 'not_held')) rows[n] = { ...rows[n], released: rel.verdict === 'released' }
  // A failed release is not final: the row stays open so a relaunch retries it, as close-out keeps a failed release stopped.
  else rows[n] = { issue: n, outcome: 'stopped', stage: 'release', detail: rel ? (rel.detail || rel.verdict) : `release-${n} returned nothing` }
}))

// The in-batch blockers of n still open on the tracker, ascending. An outside blocker is decided by eligibility.
const inBatchBlockers = n => Array.from(new Set(((FACTS[n] || {}).blockers || [])
  .filter(b => b.state === 'OPEN' && ISSUES.includes(b.issue)).map(b => b.issue))).sort((a, b) => a - b)

// A dependency cycle among the issues still to deliver is found here, right after intake and before any lane agent:
// an issue is on a cycle when a depth-first walk over in-batch blockers returns to it.
const onCycle = n => {
  const seen = new Set()
  const walk = m => {
    for (const b of inBatchBlockers(m)) {
      if (b === n) return true
      if (eligible.includes(b) && !seen.has(b)) { seen.add(b); if (walk(b)) return true }
    }
    return false
  }
  return walk(n)
}
const cycle = eligible.filter(onCycle)
for (const n of cycle) rows[n] = { issue: n, outcome: 'blocked', detail: 'cycle' }
const toDeliver = eligible.filter(n => !cycle.includes(n))

// DONE[n] resolves with the final row of every batch issue; a skipped issue resolves at once with its intake row.
const DONE = {}
const settle = {}
for (const n of ISSUES) DONE[n] = new Promise(resolve => { settle[n] = resolve })
for (const n of ISSUES) if (!toDeliver.includes(n)) settle[n](rows[n] || { issue: n, outcome: 'stopped', detail: 'no result' })

// --- Deliver ---
phase('Deliver')
const LANE_SCHEMA = { type: 'object', properties: { lane: { type: 'string', enum: ['direct', 'standard', 'needs-design'] }, why: { type: 'string' } }, required: ['lane'] }
const ACQUIRE_SCHEMA = {
  type: 'object',
  properties: { verdict: { type: 'string', enum: ['acquired', 'already_held', 'held_by', 'lost_to', 'error'] }, by: { type: 'string' }, comment_id: { type: 'integer' }, detail: { type: 'string' } },
  required: ['verdict'],
}
const ASK_SCHEMA = { type: 'object', properties: { verdict: { type: 'string', enum: ['posted', 'already_posted', 'error'] }, comment_id: { type: 'integer' } }, required: ['verdict'] }
const SETTLE_SCHEMA = { type: 'object', properties: { state: { type: 'string', enum: ['OPEN', 'CLOSED'] }, release: { type: ['string', 'null'] }, detail: { type: 'string' } }, required: ['state'] }
const ENDED_SCHEMA = { type: 'object', properties: { verdict: { type: 'string' }, detail: { type: 'string' } }, required: ['verdict'] }

// A FIFO semaphore of MAX child slots on this host: plain JS, no timers. A slot handed on by leave() stays counted.
let inUse = 0
const waiters = []
const admit = () => new Promise(resolve => { if (inUse < MAX) { inUse++; resolve() } else waiters.push(resolve) })
const leave = () => { const next = waiters.shift(); if (next) next(); else inUse-- }

// The owner's answer the batch itself carries: the relaunch's decisions only. A ticked decision prompt is read by the child.
const answerOf = n => (DECISIONS && DECISIONS[String(n)]) || null
// D12: a null child, or a stop that names dead agents, ends admission; a null field alone is an ordinary stop.
const terminalChild = r => r === null || r === undefined ||
  (!['done', 'ready', 'planned'].includes(r.stage) && Array.isArray(r.dead_agents) && r.dead_agents.length > 0)
// A stop the child raised after the merge (a re-adopted landing) still has close-out work its cont finishes; it is never settled (#714).
const POST_MERGE = ['hold', 'close-out', 'code-unmet']
const postMerge = r => !!r.pr || POST_MERGE.includes(r.stage)
const READY = {}
const readyOf = n => READY[n]
// The child's whole input (D1): the batch args, the issue's cont, its lane and the owner's answer, nothing else.
const childArgs = (n, lane) => {
  const a = { repo_root: REPO, issue: n, batch_id: BATCH, mode: 'ready' }
  if (CONTS[n]) a.cont = CONTS[n]
  else a.lane = lane
  const answer = answerOf(n)
  if (answer !== null) a.decisions = answer
  return a
}

// --- Land: one serial queue per integration branch, under the cross-host land lock (D2, D10) ---
// enqueue runs fn after every earlier landing on the branch settled, fulfilled or rejected.
const QUEUES = {}
const enqueue = (branch, fn) => {
  const run = (QUEUES[branch] || Promise.resolve()).then(() => fn())
  QUEUES[branch] = run.then(() => undefined, () => undefined)
  return run
}
const LAND_OA = [] // owner-actions the landings posted
const SEV = { type: 'string', enum: ['critical', 'important', 'minor'] }
const FINDINGS = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['pass', 'findings'] },
    findings: { type: 'array', items: { type: 'object', properties: { severity: SEV, file: { type: 'string' }, summary: { type: 'string' }, failing_input: { type: 'string' } }, required: ['severity', 'summary'] } },
  },
  required: ['verdict', 'findings'],
}
const IMPL = {
  type: 'object',
  properties: { status: { type: 'string', enum: ['done', 'blocked'] }, start_head: { type: 'string' }, commit: { type: 'string' }, tests: STRS, mutation_checked: { type: 'boolean' }, notes: { type: 'string' } },
  required: ['status', 'notes'],
}
const IMPL_RETURN = 'Return start_head (git rev-parse HEAD before you change anything) and commit (the full sha of HEAD after your last commit).'
const findingsOf = r => (r.findings || []).filter(f => f.severity !== 'minor')
const RENEW_SCHEMA = { type: 'object', properties: { verdict: { type: 'string', enum: ['renewed', 'not_held', 'error'] }, by: { type: 'string' }, detail: { type: 'string' } }, required: ['verdict'] }
const LOCK_SCHEMA = {
  type: 'object',
  properties: { verdict: { type: 'string', enum: ['acquired', 'already_held', 'moved', 'held_by', 'lost_to', 'land-contended', 'error'] }, lock_sha: { type: 'string' }, pr: { type: 'integer' }, by: { type: 'string' }, detail: { type: 'string' } },
  required: ['verdict'],
}
const LAND_PR_SCHEMA = { type: 'object', properties: { pr: { type: 'integer' }, head: { type: 'string' }, notes: { type: 'string' } }, required: ['pr', 'head'] }
const LAND_CHECKS_SCHEMA = {
  type: 'object',
  properties: { state: { type: 'string', enum: ['passed', 'failed', 'behind', 'needs_label'] }, head: { type: 'string' }, required: STRS, passed: STRS, failing: STRS, label: { type: 'string' }, details: { type: 'string' } },
  required: ['state', 'head'],
}
const RECORD_SCHEMA = { type: 'object', properties: { ok: { type: 'boolean' }, head: { type: 'string' }, detail: { type: 'string' } }, required: ['ok'] }
const LAND_SYNC_SCHEMA = {
  type: 'object',
  properties: { status: { type: 'string', enum: ['current', 'done', 'blocked'] }, conflicted: { type: 'boolean' }, head: { type: 'string' }, merge_commit: { type: 'string' }, resolved_files: STRS, tests: STRS, notes: { type: 'string' } },
  required: ['status'],
}
const LAND_MERGE_SCHEMA = { type: 'object', properties: { merged: { type: 'boolean' }, merge_commit: { type: 'string' }, notes: { type: 'string' } }, required: ['merged'] }
const CLOSE_SCHEMA = { type: 'object', properties: { issue_state: { type: 'string' }, branch_deleted: { type: 'boolean' }, released: { type: 'boolean' }, decision_ended: { type: 'boolean' }, notes: { type: 'string' } }, required: ['issue_state'] }
const MAX_SYNCS = 3

// The landing of one ready issue (D10). The order is: renew, open or re-adopt the PR at the ready head,
// take the land lock with --wait, resync, the checks loop, renew, the one-shot pre-merge acquire, merge,
// release, close out (#677). Every exit goes through the wrapper at the bottom: a landing that holds the
// lock releases it exactly once, at the last sha it was held at (P8), and a failed landing keeps the
// claim and its cont (D9).
const land = async (n, ready) => {
  const W = ready.worktree, B = ready.branch
  const RULES = RULES_FOR(W, B)
  const ACS = JSON.stringify(ready.acceptance)
  const allCode = ready.acceptance.every(a => a.kind === 'code')
  const closesLine = allCode && INT === SETUP.default_branch ? `Closes #${n}` : `Refs #${n}`
  let expected = ready.head
  let pr = null
  let lockHeld = false
  let lockSha = null
  const c = { sync: 0, syncReview: 0, lock: 0, checks: 0, record: 0, conflicts: 0, ciFails: 0 }
  const out = (outcome, extra) => ({ issue: n, outcome, ...(pr ? { pr } : {}), ...(extra || {}) })
  const call = (prompt, label, opts) => ask(agent(prompt, { label, phase: 'Land', ...opts }), label)
  const cheap = { model: 'sonnet', effort: 'low' }

  const renew = async at => {
    const label = `renew-${n}-${at}`
    const r = await call(`Renew the claim of issue #${n} of ${SLUG} (the git repository at ${REPO}) before the landing step ${at}.
Run alone and exactly: forge-claim renew --repo ${SLUG} --issue ${n} --holder ${HOLDER} --branch ${B}
Return its verdict (renewed, not_held, or error on any other exit), by and detail. Run nothing else.
${RULES}`, label, { ...cheap, schema: RENEW_SCHEMA })
    if (!r) return out('stopped', { stage: 'renew', detail: `${label} returned nothing` })
    if (r.verdict === 'renewed') return null
    if (r.verdict === 'not_held') return out('claim-lost', { by: r.by })
    return out('stopped', { stage: 'renew', detail: r.detail || r.verdict })
  }

  // The land lock; the verdict string, or null when the agent returned nothing.
  const lock = async wait => {
    c.lock++
    const label = `land-lock-${n}-${c.lock}`
    const r = await call(`Take the cross-host landing lock of the branch ${INT} for PR #${pr} of issue #${n} of ${SLUG} at the head ${expected}.
Run alone and exactly: ${LAND_ACQUIRE(expected, wait)}
${LOCK_RETURN} Run nothing else.
${RULES}`, label, { ...cheap, schema: LOCK_SCHEMA })
    return r ? r.verdict : null
  }

  const unlock = async () => {
    if (!lockHeld) return
    lockHeld = false
    await call(`Release the cross-host landing lock of the branch ${INT} held for issue #${n} of ${SLUG}.
Run alone and exactly: forge-claim land release --repo ${SLUG} --branch ${INT} --sha ${lockSha}
released and not_held are both fine. Return its verdict and any detail. Run nothing else.
${RULES}`, `land-unlock-${n}`, { ...cheap, schema: RELEASE_SCHEMA })
  }

  // D12: only an unattended run posts the marker; a session-launched run returns the same items on its row.
  const ownerAction = async (reason, items, outcome, extra) => {
    if (!UNATTENDED) return out(outcome, { ...(extra || {}), owner_ask: { reason, items } })
    const posted = await call(`The landing of issue #${n} of ${SLUG} (the git repository at ${REPO}) needs the owner (${reason}). Post the marker; the claim stays held.
1. Make a fresh directory with mktemp -d and write exactly this JSON array to a file in it: ${JSON.stringify(items)}
2. Run alone and exactly: forge-claim owner-action post --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason ${reason} --items-file <that file>
Return its verdict (posted, already_posted, or error on any other exit) and comment_id. Change nothing else.
${RULES}`, `land-ask-${n}`, { ...cheap, schema: ASK_SCHEMA })
    if (!posted || (posted.verdict !== 'posted' && posted.verdict !== 'already_posted')) {
      return out('stopped', { stage: 'owner-action', detail: `land-ask-${n} did not post the ${reason} marker` })
    }
    LAND_OA.push({ issue: n, reason, comment_id: posted.comment_id })
    return out(outcome, extra)
  }

  // After a head change that passed its gate once the PR exists (D13): record it, then move the lock.
  const advance = async () => {
    c.record++
    const label = `land-record-${n}-${c.record}`
    const rec = await call(`The head of PR #${pr} of issue #${n} of ${SLUG} changed to ${expected} and passed its gate. Record it in the PR body.
1. Run gh pr view ${pr} --repo ${SLUG} --json body,headRefOid and confirm headRefOid is ${expected}. If it is not, change nothing and return ok false with the head it shows.
2. Make a fresh directory with mktemp -d and write the body to a file in it, rewriting only the Accepted head line (the last line of the Evidence section) to exactly this text, everything else unchanged:
Accepted head: ${expected}
3. Run gh pr edit ${pr} --repo ${SLUG} --body-file <that file>. When the line already reads exactly so, change nothing.
Return ok true and head (the headRefOid you read).
${RULES}`, label, { ...cheap, schema: RECORD_SCHEMA })
    if (!rec || rec.ok !== true || rec.head !== expected) return out('stopped', { stage: 'land-record', detail: rec ? rec.detail : `${label} returned nothing`, head: rec ? rec.head : undefined })
    const v = await lock(false)
    if (v !== 'moved' && v !== 'already_held' && v !== 'acquired') return out('land-contended', { detail: `the lock did not move to ${expected}` })
    lockHeld = true
    lockSha = expected
    return null
  }

  // One resync of the branch with the integration branch (D10); a row ends the landing, null continues.
  const resync = async () => {
    c.sync++
    const label = `land-sync-${n}-${c.sync}`
    const second = c.conflicts > 0
    const sy = await call(`Issue #${n} of ${SLUG} is being landed into ${INT}. Bring the branch ${B} up to date in the worktree ${W}.
1. git -C ${W} fetch origin. If origin/${INT} is an ancestor of HEAD (git -C ${W} merge-base --is-ancestor origin/${INT} HEAD succeeds), change nothing and answer status current with head (git -C ${W} rev-parse HEAD, the full sha).
2. Otherwise merge it: git -C ${W} merge origin/${INT}. A clean merge: answer status done, conflicted false, head (the full sha of the merge commit).
3. ${second
      ? `This landing already resolved one conflict. If the merge conflicts, run git merge --abort inside ${W} and answer status blocked, conflicted true, with head (the full sha of HEAD) and notes. Do not resolve it.`
      : `If the merge conflicts, resolve each conflict keeping both sides' intent, commit the merge, and run only the tests covering the files the resolution touched; answer status done, conflicted true, with head (the full sha of the merge commit), resolved_files and tests. If you cannot resolve it safely, run git merge --abort inside ${W} and answer status blocked, conflicted true, with notes.`}
${pr ? `4. After a merge you completed, push the result: git -C ${W} push origin ${B}.` : '4. Do not push.'}
${RULES}`, label, { phase: 'Land', agentType: 'implementer', model: 'sonnet', schema: LAND_SYNC_SCHEMA })
    if (!sy) return out('stopped', { stage: 'land-sync', detail: `${label} returned nothing` })
    const conflictOwner = notes => ownerAction('conflict', [`PR #${pr} of issue #${n} conflicts with ${INT} a second time in one landing, so the merge was aborted. ${notes || ''} Resolve the conflict on the branch ${B}, then relaunch the batch.`], 'conflict', { detail: sy.notes })
    if (sy.status === 'blocked') {
      if (!sy.conflicted) return out('stopped', { stage: 'land-sync', detail: sy.notes })
      if (!second) { c.conflicts++; return out('conflict', { detail: sy.notes }) }
      return await conflictOwner(sy.notes)
    }
    const head = sy.head || sy.merge_commit || (sy.status === 'current' ? expected : null)
    if (!head) return out('stopped', { stage: 'land-sync', detail: 'the resync named no head' })
    if (sy.status === 'current') {
      if (head !== expected) return out('stopped', { stage: 'head-moved', expected, head })
      return null
    }
    if (sy.status !== 'done') return out('stopped', { stage: 'land-sync', detail: sy.notes })
    if (sy.conflicted) {
      if (second) return await conflictOwner(sy.notes)
      c.conflicts++
      c.syncReview++
      const mc = sy.merge_commit || head
      const rv = await call(`Issue #${n} of ${SLUG}, worktree ${W}, branch ${B}.
Review the conflict resolution in merge commit ${mc}: git -C ${W} show --cc ${mc} and the resolved files ${JSON.stringify(sy.resolved_files || [])}; the tests run: ${JSON.stringify(sy.tests || [])}. Report Important or Critical defects only: a dropped change from either side, a broken merge of intent, a resolved file whose tests were not run. Do not edit anything.
${RULES}`, `land-sync-review-${n}-${c.syncReview}`, { agentType: 'reviewer', schema: FINDINGS })
      if (!rv || findingsOf(rv).length) return out('conflict', { review: rv })
    }
    if (head !== expected) {
      expected = head
      if (pr) return await advance()
    }
    return null
  }

  // The behind handling shared by a checks reply and a lock that was lost and retaken.
  const behind = async () => {
    if (c.sync >= MAX_SYNCS) return out('land-contended', { detail: `behind ${INT} after ${c.sync} resyncs` })
    return await resync()
  }

  const body = async () => {
    // The order (#677): the PR opens at the ready head, the land lock is taken waiting (the CLI waits
    // within its bound, so the acquire is sent once), and only then does the first resync run, so no
    // resync, check or merge happens outside the lock. A resync that changes the head pushes it and
    // advance() moves the lock; lockSha changes only on a holding verdict, so the release below always
    // names the last sha the lock was held at, even when a move fails.
    const lostA = await renew('land')
    if (lostA) return lostA

    const prR = await call(`Open the pull request of issue #${n} of ${SLUG} (the git repository at ${REPO}) from the branch ${B} (worktree ${W}) into ${INT}, or re-adopt the open one, so that its body is exactly the text below.
1. Push the branch: git -C ${W} push origin ${B}.
2. If an open PR with head ${B} exists (a re-run), reuse it: write the body to a file under a fresh directory made with mktemp -d and run ${UNSET}gh pr edit <pr> --repo ${SLUG} --body-file <that file>. Never reuse or edit a PR whose head is another branch, even when it references this issue; leave it untouched. Otherwise open one with the create form above. Title: a short summary of the issue.
Body, plain prose, no single or double quotes, dollar signs, backticks or backslashes: sections Why, What changes, Acceptance (a table with one row per criterion: id, criterion, kind, and the test or command that shows it; criteria ${ACS}), Evidence (verification ${JSON.stringify(ready.verify || [])}; ${(ready.tasks || []).length} tasks reviewed; the last line of the Evidence section is exactly: Accepted head: ${expected}), Merge danger; then the line ${closesLine} as the last line of the body, with no attribution or generated-by line. Never attach or link the plan or the spec.
Return pr (number) and head (the full sha of the pushed head).
${RULES}`, `land-pr-${n}`, { model: 'sonnet', schema: LAND_PR_SCHEMA })
    if (!prR || !prR.pr) return out('stopped', { stage: 'pr', detail: `land-pr-${n} returned nothing` })
    pr = prR.pr
    if (prR.head !== expected) return out('stopped', { stage: 'head-moved', expected, head: prR.head })

    const v1 = await lock(true)
    if (v1 === 'acquired' || v1 === 'already_held' || v1 === 'moved') { lockHeld = true; lockSha = expected }
    else if (v1 === 'land-contended' || v1 === 'held_by' || v1 === 'lost_to') return out('land-contended', { detail: `the land lock is held by another landing (${v1})` })
    else return out('stopped', { stage: 'land-lock', detail: v1 === null ? `land-lock-${n}-1 returned nothing` : v1 })

    const first = await resync()
    if (first) return first

    for (;;) {
      c.checks++
      const label = `land-checks-${n}-${c.checks}`
      const ck = await call(`Wait for the required checks of PR #${pr} of issue #${n} of ${SLUG} (worktree ${W}, branch ${B}) at the head.
1. git -C ${W} fetch origin; if the local branch is ahead of origin/${B}, push it. head is git -C ${W} rev-parse HEAD (the full sha).
2. If origin/${INT} is not an ancestor of HEAD (git -C ${W} merge-base --is-ancestor origin/${INT} HEAD fails), answer state behind at once with head.
3. Otherwise wait in this turn for the required checks on head. The required set is the checks the project declares, as JSON: ${JSON.stringify(DECLARED)} (an empty list declares none), plus the checks the forge requires: take those from gh api repos/${SLUG}/rules/branches/${INT} (its required_status_checks rules) or else classic branch protection; if neither answers, every check is required. A declared check with no run or status at head yet is pending: keep waiting for it, never treat it as absent or green. gh pr checks ${pr} --repo ${SLUG} --watch (Bash timeout up to 60 minutes; rerun while any is pending) can return early, and its --required list can be partial: never treat a partial list as green.
4. Answer passed only when every required name has passed on head, with required (the names you used) and passed (the names passing at head). Answer failed with failing (the failing names) and details when a required check failed. Answer needs_label with label and failing when a required check failed only because the PR lacks a label that only a human may apply (do not apply it yourself).
${RULES}`, label, { ...cheap, schema: LAND_CHECKS_SCHEMA })
      if (!ck) return out('stopped', { stage: 'checks', detail: `${label} returned nothing` })
      if (ck.head !== expected) return out('stopped', { stage: 'head-moved', expected, head: ck.head })

      if (ck.state === 'needs_label') {
        const names = (ck.failing || []).join(', ')
        return await ownerAction('needs-label', [`PR #${pr} of issue #${n} needs the label ${ck.label || '(unnamed)'}, which only the owner applies; the failing required checks: ${names || 'unnamed'}.`], 'needs-label', { label: ck.label, failing: ck.failing })
      }
      if (ck.state === 'failed') {
        c.ciFails++
        if (c.ciFails >= 2) return out('ci-failed', { failing: ck.failing })
        const fix = await call(`Issue #${n} of ${SLUG}: the required checks of PR #${pr} failed at ${expected}: ${JSON.stringify(ck.failing || [])}. Details: ${ck.details || 'none given'}.
Work in the worktree ${W} on branch ${B}. Find the cause in this branch's changes, fix the failing required checks with the smallest change and a regression test, commit, and push (git -C ${W} push origin ${B}). Never weaken, skip or delete a test or check to make it pass. ${IMPL_RETURN}
${RULES}`, `land-fix-${n}`, { agentType: 'implementer', model: 'sonnet', schema: IMPL })
        if (!fix || fix.status !== 'done' || !fix.commit || fix.commit === expected) return out('ci-failed', { failing: ck.failing, detail: 'the fix round did not finish' })
        const rv = await call(`Issue #${n} of ${SLUG}, worktree ${W}, branch ${B}.
Review this fix for failing required checks: git -C ${W} diff ${fix.start_head || expected}..${fix.commit}; the failure it answers: ${JSON.stringify(ck.failing || [])}; the implementer's notes: ${fix.notes}. Report Important or Critical defects only, above all a weakened, skipped or deleted test or check. Do not edit anything.
${RULES}`, `land-fix-review-${n}`, { agentType: 'reviewer', schema: FINDINGS })
        if (!rv || findingsOf(rv).length) return out('ci-failed', { failing: ck.failing, review: rv })
        expected = fix.commit
        const adv = await advance()
        if (adv) return adv
        continue
      }
      if (ck.state === 'behind') {
        const r = await behind()
        if (r) return r
        continue
      }
      if (ck.state !== 'passed') return out('stopped', { stage: 'checks', detail: `unknown checks state ${ck.state}` })

      // D11: a declared check missing from the passed names is never merged.
      const have = ck.passed || []
      const missingNames = DECLARED.filter(d => !have.includes(d))
      if (missingNames.length) return out('stopped', { stage: 'checks', missing: missingNames })

      const lostB = await renew('merge')
      if (lostB) return lostB
      const v2 = await lock(false)
      if (v2 === 'already_held' || v2 === 'moved') break
      if (v2 === 'acquired') {
        // The lock was lost and retaken, so the base may have moved: resync first.
        lockHeld = true
        lockSha = expected
        const r = await behind()
        if (r) return r
        continue
      }
      return out('land-contended', { detail: `the land lock was not held before the merge (${v2})` })
    }

    const mg = await call(`Merge PR #${pr} of issue #${n} of ${SLUG} into ${INT}; a re-run must not merge twice.
1. Read ${UNSET}gh pr view ${pr} --repo ${SLUG} --json state,mergeCommit. When state is already MERGED, skip step 2.
2. Otherwise run, alone and exactly: ${UNSET}gh pr merge ${pr} --repo ${SLUG} --${SETUP.merge_strategy} --match-head-commit ${expected}${SETUP.delete_branch ? ' --delete-branch' : ''}
3. Read the PR state again: merged is true only when the state reads MERGED. Never retry with another form; on a guard refusal or a head mismatch return merged false with the exact message in notes.
Return merged, merge_commit and notes.
${RULES}`, `land-merge-${n}`, { ...cheap, schema: LAND_MERGE_SCHEMA })
    if (!mg || mg.merged !== true) return out('stopped', { stage: 'merge', detail: mg ? mg.notes : `land-merge-${n} returned nothing` })
    await unlock()
    // The merge is done: a failure from here on must leave a cont, or a re-adopted PR (which has none) could not be closed out.
    if (!CONTS[n]) CONTS[n] = { setup: { holder: HOLDER, branch: B, worktree: W, worktree_path: W }, lane: 'standard', plan: { acceptance: ready.acceptance } }

    const openCriteria = ready.acceptance.filter(a => a.kind !== 'code')
    const co = await call(`Issue #${n} of ${SLUG}: PR #${pr} is merged into ${INT}. Close out; skip any step an earlier attempt already finished. Each command in its own Bash call:
1. Invoke the deliver-direct skill with the Skill tool and run its step 7 (Close out) for this checkout ${REPO}, worktree ${W}, branch ${B} and integration branch ${INT}: it is the single source for removing the worktree, fast-forwarding the checkout and deleting the local branch.
2. Release the claim: run alone and exactly forge-claim release --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason done. released is true only for verdict released.
3. End the owner-action markers, each alone and exactly: forge-claim owner-action end --repo ${SLUG} --issue ${n} --reason conflict, then forge-claim owner-action end --repo ${SLUG} --issue ${n} --reason needs-label, then forge-claim owner-action end --repo ${SLUG} --issue ${n} --reason decision. The merge proves the conflict and the label resolved and the decision settled; a verdict none is fine. decision_ended is true only when the decision end exited 0 (verdict ended or none).
4. ${allCode
      ? `Every criterion is of kind code. Read ${UNSET}gh issue view ${n} --repo ${SLUG} --json state; if it is still open (${INT === SETUP.default_branch ? 'the closing keyword did not fire' : `${INT} is not the default branch, so no closing keyword fires`}), run ${UNSET}gh issue close ${n} --repo ${SLUG} --comment 'Delivered by PR ${pr} into ${INT}.'`
      : `Keep the issue open. Add the needs-verification label (create it if missing) and comment which criteria remain and how to check each: ${JSON.stringify(openCriteria)}.`}
Return issue_state (OPEN or CLOSED, read back from the tracker), branch_deleted, released, decision_ended and notes.
${RULES}`, `close-out-${n}`, { ...cheap, schema: CLOSE_SCHEMA })
    const want = allCode ? 'CLOSED' : 'OPEN'
    if (!co || co.issue_state !== want || co.released !== true || co.decision_ended !== true) return out('stopped', { stage: 'close-out', close_out: co, expected_issue_state: want })
    return out(allCode ? 'landed' : 'landed-held')
  }

  let result
  try {
    result = await body()
  } catch (e) {
    result = out('stopped', { stage: 'land', detail: String((e && e.message) || e) })
  }
  try { await unlock() } catch (e) { /* the row stands; a dead unlock agent already tripped the breaker */ }
  // D9: a landing failure keeps the claim, and CONTS[n] already holds the ready result's cont (set when the child returned), so a relaunch re-adopts both.
  return result
}

// A readoptable issue: an earlier run of this batch already opened its PR, on the branch this batch derives for the issue (D13).
// An open PR on another head branch is not readoptable: that issue goes to its child, whose own setup decides.
const readoptable = n => {
  const f = FACTS[n] || {}
  return !!(f.open_pr && f.branch && f.open_pr.head_branch === f.branch)
}
const READOPT_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' }, reason: { type: 'string', enum: ['unaccepted', 'dirty', 'no-acceptance', 'worktree', 'other'] }, detail: { type: 'string' },
    worktree: { type: 'string' }, branch: { type: 'string' }, head: { type: 'string' },
    acceptance: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, text: { type: 'string' }, kind: { type: 'string', enum: ['code', 'evidence', 'human'] } }, required: ['id', 'text', 'kind'] } },
  },
  required: ['ok'],
}
const readoptPrompt = n => {
  const f = FACTS[n], B = f.branch, pr = f.open_pr.number
  return `Re-adopt the open pull request #${pr} of issue #${n} of ${SLUG} (the git repository at ${REPO}), whose head branch ${B} an earlier run of this batch pushed. Change nothing in this step except a missing worktree: never reset, clean, restore or stash anything.
1. Run git -C ${REPO} fetch origin.
2. Read ${UNSET}gh pr view ${pr} --repo ${SLUG} --json headRefOid,body. The PR is landed as it stands only at its accepted head: the body's Evidence section ends with a line Accepted head: <sha>. Answer ok false with reason unaccepted (and the head you read in detail) when the body has no Accepted head: line or the line's sha differs from headRefOid, and stop there.
3. Find the worktree on ${B}: run git -C ${REPO} worktree list --porcelain and take the entry whose branch is refs/heads/${B}. When there is none, resolve the contract once (resolve-project resolve --repo-root ${REPO}) and add one at the path bindings.vcs.worktree.root (resolved against project.root) plus bindings.vcs.worktree.prefix and ${B}: git -C ${REPO} worktree add <path> ${B} when the local branch exists, else git -C ${REPO} worktree add --no-track -b ${B} <path> origin/${B} when only the remote branch exists. When that fails, answer ok false with reason other and the error in detail.
4. In that worktree: when git -C <worktree> status --porcelain shows any change, answer ok false with reason dirty and the status in detail. When git -C <worktree> rev-parse HEAD differs from headRefOid, answer ok false with reason worktree and both shas in detail.
5. Read the body's Acceptance table, one row per criterion (id, criterion, kind, and how it is shown). When the body has no Acceptance table, answer ok false with reason no-acceptance. Otherwise answer ok true with worktree (its absolute path), branch ${B}, head (headRefOid, the full sha) and acceptance: one {id, text (the criterion), kind (code, evidence or human, as the table says)} per row.
${RULES_FOR('<the worktree path>', B)}`
}

const deliverOne = async n => {
  if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted' }; return }
  const f = FACTS[n]
  const readopt = readoptable(n)
  let laneName
  // The lane step; false when it ended the issue (its row is set). A readoptable issue defers it until its PR is found unaccepted.
  const chooseLane = async () => {
    const lane = await ask(agent(`You choose the delivery lane of issue #${n} of ${SLUG} (the git repository at ${REPO}). Change nothing in this step.
Read the issue with its comments (gh issue view ${n} --repo ${SLUG} --comments) and invoke the deliver-direct skill with the Skill tool to read its Eligibility paragraph, the single source of what a direct issue is.
Answer direct when the issue meets that Eligibility. Answer needs-design when its criteria are missing or not checkable, or it needs an open design decision that the issue, its comments and the repository docs do not settle. Otherwise answer standard. Return lane and a one-sentence why.
${RULES_FOR(REPO, f.branch || '<branch>')}`, { label: `lane-${n}`, phase: 'Deliver', model: 'sonnet', effort: 'medium', schema: LANE_SCHEMA }), `lane-${n}`)
    if (lane === null || lane === undefined) { rows[n] = { issue: n, outcome: 'stopped', detail: `lane-${n} returned nothing` }; return false }
    if (lane.lane === 'needs-design') {
      if (readopt) {
        // The claim is already held: give it back, as the row says nothing is left to resume.
        await ask(agent(`Issue #${n} of ${SLUG} (the git repository at ${REPO}) needs a design before it can be delivered. Release the batch claim.
Run alone and exactly: forge-claim release --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason skipped
Return its verdict and any detail. Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `release-${n}`, phase: 'Deliver', model: 'sonnet', effort: 'low', schema: RELEASE_SCHEMA }), `release-${n}`)
      }
      rows[n] = { issue: n, outcome: 'needs-design', lane: lane.lane }
      return false
    }
    laneName = lane.lane
    return true
  }
  if (CONTS[n]) laneName = CONTS[n].lane || 'standard'
  else if (!readopt && !(await chooseLane())) return
  rows[n] = { issue: n, outcome: 'eligible', lane: laneName }

  // A dependent waits for each in-batch blocker's final row before it asks for a slot: it holds no slot and no claim meanwhile.
  for (const blocker of inBatchBlockers(n)) {
    const b = await DONE[blocker]
    if (b.outcome === 'landed' || b.outcome === 'closed') continue
    if (b.outcome === 'landed-held' || b.outcome === 'needs-verification') { rows[n] = { issue: n, outcome: 'waits-verification', blocker }; return }
    rows[n] = { issue: n, outcome: 'blocked', blocker }
    return
  }

  // An issue is claimed only once it holds a child slot: a waiting issue holds no claim.
  if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted' }; return }
  await admit()
  let admitted = true
  try {
    if (breaker) { rows[n] = { issue: n, outcome: 'not-admitted' }; return }
    const acq = await ask(agent(`You claim issue #${n} of ${SLUG} (the git repository at ${REPO}) for the batch holder ${HOLDER}.
Run alone and exactly: forge-claim acquire --repo ${SLUG} --issue ${n} --holder ${HOLDER} --branch ${f.branch}
Return its verdict (acquired, already_held, held_by, lost_to, or error on any other exit), by and comment_id from its output. Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `acquire-${n}`, phase: 'Deliver', model: 'sonnet', effort: 'low', schema: ACQUIRE_SCHEMA }), `acquire-${n}`)
    if (acq === null || acq === undefined) { rows[n] = { issue: n, outcome: 'stopped', stage: 'acquire', detail: `acquire-${n} returned nothing` }; return }
    if (acq.verdict === 'held_by' || acq.verdict === 'lost_to') { rows[n] = { issue: n, outcome: 'claim-lost', by: acq.by }; return }
    if (acq.verdict !== 'acquired' && acq.verdict !== 'already_held') { rows[n] = { issue: n, outcome: 'stopped', stage: 'acquire', detail: acq.detail || acq.verdict }; return }

    if (readopt) {
      // The plan was settled before the PR existed: an owner answer does not apply on this path.
      const ro = await ask(agent(readoptPrompt(n), { label: `readopt-${n}`, phase: 'Deliver', model: 'sonnet', effort: 'low', schema: READOPT_SCHEMA }), `readopt-${n}`)
      if (ro === null || ro === undefined) { rows[n] = { issue: n, outcome: 'stopped', stage: 'readopt', detail: `readopt-${n} returned nothing` }; return }
      if (ro.ok === true) {
        if (!ro.head || !ro.branch || !ro.worktree || !Array.isArray(ro.acceptance) || !ro.acceptance.length) {
          rows[n] = { issue: n, outcome: 'stopped', stage: 'readopt', detail: 'readopt reply lacks head, branch, worktree or acceptance' }
          return
        }
        // No child: the slot goes back and the PR lands as it stands, through the same path as a ready child.
        leave()
        admitted = false
        READY[n] = { head: ro.head, branch: ro.branch, worktree: ro.worktree, acceptance: ro.acceptance, verify: [], tasks: [], cont: CONTS[n] }
        rows[n] = await enqueue(INT, () => land(n, READY[n]))
        return
      }
      if (ro.reason !== 'unaccepted') {
        rows[n] = { issue: n, outcome: 'stopped', stage: 'readopt', detail: ro.reason || 'other', ...(ro.detail ? { note: ro.detail } : {}) }
        return
      }
      // Unaccepted head (D13): the child's final review and verify re-run over the moved head, with the slot and claim kept.
      if (!CONTS[n]) {
        if (!(await chooseLane())) return
        rows[n] = { issue: n, outcome: 'eligible', lane: laneName }
      }
    }

    let r = null
    try {
      try { r = await workflow({ scriptPath: CHILD }, childArgs(n, laneName)) } catch (e) { r = null }
      if (r && r.stage === 'ineligible' && !terminalChild(r)) {
        // The direct lane rejected the issue: its cont would repeat the rejected attempt, so drop it and rerun once in the standard lane (setup re-adopts the worktree and the claim).
        delete CONTS[n]
        laneName = 'standard'
        rows[n] = { issue: n, outcome: 'eligible', lane: laneName }
        try { r = await workflow({ scriptPath: CHILD }, childArgs(n, laneName)) } catch (e) { r = null }
      }
      if (terminalChild(r)) trip(`child-${n}`)
    } finally {
      leave()
      admitted = false
    }

    if (r === null || r === undefined) { rows[n] = { issue: n, outcome: 'stopped', detail: `child-${n} returned nothing` }; return }
    if (r.cont) CONTS[n] = r.cont
    if (terminalChild(r)) { rows[n] = { issue: n, outcome: 'stopped', stage: r.stage, dead_agents: r.dead_agents }; return }
    if (r.stage === 'done') {
      // A re-adopted merged landing: the child closed it out (claim released, worktree and branch removed). End the landing markers the merge resolved.
      const ended = await ask(agent(`The landing of issue #${n} of ${SLUG} (the git repository at ${REPO}) is merged and closed out. End its landing owner-action markers, each alone and exactly: forge-claim owner-action end --repo ${SLUG} --issue ${n} --reason conflict and then forge-claim owner-action end --repo ${SLUG} --issue ${n} --reason needs-label. A verdict none is fine.
Return its verdict and any detail. Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `recover-end-${n}`, phase: 'Deliver', model: 'sonnet', effort: 'low', schema: ENDED_SCHEMA }), `recover-end-${n}`)
      if (ended === null || ended === undefined) { rows[n] = { issue: n, outcome: 'stopped', stage: 'recover-end', detail: `recover-end-${n} returned nothing`, ...(r.pr ? { pr: r.pr } : {}) }; return }
      // The hold step may close the issue (its once-run passed, or every row moved to a child issue): read the state it left, never the criterion kinds.
      const heldOpen = !(r.close_out && r.close_out.issue_state === 'CLOSED')
      rows[n] = { issue: n, outcome: heldOpen ? 'landed-held' : 'landed', ...(r.pr ? { pr: r.pr } : {}) }
      return
    }
    if (r.stage === 'ready') {
      READY[n] = r
      rows[n] = await enqueue(INT, () => land(n, r))
      return
    }
    if (r.stage === 'claimed') { rows[n] = { issue: n, outcome: 'claim-lost', by: r.by }; return }
    if (r.stage === 'plan' && Array.isArray(r.needs_user) && r.needs_user.length) {
      // D6, D12: only an unattended run posts the box prompt; a session-launched run hands the questions to its session, the claim stays held.
      let marker = null
      if (UNATTENDED) {
        const posted = await ask(agent(`The delivery of issue #${n} of ${SLUG} (the git repository at ${REPO}) needs the owner's answers. Post them as the decision box prompt, the claim stays held.
The questions, as JSON: ${JSON.stringify(r.needs_user)}
1. Make a fresh directory with mktemp -d and write exactly that JSON array to a file in it.
2. Run alone and exactly: forge-claim owner-action post --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason decision --questions-file <that file>
Return its verdict (posted, already_posted, or error on any other exit) and comment_id. Change nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `ask-${n}`, phase: 'Deliver', model: 'sonnet', effort: 'low', schema: ASK_SCHEMA }), `ask-${n}`)
        if (!posted || (posted.verdict !== 'posted' && posted.verdict !== 'already_posted')) {
          rows[n] = { issue: n, outcome: 'stopped', stage: 'plan', detail: `ask-${n} did not post the questions` }
          return
        }
        marker = posted.comment_id
      }
      rows[n] = { issue: n, outcome: 'questions', lane: laneName, questions: r.needs_user, marker }
      return
    }
    if (r.cont) {
      if (r.stage !== 'planned' && !postMerge(r) && !mergedReadopt(n, f)) {
        // A stop on an issue closed meanwhile: give the claim back and drop the cont; an open issue keeps both (#714).
        // A re-adopted merged landing is never settled, whatever stage it stopped at: its close-out is still owed (#714).
        const st = await ask(agent(`Issue #${n} of ${SLUG} (the git repository at ${REPO}) stopped with a continuation. Settle its claim.
1. Read ${UNSET}gh issue view ${n} --repo ${SLUG} --json state and return state (OPEN or CLOSED).
2. Only when state is CLOSED, run alone and exactly: forge-claim release --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason closed and return its verdict as release: released (exit 0), not_held (exit 3) when the claim is already gone, or error on any other exit; otherwise return release null. Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `settle-${n}`, phase: 'Deliver', model: 'sonnet', effort: 'low', schema: SETTLE_SCHEMA }), `settle-${n}`)
        if (st && st.state === 'CLOSED' && (st.release === 'released' || st.release === 'not_held')) {
          delete CONTS[n]
          rows[n] = { issue: n, outcome: 'closed', stage: r.stage, released: st.release === 'released' }
          return
        }
      }
      rows[n] = { issue: n, outcome: 'stopped', stage: r.stage }
      return
    }
    // A stop with nothing to resume: give the claim back.
    await ask(agent(`Issue #${n} of ${SLUG} (the git repository at ${REPO}) stopped without anything to resume. Release the batch claim.
Run alone and exactly: forge-claim release --repo ${SLUG} --issue ${n} --holder ${HOLDER} --reason skipped
Return its verdict and any detail. Run nothing else.
${RULES_FOR(REPO, f.branch)}`, { label: `release-${n}`, phase: 'Deliver', model: 'sonnet', effort: 'low', schema: RELEASE_SCHEMA }), `release-${n}`)
    rows[n] = { issue: n, outcome: 'stopped', stage: r.stage }
  } finally {
    if (admitted) leave()
  }
}
await parallel(toDeliver.map(n => async () => {
  try {
    await deliverOne(n)
  } catch (e) {
    rows[n] = { issue: n, outcome: 'stopped', detail: String((e && e.message) || e) }
  } finally {
    settle[n](rows[n] || { issue: n, outcome: 'stopped', detail: 'no result' })
  }
}))

// --- Result: one table, in ISSUES order ---
const table = ISSUES.map(n => rows[n] || { issue: n, outcome: 'stopped', detail: 'no result' })
// A cycle only the owner can break: relaunching it returns the same blocked rows, so it is an owner action, not an open issue.
const open = table.filter(r => !FINAL.includes(r.outcome) && !cycle.includes(r.issue)).map(r => r.issue)
const rowOf = n => table.find(r => r.issue === n)
const relaunchArgs = () => {
  const a = { repo_root: REPO, batch_id: BATCH, child_script: CHILD, issues: open }
  // An issue whose child asked again carries no answer at all: the old one answered the earlier questions, and the new prompt's own ticks are read by the child.
  const decisions = { ...(DECISIONS || {}) }
  for (const n of open) if (rowOf(n).outcome === 'questions') delete decisions[String(n)]
  if (DECISIONS !== undefined || Object.keys(decisions).length) a.decisions = decisions
  const conts = {}
  for (const n of open) if (CONTS[n]) conts[n] = CONTS[n]
  if (Object.keys(conts).length) a.conts = conts
  if (UNATTENDED) a.unattended = true
  return a
}
for (const r of table) log(`#${r.issue}: ${r.outcome}${r.detail ? ` (${r.detail})` : ''}`)
return {
  stage: breaker ? 'breaker' : 'done', batch_id: BATCH, table,
  questions: table.filter(r => r.outcome === 'questions').map(r => ({ issue: r.issue, questions: r.questions, marker: r.marker })),
  owner_actions: [...table.filter(r => r.outcome === 'questions' && r.marker !== null && r.marker !== undefined).map(r => ({ issue: r.issue, reason: 'decision', comment_id: r.marker })), ...table.filter(r => r.outcome === 'already-fixed').map(r => ({ issue: r.issue, reason: 'already-fixed', commit: r.commit })), ...cycle.map(n => ({ issue: n, reason: 'cycle' })), ...LAND_OA],
  relaunch: open.length ? relaunchArgs() : null,
  ...(breaker ? { breaker } : {}),
}
