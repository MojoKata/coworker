#!/bin/sh
# install.sh [--change]: installs the coworker commands from this checkout into $COWORKER_HOME
# (~/coworker unless set): libexec/downloads, libexec/vms and libexec/deps as bin/* (copies, not
# links), .coworker/deps.json (coworker's own needs), PROTOCOL, and VERSION, what this checkout is
# (git describe). Creates downloads/ and vms/ there if missing and never touches what's in them.
#
# A human's call (or their say-so): a project runs it as <checkout>/coworker/bin/coworker install.
# Over an install of another protocol it needs --change (or COWORKER_UNATTENDED=1, CI's): without it,
# it says what would change, for which projects, and exits 3. README.md, "Installing".
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
if [ -n "${COWORKER_HOME:-}" ]; then H=$COWORKER_HOME
elif [ "$(id -u)" = 0 ] && [ -n "${SUDO_USER:-}" ]; then H=$(getent passwd "$SUDO_USER" | cut -d: -f6)/coworker
else H=$HOME/coworker; fi
CHANGE=0
case ${1:-} in
    --change) CHANGE=1 ;;
    '') ;;
    *) echo "usage: install.sh [--change]" >&2; exit 2 ;;
esac
[ "${COWORKER_UNATTENDED:-}" = 1 ] && CHANGE=1
new=$(cat "$HERE/PROTOCOL")
old=""
if [ -f "$H/PROTOCOL" ]; then old=$(cat "$H/PROTOCOL"); elif [ -x "$H/bin/deps" ]; then old=3; fi
if [ -n "$old" ] && [ "$old" != "$new" ] && [ "$CHANGE" = 0 ]; then
    p=""
    for f in "$H"/projects/*; do [ -f "$f" ] && case $f in *.new) ;; *) p="$p ${f##*/}" ;; esac; done
    echo "coworker in $H is protocol $old; this is $new. Every project on the machine moves with it:${p:- (none seen yet)}." >&2
    echo "When they're all ready (README.md, \"Protocol\"): $HERE/bin/coworker install --change" >&2
    exit 3
fi
mkdir -p "$H/bin" "$H/downloads" "$H/vms" "$H/.coworker"
for f in downloads vms deps; do
    install -m 755 "$HERE/libexec/$f" "$H/bin/.$f.new"
    mv -f "$H/bin/.$f.new" "$H/bin/$f"         # a rename: a run of the old copy keeps going
done
install -m 644 "$HERE/.coworker/deps.json" "$H/.coworker/.deps.json.new"
mv -f "$H/.coworker/.deps.json.new" "$H/.coworker/deps.json"     # coworker's own needs (deps check)
install -m 644 "$HERE/PROTOCOL" "$H/.PROTOCOL.new"
mv -f "$H/.PROTOCOL.new" "$H/PROTOCOL"
v=$(git -C "$HERE" describe --tags --always --dirty 2>/dev/null || echo unknown)
printf '%s\n' "$v" > "$H/VERSION"
if [ -n "$old" ] && [ "$old" != "$new" ]; then
    echo "installed coworker $v (protocol $old -> $new) in $H"
else
    echo "installed coworker $v (protocol $new) in $H"
fi
