#!/usr/bin/env bash
# Rebuild the Traits naming release from the reviewed v0.0.1 snapshot.
# No ontology queries or changes to IDs, mappings, fields, or type values.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT"

uv run python scripts/trait/v0.0.1/04_generate_output.py \
  --version 0.0.2 --from-release versions/trait/v0.0.1
uv run python scripts/trait/v0.0.1/05_quality_report.py --version 0.0.2
