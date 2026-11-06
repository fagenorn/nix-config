export const meta = {
  name: 'deliver-standard',
  description: 'Deliver one standard-lane tracker issue: plan, implement and review each task, final review, verify once, ship',
  whenToUse: 'A standard-lane issue the user asked to deliver with this program; args {repo_root, issue, decisions?, spec?, cont?}',
  phases: [
    { title: 'Setup', detail: 'resolve contract, pre-flight, claim, worktree' },
    { title: 'Plan', detail: 'plan outside the tree, then review' },
    { title: 'Tasks', detail: 'implement and review each task' },
    { title: 'Final review', detail: 'whole-range review and fix wave' },
    { title: 'Verify', detail: 'declared verification once, after the fix wave' },
    { title: 'Ship', detail: 'PR, required checks, sync, merge, close out' },
  ],
}

// Args: repo_root (the checkout), issue (number), decisions (owner answers to a
// needs_user stop), spec (path of an approved design spec), cont (the `cont`
// object of an earlier stop, passed back unchanged to resume; see RESUME below).
// Every policy value comes from the project contract that setup resolves; this
// file carries no project literal.
//
// RESUME: every stop returns { stage, ..., cont }. Passing that cont back as
// args.cont re-adopts the claimed worktree (setup re-checks it), skips planning
// and plan review when cont.plan is present, skips the tasks in cont.done,
// tells the implementer of cont.partial to inspect the uncommitted edits, then
// runs final review, verify and ship again (ship reuses an open PR).

const REPO = args && args.repo_root
const ISSUE = args && args.issue
if (!REPO || !ISSUE) return { stage: 'args', error: 'repo_root and issue are required' }
const CONT = args.cont || null

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
    findings: { type: 'array', items: { type: 'object', properties: { severity: SEV, file: { type: 'string' }, summary: { type: 'string' }, failing_input: { type: 'string' } }, required: ['severity', 'summary'] } },
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
  properties: { status: { type: 'string', enum: ['done', 'blocked'] }, commit: { type: 'string' }, tests: { type: 'array', items: { type: 'string' } }, mutation_checked: { type: 'boolean' }, notes: { type: 'string' } },
  required: ['status', 'notes'],
}
const STRS = { type: 'array', items: { type: 'string' } }
const REVIEW_STATE = { type: 'string', enum: ['available', 'blocked', 'unsupported', 'absent'] }
const SETUP_SCHEMA = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' }, reason: { type: 'string' }, details: { type: 'string' },
    slug: { type: 'string' }, integration_branch: { type: 'string' }, default_branch: { type: 'string' },
    branch: { type: 'string' }, worktree: { type: 'string' }, base_sha: { type: 'string' }, plan_dir: { type: 'string' },
    dirty: { type: 'boolean' },
    co_authored_by: { type: 'boolean' }, unset_env: STRS,
    merge_strategy: { type: 'string' }, delete_branch: { type: 'boolean' },
    review: { type: 'object', properties: { code: { type: 'string' }, plan: { type: 'string' } } },
    review_state: { type: 'object', properties: { code: REVIEW_STATE, plan: REVIEW_STATE } },
    knowledge: { type: 'object', properties: { standards: STRS, hints: STRS, rejections: STRS } },
    verification: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, argv: STRS, when_changed: STRS, skip_reason: { type: 'string' } }, required: ['id', 'argv'] } },
  },
  required: ['ok'],
}
const blocking = r => (r && r.findings ? r.findings.filter(f => f.severity !== 'minor') : [{ severity: 'critical', summary: 'reviewer returned nothing' }])

