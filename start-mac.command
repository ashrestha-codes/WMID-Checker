#!/bin/bash
# Tracker ID Checker — Mac starter. Updates itself from GitHub, then starts the app.
# Everything is inside main() so bash reads the whole file before running it —
# that makes it safe for the updater to replace this file while it is running.

main() {
  cd "$(dirname "$0")" || exit 1

  # ---------- 1. Auto-update from GitHub ----------
  REPO="$(tr -d '[:space:]' < update_source.txt 2>/dev/null)"   # e.g. owner/repo
  if [ -n "$REPO" ] && [ "$1" != "--updated" ]; then
    echo "Checking for updates from github.com/$REPO ..."
    TMP="$(mktemp -d)"
    if curl -fsSL --max-time 30 "https://github.com/$REPO/archive/refs/heads/main.zip" -o "$TMP/u.zip" \
       && unzip -q "$TMP/u.zip" -d "$TMP" ; then
      SRC="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -1)"
      OLD_REQ="$(cat requirements.txt 2>/dev/null)"
      # copy code only — the download never contains your results, screenshots or installed packages
      if cp -R "$SRC"/. ./ ; then
        chmod +x start-mac.command
        echo "Up to date (version: $(cat VERSION 2>/dev/null || echo unknown))."
        if [ -d .venv ] && [ "$OLD_REQ" != "$(cat requirements.txt)" ]; then
          echo "Installing new requirements..."
          .venv/bin/pip install -q -r requirements.txt
        fi
        rm -rf "$TMP"
        exec bash ./start-mac.command --updated   # restart with the freshly downloaded starter
      else
        echo "Update copy failed. Starting the current version."
      fi
    else
      echo "Couldn't check for updates (offline?). Starting the current version."
    fi
    rm -rf "$TMP"
  fi

  # ---------- 2. First-time install ----------
  if [ ! -d .venv ]; then
    echo "First run: installing... this takes a minute."
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    .venv/bin/python -m playwright install chromium
  fi

  # ---------- 3. Close any older copy still running, then start ----------
  OLD_PIDS="$(lsof -ti tcp:5050 2>/dev/null)"
  if [ -n "$OLD_PIDS" ]; then
    echo "Closing an older copy of the tool that was still running..."
    kill $OLD_PIDS 2>/dev/null; sleep 2
    OLD_PIDS="$(lsof -ti tcp:5050 2>/dev/null)"
    [ -n "$OLD_PIDS" ] && kill -9 $OLD_PIDS 2>/dev/null
  fi
  .venv/bin/python app.py
}

main "$@"
exit
