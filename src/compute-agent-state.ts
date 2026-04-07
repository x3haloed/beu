#!/usr/bin/env node

import { resolve } from 'node:path';
import { computeAgentState, DELTA_PATH, formatStateContext } from './beu-state.js';

async function main() {
  const inputPath = process.argv[2] ? resolve(process.argv[2]) : DELTA_PATH;
  const state = await computeAgentState(inputPath);
  process.stdout.write(formatStateContext(state));
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});