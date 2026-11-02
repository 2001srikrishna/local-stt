# local-stt

Small Linux push-to-talk dictation utility using **whisper.cpp locally** and optional **Groq Whisper**.

Hold **Home** for offline transcription, or **Insert** for Groq. Release the key, then **Ctrl+V** to paste. Native Wayland clipboard, desktop notifications, one shared listener, background transcription, and private timing diagnostics.

This is a desktop utility, not a replacement speech model. It reuses installed models and audio tools. Local mode does not send audio to a server. Insert explicitly selects Groq and uploads that recording; Groq usage can incur provider charges. Cloud failure falls back to local Whisper without a hidden retry loop.

## What changed

| Previously | Current |
|---|---|
| Each Codex/OpenCode terminal started another listener | One singleton, shared systemd user service |
| Transcription ran inside the keyboard callback | Bounded background queue; keyboard listener stays responsive |
| Only the last line of local output was delivered | Every transcript segment is preserved |
| 16 local CPU threads | 8 threads, based on a local comparison; configurable |
| X11 clipboard attempted before native Wayland | Wayland clipboard first; checked return codes |
| Groq SDK default timeout/retry behavior | 5-second connect / 25-second request timeout, no automatic retry, local fallback |
| Audio normalized without a gain limit | Silence/invalid-sample rejection, gain capped at 8× |
| No release-to-result diagnostics | Stage timings, capture overflow flag, sample levels; no transcript logged by default |

Native Wayland clipboard is a compatibility improvement. Both clipboard commands measured ~3 ms on the development desktop; the comparison does **not** establish a clipboard speedup. Likewise, the thread comparison is a small timing observation, not a universal tuning rule.

## Requirements

Tested on Fedora/KDE Wayland, Python 3.14, PipeWire and whisper.cpp 1.9.2 CPU. Python core supports 3.10+. Other distributions, X11 sessions and desktop hotkey behavior have not been validated.

- `whisper-cli` and a compatible `ggml-base.en.bin` model, normally under `~/whisper.cpp/`
- Python packages in `requirements.txt`
- PipeWire/PortAudio microphone access, a desktop X/XWayland connection for `pynput`
- `wl-copy` (Wayland) or `xclip` (X11), `notify-send` optional
- systemd user services for the shared launchers

`pynput` uses X/XWayland here. **It is not a universal global-hotkey solution for native Wayland applications.** Test Home/Insert in the applications you use. This project does not install a privileged input-injection daemon or automate pasting into another application.

## Install

If the dedicated STT virtual environment already exists, the installer reuses it. For a new setup:

```bash
python3 -m venv ~/.local/share/opencode-stt/venv
~/.local/share/opencode-stt/venv/bin/python -m pip install -r requirements.txt
```

