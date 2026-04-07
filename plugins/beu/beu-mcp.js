#!/usr/bin/env node

const { appendFile, mkdir } = require('node:fs/promises');
const { homedir } = require('node:os');
const { dirname, join } = require('node:path');

const SERVER_NAME = 'beu';
const SERVER_VERSION = '0.1.0';
const LATEST_PROTOCOL_VERSION = '2025-11-25';
const SUPPORTED_PROTOCOL_VERSIONS = [
  LATEST_PROTOCOL_VERSION,
  '2025-06-18',
  '2025-03-26',
  '2024-11-05',
  '2024-10-07'
];

const STATE_DELTA_SCHEMA = {
  $schema: 'https://json-schema.org/draft/2020-12/schema',
  $id: 'https://example.com/delta.schema.json',
  title: 'StateDelta',
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

const DELTA_PATH = join(homedir(), '.codex', 'state', 'deltas.jsonl');

let initialized = false;
let inputBuffer = Buffer.alloc(0);
let pending = Promise.resolve();

process.stdin.on('data', chunk => {
  inputBuffer = Buffer.concat([inputBuffer, chunk]);
  drainInputBuffer();
});

process.stdin.on('error', error => {
  console.error('[beu] stdin error:', error);
});

process.stdout.on('error', error => {
  console.error('[beu] stdout error:', error);
});

process.stdin.resume();

function drainInputBuffer() {
  while (true) {
    let message;
    try {
      message = readNextMessage();
    } catch (error) {
      sendError(undefined, -32_700, 'Parse error', error instanceof Error ? error.message : String(error));
      inputBuffer = Buffer.alloc(0);
      return;
    }

    if (message === null) {
      return;
    }

    pending = pending.then(async () => {
      await handleMessage(message);
    });
  }
}

function readNextMessage() {
  const headerEnd = inputBuffer.indexOf('\r\n\r\n');
  if (headerEnd === -1) {
    return null;
  }

  const headerText = inputBuffer.subarray(0, headerEnd).toString('utf8');
  const headers = new Map();
  for (const line of headerText.split('\r\n')) {
    const separator = line.indexOf(':');
    if (separator === -1) {
      continue;
    }
    const name = line.slice(0, separator).trim().toLowerCase();
    const value = line.slice(separator + 1).trim();
    headers.set(name, value);
  }

  const contentLength = Number(headers.get('content-length'));
  if (!Number.isInteger(contentLength) || contentLength < 0) {
    throw new Error('Missing or invalid Content-Length header');
  }

  const bodyStart = headerEnd + 4;
  const bodyEnd = bodyStart + contentLength;
  if (inputBuffer.length < bodyEnd) {
    return null;
  }

  const bodyText = inputBuffer.subarray(bodyStart, bodyEnd).toString('utf8');
  inputBuffer = inputBuffer.subarray(bodyEnd);
  return JSON.parse(bodyText);
}

async function handleMessage(message) {
  if (!isRequest(message)) {
    return;
  }

  switch (message.method) {
    case 'initialize':
      await handleInitialize(message);
      return;
    case 'notifications/initialized':
      return;
    case 'tools/list':
      await handleToolsList(message);
      return;
    case 'tools/call':
      await handleToolCall(message);
      return;
    case 'ping':
      sendResult(message.id, {});
      return;
    default:
      sendError(message.id, -32_601, `Method not found: ${message.method}`);
  }
}

async function handleInitialize(message) {
  const params = isRecord(message.params) ? message.params : {};
  const requestedVersion = typeof params.protocolVersion === 'string' ? params.protocolVersion : LATEST_PROTOCOL_VERSION;
  const protocolVersion = SUPPORTED_PROTOCOL_VERSIONS.includes(requestedVersion)
    ? requestedVersion
    : LATEST_PROTOCOL_VERSION;

  initialized = true;
  sendResult(message.id, {
    protocolVersion,
    capabilities: {
      tools: {
        listChanged: false
      }
    },
    serverInfo: {
      name: SERVER_NAME,
      version: SERVER_VERSION
    }
  });
}

async function handleToolsList(message) {
  if (!initialized) {
    sendError(message.id, -32_600, 'Server not initialized');
    return;
  }

  sendResult(message.id, {
    tools: [
      {
        name: 'delta',
        title: 'Delta',
        description: 'Append a validated state delta to ~/.codex/state/deltas.jsonl',
        inputSchema: STATE_DELTA_SCHEMA
      }
    ]
  });
}

async function handleToolCall(message) {
  if (!initialized) {
    sendError(message.id, -32_600, 'Server not initialized');
    return;
  }

  const params = isRecord(message.params) ? message.params : {};
  if (params.name !== 'delta') {
    sendResult(message.id, {
      content: [
        {
          type: 'text',
          text: `Unknown tool: ${String(params.name)}`
        }
      ],
      isError: true
    });
    return;
  }

  const delta = params.arguments;
  const validationError = validateStateDelta(delta);
  if (validationError !== null) {
    sendResult(message.id, {
      content: [
        {
          type: 'text',
          text: validationError
        }
      ],
      isError: true
    });
    return;
  }

  try {
    await mkdir(dirname(DELTA_PATH), { recursive: true });
    await appendFile(DELTA_PATH, `${JSON.stringify(delta)}\n`, 'utf8');
    sendResult(message.id, {
      content: [
        {
          type: 'text',
          text: `Appended delta to ${DELTA_PATH}`
        }
      ]
    });
  } catch (error) {
    sendResult(message.id, {
      content: [
        {
          type: 'text',
          text: `Failed to append delta: ${error instanceof Error ? error.message : String(error)}`
        }
      ],
      isError: true
    });
  }
}

function validateStateDelta(value) {
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
    if (error !== null) {
      return `add_threads: ${error}`;
    }
  }

  if ('remove_threads' in value) {
    const error = validateStringArray(value.remove_threads, { unique: true });
    if (error !== null) {
      return `remove_threads: ${error}`;
    }
  }

  if ('add_constraints' in value) {
    const error = validateStringArray(value.add_constraints, { unique: true });
    if (error !== null) {
      return `add_constraints: ${error}`;
    }
  }

  if ('add_recent' in value) {
    const error = validateStringArray(value.add_recent, { maxItems: 5 });
    if (error !== null) {
      return `add_recent: ${error}`;
    }
  }

  if ('set_next' in value) {
    const error = validateStringArray(value.set_next, { minItems: 1 });
    if (error !== null) {
      return `set_next: ${error}`;
    }
  }

  return null;
}

