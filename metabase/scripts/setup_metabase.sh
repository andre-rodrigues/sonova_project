#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — override via environment variables
# ---------------------------------------------------------------------------
MB_HOST="${MB_HOST:?MB_HOST is required}"
MB_SETUP_TOKEN="${MB_SETUP_TOKEN:-}"
MB_ADMIN_EMAIL="${MB_ADMIN_EMAIL:?MB_ADMIN_EMAIL is required}"
MB_ADMIN_PASSWORD="${MB_ADMIN_PASSWORD:?MB_ADMIN_PASSWORD is required}"
MB_ADMIN_FIRST_NAME="${MB_ADMIN_FIRST_NAME:?MB_ADMIN_FIRST_NAME is required}"
MB_ADMIN_LAST_NAME="${MB_ADMIN_LAST_NAME:?MB_ADMIN_LAST_NAME is required}"

CLICKHOUSE_HOST="${CLICKHOUSE_HOST:?CLICKHOUSE_HOST is required}"
CLICKHOUSE_PORT="${CLICKHOUSE_PORT:?CLICKHOUSE_PORT is required}"
CLICKHOUSE_DATABASE="${CLICKHOUSE_DATABASE:?CLICKHOUSE_DATABASE is required}"
CLICKHOUSE_USER="${CLICKHOUSE_USER:?CLICKHOUSE_USER is required}"
CLICKHOUSE_PASSWORD="${CLICKHOUSE_PASSWORD:?CLICKHOUSE_PASSWORD is required}"

TIMEOUT="${TIMEOUT:?TIMEOUT is required}"
DB_NAME="ClickHouse Sonova Gold"

# ---------------------------------------------------------------------------
# 1. Wait for Metabase to be ready
# ---------------------------------------------------------------------------
echo "Waiting for Metabase at ${MB_HOST} (timeout: ${TIMEOUT}s)..."
elapsed=0
until curl -sf "${MB_HOST}/api/health" | grep -q '"status":"ok"'; do
  if [ "$elapsed" -ge "$TIMEOUT" ]; then
    echo "ERROR: Metabase did not become ready within ${TIMEOUT}s." >&2
    exit 1
  fi
  sleep 3
  elapsed=$((elapsed + 3))
done
echo "Metabase is ready."

# ---------------------------------------------------------------------------
# 2. First-run setup or login
# ---------------------------------------------------------------------------
LIVE_TOKEN=$(curl -sf "${MB_HOST}/api/session/properties" \
  | grep -o '"setup-token":"[^"]*"' | cut -d'"' -f4 || true)

if [ -n "$LIVE_TOKEN" ]; then
  echo "Running first-run setup..."
  SETUP_RESPONSE=$(curl -sf -X POST \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${LIVE_TOKEN}" \
    -d "{
      \"prefs\": {
        \"site_locale\": \"en\",
        \"site_name\": \"Sonova\"
      },
      \"token\": \"${LIVE_TOKEN}\",
      \"user\": {
        \"email\": \"${MB_ADMIN_EMAIL}\",
        \"first_name\": \"${MB_ADMIN_FIRST_NAME}\",
        \"last_name\": \"${MB_ADMIN_LAST_NAME}\",
        \"password\": \"${MB_ADMIN_PASSWORD}\"
      }
    }" \
    "${MB_HOST}/api/setup")

  SESSION_TOKEN=$(echo "$SETUP_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4 || true)
  if [ -z "$SESSION_TOKEN" ]; then
    echo "ERROR: First-run setup failed. Response: ${SETUP_RESPONSE}" >&2
    exit 1
  fi
  echo "First-run setup complete. Admin account created."
else
  echo "Metabase already configured — authenticating as ${MB_ADMIN_EMAIL}..."
  AUTH_RESPONSE=$(curl -sf -X POST \
    -H "Content-Type: application/json" \
    -d "{\"username\": \"${MB_ADMIN_EMAIL}\", \"password\": \"${MB_ADMIN_PASSWORD}\"}" \
    "${MB_HOST}/api/session")

  SESSION_TOKEN=$(echo "$AUTH_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4 || true)
  if [ -z "$SESSION_TOKEN" ]; then
    echo "ERROR: Authentication failed. Response: ${AUTH_RESPONSE}" >&2
    exit 1
  fi
  echo "Authenticated successfully."
fi

# ---------------------------------------------------------------------------
# 4. Idempotency — skip if connection already exists
# ---------------------------------------------------------------------------
echo "Checking for existing '${DB_NAME}' database connection..."
EXISTING=$(curl -sf \
  -H "X-Metabase-Session: ${SESSION_TOKEN}" \
  "${MB_HOST}/api/database" \
  | grep -o "\"name\":\"${DB_NAME}\"" || true)

if [ -n "$EXISTING" ]; then
  echo "Database connection '${DB_NAME}' already exists — skipping creation."
  exit 0
fi

# ---------------------------------------------------------------------------
# 5. Create the ClickHouse connection
# ---------------------------------------------------------------------------
echo "Creating ClickHouse database connection '${DB_NAME}'..."
CREATE_RESPONSE=$(curl -sf -X POST \
  -H "Content-Type: application/json" \
  -H "X-Metabase-Session: ${SESSION_TOKEN}" \
  -d "{
    \"name\": \"${DB_NAME}\",
    \"engine\": \"clickhouse\",
    \"details\": {
      \"host\": \"${CLICKHOUSE_HOST}\",
      \"port\": ${CLICKHOUSE_PORT},
      \"dbname\": \"${CLICKHOUSE_DATABASE}\",
      \"user\": \"${CLICKHOUSE_USER}\",
      \"password\": \"${CLICKHOUSE_PASSWORD}\",
      \"ssl\": false
    }
  }" \
  "${MB_HOST}/api/database")

DB_ID=$(echo "$CREATE_RESPONSE" | grep -o '"id":[0-9]*' | head -1 | cut -d: -f2)

if [ -z "$DB_ID" ]; then
  echo "ERROR: Connection created but could not parse database ID from response." >&2
  echo "Response: ${CREATE_RESPONSE}" >&2
  exit 1
fi

echo "Done. ClickHouse connection '${DB_NAME}' created with database ID: ${DB_ID}"