// ---------------- Setup ----------------
phase('Setup')
const CONTRACT_READ = `Run: resolve-project resolve --repo-root ${REPO} . On refusal return ok=false, reason contract, and in details the resolver's error.code, repair_id and ordered violations exactly. From the snapshot return:
- slug: bindings.tracker.repo_slug; unset_env: bindings.tracker.credential_env.unset_before_invocation (run every gh command after unsetting exactly these names, nothing else).
- integration_branch and default_branch: bindings.vcs.integration_branch and bindings.vcs.default_branch; co_authored_by: bindings.vcs.commit.co_authored_by; merge_strategy and delete_branch: bindings.vcs.merge.strategy and bindings.vcs.merge.delete_branch.
- review: the command ids at bindings.workflow.review.code and .plan (omit an absent one); review_state: for code and plan, the state of the capability review.code and review.plan (available, blocked or unsupported; absent if the capability is missing).
- knowledge: bindings.paths.standards, bindings.paths.hints and bindings.paths.rejections, each as given (empty when absent).
- verification: for each id in bindings.workflow.verification its bindings.commands argv and any bindings.workflow.verification_conditions entry (when_changed globs, skip_reason).`
const setup = await agent(CONT ? `You re-adopt issue #${ISSUE} of the git repository at ${REPO} for a resumed delivery. Earlier setup: ${JSON.stringify(CONT.setup)}.
1. ${CONTRACT_READ}
2. Confirm: the issue is open and carries the in-progress label; no merged PR delivers it (gh pr list --repo <slug> --state merged --search ${ISSUE}); the worktree ${CONT.setup && CONT.setup.worktree} exists and is on branch ${CONT.setup && CONT.setup.branch}; ${CONT.plan ? `the plan directory ${CONT.setup && CONT.setup.plan_dir} exists.` : 'nothing else.'} If any fails, return ok=false with reason not-resumable (or already-merged) and the evidence. An open PR whose head is that branch is expected and fine.
3. Return ok=true with every contract field read fresh, worktree, branch, base_sha and plan_dir as in the earlier setup, and dirty true if git -C <worktree> status --porcelain is non-empty. Change nothing.
${BASE_RULES}` : `You prepare issue #${ISSUE} of the git repository at ${REPO} for delivery.
1. ${CONTRACT_READ}
2. Pre-flight, changing nothing yet: gh issue view ${ISSUE} --repo <slug> --json state,labels,assignees,title and gh pr list --repo <slug> --state all --search ${ISSUE}. Refuse (ok=false) with reason closed, claimed (assignee, or label in-progress, needs-verification or parked), open-pr or already-merged (a merged PR that delivers this issue). Derive branch from bindings.vcs.branch_pattern for this issue (slug from the issue title), and the worktree path <bindings.vcs.worktree.root resolved against project.root>/<bindings.vcs.worktree.prefix><branch>. After git -C ${REPO} fetch origin, refuse with reason existing-branch if a local or remote branch named branch or <prefix><branch> exists or the worktree path exists (the caller resumes with cont or cleans up). Then read the issue and the code at origin/<integration_branch>: if the issue no longer applies (already fixed or obsolete), comment the evidence on the issue and refuse with reason no-longer-applies.
3. Claim: add the in-progress label (create it if missing: gh label create in-progress --repo <slug> --description 'Being delivered by an agent').
4. git -C ${REPO} worktree add --no-track -b <branch> <worktree path> origin/<integration_branch>. base_sha is the origin/<integration_branch> sha you branched from. plan_dir is <git -C <worktree> rev-parse --absolute-git-dir>/deliver-standard; create it. It lives in the worktree's git dir, outside the tree, so the plan never enters a commit.
${BASE_RULES}`, { label: 'setup', phase: 'Setup', model: 'sonnet', effort: 'low', schema: SETUP_SCHEMA })
if (!setup || !setup.ok) return { stage: 'setup', result: setup }
// No policy is defaulted: a field the contract read did not return stops the run.
const missing = ['slug', 'integration_branch', 'default_branch', 'branch', 'worktree', 'base_sha', 'plan_dir', 'merge_strategy', 'co_authored_by', 'delete_branch', 'unset_env', 'verification']
  .filter(f => setup[f] === undefined || setup[f] === null || setup[f] === '')
if (missing.length) return { stage: 'setup', result: setup, missing }

