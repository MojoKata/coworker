#!/bin/sh
# ssh.sh [COMMAND]: SSH into this VM as its projects do (vm.env)
H=$(cd "$(dirname "$0")" && pwd); . "$H/vm.env"
exec ssh -q -i "$H/$VM_SSH_KEY" -p "$VM_SSH_PORT" -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$H/$VM_KNOWN_HOSTS" -o BatchMode=yes "$VM_SSH_USER@${VM_SSH_HOST:-127.0.0.1}" "$@"
