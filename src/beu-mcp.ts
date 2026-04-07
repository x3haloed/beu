#!/usr/bin/env node

import { appendFile, mkdir } from 'node:fs/promises';
import { homedir } from 'node:os';
import { dirname, join } from 'node:path';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
} from '@modelcontextprotocol/sdk/types.js';

const SERVER_NAME = 'beu';
const SERVER_VERSION = '0.1.0';

const STATE_DELTA_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    set_focus: {
      type: 'string',
      minLength: 1,
      description: 'Replace the current focus with a new one'
    },
    add_threads: {
      type: 'array',
      items: { type: 'string', minLength: 1 },
      uniqueItems: true,
      description: 'Add new active threads'
    },
    remove_threads: {
      type: 'array',
      items: { type: 'string', minLength: 1 },
      uniqueItems: true,
      description: 'Remove completed or irrelevant threads'
    },
    add_constraints: {
      type: 'array',
      items: { type: 'string', minLength: 1 },
      uniqueItems: true,
      description: 'Add newly discovered constraints or invariants'
    },
    add_recent: {
      type: 'array',
      items: { type: 'string', minLength: 1 },
      maxItems: 5,
      description: 'Append recent meaningful steps (will be truncated in state)'
    },
    set_next: {
      type: 'array',
      items: { type: 'string', minLength: 1 },
      minItems: 1,
      description: 'Replace next actions list'
    }
  },
  minProperties: 1
};

const DELTA_PATH = join(homedir(), '.beu', 'state', 'deltas.jsonl');

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
          description: 'Append a validated state delta to ~/.beu/state/deltas.jsonl',
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

  private isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
  }

  private isNonEmptyString(value: unknown): value is string {
    return typeof value === 'string' && value.length > 0;
  }

  private validateStringArray(
    value: unknown,
    options: {
      unique?: boolean;
      minItems?: number;
      maxItems?: number;
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
      if (!this.isNonEmptyString(item)) {
        return 'must contain only non-empty strings';
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

  private validateStateDelta(value: unknown): string | null {
    if (!this.isRecord(value) || Array.isArray(value)) {
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

    if ('set_focus' in value && !this.isNonEmptyString(value.set_focus)) {
      return 'set_focus must be a non-empty string';
    }

    if ('add_threads' in value) {
      const error = this.validateStringArray(value.add_threads, { unique: true });
      if (error !== null) return `add_threads: ${error}`;
    }

    if ('remove_threads' in value) {
      const error = this.validateStringArray(value.remove_threads, { unique: true });
      if (error !== null) return `remove_threads: ${error}`;
    }

    if ('add_constraints' in value) {
      const error = this.validateStringArray(value.add_constraints, { unique: true });
      if (error !== null) return `add_constraints: ${error}`;
    }

    if ('add_recent' in value) {
      const error = this.validateStringArray(value.add_recent, { maxItems: 5 });
      if (error !== null) return `add_recent: ${error}`;
    }

    if ('set_next' in value) {
      const error = this.validateStringArray(value.set_next, { minItems: 1 });
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
