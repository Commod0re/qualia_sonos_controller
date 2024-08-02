#!/usr/bin/make -f


INSTALL_PREFIX := $(shell mount | awk '/CIRCUITPY/ {print $$3}')
ifneq ($(INSTALL_PREFIX),)
RP = (
LP = )
C = ,
MOUNT_OPTIONS := $(subst $(C), ,$(subst $(LP),,$(subst $(RP),,$(shell mount | awk '/CIRCUITPY/ {print $$6}'))))
else
MOUNT_OPTIONS :=
endif
REQUIRES := biplane



.PHONY: circup install

circup:
	circup install $(REQUIRES)


install:
	$(if $(INSTALL_PREFIX),,$(error qualia not mounted))
	$(if $(filter rw,$(MOUNT_OPTIONS)),,$(error qualia not mounted rw))
	rsync -avuc src/ $(INSTALL_PREFIX)
	sync
