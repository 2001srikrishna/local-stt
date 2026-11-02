#!/usr/bin/env bash
# Fedora KDE setup. Existing installations/artifacts are reused, never replaced.
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
install_system=0;gpu=0;check=0
for arg in "$@"; do
    case "$arg" in
        --install-system) install_system=1 ;;
        --gpu) gpu=1 ;;
        --check) check=1 ;;
        *) echo 'Usage: bash scripts/setup.sh [--install-system] [--gpu] [--check]' >&2;exit 2 ;;
    esac
done
if ((check)); then
    /usr/bin/python3 -c 'import dbus,gi,evdev; from PySide6 import QtWidgets; print("Desktop Python dependencies: OK")'
    "$HOME/.local/share/opencode-stt/venv/bin/python" -c 'import numpy,scipy,sounddevice,groq,httpx; print("STT environment: OK")'
    [[ -x "$HOME/whisper.cpp/whisper-cli" && -x "$HOME/whisper.cpp/whisper-server" && -f "$HOME/whisper.cpp/models/ggml-base.en.bin" ]]
    echo 'Existing CPU runtime/model: OK'
    [[ -w /dev/uinput ]] && echo 'Active-user virtual keyboard access: OK' || echo 'Virtual keyboard unavailable; clipboard fallback only'
    exit 0
fi
if ((install_system)); then
    command -v dnf >/dev/null || { echo '--install-system currently supports Fedora. See README for requirements.' >&2;exit 1; }
    sudo dnf install -y python3 python3-devel python3-pyside6 python3-dbus python3-gobject python3-evdev portaudio-devel wl-clipboard xclip libnotify git gcc gcc-c++ cmake ninja-build
    # Restrict permission to the active local session; do not chmod a device world-writable.
    if [[ ! -w /dev/uinput ]]; then
        rule_file=/etc/udev/rules.d/70-local-stt-uinput.rules
        if ! sudo test -e "$rule_file"; then
            printf '%s\n' 'SUBSYSTEM=="misc", KERNEL=="uinput", TAG+="uaccess", OPTIONS+="static_node=uinput"' | sudo tee "$rule_file" >/dev/null
        fi
        sudo modprobe uinput
        sudo udevadm control --reload-rules
        sudo udevadm trigger --subsystem-match=misc --sysname-match=uinput
    fi
fi
/usr/bin/python3 -c 'import dbus,gi,evdev; from PySide6 import QtWidgets'
venv="$HOME/.local/share/opencode-stt/venv"
if [[ ! -x "$venv/bin/python" ]]; then python3 -m venv "$venv";fi
if ! "$venv/bin/python" -c 'import numpy,scipy,sounddevice,pynput,groq,httpx' >/dev/null 2>&1;then
    "$venv/bin/python" -m pip install -r "$repo_dir/requirements.txt"
fi
if [[ ! -x "$HOME/whisper.cpp/whisper-cli" || ! -x "$HOME/whisper.cpp/whisper-server" ]];then
    source_dir="$HOME/.local/share/local-stt/whisper-v1.9.5"
    mkdir -p "$(dirname -- "$source_dir")"
    if [[ ! -d "$source_dir/.git" ]];then git clone --depth 1 --branch v1.9.5 https://github.com/ggml-org/whisper.cpp.git "$source_dir";fi
    cmake -S "$source_dir" -B "$source_dir/build" -G Ninja -DCMAKE_BUILD_TYPE=Release -DGGML_CUDA=OFF -DGGML_HIP=OFF -DGGML_VULKAN=OFF
    cmake --build "$source_dir/build" --target whisper-cli whisper-server --parallel 2
    mkdir -p "$HOME/whisper.cpp"
    for binary in whisper-cli whisper-server;do
        if [[ ! -e "$HOME/whisper.cpp/$binary" ]];then ln -s "$source_dir/build/bin/$binary" "$HOME/whisper.cpp/$binary";fi
    done
fi
python3 "$repo_dir/scripts/download-model.py" base.en
if ((gpu));then
    command -v docker >/dev/null || { echo 'Install/configure Docker separately, then rerun --gpu. CPU setup files are preserved.' >&2;exit 1; }
    docker info >/dev/null
    docker pull ghcr.io/ggml-org/whisper.cpp@sha256:f723c938f4e0938c979cd82cef1f64c9a73cad3c3f4f8d6b1ab038bc9e981ff9
    python3 "$repo_dir/scripts/download-model.py" large-v3-turbo
fi
bash "$repo_dir/scripts/install.sh"
bash "$repo_dir/scripts/install-tray.sh"
systemctl --user enable --now local-stt.service
printf '%s\n' 'Local STT installed. Open Local STT from the application menu or microphone tray icon.' 'Continuous listening starts OFF. Configure any Groq key privately; no cloud account or spending is enabled by setup.'
