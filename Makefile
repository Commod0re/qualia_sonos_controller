#!/usr/bin/make -f


INSTALL_PREFIX := $(shell mount | awk '/CIRCUITPY/ {print $3}')
REQUIRES := biplane



.PHONY: circup install

circup:
	circup install $(REQUIRES)


install:
	$(abort NOT_IMPLEMENTED)

