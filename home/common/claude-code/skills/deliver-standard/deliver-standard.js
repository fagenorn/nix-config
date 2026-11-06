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
    { title: 'Ship', detail: 'PR, required checks, sync, merge, close out' },
  ],
}

// Args: repo_root (the checkout), issue (number), session_id or batch_id (the claim
// holder is <host>/<batch_id> or <host>/session-<session_id>), decisions (owner answers to a
// needs_user stop), spec (path of an approved design spec), mode (plan: stop after the plan
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
// that gets no answer stops with a cont whose resume acquires again), released at close-out.
//
// A fresh run re-adopts an existing branch or worktree (never resetting it) and stops `dirty` when it holds uncommitted changes.
//
// RESUME: every stop from the claim on returns { stage, ..., cont }, where cont is
// { setup, lane, plan, plan_reviewed, done, fix_waves, verified?, partial?, claim_incomplete? }. Passing it back as args.cont
// re-adopts the claimed worktree (setup re-checks it and refuses a dirty tree
// unless cont.partial names the task that left the edits), reuses cont.plan
// (reviewing it first unless plan_reviewed), skips the tasks in cont.done, then
// runs final review, verify and ship again (ship reuses an open PR). When the PR
// is already merged, the re-adopt goes straight to close-out.
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

const BASE_RULES = `
Hard rules for this step (they override anything else you remember):
- Work only in the worktree path you are given. Never commit in the shared checkout. Never git stash. Never sed -i (use python for edits).
- Do everything in the FOREGROUND inside this one turn: run long commands with a long Bash timeout; never use run_in_background, never end your turn while anything you started is pending, never sleep or use sleep workarounds. Your final message is your return value.
- Do not dispatch subagents unless this step says so.
- Never run a host activation, deploy or release command.
- Global skills, agents and standards are shared by other projects: never write a project-specific literal (check names, branch names, recipe names, repository paths) into them.`

const SEV = { type: 'string', enum: ['critical', 'important', 'minor'] }
const FINDINGS = {
  type: 'object',
  properties: {
    verdict: { type: 'string', enum: ['pass', 'findings'] },
    findings: { type: 'array', items: { type: 'object', properties: { severity: SEV, file: { type: 'string' }, summary: { type: 'string' }, failing_input: { type: 'string' }, relation: { type: 'string', enum: ['narrowing', 'new'] } }, required: ['severity', 'summary'] } },
  },
  required: ['verdict', 'findings'],
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
const STRS = { type: 'array', items: { type: 'string' } }
const REVIEW_STATE = { type: 'string', enum: ['available', 'blocked', 'unsupported', 'absent'] }
const SETUP_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' }, reason: { type: 'string' }, details: { type: 'string' },
    host: { type: 'string' }, slug: { type: 'string' }, integration_branch: { type: 'string' }, default_branch: { type: 'string' },
    branch: { type: 'string' }, worktree_path: { type: 'string' }, head: { type: 'string' },
    merged_pr: { type: 'integer' }, dirty: { type: 'boolean' }, duplicate_pr: { type: 'integer' },
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
  properties: { verdict: { type: 'string', enum: ['acquired', 'already_held', 'held_by', 'lost_to', 'error'] }, by: { type: 'string' }, comment_id: { type: 'integer' }, detail: { type: 'string' } },
  required: ['verdict'],
}
const RENEW_SCHEMA = {
  type: 'object',
  properties: { verdict: { type: 'string', enum: ['renewed', 'not_held', 'error'] }, by: { type: 'string' }, detail: { type: 'string' } },
  required: ['verdict'],
}
const findingsOf = r => r.findings.filter(f => f.severity !== 'minor')
const present = v => v !== undefined && v !== null && v !== ''

