#!/bin/sh
# The variables the web-prepackage hook writes must be exactly the ones config.ts requires.
set -eu
cd "$(dirname "$0")/../.."
required="$(sed -n 's/^const REQUIRED = \[\(.*\)\] as const;/\1/p' clients/web/src/config.ts | tr -d '" ' | tr ',' '\n' | sort)"
written="$(sed -n 's/^\(VITE_[A-Z_]*\)=.*/\1/p' hooks/web-prepackage.sh | sort)"
[ -n "$required" ] || { echo "could not read REQUIRED from config.ts" >&2; exit 1; }
if [ "$required" != "$written" ]; then
  echo "mismatch: config.ts requires:\n$required\nhook writes:\n$written" >&2
  exit 1
fi
echo "web env names ok"
