# Fast build: start from an already-built base image (see Dockerfile.base and
# the README), copy in the local board/config files, and re-run the build.
#
# Some config changes don't make Buildroot rebuild what they affect, so the
# steps below force the kernel, BusyBox, U-Boot and the boot script to be
# rebuilt. The apps are laid out afresh every time (board/licheepi_nano/post-image.sh).
#
# For tools/apps/layout.py (deploy, pack), which compiles an app's C part, tag this build's toolchain too
# (instant once the build has run, as every step is cached):
#   container build --build-arg BASE_IMAGE=licheepi-nano-mybase --target local -t licheepi-nano-dev .

ARG BASE_IMAGE=unframework/licheepi-nano-buildroot
ARG BASE_VERSION=latest

FROM $BASE_IMAGE:$BASE_VERSION AS local

# every app in apps/ goes on the SD card's apps partition (see docs/apps.md); this is the one that
# starts at first boot: chess (the chess clock), castle or cruise (countdowns, on the countdown
# runtime). `app NAME` on the board, or Settings > Apps, switches later.
ARG APP=chess
# WiFi through an ESP32 on SPI1 (package/esp-hosted): 1 to include it, with TLS for Python (OpenSSL
# and the CA certificates: the cruise app's AIS feed, apps/cruise/ais.py, is over a secure websocket). It costs about 4 MB of the
# Nano's 32 MB: with the countdown too, it needs the swap file S01swap makes.
ARG WIFI=0

# copy newest version of local files
WORKDIR /root/licheepi-nano
COPY board/ board/
COPY configs/ configs/
COPY package/ package/
COPY apps/ apps/
COPY tools/apps/ tools/apps/
COPY \
    Config.in \
    external.desc \
    external.mk \
    ./

WORKDIR /root/buildroot
RUN BR2_EXTERNAL=/root/licheepi-nano make licheepi_nano_defconfig
RUN [ -f "/root/licheepi-nano/apps/$APP/run" ] || { echo "APP must be an app in apps/ (chess, castle, cruise), not $APP"; exit 1; }
# the apps used to be packages installed into the root filesystem: clear out what the base image has
RUN cd output/target && rm -rf etc/init.d/S00splash etc/init.d/S99fbclock etc/init.d/S99vacation \
        usr/bin/fbclock usr/bin/vacation usr/sbin/setcpu usr/lib/libvacfx.so etc/fbclock.conf etc/vacation.conf \
        usr/share/fbclock usr/share/vacation var/lib/fbclock var/lib/vacation \
        usr/lib/python3.*/site-packages/fbclock.pyc usr/lib/python3.*/site-packages/vacation*.pyc
RUN if [ "$WIFI" = 1 ]; then \
        echo 'BR2_PACKAGE_ESP_HOSTED=y' >> .config && \
        echo 'BR2_LINUX_KERNEL_CONFIG_FRAGMENT_FILES="$(BR2_EXTERNAL_LICHEEPI_NANO_PATH)/board/licheepi_nano/linux/wifi.fragment"' >> .config && \
        echo 'BR2_PACKAGE_PYTHON3_SSL=y' >> .config && \
        echo 'BR2_PACKAGE_CA_CERTIFICATES=y' >> .config && \
        make olddefconfig && \
        rm -rf output/build/python3-3*; \
    else rm -f output/target/etc/init.d/S35wifi output/target/etc/init.d/S50dropbear; fi

# Rebuild the kernel from a freshly unpacked source tree: the base image may
# hold a different kernel version, and kernel patches are only applied when
# the source is unpacked. (The tarball itself is cached, so this is quick.)
RUN rm -rf output/build/linux-custom
# (BusyBox too, so changes to its config fragment take effect)
RUN rm -rf output/build/busybox-*
# (U-Boot from scratch too, so changes to its config fragment take effect)
RUN rm -rf output/build/uboot-v2021.01-f1c100s-4
RUN cd output/build/host-uboot-tools-2021.07/ && rm -f .stamp_built .stamp_*installed
RUN cd output/build/linux-firmware-20221214/ && rm -f .stamp_built .stamp_*installed

# turning a package off doesn't remove what it already installed
RUN rm -f output/target/etc/init.d/S40network

# re-run build (post-image.sh lays out the apps partition from apps/, with tools/apps/layout.py)
RUN DEFAULT_APP=$APP make

# expose built image files in standalone root folder
FROM scratch AS localout
COPY --from=local /root/buildroot/output/images/ .
