#!/usr/bin/env node

import { appendFile, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
} from '@modelcontextprotocol/sdk/types.js';
import {
  DELTA_PATH,
  DELTA_TOOL_DESCRIPTION,
  STATE_DELTA_FIELD_DESCRIPTIONS,
  isNonEmptyString,
  isRecord,
  validateStringArray,
} from './beu-state.js';

const SERVER_NAME = 'beu';
const SERVER_VERSION = '0.1.0';

const STATE_DELTA_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    set_focus: {
      type: 'string',
      minLength: 1,
      description: STATE_DELTA_FIELD_DESCRIPTIONS.set_focus
    },
    add_threads: {
      type: 'array',
      items: { type: 'string', minLength: 1 },
      uniqueItems: true,
      description: STATE_DELTA_FIELD_DESCRIPTIONS.add_threads
    },
    remove_threads: {
      type: 'array',
      items: { type: 'string', minLength: 1 },
      uniqueItems: true,
      description: STATE_DELTA_FIELD_DESCRIPTIONS.remove_threads
    },
    add_constraints: {
      type: 'array',
      items: { type: 'string', minLength: 1 },
      uniqueItems: true,
      description: STATE_DELTA_FIELD_DESCRIPTIONS.add_constraints
    },
    add_recent: {
      type: 'array',
      items: { type: 'string', minLength: 1 },
      maxItems: 5,
      description: STATE_DELTA_FIELD_DESCRIPTIONS.add_recent
    },
    set_next: {
      type: 'array',
      items: { type: 'string', minLength: 1 },
      minItems: 1,
      description: STATE_DELTA_FIELD_DESCRIPTIONS.set_next
    }
  },
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
      const validationError = this.validateStateDelta(delta);
      
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
        await mkdir(dirname(DELTA_PATH), { recursive: true });
        await appendFile(DELTA_PATH, `${JSON.stringify(delta)}\n`, 'utf8');
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

  private validateStateDelta(value: unknown): string | null {
    if (!isRecord(value) || Array.isArray(value)) {
      return 'delta must be an object';
    }

    const keys = Object.keys(value);
    if (keys.length === 0) {
      return 'delta must include at least one property';
    }

    for (const key of keys) {
      if (!(key in STATE_DELTA_SCHEMA.properties)) {
        return `Unknown delta property: ${key}`;
      }
    }

    if ('set_focus' in value && !isNonEmptyString(value.set_focus)) {
      return 'set_focus must be a non-empty string';
    }

    if ('add_threads' in value) {
      const error = validateStringArray(value.add_threads, { unique: true });
      if (error !== null) return `add_threads: ${error}`;
    }

    if ('remove_threads' in value) {
      const error = validateStringArray(value.remove_threads, { unique: true });
      if (error !== null) return `remove_threads: ${error}`;
    }

    if ('add_constraints' in value) {
      const error = validateStringArray(value.add_constraints, { unique: true });
      if (error !== null) return `add_constraints: ${error}`;
    }

    if ('add_recent' in value) {
      const error = validateStringArray(value.add_recent, { maxItems: 5 });
      if (error !== null) return `add_recent: ${error}`;
    }

    if ('set_next' in value) {
      const error = validateStringArray(value.set_next, { minItems: 1 });
      if (error !== null) return `set_next: ${error}`;
    }

    return null;
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