// ---------------- Setup ----------------
phase('Setup')
const CONTRACT_READ = `Run: hostname -s and return its output as host. Run: resolve-project resolve --repo-root ${REPO} . On refusal return ok=false, reason contract, and in details the resolver's error.code, repair_id and ordered violations exactly. From the snapshot return:
- slug: bindings.tracker.repo_slug; unset_env: bindings.tracker.credential_env.unset_before_invocation (run every gh command after unsetting exactly these names, nothing else).
- integration_branch and default_branch: bindings.vcs.integration_branch and bindings.vcs.default_branch; merge_strategy and delete_branch: bindings.vcs.merge.strategy and bindings.vcs.merge.delete_branch.
- review: the command ids at bindings.workflow.review.code and .plan (omit an absent one); review_state: for code and plan, the state of the capability review.code and review.plan (available, blocked or unsupported; absent if the capability is missing).
- knowledge: bindings.paths.standards, bindings.paths.hints and bindings.paths.rejections, each as given (empty when absent).
- verification: for each id in bindings.workflow.verification its bindings.commands argv, its cwd relative to project.root (. for the root), and any bindings.workflow.verification_conditions entry (when_changed globs, skip_reason).`
// Shared by the fresh setup and the incomplete-claim resume: the facts the worktree step chooses its command from.
const EXISTING_READ = (branch, path) => `Read what already exists for the delivery, and change nothing: never reset, clean, restore or stash, and never delete a branch or worktree. Return existing with local_branch (a local branch named ${branch} exists), remote_branch (origin/${branch} exists), worktree (the path ${path} exists and is on branch ${branch}), dirty (git -C ${path} status --porcelain is non-empty), status (that output, its first 40 lines) and head (git -C ${path} rev-parse HEAD, or the branch tip when there is no worktree). Omit existing when there is no such branch and no such path. Refuse with reason worktree-mismatch and the path when ${path} is on another branch or ${branch} is checked out at another path.`
const setup = await agent(CONT ? `You re-adopt issue #${ISSUE} of the git repository at ${REPO} for a resumed delivery. Earlier setup: ${JSON.stringify(CONT.setup)}.
1. ${CONTRACT_READ}
2. If a merged PR has head ${CONT.setup && CONT.setup.branch} (gh pr list --repo <slug> --state merged --head ${CONT.setup && CONT.setup.branch}), return ok=true with merged_pr set to its number; the worktree may already be gone.
3. Otherwise confirm: ${CONT.claim_incomplete ? `the issue is open (an earlier claim stopped part way; the next step finishes it)` : `the issue is open; the worktree ${CONT.setup && CONT.setup.worktree} exists and is on branch ${CONT.setup && CONT.setup.branch}${CONT.plan ? `; the plan directory ${CONT.setup && CONT.setup.plan_dir} exists` : ''}`}. If any fails, return ok=false with reason not-resumable and the evidence. An open PR whose head is that branch is expected and fine. Set dirty true if git -C <worktree> status --porcelain is non-empty. Return head: git -C <worktree> rev-parse HEAD (the full sha).
${CONT.claim_incomplete ? `4. After git -C ${REPO} fetch origin: ${EXISTING_READ(CONT.setup && CONT.setup.branch, CONT.setup && CONT.setup.worktree_path)} An earlier worktree step may have created the branch, the worktree or both before it failed, so report existing afresh.
5.` : '4.'} Return every contract field read fresh, branch as in the earlier setup. Change nothing.
${BASE_RULES}` : `You check issue #${ISSUE} of the git repository at ${REPO} before delivery. Change nothing in this step except one issue comment named below.
1. ${CONTRACT_READ}
2. Derive branch from bindings.vcs.branch_pattern for this issue (slug from the issue title), and worktree_path as <bindings.vcs.worktree.root resolved against project.root>/<bindings.vcs.worktree.prefix><branch>. Then gh issue view ${ISSUE} --repo <slug> --json state,labels,title and gh pr list --repo <slug> --state all --search ${ISSUE} --json number,state,headRefName. Refuse (ok=false) with reason closed, parked (label needs-verification or parked), duplicate (a merged PR referencing this issue, a possible duplicate delivery: set duplicate_pr to its number) or open-pr (an open PR referencing this issue whose head is not branch).
3. After git -C ${REPO} fetch origin, re-adopt instead of refusing when the work already exists. ${EXISTING_READ('<branch>', '<worktree_path>')}
4. Read the issue and the code at origin/<integration_branch>: if the issue no longer applies (already fixed or obsolete), comment the evidence on the issue and refuse with reason no-longer-applies.
5. Return ok=true with every field above.
${BASE_RULES}`, { label: 'setup', phase: 'Setup', model: 'sonnet', effort: 'low', schema: SETUP_SCHEMA })
if (!setup || !setup.ok) return { stage: 'setup', result: setup }
// A fresh run never closes out a merged PR: it is a possible duplicate delivery, for the owner to judge.
if (!CONT && setup.merged_pr) return { stage: 'setup', result: setup, duplicate: setup.merged_pr }
// No policy is defaulted: a field the contract read did not return stops the run (before any claim on a fresh run).
const missing = ['slug', 'integration_branch', 'default_branch', 'branch', 'merge_strategy', 'delete_branch', 'unset_env', 'verification']
  .concat(CONT ? [] : ['worktree_path'])  // a resume carries it in cont.setup
  .concat(CONT && CONT.setup && CONT.setup.holder ? [] : ['host'])  // a resume carries the holder in cont.setup
  .filter(f => !present(setup[f]))
// Each review capability needs an explicit state, and an available one its command id, or a review could vanish silently.
for (const k of ['code', 'plan']) {
  const st = setup.review_state && setup.review_state[k]
  if (!present(st)) missing.push(`review_state.${k}`)
  else if (st === 'available' && !(setup.review && present(setup.review[k]))) missing.push(`review.${k}`)
}
if (missing.length) return { stage: 'setup', result: setup, missing, ...(CONT ? { cont: CONT } : {}) }
if (CONT) Object.assign(setup, { worktree_path: CONT.setup.worktree_path, worktree: CONT.setup.worktree, base_sha: CONT.setup.base_sha, plan_dir: CONT.setup.plan_dir, ...(CONT.setup.holder ? { holder: CONT.setup.holder } : {}) })
setup.holder = (CONT && CONT.setup && CONT.setup.holder) || `${setup.host}/${HOLDER_ID}`
if (!HOLDER_RE.test(setup.holder)) return { stage: 'setup', result: setup, invalid: 'holder', holder: setup.holder, ...(CONT ? { cont: CONT } : {}) }

let plan = CONT && CONT.plan ? CONT.plan : null
let planReviewed = !!(CONT && CONT.plan && CONT.plan_reviewed)
const taskLog = CONT && CONT.done ? CONT.done.slice() : []
let claimIncomplete = !!(CONT && CONT.claim_incomplete)
// A partial task's edits stay claimed through any stop until that task is done.
let partial = CONT && CONT.partial !== undefined ? CONT.partial : undefined
// Fix waves already spent, carried through a resume; declared before stop() because early failures call it.
let fixWaves = (CONT && CONT.fix_waves) || 0
// The verified head and results of a ready stop; carried until a resume finds the head moved.
let verified = (CONT && CONT.verified) || null
const stop = (stage, extra) => ({ stage, ...extra, cont: { setup, lane: LANE, plan, plan_reviewed: planReviewed, done: taskLog, fix_waves: fixWaves, ...(verified ? { verified } : {}), ...(claimIncomplete ? { claim_incomplete: true } : {}), ...(partial !== undefined ? { partial } : {}) } })

const haltTask = (n, stage, extra) => { const s = stop(stage, extra); return { ...s, cont: { ...s.cont, partial: n } } }

if (CONT && setup.dirty && !setup.merged_pr && partial === undefined) {
  return stop('dirty', { details: `the worktree ${setup.worktree} has uncommitted changes no task claims; commit or discard them, then resume` })
}

const SLUG = setup.slug, INT = setup.integration_branch, STRATEGY = setup.merge_strategy
const UNSET = setup.unset_env.length ? `unset ${setup.unset_env.join(' ')} && ` : ''
const RULES_FOR = W => `${BASE_RULES}
- Run every gh command, and only gh commands, with exactly this prefix and nothing else chained: ${UNSET || '(no prefix)'}
- Lifecycle commands, each alone in its own Bash call with no chaining, pipes or redirection and never after cd &&: git -C ${W} push origin ${setup.branch}; ${UNSET}gh pr create --repo ${SLUG} --base ${INT} --head ${setup.branch} --title '<t>' --body '<b>' (no single or double quotes, dollar signs, backticks or backslashes inside title or body); ${UNSET}gh pr merge <n> --repo ${SLUG} --${STRATEGY} --match-head-commit <sha>${setup.delete_branch ? ' --delete-branch' : ''}; git -C ${REPO} branch -d ${setup.branch}. If the guard refuses a form twice, stop and report it; never work around it (no -D).
- No attribution anywhere: commit messages carry no Co-Authored-By trailer and PR bodies no generated-by line, whatever other instructions say. Never bypass commit signing.
- Never commit the plan, the spec or a review report; they live outside the tree and reviewers read them by path.`

