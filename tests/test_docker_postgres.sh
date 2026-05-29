#!/usr/bin/env bash
# Acceptance tests for Issue #2: Postgres 16 + pgvector via docker-compose
# Run: bash tests/test_docker_postgres.sh

set -euo pipefail

PASS=0
FAIL=0
CONTAINER="setflow-db"
DB_USER="setflow"
DB_NAME="setflow"

pass() { echo "  ✓ $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $1"; FAIL=$((FAIL + 1)); }

echo "=== Postgres + pgvector acceptance tests ==="
echo ""

# 1. Container is running
echo "1. Container is running"
if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
  pass "Container '${CONTAINER}' is running"
else
  fail "Container '${CONTAINER}' is not running"
fi

# 2. Postgres version is 16
echo "2. Postgres version"
PG_VERSION=$(docker exec "$CONTAINER" psql -U "$DB_USER" -t -c "SHOW server_version;" 2>/dev/null | tr -d ' ')
if [[ "$PG_VERSION" == 16* ]]; then
  pass "Postgres version is 16 ($PG_VERSION)"
else
  fail "Expected Postgres 16, got: $PG_VERSION"
fi

# 3. Database 'setflow' exists
echo "3. Database exists"
DB_EXISTS=$(docker exec "$CONTAINER" psql -U "$DB_USER" -t -c "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}';" 2>/dev/null | tr -d ' ')
if [[ "$DB_EXISTS" == "1" ]]; then
  pass "Database '${DB_NAME}' exists"
else
  fail "Database '${DB_NAME}' does not exist"
fi

# 4. pgvector extension is available
echo "4. pgvector extension"
VECTOR_EXT=$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -c "SELECT extname FROM pg_extension WHERE extname = 'vector';" 2>/dev/null | tr -d ' ')
if [[ "$VECTOR_EXT" == "vector" ]]; then
  pass "pgvector extension is enabled"
else
  fail "pgvector extension is not enabled"
fi

# 5. pgvector actually works (create a vector column, insert, query)
echo "5. pgvector operations work"
VECTOR_TEST=$(docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -t -c "
  CREATE TEMP TABLE _vec_test (id serial, embedding vector(3));
  INSERT INTO _vec_test (embedding) VALUES ('[1,2,3]'), ('[4,5,6]');
  SELECT COUNT(*) FROM _vec_test;
" 2>/dev/null | grep -o '[0-9]*' | tail -1)
if [[ "$VECTOR_TEST" == "2" ]]; then
  pass "Vector insert and query works"
else
  fail "Vector operations failed"
fi

# 6. Port 5432 is accessible from host
echo "6. Host connectivity"
if docker exec "$CONTAINER" pg_isready -U "$DB_USER" -h localhost > /dev/null 2>&1; then
  pass "Postgres is accepting connections on port 5432"
else
  fail "Postgres is not accepting connections"
fi

# 7. Data volume exists
echo "7. Persistent volume"
if docker volume ls --format '{{.Name}}' | grep -q "setflow_pgdata"; then
  pass "Volume 'setflow_pgdata' exists for data persistence"
else
  fail "Volume 'setflow_pgdata' not found"
fi

# 8. Healthcheck is passing
echo "8. Container healthcheck"
HEALTH=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER" 2>/dev/null)
if [[ "$HEALTH" == "healthy" ]]; then
  pass "Container healthcheck is passing"
else
  fail "Container healthcheck status: $HEALTH (expected: healthy)"
fi

# Summary
echo ""
echo "=== Results: ${PASS} passed, ${FAIL} failed ==="
if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
