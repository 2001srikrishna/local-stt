# Optional Radeon GPU dictation

Hold **Ctrl+Alt+End**, speak, release all keys. CPU **Ctrl+Alt+Home** and cloud **Ctrl+Alt+Insert** remain available. The GPU mode is optional and can be disabled in tray Settings.

Uses the already-installed `ggml-large-v3-turbo.bin` through the official whisper.cpp Vulkan runtime. It is **on demand**, not a resident GPU server. The existing base.en CPU server remains the fast lightweight default.

## Runtime

Pinned official image:

```
ghcr.io/ggml-org/whisper.cpp@sha256:f723c938f4e0938c979cd82cef1f64c9a73cad3c3f4f8d6b1ab038bc9e981ff9
```

For another installation, explicitly download the runtime first:

```bash
docker pull ghcr.io/ggml-org/whisper.cpp@sha256:f723c938f4e0938c979cd82cef1f64c9a73cad3c3f4f8d6b1ab038bc9e981ff9
```

The application uses `--pull=never`: it never downloads an image during dictation. Docker and device permissions must already be configured. Image size was approximately930MB. No models were downloaded; the installed Turbo file is reused. Do not replace the pinned runtime casually without retesting.

Container restrictions: no network, read-only root, two read-only file mounts (selected model and current audio), unprivileged user, no added capabilities, no-new-privileges, 4GiB RAM/4.5GiB total RAM+swap, 8 CPU quota,128MB temporary filesystem,90-second internal timeout. A host-side watchdog also enforces90seconds, RAM>=1.5GiB and VRAM>=0.75GiB headroom. It removes its uniquely named container on exit/failure. Initial launch needs>=4GiB available RAM and>=4GiB free VRAM. These limits do not guarantee against instantaneous resource spikes.

The tested Radeon is `/dev/dri/renderD128` (RX9070XT). Only that render node is exposed; the runtime confirmed Vulkan0 execution. It does not quietly accept a CPU-only container result as GPU success. Local llama-server/llama-cli or ComfyUI on8188 blocks this mode; it falls back to CPU. No cloud call is made by GPU mode or its failure fallback.

Optional private config:

```
STT_GPU_ENABLED=1
STT_GPU_MODEL=/absolute/path/to/ggml-large-v3-turbo.bin
STT_GPU_RENDER_NODE=/dev/dri/renderD128
```

No GPU container/VRAM allocation remains idle after a completed run. An abrupt parent shutdown can leave the container briefly active until its internal timeout or normal inference completion; the internal timeout bounds this case. The same namespace must not be used by unrelated containers.

## Measurements —2026-11-02

RX9070XT, Ryzen7700X, installed Turbo model, official Vulkan image; beam5/best-of5; no competing local inference/video jobs. Inputs were the public11secJFK sample and a33sec repetition, not private microphone audio.

| Public clip | Repetitions | Container wall seconds | Peak total sampled VRAM | Minimum available host RAM |
|---|---:|---:|---:|---:|
|11sec JFK|2|1.2025–1.2026|2.874GiB|10.28GiB|
|33sec repeated JFK|2|1.3527–1.3528|2.874GiB|10.27GiB|

Container wall includes process startup, model load and inference, measured at~150ms polling granularity; it excludes initial availability checks and final cleanup. One full Engine.gpu routing call measured **1.276sec** including those costs. An initial direct Whisper run reported~0.88sec internally, of which~0.40sec was model loading. Neither measure is a guaranteed latency for live speech. Earlier TurboCPU11sec run was~7sec, using a different Whisper build. Base.enCPU is smaller and can still be faster than on-demand GPUTurbo.

The runtime selected `AMD Radeon RX9070XT (RADV GFX1201)` and `using Vulkan0 backend`. Its bundled driver printed a RADV nonconformance/testing warning. Public-clip tests completed without observed failures; wider driver/application stability is not established. The container leaves the host's working CPU/runtime installation untouched.

This demonstrates compatibility, speed and memory footprint, **not best-model accuracy**. See [MODEL_RESEARCH.md](MODEL_RESEARCH.md) for alternatives and limitations.

Source: [official whisper.cpp Vulkan runtime](https://github.com/ggml-org/whisper.cpp/blob/master/.devops/main-vulkan.Dockerfile).
