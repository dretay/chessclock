################################################################################
#
# esp-hosted-nano - WiFi through an ESP32 on SPI (the host side of esp-hosted-linux)
#
################################################################################

ESP_HOSTED_NANO_VERSION = 477d5e5a3931b6a549a8a82c5cb3ce934018badc
ESP_HOSTED_NANO_SITE = $(call github,espressif,esp-hosted-linux,$(ESP_HOSTED_NANO_VERSION))
ESP_HOSTED_NANO_LICENSE = GPL-2.0
ESP_HOSTED_NANO_LICENSE_FILES = host/LICENSE

# the kernel module: host/ is a kbuild directory; target=spi picks the SPI transport
ESP_HOSTED_NANO_MODULE_SUBDIRS = host
ESP_HOSTED_NANO_MODULE_MAKE_OPTS = target=spi

define ESP_HOSTED_NANO_LINUX_CONFIG_FIXUPS
	$(call KCONFIG_ENABLE_OPT,CONFIG_MODULES)
	$(call KCONFIG_ENABLE_OPT,CONFIG_INET)
	$(call KCONFIG_ENABLE_OPT,CONFIG_CFG80211)
	$(call KCONFIG_SET_OPT,CONFIG_BT,m)
	$(call KCONFIG_ENABLE_OPT,CONFIG_SPI)
	$(call KCONFIG_ENABLE_OPT,CONFIG_SPI_SUN6I)
endef

define ESP_HOSTED_NANO_INSTALL_INIT_SYSV
	$(INSTALL) -D -m 0755 $(ESP_HOSTED_NANO_PKGDIR)/S35wifi $(TARGET_DIR)/etc/init.d/S35wifi
	$(INSTALL) -D -m 0600 $(ESP_HOSTED_NANO_PKGDIR)/wpa_supplicant.conf $(TARGET_DIR)/etc/wpa_supplicant.conf
endef

$(eval $(kernel-module))
$(eval $(generic-package))
