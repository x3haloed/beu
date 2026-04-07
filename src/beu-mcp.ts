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
  appendStateDelta,
  createStateDeltaJsonSchemaProperties,
  DELTA_PATH,
  DELTA_TOOL_DESCRIPTION,
  validateStateDelta,
} from './beu-state.js';

const SERVER_NAME = 'beu';
const SERVER_VERSION = '0.1.0';

const STATE_DELTA_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: createStateDeltaJsonSchemaProperties(),
  minProperties: 1
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
      ],
    }));

    this.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      if (request.params.name !== 'delta') {
        throw new McpError(
          ErrorCode.MethodNotFound,
          `Unknown tool: ${request.params.name}`
        );
      }

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

      try {
        await appendStateDelta(delta);
        return {
          content: [
            {
              type: 'text',
              text: `Appended delta to ${DELTA_PATH}`,
            },
          ],
        };
      } catch (error) {
        return {
          content: [
            {
              type: 'text',
              text: `Failed to append delta: ${error instanceof Error ? error.message : String(error)}`,
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
