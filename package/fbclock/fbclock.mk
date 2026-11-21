################################################################################
#
# fbclock - the chess clock application (source in clock/)
#
################################################################################

FBCLOCK_VERSION = 1.0
FBCLOCK_SITE = $(BR2_EXTERNAL_LICHEEPI_NANO_PATH)/clock
FBCLOCK_SITE_METHOD = local
FBCLOCK_LICENSE = GPL-3.0
FBCLOCK_DEPENDENCIES = python3

# The program goes in as a Python module, so it is compiled once while the
# image is built (BR2_PACKAGE_PYTHON3_PYC_ONLY) instead of at every start,
# which takes seconds on this CPU; /usr/bin/fbclock is a small launcher.
FBCLOCK_MODULE_DIR = $(TARGET_DIR)/usr/lib/python$(PYTHON3_VERSION_MAJOR)/site-packages

define FBCLOCK_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0644 $(@D)/fbclock.py $(FBCLOCK_MODULE_DIR)/fbclock.py
	$(INSTALL) -D -m 0755 $(@D)/fbclock $(TARGET_DIR)/usr/bin/fbclock
	rm -f $(TARGET_DIR)/usr/bin/fbclock.py   # where earlier versions went
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
