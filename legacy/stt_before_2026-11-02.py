#!/usr/bin/env python3
# ~/stt.py - Unified STT: Insert=Groq, Home=Local
# Features: clipboard fallback, desktop notifications, better error handling
import os, tempfile, threading, subprocess, sys, shutil, math

# Use the dedicated STT environment when the script is started with system
# python3, so `python3 ~/stt.py` works as well as the OpenCode/Codex launchers.
STT_VENV_PYTHON = os.path.expanduser("~/.local/share/opencode-stt/venv/bin/python")
if sys.prefix == sys.base_prefix and os.path.isfile(STT_VENV_PYTHON):
    if os.path.realpath(sys.executable) != os.path.realpath(STT_VENV_PYTHON):
        os.execv(STT_VENV_PYTHON, [STT_VENV_PYTHON, os.path.abspath(__file__), *sys.argv[1:]])

import sounddevice as sd
import numpy as np
from scipy.io.wavfile import write
from scipy.signal import resample_poly
from pynput import keyboard

# ===== CONFIG =====
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WHISPER_BIN = os.getenv("STT_WHISPER_BIN", os.path.expanduser("~/whisper.cpp/whisper-cli"))
WHISPER_MODEL = os.getenv("STT_WHISPER_MODEL", os.path.expanduser("~/whisper.cpp/models/ggml-base.en.bin"))
SAMPLE_RATE = 16000
MIN_AUDIO_PEAK = float(os.getenv("STT_MIN_AUDIO_PEAK", "0.000001"))
# Prefer PipeWire device to avoid ALSA errors
INPUT_DEVICE = os.getenv("STT_INPUT_DEVICE", None)  # Set to device index or name

KEY_GROQ = keyboard.Key.insert      # Hold for Groq
KEY_LOCAL = keyboard.Key.home       # Hold for Local
# ===================

recording = []
stream = None
recording_event = threading.Event()
current_mode = None
recording_sample_rate = SAMPLE_RATE
client = None
has_xdotool = shutil.which("xdotool") is not None
has_notify = shutil.which("notify-send") is not None
has_xclip = shutil.which("xclip") is not None or shutil.which("wl-copy") is not None

if GROQ_API_KEY:
    from groq import Groq
    client = Groq(api_key=GROQ_API_KEY)

def notify(title, msg, urgency="normal"):
    if has_notify:
        subprocess.run(["notify-send", "-u", urgency, title, msg], capture_output=True)

def copy_to_clipboard(text):
    """Try xclip (X11) then wl-copy (Wayland)"""
    for cmd in [["xclip", "-selection", "clipboard"], ["wl-copy"]]:
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text.encode(), check=True, timeout=2)
                return True
            except: pass
    return False

def paste_text(text):
    """Try to type text, otherwise copy it to the Wayland clipboard."""
    if has_xdotool:
        try:
            escaped = text.replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
            subprocess.run(["xdotool", "type", "--clearmodifiers", escaped], timeout=5)
            return "typed"
        except:
            pass
    if copy_to_clipboard(text):
        return "clipboard"
    return None

def deliver_transcript(text, source):
    delivery = paste_text(text)
    if delivery == "typed":
        notify(f"STT ({source})", "Inserted into the focused window", "low")
    elif delivery == "clipboard":
        notify(f"STT ({source})", "Copied to clipboard — focus your prompt and press Ctrl+V", "normal")
    else:
        notify("STT", "Could not type or copy the transcript", "critical")

def audio_cb(indata, frames, time_info, status):
    if recording_event.is_set():
        recording.append(indata.copy())

def resolve_input_device():
    """Choose a usable capture device and a rate it actually supports."""
    devices = sd.query_devices()
    requested = INPUT_DEVICE

    if requested is not None and str(requested).strip():
        value = str(requested).strip()
        if value.isdigit():
            index = int(value)
            if index >= len(devices):
                raise RuntimeError(f"STT_INPUT_DEVICE index {index} does not exist")
            index = index
        else:
            matches = [i for i, d in enumerate(devices) if d["name"] == value]
            if not matches:
                matches = [i for i, d in enumerate(devices) if value.lower() in d["name"].lower()]
            if not matches:
                raise RuntimeError(f"No audio device matches STT_INPUT_DEVICE={value!r}")
            index = matches[0]
        info = devices[index]
        if info["max_input_channels"] < 1:
            raise RuntimeError(f"Audio device {info['name']!r} has no input channels")
        return index, max(1, round(info["default_samplerate"])), info["name"]

    default_input = sd.default.device[0]
    if default_input is not None and int(default_input) >= 0:
        info = devices[int(default_input)]
        if info["max_input_channels"] > 0:
            return int(default_input), max(1, round(info["default_samplerate"])), info["name"]

    candidates = [
        (i, d) for i, d in enumerate(devices)
        if d["max_input_channels"] > 0 and "monitor" not in d["name"].lower()
    ]
    if not candidates:
        raise RuntimeError("No microphone/audio input device is available to this process")

    preferred_words = ("pipewire", "pulse", "default", "microphone", "mic", "headset", "usb")
    candidates.sort(key=lambda item: (
        not any(word in item[1]["name"].lower() for word in preferred_words),
        item[0],
    ))
    index, info = candidates[0]
    return index, max(1, round(info["default_samplerate"])), info["name"]

