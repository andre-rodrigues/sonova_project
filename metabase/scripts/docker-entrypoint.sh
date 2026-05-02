#!/usr/bin/env bash
set -euo pipefail

/app/run_metabase.sh &
MB_PID=$!

/scripts/setup_metabase.sh || echo "WARNING: Metabase setup failed — check logs above"

wait "$MB_PID"
