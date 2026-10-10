#!/usr/bin/env bash
# Times a few `pman -k` queries against whatever is installed in the real PMAN_HOME (or a given one).
# Usage: tools/bench.sh [pman_home]
set -euo pipefail
BIN="${PMAN_BIN:-./target/release/pman.exe}"
[ -x "$BIN" ] || BIN="./target/release/pman"
if [ $# -ge 1 ]; then export PMAN_HOME="$1"; fi

queries=(
  "list comprehension"
  "proxy_pass"
  "zzzzqq"
  "z"
  "fetch"
  "fs.readFile"
)

echo "pman reindex (ensure every pack has search.idx)..."
"$BIN" reindex >/dev/null 2>&1 || true

printf "%-28s %8s %8s %8s\n" query run1 run2 run3
for q in "${queries[@]}"; do
  times=()
  for i in 1 2 3; do
    start=$(date +%s%N)
    "$BIN" -k "$q" >/dev/null 2>&1 </dev/null || true
    end=$(date +%s%N)
    times+=("$(( (end - start) / 1000000 ))")
  done
  printf "%-28s %6sms %6sms %6sms\n" "$q" "${times[0]}" "${times[1]}" "${times[2]}"
done
