.PHONY: install start stop restart status logs clean

UNAME_S := $(shell uname -s)

ifeq ($(UNAME_S),Darwin)
# macOS launchd configuration
PLIST_NAME = com.brain.llm-agent-watcher.plist
USER_LAUNCHD_DIR = $(HOME)/Library/LaunchAgents

install:
	mkdir -p $(USER_LAUNCHD_DIR) $(HOME)/.local/share/brain-llm
	cp $(PLIST_NAME) $(USER_LAUNCHD_DIR)/$(PLIST_NAME)
	launchctl load -w $(USER_LAUNCHD_DIR)/$(PLIST_NAME)
	@echo "==> $(PLIST_NAME) zainstalowany i załadowany w launchd (macOS)."

start:
	launchctl start com.brain.llm-agent-watcher

stop:
	launchctl stop com.brain.llm-agent-watcher

restart:
	launchctl stop com.brain.llm-agent-watcher
	launchctl start com.brain.llm-agent-watcher

status:
	launchctl list | grep com.brain.llm-agent-watcher || echo "Service not running."

logs:
	tail -f $(HOME)/.local/share/brain-llm/watcher.log

clean:
	-launchctl unload -w $(USER_LAUNCHD_DIR)/$(PLIST_NAME)
	rm -f $(USER_LAUNCHD_DIR)/$(PLIST_NAME)
	@echo "==> $(PLIST_NAME) odinstalowany z launchd."

else
# Linux systemd configuration
SERVICE_FILE = llm-agent-watcher.service
USER_SYSTEMD_DIR = $(HOME)/.config/systemd/user

install:
	mkdir -p $(USER_SYSTEMD_DIR) $(HOME)/.local/share/brain-llm
	cp $(SERVICE_FILE) $(USER_SYSTEMD_DIR)/$(SERVICE_FILE)
	systemctl --user daemon-reload
	systemctl --user enable --now $(SERVICE_FILE)
	@echo "==> $(SERVICE_FILE) zainstalowany i uruchomiony w systemd --user (Linux)."

start:
	systemctl --user start $(SERVICE_FILE)

stop:
	systemctl --user stop $(SERVICE_FILE)

restart:
	systemctl --user restart $(SERVICE_FILE)

status:
	systemctl --user status $(SERVICE_FILE)

logs:
	journalctl --user -u $(SERVICE_FILE) -f -n 50

clean:
	-systemctl --user stop $(SERVICE_FILE)
	-systemctl --user disable $(SERVICE_FILE)
	rm -f $(USER_SYSTEMD_DIR)/$(SERVICE_FILE)
	systemctl --user daemon-reload
	@echo "==> $(SERVICE_FILE) odinstalowany z systemd."

endif
