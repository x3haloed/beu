const test = require('node:test');
const assert = require('node:assert/strict');
const { mkdtemp, mkdir, writeFile } = require('node:fs/promises');
const { tmpdir } = require('node:os');
const { join } = require('node:path');
const { spawn } = require('node:child_process');

const CLI_PATH = join(__dirname, '..', 'dist', 'compute-agent-state.js');

function runCli(cwd) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [CLI_PATH], {
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

  const result = await runCli(cwd);

  assert.equal(result.code, 0, `stderr: ${result.stderr}`);
  assert.deepEqual(JSON.parse(result.stdout), {
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
  });
});