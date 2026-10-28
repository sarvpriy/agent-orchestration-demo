#!/usr/bin/env bash
# One entry point for the agent-orchestration demo.
#   ./run.sh setup            create .venv, install Python + Node deps, build, create .env
#   ./run.sh api              run the Knowledge Retrieval API (foreground)
#   ./run.sh app ["query"]    run the Node workflow (needs the API running + GROQ_API_KEY)
#   ./run.sh all ["query"]    start the API in the background, run the Node workflow, stop the API
#   ./run.sh test             full self-test: API checks + end-to-end with a mock LLM (no keys needed)
#   ./run.sh stop             stop background services started by this script
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PORT="${PORT:-8000}"
MOCK_PORT="${MOCK_LLM_PORT:-4010}"
RUN_DIR="$ROOT/.run"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"

log()  { printf '\033[1;34m[run]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[run] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || fail "'$1' not found. $2"; }

port_in_use() { lsof -ti "tcp:$1" >/dev/null 2>&1; }

wait_for() { # wait_for <url> <seconds> <label>
  local url="$1" secs="$2" label="$3" i
  for ((i = 0; i < secs; i++)); do
    curl -sf "$url" >/dev/null 2>&1 && return 0
    sleep 1
  done
  fail "$label did not become ready at $url within ${secs}s (see $RUN_DIR/*.log)"
}

cmd_setup() {
  need python3 "Install Python 3.10+."
  need node "Install Node 20.6+."
  need npm "Install Node 20.6+."
  [ -d "$VENV" ] || { log "creating .venv"; python3 -m venv "$VENV"; }
  log "installing Python dependencies"
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -q -r requirements.txt
  log "installing Node dependencies"
  npm install --no-audit --no-fund
  log "building TypeScript"
  npm run build
  if [ ! -f .env ]; then
    cp env.example .env
    log "created .env from env.example -> add your GROQ_API_KEY"
  fi
  log "setup complete"
}

ensure_setup() {
  [ -x "$PY" ] && [ -d node_modules ] || cmd_setup
}

start_api() { # background; reuses an already-healthy API
  mkdir -p "$RUN_DIR"
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    log "API already running on :$PORT"
    return 0
  fi
  port_in_use "$PORT" && fail "port $PORT is in use by something that is not a healthy API (try: lsof -i :$PORT)"
  log "starting API on :$PORT (first start downloads the embedding model)"
  nohup "$PY" -m uvicorn api:app --host 127.0.0.1 --port "$PORT" >"$RUN_DIR/api.log" 2>&1 &
  echo $! >"$RUN_DIR/api.pid"
  wait_for "http://127.0.0.1:$PORT/health" "${API_START_TIMEOUT:-180}" "API"
  log "API ready"
}

stop_pidfile() {
  local f="$RUN_DIR/$1.pid"
  [ -f "$f" ] || return 0
  kill "$(cat "$f")" 2>/dev/null || true
  rm -f "$f"
}

cmd_stop() {
  stop_pidfile api
  stop_pidfile mock
  log "stopped background services"
}

cmd_api() {
  ensure_setup
  port_in_use "$PORT" && fail "port $PORT already in use"
  log "API docs: http://127.0.0.1:$PORT/docs"
  if [ "${DEV:-0}" = "1" ]; then
    exec "$PY" -m uvicorn api:app --host 127.0.0.1 --port "$PORT" --reload
  fi
  exec "$PY" -m uvicorn api:app --host 127.0.0.1 --port "$PORT"
}

check_env() {
  local key="${GROQ_API_KEY:-}"
  if [ -z "$key" ] && [ -f .env ]; then
    key="$(grep -E '^GROQ_API_KEY=' .env | tail -1 | cut -d= -f2- | tr -d '"'"'"' ')"
  fi
  [ -n "$key" ] || fail "GROQ_API_KEY is empty. Set it in .env (or export it) first."
}

run_app() {
  export KNOWLEDGE_RETRIEVAL_AGENT_URL="${KNOWLEDGE_RETRIEVAL_AGENT_URL:-http://127.0.0.1:$PORT/retrieve}"
  export DOTENV_CONFIG_QUIET=true
  exec npx --no-install tsx src/index.ts "$@"
}

cmd_app() {
  ensure_setup
  check_env
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 \
    || fail "Knowledge Retrieval API is not running on :$PORT. Start it with './run.sh api'."
  run_app "$@"
}

cmd_all() {
  ensure_setup
  check_env
  trap cmd_stop EXIT
  start_api
  # no exec: keep the trap so the API is stopped afterwards
  ( export KNOWLEDGE_RETRIEVAL_AGENT_URL="${KNOWLEDGE_RETRIEVAL_AGENT_URL:-http://127.0.0.1:$PORT/retrieve}" \
           DOTENV_CONFIG_QUIET=true; npx --no-install tsx src/index.ts "$@" )
}

cmd_test() {
  ensure_setup
  mkdir -p "$RUN_DIR"
  trap cmd_stop EXIT
  local failed=0

  # Own port and a throwaway ticket DB so tests never touch real tickets.
  PORT="${TEST_PORT:-8765}"
  export TICKETS_DB="$RUN_DIR/test_tickets.db"
  rm -f "$TICKETS_DB"

  log "type-check / build"
  npm run build --silent

  start_api
  log "API checks"
  "$PY" tests/test_api.py "http://127.0.0.1:$PORT" || failed=1
  log "ticket management checks"
  "$PY" tests/test_tickets.py "http://127.0.0.1:$PORT" || failed=1

  log "end-to-end workflow with mock LLM (no real keys used)"
  port_in_use "$MOCK_PORT" && fail "mock LLM port $MOCK_PORT in use (set MOCK_LLM_PORT)"
  node tests/mock_llm.mjs "$MOCK_PORT" >"$RUN_DIR/mock.log" 2>&1 &
  echo $! >"$RUN_DIR/mock.pid"
  wait_for_mock

  local out q
  while IFS='|' read -r q expect; do
    out="$(GROQ_API_KEY=mock GROQ_MODEL=mock LLM_BASE_URL="http://127.0.0.1:$MOCK_PORT/v1" \
           KNOWLEDGE_RETRIEVAL_AGENT_URL="http://127.0.0.1:$PORT/retrieve" DOTENV_CONFIG_QUIET=true \
           npx --no-install tsx src/index.ts "$q" 2>&1)" || { echo "FAIL  e2e '$q' exited non-zero: $out"; failed=1; continue; }
    if grep -q "$expect" <<<"$out"; then echo "PASS  e2e '$q' -> $expect"; else echo "FAIL  e2e '$q' expected '$expect', got: $out"; failed=1; fi
  done <<'CASES'
My VPN keeps disconnecting repeatedly.|INC001
The office air conditioning is not working.|INC006
I need new software installed.|CHG001
I need to change the office seating layout.|CHG004
Our VPN has dropped every week for a month. We suspect a firewall firmware bug and want to find the root cause.|PRB001
CASES

  # ticketing through the full workflow: first report creates, repeat attaches
  local t1 t2 n1 n2
  local tq="The VPN keeps disconnecting for the whole sales team since this morning."
  t1="$(GROQ_API_KEY=mock LLM_BASE_URL="http://127.0.0.1:$MOCK_PORT/v1" KNOWLEDGE_RETRIEVAL_AGENT_URL="http://127.0.0.1:$PORT/retrieve" \
        DOTENV_CONFIG_QUIET=true npx --no-install tsx src/index.ts "$tq" 2>&1)" || true
  t2="$(GROQ_API_KEY=mock LLM_BASE_URL="http://127.0.0.1:$MOCK_PORT/v1" KNOWLEDGE_RETRIEVAL_AGENT_URL="http://127.0.0.1:$PORT/retrieve" \
        DOTENV_CONFIG_QUIET=true npx --no-install tsx src/index.ts "$tq" 2>&1)" || true
  n1="$(grep -oE 'ticket=[A-Z]{3}[0-9]{7} created=true' <<<"$t1" || true)"
  n2="$(grep -oE 'ticket=[A-Z]{3}[0-9]{7} created=false' <<<"$t2" || true)"
  if [ -n "$n1" ] && [ -n "$n2" ] && [ "${n1%% *}" = "${n2%% *}" ]; then
    echo "PASS  e2e ticket: created (${n1%% *}) then reused on repeat"
  else
    echo "FAIL  e2e ticket: first='$t1' second='$t2'"; failed=1
  fi

  # ticket service down must not break the knowledge answer
  if out="$(GROQ_API_KEY=mock LLM_BASE_URL="http://127.0.0.1:$MOCK_PORT/v1" KNOWLEDGE_RETRIEVAL_AGENT_URL="http://127.0.0.1:$PORT/retrieve" \
        TICKET_AGENT_URL="http://127.0.0.1:1/x" DOTENV_CONFIG_QUIET=true npx --no-install tsx src/index.ts "I need new software installed." 2>&1)" \
     && grep -q "CHG001" <<<"$out" && grep -q "ticket=error" <<<"$out"; then
    echo "PASS  e2e ticket service down -> answer still returned"
  else
    echo "FAIL  e2e ticket service down: $out"; failed=1
  fi

  # interactive mode: piped input, "exit" and plain EOF must both end cleanly
  for input in $'My VPN keeps disconnecting repeatedly.\nexit\n' $'My VPN keeps disconnecting repeatedly.\n'; do
    if out="$(printf '%s' "$input" | GROQ_API_KEY=mock LLM_BASE_URL="http://127.0.0.1:$MOCK_PORT/v1" \
         KNOWLEDGE_RETRIEVAL_AGENT_URL="http://127.0.0.1:$PORT/retrieve" DOTENV_CONFIG_QUIET=true \
         npx --no-install tsx src/index.ts 2>&1)" && grep -q INC001 <<<"$out"; then
      echo "PASS  e2e interactive mode"
    else
      echo "FAIL  e2e interactive mode: $out"; failed=1
    fi
  done

  # error path: dead retrieval URL must exit non-zero with a readable message
  if GROQ_API_KEY=mock LLM_BASE_URL="http://127.0.0.1:$MOCK_PORT/v1" KNOWLEDGE_RETRIEVAL_AGENT_URL="http://127.0.0.1:1/retrieve" \
     DOTENV_CONFIG_QUIET=true npx --no-install tsx src/index.ts "VPN down" >/dev/null 2>&1; then
    echo "FAIL  e2e with dead retrieval service should exit non-zero"; failed=1
  else
    echo "PASS  e2e dead retrieval service -> non-zero exit"
  fi

  [ "$failed" = 0 ] && log "ALL TESTS PASSED" || fail "some tests failed"
}

wait_for_mock() {
  local i
  for ((i = 0; i < 20; i++)); do
    port_in_use "$MOCK_PORT" && return 0
    sleep 0.5
  done
  fail "mock LLM did not start (see $RUN_DIR/mock.log)"
}

case "${1:-}" in
  setup) cmd_setup ;;
  api)   cmd_api ;;
  app)   shift; cmd_app "$@" ;;
  all)   shift; cmd_all "$@" ;;
  test)  cmd_test ;;
  stop)  cmd_stop ;;
  *)     sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
