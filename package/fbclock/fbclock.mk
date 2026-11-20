################################################################################
#
# fbclock - the chess clock application (source in clock/)
#
################################################################################

FBCLOCK_VERSION = 1.0
FBCLOCK_SITE = $(BR2_EXTERNAL_LICHEEPI_NANO_PATH)/clock
FBCLOCK_SITE_METHOD = local
FBCLOCK_LICENSE = GPL-3.0

define FBCLOCK_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/fbclock.py $(TARGET_DIR)/usr/bin/fbclock.py
	$(INSTALL) -D -m 0644 $(@D)/games.pgn $(TARGET_DIR)/usr/share/fbclock/games.pgn
	for f in $(@D)/splash/*.raw.gz; do \
		$(INSTALL) -D -m 0644 $$f $(TARGET_DIR)/usr/share/fbclock/$$(basename $$f) || exit 1; \
	done
	$(INSTALL) -D -m 0644 $(@D)/fbclock.conf $(TARGET_DIR)/etc/fbclock.conf
endef

define FBCLOCK_INSTALL_INIT_SYSV
	$(INSTALL) -D -m 0755 $(@D)/init.d/S00splash $(TARGET_DIR)/etc/init.d/S00splash
	$(INSTALL) -D -m 0755 $(@D)/init.d/S99fbclock $(TARGET_DIR)/etc/init.d/S99fbclock
endef

$(eval $(generic-package))
