#!/usr/bin/env node

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
} from '@modelcontextprotocol/sdk/types.js';
import {
  appendConstraintCompression,
  appendHypothesisCompression,
  appendOrientationSurvey,
  appendStateDelta,
  COMPRESS_TOOL_DESCRIPTION,
  createStateDeltaJsonSchemaProperties,
  DELTA_PATH,
  DELTA_TOOL_DESCRIPTION,
  createOrientationSurveyJsonSchemaProperties,
  ORIENTATION_SURVEY_TOOL_DESCRIPTION,
  SURVEY_PATH,
  validateStateDelta,
  validateOrientationSurvey,
} from './beu-state.js';

const SERVER_NAME = 'beu';
const SERVER_VERSION = '0.1.0';

const STATE_DELTA_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: createStateDeltaJsonSchemaProperties(),
  minProperties: 1,
};

const COMPRESS_SCHEMA = {
  oneOf: [
    {
      type: 'object',
      additionalProperties: false,
      required: ['kind', 'constraint'],
      properties: {
        kind: {
          type: 'string',
          enum: ['constraint'],
        },
        constraint: {
          type: 'string',
          minLength: 1,
          maxLength: 200,
          description: 'A single compressed constraint string',
        },
      },
    },
    {
      type: 'object',
      additionalProperties: false,
      required: ['kind', 'hypothesis'],
      properties: {
        kind: {
          type: 'string',
          enum: ['hypothesis'],
        },
        hypothesis: {
          type: 'string',
          minLength: 1,
          maxLength: 200,
          description: 'A single compressed hypothesis string',
        },
      },
    },
  ],
};

const ORIENTATION_SURVEY_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['survey_version'],
  properties: createOrientationSurveyJsonSchemaProperties(),
};

class BeuMcpServer {
  private server: Server;

  constructor() {
    this.server = new Server(
      {
        name: SERVER_NAME,
        version: SERVER_VERSION,
      },
      {
        capabilities: {
          tools: {},
        },
      }
    );

    this.setupToolHandlers();
    
    // Error handling
    this.server.onerror = (error) => console.error('[MCP Error]', error);
    process.on('SIGINT', async () => {
      await this.server.close();
      process.exit(0);
    });
  }

  private setupToolHandlers() {
    this.server.setRequestHandler(ListToolsRequestSchema, async () => ({
      tools: [
        {
          name: 'delta',
          description: DELTA_TOOL_DESCRIPTION,
          inputSchema: STATE_DELTA_SCHEMA,
        },
        {
          name: 'orientation_survey',
          description: ORIENTATION_SURVEY_TOOL_DESCRIPTION,
          inputSchema: ORIENTATION_SURVEY_SCHEMA,
        },
        {
          name: 'compress',
          description: COMPRESS_TOOL_DESCRIPTION,
          inputSchema: COMPRESS_SCHEMA,
        },
      ],
    }));

    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      if (
        request.params.name !== 'delta' &&
        request.params.name !== 'orientation_survey' &&
        request.params.name !== 'compress'
      ) {
        throw new McpError(
          ErrorCode.MethodNotFound,
          `Unknown tool: ${request.params.name}`
        );
      }

      try {
        if (request.params.name === 'delta') {
          const delta = request.params.arguments;
          const validationError = validateStateDelta(delta);
          if (validationError !== null) {
            return {
              content: [
                {
                  type: 'text',
                  text: validationError,
                },
              ],
              isError: true,
            };
          }

          await appendStateDelta(delta);
          return {
            content: [
              {
                type: 'text',
                text: `Appended delta to ${DELTA_PATH}`,
              },
            ],
          };
        }

        if (request.params.name === 'compress') {
          const args = request.params.arguments ?? {};
          if (args.kind === 'constraint') {
            const constraint = args.constraint;
            if (typeof constraint !== 'string' || constraint.length === 0) {
              return {
                content: [
                  {
                    type: 'text',
                    text: 'constraint must be a non-empty string',
                  },
                ],
                isError: true,
              };
            }

            await appendConstraintCompression(constraint);
            return {
              content: [
                {
                  type: 'text',
                  text: `Compressed constraints into ${constraint} and appended to ${DELTA_PATH}`,
                },
              ],
            };
          }

          if (args.kind === 'hypothesis') {
            const hypothesis = args.hypothesis;
            if (typeof hypothesis !== 'string' || hypothesis.length === 0) {
              return {
                content: [
                  {
                    type: 'text',
                    text: 'hypothesis must be a non-empty string',
                  },
                ],
                isError: true,
              };
            }

            await appendHypothesisCompression(hypothesis);
            return {
              content: [
                {
                  type: 'text',
                  text: `Compressed hypotheses into ${hypothesis} and appended to ${DELTA_PATH}`,
                },
              ],
            };
          }

          return {
            content: [
              {
                type: 'text',
                text: 'compress requires kind=constraint or kind=hypothesis',
              },
            ],
            isError: true,
          };
        }

        const survey = request.params.arguments;
        const validationError = validateOrientationSurvey(survey);
        if (validationError !== null) {
          return {
            content: [
              {
                type: 'text',
                text: validationError,
              },
            ],
            isError: true,
          };
        }

        await appendOrientationSurvey(survey);
        return {
          content: [
            {
              type: 'text',
              text: `Appended orientation survey to ${SURVEY_PATH}`,
            },
          ],
        };
      } catch (error) {
        return {
          content: [
            {
              type: 'text',
              text: `Failed to append ${request.params.name}: ${error instanceof Error ? error.message : String(error)}`,
            },
          ],
          isError: true,
        };
      }
    });
  }

  async run() {
    const transport = new StdioServerTransport();
    await this.server.connect(transport);
    console.error('Beu MCP server running on stdio');
  }
}

const server = new BeuMcpServer();
server.run().catch((error) => {
  console.error('Fatal error in main():', error);
  process.exit(1);
});
