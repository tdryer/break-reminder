.PHONY: check
check:
	black --check break_reminder.py
	ruff check break_reminder.py
	@echo OK
