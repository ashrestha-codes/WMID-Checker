#!/bin/bash
# Tracker ID Checker — Mac starter. Updates itself from GitHub, then starts the app.
cd "$(dirname "$0")"

# ---------- 1. Auto-update from GitHub ----------
REPO="$(tr -d '[:space:]' < update_source.txt 2>/dev/null)"   # e.g. yourname/wmid-tracker-checker
if [ -n "$REPO" ]; then
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
    else
      echo "Update copy failed. Starting the current version."
    fi
    if [ -d .venv ] && [ "$OLD_REQ" != "$(cat requirements.txt)" ]; then
      echo "Installing new requirements..."
      .venv/bin/pip install -q -r requirements.txt
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

# ---------- 3. Start ----------
.venv/bin/python app.py
