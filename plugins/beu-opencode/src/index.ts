import { tool, type Plugin } from '@opencode-ai/plugin';
import { existsSync } from 'node:fs';
import {
  appendOrientationSurvey,
  appendConstraintCompression,
  appendHypothesisCompression,
  appendStateDelta,
  computeAgentState,
  COMPRESS_TOOL_DESCRIPTION,
  DELTA_PATH,
  DELTA_TOOL_DESCRIPTION,
  ORIENTATION_SURVEY_FIELDS,
  ORIENTATION_SURVEY_TOOL_DESCRIPTION,
  STATE_DELTA_FIELDS,
  formatStateContext,
  type OrientationSurvey,
  type StateDelta,
} from '../../../src/beu-state.js';

type OpenCodeArraySpec = {
  kind: 'string[]';
  itemMinLength: number;
  itemMaxLength: number;
  description: string;
  minItems?: number;
  maxItems?: number;
};

type OpenCodeEnumArraySpec = {
  kind: 'enum[]';
  values: readonly string[];
  description: string;
  maxItems?: number;
};

function createOpenCodeDeltaArgs(schema: typeof tool.schema) {
  return Object.fromEntries(
    Object.entries(STATE_DELTA_FIELDS)
      .filter(([, spec]) => !spec.hidden)
      .map(([key, spec]) => {
        if (spec.kind === 'string') {
          return [key, schema.string().min(spec.minLength).max(spec.maxLength).optional().describe(spec.description)];
        }

        const arraySpec = spec as OpenCodeArraySpec;
        const item = schema.string().min(arraySpec.itemMinLength).max(arraySpec.itemMaxLength);
        let arrayField = schema.array(item);
        if (typeof arraySpec.maxItems === 'number') {
          arrayField = arrayField.max(arraySpec.maxItems);
        }
        if (typeof arraySpec.minItems === 'number') {
          arrayField = arrayField.min(arraySpec.minItems);
        }

        const field = schema.union([item, arrayField]);
        return [key, field.optional().describe(arraySpec.description)];
      })
  );
}

function createOpenCodeSurveyArgs(schema: typeof tool.schema) {
  const enumValues = ORIENTATION_SURVEY_FIELDS.resume_vs_restart.values as [string, string, string];
  const ambiguityValues = ORIENTATION_SURVEY_FIELDS.ambiguity_types.values as [string, string, string, string, string, string];
  const ambiguitySpec = ORIENTATION_SURVEY_FIELDS.ambiguity_types as OpenCodeEnumArraySpec;

  return {
    survey_version: schema.literal('v1').describe(ORIENTATION_SURVEY_FIELDS.survey_version.description),
    agent_name_reported: schema
      .string()
      .min(ORIENTATION_SURVEY_FIELDS.agent_name_reported.minLength)
      .max(ORIENTATION_SURVEY_FIELDS.agent_name_reported.maxLength)
      .optional()
      .describe(ORIENTATION_SURVEY_FIELDS.agent_name_reported.description),
    user_name_reported: schema
      .string()
      .min(ORIENTATION_SURVEY_FIELDS.user_name_reported.minLength)
      .max(ORIENTATION_SURVEY_FIELDS.user_name_reported.maxLength)
      .optional()
      .describe(ORIENTATION_SURVEY_FIELDS.user_name_reported.description),
    identity_confidence: schema
      .number()
      .int()
      .min(ORIENTATION_SURVEY_FIELDS.identity_confidence.minimum)
      .max(ORIENTATION_SURVEY_FIELDS.identity_confidence.maximum)
      .optional()
      .describe(ORIENTATION_SURVEY_FIELDS.identity_confidence.description),
    task_state_confidence: schema
      .number()
      .int()
      .min(ORIENTATION_SURVEY_FIELDS.task_state_confidence.minimum)
      .max(ORIENTATION_SURVEY_FIELDS.task_state_confidence.maximum)
      .optional()
      .describe(ORIENTATION_SURVEY_FIELDS.task_state_confidence.description),
    next_step_confidence: schema
      .number()
      .int()
      .min(ORIENTATION_SURVEY_FIELDS.next_step_confidence.minimum)
      .max(ORIENTATION_SURVEY_FIELDS.next_step_confidence.maximum)
      .optional()
      .describe(ORIENTATION_SURVEY_FIELDS.next_step_confidence.description),
    resume_vs_restart: schema
      .enum(enumValues)
      .optional()
      .describe(ORIENTATION_SURVEY_FIELDS.resume_vs_restart.description),
    ambiguity_types: schema
      .array(schema.enum(ambiguityValues))
      .max(ambiguitySpec.maxItems ?? ambiguityValues.length)
      .optional()
      .describe(ambiguitySpec.description),
    would_act_now: schema.boolean().optional().describe(ORIENTATION_SURVEY_FIELDS.would_act_now.description),
    risk_of_wrong_action: schema
      .number()
      .int()
      .min(ORIENTATION_SURVEY_FIELDS.risk_of_wrong_action.minimum)
      .max(ORIENTATION_SURVEY_FIELDS.risk_of_wrong_action.maximum)
      .optional()
      .describe(ORIENTATION_SURVEY_FIELDS.risk_of_wrong_action.description),
    missing_critical_context: schema
      .string()
      .min(ORIENTATION_SURVEY_FIELDS.missing_critical_context.minLength)
      .max(ORIENTATION_SURVEY_FIELDS.missing_critical_context.maxLength)
      .optional()
      .describe(ORIENTATION_SURVEY_FIELDS.missing_critical_context.description),
    intended_next_action: schema
      .string()
      .min(ORIENTATION_SURVEY_FIELDS.intended_next_action.minLength)
      .max(ORIENTATION_SURVEY_FIELDS.intended_next_action.maxLength)
      .optional()
      .describe(ORIENTATION_SURVEY_FIELDS.intended_next_action.description),
  };
}

