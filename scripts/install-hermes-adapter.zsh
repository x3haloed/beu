#!/bin/zsh
set -euo pipefail

repo_root="${0:A:h:h}"
hermes_home="${1:-${HERMES_HOME:-$HOME/.hermes}}"
plugin_dir="$hermes_home/plugins/beu"
legacy_plugin_dir="$hermes_home/plugins/hermes-adapter"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  print "Usage: $0 [HERMES_HOME]"
  print ""
  print "Installs the BeU Hermes adapter into HERMES_HOME/plugins/beu."
  print "If HERMES_HOME is omitted, defaults to ~/.hermes (or \$HERMES_HOME if set)."
  exit 0
fi

mkdir -p "$plugin_dir"

if [[ -d "$legacy_plugin_dir" ]]; then
  if [[ ! -f "$plugin_dir/beu.yaml" && -f "$legacy_plugin_dir/beu.yaml" ]]; then
    cp "$legacy_plugin_dir/beu.yaml" "$plugin_dir/beu.yaml"
  fi
  rm -rf "$legacy_plugin_dir"
fi

find "$plugin_dir" -mindepth 1 -maxdepth 1 \
  ! -name 'beu.yaml' \
  -exec rm -rf {} +

cp "$repo_root/hermes-adapter/__init__.py" "$plugin_dir/__init__.py"
cp "$repo_root/hermes-adapter/_shared.py" "$plugin_dir/_shared.py"
cp "$repo_root/hermes-adapter/config.py" "$plugin_dir/config.py"
cp "$repo_root/hermes-adapter/hooks.py" "$plugin_dir/hooks.py"
cp "$repo_root/hermes-adapter/plugin.py" "$plugin_dir/plugin.py"
cp "$repo_root/hermes-adapter/process.py" "$plugin_dir/process.py"
cp "$repo_root/hermes-adapter/tools.py" "$plugin_dir/tools.py"
cp "$repo_root/hermes-adapter/plugin.yaml" "$plugin_dir/plugin.yaml"
cp "$repo_root/target/debug/beu" "$plugin_dir/beu"

chmod +x "$plugin_dir/beu"

print "Installed Hermes adapter into $plugin_dir"
print "Preserved $plugin_dir/beu.yaml if it existed"
print "Removed legacy adapter directory $legacy_plugin_dir if it existed"
