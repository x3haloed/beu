import { tool, type Plugin } from '@opencode-ai/plugin';
import { appendFile, mkdir, readFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';

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

const DELTA_PATH = join(homedir(), '.beu', 'state', 'deltas.jsonl');
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
    if (error !== null) return `add_threads: ${error}`;
  }

  if ('remove_threads' in value) {
    const error = validateStringArray(value.remove_threads, { unique: true, maxLength: 160 });
    if (error !== null) return `remove_threads: ${error}`;
  }

  if ('add_constraints' in value) {
    const error = validateStringArray(value.add_constraints, { unique: true, maxLength: 200 });
    if (error !== null) return `add_constraints: ${error}`;
  }

  if ('add_recent' in value) {
    const error = validateStringArray(value.add_recent, { maxItems: 5, maxLength: 200 });
    if (error !== null) return `add_recent: ${error}`;
  }

  if ('set_next' in value) {
    const error = validateStringArray(value.set_next, { minItems: 1, maxLength: 160 });
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
  const nextState: PendingState = {
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
  return `${CONTEXT_PREFIX}\n${JSON.stringify(state, null, 2)}`;
}

function normalizeDelta(value: StateDelta): StateDelta {
  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => item !== undefined)
  ) as StateDelta;
}

export const BeUPlugin: Plugin = async ({ client }) => {
  const injectedSessions = new Set<string>();

  return {
    'chat.message': async (input, output) => {
      if (injectedSessions.has(input.sessionID)) {
        return;
      }

      injectedSessions.add(input.sessionID);

      if (!existsSync(DELTA_PATH)) {
        return;
      }

      try {
        const state = await computeAgentState(DELTA_PATH);
        output.parts.unshift({
          id: `prt_beu-state-${Date.now()}`,
          sessionID: input.sessionID,
          messageID: output.message.id,
          type: 'text',
          text: formatStateContext(state),
          synthetic: true,
        });
      } catch (error) {
        await client.app.log({
          body: {
            service: 'beu-opencode',
            level: 'warn',
            message: 'Failed to inject BEU state context',
            extra: {
              error: error instanceof Error ? error.message : String(error),
            },
          },
        });
      }
    },

    tool: {
      delta: tool({
        description: 'Append a validated state delta to ~/.beu/state/deltas.jsonl',
        args: {
          set_focus: tool.schema.string().min(1).max(200).optional().describe('Replace the current focus with a new one'),
          add_threads: tool.schema.array(tool.schema.string().min(1).max(160)).optional().describe('Add new active threads'),
          remove_threads: tool.schema.array(tool.schema.string().min(1).max(160)).optional().describe('Remove completed or irrelevant threads'),
          add_constraints: tool.schema.array(tool.schema.string().min(1).max(200)).optional().describe('Add newly discovered constraints or invariants'),
          add_recent: tool.schema.array(tool.schema.string().min(1).max(200)).max(5).optional().describe('Append recent meaningful steps'),
          set_next: tool.schema.array(tool.schema.string().min(1).max(160)).min(1).optional().describe('Replace next actions list'),
        },
        async execute(args, context) {
          const delta = normalizeDelta(args as StateDelta);
          const validationError = validateStateDelta(delta);

          if (validationError !== null) {
            throw new Error(validationError);
          }

          await mkdir(dirname(DELTA_PATH), { recursive: true });
          await appendFile(DELTA_PATH, `${JSON.stringify(delta)}\n`, 'utf8');

          context.metadata({
            title: 'State delta',
            metadata: {
              path: DELTA_PATH,
            },
          });

          return `Appended delta to ${DELTA_PATH}`;
        },
      }),
    },
  };
};