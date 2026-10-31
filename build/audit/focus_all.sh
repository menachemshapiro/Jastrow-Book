#!/bin/bash
# focus.py over the whole book, 100 pages per batch (one report folder each, in work/audit/focus/).
# usage: bash build/audit/focus_all.sh [FIRST] [LAST]      (default 1 1800)
cd "$(dirname "$0")/../.." || exit 1
source ~/jastrow/venv/bin/activate
first=${1:-1}; last=${2:-1800}
for a in $(seq "$first" 100 "$last"); do
  echo "=== pages $a-$((a + 99))  $(date '+%H:%M')"
  python3 build/audit/focus.py --pages "$a-$((a + 99))"
done
echo "=== all done  $(date '+%H:%M')"
