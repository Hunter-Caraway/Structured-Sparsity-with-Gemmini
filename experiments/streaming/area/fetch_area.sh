#!/bin/bash
# Copy a finished area run back from the server and verify its checksums.
# Usage: fetch_area.sh <run name, e.g. 20261117-150000-GemminiRocketConfig-nangate45-area>
# No tar/rsync on the server: each file comes over ssh cat, then sha256sum -c.
set -euo pipefail
[ $# -eq 1 ] || { sed -n '2,4p' "$0"; exit 2; }
NAME=$(basename "$1")
HERE=$(cd "$(dirname "$0")" && pwd)
H=ai-user@ai-1769.floridapoly.org
SSH=(ssh -o ControlPath=/tmp/claude-1000/cm-%C -o BatchMode=yes -o ConnectTimeout=15 "$H")
SRC="area/runs/$NAME"
DST="$HERE/runs/$NAME"

status=$("${SSH[@]}" "cat ~/$SRC/STATUS 2>/dev/null || echo RUNNING")
[ "$status" = DONE ] || { echo "$NAME: STATUS=$status"; exit 1; }
[ ! -e "$DST" ] || { echo "$DST exists; recorded runs are never overwritten"; exit 1; }
mkdir -p "$DST"
"${SSH[@]}" "cat ~/$SRC/SHA256SUMS" > "$DST/SHA256SUMS"
for f in $(cut -d' ' -f3 "$DST/SHA256SUMS") STATUS nohup.out; do
  mkdir -p "$DST/$(dirname "$f")"
  "${SSH[@]}" "cat ~/$SRC/$f" > "$DST/$f"
done
(cd "$DST" && sha256sum -c --quiet SHA256SUMS)
echo "fetched and verified $DST"
