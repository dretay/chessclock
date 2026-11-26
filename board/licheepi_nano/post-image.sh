#!/bin/bash -e
# based on https://github.com/Squonk42/buildroot-licheepi-zero

BOARD_DIR="$(dirname $0)"
EXT="${BR2_EXTERNAL_LICHEEPI_NANO_PATH}"

# the apps partition (/apps on the board; see docs/apps.md): every app in apps/ (the system package, the
# countdown runtime and the countdown apps on it), laid out by tools/apps/layout.py as deploy and
# packing do, with the drawing library compiled for the board and the Python pre-compiled (the
# build's Python is the board's version) so the first start isn't slow. They go unsigned: the image
# is where they come from. DEFAULT_APP (the Dockerfile's APP) is the one that starts at first boot;
# `app NAME` on the board, or Settings > Apps, switches.
APPS_SIZE=128M
APPS_ROOT="${BUILD_DIR}/apps-root"
rm -rf "${APPS_ROOT}"
mkdir -p "${APPS_ROOT}/data"
for a in "${EXT}"/apps/*/app.json; do
  a=$(basename "$(dirname "$a")")
  CC="${HOST_DIR}/bin/arm-linux-gcc" "${HOST_DIR}/bin/python3" "${EXT}/tools/apps/layout.py" --local "$a" "${APPS_ROOT}/$a" >/dev/null
done
echo "${DEFAULT_APP:-castle}" > "${APPS_ROOT}/current"
"${HOST_DIR}/bin/python3" -m compileall -q -o 0 -o 2 "${APPS_ROOT}"     # (-o 2: for the python3 -OO the countdown and system run)
rm -f "${BINARIES_DIR}/apps.ext4"
"${HOST_DIR}/sbin/mkfs.ext4" -q -L apps -d "${APPS_ROOT}" -E root_owner=0:0 "${BINARIES_DIR}/apps.ext4" "${APPS_SIZE}"

# combined bootable image
GENIMAGE_CFG="${BOARD_DIR}/genimage.cfg"
GENIMAGE_TMP="${BUILD_DIR}/genimage.tmp"

rm -rf "${GENIMAGE_TMP}"

genimage \
  --rootpath "${TARGET_DIR}" \
  --tmppath "${GENIMAGE_TMP}" \
  --inputpath "${BINARIES_DIR}" \
  --outputpath "${BINARIES_DIR}" \
  --config "${GENIMAGE_CFG}"

exit $?
