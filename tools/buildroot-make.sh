#!/bin/bash
# Runs inside the build container for tools/build.sh (see there): the Dockerfile's fast build, done
# incrementally in a Buildroot tree that persists (/root/buildroot, a volume). WIFI=0|1,
# DEFAULT_APP; the repository at /root/licheepi-nano; the images go to /images.
set -e
BR=/root/buildroot; EXT=/root/licheepi-nano; OUT=$BR/output
cd "$BR"

# (tools/build.sh seeds the volume from the base image before the first build)
[ -d "$OUT/build" ] || { echo "the build tree is empty: run tools/build.sh, which seeds it"; exit 1; }

BR2_EXTERNAL=$EXT make licheepi_nano_defconfig >/dev/null
if [ "$WIFI" = 1 ]; then
	echo 'BR2_PACKAGE_ESP_HOSTED=y' >> .config
	echo 'BR2_LINUX_KERNEL_CONFIG_FRAGMENT_FILES="$(BR2_EXTERNAL_LICHEEPI_NANO_PATH)/board/licheepi_nano/linux/wifi.fragment"' >> .config
	echo 'BR2_PACKAGE_PYTHON3_SSL=y' >> .config
	echo 'BR2_PACKAGE_CA_CERTIFICATES=y' >> .config
	make olddefconfig >/dev/null
else
	rm -f "$OUT"/target/etc/init.d/S35wifi "$OUT"/target/etc/init.d/S50dropbear
fi
# the apps used to be packages installed into the root filesystem (harmless once they're gone)
(cd "$OUT/target" && rm -rf etc/init.d/S00splash etc/init.d/S99fbclock etc/init.d/S99vacation \
	usr/bin/fbclock usr/bin/vacation usr/lib/libvacfx.so etc/fbclock.conf etc/vacation.conf \
	usr/share/fbclock usr/share/vacation var/lib/fbclock var/lib/vacation \
	usr/lib/python3.*/site-packages/fbclock.pyc usr/lib/python3.*/site-packages/vacation*.pyc \
	etc/init.d/S40network)

# what Buildroot can't see changing: when these inputs change, start that package over
STATE=$OUT/.input-hashes; touch "$STATE"
hash_of() { (cd "$EXT" && find "$@" -type f 2>/dev/null | sort | xargs cat 2>/dev/null; echo "wifi=$WIFI") | sha256sum | cut -c1-16; }
redo() {   # redo NAME 'how to clean' INPUT...
	local name=$1 clean=$2; shift 2
	local h; h=$(hash_of "$@")
	if [ "$(sed -n "s/^$name=//p" "$STATE")" != "$h" ]; then
		echo "rebuilding $name (its inputs changed)"; eval "$clean"
		grep -v "^$name=" "$STATE" > "$STATE.tmp" || true; echo "$name=$h" >> "$STATE.tmp"; mv "$STATE.tmp" "$STATE"
	fi
}
redo linux 'rm -rf "$OUT"/build/linux-custom' board/licheepi_nano/linux configs/licheepi_nano_defconfig
redo busybox 'rm -rf "$OUT"/build/busybox-*' board/licheepi_nano/busybox.fragment
redo uboot 'rm -rf "$OUT"/build/uboot-*' board/licheepi_nano/uboot.fragment
redo bootscript 'rm -f "$OUT"/build/host-uboot-tools-*/.stamp_built "$OUT"/build/host-uboot-tools-*/.stamp_*installed' board/licheepi_nano/boot.cmd
redo esp-hosted 'rm -rf "$OUT"/build/esp-hosted-*' package/esp-hosted
redo python3 'rm -rf "$OUT"/build/python3-3*' configs/licheepi_nano_defconfig      # (and wifi=, for its TLS)
# linux-firmware's install is cheap and depends on the kernel config: always
rm -f "$OUT"/build/linux-firmware-*/.stamp_built "$OUT"/build/linux-firmware-*/.stamp_*installed

make
rm -rf /images/*; cp -rL "$OUT"/images/* /images/      # (files, not the folder: the Mac's shared folder keeps its own times)
echo "built: $(ls /images | tr '\n' ' ')"
