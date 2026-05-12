#!/bin/bash

if [ $# -eq 0 ]; then
  echo "Usage: $0 <json-file>"
  exit 1
fi

FILE="$1"
PREV="${FILE}.prev"

if [ ! -f "$FILE" ]; then
  echo "Error: File not found: $FILE"
  exit 1
fi

if [ -f "$PREV" ]; then
  echo "=== Changes since last confirmation ==="
  diff <(jq -S . "$PREV") <(jq -S . "$FILE") || true
  echo

  read -p "Was this an improvement? [Y/n] " -n 1 -r
  echo

  if [[ $REPLY =~ ^[Nn]$ ]]; then
    echo "Undoing changes..."
    cp "$PREV" "$FILE"
    echo "✓ Restored to previous state"
  else
    echo "Accepting changes"
    cp "$FILE" "$PREV"
    echo "✓ Baseline updated"
  fi
else
  echo "First run - storing baseline"
  cp "$FILE" "$PREV"
  echo "✓ Baseline created"
fi
