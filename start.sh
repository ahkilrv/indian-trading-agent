#!/usr/bin/env bash
# One-button starter: launches NSE sidecar + backend + frontend,
# waits for all to be healthy, opens the dashboard in your browser,
# then tails their logs in one terminal.  Ctrl+C cleanly shuts all down.
#
# Usage:
#   ./start.sh                    # default ports
#   BACKEND_PORT=9000 ./start.sh  # override backend port
#   FRONTEND_PORT=3001 ./start.sh # override frontend port
#   NSE_PORT=3010 ./start.sh      # override NSE sidecar port
#
# Requirements: venv at ./venv, frontend deps installed (./frontend/node_modules).

set -euo pipefail

# --- Configuration ---
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
NSE_SIDECAR_DIR="${NSE_SIDECAR_DIR:-/tmp/nse-sidecar/stock-nse-india}"
NSE_PORT="${NSE_PORT:-3009}"
BACKEND_LOG="/tmp/trading-agent-backend.log"
FRONTEND_LOG="/tmp/trading-agent-frontend.log"
NSE_LOG="/tmp/trading-agent-nse-sidecar.log"
BACKEND_HEALTH_URL="http://localhost:${BACKEND_PORT}/api/health"
FRONTEND_URL="http://localhost:${FRONTEND_PORT}"
NSE_HEALTH_URL="http://localhost:${NSE_PORT}/api/marketStatus"
HEALTH_TIMEOUT=60   # seconds to wait for each service

# --- Colors ---
if [[ -t 1 ]]; then
  C_RED=$'\033[0;31m'
  C_GREEN=$'\033[0;32m'
  C_YELLOW=$'\033[0;33m'
  C_BLUE=$'\033[0;34m'
  C_BOLD=$'\033[1m'
  C_RESET=$'\033[0m'
else
  C_RED='' C_GREEN='' C_YELLOW='' C_BLUE='' C_BOLD='' C_RESET=''
fi

log()    { echo "${C_BLUE}[start]${C_RESET} $*"; }
ok()     { echo "${C_GREEN}[ok]${C_RESET}    $*"; }
warn()   { echo "${C_YELLOW}[warn]${C_RESET}  $*"; }
err()    { echo "${C_RED}[err]${C_RESET}   $*" 1>&2; }

# --- Pre-flight checks ---
cd "$ROOT_DIR"

if [[ ! -d "venv" ]]; then
  err "No venv found at ./venv. Create one first:"
  err "  python3 -m venv venv && source venv/bin/activate && pip install -e ."
  exit 1
fi

if [[ ! -d "frontend/node_modules" ]]; then
  warn "frontend/node_modules missing. Running 'npm install' (one-time setup)..."
  (cd frontend && npm install)
fi

# --- NSE sidecar pre-flight ---
NSE_SHOULD_START=false
if [[ -d "$NSE_SIDECAR_DIR" ]] && command -v node &>/dev/null; then
  if [[ ! -f "$NSE_SIDECAR_DIR/build/server.js" ]]; then
    warn "NSE sidecar not built. Building (one-time)..."
    (cd "$NSE_SIDECAR_DIR" && rm -rf build && npx tsc && mkdir -p build/graphql-schema && find src -name "*.graphql" -exec cp {} build/graphql-schema/ \; 2>/dev/null) || warn "NSE sidecar build failed — continuing without it"
  fi
  if [[ -f "$NSE_SIDECAR_DIR/build/server.js" ]]; then
    NSE_SHOULD_START=true
  fi
fi
if ! $NSE_SHOULD_START; then
  warn "NSE sidecar not found at $NSE_SIDECAR_DIR. Clone with:"
  warn "  mkdir -p /tmp/nse-sidecar && git clone https://github.com/hi-imcodeman/stock-nse-india.git /tmp/nse-sidecar/stock-nse-india && cd /tmp/nse-sidecar/stock-nse-india && npm install"
  warn "The app will start without NSE data (falling back to yfinance)."
fi

# --- Free ports if something's already running ---
free_port() {
  local port="$1"
  local pids
  pids="$(lsof -ti ":${port}" 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    warn "Port ${port} is in use. Killing existing process(es): ${pids}"
    # shellcheck disable=SC2086
    kill ${pids} 2>/dev/null || true
    sleep 2
    # Force-kill anything still hanging on
    pids="$(lsof -ti ":${port}" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      # shellcheck disable=SC2086
      kill -9 ${pids} 2>/dev/null || true
      sleep 1
    fi
  fi
}

free_port "$BACKEND_PORT"
free_port "$FRONTEND_PORT"
if $NSE_SHOULD_START; then
  free_port "$NSE_PORT"
fi

# --- Cleanup on exit (Ctrl+C, normal exit, or error) ---
BACKEND_PID=""
FRONTEND_PID=""
NSE_PID=""
TAIL_PID=""

