################################################################################
#
# fbvacation - the vacation countdown (source in vacation/)
#
################################################################################

FBVACATION_VERSION = 1.0
FBVACATION_SITE = $(BR2_EXTERNAL_LICHEEPI_NANO_PATH)/vacation
FBVACATION_SITE_METHOD = local
FBVACATION_LICENSE = GPL-3.0
FBVACATION_DEPENDENCIES = python3 zlib

# the theme to install (a folder in vacation/themes made by tools/themegen)
FBVACATION_THEMES = dream
FBVACATION_MODULE_DIR = $(TARGET_DIR)/usr/lib/python$(PYTHON3_VERSION_MAJOR)/site-packages

define FBVACATION_BUILD_CMDS
	$(TARGET_CC) $(TARGET_CFLAGS) -O2 -Wall -shared -fPIC -o $(@D)/fx/libvacfx.so $(@D)/fx/vacfx.c $(TARGET_LDFLAGS) -lz
endef

define FBVACATION_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/fx/libvacfx.so $(TARGET_DIR)/usr/lib/libvacfx.so
	$(INSTALL) -D -m 0644 $(@D)/vacation.py $(FBVACATION_MODULE_DIR)/vacation.py
	$(INSTALL) -D -m 0644 $(@D)/vacation_settings.py $(FBVACATION_MODULE_DIR)/vacation_settings.py
	$(INSTALL) -D -m 0644 $(@D)/vacation_touch.py $(FBVACATION_MODULE_DIR)/vacation_touch.py
	$(INSTALL) -D -m 0644 $(@D)/vacation_layout.py $(FBVACATION_MODULE_DIR)/vacation_layout.py
	$(INSTALL) -D -m 0644 $(@D)/ui/ui.bin.gz $(TARGET_DIR)/usr/share/vacation/ui/ui.bin.gz
	$(INSTALL) -D -m 0644 $(@D)/fonts/OFL.txt $(TARGET_DIR)/usr/share/vacation/ui/OFL.txt
	$(INSTALL) -D -m 0755 $(@D)/vacation $(TARGET_DIR)/usr/bin/vacation
	$(INSTALL) -D -m 0755 $(@D)/native/setcpu.sh $(TARGET_DIR)/usr/sbin/setcpu
	$(INSTALL) -D -m 0644 $(@D)/vacation.conf $(TARGET_DIR)/etc/vacation.conf
	for t in $(FBVACATION_THEMES); do \
		for f in $(@D)/themes/$$t/*.gz $(@D)/themes/$$t/theme.json; do \
			$(INSTALL) -D -m 0644 $$f $(TARGET_DIR)/usr/share/vacation/themes/$$t/$$(basename $$f) || exit 1; \
		done; \
	done
endef

define FBVACATION_INSTALL_INIT_SYSV
	$(INSTALL) -D -m 0755 $(@D)/init.d/S99vacation $(TARGET_DIR)/etc/init.d/S99vacation
endef

$(eval $(generic-package))
