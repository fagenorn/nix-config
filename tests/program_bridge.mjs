// Program bridge: runs a Workflow program (deliver-standard.js, deliver-batch.js,
// ...) in-process and relays each agent() call to a Python actor over a line
// protocol on stdin/stdout. Usage: node tests/program_bridge.mjs
//
// Wire format (the contract of this file and tests/program_bridge.py; exact).
// One JSON object per line, UTF-8, newline-terminated.
//  1. Python -> node, first line: {"program": "<absolute path of the .js>", "args": {...}}
//  2. Node -> Python, agent call: {"type": "agent", "id": <int, from 1, unique per run>,
//     "label": <opts.label or null>, "program": "<basename without .js of the program that
//     made the call>", "issue": <int or null>, "mode": <string or null>, "prompt": "<prompt>",
//     "schema": <opts.schema or null>, "agentType": <opts.agentType or null>}.
//     issue/mode are those of the running program's args (args.issue when an integer, else
//     null; args.mode when a string, else null); for a child run they are the child's args.
//  3. Python -> node, answer: {"id": <same id>, "reply": <any JSON>} resolves that call;
//     {"id": <same id>, "throw": "<message>"} rejects it with new Error(message). Answers
//     may arrive in any order; node matches them by id.
//  4. Node -> Python, child returned: {"type": "child", "issue": <int or null>, "mode":
//     <string or null>, "program": "<basename>", "result": <the child's return or null>}
//     (no answer expected). workflow(ref, a) loads ref.scriptPath and runs it in-process
//     with a as its args and the same relaying agent; a child throw propagates to the
//     caller's await.
//  5. Node -> Python, last line: {"type": "result", "result": <return or null>, "error":
//     <string or null>, "logs": [<each log() line>]}, then node exits 0, only once that
//     line has been written out whole (the exit is made from the write's completion
//     callback: an immediate exit can drop buffered output when stdout is a pipe).
import { createInterface } from 'node:readline'
import { readFileSync } from 'node:fs'
import { basename } from 'node:path'

const rl = createInterface({ input: process.stdin })
const lines = rl[Symbol.asyncIterator]()
const pending = new Map()
const logs = []
let nextId = 1

const send = (obj, done) => process.stdout.write(JSON.stringify(obj) + '\n', done)

const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const load = path => {
  const body = readFileSync(path, 'utf8').replace(/^export const meta\b/m, 'const meta')
  return new AsyncFunction('agent', 'parallel', 'pipeline', 'phase', 'log', 'args', 'budget', 'workflow', body)
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

const runProgram = async (path, args) => {
  const program = basename(path).replace(/\.js$/, '')
  const issue = Number.isInteger(args?.issue) ? args.issue : null
  const mode = typeof args?.mode === 'string' ? args.mode : null
  const agent = (prompt, opts = {}) => new Promise((resolve, reject) => {
    const id = nextId++
    pending.set(id, { resolve, reject })
    send({
      type: 'agent',
      id,
      label: opts.label ?? null,
      program,
      issue,
      mode,
      prompt,
      schema: opts.schema ?? null,
      agentType: opts.agentType ?? null,
    })
  })
  const workflow = async (ref, a) => {
    const result = await runProgram(ref.scriptPath, a)
    send({
      type: 'child',
      issue: Number.isInteger(a?.issue) ? a.issue : null,
      mode: typeof a?.mode === 'string' ? a.mode : null,
      program: basename(ref.scriptPath).replace(/\.js$/, ''),
      result: result ?? null,
    })
    return result
  }
  const run = load(path)
  return run(agent, parallel, pipeline, noop, line => { logs.push(String(line)) }, args, budget, workflow)
}

// Answers are routed on a background reader; the first line is the config.
const first = await lines.next()
const config = JSON.parse(first.value)
;(async () => {
  for await (const line of lines) {
    if (!line.trim()) continue
    const answer = JSON.parse(line)
    const call = pending.get(answer.id)
    if (!call) continue
    pending.delete(answer.id)
    if (typeof answer.throw === 'string') call.reject(new Error(answer.throw))
    else call.resolve(answer.reply)
  }
})()

let result = null
let error = null
try {
  result = (await runProgram(config.program, config.args ?? {})) ?? null
} catch (e) {
  error = e instanceof Error ? e.message : String(e)
}
rl.close()
send({ type: 'result', result, error, logs }, () => process.exit(0))
