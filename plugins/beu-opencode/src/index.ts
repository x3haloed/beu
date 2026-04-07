import { tool, type Plugin } from '@opencode-ai/plugin';
import { appendFile, mkdir } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { dirname } from 'node:path';
import {
  computeAgentState,
  DELTA_PATH,
  DELTA_TOOL_DESCRIPTION,
  STATE_DELTA_FIELD_DESCRIPTIONS,
  formatStateContext,
  normalizeDelta,
  type StateDelta,
  validateStateDelta,
} from '../../../src/beu-state.js';

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
        description: DELTA_TOOL_DESCRIPTION,
        args: {
          set_focus: tool.schema.string().min(1).max(200).optional().describe(STATE_DELTA_FIELD_DESCRIPTIONS.set_focus),
          add_threads: tool.schema.array(tool.schema.string().min(1).max(160)).optional().describe(STATE_DELTA_FIELD_DESCRIPTIONS.add_threads),
          remove_threads: tool.schema.array(tool.schema.string().min(1).max(160)).optional().describe(STATE_DELTA_FIELD_DESCRIPTIONS.remove_threads),
          add_constraints: tool.schema.array(tool.schema.string().min(1).max(200)).optional().describe(STATE_DELTA_FIELD_DESCRIPTIONS.add_constraints),
          add_recent: tool.schema.array(tool.schema.string().min(1).max(200)).max(5).optional().describe(STATE_DELTA_FIELD_DESCRIPTIONS.add_recent),
          set_next: tool.schema.array(tool.schema.string().min(1).max(160)).min(1).optional().describe(STATE_DELTA_FIELD_DESCRIPTIONS.set_next),
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