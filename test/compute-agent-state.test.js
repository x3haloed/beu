const test = require('node:test');
const assert = require('node:assert/strict');
const { mkdtemp, mkdir, writeFile } = require('node:fs/promises');
const { tmpdir } = require('node:os');
const { join } = require('node:path');
const { spawn } = require('node:child_process');

const CLI_PATH = join(__dirname, '..', 'dist', 'compute-agent-state.js');

function runCli(cwd, deltaPath) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [CLI_PATH, deltaPath], {
      cwd,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    let stdout = '';
    let stderr = '';

    child.stdout.on('data', (chunk) => {
      stdout += chunk;
    });

    child.stderr.on('data', (chunk) => {
      stderr += chunk;
    });

    child.on('close', (code) => {
      resolve({ code, stdout, stderr });
    });
  });
}

test('computes the current agent state from accumulated deltas', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'beu-state-'));
  const stateDir = join(cwd, '.beu', 'state');
  const deltaPath = join(stateDir, 'deltas.jsonl');

  await mkdir(stateDir, { recursive: true });
  await writeFile(
    deltaPath,
    [
      JSON.stringify({
        set_focus: 'Ship current state tool',
        add_threads: ['design CLI', 'verify folding'],
        add_constraints: ['must stay schema-valid'],
        add_recent: ['created failing test'],
        set_next: ['implement CLI'],
      }),
      JSON.stringify({
        add_threads: ['wire build'],
        remove_threads: ['design CLI'],
        add_recent: [
          'implemented fold logic',
          'trimmed recent list',
          'validated state',
          'verified output',
          'documented usage',
        ],
        set_next: ['ship tool', 'use it from plugin'],
      }),
      '',
    ].join('\n'),
    'utf8'
  );

  const result = await runCli(cwd, deltaPath);

  assert.equal(result.code, 0, `stderr: ${result.stderr}`);
  assert.equal(
    result.stdout,
    `[BEU STATE]

This is your current working state. You are CONTINUING from this state — not starting fresh.

STATE:
${JSON.stringify(
      {
        focus: 'Ship current state tool',
        threads: ['verify folding', 'wire build'],
        constraints: ['must stay schema-valid'],
        recent: [
          'implemented fold logic',
          'trimmed recent list',
          'validated state',
          'verified output',
          'documented usage',
        ],
        next: ['ship tool', 'use it from plugin'],
      },
      null,
      2
    )}

You MUST maintain this state as you work.

Call the delta tool IMMEDIATELY if any of the following become true:
- The focus changes or sharpens
- A new thread appears
- A thread is resolved or irrelevant
- A constraint is discovered
- A meaningful step completes
- The next actions change

Do NOT call delta for minor reasoning or explanation.

If failing to update this state would cause future steps to go in the wrong direction,
you MUST call delta.

Otherwise, continue without calling it.
`
  );
});