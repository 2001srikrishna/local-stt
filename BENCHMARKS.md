# Initial measurements — 2026-11-02

Ryzen 7 7700X, Fedora, installed whisper.cpp 1.9.2 CPU backend. Input: upstream whisper.cpp [samples/jfk.wav](https://github.com/ggml-org/whisper.cpp/blob/master/samples/jfk.wav), 11 seconds, 16 kHz. No microphone audio was published.

A single measured run per configuration, sequential, including process/model startup. These measurements are exploratory; no confidence interval or generalized accuracy ranking is implied.

| Model | Threads | Beam / best-of | Wall seconds |
|---|---:|---:|---:|
| base.en (previous default) | 16 | 5 / 5 | 0.613 |
| base.en (new default) | 8 | 5 / 5 | 0.533 |
| base.en | 4 | 5 / 5 | 0.815 |
| base.en | 8 | 1 / 1 | 0.442 |
| large-v3-turbo | 8 | 1 / 1 | 7.020 |
| large-v3-turbo | 8 | 5 / 5 | 6.930 |

All produced the expected words on this clip, with punctuation differences. Beam5 retained for dictation; saving ~0.09 sec with greedy decoding was not enough evidence to sacrifice decoding alternatives on difficult speech. The larger model was not made the default because the observed CPU delay was much worse.

## New full pipeline

Using the public clip through the actual background worker and native clipboard:

- Local transcription including process/model startup: **0.5209 sec**
- Clipboard delivery plus asynchronous notification scheduling: **0.0037 sec**
- Total through worker/audio preparation/delivery: **0.5262 sec**
- Microphone open/close probe using the desktop's PipeWire source: **0.0061 sec** to open; samples discarded, no voice transcription performed.
- Clipboard commands tested independently: xclip0.0033sec, wl-copy0.0035sec. Previous text clipboard content restored after the integration test. No clipboard speedup claim.

The previous script had two simultaneously running listeners when inspected. No claim of a numerical latency reduction from deduplication is made because a controlled two-listener latency benchmark was not performed. The multi-segment truncation and synchronous keyboard callbacks were confirmed directly in the source and covered by regression tests.

## Validation

Eleven offline tests cover complete multi-segment text, literal clipboard text, Wayland preference and error fallback, silence/NaN rejection, resampling/gain cap, singleton locking, offline-only Home, cloud-to-local error fallback, a responsive recording callback during blocked background transcription, microphone selection changes, and literal configuration loading.

Live service starts and duplicate startup exits cleanly. Real local engine output, clipboard delivery and microphone opening tested. No cloud request was made during testing: production SDK configuration was inspected and failure fallback tested with a simulated error. No real-voice WER claim. Existing Home/Insert desktop hotkeys still require user verification in their active application; global Wayland coverage is limited by pynput/XWayland.

## Resident-engine follow-up

Tested the installed whisper-server with the same base.en model, 8 threads and beam5, bound to loopback. An initial HTTP-only sequence measured ~0.45sec on the11sec clip and~1.007sec on a33sec file made by repeating the public clip3times. Beam1 was faster (~0.38sec/~0.787sec), but on the33sec clip it changed **“ask not” to “asked not”** repeatedly. It was rejected as the default because quality was already a user concern.

The production path now reuses a persistent HTTP client and a resident CPU model, keeping beam5. Three alternating standalone/resident pairs through the actual Engine class measured median **0.6432sec standalone vs0.5815sec resident** (~62ms/10% saved) on the11sec clip. All normalized word sequences matched; punctuation differed in one output variant. An earlier paired check saw a larger timing difference, so do not treat a single percentage as stable: CPU load/clocks affect these very short runs. The improvement removes startup overhead; it does not establish a major latency reduction for long dictation.

Resident process MemoryCurrent was~301MB. Thirteen regression tests now pass, adding resident response handling and standalone fallback on connection failure. No cloud request was made for this follow-up. The private user's previous live36.2sec local recording took1.03sec release-to-clipboard before this follow-up; the corresponding audio was not retained, so no same-recording before/after comparison is possible.
