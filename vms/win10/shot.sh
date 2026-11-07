#!/bin/sh
H=$(cd "$(dirname "$0")" && pwd)    # this VM's folder
. $H/vm.env                         # VM_CONTAINER
# shot.sh name  → desktop/<name>.png (a capture of the VM's real display)
set -e
f=shot-$$-$(date +%s).ppm
docker exec "$VM_CONTAINER" python3 /storage/vmctl.py "screendump /storage/$f" >/dev/null
sleep 1
mkdir -p $H/desktop
# Pillow on purpose: its PNGs measured the best for size and quality
${PYTHON:-python3} -c "from PIL import Image; Image.open('$H/storage/$f').save('$H/desktop/$1.png')"
docker exec "$VM_CONTAINER" rm -f /storage/$f
echo $H/desktop/$1.png
