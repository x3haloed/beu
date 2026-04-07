#!/usr/bin/env node

const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const MANAGED_HOOK_EVENTS = ['SessionStart', 'UserPromptSubmit', 'PostToolUse', 'Stop'];

function shellQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

function hookCommand() {
  const installedProgram = shellQuote(path.join(os.homedir(), '.beu', 'compute-agent-state.js'));
  const deltaPath = shellQuote(path.join(os.homedir(), '.beu', 'state', 'deltas.jsonl'));
  return `if [ -f ${deltaPath} ]; then node ${installedProgram} ${deltaPath}; else printf ''; fi`;
}

function desiredHooks() {
  const command = hookCommand();
  return {
    hooks: {
      SessionStart: [
        {
          matcher: 'startup|resume',
          hooks: [
            {
              type: 'command',
              command,
              statusMessage: 'Loading agent state',
            },
          ],
        },
      ],
    },
  };
}

function loadJson(targetPath) {
  return JSON.parse(fs.readFileSync(targetPath, 'utf8'));
}

function mergeHooks(existing, desired) {
  const merged = existing && typeof existing === 'object' && !Array.isArray(existing) ? { ...existing } : {};
  const mergedHooks =
    merged.hooks && typeof merged.hooks === 'object' && !Array.isArray(merged.hooks)
      ? { ...merged.hooks }
      : {};

  for (const eventName of MANAGED_HOOK_EVENTS) {
    delete mergedHooks[eventName];
  }

  for (const [eventName, desiredGroups] of Object.entries(desired.hooks)) {
    mergedHooks[eventName] = desiredGroups;
  }

  merged.hooks = mergedHooks;
  return merged;
}

function backupPath(targetPath) {
  return path.join(path.dirname(targetPath), `${path.basename(targetPath)}.bak`);
}

function writeAtomic(targetPath, contents) {
  fs.mkdirSync(path.dirname(targetPath), { recursive: true });
  const tempPath = path.join(path.dirname(targetPath), `.${path.basename(targetPath)}.tmp`);
  fs.writeFileSync(tempPath, contents, 'utf8');
  fs.renameSync(tempPath, targetPath);
}

function expandHome(targetPath) {
  if (targetPath === '~') {
    return os.homedir();
  }

  if (targetPath.startsWith('~/')) {
    return path.join(os.homedir(), targetPath.slice(2));
  }

  return targetPath;
}

function parseArgs(argv) {
  const defaultTarget = path.join(os.homedir(), '.codex', 'hooks.json');
  let target = defaultTarget;
  let dryRun = false;

  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];

    if (arg === '--dry-run') {
      dryRun = true;
      continue;
    }

    if (arg === '--target') {
      const value = argv[index + 1];
      if (!value) {
        throw new Error('--target requires a path');
      }
      target = value;
      index += 1;
      continue;
    }

    if (arg === '--help' || arg === '-h') {
      return { help: true, target, dryRun };
    }

    throw new Error(`Unknown argument: ${arg}`);
  }

  return {
    help: false,
    target: path.resolve(expandHome(target)),
    dryRun,
  };
}

function renderHelp() {
  return [
    'Install BEU Codex session-start hooks.',
    '',
    'Usage:',
    '  node scripts/install_hooks.js [--target <path>] [--dry-run]',
    '',
    'Options:',
    '  --target <path>  Hooks file to write or merge (default: ~/.codex/hooks.json)',
    '  --dry-run        Print the merged hooks JSON without writing anything',
    '  -h, --help       Show this help text',
  ].join('\n');
}

function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    process.stderr.write(`${error.message}\n`);
    process.stderr.write(`${renderHelp()}\n`);
    process.exitCode = 1;
    return;
  }

  if (args.help) {
    process.stdout.write(`${renderHelp()}\n`);
    return;
  }

  const desired = desiredHooks();

  let existing = {};
  if (fs.existsSync(args.target)) {
    try {
      existing = loadJson(args.target);
    } catch (error) {
      process.stderr.write(`warning: failed to parse existing hooks file ${args.target}: ${error.message}\n`);
      existing = {};
    }
  }

  const merged = mergeHooks(existing, desired);
  const rendered = `${JSON.stringify(merged, null, 2)}\n`;

  if (args.dryRun) {
    process.stdout.write(rendered);
    return;
  }

  if (fs.existsSync(args.target)) {
    const backup = backupPath(args.target);
    if (!fs.existsSync(backup)) {
      fs.copyFileSync(args.target, backup);
    }
  }

  writeAtomic(args.target, rendered);
  process.stdout.write(`installed BEU session-start hooks at ${args.target}\n`);
  process.stdout.write(`hook commands point at ${path.join(os.homedir(), '.beu', 'compute-agent-state.js')}\n`);
}

main();