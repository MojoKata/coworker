#!/bin/sh
# install.sh: installs the coworker commands from this checkout into $COWORKER_HOME (~/coworker
# unless set): bin/downloads and bin/vms (copies, not links), and VERSION, what this checkout is
# (git describe). Creates downloads/ and vms/ there if missing and never touches what's in them, so
# running it again after a git pull is how to update. README.md, "Installing".
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
H=${COWORKER_HOME:-$HOME/coworker}
mkdir -p "$H/bin" "$H/downloads" "$H/vms"
for f in downloads vms; do
    install -m 755 "$HERE/bin/$f" "$H/bin/.$f.new"
    mv -f "$H/bin/.$f.new" "$H/bin/$f"         # a rename: a run of the old copy keeps going
done
v=$(git -C "$HERE" describe --tags --always --dirty 2>/dev/null || echo unknown)
printf '%s\n' "$v" > "$H/VERSION"
echo "installed coworker $v in $H"