def start_rec(mode_):
    global recording, stream, current_mode, recording_sample_rate
    device, device_rate, device_name = resolve_input_device()
    recording = []
    current_mode = mode_
    recording_sample_rate = device_rate
    recording_event.set()
    try:
        stream = sd.InputStream(
            samplerate=recording_sample_rate,
            channels=1,
            callback=audio_cb,
            device=device,
            dtype="float32",
        )
        stream.start()
    except Exception:
        recording_event.clear()
        if stream:
            try:
                stream.close()
            except Exception:
                pass
            stream = None
        raise
    label = "Groq ☁️" if mode_ == "groq" else "Local 💻"
    notify("STT", f"Recording ({label})", "low")
    print(f"🎙️  Recording ({label}) from {device_name} at {recording_sample_rate} Hz...")

def stop_rec():
    global stream
    recording_event.clear()
    active_stream = stream
    stream = None
    if active_stream:
        try:
            active_stream.stop()
        finally:
            active_stream.close()
    notify("STT", "Transcribing...", "low")
    print("⏳ Transcribing...")
    if not recording: return
    audio = np.concatenate(recording, axis=0).astype(np.float32, copy=False)
    if len(audio) < recording_sample_rate * 0.5:
        notify("STT", "Recording too short", "normal")
        print("⚠️  Recording too short")
        return
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(np.square(audio))))
    print(f"Audio level: peak={peak:.7f}, RMS={rms:.7f}")
    if peak < MIN_AUDIO_PEAK:
        notify("STT", "Audio too quiet", "normal")
        print(f"⚠️  Audio too quiet (peak {peak:.7f}; minimum {MIN_AUDIO_PEAK:.7f})")
        return
    audio = audio / np.max(np.abs(audio)) * 0.95
    if recording_sample_rate != SAMPLE_RATE:
        divisor = math.gcd(recording_sample_rate, SAMPLE_RATE)
        audio = resample_poly(
            audio,
            SAMPLE_RATE // divisor,
            recording_sample_rate // divisor,
            axis=0,
        )
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        write(f.name, SAMPLE_RATE, (audio * 32767).astype(np.int16))
        path = f.name
    try:
        if current_mode == "groq":
            transcribe_groq(path)
        else:
            transcribe_local(path)
    except Exception as e:
        notify("STT Error", str(e), "critical")
        print(f"Error: {e}")
    finally:
        try: os.unlink(path)
        except: pass

def transcribe_groq(path):
    with open(path, "rb") as f:
        text = client.audio.transcriptions.create(
            file=(path, f.read()),
            model="whisper-large-v3-turbo",
            language="en",
            response_format="text"
        ).strip()
    if text and text != "." and len(text) > 1:
        print(f"📝 {text}")
        deliver_transcript(text, "Groq")
    else:
        notify("STT", "Empty or invalid transcript", "normal")

def transcribe_local(path):
    result = subprocess.run(
        [WHISPER_BIN, "-m", WHISPER_MODEL, "-f", path, "-t", "16", "-ac", "0", "--no-timestamps"],
        capture_output=True, text=True, timeout=90
    )
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        raise RuntimeError(detail[-1] if detail else "whisper-cli failed")
    text = result.stdout.strip()
    lines = [l for l in text.split('\n') if l and not l.startswith('[')]
    text = lines[-1] if lines else ""
    if text and text != "." and len(text) > 1:
        print(f"📝 {text}")
        deliver_transcript(text, "Local")
    else:
        notify("STT", "Empty or invalid transcript", "normal")

def on_press(k):
    try:
        if k == KEY_GROQ and not recording_event.is_set():
            if not GROQ_API_KEY:
                notify("STT", "Groq API key not set", "critical")
                return
            start_rec("groq")
        elif k == KEY_LOCAL and not recording_event.is_set():
            if not os.path.isfile(WHISPER_BIN) or not os.access(WHISPER_BIN, os.X_OK):
                notify("STT", "whisper-cli is unavailable", "critical")
                return
            if not os.path.isfile(WHISPER_MODEL):
                notify("STT", "Whisper model is unavailable", "critical")
                return
            start_rec("local")
    except Exception as e:
        recording_event.clear()
        notify("STT Error", str(e), "critical")
        print(f"Recording error: {e}", file=sys.stderr, flush=True)

def on_release(k):
    try:
        released_mode = "groq" if k == KEY_GROQ else "local" if k == KEY_LOCAL else None
        if released_mode == current_mode and recording_event.is_set():
            stop_rec()
    except Exception as e:
        recording_event.clear()
        notify("STT Error", str(e), "critical")
        print(f"Stop/transcription error: {e}", file=sys.stderr, flush=True)

# Startup
print("=" * 55)
print("UNIFIED STT - Ready")
print("=" * 55)
print(f"INSERT  → Groq Whisper (cloud, ~1s)")
print(f"HOME    → Local whisper.cpp base.en (offline, ~10-15x realtime)")
print("-" * 55)
print(f"xdotool:  {'✅' if has_xdotool else '❌'}  clipboard: {'✅' if has_xclip else '❌'}  notify: {'✅' if has_notify else '❌'}")
if not GROQ_API_KEY: print("⚠️  GROQ_API_KEY not set")
if not os.path.isfile(WHISPER_BIN): print(f"⚠️  whisper-cli missing: {WHISPER_BIN}")
if not os.path.isfile(WHISPER_MODEL): print(f"⚠️  Whisper model missing: {WHISPER_MODEL} (download: huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin)")
print("=" * 55)

notify("STT Ready", "INSERT=Groq  HOME=Local (base.en)", "low")

with keyboard.Listener(on_press=on_press, on_release=on_release) as l:
    l.join()
