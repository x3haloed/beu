import { tool, type Plugin } from '@opencode-ai/plugin';
import { existsSync } from 'node:fs';
import {
  appendStateDelta,
  computeAgentState,
  DELTA_PATH,
  DELTA_TOOL_DESCRIPTION,
  STATE_DELTA_FIELDS,
  STATE_DELTA_FIELD_DESCRIPTIONS,
  formatStateContext,
  type StateDelta,
} from '../../../src/beu-state.js';

function createOpenCodeDeltaArgs(schema: typeof tool.schema) {
  return Object.fromEntries(
    Object.entries(STATE_DELTA_FIELDS).map(([key, spec]) => {
      if (spec.kind === 'string') {
        return [key, schema.string().min(spec.minLength).max(spec.maxLength).optional().describe(spec.description)];
      }

      let field = schema.array(schema.string().min(spec.itemMinLength).max(spec.itemMaxLength));
      if (typeof spec.maxItems === 'number') {
        field = field.max(spec.maxItems);
      }
      if (typeof spec.minItems === 'number') {
        field = field.min(spec.minItems);
      }

      return [key, field.optional().describe(spec.description)];
    })
  );
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
    },
  };
};