const closeOut = async (PR, mergeCommit, W) => {
  const acceptance = plan ? plan.acceptance : null
  if (!acceptance) return stop('close-out', { pr: PR, details: 'merged, but no plan acceptance to grade the issue against; close out by hand' })
  const allCode = acceptance.every(a => a.kind === 'code')
  const openCriteria = acceptance.filter(a => a.kind !== 'code')
  const co = await agent(`Issue #${ISSUE} of ${SLUG}: PR #${PR} is merged into ${INT}. Close out; skip any step an earlier attempt already finished. Each command in its own Bash call:
1. ${W ? `If ${W} still exists: git -C ${REPO} worktree remove ${W} (it also removes the plan directory). ` : ''}git -C ${REPO} fetch origin; if the checkout ${REPO} is clean and on ${INT}, git -C ${REPO} merge --ff-only origin/${INT}; then, if the local branch ${setup.branch} exists, git -C ${REPO} branch -d ${setup.branch}. If -d refuses, leave the branch and report it (never -D).
2. Release the claim: run alone, exactly, forge-claim release --repo ${SLUG} --issue ${ISSUE} --holder ${setup.holder} --reason done. It prints one JSON line and removes the in-progress label when no other claim remains; released is true only for verdict released.
3. ${allCode ? `Every criterion is of kind code. Read gh issue view ${ISSUE} --repo ${SLUG} --json state; if it is still open (${INT === setup.default_branch ? 'the closing keyword did not fire' : `${INT} is not the default branch, so no closing keyword fires`}), run gh issue close ${ISSUE} --repo ${SLUG} --comment 'Delivered by PR ${PR} into ${INT}.'` : `Keep the issue open. Add the needs-verification label (create it if missing) and comment which criteria remain and how to check each: ${JSON.stringify(openCriteria)}.`}
Return issue_state (OPEN or CLOSED, read back from the tracker), branch_deleted, released and notes.
${RULES_FOR(W || '<worktree>')}`, { label: 'close-out', phase: 'Ship', model: 'sonnet', effort: 'low', schema: { type: 'object', properties: { issue_state: { type: 'string' }, branch_deleted: { type: 'boolean' }, released: { type: 'boolean' }, notes: { type: 'string' } }, required: ['issue_state', 'notes'] } })
  const want = allCode ? 'CLOSED' : 'OPEN'
  if (!co || co.issue_state !== want || co.released !== true) return stop('close-out', { pr: PR, close_out: co, expected_issue_state: want })
  return { stage: 'done', pr: PR, merged: true, merge_commit: mergeCommit, close_out: co, tasks: taskLog, acceptance, fix_waves: fixWaves }
}

if (CONT && setup.merged_pr) {
  phase('Ship')
  log(`PR #${setup.merged_pr} is already merged; closing out`)
  return await closeOut(setup.merged_pr, null, setup.worktree)
}

const RS = setup.review_state || {}
for (const k of ['plan', 'code']) {
  // Before a fresh claim nothing is held, so the stop carries no cont: fix the capability and start again.
  if (RS[k] === 'blocked') return CONT ? stop('review-blocked', { review: k }) : { stage: 'review-blocked', review: k }
}
const REVIEW_CODE = RS.code === 'available' && setup.review && setup.review.code ? setup.review.code : null
const REVIEW_PLAN = RS.plan === 'available' && setup.review && setup.review.plan ? setup.review.plan : null

if (CLAIMING) {
  // This run's own setup report, never an earlier run's: a failed worktree step may have left the branch or the worktree behind.
  const EX = setup.existing || null
  const acq = await agent(`Claim issue #${ISSUE} of ${SLUG} for delivery. Run, alone and exactly: forge-claim acquire --repo ${SLUG} --issue ${ISSUE} --holder ${setup.holder} --branch ${setup.branch}
It prints one JSON line and adds the in-progress label itself. Return its verdict (error, with detail, on exit 1 or 2), by and comment_id. Run nothing else and change nothing.
${RULES_FOR(setup.worktree_path)}`, { label: 'acquire', phase: 'Setup', model: 'sonnet', effort: 'low', schema: ACQUIRE_SCHEMA })
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
  const claim = await agent(`Set up the worktree for issue #${ISSUE} of ${SLUG}, each command in its own Bash call. An earlier attempt may have done part of this: skip a step already done (the worktree already at that path on branch ${setup.branch}; the plan directory already there).
1. ${WT} Never reset, clean, restore or stash anything in it.
2. plan_dir is <git -C ${setup.worktree_path} rev-parse --absolute-git-dir>/deliver-standard; create it. It lives in the worktree's git dir, outside the tree, so the plan never enters a commit.
Return ok, worktree (${setup.worktree_path}), base_sha (full sha) and plan_dir; on any failure ok=false with the reason and what you already did.
${RULES_FOR(setup.worktree_path)}`, { label: 'worktree', phase: 'Setup', model: 'sonnet', effort: 'low', schema: CLAIM_SCHEMA })
  // A claim that stopped part way may hold the claim or the worktree: its cont finishes it on resume.
  if (!claim || !claim.ok || !present(claim.worktree) || !present(claim.base_sha) || !present(claim.plan_dir)) { claimIncomplete = true; return stop('claim', { result: claim }) }
  Object.assign(setup, { worktree: claim.worktree, base_sha: claim.base_sha, plan_dir: claim.plan_dir })
  claimIncomplete = false
  if (EX && EX.dirty && partial === undefined) {
    return stop('dirty', { details: `the adopted worktree ${setup.worktree} has uncommitted changes, left as found; commit or discard them, then resume with cont: ${EX.status}`, status: EX.status })
  }
}

