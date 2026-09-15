#!/usr/bin/env bash
set -Eeuo pipefail

# shellcheck source=scripts/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"
init_runtime_dirs

logs=()
for name in backend ryu frontend; do
    path="$LOG_DIR/$name.log"
    if [[ -f "$path" ]]; then
        logs+=("$path")
    else
        printf '[missing] %s\n' "$path"
    fi
done
if (( ${#logs[@]} == 0 )); then
    printf 'No service logs exist yet. Run ./scripts/start.sh first.\n'
    exit 0
fi
printf 'Following logs (Ctrl-C to stop):\n'
printf '  %s\n' "${logs[@]}"
exec tail -n 80 -F "${logs[@]}"
