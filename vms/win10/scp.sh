#!/bin/sh
# scp.sh SRC... DEST: copy to or from this VM (vm.env); the VM's side is "$VM_SSH_USER@127.0.0.1:PATH"
H=$(cd "$(dirname "$0")" && pwd); . "$H/vm.env"
exec scp -q -i "$H/$VM_SSH_KEY" -P "$VM_SSH_PORT" -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$H/$VM_KNOWN_HOSTS" -o BatchMode=yes "$@"