const W = setup.worktree
const RULES = RULES_FOR(W)
// Renews the claim before the step it guards. null = renewed; else the stop to return.
const renew = async (at, ph) => {
  const r = await agent(`Renew the claim on issue #${ISSUE} of ${SLUG}. Run, alone and exactly: forge-claim renew --repo ${SLUG} --issue ${ISSUE} --holder ${setup.holder} --branch ${setup.branch}
It prints one JSON line. Return its verdict (error, with detail, on exit 1 or 2), by and detail. Run nothing else and change nothing.
${RULES}`, { label: `renew-${at}`, phase: ph, model: 'sonnet', effort: 'low', schema: RENEW_SCHEMA })
  if (r && r.verdict === 'renewed') return null
  // An ended claim never comes back: no cont, a resume could only stop here again.
  if (r && r.verdict === 'not_held') return { stage: 'claim-lost', at, renew: r, details: 'the claim was ended (released, or honoured as stale by the owner); start again without cont: setup re-adopts the branch and acquire decides' }
  claimIncomplete = true
  return stop('claim-lost', { at, renew: r })
}
const RANGE = `origin/${INT}...HEAD`
const CTX = `Issue #${ISSUE} of ${SLUG}. Worktree: ${W} (branch ${setup.branch}, base ${setup.base_sha}, integration branch ${INT}). The branch's changes are git -C ${W} diff ${RANGE} (fetch origin first).`
const K = setup.knowledge || {}
const list = a => (a && a.length ? a.join(', ') : 'none')
const KNOW = `Ground the review in: ~/.agents/standards/the-bar.md and its stacks/ shards matching the changed file types (when present); the project's standards (${list(K.standards)}), only shards whose globs intersect the change; review hints (${list(K.hints)}); recorded rejections (${list(K.rejections)}): never raise a finding a rejection already settles.`
const implDone = i => !!(i && i.status === 'done' && present(i.commit) && present(i.start_head))
const span = i => `git -C ${W} diff ${i.start_head}..${i.commit}`
log(`claimed #${ISSUE}, worktree ${W}; review code=${REVIEW_CODE || RS.code || 'none'} plan=${REVIEW_PLAN || RS.plan || 'none'}`)

// ---------------- Plan ----------------
const PLAN_SCHEMA = {
  type: 'object',
  properties: {
    status: { type: 'string', enum: ['planned', 'needs_user'] },
    questions: STRS,
    plan_root: { type: 'string' },
    acceptance: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, text: { type: 'string' }, kind: { type: 'string', enum: ['code', 'evidence', 'human'] } }, required: ['id', 'text', 'kind'] } },
    tasks: { type: 'array', items: { type: 'object', properties: { n: { type: 'integer' }, title: { type: 'string' }, file: { type: 'string' }, risk: { type: 'string', enum: ['mechanical', 'low', 'standard', 'security'] } }, required: ['n', 'title', 'file', 'risk'] } },
  },
  required: ['status'],
}
const wellFormed = p => !!(p && p.status === 'planned' && present(p.plan_root) && Array.isArray(p.acceptance) && p.acceptance.length && Array.isArray(p.tasks) && p.tasks.length)
const SPEC = args.spec ? `\nThe approved design spec for this issue is ${args.spec}: plan from it, its decisions are binding, and never edit or commit it.` : ''
const planPrompt = extra => `${CTX}
Plan this issue. Read the issue (gh issue view ${ISSUE} --repo ${SLUG} --comments) and the code it touches.${SPEC} Use the writing-plans skill for the plan's form only: its file location, size checks and reports do not apply here. Write the plan to ${setup.plan_dir}/plan.md and one task file per task beside it (${setup.plan_dir}/task-<n>.md); never commit them and never write under the project's artifact directories. Do not build, prototype or run the change; confirming each task's failing test later is the implementers' job. If the issue needs a decision only the user can make (a preference, an irreversible or scope choice not settled by the issue, the spec, the repo's docs or ADRs), return status needs_user with concise questions and stop. Otherwise return status planned with plan_root ${setup.plan_dir}/plan.md, the issue's acceptance criteria (kind code if a test or command in this repo can show it, evidence if it needs a deploy, an activation or observation over time, human if only the user can judge), and the task list in execution order with each task's file and a risk: security for authentication, permission or command guards, secrets, CI/CD or deploy config, data migrations; mechanical or low for small contained edits; else standard.${args.decisions ? `\nThe owner has answered the open decisions for this issue; they are binding: ${args.decisions} Do not ask them again; record them as decisions in the plan.` : ''}${extra || ''}
${RULES}`
// A planner reply is either questions (the plan is dropped so a resume plans again with decisions) or a well-formed plan.
const takePlan = (p, label) => {
  if (p && p.status === 'needs_user') { plan = null; planReviewed = false; return stop('plan', { needs_user: p.questions }) }
  // A failed revision may have half-edited the files on disk, so the plan is dropped and a resume plans again.
  if (!wellFormed(p)) { plan = null; planReviewed = false; return stop('plan', { step: label, invalid: p }) }
  plan = p
  return null
}