function createOpenCodeCompressArgs(schema: typeof tool.schema) {
  return schema.union([
    schema.object({
      kind: schema.literal('constraint'),
      constraint: schema
        .string()
        .min(1)
        .max(200)
        .describe('A single compressed constraint string'),
    }),
    schema.object({
      kind: schema.literal('hypothesis'),
      hypothesis: schema
        .string()
        .min(1)
        .max(200)
        .describe('A single compressed hypothesis string'),
    }),
  ]);
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
            message: 'Failed to inject BEU session-start-equivalent state context',
            extra: {
              error: error instanceof Error ? error.message : String(error),
            },
          },
        });
      }
    },

    tool: {
      delta: tool({
        description: DELTA_TOOL_DESCRIPTION,
        args: createOpenCodeDeltaArgs(tool.schema),
        async execute(args, context) {
          const path = await appendStateDelta(args as StateDelta);

          context.metadata({
            title: 'State delta',
            metadata: {
              path,
            },
          });

          return `Appended delta to ${path}`;
        },
      }),
      compress: tool({
        description: COMPRESS_TOOL_DESCRIPTION,
        args: createOpenCodeCompressArgs(tool.schema),
        async execute(args, context) {
          const payload = args as { kind: 'constraint' | 'hypothesis'; constraint?: string; hypothesis?: string };
          const path =
            payload.kind === 'constraint'
              ? await appendConstraintCompression(payload.constraint as string)
              : await appendHypothesisCompression(payload.hypothesis as string);

          context.metadata({
            title: 'Constraint compression',
            metadata: {
              path,
            },
          });

          return payload.kind === 'constraint'
            ? `Compressed constraints and appended to ${path}`
            : `Compressed hypotheses and appended to ${path}`;
        },
      }),
      orientation_survey: tool({
        description: ORIENTATION_SURVEY_TOOL_DESCRIPTION,
        args: createOpenCodeSurveyArgs(tool.schema),
        async execute(args, context) {
          const path = await appendOrientationSurvey(args as OrientationSurvey);

          context.metadata({
            title: 'Orientation survey',
            metadata: {
              path,
            },
          });

          return `Appended orientation survey to ${path}`;
        },
      }),
    },
  };
};