let plan = CONT && CONT.plan ? CONT.plan : null
const taskLog = CONT && CONT.done ? CONT.done.slice() : []
const stop = (stage, extra) => ({ stage, ...extra, cont: { setup, plan, done: taskLog } })

const RS = setup.review_state || {}
for (const k of ['plan', 'code']) {
  if (RS[k] === 'blocked') return stop('review-blocked', { review: k })
}
const REVIEW_CODE = RS.code === 'available' && setup.review && setup.review.code ? setup.review.code : null
const REVIEW_PLAN = RS.plan === 'available' && setup.review && setup.review.plan ? setup.review.plan : null

const W = setup.worktree, SLUG = setup.slug, INT = setup.integration_branch
const UNSET = setup.unset_env && setup.unset_env.length ? `unset ${setup.unset_env.join(' ')} && ` : ''
const STRATEGY = setup.merge_strategy
const RANGE = `origin/${INT}...HEAD`
const CTX = `Issue #${ISSUE} of ${SLUG}. Worktree: ${W} (branch ${setup.branch}, base ${setup.base_sha}, integration branch ${INT}). The branch's changes are git -C ${W} diff ${RANGE} (fetch origin first).`
const K = setup.knowledge || {}
const list = a => (a && a.length ? a.join(', ') : 'none')
const KNOW = `Ground the review in: ~/.agents/standards/the-bar.md and its stacks/ shards matching the changed file types (when present); the project's standards (${list(K.standards)}), only shards whose globs intersect the change; review hints (${list(K.hints)}); recorded rejections (${list(K.rejections)}): never raise a finding a rejection already settles.`
const RULES = `${BASE_RULES}
- Run every gh command with exactly this prefix and nothing else chained: ${UNSET || '(no prefix)'}
- Lifecycle commands, each alone in its own Bash call with no chaining, pipes or redirection and never after cd &&, only with the prefix above: git -C <worktree> push origin <branch>; gh pr create --repo <slug> --base <integration> --head <branch> --title '<t>' --body '<b>' (no single or double quotes, dollar signs, backticks or backslashes inside title or body); gh pr merge <n> --repo <slug> --${STRATEGY} --match-head-commit <sha>${setup.delete_branch ? ' --delete-branch' : ''}; git -C <checkout> branch -d <branch>. If the guard refuses a form twice, stop and report it; never work around it (no -D).
- Commit messages ${setup.co_authored_by ? 'end with the Co-Authored-By trailer your attribution instructions give' : 'carry no Co-Authored-By trailer: the project contract turns it off, whatever other instructions say'}. Never bypass commit signing.
- Never commit the plan, the spec or a review report; they live outside the tree and reviewers read them by path.`
log(`claimed #${ISSUE}, worktree ${W}; review code=${REVIEW_CODE || RS.code || 'none'} plan=${REVIEW_PLAN || RS.plan || 'none'}`)

// ---------------- Plan ----------------
phase('Plan')
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
const SPEC = args.spec ? `\nThe approved design spec for this issue is ${args.spec}: plan from it, its decisions are binding, and never edit or commit it.` : ''
const planPrompt = extra => `${CTX}
Plan this issue. Read the issue (gh issue view ${ISSUE} --repo ${SLUG} --comments) and the code it touches.${SPEC} Use the writing-plans skill for the plan's form only: its file location, size checks and reports do not apply here. Write the plan to ${setup.plan_dir}/plan.md and one task file per task beside it (${setup.plan_dir}/task-<n>.md); never commit them and never write under the project's artifact directories. Do not build, prototype or run the change; confirming each task's failing test later is the implementers' job. If the issue needs a decision only the user can make (a preference, an irreversible or scope choice not settled by the issue, the spec, the repo's docs or ADRs), return status needs_user with concise questions and stop. Otherwise return status planned with plan_root ${setup.plan_dir}/plan.md, the issue's acceptance criteria (kind code if a test or command in this repo can show it, evidence if it needs a deploy, an activation or observation over time, human if only the user can judge), and the task list in execution order with each task's file and a risk: security for authentication, permission or command guards, secrets, CI/CD or deploy config, data migrations; mechanical or low for small contained edits; else standard.${args.decisions ? `\nThe owner has answered the open decisions for this issue; they are binding: ${args.decisions} Do not ask them again; record them as decisions in the plan.` : ''}${extra || ''}
${RULES}`

