#!/bin/sh
# Nightly backup of audit data and the Hermes home directory.
set -e
STAMP=$(date +%Y%m%d)
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
DEST=${BACKUP_DIR:-$ROOT/data/backups/$STAMP}
mkdir -p "$DEST"
cp -a "$ROOT/data/audits.db" "$DEST/" 2>/dev/null || true
tar -C "$ROOT" -czf "$DEST/reports.tgz" reports 2>/dev/null || true
if [ -d "$HOME/.hermes" ]; then
  tar -C "$HOME" -czf "$DEST/hermes-home.tgz" .hermes
fi
find "$ROOT/data/backups" -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +
echo "Backup written to $DEST"
