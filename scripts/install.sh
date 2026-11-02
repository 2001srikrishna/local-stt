#!/usr/bin/env bash
# Reuse an installed STT venv; don't download models or touch account credentials.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="$HOME/.local/share/opencode-stt/venv/bin/python"
[[ -x "$python_bin" ]] || { echo 'Create the environment described in README.md first.' >&2; exit 1; }
"$python_bin" -c 'import sounddevice, numpy, scipy, pynput'
mkdir -p "$HOME/.config/systemd/user" "$HOME/.config/local-stt" "$HOME/.local/state/opencode-stt" "$HOME/bin"
if [[ -e "$HOME/stt.py" && ! -L "$HOME/stt.py" ]]; then
    cp -p "$HOME/stt.py" "$HOME/.local/state/opencode-stt/stt.py.backup-$(date +%Y%m%dT%H%M%S)"
fi
if [[ "$(readlink -f "$HOME/stt.py" 2>/dev/null || true)" != "$repo_dir/stt.py" ]]; then
    ln -sfn "$repo_dir/stt.py" "$HOME/stt.py"
fi
cat > "$HOME/.config/systemd/user/local-stt.service" <<'EOF'
[Unit]
Description=Shared local and Groq push-to-talk dictation
After=graphical-session.target local-stt-engine.service
Wants=local-stt-engine.service

[Service]
ExecStart=%h/.local/share/opencode-stt/venv/bin/python -u %h/stt.py
Environment=PYTHONUNBUFFERED=1
Environment=STT_RESIDENT=1
Restart=on-failure
RestartSec=3
MemoryMax=4G
MemorySwapMax=512M
TimeoutStopSec=5
KillMode=control-group

[Install]
WantedBy=default.target
EOF
cat > "$HOME/.config/systemd/user/local-stt-engine.service" <<'EOF'
[Unit]
Description=Resident CPU Whisper engine for dictation (loopback only)
PartOf=local-stt.service

[Service]
ExecStart=%h/.local/share/opencode-stt/venv/bin/python -u %h/stt.py --serve
Restart=on-failure
RestartSec=2
MemoryMax=4G
MemorySwapMax=512M
TimeoutStopSec=5
KillMode=control-group
EOF
cat > "$HOME/bin/stt" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-start}" in
    start|stop|restart|status) exec systemctl --user "${1:-start}" local-stt.service ;;
    logs) exec journalctl --user -u local-stt.service -n 30 --no-pager ;;
    devices) exec "$HOME/.local/share/opencode-stt/venv/bin/python" "$HOME/stt.py" --devices ;;
    *) echo 'Usage: stt {start|stop|restart|status|logs|devices}' >&2; exit 2 ;;
esac
EOF
chmod +x "$HOME/bin/stt"
systemctl --user daemon-reload
printf '%s\n' 'Installed. Run ~/bin/stt start. Existing listeners must be stopped first.'
