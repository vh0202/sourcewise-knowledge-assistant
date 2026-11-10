#!/usr/bin/env sh
# One-command start for macOS and Linux (also runs in Git Bash on Windows).
#
#     ./start.sh
#
# Creates .venv on the first run, installs the pinned requirements, loads the demo data if the
# database is empty, and serves the app on http://127.0.0.1:8102. Stop with Ctrl+C.
#
# Nothing is installed globally. Node.js is not needed: the built frontend is in frontend/dist.
set -eu
cd "$(dirname "$0")"

find_python() {
  # Prints the first Python 3.12+ interpreter found on PATH.
  for candidate in python3.12 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
      "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

venv_python() {
  # A virtual environment keeps its interpreter in bin/ on POSIX and in Scripts/ on Windows.
  if [ -x .venv/bin/python ]; then
    echo .venv/bin/python
  elif [ -x .venv/Scripts/python.exe ]; then
    echo .venv/Scripts/python.exe
  else
    return 1
  fi
}

if ! PY=$(venv_python); then
  if ! SYSTEM_PYTHON=$(find_python); then
    echo "Python 3.12 or newer was not found. Install it and run this script again." >&2
    exit 1
  fi
  echo "Creating the virtual environment (.venv) ..."
  "$SYSTEM_PYTHON" -m venv .venv
  PY=$(venv_python)
fi

# Install dependencies only when requirements.txt has changed since the last install.
if ! cmp -s requirements.txt .venv/requirements.installed; then
  echo "Installing Python dependencies into .venv ..."
  "$PY" -m pip install --disable-pip-version-check --quiet -r requirements.txt
  cp requirements.txt .venv/requirements.installed
fi

"$PY" -m sourcewise seed --if-empty
exec "$PY" -m sourcewise serve "$@"
