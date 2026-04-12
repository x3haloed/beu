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
  appendConstraintCompression,
  appendHypothesisCompression,
  appendOrientationSurvey,
  appendStateDelta,
  computeAgentState,
  formatStateContext,
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

test('validateStateDelta accepts compression deltas', () => {
  assert.equal(
    validateStateDelta({
      remove_constraints: ['old invariant'],
      add_constraints: ['compressed invariant'],
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
      remove_constraints: 'old invariant',
      add_recent: 'updated vault',
      set_next: 'continue implementation',
    }),
    {
      add_threads: ['GCS migration'],
      remove_threads: ['old migration note'],
      add_constraints: ['player repos confirmed'],
      remove_constraints: ['old invariant'],
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

test('appendStateDelta injects thread removals when adding threads would overflow', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-state-thread-trim-'));
  const deltaPath = join(root, '.beu', 'state', 'deltas.jsonl');

  await appendStateDelta(
    {
      set_focus: 'Trim threads',
      add_threads: ['a', 'b', 'c', 'd', 'e', 'f', 'g'],
      set_next: ['continue'],
    },
    deltaPath
  );

  await appendStateDelta(
    {
      add_threads: ['h', 'i'],
    },
    deltaPath
  );

  const lines = (await readFile(deltaPath, 'utf8')).trim().split(/\r?\n/);
  assert.match(lines[1], /"remove_threads":\["a"\]/);

  assert.deepEqual(await computeAgentState(deltaPath), {
    focus: 'Trim threads',
    threads: ['b', 'c', 'd', 'e', 'f', 'g', 'h', 'i'],
    constraints: [],
    hypotheses: [],
    recent: [],
    next: ['continue'],
  });
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

test('computeAgentState trims recent history and next actions to the newest entries', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-state-trim-'));
  const deltaPath = join(root, 'deltas.jsonl');

  await writeFile(
    deltaPath,
    JSON.stringify({
      set_focus: 'Trim all the things',
      add_threads: ['thread 1', 'thread 2', 'thread 3', 'thread 4', 'thread 5', 'thread 6', 'thread 7', 'thread 8', 'thread 9'],
      add_recent: ['r1', 'r2', 'r3', 'r4', 'r5', 'r6'],
      set_next: ['n1', 'n2', 'n3', 'n4', 'n5', 'n6'],
    }) + '\n',
    'utf8'
  );

  assert.deepEqual(await computeAgentState(deltaPath), {
    focus: 'Trim all the things',
    threads: ['thread 2', 'thread 3', 'thread 4', 'thread 5', 'thread 6', 'thread 7', 'thread 8', 'thread 9'],
    constraints: [],
    hypotheses: [],
    recent: ['r2', 'r3', 'r4', 'r5', 'r6'],
    next: ['n2', 'n3', 'n4', 'n5', 'n6'],
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

test('computeAgentState asks for hypothesis compression when hypotheses reach capacity', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-state-hypothesis-compress-note-'));
  const deltaPath = join(root, 'deltas.jsonl');

  await writeFile(
    deltaPath,
    JSON.stringify({
      set_focus: 'Keep hypotheses compact',
      set_next: ['compress hypotheses'],
      add_hypothesis: {
        hypothesis: 'hypothesis 1',
        invalidated_by: 'evidence 1',
      },
    }) + '\n' +
      JSON.stringify({
        add_hypothesis: {
          hypothesis: 'hypothesis 2',
          invalidated_by: 'evidence 2',
        },
      }) + '\n' +
      JSON.stringify({
        add_hypothesis: {
          hypothesis: 'hypothesis 3',
          invalidated_by: 'evidence 3',
        },
      }) + '\n' +
      JSON.stringify({
        add_hypothesis: {
          hypothesis: 'hypothesis 4',
          invalidated_by: 'evidence 4',
        },
      }) + '\n' +
      JSON.stringify({
        add_hypothesis: {
          hypothesis: 'hypothesis 5',
          invalidated_by: 'evidence 5',
        },
      }) + '\n' +
      JSON.stringify({
        add_hypothesis: {
          hypothesis: 'hypothesis 6',
          invalidated_by: 'evidence 6',
        },
      }) + '\n' +
      JSON.stringify({
        add_hypothesis: {
          hypothesis: 'hypothesis 7',
          invalidated_by: 'evidence 7',
        },
      }) + '\n' +
      JSON.stringify({
        add_hypothesis: {
          hypothesis: 'hypothesis 8',
          invalidated_by: 'evidence 8',
        },
      }) + '\n',
    'utf8'
  );

  const state = await computeAgentState(deltaPath);
  const context = formatStateContext(state);

  assert.equal(state.hypotheses.length, 8);
  assert.match(context, /HYPOTHESIS COMPACTION REQUIRED:/);
  assert.match(context, /call `compress`/);
  assert.doesNotMatch(context, /CONSTRAINT COMPACTION REQUIRED:/);
});

test('appendHypothesisCompression replaces the current hypotheses with one compressed hypothesis', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-state-hypothesis-compress-write-'));
  const deltaPath = join(root, 'deltas.jsonl');

  await writeFile(
    deltaPath,
    [
      JSON.stringify({
        set_focus: 'Keep hypotheses compact',
        set_next: ['compress hypotheses'],
        add_hypothesis: {
          hypothesis: 'hypothesis 1',
          invalidated_by: 'evidence 1',
        },
      }),
      JSON.stringify({
        add_hypothesis: {
          hypothesis: 'hypothesis 2',
          invalidated_by: 'evidence 2',
        },
      }),
    ].join('\n') + '\n',
    'utf8'
  );

  await appendHypothesisCompression('compressed summary hypothesis', deltaPath);

  assert.deepEqual(await computeAgentState(deltaPath), {
    focus: 'Keep hypotheses compact',
    threads: [],
    constraints: [],
    hypotheses: [
      {
        hypothesis: 'compressed summary hypothesis',
        invalidated_by: 'Evidence that the compressed summary no longer captures the active hypotheses.',
      },
    ],
    recent: [],
    next: ['compress hypotheses'],
  });
});

test('computeAgentState asks for compression when constraints reach capacity', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-state-compress-note-'));
  const deltaPath = join(root, 'deltas.jsonl');

  await writeFile(
    deltaPath,
    JSON.stringify({
      set_focus: 'Keep state compact',
      add_constraints: [
        'constraint 1',
        'constraint 2',
        'constraint 3',
        'constraint 4',
        'constraint 5',
        'constraint 6',
        'constraint 7',
        'constraint 8',
      ],
      set_next: ['compress constraints'],
    }),
    'utf8'
  );

  const state = await computeAgentState(deltaPath);
  const context = formatStateContext(state);

  assert.equal(state.constraints.length, 8);
  assert.match(context, /CONSTRAINT COMPACTION REQUIRED:/);
  assert.match(context, /call `compress`/);
});

test('appendConstraintCompression replaces the current constraints with one compressed constraint', async () => {
  const root = await mkdtemp(join(tmpdir(), 'beu-state-compress-write-'));
  const deltaPath = join(root, 'deltas.jsonl');

  await writeFile(
    deltaPath,
    [
      JSON.stringify({
        set_focus: 'Keep state compact',
        add_constraints: ['old invariant 1', 'old invariant 2'],
        set_next: ['compress constraints'],
      }),
    ].join('\n') + '\n',
    'utf8'
  );

  await appendConstraintCompression('compressed invariant', deltaPath);

  assert.deepEqual(await computeAgentState(deltaPath), {
    focus: 'Keep state compact',
    threads: [],
    constraints: ['compressed invariant'],
    hypotheses: [],
    recent: [],
    next: ['compress constraints'],
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