const FOCUSED = 'Run only the tests that cover the files you changed; do not run the full test suite or the project\'s declared verification (that runs once later).'
let ACS = null, PLAN_REF = null
const planRefs = () => {
  ACS = JSON.stringify(plan.acceptance)
  PLAN_REF = plan.plan_root ? `Plan: ${plan.plan_root} (task files beside it).` : 'No plan: direct lane.'
}
let chunked = false
// A ready stop's verified head, unchanged and clean, needs no second review or verify.
const SKIP_REVIEW = !!(verified && plan && setup.head === verified.head && !setup.dirty && plan.tasks.every(t => taskLog.some(d => d.n === t.n)))
if (!SKIP_REVIEW) verified = null
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
    impl = await agent(`${CTX}
Deliver issue #${ISSUE} in the direct lane. Invoke the deliver-direct skill with the Skill tool to read it: it is the single source for this step. Its steps 1 and 2 are done by this program (the claim is held by ${setup.holder}; the worktree is ${W} on branch ${setup.branch}). Check its Eligibility first: if the issue fails it, change nothing and return status blocked with ineligible true and why. Otherwise follow its step 3 exactly and commit. Do not run its steps 4 to 7: review, verification, ship and close-out belong to this program. Return acceptance (the issue's criteria; kind code if a test or command in this repo can show it, evidence if it needs a deploy, an activation or observation over time, human if only the user can judge) and sensitive (true when the diff touches authentication or authorization, permission or command guards, secrets or credentials, CI/CD or deploy config, or data migrations). ${FOCUSED} ${IMPL_RETURN}${CONT && CONT.partial === 1 ? `
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
  if (!(SKIP_REVIEW || (!impl && present(d1.reviewed_head) && d1.reviewed_head === setup.head))) {
    let fix = null
    phase('Final review')
    const lost = await renew('final-review', 'Final review')
    if (lost) return lost
    const codexP = REVIEW_CODE ? agent(`${CTX}
${PLAN_REF} Acceptance criteria: ${ACS}.
Run the project's configured independent code review: the contract's workflow.review.code is the command ${REVIEW_CODE}. Use the codex-collaboration skill (invoke it with the Skill tool) to run that Codex diff review over the delivery range ${RANGE} in the worktree ${W}, with no review package; this step may dispatch the Codex reviewer that skill uses, and must wait for its result in this turn. Return Codex's Important or Critical findings as they are (correctness defects with a concrete failing input, unmet criteria) without adding your own review; verdict pass if none. If Codex cannot be run, return available false with the reason in raw_summary; never substitute your own review.
${RULES}`, { label: 'direct-codex', phase: 'Final review', model: 'sonnet', schema: CODEX }) : Promise.resolve(null)
    // The stored plan's risk, not this run's reply, picks the reviewer, so a resumed review keeps the implementer's choice.
    const lite = plan.tasks[0].risk !== 'security'
    const reviewPrompt = isLite => `${CTX}
${isLite ? 'lane: direct. ' : ''}Review the delivery diff git -C ${W} diff ${RANGE} for issue #${ISSUE} against its acceptance criteria ${ACS}. ${KNOW} Report Important or Critical correctness defects and unmet criteria only, each with a concrete failing input. ${isLite ? 'If the diff touches authentication or authorization, permission or command guards, secrets or credentials, CI/CD or deploy config, or data migrations, set escalate true. ' : ''}Do not edit anything.`
    let review = await agent(reviewPrompt(lite), { label: 'direct-review', phase: 'Final review', agentType: lite ? 'reviewer-lite' : 'reviewer', schema: DIRECT_FINDINGS })
    let passedBy = lite ? 'reviewer-lite' : 'reviewer'
    if (lite && review && review.escalate === true) {
      review = await agent(reviewPrompt(false), { label: 'direct-review-full', phase: 'Final review', agentType: 'reviewer', schema: FINDINGS })
      passedBy = 'reviewer'
    }
    const codexR = await codexP
    if (!review) return stop('direct-review', { review: null })
    if (REVIEW_CODE && (!codexR || !codexR.available)) return stop('codex-unavailable', { step: 'code', codex: codexR })
    const findings = findingsOf(review).concat(REVIEW_CODE ? findingsOf(codexR).map(f => ({ ...f, source: 'codex' })) : [])
    if (REVIEW_CODE) log(`codex review: ${findingsOf(codexR).length} blocking findings`)
    if (findings.length) {
      log(`direct review: ${findings.length} blocking findings, one fix round`)
      fix = await agent(`${CTX}\n${PLAN_REF} Fix these review findings in the worktree, with a regression test for each real defect, then commit: ${JSON.stringify(findings)}. If a finding is wrong, say so in notes with evidence instead of changing code. ${FOCUSED} ${IMPL_RETURN}\n${RULES}`, { label: 'direct-fix', phase: 'Final review', agentType: 'implementer', model: 'sonnet', schema: IMPL })
      if (!implDone(fix)) return stop('direct-fix', { fix })
      const rereview = await agent(`${CTX}
Re-review only these previously reported findings against the fix: ${span(fix)}; the implementer's notes: ${fix.notes}. Findings: ${JSON.stringify(findings)}. Report any finding still unresolved and any new Important or Critical defect the fix introduced.`, { label: 'direct-rereview', phase: 'Final review', agentType: 'reviewer-lite', schema: FINDINGS })
      if (!rereview || findingsOf(rereview).length) return stop('direct-review', { review: rereview, findings })
      passedBy = 'reviewer-lite'
    }
    Object.assign(d1, { reviewed_head: fix ? fix.commit : reviewHead, review_rounds: fix ? 1 : 0, reviewer: passedBy })
  }
} else {
phase('Plan')
if (!plan || !planReviewed) {
  const lost = await renew('plan', 'Plan')
  if (lost) return lost
}
if (!plan) {
  const halted = takePlan(await agent(planPrompt(), { label: 'plan', phase: 'Plan', schema: PLAN_SCHEMA }), 'plan')
  if (halted) return halted
}
if (!planReviewed) {
  const ACS0 = JSON.stringify(plan.acceptance)
  const planCodexP = REVIEW_PLAN ? agent(`${CTX}
Plan: ${plan.plan_root} (task files beside it). Acceptance criteria: ${ACS0}.${SPEC}
Run the project's configured independent plan review: the contract's workflow.review.plan is the command ${REVIEW_PLAN}. Use the codex-collaboration skill (invoke it with the Skill tool) to run that Codex plan review over the plan at that path against issue #${ISSUE} in the worktree ${W}; this step may dispatch the Codex reviewer that skill uses, and must wait for its result in this turn. Return Codex's Important or Critical findings as they are without adding your own review; verdict pass if none. If Codex cannot be run, return available false with the reason in raw_summary; never substitute your own review.
${RULES}`, { label: 'plan-codex', phase: 'Plan', model: 'sonnet', schema: CODEX }) : Promise.resolve(null)
  const planReviewClaude = await agent(`${CTX}
Review the implementation plan at ${plan.plan_root} (and its task files) against issue #${ISSUE} (gh issue view ${ISSUE} --repo ${SLUG}).${SPEC} ${KNOW} Report only Important or Critical defects: an acceptance criterion with no task, a task whose test cannot fail, wrong or missing interfaces, a design choice that breaks the project's documented conventions, or a project-specific literal written into global skills or agents. No style notes. Do not edit anything.`, { label: 'plan-review', phase: 'Plan', agentType: 'reviewer', schema: FINDINGS })
  const planCodexR = await planCodexP
  if (!planReviewClaude) return stop('plan-review', { details: 'the plan reviewer returned nothing' })
  let planFindings = findingsOf(planReviewClaude)
  if (REVIEW_PLAN) {
    if (!planCodexR || !planCodexR.available) return stop('codex-unavailable', { step: 'plan', codex: planCodexR })
    planFindings = planFindings.concat(findingsOf(planCodexR).map(f => ({ ...f, source: 'codex' })))
    log(`codex plan review: ${findingsOf(planCodexR).length} blocking findings`)
  }
  if (planFindings.length) {
    log(`plan review: ${planFindings.length} blocking findings, revising once`)
    const revised = await agent(planPrompt(`\nA reviewer found these defects in your plan at ${plan.plan_root}; fix them in place and return the full result again: ${JSON.stringify(planFindings)}`), { label: 'plan-revise', phase: 'Plan', schema: PLAN_SCHEMA })
    const halted = takePlan(revised, 'plan-revise')
    if (halted) return { ...halted, findings: planFindings }
  }
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
  const start = `${CTX}\n${PLAN_REF}`
  const halt = (stage, extra) => haltTask(t.n, stage, extra)
  let impl = await agent(`${start}
Implement task ${t.n} (${t.title}) exactly as its task file ${t.file} specifies: write the failing test first and see it fail, implement, see it pass, run the task's focused test commands, then for each new test temporarily remove the code it pins and confirm it fails, restore, and commit only this task's files in the worktree. ${FOCUSED} ${IMPL_RETURN} Return status blocked with notes if the task file is wrong or impossible.${CONT && CONT.partial === t.n ? `
An earlier attempt at this task was cut off and may have left uncommitted edits or commits in the worktree (git -C ${W} status, git -C ${W} diff and git -C ${W} log ${RANGE}). Inspect them: keep what matches the task file, finish or redo the rest, and make sure the failing-test-first and mutation checks still hold for the final result; start_head is the head before this task's first commit.` : ''}
${RULES}`, { label: `impl-${t.n}`, phase: 'Tasks', agentType: 'implementer', model: 'sonnet', schema: IMPL })
  if (!implDone(impl)) return halt('task', { task: t, impl })
  const taskSpan = span(impl)
  const reviewer = (t.risk === 'mechanical' || t.risk === 'low') ? 'reviewer-lite' : 'reviewer'
  // reviewer-lite first-passes only a task whose declared lane is mechanical or low (its lane verification mode).
  let review = await agent(`${start}
${reviewer === 'reviewer-lite' ? `lane: ${t.risk}. ` : ''}Review the diff of task ${t.n} only: ${taskSpan} (and the task file ${t.file} as its contract). ${KNOW} Report Important or Critical correctness defects and unmet task requirements only, each with a concrete failing input. No style notes. Do not edit anything.`, { label: `review-${t.n}`, phase: 'Tasks', agentType: reviewer, schema: FINDINGS })
  if (!review) return halt('task-review', { task: t, review: null })
  let rounds = 0
  while (findingsOf(review).length && rounds < 2) {
    rounds++
    const fix = await agent(`${start}
Fix these review findings for task ${t.n} (${t.file}) in the worktree, with a regression test for each real defect, then commit: ${JSON.stringify(findingsOf(review))}. If a finding is wrong, say so in notes with evidence instead of changing code. ${FOCUSED} ${IMPL_RETURN}
${RULES}`, { label: `fix-${t.n}-${rounds}`, phase: 'Tasks', agentType: 'implementer', model: 'sonnet', schema: IMPL })
    if (!implDone(fix)) return halt('task-fix', { task: t, impl: fix })
    impl = fix
    review = await agent(`${start}
Re-review only these previously reported findings for task ${t.n} against the fix: ${span(fix)}; the implementer's notes: ${fix.notes}. Findings: ${JSON.stringify(findingsOf(review))}. Report any finding still unresolved and any new Important or Critical defect the fix introduced.`, { label: `rereview-${t.n}-${rounds}`, phase: 'Tasks', agentType: 'reviewer-lite', schema: FINDINGS })
    if (!review) return halt('task-review', { task: t, review: null })
  }
  if (findingsOf(review).length) return halt('task-review', { task: t, review })
  taskLog.push({ n: t.n, commit: impl.commit, review_rounds: rounds, reviewer })
  if (partial === t.n) partial = undefined
}

// ---------------- Final review ----------------
phase('Final review')
const groups = []
const PER = 3
for (let i = 0; i < plan.tasks.length; i += PER) groups.push(plan.tasks.slice(i, i + PER))
chunked = groups.length > 1
if (!SKIP_REVIEW) {
{
  const lost = await renew('final-review', 'Final review')
  if (lost) return lost
}
const codexP = REVIEW_CODE ? agent(`${CTX}
${PLAN_REF} Acceptance criteria: ${ACS}.
Run the project's configured independent code review: the contract's workflow.review.code is the command ${REVIEW_CODE}. Use the codex-collaboration skill (invoke it with the Skill tool) to run that Codex diff review over the delivery range ${RANGE} in the worktree ${W}, with no review package; this step may dispatch the Codex reviewer that skill uses, and must wait for its result in this turn. Return Codex's Important or Critical findings as they are (correctness defects with a concrete failing input, unmet criteria) without adding your own review; verdict pass if none. If Codex cannot be run, return available false with the reason in raw_summary; never substitute your own review.
${RULES}`, { label: 'final-codex', phase: 'Final review', model: 'sonnet', schema: CODEX }) : Promise.resolve(null)
const finals = await parallel(groups.map((g, gi) => () => agent(`${CTX}
${PLAN_REF} Acceptance criteria: ${ACS}.
Final review${chunked ? ` of chunk ${gi + 1}/${groups.length}: tasks ${g.map(t => t.n).join(', ')} only (their files: ${g.map(t => t.file).join(', ')}); grade only these tasks` : ' of the whole delivery'}: git -C ${W} diff ${RANGE}${chunked ? ' restricted to the paths these tasks own' : ''}. ${KNOW} Two axes: correctness (real defects with a concrete failing input) and conformance (each task and each acceptance criterion of kind code is actually met, with the test or command that shows it). Report Important or Critical findings only. Do not edit anything.`, { label: `final-${gi + 1}`, phase: 'Final review', agentType: 'reviewer', schema: FINDINGS })))
const codexR = await codexP
if (finals.some(r => !r)) return stop('final-review', { details: 'a final reviewer returned nothing', finals })
let finalFindings = finals.flatMap(findingsOf)
if (REVIEW_CODE) {
  if (!codexR || !codexR.available) return stop('codex-unavailable', { step: 'code', codex: codexR })
  finalFindings = finalFindings.concat(findingsOf(codexR).map(f => ({ ...f, source: 'codex' })))
  log(`codex review: ${findingsOf(codexR).length} blocking findings`)
}
if (chunked) {
  const integ = await agent(`${CTX}
${PLAN_REF} Integration review. The delivery was reviewed in ${groups.length} chunks by task; their verdicts: ${JSON.stringify(finals)}. Read the full changed-file list (git -C ${W} diff --stat ${RANGE}) and the head tree as needed. ${KNOW} Check the interfaces between chunks and grade every acceptance criterion: ${ACS}. Report Important or Critical findings only.`, { label: 'final-integration', phase: 'Final review', agentType: 'reviewer', schema: FINDINGS })
  if (!integ) return stop('final-review', { details: 'the integration reviewer returned nothing' })
  finalFindings = finalFindings.concat(findingsOf(integ))
}
if (finalFindings.length) {
  // At most two waves: the second runs only when the first re-review's findings all narrow the first round (same kind of defect on another path); a new kind stops.
  let waveFindings = finalFindings
  for (let k = 1; k <= 2; k++) {
    const fwLabel = k === 1 ? 'fix-wave' : `fix-wave-${k}`
    const rvLabel = k === 1 ? 'fix-wave-review' : `fix-wave-review-${k}`
    log(`final review: ${waveFindings.length} blocking findings, fix wave ${k}`)
    fixWaves++
    const fw = await agent(`${CTX}\n${PLAN_REF} Fix these final-review findings, each real defect with a regression test, then commit: ${JSON.stringify(waveFindings)}.${k === 2 ? ` They narrow these first-round findings: ${JSON.stringify(finalFindings)}.` : ''} If a finding is wrong, explain with evidence in notes. ${FOCUSED} ${IMPL_RETURN}\n${RULES}`, { label: fwLabel, phase: 'Final review', agentType: 'implementer', model: 'sonnet', schema: IMPL })
    if (!implDone(fw)) return stop('fix-wave', { fw, finalFindings: waveFindings, fix_waves: fixWaves })
    const rv = await agent(`${CTX}\nRe-review these final-review findings against the fix (${span(fw)}); implementer notes: ${fw.notes}. Findings: ${JSON.stringify(waveFindings)}. Report any still unresolved and any new Important or Critical defect. For each finding you still report, set relation: narrowing when it is the same kind of defect as one of the findings above reached on another path, input or call site; new when it is a different kind. Unsure is new.`, { label: rvLabel, phase: 'Final review', agentType: 'reviewer', schema: FINDINGS })
    if (!rv) return stop('fix-wave-review', { rv, fix_waves: fixWaves })
    const next = findingsOf(rv)
    if (!next.length) break
    if (k === 2 || next.some(f => f.relation !== 'narrowing')) return stop('fix-wave-review', { rv, fix_waves: fixWaves })
    waveFindings = next
  }
}
}
}