if (!plan) {
  plan = await agent(planPrompt(), { label: 'plan', phase: 'Plan', schema: PLAN_SCHEMA })
  if (!plan) return stop('plan', { result: null })
  if (plan.status === 'needs_user') {
    const questions = plan.questions
    plan = null
    return stop('plan', { needs_user: questions })
  }
  const ACS0 = JSON.stringify(plan.acceptance || [])
  const planCodexP = REVIEW_PLAN ? agent(`${CTX}
Plan: ${plan.plan_root} (task files beside it). Acceptance criteria: ${ACS0}.${SPEC}
Run the project's configured independent plan review: the contract's workflow.review.plan is the command ${REVIEW_PLAN}. Use the codex-collaboration skill (invoke it with the Skill tool) to run that Codex plan review over the plan at that path against issue #${ISSUE} in the worktree ${W}; this step may dispatch the Codex reviewer that skill uses, and must wait for its result in this turn. Return Codex's Important or Critical findings as they are without adding your own review; verdict pass if none. If Codex cannot be run, return available false with the reason in raw_summary; never substitute your own review.
${RULES}`, { label: 'plan-codex', phase: 'Plan', model: 'sonnet', schema: CODEX }) : Promise.resolve(null)
  const planReviewClaude = await agent(`${CTX}
Review the implementation plan at ${plan.plan_root} (and its task files) against issue #${ISSUE} (gh issue view ${ISSUE} --repo ${SLUG}).${SPEC} ${KNOW} Report only Important or Critical defects: an acceptance criterion with no task, a task whose test cannot fail, wrong or missing interfaces, a design choice that breaks the project's documented conventions, or a project-specific literal written into global skills or agents. No style notes. Do not edit anything.`, { label: 'plan-review', phase: 'Plan', agentType: 'reviewer', schema: FINDINGS })
  const planCodexR = await planCodexP
  let planFindings = blocking(planReviewClaude)
  if (REVIEW_PLAN) {
    if (!planCodexR || !planCodexR.available) return stop('codex-unavailable', { step: 'plan', codex: planCodexR })
    planFindings = planFindings.concat(blocking(planCodexR).map(f => ({ ...f, source: 'codex' })))
    log(`codex plan review: ${blocking(planCodexR).length} blocking findings`)
  }
  if (planFindings.length) {
    log(`plan review: ${planFindings.length} blocking findings, revising once`)
    const revised = await agent(planPrompt(`\nA reviewer found these defects in your plan at ${plan.plan_root}; fix them in place and return the full result again: ${JSON.stringify(planFindings)}`), { label: 'plan-revise', phase: 'Plan', schema: PLAN_SCHEMA })
    if (revised && revised.status === 'planned') plan = revised
  }
}
const ACS = JSON.stringify(plan.acceptance || [])
const PLAN_REF = `Plan: ${plan.plan_root} (task files beside it).`
log(`plan: ${plan.tasks.length} tasks`)