Install whisper.cpp and its model from the [official project](https://github.com/ggml-org/whisper.cpp); this installer does not download or replace model files.

From this checkout:

```bash
bash scripts/install.sh
~/bin/stt start
```

This backs up an existing regular `~/stt.py`, links it to the checkout, and installs an on-demand `local-stt.service`. Keep the checkout in place. Stop older manually launched listeners before starting the service. Installation is intended to run inside a logged-in desktop session. It does not enable login autostart.

Optional existing CLI integrations:

```bash
install -m 755 scripts/codex-stt ~/bin/codex-stt
install -m 755 scripts/opencode-stt ~/bin/opencode-stt
```

These expect Codex at `~/.local/bin/codex` and OpenCode at `~/.opencode/bin/opencode`. They reuse the shared service. Closing one terminal does not terminate STT for another terminal.

## Configure

```bash
mkdir -p ~/.config/local-stt
cp config.example.env ~/.config/local-stt/stt.env
chmod 600 ~/.config/local-stt/stt.env
gvim ~/.config/local-stt/stt.env
~/bin/stt restart
```

Environment variables override file values. The config contains literal assignments, not executable shell code. Available settings: `STT_THREADS`, `STT_LANGUAGE`, `STT_MAX_SECONDS`, `STT_INPUT_DEVICE`, `STT_WHISPER_BIN`, `STT_WHISPER_MODEL`, `STT_MIN_AUDIO_PEAK`, `STT_LOG_TRANSCRIPTS`.

Optional `GROQ_API_KEY` may be set privately in the config/environment. For compatibility, an existing literal key in `~/.config/aider/credentials.env` is read without executing that file. Never put real keys in this checkout.

An unset input device resolves the PipeWire input on each recording, following the desktop's default microphone. To inspect available inputs:

```bash
~/bin/stt devices
```

With the Sony ULT FIELD 1 microphone, Bluetooth's hands-free profile is necessary for capture. AAC applies to music playback and does not increase microphone capture quality. Switching to a close headset/USB microphone is worth comparing for recognition quality; leave device selection unset when alternating microphones. No automatic profile switch is forced by this utility.

## Diagnostics

```bash
~/bin/stt status
~/bin/stt logs
~/.local/share/opencode-stt/venv/bin/python ~/stt.py --transcribe /path/to/test.wav
~/.local/share/opencode-stt/venv/bin/python -m unittest discover -s tests -v
```

Timing records: `~/.local/state/opencode-stt/timings.jsonl`.

- `capture_open_seconds`: time to open the microphone.
- `queue_seconds`: release through audio close/snapshot/worker scheduling.
- `transcription_seconds`: model initialization plus local inference, or cloud request plus any fallback.
- `delivery_seconds`: copying text and scheduling the desktop notification.
- `release_to_result_seconds`: release through clipboard delivery.

Audio is transient, removed after processing. By default, timings include levels/device names/character counts, not transcripts. `STT_LOG_TRANSCRIPTS=1` explicitly enables transcript logging in the journal. Provider error bodies and keys are not logged.

The worker accepts one queued recording while the previous transcription runs. Timings expose the wait. Recording is limited to 120 seconds by default; results stay in capture order. Clipboard contents can be replaced by subsequent completed recordings, so paste each result promptly. Stop the service before heavy benchmarks if you want dictation to avoid CPU contention.

## Measurements and limitations

See [BENCHMARKS.md](BENCHMARKS.md). The public test clip is not an accent/noise/real-microphone quality evaluation. No improvement in the user's real-speech word error rate is claimed. The existing larger model remains configurable but was ~7 seconds on CPU in the small comparison; it is not the default. No new models, Python dependencies or GPU runtimes were installed during this update.

The service has `MemoryMax=4G` and `MemorySwapMax=512M`. Increase those deliberately if a different model requires more. The current offline path is CPU-only; this avoids competing with GPU video jobs but can contend for CPU with other applications.

## Legacy snapshot / rollback

[`legacy/stt_before_2026-11-02.py`](legacy/stt_before_2026-11-02.py) is the exact script from before this update, with the original launcher snapshots alongside it. The snapshots include historical machine-specific paths, but no credentials/model files/recordings. They are retained for comparison, not recommended as current setup instructions.

To temporarily run the old behavior:

```bash
~/bin/stt stop
~/.local/share/opencode-stt/venv/bin/python legacy/stt_before_2026-11-02.py
# Ctrl+C when finished, then:
~/bin/stt start
```

## Sources

- [whisper.cpp](https://github.com/ggml-org/whisper.cpp)
- [Groq speech-to-text API](https://console.groq.com/docs/speech-to-text)
- [pynput platform limitations](https://pynput.readthedocs.io/en/latest/limitations.html)


## Resident engine (latency follow-up)

The shared listener now keeps the installed local model loaded through `whisper-server`, bound only to `127.0.0.1:18765`. `local-stt-engine.service` starts with the listener and stops with it. This avoids repeated model loading and process startup while keeping beam5 decoding. It uses about 300 MB additional RAM on the tested base.en model. The engine has its own 4 GiB /512 MiB swap limit. A standalone CLI fallback remains available if its HTTP endpoint cannot be used.

`STT_RESIDENT=1` enables this path in the service; direct `--transcribe` calls still default to standalone unless that variable is set. `STT_WHISPER_SERVER` can override the binary and `STT_SERVER_PORT` its loopback port (change in the config and restart both through `~/bin/stt restart`). The HTTP client ignores proxy environment variables, keeping local audio on loopback. No public interface or sharing tunnel is started. Other local users/processes able to reach loopback can access this endpoint; it has no HTTP authentication.

After pulling this update, rerun `bash scripts/install.sh` then `~/bin/stt restart` to install the companion engine unit. `~/bin/stt stop` also stops the resident engine to free its RAM. Model, beam size and transcription quality settings stay the same. This trims startup overhead; it does not make the recognition compute cost disappear, especially on longer recordings.
