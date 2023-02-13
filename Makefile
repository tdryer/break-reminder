.PHONY: check
check:
	@black --check --quiet break_reminder.py
	@ruff check break_reminder.py
