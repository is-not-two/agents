#!/bin/sh
set -eu
[ "$#" -eq 1 ] || { echo "Usage: $0 target-copy" >&2; exit 2; }
here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cp -- "$here/BASELINE.py" "$1"
