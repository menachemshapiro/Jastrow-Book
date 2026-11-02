#!/bin/bash
# audit.py (stages 1-4) over the whole book, 100 pages per batch (one run folder each, in work/audit/runs/).
# usage: bash build/audit/audit_all.sh [FIRST] [LAST]      (default 1 1800)
cd "$(dirname "$0")/../.." || exit 1
source ~/jastrow/venv/bin/activate
first=${1:-1}; last=${2:-1800}
for a in $(seq "$first" 100 "$last"); do
  echo "=== pages $a-$((a + 99))  $(date '+%H:%M')"
  python3 build/audit/audit.py --pages "$a-$((a + 99))"
done
echo "=== all done  $(date '+%H:%M')"