// ---------------- Verify ----------------
phase('Verify')
const VERIFY = {
  type: 'object',
  properties: { head: { type: 'string' }, clean: { type: 'boolean' }, results: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, status: { type: 'string', enum: ['pass', 'fail', 'skipped'] }, summary: { type: 'string' } }, required: ['id', 'status', 'summary'] } } },
  required: ['head', 'clean', 'results'],
}
const verifyPrompt = `${CTX}
Run the project's declared verification once on the worktree head, in the foreground, each command with a Bash timeout of up to 60 minutes: ${JSON.stringify(setup.verification)}. Run each argv with <worktree>/<its cwd> as working directory. If an entry has when_changed globs and none of the files changed (git -C ${W} diff --no-renames --name-only ${RANGE}, so a rename lists both paths) match, mark it skipped with its skip_reason. Return head (git -C ${W} rev-parse HEAD, the full sha), clean (git -C ${W} status --porcelain is empty, checked before and after the runs) and one result per id; for failures, summarize the failing tests or errors precisely. Do not change any file.
${RULES}`
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
let verify = SKIP_REVIEW ? { head: verified.head, clean: true, results: verified.results } : null
if (!SKIP_REVIEW) {
{
  const lost = await renew('verify', 'Verify')
  if (lost) return lost
}
verify = await agent(verifyPrompt, { label: 'verify', phase: 'Verify', model: 'sonnet', effort: 'low', schema: VERIFY })
let vRounds = 0
while (verify && verifyProblems(verify).length && vRounds < 2) {
  vRounds++
  const fix = await agent(`${CTX}\n${PLAN_REF} The project's verification failed: ${JSON.stringify(verifyProblems(verify))}. Find the cause in this branch's changes (git -C ${W} diff ${RANGE}), fix it with the smallest change, commit. Never weaken, skip or delete a test to make it pass. ${FOCUSED} ${IMPL_RETURN}\n${RULES}`, { label: `verify-fix-${vRounds}`, phase: 'Verify', agentType: 'implementer', model: 'sonnet', schema: IMPL })
  if (!implDone(fix)) return stop('verify-fix', { verify, fix })
  const fr = await agent(`${CTX}\nReview this verification fix: ${span(fix)}; the failure it answers: ${JSON.stringify(verifyProblems(verify))}; implementer notes: ${fix.notes}. Report Important or Critical defects only, above all a weakened, skipped or deleted test or check.`, { label: `verify-fix-review-${vRounds}`, phase: 'Verify', agentType: 'reviewer', schema: FINDINGS })
  if (!fr || findingsOf(fr).length) return stop('verify-fix-review', { review: fr })
  verify = await agent(verifyPrompt, { label: `verify-${vRounds + 1}`, phase: 'Verify', model: 'sonnet', effort: 'low', schema: VERIFY })
}
}
if (verifyProblems(verify).length) return stop('verify', { verify, problems: verifyProblems(verify) })
if (MODE === 'ready') {
  verified = { head: verify.head, results: verify.results }
  return stop('ready', { head: verify.head, branch: setup.branch, worktree: W, verify: verify.results, tasks: taskLog, acceptance: plan.acceptance, fix_waves: fixWaves })
}