function validateStringArray(value, options) {
  if (!Array.isArray(value)) {
    return 'must be an array of strings';
  }

  if (typeof options.minItems === 'number' && value.length < options.minItems) {
    return `must contain at least ${options.minItems} item${options.minItems === 1 ? '' : 's'}`;
  }

  if (typeof options.maxItems === 'number' && value.length > options.maxItems) {
    return `must contain at most ${options.maxItems} item${options.maxItems === 1 ? '' : 's'}`;
  }

  const seen = new Set();
  for (const item of value) {
    if (!isNonEmptyString(item)) {
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

function isRequest(message) {
  return isRecord(message) && typeof message.method === 'string' && Object.prototype.hasOwnProperty.call(message, 'id');
}

function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value) {
  return typeof value === 'string' && value.length > 0;
}

function sendResult(id, result) {
  sendMessage({
    jsonrpc: '2.0',
    id,
    result
  });
}

function sendError(id, code, message, data) {
  const error = {
    jsonrpc: '2.0',
    error: {
      code,
      message,
      ...(data === undefined ? {} : { data })
    }
  };

  if (id !== undefined) {
    error.id = id;
  }

  sendMessage(error);
}

function sendMessage(message) {
  const body = Buffer.from(JSON.stringify(message), 'utf8');
  const frame = Buffer.concat([Buffer.from(`Content-Length: ${body.length}\r\n\r\n`, 'utf8'), body]);
  process.stdout.write(frame);
}
