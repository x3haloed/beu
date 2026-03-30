#!/bin/zsh
set -euo pipefail

repo_root="${0:A:h:h}"
hermes_home="${1:-${HERMES_HOME:-$HOME/.hermes}}"
plugin_dir="$hermes_home/plugins/hermes-adapter"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  print "Usage: $0 [HERMES_HOME]"
  print ""
  print "Installs the BeU Hermes adapter into HERMES_HOME/plugins/hermes-adapter."
  print "If HERMES_HOME is omitted, defaults to ~/.hermes (or \$HERMES_HOME if set)."
  exit 0
fi

mkdir -p "$plugin_dir"

find "$plugin_dir" -mindepth 1 -maxdepth 1 \
  ! -name 'beu.yaml' \
  -exec rm -rf {} +

cp "$repo_root/hermes-adapter/__init__.py" "$plugin_dir/__init__.py"
cp "$repo_root/hermes-adapter/plugin.yaml" "$plugin_dir/plugin.yaml"
cp "$repo_root/target/debug/beu" "$plugin_dir/beu"

chmod +x "$plugin_dir/beu"

print "Installed Hermes adapter into $plugin_dir"
print "Preserved $plugin_dir/beu.yaml if it existed"