// ---------------- Tasks ----------------
phase('Tasks')
const FOCUSED = 'Run only the tests that cover the files you changed; do not run the full test suite or the project\'s declared verification (that runs once later).'
for (const t of plan.tasks) {
  if (taskLog.some(d => d.n === t.n)) continue
  const start = `${CTX}\n${PLAN_REF}`
  let impl = await agent(`${start}
Implement task ${t.n} (${t.title}) exactly as its task file ${t.file} specifies: write the failing test first and see it fail, implement, see it pass, run the task's focused test commands, then for each new test temporarily remove the code it pins and confirm it fails, restore, and commit only this task's files in the worktree. ${FOCUSED} Return status blocked with notes if the task file is wrong or impossible.${CONT && CONT.partial === t.n ? `
An earlier attempt at this task was cut off and may have left uncommitted edits in the worktree (git -C ${W} status and git -C ${W} diff). Inspect them: keep what matches the task file, finish or redo the rest, and make sure the failing-test-first and mutation checks still hold for the final result.` : ''}
${RULES}`, { label: `impl-${t.n}`, phase: 'Tasks', agentType: 'implementer', model: 'sonnet', schema: IMPL })
  const halt = (stage, extra) => ({ ...stop(stage, extra), cont: { setup, plan, done: taskLog, partial: t.n } })
  if (!impl || impl.status !== 'done') return halt('task', { task: t, impl })
  const reviewer = (t.risk === 'mechanical' || t.risk === 'low') ? 'reviewer-lite' : 'reviewer'
  let review = await agent(`${start}
lane: direct. Review the diff of task ${t.n} only: git -C ${W} show ${impl.commit} (and the task file ${t.file} as its contract). ${KNOW} Report Important or Critical correctness defects and unmet task requirements only, each with a concrete failing input. No style notes. Do not edit anything.`, { label: `review-${t.n}`, phase: 'Tasks', agentType: reviewer, schema: FINDINGS })
  let rounds = 0
  while (blocking(review).length && rounds < 2) {
    rounds++
    impl = await agent(`${start}
Fix these review findings for task ${t.n} (${t.file}) in the worktree, with a regression test for each real defect, then commit: ${JSON.stringify(blocking(review))}. If a finding is wrong, say so in notes with evidence instead of changing code. ${FOCUSED}
${RULES}`, { label: `fix-${t.n}-${rounds}`, phase: 'Tasks', agentType: 'implementer', model: 'sonnet', schema: IMPL })
    if (!impl || impl.status !== 'done') return halt('task-fix', { task: t, impl })
    review = await agent(`${start}
Re-review only these previously reported findings for task ${t.n} against the fix commit ${impl.commit} (git -C ${W} show ${impl.commit}); the implementer's notes: ${impl.notes}. Findings: ${JSON.stringify(blocking(review))}. Report any finding still unresolved and any new Important or Critical defect the fix introduced.`, { label: `rereview-${t.n}-${rounds}`, phase: 'Tasks', agentType: 'reviewer-lite', schema: FINDINGS })
  }
  if (blocking(review).length) return halt('task-review', { task: t, review })
  taskLog.push({ n: t.n, commit: impl.commit, review_rounds: rounds, reviewer })
}

