#!/usr/bin/env node

import { readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';

type StateDelta = {
  set_focus?: string;
  add_threads?: string[];
  remove_threads?: string[];
  add_constraints?: string[];
  add_recent?: string[];
  set_next?: string[];
};

type AgentState = {
  focus: string;
  threads: string[];
  constraints: string[];
  recent: string[];
  next: string[];
};

type PendingState = {
  focus?: string;
  threads: string[];
  constraints: string[];
  recent: string[];
  next?: string[];
};

const DEFAULT_DELTA_PATH = join(homedir(), '.beu', 'state', 'deltas.jsonl');
const CONTEXT_PREFIX = '[BEU STATE]';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

function validateStringArray(
  value: unknown,
  options: {
    unique?: boolean;
    minItems?: number;
    maxItems?: number;
    maxLength?: number;
  }
): string | null {
  if (!Array.isArray(value)) {
    return 'must be an array of strings';
  }

  if (typeof options.minItems === 'number' && value.length < options.minItems) {
    return `must contain at least ${options.minItems} item${options.minItems === 1 ? '' : 's'}`;
  }

  if (typeof options.maxItems === 'number' && value.length > options.maxItems) {
    return `must contain at most ${options.maxItems} item${options.maxItems === 1 ? '' : 's'}`;
  }

  const seen = new Set<string>();
  for (const item of value) {
    if (!isNonEmptyString(item)) {
      return 'must contain only non-empty strings';
    }

    if (typeof options.maxLength === 'number' && item.length > options.maxLength) {
      return `items must be at most ${options.maxLength} characters long`;
    }

    if (options.unique) {
      if (seen.has(item)) {
        return 'must not contain duplicate values';
      }
      seen.add(item);
    }
  }

  return null;
}

function validateStateDelta(value: unknown): string | null {
  if (!isRecord(value)) {
    return 'delta must be an object';
  }

  const keys = Object.keys(value);
  if (keys.length === 0) {
    return 'delta must include at least one property';
  }

  const allowedKeys = new Set([
    'set_focus',
    'add_threads',
    'remove_threads',
    'add_constraints',
    'add_recent',
    'set_next',
  ]);

  for (const key of keys) {
    if (!allowedKeys.has(key)) {
      return `Unknown delta property: ${key}`;
    }
  }

  if ('set_focus' in value) {
    if (!isNonEmptyString(value.set_focus)) {
      return 'set_focus must be a non-empty string';
    }
    if (value.set_focus.length > 200) {
      return 'set_focus must be at most 200 characters long';
    }
  }

  if ('add_threads' in value) {
    const error = validateStringArray(value.add_threads, { unique: true, maxLength: 160 });
    if (error !== null) {
      return `add_threads: ${error}`;
    }
  }

  if ('remove_threads' in value) {
    const error = validateStringArray(value.remove_threads, { unique: true, maxLength: 160 });
    if (error !== null) {
      return `remove_threads: ${error}`;
    }
  }

  if ('add_constraints' in value) {
    const error = validateStringArray(value.add_constraints, { unique: true, maxLength: 200 });
    if (error !== null) {
      return `add_constraints: ${error}`;
    }
  }

  if ('add_recent' in value) {
    const error = validateStringArray(value.add_recent, { maxItems: 5, maxLength: 200 });
    if (error !== null) {
      return `add_recent: ${error}`;
    }
  }

  if ('set_next' in value) {
    const error = validateStringArray(value.set_next, { minItems: 1, maxLength: 160 });
    if (error !== null) {
      return `set_next: ${error}`;
    }
  }

  return null;
}

function appendUnique(existing: string[], additions: string[]): string[] {
  const nextValues = [...existing];
  const seen = new Set(existing);

  for (const item of additions) {
    if (!seen.has(item)) {
      nextValues.push(item);
      seen.add(item);
    }
  }

  return nextValues;
}

function applyDelta(state: PendingState, delta: StateDelta): PendingState {
  let nextState: PendingState = {
    focus: state.focus,
    threads: [...state.threads],
    constraints: [...state.constraints],
    recent: [...state.recent],
    next: state.next ? [...state.next] : undefined,
  };

  if (delta.set_focus !== undefined) {
    nextState.focus = delta.set_focus;
  }

  if (delta.add_threads !== undefined) {
    nextState.threads = appendUnique(nextState.threads, delta.add_threads);
  }

  if (delta.remove_threads !== undefined) {
    const removals = new Set(delta.remove_threads);
    nextState.threads = nextState.threads.filter((thread) => !removals.has(thread));
  }

  if (delta.add_constraints !== undefined) {
    nextState.constraints = appendUnique(nextState.constraints, delta.add_constraints);
  }

  if (delta.add_recent !== undefined) {
    nextState.recent = [...nextState.recent, ...delta.add_recent].slice(-5);
  }

  if (delta.set_next !== undefined) {
    nextState.next = [...delta.set_next];
  }

  return nextState;
}

function validateFinalState(state: PendingState): AgentState {
  if (!isNonEmptyString(state.focus)) {
    throw new Error('Computed state is invalid: focus is required');
  }

  if (state.focus.length > 200) {
    throw new Error('Computed state is invalid: focus must be at most 200 characters long');
  }

  const threadsError = validateStringArray(state.threads, {
    unique: true,
    maxItems: 8,
    maxLength: 160,
  });
  if (threadsError !== null) {
    throw new Error(`Computed state is invalid: threads ${threadsError}`);
  }

  const constraintsError = validateStringArray(state.constraints, {
    unique: true,
    maxItems: 8,
    maxLength: 200,
  });
  if (constraintsError !== null) {
    throw new Error(`Computed state is invalid: constraints ${constraintsError}`);
  }

  const recentError = validateStringArray(state.recent, {
    maxItems: 5,
    maxLength: 200,
  });
  if (recentError !== null) {
    throw new Error(`Computed state is invalid: recent ${recentError}`);
  }

  if (state.next === undefined) {
    throw new Error('Computed state is invalid: next is required');
  }

  const nextError = validateStringArray(state.next, {
    minItems: 1,
    maxItems: 5,
    maxLength: 160,
  });
  if (nextError !== null) {
    throw new Error(`Computed state is invalid: next ${nextError}`);
  }

  return {
    focus: state.focus,
    threads: state.threads,
    constraints: state.constraints,
    recent: state.recent,
    next: state.next,
  };
}

async function computeAgentState(deltaPath: string): Promise<AgentState> {
  const fileContents = await readFile(deltaPath, 'utf8');
  const lines = fileContents.split(/\r?\n/);

  let state: PendingState = {
    threads: [],
    constraints: [],
    recent: [],
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim();
    if (line.length === 0) {
      continue;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(line);
    } catch (error) {
      throw new Error(
        `Invalid JSON in ${deltaPath} at line ${index + 1}: ${error instanceof Error ? error.message : String(error)}`
      );
    }

    const validationError = validateStateDelta(parsed);
    if (validationError !== null) {
      throw new Error(`Invalid delta in ${deltaPath} at line ${index + 1}: ${validationError}`);
    }

    state = applyDelta(state, parsed as StateDelta);
  }

  return validateFinalState(state);
}

function formatStateContext(state: AgentState): string {
  return `${CONTEXT_PREFIX}

This is your current working state. You are CONTINUING from this state — not starting fresh.

STATE:
${JSON.stringify(state, null, 2)}

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
`;
}

async function main() {
  const inputPath = process.argv[2] ? resolve(process.argv[2]) : resolve(DEFAULT_DELTA_PATH);
  const state = await computeAgentState(inputPath);
  process.stdout.write(formatStateContext(state));
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});