#!/usr/bin/env node

import { resolve } from 'node:path';
import { computeAgentState, DELTA_PATH, formatCodexSessionStartOutput, formatStateContext } from './beu-state.js';

async function main() {
  const args = process.argv.slice(2);
  const codexSessionStartJson = args.includes('--codex-session-start-json');
  const inputPathArg = args.find((arg) => arg !== '--codex-session-start-json');
  const inputPath = inputPathArg ? resolve(inputPathArg) : DELTA_PATH;
  const state = await computeAgentState(inputPath);
  process.stdout.write(codexSessionStartJson ? formatCodexSessionStartOutput(state) : formatStateContext(state));
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
  process.exit(1);
});
