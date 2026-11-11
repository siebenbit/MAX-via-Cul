#!/usr/bin/env bash
# Serve the local card fixtures with simulated Home Assistant data.
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

echo "Kartenvorschau: http://127.0.0.1:8765/tests/frontend/"
echo "Beenden mit Strg+C."
exec python3 -m http.server 8765 --bind 127.0.0.1 \
  --directory "$repo_dir/custom_components/cul_max"
