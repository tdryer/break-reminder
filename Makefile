.PHONY: install
install:
	cp break-reminder ~/.local/bin/
	cp break-reminder.service ~/.config/systemd/user/
	systemctl --user enable break-reminder --now

.PHONY: uninstall
uninstall:
	systemctl --user disable break-reminder --now || true
	rm -f ~/.local/bin/break-reminder ~/.config/systemd/user/break-reminder.service

.PHONY: check
check:
	black --check --quiet break-reminder
	ruff check break-reminder

.PHONY: clean
clean:
	rm -rf __pycache__ *.deb *.buildinfo *.changes
