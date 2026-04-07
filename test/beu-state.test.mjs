import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

import { build } from 'esbuild';

const moduleRoot = await mkdtemp(join(tmpdir(), 'beu-state-module-'));
const bundledModulePath = join(moduleRoot, 'beu-state.mjs');

await build({
  entryPoints: [join(process.cwd(), 'src', 'beu-state.ts')],
  bundle: true,
  platform: 'node',
  format: 'esm',
  outfile: bundledModulePath,
});

const { appendStateDelta, computeAgentState, validateStateDelta } = await import(pathToFileURL(bundledModulePath).href);

test('validateStateDelta rejects unknown properties', () => {
  assert.equal(validateStateDelta({ unexpected: 'value' }), 'Unknown delta property: unexpected');
});

test('validateStateDelta rejects duplicate thread additions', () => {
  assert.equal(
    validateStateDelta({ add_threads: ['keep parity', 'keep parity'] }),
    'add_threads: must not contain duplicate values'
  );
});

test('appendStateDelta creates the parent directory and writes normalized jsonl', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-state-write-'));
  const deltaPath = join(root, '.beu', 'state', 'deltas.jsonl');

  const writtenPath = await appendStateDelta(
    {
      set_focus: 'Preserve parity',
      add_threads: ['share prompt text'],
      set_next: ['write regression tests'],
      add_recent: undefined,
    },
    deltaPath
  );

  assert.equal(writtenPath, deltaPath);
  await stat(join(root, '.beu', 'state'));
  assert.equal(
    await readFile(deltaPath, 'utf8'),
    `${JSON.stringify({
      set_focus: 'Preserve parity',
      add_threads: ['share prompt text'],
      set_next: ['write regression tests'],
    })}\n`
  );
});

test('appendStateDelta rejects invalid deltas without writing a file', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-state-invalid-write-'));
  const deltaPath = join(root, '.beu', 'state', 'deltas.jsonl');

  await assert.rejects(
    appendStateDelta({ set_next: [] }, deltaPath),
    /set_next: must contain at least 1 item/
  );

  await assert.rejects(stat(deltaPath));
});

test('computeAgentState reports invalid json with the source line number', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-state-invalid-json-'));
  const deltaPath = join(root, 'deltas.jsonl');

  await writeFile(
    deltaPath,
    [
      JSON.stringify({
        set_focus: 'Ship tests',
        set_next: ['run them'],
      }),
      '{not-json}',
    ].join('\n'),
    'utf8'
  );

  await assert.rejects(
    computeAgentState(deltaPath),
    /Invalid JSON in .*deltas\.jsonl at line 2/
  );
});

test('computeAgentState removes threads added and removed in the same delta and truncates recent history', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-state-fold-'));
  const deltaPath = join(root, 'deltas.jsonl');

  await writeFile(
    deltaPath,
    [
      JSON.stringify({
        set_focus: 'Keep host behavior aligned',
        add_threads: ['document codex', 'share schema'],
        add_constraints: ['single storage path'],
        add_recent: ['added baseline tests'],
        set_next: ['cover fold edge cases'],
      }),
      JSON.stringify({
        add_threads: ['remove stale docs'],
        remove_threads: ['document codex', 'remove stale docs'],
        add_recent: [
          'covered validation',
          'covered append writes',
          'covered invalid json',
          'covered fold behavior',
          'kept only the latest recent entries',
        ],
        set_next: ['review remaining gaps'],
      }),
    ].join('\n'),
    'utf8'
  );

  assert.deepEqual(await computeAgentState(deltaPath), {
    focus: 'Keep host behavior aligned',
    threads: ['share schema'],
    constraints: ['single storage path'],
    recent: [
      'covered validation',
      'covered append writes',
      'covered invalid json',
      'covered fold behavior',
      'kept only the latest recent entries',
    ],
    next: ['review remaining gaps'],
  });
});

test('computeAgentState rejects a final state that never sets next actions', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-state-missing-next-'));
  const deltaPath = join(root, 'deltas.jsonl');

  await writeFile(
    deltaPath,
    JSON.stringify({
      set_focus: 'Recover context',
      add_threads: ['load prior state'],
    }),
    'utf8'
  );

  await assert.rejects(computeAgentState(deltaPath), /Computed state is invalid: next is required/);
});