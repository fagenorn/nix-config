import type { EngineInterface, Register } from 'claude-code'

const COMMAND = 'account'
const PASSED_ON = new Set(['list', 'status', 'add', 'use'])

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: COMMAND,
      description: 'Show Claude accounts, or bind this project to one',
      argumentHint: '[<name> | default | add <name> | status]',
      immediate: true,
    })
    const active = await run($, ['active'])
    if (active.isOk) $.ui.status(`account: ${active.text}`)

    return next(e)
  })

  on('command.run', { command: COMMAND }, async ($, e) => {
    const words = e.args.trim().split(/\s+/).filter(Boolean)
    const [first = 'list'] = words
    const argv = PASSED_ON.has(first) ? words.length ? words : ['list'] : ['use', first]
    const ran = await run($, argv)
    if (!ran.isOk || argv[0] !== 'use') return { text: ran.text }

    const active = await run($, ['active'])
    const isSwitch = active.isOk && active.text !== argv[1]
    if (isSwitch) $.ui.status(`account: ${active.text} (${argv[1]} after restart)`)
    else if (active.isOk) $.ui.status(`account: ${active.text}`)

    return {
      text: isSwitch
        ? `${ran.text}\nThis session stays on '${active.text}'. Exit and run \`claude -c\` to continue it as '${argv[1]}'.`
        : ran.text,
    }
  })
}

type Ran = { isOk: boolean; text: string }

async function run($: EngineInterface, argv: string[]): Promise<Ran> {
  try {
    const { exitCode, stdout, stderr } = await $.process.run([
      `${$.plugin.root}/bin/claude-account`,
      ...argv,
    ])

    return { isOk: exitCode === 0, text: (exitCode === 0 ? stdout : stderr || stdout).trim() }
  } catch (error) {
    return { isOk: false, text: `claude-account did not run: ${String(error)}` }
  }
}
