#!/bin/bash
# Double-click this file on a Mac to start Clinical Signal.
# The first run sets up a private Python environment in this folder (about a minute).

cd "$(dirname "$0")" || exit 1

pause_and_exit() { echo; read -r -p "Press Return to close this window." _; exit 1; }

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed."
  echo "Install it from https://www.python.org/downloads/ and double-click this file again."
  pause_and_exit
fi

if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up. This takes about a minute and needs an internet connection."
  python3 -m venv .venv || { echo "Could not create the Python environment."; pause_and_exit; }
fi

# Install the packages on first run, and again only if requirements.txt changes.
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt \
    || { echo "Could not install the required packages. Check your internet connection and try again."; pause_and_exit; }
  touch .venv/.installed
fi

echo "Starting Clinical Signal. Leave this window open while you use it."
.venv/bin/python run.py || pause_and_exit
