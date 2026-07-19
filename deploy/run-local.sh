#!/bin/sh
set -eu

PORT_NUMBER="${1:-8001}"
PYTHON="python3"
if [ -x ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
fi

"$PYTHON" manage.py check
"$PYTHON" manage.py migrate --noinput

"$PYTHON" manage.py send_appointment_reminders --watch &
REMINDER_PID=$!

cleanup() {
    kill "$REMINDER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

"$PYTHON" manage.py runserver "127.0.0.1:$PORT_NUMBER" --noreload
