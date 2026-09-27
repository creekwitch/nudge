#!/usr/bin/env bash
# Install nudge as a systemd user service.
# Usage: tools/install-service.sh [checkout-dir] (default: this repo's parent)
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
LIB_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/nudge"

mkdir -p "$LIB_DIR" "$HOME/.config/nudge" "$HOME/.local/state/nudge"
# daemon imports the nudge package; run from a stable copy
rsync -a --delete "$SRC/nudge/" "$LIB_DIR/nudge/"
mkdir -p "$LIB_DIR/sounds"
cp -f "$SRC/sounds/chime.ogg" "$LIB_DIR/sounds/chime.ogg" 2>/dev/null || true
# The settings panel is served from disk by server.py, which looks for
# <lib>/ui/. Without this the CLI installs fine and `nudge ui` dies with
# FileNotFoundError on ui/index.html — the GUI is unreachable from an
# installed copy.
rsync -a --delete "$SRC/ui/" "$LIB_DIR/ui/"
cp -f "$SRC/nudge.service" "$HOME/.config/systemd/user/nudge.service"
# CLI on PATH: thin launcher that runs the installed copy on system python
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/nudge" <<EOF
#!/usr/bin/env python3
import sys
sys.path.insert(0, "$LIB_DIR")
from nudge.cli import main
sys.exit(main())
EOF
chmod +x "$HOME/.local/bin/nudge"
# unit runs from the installed copy
sed -i "s|ExecStart=.*|ExecStart=/usr/bin/python3 -c \"import sys; sys.path.insert(0,'$LIB_DIR'); from nudge.cli import main; sys.exit(main())\" start|" \
  "$HOME/.config/systemd/user/nudge.service"

systemctl --user daemon-reload
systemctl --user enable --now nudge.service
sleep 1
systemctl --user --no-pager status nudge.service | head -5
echo "installed. logs: ~/.local/state/nudge/log  |  config: ~/.config/nudge/"
