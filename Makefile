.PHONY: test check-shell install install-all verify install-desklet

test:
	python3 -m pytest -q

check-shell:
	@for f in tools/*.sh; do bash -n $$f || exit 1; done; echo "shell OK"

# NOTE: the running app reads the INSTALLED copy at ~/.local/share/nudge,
# never this checkout. Editing a file here and restarting the daemon changes
# nothing until you `make install`. That gap produced two confusing bug
# reports on 2026-09-26 (a parser fix that never reached the app, and a
# popup whose window type was fixed only in source). Run this after any
# source edit — it is the only step that makes changes real.
install: check-shell test
	tools/install-service.sh

# Install code + desklet together, then prove the installed copy matches
# source. Prefer this over bare `install` when you have touched nudge/ or
# desklet/.
install-all: install install-desklet
	tools/verify-install.sh

install-desklet: check-shell
	tools/install-desklet.sh

# fail loudly if the installed copy has drifted from source
verify: 
	tools/verify-install.sh