cleanup() {
  echo
  log "Shutting down..."
  for pid in "$TAIL_PID" "$FRONTEND_PID" "$NSE_PID" "$BACKEND_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  # Final port sweep
  sleep 1
  free_port "$BACKEND_PORT" >/dev/null 2>&1 || true
  free_port "$FRONTEND_PORT" >/dev/null 2>&1 || true
  free_port "$NSE_PORT" >/dev/null 2>&1 || true
  ok "Stopped."
}
trap cleanup EXIT INT TERM

# --- Start NSE sidecar ---
if $NSE_SHOULD_START; then
  log "Starting NSE sidecar on :${NSE_PORT}..."
  : > "$NSE_LOG"
  (
    cd "$NSE_SIDECAR_DIR"
    export PORT="$NSE_PORT"
    exec node build/server.js
  ) >>"$NSE_LOG" 2>&1 &
  NSE_PID=$!
fi

# --- Start backend ---
log "Starting backend on :${BACKEND_PORT}..."
: > "$BACKEND_LOG"
(
  cd "$ROOT_DIR"
  # shellcheck disable=SC1091
  source venv/bin/activate
  exec uvicorn backend.app:app --reload --port "$BACKEND_PORT"
) >>"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

# --- Start frontend ---
log "Starting frontend on :${FRONTEND_PORT}..."
: > "$FRONTEND_LOG"
(
  cd "$ROOT_DIR/frontend"
  exec npm run dev -- --port "$FRONTEND_PORT"
) >>"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

# --- Health checks ---
wait_until_healthy() {
  local url="$1"
  local label="$2"
  local pid="$3"
  local elapsed=0
  while (( elapsed < HEALTH_TIMEOUT )); do
    if ! kill -0 "$pid" 2>/dev/null; then
      err "${label} process died unexpectedly. Last 30 lines of log:"
      tail -n 30 "$([[ "$label" == "Backend" ]] && echo "$BACKEND_LOG" || echo "$FRONTEND_LOG")" 1>&2
      return 1
    fi
    if curl -sf -o /dev/null --max-time 2 "$url" 2>/dev/null; then
      return 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
    if (( elapsed % 5 == 0 )); then
      log "${label} starting... (${elapsed}s)"
    fi
  done
  err "${label} didn't become healthy within ${HEALTH_TIMEOUT}s."
  return 1
}

wait_until_healthy "$BACKEND_HEALTH_URL" "Backend" "$BACKEND_PID" || exit 1
ok "Backend ready at http://localhost:${BACKEND_PORT}"

wait_until_healthy "$FRONTEND_URL" "Frontend" "$FRONTEND_PID" || exit 1
ok "Frontend ready at ${FRONTEND_URL}"

if $NSE_SHOULD_START; then
  wait_until_healthy "$NSE_HEALTH_URL" "NSE sidecar" "$NSE_PID" || true
  if kill -0 "$NSE_PID" 2>/dev/null; then
    ok "NSE sidecar ready at http://localhost:${NSE_PORT}"
  else
    warn "NSE sidecar failed — stock data will fall back to yfinance"
    NSE_SHOULD_START=false
  fi
fi

# --- Open browser ---
log "Opening ${FRONTEND_URL} in browser..."
if command -v open >/dev/null 2>&1; then
  open "$FRONTEND_URL"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$FRONTEND_URL" >/dev/null 2>&1 &
elif command -v start >/dev/null 2>&1; then
  start "$FRONTEND_URL" >/dev/null 2>&1 &
else
  warn "Couldn't auto-open browser. Visit ${FRONTEND_URL} manually."
fi

# --- Tail logs (interleaved) ---
echo
ok "${C_BOLD}All services are running.${C_RESET}"
echo "  Backend logs:    $BACKEND_LOG"
echo "  Frontend logs:   $FRONTEND_LOG"
if $NSE_SHOULD_START; then
  echo "  NSE sidecar logs: $NSE_LOG"
fi
echo "  Frontend URL:    ${FRONTEND_URL}"
echo
log "Tailing all logs. Press Ctrl+C to stop everything."
echo

TAIL_FILES=("$BACKEND_LOG" "$FRONTEND_LOG")
if $NSE_SHOULD_START; then
  TAIL_FILES+=("$NSE_LOG")
fi
tail -F "${TAIL_FILES[@]}" 2>/dev/null &
TAIL_PID=$!

# Poll child PIDs every 2s.
while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  if $NSE_SHOULD_START && ! kill -0 "$NSE_PID" 2>/dev/null; then
    warn "NSE sidecar exited. Stock data will fall back to yfinance."
    NSE_SHOULD_START=false
  fi
  sleep 2
done

# If we got here, at least one required service died.
if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  err "Backend exited unexpectedly. Last 20 lines:"
  tail -n 20 "$BACKEND_LOG" 1>&2
fi
if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
  err "Frontend exited unexpectedly. Last 20 lines:"
  tail -n 20 "$FRONTEND_LOG" 1>&2
fi
exit 1
