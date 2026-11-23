// Runs deliver-batch.js against stub agents and a stub child workflow (issue 636).
// Usage: node deliver_batch_harness.mjs <program.js> with a scenario JSON on stdin (one-shot), or import { makeRunner } and call makeRunner(programText)(scenario), which resolves to the exact text one-shot mode prints (program_server.mjs does, once per program); a program throw rejects it, as it escapes the one-shot run:
//   { "args": {...}, "replies": {"<label>": reply | [reply per call]}, "patch": {"<label>": {...}},
//     "children": {"<issue>": child result | [one per call] | "throw"}, "turns": {"<issue>:<mode>": n}, "delays": {"<label>": n} }
// A label with no reply gets its default (DEFAULTS); a patch is merged over that default. A facts reply without `look` reads unmarked and one without `live_fault` reads no-sprint (NESTED). A reply
// of null is returned as null (a dead agent). Prints { result, calls, events (each agent's `call <label>` and `reply <label>`, in order), logs (each log() line), max_active, max_planning, child_events, child_returns }:
// calls lists agents ({kind: 'agent', label, prompt, schema, agentType, model, effort, facts_pending}) and children
// ({kind: 'workflow', label: 'child-<issue>', script, args}) in start order. A children entry applies to every child
// call of its issue, mode 'plan' and 'ready' alike, in call order, and a list element "throw" throws Error('child failed'); an object
// with a string `throw` member (as the entry or a list element) throws new Error(<that string>) instead; an issue with no
// entry gets plannedOf(a) for a mode 'plan' call and readyOf(a) otherwise. turns ({"<issue>:<mode>": n}) makes that
// child take n macrotask turns instead of 5, so a test can hold it pending. max_active is the most children not in
// plan mode at once, max_planning the most executing plan-mode children at once, and child_events the ordered
// {event: 'start'|'return', issue, mode} of every child; child_returns lists, per child return, {issue, mode, calls: the number of calls started before it}.
// A reply equal to "throw" makes the stub agent throw after its call was recorded (land() catches it and releases).
// A folded label (NESTED) given an explicit object reply with no own key for one of its nested steps gets that
// step's default; a key present with null stays null (the nested step did not run).
// The train steps (#822) default from their own prompt: the members a train-build, train-ready or train-merge prompt lists.
import { readFileSync, realpathSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const SHA = 'a'.repeat(40)
const PASS = { verdict: 'pass', findings: [] }
const SYNC_FIXED = 'f'.repeat(40)
const RESOLVED = 'b'.repeat(40)
const DONE = { status: 'done', start_head: 'b0', commit: 'c0ffee', tests: ['t'], notes: 'ok' }
const AC = [{ id: 'AC1', text: 'works', kind: 'code' }]
const promptHead = p => (p.match(/Accepted head: ([0-9a-f]+)/) || [])[1] || SHA
const num = label => Number((label.match(/-(\d+)(?:-|$)/) || [])[1])
const CAR = i => String(i).repeat(40)
// One sha is the other, in full or short form.
const sameHead = (a, b) => typeof a === 'string' && typeof b === 'string' && a !== '' && b !== '' && (a.startsWith(b) || b.startsWith(a))
const RELEASED = (p, r) => (/return lock_released true/i.test(p) && !sameHead(r.commit, r.start_head) ? { lock_released: true } : {})
// The JSON value that ends the prompt line starting with `lead`.
const jsonAfter = (p, lead) => JSON.parse(p.slice(p.indexOf(lead) + lead.length).split('\n')[0])
// Ordered: the first matching pattern wins. A default gets the label, the prompt and the scenario's acceptance (one copy per scenario, shared with a ready child's).
const DEFAULTS = [
  [/^setup$/, () => ({ ok: true, host: 'h1', slug: 'owner/repo', integration_branch: 'dev', default_branch: 'main', merge_strategy: 'merge', delete_branch: true, unset_env: [], max_parallel: 2, required_checks: null, guards: [] })],
  [/^facts-/, l => ({ state: 'OPEN', labels: [], title: 't', branch: `issue-${num(l)}-x`, claim: { verdict: 'free', by: null }, merged_refs: [], open_pr: null, native: { verdict: 'read', blocked_by: [] }, blockers: [], decision: { verdict: 'none', comment_id: null, questions: [], decisions: '' }, lane: 'standard', why: 'x', look: { verdict: 'unmarked' }, live_fault: { verdict: 'no-sprint' } })],
  [/^acquire-/, () => ({ verdict: 'acquired', comment_id: 7 })],
  [/^renew-/, () => ({ verdict: 'renewed' })],
  [/^release-/, () => ({ verdict: 'released' })],
  [/^settle-/, () => ({ state: 'OPEN', release: null })],
  [/^(ask|land-ask)-/, () => ({ verdict: 'posted', comment_id: 99 })],
  [/^recover-end-/, () => ({ verdict: 'ended' })],
  // #1019: the push of the clean merges a readopt found on top of the PR head lands at the head its prompt names.
  [/^readopt-push-/, (l, p) => ({ pushed: true, head: (p.match(/rev-parse HEAD prints ([0-9a-f]{40})/) || [])[1] })],
  // #1371: the push of a reviewed sync fix before the checks of its head are polled lands at the head its prompt names.
  [/^land-push-/, (l, p) => ({ ok: true, head: (p.match(/rev-parse HEAD prints ([0-9a-f]{40})/) || [])[1] })],
  [/^readopt-/, (l, p, ac) => ({ ok: true, worktree: `/r/.wt/w-issue-${num(l)}-x`, branch: `issue-${num(l)}-x`, head: SHA, acceptance: ac })],
  [/^land-sync-review-|^land-sync-rereview-|^land-fix-review-/, () => PASS],
  // #907: a sync fix defaults to one commit, SYNC_FIXED, on top of the merge commit its prompt names.
  [/^land-sync-fix-/, (l, p) => ({ ...DONE, start_head: (p.match(/merge commit ([0-9a-f]{40})/) || [])[1], commit: SYNC_FIXED })],
  [/^land-record-/, (l, p) => { const head = promptHead(p); return { ok: true, head, lock: { verdict: 'moved', lock_sha: head }, checks: { state: 'passed', head, required: ['ci'], passed: ['ci'] } } }],
  // #913: the resolution of an aborted sync merge, outside the land lock, defaults to a resolved merge commit RESOLVED.
  // #1022: the second proof of the clean merges a rerun sync step reported.
  [/^land-sync-prove-/, () => ({ proven: true })],
  [/^land-sync-resolve-/, () => ({ status: 'done', conflicted: true, head: RESOLVED, merge_commit: RESOLVED, resolved_files: ['x.py'], markers_checked: true, tests: ['t'], notes: 'ok' })],
  [/^land-sync-/, () => ({ status: 'current', conflicted: false, head: SHA, notes: 'ok' })],
  // #1001: the PR opened while the issue waited in the land queue, at the same number its land-pr or train-pr reports.
  [/^land-open-/, (l, p) => ({ pr: 40 + num(l), head: promptHead(p), renew: { verdict: 'renewed' } })],
  [/^land-pr-/, (l, p) => ({ pr: 40 + num(l), head: SHA, renew: { verdict: 'renewed' }, checks: { state: 'passed', head: promptHead(p), required: ['ci'], passed: ['ci'] } })],
  // The lock is taken once the head is green; the take and each wait for it say whether the base moved past it.
  [/^land-(take-|(re)?lock-)/, () => ({ renew: { verdict: 'renewed' }, lock: { verdict: 'acquired', lock_sha: SHA }, behind: false })],
  [/^land-checks-/, () => ({ state: 'passed', head: SHA, required: ['ci'], passed: ['ci'] })],
  // #1001: a fix step asked to release the land lock before it edits reports the release, unless a scenario says otherwise.
  [/^land-fix-/, (l, p) => ({ ...DONE, ...RELEASED(p, DONE) })],
  [/^land-merge-/, () => ({ merged: true, merge_commit: SHA, notes: 'merged', renew: { verdict: 'renewed' }, lock: { verdict: 'already_held', lock_sha: SHA } })],
  [/^land-unlock-/, () => ({ verdict: 'released' })],
  [/^close-out-/, () => ({ issue_state: 'CLOSED', released: true, decision_ended: true, branch_deleted: true, notes: 'ok', release: { verdict: 'released' } })],
  // #822 train landing. Car i of a train defaults to head CAR(i) and PR 90 + i; a member PR defaults to OPEN before the merge and MERGED after it, and a train-flip read to a merged car.
  [/^train-sweep-/, () => ({ ok: true, closed: [], deleted: [] })],
  [/^train-pr-/, (l, p) => ({ pr: 40 + num(l), head: promptHead(p), renew: { verdict: 'renewed' } })],
  [/^train-build-/, (l, p) => ({ status: 'done', conflicted: false, worktree: '/tmp/t/land-train', notes: 'ok', cars: jsonAfter(p, 'The members, in order, as JSON: ').map((m, i) => ({ issue: m.issue, head: CAR(i + 1), pr: 91 + i })) })],
  [/^train-checks-/, (l, p) => ({ state: 'passed', head: (p.match(/at the car head ([0-9a-f]{40})/) || [])[1], required: ['ci'], passed: ['ci'], refresh: { last: 'refreshed', refreshed: 1 } })],
  [/^train-ready-/, (l, p) => ({ members: jsonAfter(p, 'The members, in order, as JSON: ').map(m => ({ issue: m.issue, renew: { verdict: 'renewed' }, head: m.head, state: 'OPEN' })) })],
  [/^train-flip-/, (l, p) => ({ car: 'MERGED', prs: jsonAfter(p, 'The pull requests to read, as JSON: ').map(pr => ({ pr, state: 'MERGED' })) })],
  [/^train-merge-/, (l, p) => ({ lock: { verdict: 'already_held', lock_sha: SHA }, merged: true, notes: 'merged', prs: jsonAfter(p, 'The member pull requests, as JSON: ').map(pr => ({ pr, state: 'MERGED' })) })],
]
// Folded labels: the nested steps their reply carries, each defaulted when an explicit reply leaves it out.
const NESTED = [[/^train-pr-/, ['renew']], [/^train-merge-/, ['lock']], [/^land-pr-/, ['renew', 'checks']], [/^land-(take-|(re)?lock-)/, ['renew', 'lock', 'behind']], [/^land-merge-/, ['renew', 'lock']], [/^land-record-/, ['lock', 'checks']], [/^close-out-/, ['release']], [/^facts-/, ['look', 'live_fault']]]

const readyOf = (a, acceptance) => ({
  stage: 'ready', head: SHA, branch: `issue-${a.issue}-x`, worktree: `/r/.wt/w-issue-${a.issue}-x`,
  verify: [{ id: 'build', status: 'pass', summary: 'ok' }], tasks: [{ n: 1 }], acceptance, fix_waves: 0,
  cont: { setup: { holder: `h1/${a.batch_id}`, branch: `issue-${a.issue}-x`, worktree: `/r/.wt/w-issue-${a.issue}-x` } },
})
// A plan-mode child's default: it echoes a forwarded cont, else returns a fresh cont with a reviewed plan.
const plannedOf = a => ({
  stage: 'planned', plan: { tasks: [{ n: 1 }] },
  cont: a.cont !== undefined ? structuredClone(a.cont)
    : { setup: { holder: `h1/${a.batch_id}`, branch: `issue-${a.issue}-x`, worktree: `/r/.wt/w-issue-${a.issue}-x` }, lane: 'standard', plan_reviewed: true },
})

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
// Rewrites meta and compiles the program once; each scenario then runs against state made anew, so one process can answer many scenarios.
export function makeRunner(programText) {
  const body = programText.replace(/^export const meta\b/m, 'const meta')
  const run = new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow', body)
  return async function runScenario(scenario) {
    const calls = []
    // One copy of the acceptance per scenario, behind both a ready child's default and the readopt default: a program that edits one sees it in the other,
    // as in a fresh process, and never changes the next scenario's.
    const ac = structuredClone(AC)
    let factsPending = 0 // facts agents started and not yet answered
    const seen = {}
    // Each agent call and each reply, in the order they happened (#1001: a step that must wait for another's reply).
    const events = []
    async function agent(prompt, opts = {}) {
      events.push(`call ${opts.label}`)
      try { return await answer(prompt, opts) } finally { events.push(`reply ${opts.label}`) }
    }
    async function answer(prompt, opts = {}) {
      const label = opts.label
      calls.push({ kind: 'agent', label, prompt, schema: opts.schema || null, agentType: opts.agentType || null, model: opts.model || null, effort: opts.effort || null, facts_pending: factsPending })
      const isFacts = /^facts-/.test(label)
      if (isFacts) factsPending++
      // A facts agent answers later the higher its issue number, so a program that does not wait for every
      // facts reply before its first acquire would start an acquire while a later issue's facts are pending.
      if (isFacts) {
        for (let i = 0; i < num(label) * 3; i++) await new Promise(r => setImmediate(r))
        factsPending--
      }
      // A landing agent takes a macrotask, so two landings that were not serialised would interleave their calls.
      if (/^(renew|land|close-out|train)-/.test(label)) await new Promise(r => setImmediate(r))
      // delays ({"<label>": n}) holds that agent n more macrotask turns, so a test can let a child return while the step is pending (#936).
      for (let i = 0; i < ((scenario.delays || {})[label] || 0); i++) await new Promise(r => setImmediate(r))
      const n = seen[label] = (seen[label] || 0) + 1
      const replies = scenario.replies || {}
      if (Object.prototype.hasOwnProperty.call(replies, label)) {
        const r = replies[label]
        const out = structuredClone(Array.isArray(r) ? r[Math.min(n, r.length) - 1] : r)
        if (out === 'throw') throw new Error(`stub agent ${label} threw`)
        // An explicit fix reply that does not say whether it released the lock gets the default answer: released when it made a commit.
        if (/^land-fix-\d+$/.test(label) && out && typeof out === 'object' && !Object.prototype.hasOwnProperty.call(out, 'lock_released')) Object.assign(out, RELEASED(prompt, out))
        const row = NESTED.find(([re]) => re.test(label))
        if (row && out && typeof out === 'object' && !Array.isArray(out)) {
          const base = DEFAULTS.find(([re]) => re.test(label))[1](label, prompt, ac)
          // A record's default lock is moved, and its default checks pass, at the head the reply itself reports.
          if (/^land-record-/.test(label) && typeof out.head === 'string') { base.lock = { verdict: 'moved', lock_sha: out.head }; base.checks.head = out.head }
          for (const k of row[1]) if (!Object.prototype.hasOwnProperty.call(out, k)) out[k] = structuredClone(base[k])
        }
        return out
      }
      const hit = DEFAULTS.find(([re]) => re.test(label))
      if (!hit) throw new Error(`no stub reply for agent label ${label}`)
      return structuredClone({ ...hit[1](label, prompt, ac), ...((scenario.patch || {})[label] || {}) })
    }

    let active = 0
    let maxActive = 0
    let planning = 0
    let maxPlanning = 0
    const childEvents = []
    const childReturns = [] // per child return, the number of calls started before it (#936)
    const childSeen = {}
    async function workflow(ref, a) {
      calls.push({ kind: 'workflow', label: `child-${a.issue}`, script: ref && ref.scriptPath, args: structuredClone(a) })
      const plan = a.mode === 'plan'
      childEvents.push({ event: 'start', issue: a.issue, mode: a.mode })
      if (plan) { planning++; maxPlanning = Math.max(maxPlanning, planning) } else { active++; maxActive = Math.max(maxActive, active) }
      try {
        const t = (scenario.turns || {})[`${a.issue}:${a.mode}`]
        for (let i = 0; i < (Number.isInteger(t) ? t : 5); i++) await new Promise(r => setImmediate(r))
        const n = childSeen[a.issue] = (childSeen[a.issue] || 0) + 1
        const c = (scenario.children || {})[String(a.issue)]
        if (c === 'throw') throw new Error('child failed')
        if (c && typeof c === 'object' && !Array.isArray(c) && typeof c.throw === 'string') throw new Error(c.throw)
        if (c === undefined) return plan ? plannedOf(a) : readyOf(a, ac)
        const out = Array.isArray(c) ? c[Math.min(n, c.length) - 1] : c
        if (out === 'throw') throw new Error('child failed')
        if (out && typeof out === 'object' && typeof out.throw === 'string') throw new Error(out.throw)
        return structuredClone(out)
      } finally {
        if (plan) planning--; else active--
        childEvents.push({ event: 'return', issue: a.issue, mode: a.mode })
        childReturns.push({ issue: a.issue, mode: a.mode, calls: calls.length })
      }
    }
    const parallel = thunks => Promise.all(thunks.map(t => Promise.resolve().then(t).catch(() => null)))
    const pipeline = (items, ...stages) => Promise.all(items.map(async (item, i) => {
      let r = item
      for (const s of stages) {
        try { r = await s(r, item, i) } catch { return null }
      }
      return r
    }))
    const budget = { total: null, spent: () => 0, remaining: () => Infinity }
    const noop = () => {}

    const logs = []
    const result = await run(agent, parallel, pipeline, noop, line => { logs.push(String(line)) }, scenario.args, budget, workflow)
    return JSON.stringify({ result, calls, events, logs, max_active: maxActive, max_planning: maxPlanning, child_events: childEvents, child_returns: childReturns })
  }
}

// One-shot mode (node <harness> <program.js>, scenario on stdin) runs only when this file is the entry module; Node resolves an ESM entry's symlinks, so import.meta.url is its real path.
if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.stdout.write(await makeRunner(readFileSync(process.argv[2], 'utf8'))(JSON.parse(readFileSync(0, 'utf8'))))
}
