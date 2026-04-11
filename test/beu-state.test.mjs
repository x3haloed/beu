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

const {
  appendOrientationSurvey,
  appendStateDelta,
  computeAgentState,
  normalizeDelta,
  validateOrientationSurvey,
  validateStateDelta,
} = await import(pathToFileURL(bundledModulePath).href);

test('validateStateDelta rejects unknown properties', () => {
  assert.equal(validateStateDelta({ unexpected: 'value' }), 'Unknown delta property: unexpected');
});

test('validateStateDelta rejects duplicate thread additions', () => {
  assert.equal(
    validateStateDelta({ add_threads: ['keep parity', 'keep parity'] }),
    'add_threads: must not contain duplicate values'
  );
});

test('validateStateDelta accepts string shorthand for array fields', () => {
  assert.equal(
    validateStateDelta({
      set_focus: 'Update vault with new answers',
      add_recent: 'Player repos confirmed',
      set_next: 'record answer',
    }),
    null
  );
});

test('validateStateDelta requires both fields for add_hypothesis', () => {
  assert.equal(
    validateStateDelta({
      add_hypothesis: {
        hypothesis: 'The failure only happens in Codex SessionStart hooks',
      },
    }),
    'add_hypothesis: invalidated_by must be a non-empty string'
  );
});

test('validateStateDelta requires index and reason for invalidate_hypothesis', () => {
  assert.equal(
    validateStateDelta({
      invalidate_hypothesis: {
        index: 0,
      },
    }),
    'invalidate_hypothesis: index: must be between 1 and 9007199254740991'
  );
});

test('normalizeDelta converts string shorthand to canonical array fields', () => {
  assert.deepEqual(
    normalizeDelta({
      add_threads: 'GCS migration',
      remove_threads: 'old migration note',
      add_constraints: 'player repos confirmed',
      add_recent: 'updated vault',
      set_next: 'continue implementation',
    }),
    {
      add_threads: ['GCS migration'],
      remove_threads: ['old migration note'],
      add_constraints: ['player repos confirmed'],
      add_recent: ['updated vault'],
      set_next: ['continue implementation'],
    }
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

test('appendStateDelta writes canonical arrays for string shorthand fields', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-state-loose-write-'));
  const deltaPath = join(root, '.beu', 'state', 'deltas.jsonl');

  await appendStateDelta(
    {
      set_focus: 'Update vault with new answers',
      add_recent: 'Player repos confirmed',
      set_next: 'record answer',
    },
    deltaPath
  );

  assert.equal(
    await readFile(deltaPath, 'utf8'),
    `${JSON.stringify({
      set_focus: 'Update vault with new answers',
      add_recent: ['Player repos confirmed'],
      set_next: ['record answer'],
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

test('validateOrientationSurvey rejects an unknown property', () => {
  assert.equal(validateOrientationSurvey({ survey_version: 'v1', unexpected: true }), 'Unknown survey property: unexpected');
});

test('appendOrientationSurvey creates the parent directory and writes a timestamped jsonl record', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-survey-write-'));
  const surveyPath = join(root, '.beu', 'state', 'surveys.jsonl');

  const writtenPath = await appendOrientationSurvey(
    {
      survey_version: 'v1',
      agent_name_reported: 'Codex',
      identity_confidence: 5,
      intended_next_action: 'Inspect the repo hooks.',
    },
    surveyPath,
    new Date('2026-04-08T12:34:56.000Z')
  );

  assert.equal(writtenPath, surveyPath);
  await stat(join(root, '.beu', 'state'));
  assert.equal(
    await readFile(surveyPath, 'utf8'),
    `${JSON.stringify({
      recorded_at: '2026-04-08T12:34:56.000Z',
      survey_version: 'v1',
      agent_name_reported: 'Codex',
      identity_confidence: 5,
      intended_next_action: 'Inspect the repo hooks.',
    })}\n`
  );
});

test('appendOrientationSurvey rejects invalid surveys without writing a file', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-survey-invalid-write-'));
  const surveyPath = join(root, '.beu', 'state', 'surveys.jsonl');

  await assert.rejects(
    appendOrientationSurvey({ survey_version: 'v2' }, surveyPath),
    /survey_version must be v1/
  );

  await assert.rejects(stat(surveyPath));
});

test('computeAgentState heals string shorthand from existing delta logs', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-state-loose-fold-'));
  const deltaPath = join(root, 'deltas.jsonl');

  await writeFile(
    deltaPath,
    JSON.stringify({
      set_focus: 'Update vault',
      add_threads: 'confirm player repos',
      add_recent: 'Player repos confirmed',
      set_next: 'continue vault update',
    }),
    'utf8'
  );

  assert.deepEqual(await computeAgentState(deltaPath), {
    focus: 'Update vault',
    threads: ['confirm player repos'],
    constraints: [],
    hypotheses: [],
    recent: ['Player repos confirmed'],
    next: ['continue vault update'],
  });
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
    hypotheses: [],
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

test('computeAgentState keeps only active hypotheses after invalidation', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-state-hypotheses-'));
  const deltaPath = join(root, 'deltas.jsonl');

  await writeFile(
    deltaPath,
    [
      JSON.stringify({
        set_focus: 'Debug SessionStart recovery',
        add_hypothesis: {
          hypothesis: 'The hook is emitting non-JSON output',
          invalidated_by: 'The exact hook command parses as valid JSON',
        },
        set_next: ['reproduce the failure'],
      }),
      JSON.stringify({
        add_hypothesis: {
          hypothesis: 'Hermes prompt formatting drift is causing the mismatch',
          invalidated_by: 'Hermes and TypeScript formatters are byte-for-byte aligned',
        },
      }),
      JSON.stringify({
        invalidate_hypothesis: {
          index: 1,
          reason: 'The exact live hook command parsed as valid JSON after the installer update',
        },
        add_recent: ['verified the hook output'],
      }),
    ].join('\n'),
    'utf8'
  );

  assert.deepEqual(await computeAgentState(deltaPath), {
    focus: 'Debug SessionStart recovery',
    threads: [],
    constraints: [],
    hypotheses: [
      {
        hypothesis: 'Hermes prompt formatting drift is causing the mismatch',
        invalidated_by: 'Hermes and TypeScript formatters are byte-for-byte aligned',
      },
    ],
    recent: ['verified the hook output'],
    next: ['reproduce the failure'],
  });
});

test('computeAgentState rejects invalidated hypothesis indexes outside the active range', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-state-hypothesis-range-'));
  const deltaPath = join(root, 'deltas.jsonl');

  await writeFile(
    deltaPath,
    [
      JSON.stringify({
        set_focus: 'Track active hypotheses',
        add_hypothesis: {
          hypothesis: 'State is stale',
          invalidated_by: 'A recomputation matches the current workspace',
        },
        set_next: ['test invalidation'],
      }),
      JSON.stringify({
        invalidate_hypothesis: {
          index: 2,
          reason: 'No second hypothesis was active',
        },
      }),
    ].join('\n'),
    'utf8'
  );

  await assert.rejects(
    computeAgentState(deltaPath),
    /invalidate_hypothesis index 2 is out of range for 1 active hypothesis/
  );
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