// ---------------- Final review ----------------
phase('Final review')
const groups = []
const PER = 3
for (let i = 0; i < plan.tasks.length; i += PER) groups.push(plan.tasks.slice(i, i + PER))
const chunked = groups.length > 1
const codexP = REVIEW_CODE ? agent(`${CTX}
${PLAN_REF} Acceptance criteria: ${ACS}.
Run the project's configured independent code review: the contract's workflow.review.code is the command ${REVIEW_CODE}. Use the codex-collaboration skill (invoke it with the Skill tool) to run that Codex diff review over the delivery range ${RANGE} in the worktree ${W}, with no review package; this step may dispatch the Codex reviewer that skill uses, and must wait for its result in this turn. Return Codex's Important or Critical findings as they are (correctness defects with a concrete failing input, unmet criteria) without adding your own review; verdict pass if none. If Codex cannot be run, return available false with the reason in raw_summary; never substitute your own review.
${RULES}`, { label: 'final-codex', phase: 'Final review', model: 'sonnet', schema: CODEX }) : Promise.resolve(null)
const finals = await parallel(groups.map((g, gi) => () => agent(`${CTX}
${PLAN_REF} Acceptance criteria: ${ACS}.
Final review${chunked ? ` of chunk ${gi + 1}/${groups.length}: tasks ${g.map(t => t.n).join(', ')} only (their files: ${g.map(t => t.file).join(', ')}); grade only these tasks` : ' of the whole delivery'}: git -C ${W} diff ${RANGE}${chunked ? ' restricted to the paths these tasks own' : ''}. ${KNOW} Two axes: correctness (real defects with a concrete failing input) and conformance (each task and each acceptance criterion of kind code is actually met, with the test or command that shows it). Report Important or Critical findings only. Do not edit anything.`, { label: `final-${gi + 1}`, phase: 'Final review', agentType: 'reviewer', schema: FINDINGS })))
let finalFindings = finals.flatMap(blocking)
const codexR = await codexP
if (REVIEW_CODE) {
  if (!codexR || !codexR.available) return stop('codex-unavailable', { step: 'code', codex: codexR })
  finalFindings = finalFindings.concat(blocking(codexR).map(f => ({ ...f, source: 'codex' })))
  log(`codex review: ${blocking(codexR).length} blocking findings`)
}
if (chunked) {
  const integ = await agent(`${CTX}
${PLAN_REF} Integration review. The delivery was reviewed in ${groups.length} chunks by task; their verdicts: ${JSON.stringify(finals)}. Read the full changed-file list (git -C ${W} diff --stat ${RANGE}) and the head tree as needed. ${KNOW} Check the interfaces between chunks and grade every acceptance criterion: ${ACS}. Report Important or Critical findings only.`, { label: 'final-integration', phase: 'Final review', agentType: 'reviewer', schema: FINDINGS })
  finalFindings = finalFindings.concat(blocking(integ))
}
if (finalFindings.length) {
  log(`final review: ${finalFindings.length} blocking findings, one fix wave`)
  const fw = await agent(`${CTX}\n${PLAN_REF} Fix these final-review findings, each real defect with a regression test, then commit: ${JSON.stringify(finalFindings)}. If a finding is wrong, explain with evidence in notes. ${FOCUSED}\n${RULES}`, { label: 'fix-wave', phase: 'Final review', agentType: 'implementer', model: 'sonnet', schema: IMPL })
  if (!fw || fw.status !== 'done') return stop('fix-wave', { fw, finalFindings })
  const rv = await agent(`${CTX}\nRe-review these final-review findings against the fix (git -C ${W} show ${fw.commit}); implementer notes: ${fw.notes}. Findings: ${JSON.stringify(finalFindings)}. Report any still unresolved and any new Important or Critical defect.`, { label: 'fix-wave-review', phase: 'Final review', agentType: 'reviewer', schema: FINDINGS })
  if (blocking(rv).length) return stop('fix-wave-review', { rv })
}

// ---------------- Verify ----------------
phase('Verify')
const VERIFY = {
  type: 'object',
  properties: { head: { type: 'string' }, results: { type: 'array', items: { type: 'object', properties: { id: { type: 'string' }, status: { type: 'string', enum: ['pass', 'fail', 'skipped'] }, summary: { type: 'string' } }, required: ['id', 'status', 'summary'] } } },
  required: ['head', 'results'],
}
const verifyPrompt = `${CTX}
Run the project's declared verification once on the worktree head, in the foreground, each command with a Bash timeout of up to 60 minutes: ${JSON.stringify(setup.verification || [])}. Run each argv with the worktree as working directory. If an entry has when_changed globs and none of the files changed (git -C ${W} diff --name-only ${RANGE}) match, mark it skipped with its skip_reason. Return head (git -C ${W} rev-parse HEAD, the full sha) and one result per id; for failures, summarize the failing tests or errors precisely. Do not change any file.
${RULES}`
let verify = await agent(verifyPrompt, { label: 'verify', phase: 'Verify', model: 'sonnet', effort: 'low', schema: VERIFY })
let vRounds = 0
const failed = v => (v ? v.results.filter(r => r.status === 'fail') : [{ id: '?', summary: 'verification returned nothing' }])
while (failed(verify).length && vRounds < 2) {
  vRounds++
  const fix = await agent(`${CTX}\n${PLAN_REF} The project's verification failed: ${JSON.stringify(failed(verify))}. Find the cause in this branch's changes (git -C ${W} diff ${RANGE}), fix it with the smallest change, commit. ${FOCUSED}\n${RULES}`, { label: `verify-fix-${vRounds}`, phase: 'Verify', agentType: 'implementer', model: 'sonnet', schema: IMPL })
  if (!fix || fix.status !== 'done') return stop('verify-fix', { verify, fix })
  verify = await agent(verifyPrompt, { label: `verify-${vRounds + 1}`, phase: 'Verify', model: 'sonnet', effort: 'low', schema: VERIFY })
}
if (failed(verify).length) return stop('verify', { verify })

