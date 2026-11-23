#!/bin/bash -e
# based on https://github.com/Squonk42/buildroot-licheepi-zero

BOARD_DIR="$(dirname $0)"
EXT="${BR2_EXTERNAL_LICHEEPI_NANO_PATH}"

# the apps partition (/apps on the board; see docs/apps.md): every app, laid out by its own
# install.sh, with the drawing library compiled for the board and the Python pre-compiled (the
# build's Python is the board's version) so the first start isn't slow. DEFAULT_APP (the Dockerfile's
# APP) is the one that starts at first boot; `app NAME` on the board switches.
APPS="chess=clock vacation=vacation"
APPS_SIZE=128M
APPS_ROOT="${BUILD_DIR}/apps-root"
rm -rf "${APPS_ROOT}"
mkdir -p "${APPS_ROOT}/data"
for a in ${APPS}; do
  CC="${HOST_DIR}/bin/arm-linux-gcc" "${EXT}/${a#*=}/install.sh" "${APPS_ROOT}/${a%%=*}"
done
echo "${DEFAULT_APP:-chess}" > "${APPS_ROOT}/current"
"${HOST_DIR}/bin/python3" -m compileall -q "${APPS_ROOT}"
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
