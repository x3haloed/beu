#!/usr/bin/env bash
# Architecture boundary checks for BeU.
# Run as: bash scripts/check-boundaries.sh
# Returns non-zero if hard violations are found.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

violations=0

echo "=== Architecture Boundary Checks ==="
echo

# --------------------------------------------------------------------------
# Check 1: Direct libsql usage outside the storage layer
# --------------------------------------------------------------------------
# libsql:: types should appear only in src/storage/ and other files that are
# explicitly part of the persistence boundary.
# --------------------------------------------------------------------------

echo "--- Check 1: Direct libsql usage outside storage ---"

results=$(grep -rn 'libsql::\|use libsql::\|libsql{' src/ \
    --include='*.rs' \
    | grep -v 'src/storage/' \
    | grep -v '^\s*//' \
    | grep -v '//.*libsql' \
    || true)

if [ -n "$results" ]; then
    echo "VIOLATION: Direct libsql usage found outside storage:"
    echo "$results"
    echo
    count=$(echo "$results" | wc -l | tr -d ' ')
    echo "($count occurrence(s) -- these modules should go through the storage boundary)"
    violations=$((violations + 1))
else
    echo "OK"
fi
echo

# --------------------------------------------------------------------------
# Check 4: Test tier gating for external-service integration tests
# --------------------------------------------------------------------------
# Tests that touch libsql or external services should be gated so the fast
# local test path remains lightweight.
# --------------------------------------------------------------------------

echo "--- Check 4: Test tier gating for integration tests ---"

tier_violations=()
for test_file in tests/*.rs; do
    [ -f "$test_file" ] || continue

    needs_gate=false
    if grep -q 'PgPool\|libsql::\|create_pool\|\.connect(' "$test_file" 2>/dev/null; then
        needs_gate=true
    fi

    if [ "$needs_gate" = true ]; then
        if ! head -5 "$test_file" | grep -q 'cfg.*feature.*integration' 2>/dev/null; then
            tier_violations+=("  $test_file: needs '#![cfg(all(feature = \"libsql\", feature = \"integration\"))]'")
        fi
    fi
done

if [ ${#tier_violations[@]} -gt 0 ]; then
    echo "VIOLATION: Integration tests missing feature gate:"
    printf '%s\n' "${tier_violations[@]}"
    echo
    echo "(Tests requiring external services should be isolated from the default fast path)"
    violations=$((violations + 1))
else
    echo "OK"
fi
echo

# --------------------------------------------------------------------------
# Check 5: No silent test-skip patterns
# --------------------------------------------------------------------------

echo "--- Check 5: No silent test-skip patterns ---"

skip_results=$(grep -rn 'try_connect\|is_available.*return\|is_none.*return\|is_err.*return.*//.*skip' tests/ \
    --include='*.rs' \
    || true)

if [ -n "$skip_results" ]; then
    echo "VIOLATION: Silent test-skip patterns found (use explicit gating instead):"
    echo "$skip_results"
    echo
    violations=$((violations + 1))
else
    echo "OK"
fi
echo

# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------

echo "=== Summary ==="
if [ "$violations" -gt 0 ]; then
    echo "FAILED: $violations hard violation(s) found"
    exit 1
else
    echo "PASSED: No hard violations found (review warnings above)"
    exit 0
fi