// ---------------- Ship ----------------
phase('Ship')
const allCode = plan.acceptance.every(a => a.kind === 'code')
const closesLine = allCode && INT === setup.default_branch ? `Closes #${ISSUE}` : `Refs #${ISSUE}`
{
  const lost = await renew('ship', 'Ship')
  if (lost) return lost
}
const prR = await agent(`${CTX}
Open the pull request for this branch. Push the branch (git -C ${W} push origin ${setup.branch}). If an open PR with head ${setup.branch} already exists (a resumed delivery), reuse it; else open one against ${INT}. Title: a short summary of the issue. Body, plain prose, no single or double quotes, dollar signs, backticks or backslashes: sections Why, What changes, Acceptance (a table with one row per criterion: id, criterion, kind, and the test or command that shows it; criteria ${ACS}), Evidence (verification ${JSON.stringify(verify.results)}; ${taskLog.length} tasks reviewed; ${LANE === 'direct' ? 'direct-lane review' : 'final review ' + (chunked ? 'chunked' : 'whole')}${REVIEW_CODE ? ' plus the configured independent review' : ''}), Merge danger; then the line ${closesLine} as the last line, with no attribution or generated-by line. Never attach or link the plan or the spec. Return pr (number) and head (full sha of the pushed head).
${RULES}`, { label: 'pr', phase: 'Ship', model: 'sonnet', schema: { type: 'object', properties: { pr: { type: 'integer' }, head: { type: 'string' }, notes: { type: 'string' } }, required: ['pr', 'head'] } })
if (!prR || !prR.pr) return stop('pr', { result: prR })
// The shipped head must be the verified head; after a sync, the reviewed merge commit.
if (prR.head !== verify.head) return stop('head-moved', { pr: prR.pr, expected: verify.head, head: prR.head })
const PR = prR.pr

