#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
/usr/bin/python3 -c 'from PySide6 import QtWidgets, QtDBus'
mkdir -p "$HOME/.config/systemd/user" "$HOME/.local/share/applications"
cat > "$HOME/.config/systemd/user/local-stt-tray.service" <<EOF
[Unit]
Description=Local STT tray and settings
After=graphical-session.target
PartOf=graphical-session.target

[Service]
ExecStart=/usr/bin/python3 "$repo_dir/tray_app.py"
MemoryMax=512M
MemorySwapMax=128M
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
EOF
cat > "$HOME/.local/share/applications/local-stt-tray.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Local STT
Comment=Dictation tray and settings
Exec=/usr/bin/python3 "$repo_dir/tray_app.py" --settings
Icon=audio-input-microphone
Terminal=false
Categories=Utility;Accessibility;
EOF
systemctl --user daemon-reload
systemctl --user enable --now local-stt-tray.service
