#!/usr/bin/env bash
# Puts this working tree on a machine where Shrinkarr is installed, using install/install.sh (for development).
# Usage: scripts/dev-deploy.sh <ssh-host>
# Note: the service restarts, so a running conversion starts again. Pause the queue first if needed.
set -euo pipefail
HOST=${1:?usage: scripts/dev-deploy.sh <ssh-host>}
cd "$(dirname "$0")/.."
tar --exclude .git --exclude __pycache__ --exclude .venv -czf - . | ssh "$HOST" \
  'cat > /tmp/shrinkarr.tar.gz && tar -xzf /tmp/shrinkarr.tar.gz -O ./install/install.sh > /tmp/shrinkarr-install.sh &&
   SHRINKARR_TARBALL=/tmp/shrinkarr.tar.gz bash /tmp/shrinkarr-install.sh; rm -f /tmp/shrinkarr.tar.gz /tmp/shrinkarr-install.sh'
