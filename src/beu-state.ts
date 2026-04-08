import { appendFile, mkdir, readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';

export type StateDelta = {
  set_focus?: string;
  add_threads?: string[];
  remove_threads?: string[];
  add_constraints?: string[];
  add_recent?: string[];
  set_next?: string[];
};

export type LooseStateDelta = {
  set_focus?: string;
  add_threads?: string | string[];
  remove_threads?: string | string[];
  add_constraints?: string | string[];
  add_recent?: string | string[];
  set_next?: string | string[];
};

export type AgentState = {
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

type StringFieldSpec = {
  kind: 'string';
  minLength: number;
  maxLength: number;
  description: string;
};

type StringArrayFieldSpec = {
  kind: 'string[]';
  itemMinLength: number;
  itemMaxLength: number;
  description: string;
  unique?: boolean;
  minItems?: number;
  maxItems?: number;
};

type StateDeltaFieldSpec = StringFieldSpec | StringArrayFieldSpec;

export const DELTA_PATH = join(homedir(), '.beu', 'state', 'deltas.jsonl');
export const CONTEXT_PREFIX = '[BEU STATE]';
export const DELTA_TOOL_DESCRIPTION = `
Persist a minimal state update when orientation changes.

CALL THIS TOOL IMMEDIATELY if:
- Focus changes or sharpens
- A new thread appears or a thread is resolved
- A constraint is discovered
- A meaningful step completes
- Next actions change

DO NOT call for explanation or minor reasoning.

CRITICAL:
If failing to record this change would cause the next step to go in the wrong direction, you MUST call delta().
`;

export const STATE_DELTA_FIELDS = {
  set_focus: {
    kind: 'string',
    minLength: 1,
    maxLength: 200,
    description: 'Replace the current focus with a new one',
  },
  add_threads: {
    kind: 'string[]',
    itemMinLength: 1,
    itemMaxLength: 160,
    unique: true,
    description: 'Add new active threads',
  },
  remove_threads: {
    kind: 'string[]',
    itemMinLength: 1,
    itemMaxLength: 160,
    unique: true,
    description: 'Remove completed or irrelevant threads',
  },
  add_constraints: {
    kind: 'string[]',
    itemMinLength: 1,
    itemMaxLength: 200,
    unique: true,
    description: 'Add newly discovered constraints or invariants',
  },
  add_recent: {
    kind: 'string[]',
    itemMinLength: 1,
    itemMaxLength: 200,
    maxItems: 5,
    description: 'Append recent meaningful steps (will be truncated in state)',
  },
  set_next: {
    kind: 'string[]',
    itemMinLength: 1,
    itemMaxLength: 160,
    minItems: 1,
    description: 'Replace next actions list',
  },
} as const;

export const STATE_DELTA_FIELD_DESCRIPTIONS = Object.fromEntries(
  Object.entries(STATE_DELTA_FIELDS).map(([key, spec]) => [key, spec.description])
) as Record<keyof typeof STATE_DELTA_FIELDS, string>;

export function createStateDeltaJsonSchemaProperties() {
  return Object.fromEntries(
    Object.entries(STATE_DELTA_FIELDS).map(([key, spec]) => {
      if (spec.kind === 'string') {
        return [
          key,
          {
            type: 'string',
            minLength: spec.minLength,
            maxLength: spec.maxLength,
            description: spec.description,
          },
        ];
      }

      const arraySpec = spec as StringArrayFieldSpec;
      return [
        key,
        {
          anyOf: [
            {
              type: 'string',
              minLength: arraySpec.itemMinLength,
              maxLength: arraySpec.itemMaxLength,
            },
            {
              type: 'array',
              items: {
                type: 'string',
                minLength: arraySpec.itemMinLength,
                maxLength: arraySpec.itemMaxLength,
              },
              ...(arraySpec.unique ? { uniqueItems: true } : {}),
              ...(typeof arraySpec.minItems === 'number' ? { minItems: arraySpec.minItems } : {}),
              ...(typeof arraySpec.maxItems === 'number' ? { maxItems: arraySpec.maxItems } : {}),
            },
          ],
          description: arraySpec.description,
        },
      ];
    })
  );
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0;
}

export function validateStringArray(
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

export function validateStateDelta(value: unknown): string | null {
  const normalizedValue = normalizeDelta(value);
  if (!isRecord(normalizedValue)) {
    return 'delta must be an object';
  }

  const keys = Object.keys(normalizedValue);
  if (keys.length === 0) {
    return 'delta must include at least one property';
  }

  const allowedKeys = new Set(Object.keys(STATE_DELTA_FIELDS));

  for (const key of keys) {
    if (!allowedKeys.has(key)) {
      return `Unknown delta property: ${key}`;
    }
  }

  if ('set_focus' in normalizedValue) {
    if (!isNonEmptyString(normalizedValue.set_focus)) {
      return 'set_focus must be a non-empty string';
    }
    if (normalizedValue.set_focus.length > STATE_DELTA_FIELDS.set_focus.maxLength) {
      return `set_focus must be at most ${STATE_DELTA_FIELDS.set_focus.maxLength} characters long`;
    }
  }

  if ('add_threads' in normalizedValue) {
    const error = validateStringArray(normalizedValue.add_threads, {
      unique: STATE_DELTA_FIELDS.add_threads.unique,
      maxLength: STATE_DELTA_FIELDS.add_threads.itemMaxLength,
    });
    if (error !== null) return `add_threads: ${error}`;
  }

  if ('remove_threads' in normalizedValue) {
    const error = validateStringArray(normalizedValue.remove_threads, {
      unique: STATE_DELTA_FIELDS.remove_threads.unique,
      maxLength: STATE_DELTA_FIELDS.remove_threads.itemMaxLength,
    });
    if (error !== null) return `remove_threads: ${error}`;
  }

  if ('add_constraints' in normalizedValue) {
    const error = validateStringArray(normalizedValue.add_constraints, {
      unique: STATE_DELTA_FIELDS.add_constraints.unique,
      maxLength: STATE_DELTA_FIELDS.add_constraints.itemMaxLength,
    });
    if (error !== null) return `add_constraints: ${error}`;
  }

  if ('add_recent' in normalizedValue) {
    const error = validateStringArray(normalizedValue.add_recent, {
      maxItems: STATE_DELTA_FIELDS.add_recent.maxItems,
      maxLength: STATE_DELTA_FIELDS.add_recent.itemMaxLength,
    });
    if (error !== null) return `add_recent: ${error}`;
  }

  if ('set_next' in normalizedValue) {
    const error = validateStringArray(normalizedValue.set_next, {
      minItems: STATE_DELTA_FIELDS.set_next.minItems,
      maxLength: STATE_DELTA_FIELDS.set_next.itemMaxLength,
    });
    if (error !== null) return `set_next: ${error}`;
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
  return {
    focus: delta.set_focus ?? state.focus,
    threads:
      delta.remove_threads !== undefined
        ? appendUnique(state.threads, delta.add_threads ?? []).filter(
            (thread) => !new Set(delta.remove_threads).has(thread)
          )
        : delta.add_threads !== undefined
          ? appendUnique(state.threads, delta.add_threads)
          : [...state.threads],
    constraints:
      delta.add_constraints !== undefined
        ? appendUnique(state.constraints, delta.add_constraints)
        : [...state.constraints],
    recent:
      delta.add_recent !== undefined
        ? [...state.recent, ...delta.add_recent].slice(-5)
        : [...state.recent],
    next: delta.set_next !== undefined ? [...delta.set_next] : state.next ? [...state.next] : undefined,
  };
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

export async function computeAgentState(deltaPath: string): Promise<AgentState> {
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

    const normalizedDelta = normalizeDelta(parsed);
    const validationError = validateStateDelta(normalizedDelta);
    if (validationError !== null) {
      throw new Error(`Invalid delta in ${deltaPath} at line ${index + 1}: ${validationError}`);
    }

    state = applyDelta(state, normalizedDelta);
  }

  return validateFinalState(state);
}

export function formatStateContext(state: AgentState): string {
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

export function formatCodexSessionStartOutput(state: AgentState): string {
  return JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'SessionStart',
      additionalContext: formatStateContext(state),
    },
  });
}

function normalizeStringArrayField(value: unknown): unknown {
  return typeof value === 'string' ? [value] : value;
}

export function normalizeDelta(value: unknown): StateDelta {
  if (!isRecord(value)) {
    return value as StateDelta;
  }

  return Object.fromEntries(
    Object.entries(value)
      .filter(([, item]) => item !== undefined)
      .map(([key, item]) => {
        const spec = STATE_DELTA_FIELDS[key as keyof typeof STATE_DELTA_FIELDS];
        if (spec?.kind === 'string[]') {
          return [key, normalizeStringArrayField(item)];
        }
        return [key, item];
      })
  ) as StateDelta;
}

export async function appendStateDelta(delta: unknown, deltaPath: string = DELTA_PATH): Promise<string> {
  const normalizedDelta = normalizeDelta(delta);
  const validationError = validateStateDelta(normalizedDelta);

  if (validationError !== null) {
    throw new Error(validationError);
  }

  await mkdir(dirname(deltaPath), { recursive: true });
  await appendFile(deltaPath, `${JSON.stringify(normalizedDelta)}\n`, 'utf8');
  return deltaPath;
}
