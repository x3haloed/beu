const test = require('node:test');
const assert = require('node:assert/strict');
const { mkdtemp, mkdir, writeFile } = require('node:fs/promises');
const { tmpdir } = require('node:os');
const { join } = require('node:path');
const { spawn } = require('node:child_process');
const { build } = require('esbuild');

let CLI_PATH;

test.before(async () => {
  const buildRoot = await mkdtemp(join(tmpdir(), 'beu-compute-cli-'));
  CLI_PATH = join(buildRoot, 'compute-agent-state.js');

  await build({
    entryPoints: [join(__dirname, '..', 'src', 'compute-agent-state.ts')],
    bundle: true,
    platform: 'node',
    format: 'cjs',
    outfile: CLI_PATH,
  });
});

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
        add_hypothesis: {
          hypothesis: 'The CLI should print the same state across hosts',
          invalidated_by: 'Two hosts compute different state from the same delta log',
        },
        add_recent: ['created failing test'],
        set_next: ['implement CLI'],
      }),
      JSON.stringify({
        add_threads: ['wire build'],
        remove_threads: ['design CLI'],
        invalidate_hypothesis: {
          index: 1,
          reason: 'The shared state module now drives every host integration',
        },
        add_hypothesis: {
          hypothesis: 'Codex SessionStart output still needs a JSON mode',
          invalidated_by: 'The hook command emits a valid SessionStart JSON payload',
        },
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
        hypotheses: [
          {
            hypothesis: 'Codex SessionStart output still needs a JSON mode',
            invalidated_by: 'The hook command emits a valid SessionStart JSON payload',
          },
        ],
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

ACTIVE HYPOTHESES:
1. Codex SessionStart output still needs a JSON mode
   Invalidated by: The hook command emits a valid SessionStart JSON payload

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

[SURVEY PROTOCOL]
Before responding to the user, call \`orientation_survey\` exactly once for this session.
Use it only now to record startup orientation metrics.
`
  );
});

test('can emit Codex SessionStart hook JSON output', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'beu-codex-hook-'));
  const stateDir = join(cwd, '.beu', 'state');
  const deltaPath = join(stateDir, 'deltas.jsonl');

  await mkdir(stateDir, { recursive: true });
  await writeFile(
    deltaPath,
    `${JSON.stringify({
      set_focus: 'Debug Codex hook',
      set_next: ['emit JSON'],
    })}\n`,
    'utf8'
  );

  const child = spawn(process.execPath, [CLI_PATH, '--codex-session-start-json', deltaPath], {
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

  const code = await new Promise((resolve) => {
    child.on('close', resolve);
  });

  assert.equal(code, 0, `stderr: ${stderr}`);

  const parsed = JSON.parse(stdout);
  assert.deepEqual(Object.keys(parsed), ['hookSpecificOutput']);
  assert.equal(parsed.hookSpecificOutput.hookEventName, 'SessionStart');
  assert.match(parsed.hookSpecificOutput.additionalContext, /^\[BEU STATE\]/);
  assert.match(parsed.hookSpecificOutput.additionalContext, /"focus": "Debug Codex hook"/);
});
