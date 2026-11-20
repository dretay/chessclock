# Fast build: start from an already-built base image (see Dockerfile.base and
# the README), copy in the local board/config files, and re-run the build.
#
# Some config changes don't make Buildroot rebuild what they affect, so the
# steps below force the kernel, the clock, U-Boot and the boot script to be
# rebuilt.

ARG BASE_IMAGE=unframework/licheepi-nano-buildroot
ARG BASE_VERSION=latest

FROM $BASE_IMAGE:$BASE_VERSION AS local

# copy newest version of local files
WORKDIR /root/licheepi-nano
COPY board/ board/
COPY configs/ configs/
COPY package/ package/
COPY clock/ clock/
COPY \
    Config.in \
    external.desc \
    external.mk \
    ./

WORKDIR /root/buildroot
RUN BR2_EXTERNAL=/root/licheepi-nano make licheepi_nano_defconfig

# Rebuild the kernel from a freshly unpacked source tree: the base image may
# hold a different kernel version, and kernel patches are only applied when
# the source is unpacked. (The tarball itself is cached, so this is quick.)
RUN rm -rf output/build/linux-custom
# the clock is a local package: Buildroot only copies its source in once, so
# start it afresh to pick up changes in clock/
RUN rm -rf output/build/fbclock-*
RUN cd output/build/uboot-v2021.01-f1c100s-4/ && rm -f .stamp_built .stamp_*installed
RUN cd output/build/host-uboot-tools-2021.07/ && rm -f .stamp_built .stamp_*installed
RUN cd output/build/linux-firmware-20221214/ && rm -f .stamp_built .stamp_*installed

# re-run build
RUN make

# expose built image files in standalone root folder
FROM scratch AS localout
COPY --from=local /root/buildroot/output/images/ .
