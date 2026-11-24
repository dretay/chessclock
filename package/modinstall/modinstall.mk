################################################################################
#
# modinstall - check a module's signature, and install it (source in src/)
#
################################################################################

MODINSTALL_VERSION = 1
MODINSTALL_SITE = $(BR2_EXTERNAL_LICHEEPI_NANO_PATH)/package/modinstall/src
MODINSTALL_SITE_METHOD = local
MODINSTALL_LICENSE = GPL-3.0+, BSD-2-Clause or CC0-1.0 (Monocypher)
MODINSTALL_LICENSE_FILES = monocypher/LICENCE.md
MODINSTALL_DEPENDENCIES = zlib

define MODINSTALL_BUILD_CMDS
	$(TARGET_CC) $(TARGET_CFLAGS) -Os -Wall -o $(@D)/modinstall $(@D)/modinstall.c \
		$(@D)/monocypher/monocypher.c $(@D)/monocypher/monocypher-ed25519.c $(TARGET_LDFLAGS) -lz
endef

define MODINSTALL_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/modinstall $(TARGET_DIR)/usr/bin/modinstall
endef

$(eval $(generic-package))
