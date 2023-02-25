.PHONY: check
check:
	@black --check --quiet break-reminder
	@ruff check break-reminder

.PHONY: deb
deb:
	@equivs-build break-reminder.equivs

.PHONY: clean
clean:
	rm -rf __pycache__ *.deb *.buildinfo *.changes
