import { appendFile, mkdir, readFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';

export type StateDelta = {
  set_focus?: string;
  add_threads?: string[];
  remove_threads?: string[];
  add_constraints?: string[];
  add_hypothesis?: HypothesisRecord;
  invalidate_hypothesis?: HypothesisInvalidation;
  add_recent?: string[];
  set_next?: string[];
};

export type LooseStateDelta = {
  set_focus?: string;
  add_threads?: string | string[];
  remove_threads?: string | string[];
  add_constraints?: string | string[];
  add_hypothesis?: HypothesisRecord;
  invalidate_hypothesis?: HypothesisInvalidation;
  add_recent?: string | string[];
  set_next?: string | string[];
};

export type HypothesisRecord = {
  hypothesis: string;
  invalidated_by: string;
};

export type HypothesisInvalidation = {
  index: number;
  reason: string;
};

export type AgentState = {
  focus: string;
  threads: string[];
  constraints: string[];
  hypotheses: HypothesisRecord[];
  recent: string[];
  next: string[];
};

export type OrientationSurvey = {
  survey_version: 'v1';
  agent_name_reported?: string;
  user_name_reported?: string;
  identity_confidence?: number;
  task_state_confidence?: number;
  next_step_confidence?: number;
  resume_vs_restart?: 'resuming' | 'partially_resuming' | 'restarting';
  ambiguity_types?: Array<'identity' | 'task' | 'state' | 'constraints' | 'next_step' | 'none'>;
  would_act_now?: boolean;
  risk_of_wrong_action?: number;
  missing_critical_context?: string;
  intended_next_action?: string;
};

type PendingState = {
  focus?: string;
  threads: string[];
  constraints: string[];
  hypotheses: HypothesisRecord[];
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

type ObjectFieldSpec = {
  kind: 'object';
  description: string;
  schema: Record<string, unknown>;
};

type StateDeltaFieldSpec = StringFieldSpec | StringArrayFieldSpec | ObjectFieldSpec;

export const DELTA_PATH = join(homedir(), '.beu', 'state', 'deltas.jsonl');
export const SURVEY_PATH = join(homedir(), '.beu', 'state', 'surveys.jsonl');
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
export const ORIENTATION_SURVEY_TOOL_DESCRIPTION = `
Record a one-time orientation survey for this fresh session.

Call this tool immediately at session start before doing substantive work.

Keep the response minimal and only include fields you can answer confidently.
Omit any field you cannot answer.
`;
export const ORIENTATION_SURVEY_SESSION_START_INSTRUCTION = `[SURVEY PROTOCOL]
Before responding to the user, call \`orientation_survey\` exactly once for this session.
Use it only now to record startup orientation metrics.`;

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
  add_hypothesis: {
    kind: 'object',
    description:
      'Record a strong, falsifiable belief about the user, agent, environment, or working context that you are relying on. If you act on it, you must record the concrete evidence that would prove it wrong.',
    schema: {
      type: 'object',
      additionalProperties: false,
      required: ['hypothesis', 'invalidated_by'],
      properties: {
        hypothesis: {
          type: 'string',
          minLength: 1,
          maxLength: 200,
          description: 'The strong, falsifiable belief you are relying on',
        },
        invalidated_by: {
          type: 'string',
          minLength: 1,
          maxLength: 200,
          description: 'The concrete evidence that would prove this belief wrong',
        },
      },
    },
  },
  invalidate_hypothesis: {
    kind: 'object',
    description: 'Invalidate an active hypothesis by its 1-based displayed index, with the reason it was invalidated',
    schema: {
      type: 'object',
      additionalProperties: false,
      required: ['index', 'reason'],
      properties: {
        index: {
          type: 'integer',
          minimum: 1,
          description: '1-based index from the currently displayed active hypothesis list',
        },
        reason: {
          type: 'string',
          minLength: 1,
          maxLength: 200,
          description: 'Why the hypothesis was found to be invalid',
        },
      },
    },
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

export const ORIENTATION_SURVEY_FIELDS = {
  survey_version: {
    kind: 'string',
    minLength: 2,
    maxLength: 8,
    description: 'Survey schema version. Always use v1.',
  },
  agent_name_reported: {
    kind: 'string',
    minLength: 1,
    maxLength: 80,
    description: 'Reported name of the agent, if confidently known',
  },
  user_name_reported: {
    kind: 'string',
    minLength: 1,
    maxLength: 80,
    description: 'Reported name of the user, if confidently known',
  },
  identity_confidence: {
    kind: 'integer',
    minimum: 1,
    maximum: 5,
    description: 'Confidence in identity orientation from 1 to 5',
  },
  task_state_confidence: {
    kind: 'integer',
    minimum: 1,
    maximum: 5,
    description: 'Confidence in task and state orientation from 1 to 5',
  },
  next_step_confidence: {
    kind: 'integer',
    minimum: 1,
    maximum: 5,
    description: 'Confidence in the next concrete action from 1 to 5',
  },
  resume_vs_restart: {
    kind: 'enum',
    values: ['resuming', 'partially_resuming', 'restarting'],
    description: 'Whether this feels like resuming, partially resuming, or restarting',
  },
  ambiguity_types: {
    kind: 'enum[]',
    values: ['identity', 'task', 'state', 'constraints', 'next_step', 'none'],
    description: 'Types of ambiguity currently present',
    unique: true,
    maxItems: 6,
  },
  would_act_now: {
    kind: 'boolean',
    description: 'Whether you would proceed with action now without asking for clarification',
  },
  risk_of_wrong_action: {
    kind: 'integer',
    minimum: 1,
    maximum: 5,
    description: 'Estimated risk that the next action would be wrong, from 1 to 5',
  },
  missing_critical_context: {
    kind: 'string',
    minLength: 1,
    maxLength: 240,
    description: 'Short description of any critical missing context',
  },
  intended_next_action: {
    kind: 'string',
    minLength: 1,
    maxLength: 240,
    description: 'Short description of the next action you intend to take',
  },
} as const;

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

      if (spec.kind === 'object') {
        return [key, { ...spec.schema, description: spec.description }];
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

export function createOrientationSurveyJsonSchemaProperties() {
  return Object.fromEntries(
    Object.entries(ORIENTATION_SURVEY_FIELDS).map(([key, spec]) => {
      switch (spec.kind) {
        case 'string':
          return [
            key,
            {
              type: 'string',
              minLength: spec.minLength,
              maxLength: spec.maxLength,
              description: spec.description,
            },
          ];
        case 'integer':
          return [
            key,
            {
              type: 'integer',
              minimum: spec.minimum,
              maximum: spec.maximum,
              description: spec.description,
            },
          ];
        case 'enum':
          return [
            key,
            {
              type: 'string',
              enum: spec.values,
              description: spec.description,
            },
          ];
        case 'enum[]':
          return [
            key,
            {
              type: 'array',
              items: {
                type: 'string',
                enum: spec.values,
              },
              uniqueItems: spec.unique ?? false,
              ...(typeof spec.maxItems === 'number' ? { maxItems: spec.maxItems } : {}),
              description: spec.description,
            },
          ];
        case 'boolean':
          return [
            key,
            {
              type: 'boolean',
              description: spec.description,
            },
          ];
      }
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

function validateIntegerInRange(value: unknown, minimum: number, maximum: number): string | null {
  if (!Number.isInteger(value)) {
    return 'must be an integer';
  }
  if ((value as number) < minimum || (value as number) > maximum) {
    return `must be between ${minimum} and ${maximum}`;
  }
  return null;
}

function validateHypothesisRecord(value: unknown): string | null {
  if (!isRecord(value)) {
    return 'must be an object';
  }

  if (!isNonEmptyString(value.hypothesis)) {
    return 'hypothesis must be a non-empty string';
  }
  if (value.hypothesis.length > 200) {
    return 'hypothesis must be at most 200 characters long';
  }

  if (!isNonEmptyString(value.invalidated_by)) {
    return 'invalidated_by must be a non-empty string';
  }
  if (value.invalidated_by.length > 200) {
    return 'invalidated_by must be at most 200 characters long';
  }

  return null;
}

function validateHypothesisInvalidation(value: unknown): string | null {
  if (!isRecord(value)) {
    return 'must be an object';
  }

  const indexError = validateIntegerInRange(value.index, 1, Number.MAX_SAFE_INTEGER);
  if (indexError !== null) {
    return `index: ${indexError}`;
  }

  if (!isNonEmptyString(value.reason)) {
    return 'reason must be a non-empty string';
  }
  if (value.reason.length > 200) {
    return 'reason must be at most 200 characters long';
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

  if ('add_hypothesis' in normalizedValue) {
    const error = validateHypothesisRecord(normalizedValue.add_hypothesis);
    if (error !== null) return `add_hypothesis: ${error}`;
  }

  if ('invalidate_hypothesis' in normalizedValue) {
    const error = validateHypothesisInvalidation(normalizedValue.invalidate_hypothesis);
    if (error !== null) return `invalidate_hypothesis: ${error}`;
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

export function validateOrientationSurvey(value: unknown): string | null {
  if (!isRecord(value)) {
    return 'survey must be an object';
  }

  const keys = Object.keys(value);
  if (keys.length === 0) {
    return 'survey must include at least one property';
  }

  const allowedKeys = new Set(Object.keys(ORIENTATION_SURVEY_FIELDS));
  for (const key of keys) {
    if (!allowedKeys.has(key)) {
      return `Unknown survey property: ${key}`;
    }
  }

  if (value.survey_version !== 'v1') {
    return 'survey_version must be v1';
  }

  if ('agent_name_reported' in value) {
    if (!isNonEmptyString(value.agent_name_reported)) {
      return 'agent_name_reported must be a non-empty string';
    }
    if (value.agent_name_reported.length > ORIENTATION_SURVEY_FIELDS.agent_name_reported.maxLength) {
      return `agent_name_reported must be at most ${ORIENTATION_SURVEY_FIELDS.agent_name_reported.maxLength} characters long`;
    }
  }

  if ('user_name_reported' in value) {
    if (!isNonEmptyString(value.user_name_reported)) {
      return 'user_name_reported must be a non-empty string';
    }
    if (value.user_name_reported.length > ORIENTATION_SURVEY_FIELDS.user_name_reported.maxLength) {
      return `user_name_reported must be at most ${ORIENTATION_SURVEY_FIELDS.user_name_reported.maxLength} characters long`;
    }
  }

  for (const key of ['identity_confidence', 'task_state_confidence', 'next_step_confidence', 'risk_of_wrong_action'] as const) {
    if (key in value) {
      const spec = ORIENTATION_SURVEY_FIELDS[key];
      const error = validateIntegerInRange(value[key], spec.minimum, spec.maximum);
      if (error !== null) {
        return `${key}: ${error}`;
      }
    }
  }

  if ('resume_vs_restart' in value) {
    if (
      typeof value.resume_vs_restart !== 'string' ||
      !ORIENTATION_SURVEY_FIELDS.resume_vs_restart.values.includes(value.resume_vs_restart)
    ) {
      return 'resume_vs_restart must be one of: resuming, partially_resuming, restarting';
    }
  }

  if ('ambiguity_types' in value) {
    const error = validateStringArray(value.ambiguity_types, {
      unique: ORIENTATION_SURVEY_FIELDS.ambiguity_types.unique,
      maxItems: ORIENTATION_SURVEY_FIELDS.ambiguity_types.maxItems,
    });
    if (error !== null) {
      return `ambiguity_types: ${error}`;
    }
    const invalidValue = value.ambiguity_types.find(
      (item) => !ORIENTATION_SURVEY_FIELDS.ambiguity_types.values.includes(item as never)
    );
    if (invalidValue !== undefined) {
      return `ambiguity_types: invalid value ${invalidValue}`;
    }
  }

  if ('would_act_now' in value && typeof value.would_act_now !== 'boolean') {
    return 'would_act_now must be a boolean';
  }

  for (const key of ['missing_critical_context', 'intended_next_action'] as const) {
    if (key in value) {
      if (!isNonEmptyString(value[key])) {
        return `${key} must be a non-empty string`;
      }
      if (value[key].length > ORIENTATION_SURVEY_FIELDS[key].maxLength) {
        return `${key} must be at most ${ORIENTATION_SURVEY_FIELDS[key].maxLength} characters long`;
      }
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

function appendUniqueHypothesis(existing: HypothesisRecord[], addition: HypothesisRecord): HypothesisRecord[] {
  if (
    existing.some(
      (item) => item.hypothesis === addition.hypothesis && item.invalidated_by === addition.invalidated_by
    )
  ) {
    return [...existing];
  }

  return [...existing, addition];
}

function invalidateHypothesis(
  hypotheses: HypothesisRecord[],
  invalidation: HypothesisInvalidation | undefined
): HypothesisRecord[] {
  if (invalidation === undefined) {
    return [...hypotheses];
  }

  if (invalidation.index > hypotheses.length) {
    throw new Error(
      `Computed state is invalid: invalidate_hypothesis index ${invalidation.index} is out of range for ${hypotheses.length} active hypothesis${hypotheses.length === 1 ? '' : 'es'}`
    );
  }

  return hypotheses.filter((_, index) => index !== invalidation.index - 1);
}

function applyDelta(state: PendingState, delta: StateDelta): PendingState {
  const remainingHypotheses = invalidateHypothesis(state.hypotheses, delta.invalidate_hypothesis);
  const nextHypotheses =
    delta.add_hypothesis !== undefined
      ? appendUniqueHypothesis(remainingHypotheses, delta.add_hypothesis)
      : remainingHypotheses;

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
    hypotheses: nextHypotheses,
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

  if (!Array.isArray(state.hypotheses)) {
    throw new Error('Computed state is invalid: hypotheses must be an array');
  }
  if (state.hypotheses.length > 8) {
    throw new Error('Computed state is invalid: hypotheses must contain at most 8 items');
  }
  for (const hypothesis of state.hypotheses) {
    const error = validateHypothesisRecord(hypothesis);
    if (error !== null) {
      throw new Error(`Computed state is invalid: hypotheses ${error}`);
    }
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
    hypotheses: state.hypotheses,
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
    hypotheses: [],
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
  const hypothesesSection =
    state.hypotheses.length === 0
      ? 'ACTIVE HYPOTHESES:\n- None\n\n'
      : `ACTIVE HYPOTHESES:\n${state.hypotheses
          .map(
            (item, index) =>
              `${index + 1}. ${item.hypothesis}\n   Invalidated by: ${item.invalidated_by}`
          )
          .join('\n')}\n\n`;

  return `${CONTEXT_PREFIX}

This is your current working state. You are CONTINUING from this state — not starting fresh.

STATE:
${JSON.stringify(state, null, 2)}

${hypothesesSection}You MUST maintain this state as you work.

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

${ORIENTATION_SURVEY_SESSION_START_INSTRUCTION}
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

export async function appendOrientationSurvey(
  survey: unknown,
  surveyPath: string = SURVEY_PATH,
  now: Date = new Date()
): Promise<string> {
  const validationError = validateOrientationSurvey(survey);
  if (validationError !== null) {
    throw new Error(validationError);
  }

  const record = {
    recorded_at: now.toISOString(),
    ...(survey as OrientationSurvey),
  };

  await mkdir(dirname(surveyPath), { recursive: true });
  await appendFile(surveyPath, `${JSON.stringify(record)}\n`, 'utf8');
  return surveyPath;
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