// ---------------- Ship ----------------
phase('Ship')
const allCode = (plan.acceptance || []).length > 0 && plan.acceptance.every(a => a.kind === 'code')
const closesLine = allCode && INT === setup.default_branch ? `Closes #${ISSUE}` : `Refs #${ISSUE}`
const prR = await agent(`${CTX}
Open the pull request for this branch. Push the branch (git -C ${W} push origin ${setup.branch}). If an open PR with head ${setup.branch} already exists (a resumed delivery), reuse it; else open one against ${INT}. Title: a short summary of the issue. Body, plain prose, no single or double quotes, dollar signs, backticks or backslashes: sections Why, What changes, Acceptance (a table with one row per criterion: id, criterion, kind, and the test or command that shows it; criteria ${ACS}), Evidence (verification ${JSON.stringify(verify.results)}; ${taskLog.length} tasks reviewed; final review ${chunked ? 'chunked' : 'whole'}${REVIEW_CODE ? ' plus the configured independent review' : ''}), Merge danger; then the line ${closesLine}; then the attribution lines your instructions give for pull requests, if any. Never attach or link the plan or the spec. Return pr (number) and head (full sha of the pushed head).
${RULES}`, { label: 'pr', phase: 'Ship', model: 'sonnet', schema: { type: 'object', properties: { pr: { type: 'integer' }, head: { type: 'string' }, notes: { type: 'string' } }, required: ['pr', 'head'] } })
if (!prR || !prR.pr) return stop('pr', { result: prR })
const PR = prR.pr

const CHECKS = { type: 'object', properties: { state: { type: 'string', enum: ['passed', 'failed', 'behind'] }, head: { type: 'string' }, required: STRS, details: { type: 'string' } }, required: ['state', 'head'] }
const SYNC = { type: 'object', properties: { status: { type: 'string', enum: ['done', 'blocked'] }, conflicted: { type: 'boolean' }, merge_commit: { type: 'string' }, resolved_files: STRS, tests: STRS, notes: { type: 'string' } }, required: ['status', 'conflicted', 'notes'] }
let head = prR.head
let syncs = 0
for (;;) {
  const ck = await agent(`${CTX}
Wait for PR #${PR} to be mergeable. 1. git -C ${W} fetch origin; if the local branch is ahead of origin/${setup.branch}, push it. head is git -C ${W} rev-parse HEAD (full sha). 2. If origin/${INT} is not an ancestor of HEAD (git -C ${W} merge-base --is-ancestor origin/${INT} HEAD fails), return state behind at once. 3. Otherwise wait in this turn for the required checks on head: take the required check names from gh api repos/${SLUG}/rules/branches/${INT} (its required_status_checks rules) or else classic branch protection; if neither answers, every check is required. gh pr checks ${PR} --repo ${SLUG} --watch (Bash timeout up to 60 minutes; rerun while any is pending) can return early, and its --required list can be partial: never treat a partial list as green. Return passed only when every required name has passed on head, failed with the failing names and why when any required check failed, and the required names you used.
${RULES}`, { label: `checks-${syncs + 1}`, phase: 'Ship', model: 'sonnet', effort: 'low', schema: CHECKS })
  if (!ck) return stop('checks', { pr: PR, checks: null })
  if (ck.state === 'failed') return stop('checks', { pr: PR, checks: ck })
  head = ck.head
  if (ck.state === 'passed') break
  if (syncs >= 2) return stop('sync-contention', { pr: PR, syncs })
  syncs++
  const sy = await agent(`${CTX}
The branch is behind ${INT}. Merge origin/${INT} into it in the worktree (git -C ${W} merge origin/${INT}). If it conflicts, resolve each conflict keeping both sides' intent, commit the merge, and run only the tests covering the files the resolution touched. Do not push. Return conflicted, merge_commit (full sha), resolved_files and the tests you ran; status blocked with notes if you cannot resolve it safely.
${RULES}`, { label: `sync-${syncs}`, phase: 'Ship', agentType: 'implementer', model: 'sonnet', schema: SYNC })
  if (!sy || sy.status !== 'done') return stop('sync', { pr: PR, sync: sy })
  if (sy.conflicted) {
    const sr = await agent(`${CTX}
Review the conflict resolution in merge commit ${sy.merge_commit}: git -C ${W} show --cc ${sy.merge_commit} and the resolved files ${JSON.stringify(sy.resolved_files || [])}; the tests run: ${JSON.stringify(sy.tests || [])}. Report Important or Critical defects only: a dropped change from either side, a broken merge of intent, a resolved file whose tests were not run.`, { label: `sync-review-${syncs}`, phase: 'Ship', agentType: 'reviewer-lite', schema: FINDINGS })
    if (blocking(sr).length) return stop('sync-review', { pr: PR, review: sr })
  }
}

