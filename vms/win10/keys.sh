#!/bin/sh
# keys.sh key [key...]  → QEMU sendkey for each (e.g. alt-y, ret, tab)
H=$(cd "$(dirname "$0")" && pwd); . $H/vm.env    # VM_CONTAINER
for k in "$@"; do docker exec "$VM_CONTAINER" python3 /storage/vmctl.py "sendkey $k" >/dev/null; sleep 0.4; done
