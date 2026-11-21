// Runs a Workflow-tool program's control flow against stub agents (issue 618).
// Usage: node deliver_standard_harness.mjs <program.js>  with a scenario JSON on stdin (one-shot), or import { makeRunner } and call makeRunner(programText)(scenario), which resolves to the exact text one-shot mode prints (program_server.mjs does, once per program):
//   { "args": {...}, "replies": { "<label>": reply | [reply per call] }, "patch": { "<label>": {...} } }
// A label with no reply gets the default for its kind (DEFAULTS below); a patch
// is merged over that default; a reply "throw" throws, and a program throw prints { result: null, error, calls }. A folded label (NESTED) given an explicit object reply with no own key for a nested step
// gets that step's default; a key present with null stays null. The fresh setup prompt (it names `--holder <host>/<id> `)
// A scenario's "after": { "<label>": "<other label>" } holds the reply of <label> until <other label> has been called (a run where it never is does not end).
// #1139: every setup reply carries the look marker read (SETUP.look, unmarked): an explicit ok setup reply with no own look key gets it too, fresh and resume alike.
// also gets the folded claim: holder (built from the merged host, unless the patch sets it), acquire, claim, answer (the owner's answer) and renew (the already_held claim renew); a resume setup gets none. Prints { result, calls: [{label, agentType, model, effort, schema, prompt}], logs: [each log() line], events: ["call <label>" and "reply <label>" in order] }.
import { readFileSync, realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const SHA = 'a'.repeat(40)
const PASS = { verdict: 'pass', findings: [] }
const TASK_COMMIT = n => (n === 1 ? 'c0ffee' : `c0ffee${n}`)
const DONE = { status: 'done', start_head: 'b0', commit: 'c0ffee', tests: ['t'], notes: 'ok' }
const SETUP = {
  ok: true, host: 'h1', slug: 'owner/repo', integration_branch: 'dev', default_branch: 'main',
  branch: 'issue-9-x', worktree_path: '/r/.wt/w-issue-9-x', dirty: false, unset_env: [], merge_strategy: 'merge', delete_branch: true,
  review: { code: 'cr', plan: 'pr' }, review_state: { code: 'available', plan: 'available' },
  knowledge: { standards: ['/r/docs/standards'], hints: ['/r/.hints'], rejections: ['/r/.rej'] },
  verification: [{ id: 'build', argv: ['make', 'build'], cwd: '.' }],
  look: { verdict: 'unmarked', covers: [] },
}
// The folded claim of a fresh setup prompt: the id its acquire command names, or null for a resume prompt.
const HOLDER_ID = prompt => { const m = /--holder <host>\/([A-Za-z0-9._-]+) /.exec(prompt); return m ? m[1] : null }
const FOLDED_SETUP = {
  acquire: { verdict: 'acquired', comment_id: 7 },
  claim: { ok: true, worktree: '/r/.wt/w-issue-9-x', base_sha: SHA, plan_dir: '/r/.git/worktrees/w/deliver-standard' },
  answer: { verdict: 'none', comment_id: null, questions: [], decisions: '' },
  renew: { verdict: 'renewed' },
}
const holderOf = (host, prompt) => (typeof host === 'string' && host ? { holder: `${host}/${HOLDER_ID(prompt)}` } : {})
// #1372: a security task keeps the Codex plan review in every default run; a small plan of no security task skips it.
const PLAN = {
  status: 'planned', plan_root: '/r/.git/worktrees/w/deliver-standard/plan.md',
  acceptance: [{ id: 'AC1', text: 'works', kind: 'code' }],
  tasks: [{ n: 1, title: 'one', file: 'task-1.md', risk: 'security' }],
}
// A hold reply posts the checks the prompt gives it (its Checks line, #1281), as a real hold does; a prompt without one gets a check for every non-code criterion it lists.
const openChecks = prompt => {
  const given = /^Checks: (\[.*\])$/m.exec(prompt)
  if (given) return JSON.parse(given[1])
  const m = /Criteria: (\[.*\])/.exec(prompt)
  return (m ? JSON.parse(m[1]) : []).filter(a => a.kind !== 'code').map(a => ({ ac: a.id, kind: a.kind }))
}
// #1281: the draft writes a check for each criterion the prompt lists without a verify member.
const unverified = prompt => {
  const m = /Criteria without a verify member: (\[.*\])/.exec(prompt)
  return (m ? JSON.parse(m[1]) : []).map(a => ({ ac: a.id, kind: a.kind }))
}
// Ordered: the first matching pattern wins.
const DEFAULTS = [
  [/^land-push-/, prompt => ({ head: (/at the head ([0-9a-f]+)/.exec(prompt) || [])[1] || SHA, renew: { verdict: 'renewed' } })],
  // #1139: a marked delivery's pull request step (no lock) and its push; the push answers the head the prompt names.
  [/^look-pr$/, { pr: 42, head: SHA, probe: { conflicted: false }, behind: false, renew: { verdict: 'renewed' } }],
  [/^look-push$/, prompt => ({ head: (/at the head ([0-9a-f]+)/.exec(prompt) || [])[1] || SHA, renew: { verdict: 'renewed' } })],
  // #1373: the checks of the head the owner will see (green at the head the prompt names), and the verification of a head a fix or a sync moved.
  [/^look-checks-/, prompt => ({ state: 'passed', head: (/look at the head ([0-9a-f]+)/.exec(prompt) || [])[1] || SHA, behind: false, required: ['ci'], passed: ['ci'], renew: { verdict: 'renewed' } })],
  [/^look-reverify$/, prompt => ({ head: (/moved to the head ([0-9a-f]+)/.exec(prompt) || [])[1] || SHA, clean: true, results: [{ id: 'build', status: 'pass', summary: 'ok' }] })],
  // #1139: the owner's look answers: the pull request head read, the approval post, and the fix round of a changes answer (look-fix-review falls to the review default).
  [/^look-head$/, { head: SHA, state: 'OPEN', merge: 'c0ffee' + '0'.repeat(34), renew: { verdict: 'renewed' } }],
  [/^look-post$/, { verdict: 'posted', comment_id: 101 }],
  [/^look-read$/, { verdict: 'approved', kept_from: null }],
  [/^look-stale$/, { complete: true, stale: [] }],
  [/^look-status$/, { verdict: 'needed', kept_from: null }],
  // #1246: the verification of an approved head; the fast-forward reached the head the prompt names.
  [/^look-verify$/, prompt => ({ head: (/merge --ff-only ([0-9a-f]{40})/.exec(prompt) || [])[1] || SHA, clean: true, merge_only: true, ahead: false, results: [{ id: 'build', status: 'pass', summary: 'ok' }] })],
  [/^look-fix$/, { ...DONE, start_head: SHA, commit: 'f1c0de' }],
  // #1371: the retest of a push-bound fix reports the tree clean once its tests ran, unless a scenario says otherwise.
  [/^fix-retest$/, { ...DONE, clean: true }],
  [/^land-unlock$/, { verdict: 'released' }],
  [/^land-(re)?lock-/, { renew: { verdict: 'renewed' }, lock: { verdict: 'acquired', lock_sha: SHA } }],
  [/^renew-/, { verdict: 'renewed', comment_id: 7 }],
  [/^acquire$/, { verdict: 'acquired', comment_id: 7 }],
  [/^setup$/, prompt => (HOLDER_ID(prompt) ? { ...SETUP, ...holderOf(SETUP.host, prompt), ...FOLDED_SETUP } : SETUP)],
  [/^worktree$/, { ok: true, worktree: '/r/.wt/w-issue-9-x', base_sha: SHA, plan_dir: '/r/.git/worktrees/w/deliver-standard' }],
  [/^plan(-revise|-rules-revise|-branch-revise|-task-revise)?$/, PLAN],
  [/^direct-impl$/, { ...DONE, acceptance: [{ id: 'AC1', text: 'works', kind: 'code' }], sensitive: false, ineligible: false, renew: { verdict: 'renewed' } }],
  [/^direct-fix$/, DONE],
  [/-codex$/, { available: true, ...PASS }],
  [/^diff-size$/, { measured: true, changed_lines: 10 }],
  [/^owner-answer$/, { verdict: 'none', comment_id: null, questions: [], decisions: '', renew: { verdict: 'renewed' } }],
  [/^amend$/, prompt => {
    const m = /^Input: (\{.*\})$/m.exec(prompt)
    const input = m ? JSON.parse(m[1]) : { edits: [] }
    return { status: 'applied', edits: input.edits.map(e => ({ file: e.file, exists: true, occurrences: 1, already: false })), refused: [] }
  }],
  [/^direct-review/, { ...PASS, acceptance: [{ id: 'AC1', met: true, evidence: 'test_a.py:10 test_works' }] }],
  // #1386: the follow-up filing step files each entry it is given as the next issue number of its call.
  [/^follow-ups-\d+$/, (prompt, label) => {
    const m = /^Follow-ups: (\[.*\])$/m.exec(prompt)
    const k = +label.split('-').pop()
    return { filed: (m ? JSON.parse(m[1]) : []).map(f => ({ n: f.n, issue: 900 + 10 * k + f.n })) }
  }],
  [/review|^final-/, PASS],
  // #913: the resolution of an aborted sync merge, outside the land lock; like the sync default, its merge commit is the head unless a scenario names one.
  [/^sync-resolve-/, { status: 'done', conflicted: true, merge_commit: SHA, resolved_files: ['a.py'], notes: 'resolved' }],
  [/^sync-/, { status: 'done', conflicted: false, merge_commit: SHA, notes: 'clean' }],
  [/^ws-check-/, { whitespace_exit: 1, changed_paths: ['src/a.js'] }],
  [/^verify-fix-/, DONE],
  [/^verify/, { head: SHA, clean: true, results: [{ id: 'build', status: 'pass', summary: 'ok' }], renew: { verdict: 'renewed' } }],
  // #923: honest heads. Task n starts at the head task n-1 left (the base for task 1) and commits its own; a task fix round commits on
  // top of the head just reviewed, and a fix at that same head is a rebuttal.
  [/^fix-\d+-1$/, (prompt, label) => ({ ...DONE, start_head: TASK_COMMIT(+label.split('-')[1]), commit: 'f1c0de' })],
  [/^fix-\d+-2$/, { ...DONE, start_head: 'f1c0de', commit: 'f2c0de' }],
  [/^impl-/, (prompt, label) => { const n = +label.split('-')[1]; return { ...DONE, start_head: n === 1 ? SHA : TASK_COMMIT(n - 1), commit: TASK_COMMIT(n), renew: { verdict: 'renewed' } } }],
  [/^(impl|fix)-|^fix-wave$/, DONE],
  [/^pr$/, { pr: 42, head: SHA, renew: { verdict: 'renewed' }, lock: { verdict: 'already_held', lock_sha: SHA }, checks: { state: 'passed', head: SHA, required: ['ci'], passed: ['ci'] } }],
  [/^checks-/, { state: 'passed', head: SHA, required: ['ci'], passed: ['ci'], renew: { verdict: 'renewed' }, lock: { verdict: 'already_held', lock_sha: SHA } }],
  [/^merge$/, { merged: true, merge_commit: SHA, notes: 'merged', renew: { verdict: 'renewed' }, lock: { verdict: 'already_held', lock_sha: SHA } }],
  [/^hold-draft$/, prompt => ({ complete: true, merge: SHA, posted: [], written: unverified(prompt) })],
  [/^hold$/, prompt => ({ merge_commit_local: true, code_unmet: [], blocks: [], split: [], block: { v: 1, merge: SHA, checks: openChecks(prompt) }, lint: { ok: true, errors: [] }, verify_run: { ran: true, exit: 0 }, issue_state: 'OPEN', notes: 'held', release: { verdict: 'released' } })],
  // #1186: an approved marked delivery's close-out call also carries the look tick, which answers ticked.
  [/^close-out$/, prompt => ({ issue_state: 'CLOSED', branch_deleted: true, released: true, decision_ended: true, notes: 'ok', ...(prompt.includes('look-approval tick') ? { look_tick: { verdict: 'ticked', ticked: 1 } } : {}) })],
]
// Folded labels: the nested steps their reply carries, each defaulted when an explicit reply leaves it out.
const NESTED = [[/^(owner-answer|verify)$/, ['renew']], [/^setup$/, ['holder', 'acquire', 'claim', 'answer', 'renew']], [/^pr$/, ['renew', 'lock', 'checks']], [/^merge$/, ['renew', 'lock']], [/^land-push-/, ['renew']], [/^look-(pr|push|head)$/, ['renew']], [/^look-checks-/, ['renew']], [/^land-(re)?lock-/, ['renew', 'lock']], [/^checks-/, ['renew', 'lock']], [/^(impl-\d+|direct-impl)$/, ['renew']], [/^hold$/, ['release']]]
const defaultOf = (label, prompt, over = {}) => {
  const hit = DEFAULTS.find(([re]) => re.test(label))
  if (!hit) throw new Error(`no stub reply for agent label ${label}`)
  const base = typeof hit[1] === 'function' ? hit[1](prompt, label) : hit[1]
  // A fresh setup's holder follows the explicit reply's own host.
  return label === 'setup' && HOLDER_ID(prompt) && 'host' in over ? { ...base, ...holderOf(over.host, prompt) } : base
}

// #1001: a CI fix asked to release the land lock before it edits reports the release when it made a commit, unless a scenario says otherwise.
const released = (label, prompt, r) => {
  if (label === 'fix-ci' && r && typeof r === 'object' && /return lock_released true/i.test(prompt) && !Object.prototype.hasOwnProperty.call(r, 'lock_released') && !(typeof r.commit === 'string' && typeof r.start_head === 'string' && r.commit && r.start_head && (r.commit.startsWith(r.start_head) || r.start_head.startsWith(r.commit)))) r.lock_released = true
  return r
}

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
// Rewrites meta and compiles the program once; each scenario then runs against state made anew, so one process can answer many scenarios.
export function makeRunner(programText) {
  const body = programText.replace(/^export const meta\b/m, 'const meta')
  const run = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow', body)
  return async function runScenario(scenario) {
    const calls = []
    const seen = {}
    // The "after" gates: one promise per awaited label, resolved when that label is called.
    const called = {}
    // Each agent call and each reply, in the order they happened.
    const events = []
    const gate = label => (called[label] = called[label] || (() => { let open; const p = new Promise(r => { open = r }); return { p, open } })())
    async function agent(prompt, opts = {}) {
      events.push(`call ${opts.label}`)
      gate(opts.label).open()
      try {
        const reply = replyOf(prompt, opts)
        const wait = (scenario.after || {})[opts.label]
        if (wait) await gate(wait).p
        return reply
      } finally {
        events.push(`reply ${opts.label}`)
      }
    }
    function replyOf(prompt, opts) {
      const label = opts.label
      calls.push({ label, agentType: opts.agentType || null, model: opts.model || null, effort: opts.effort || null, schema: opts.schema || null, prompt })
      const n = seen[label] = (seen[label] || 0) + 1
      const replies = scenario.replies || {}
      if (Object.prototype.hasOwnProperty.call(replies, label)) {
        const r = replies[label]
        const out = structuredClone(Array.isArray(r) ? r[Math.min(n, r.length) - 1] : r)
        // A reply equal to "throw" makes the stub agent throw after the call was recorded.
        if (out === 'throw') throw new Error(`stub agent ${label} threw`)
        const row = NESTED.find(([re]) => re.test(label))
        if (row && out && typeof out === 'object' && !Array.isArray(out) && (label !== 'setup' || (out.ok === true && HOLDER_ID(prompt)))) {
          const base = defaultOf(label, prompt, out)
          for (const k of row[1]) if (!Object.prototype.hasOwnProperty.call(out, k)) out[k] = structuredClone(base[k])
        }
        if (label === 'setup' && out && typeof out === 'object' && !Array.isArray(out) && out.ok === true && !Object.prototype.hasOwnProperty.call(out, 'look')) out.look = structuredClone(SETUP.look)
        return released(label, prompt, out)
      }
      const base = defaultOf(label, prompt)
      const patch = (scenario.patch || {})[label] || {}
      const merged = { ...base, ...patch }
      // A fresh setup's holder is computed after the patch is merged, from the merged host.
      if (label === 'setup' && HOLDER_ID(prompt) && !('holder' in patch)) {
        delete merged.holder
        Object.assign(merged, holderOf(merged.host, prompt))
      }
      return released(label, prompt, structuredClone(merged))
    }
    const parallel = thunks => Promise.all(thunks.map(t => Promise.resolve().then(t).catch(() => null)))
    const pipeline = () => { throw new Error('pipeline is not stubbed') }
    const workflow = () => { throw new Error('workflow is not stubbed') }
    const budget = { total: null, spent: () => 0, remaining: () => Infinity }
    const noop = () => {}
    const logs = []
    const log = line => { logs.push(String(line)) }

    // A program throw is printed with the calls that ran, the finally release among them.
    let result = null
    let error = null
    try {
      result = await run(agent, parallel, pipeline, noop, log, scenario.args, budget, workflow)
    } catch (e) {
      error = String((e && e.message) || e)
    }
    return JSON.stringify(error === null ? { result, calls, logs, events } : { result: null, error, calls, logs, events })
  }
}

// One-shot mode (node <harness> <program.js>, scenario on stdin) runs only when this file is the entry module; Node resolves an ESM entry's symlinks, so import.meta.url is its real path.
if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.stdout.write(await makeRunner(readFileSync(process.argv[2], 'utf8'))(JSON.parse(readFileSync(0, 'utf8'))))
}