const mg = await agent(`${CTX}
Merge PR #${PR}. Run, alone and exactly: ${UNSET}gh pr merge ${PR} --repo ${SLUG} --${STRATEGY} --match-head-commit ${head}${setup.delete_branch ? ' --delete-branch' : ''}
Then read gh pr view ${PR} --repo ${SLUG} --json state,mergeCommit: merged is true only when state is MERGED. Never retry with another form; on a guard refusal or a head mismatch return merged false with the exact message.
${RULES}`, { label: 'merge', phase: 'Ship', model: 'sonnet', effort: 'low', schema: { type: 'object', properties: { merged: { type: 'boolean' }, merge_commit: { type: 'string' }, notes: { type: 'string' } }, required: ['merged', 'notes'] } })
if (!mg || !mg.merged) return stop('merge', { pr: PR, merge: mg })

const openCriteria = (plan.acceptance || []).filter(a => a.kind !== 'code')
const co = await agent(`${CTX}
PR #${PR} is merged into ${INT}. Close out, each command in its own Bash call:
1. git -C ${REPO} worktree remove ${W} (it also removes the plan directory); then git -C ${REPO} fetch origin; if the checkout ${REPO} is clean and on ${INT}, git -C ${REPO} merge --ff-only origin/${INT}; then git -C ${REPO} branch -d ${setup.branch}. If -d refuses, leave the branch and report it (never -D).
2. Remove the in-progress label from issue #${ISSUE}.
3. ${allCode ? `Every criterion is of kind code. Read gh issue view ${ISSUE} --repo ${SLUG} --json state; if it is still open (${INT === setup.default_branch ? 'the closing keyword did not fire' : `${INT} is not the default branch, so no closing keyword fires`}), run gh issue close ${ISSUE} --repo ${SLUG} --comment 'Delivered by PR ${PR} into ${INT}.'` : `Keep the issue open. Add the needs-verification label (create it if missing) and comment which criteria remain and how to check each: ${JSON.stringify(openCriteria)}.`}
Return issue_state (OPEN or CLOSED, read back from the tracker), branch_deleted and notes.
${RULES}`, { label: 'close-out', phase: 'Ship', model: 'sonnet', effort: 'low', schema: { type: 'object', properties: { issue_state: { type: 'string' }, branch_deleted: { type: 'boolean' }, notes: { type: 'string' } }, required: ['issue_state', 'notes'] } })

return { stage: 'done', pr: PR, merged: true, merge_commit: mg.merge_commit, close_out: co, tasks: taskLog, acceptance: plan.acceptance, chunked, syncs, verify: verify.results }
