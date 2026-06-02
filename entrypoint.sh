#!/bin/bash
set -e

echo "=== Starting NSE sidecar on :${SIDECAR_PORT:-3000} ==="
cd /app/sidecar
PORT=${SIDECAR_PORT:-3000} node build/server.js &
SIDECAR_PID=$!

# Wait for sidecar to be ready
echo "=== Waiting for sidecar health check ==="
for i in $(seq 1 15); do
  if curl -s -o /dev/null "http://localhost:${SIDECAR_PORT:-3000}/api/marketStatus" 2>/dev/null; then
    echo "Sidecar ready after ${i}s"
    break
  fi
  sleep 1
done

echo "=== Starting Python backend on :${PORT:-10000} ==="
cd /app
uvicorn backend.app:app --host 0.0.0.0 --port ${PORT:-10000} &
BACKEND_PID=$!

# Forward signals to both children
trap "kill $SIDECAR_PID $BACKEND_PID 2>/dev/null; exit 0" TERM INT

# Wait for either to exit
wait -n $SIDECAR_PID $BACKEND_PID 2>/dev/null
EXIT_CODE=$?
echo "Process exited with code $EXIT_CODE"
kill $SIDECAR_PID $BACKEND_PID 2>/dev/null
wait 2>/dev/null
exit $EXIT_CODE