const CHECKS = { type: 'object', properties: { state: { type: 'string', enum: ['passed', 'failed', 'behind'] }, head: { type: 'string' }, required: STRS, details: { type: 'string' } }, required: ['state', 'head'] }
const SYNC = { type: 'object', properties: { status: { type: 'string', enum: ['done', 'blocked'] }, conflicted: { type: 'boolean' }, merge_commit: { type: 'string' }, resolved_files: STRS, tests: STRS, notes: { type: 'string' } }, required: ['status', 'conflicted', 'notes'] }
let head = prR.head
let expected = verify.head
let syncs = 0
for (;;) {
  const lost = await renew(`checks-${syncs + 1}`, 'Ship')
  if (lost) return lost
  const ck = await agent(`${CTX}
Wait for PR #${PR} to be mergeable. 1. git -C ${W} fetch origin; if the local branch is ahead of origin/${setup.branch}, push it. head is git -C ${W} rev-parse HEAD (full sha). 2. If origin/${INT} is not an ancestor of HEAD (git -C ${W} merge-base --is-ancestor origin/${INT} HEAD fails), return state behind at once. 3. Otherwise wait in this turn for the required checks on head: take the required check names from gh api repos/${SLUG}/rules/branches/${INT} (its required_status_checks rules) or else classic branch protection; if neither answers, every check is required. gh pr checks ${PR} --repo ${SLUG} --watch (Bash timeout up to 60 minutes; rerun while any is pending) can return early, and its --required list can be partial: never treat a partial list as green. Return passed only when every required name has passed on head, failed with the failing names and why when any required check failed, and the required names you used.
${RULES}`, { label: `checks-${syncs + 1}`, phase: 'Ship', model: 'sonnet', effort: 'low', schema: CHECKS })
  if (!ck) return stop('checks', { pr: PR, checks: null })
  if (ck.state === 'failed') return stop('checks', { pr: PR, checks: ck })
  if (ck.head !== expected) return stop('head-moved', { pr: PR, expected, head: ck.head })
  head = ck.head
  if (ck.state === 'passed') break
  if (syncs >= 2) return stop('sync-contention', { pr: PR, syncs })
  syncs++
  const sy = await agent(`${CTX}
The branch is behind ${INT}. Merge origin/${INT} into it in the worktree (git -C ${W} merge origin/${INT}). If it conflicts, resolve each conflict keeping both sides' intent, commit the merge, and run only the tests covering the files the resolution touched. Do not push. Return conflicted, merge_commit (full sha), resolved_files and the tests you ran; status blocked with notes if you cannot resolve it safely.
${RULES}`, { label: `sync-${syncs}`, phase: 'Ship', agentType: 'implementer', model: 'sonnet', schema: SYNC })
  if (!sy || sy.status !== 'done' || !present(sy.merge_commit)) return stop('sync', { pr: PR, sync: sy })
  expected = sy.merge_commit
  if (sy.conflicted) {
    const sr = await agent(`${CTX}
Review the conflict resolution in merge commit ${sy.merge_commit}: git -C ${W} show --cc ${sy.merge_commit} and the resolved files ${JSON.stringify(sy.resolved_files || [])}; the tests run: ${JSON.stringify(sy.tests || [])}. Report Important or Critical defects only: a dropped change from either side, a broken merge of intent, a resolved file whose tests were not run.`, { label: `sync-review-${syncs}`, phase: 'Ship', agentType: 'reviewer', schema: FINDINGS })
    if (!sr || findingsOf(sr).length) return stop('sync-review', { pr: PR, review: sr })
  }
}

{
  const lost = await renew('merge', 'Ship')
  if (lost) return lost
}
const mg = await agent(`${CTX}
Merge PR #${PR}. Run, alone and exactly: ${UNSET}gh pr merge ${PR} --repo ${SLUG} --${STRATEGY} --match-head-commit ${head}${setup.delete_branch ? ' --delete-branch' : ''}
Then read gh pr view ${PR} --repo ${SLUG} --json state,mergeCommit: merged is true only when state is MERGED. Never retry with another form; on a guard refusal or a head mismatch return merged false with the exact message.
${RULES}`, { label: 'merge', phase: 'Ship', model: 'sonnet', effort: 'low', schema: { type: 'object', properties: { merged: { type: 'boolean' }, merge_commit: { type: 'string' }, notes: { type: 'string' } }, required: ['merged', 'notes'] } })
if (!mg || !mg.merged) return stop('merge', { pr: PR, merge: mg })

const finished = await closeOut(PR, mg.merge_commit, W)
return finished.stage === 'done' ? { ...finished, chunked, syncs, verify: verify.results } : finished
