# Local and cloud model research —2026-11-02

There is **no established best model for this user's speech yet**. The local performance tests used public speech, not a reference-labeled set of the user's microphone recordings. Published benchmark results, throughput figures and streaming first-token latency do not directly predict release-to-final-paste latency or Indian-English/technical-vocabulary accuracy.

## Local shortlist

| Candidate | Primary-source evidence | Our machine |
|---|---|---|
|Whisper base.en CPU|Existing small English model|Fast, resident and tested; remains CPU default|
|Whisper LargeV3 Turbo Vulkan|OpenAI's model card describes pruning decoder32layers→4 for speed, with some quality degradation versus full LargeV3|Installed weights reused; RX9070XT execution verified, on-demand container~1.2–1.35sec for public11/33sec clips|
|IBM Granite Speech5.0 470M TurboCTC|IBM's Oct21 multilingual update describes greedy non-autoregressive decoding, native punctuation/capitalization and reported English WER5.51% across its cited benchmark setup|Not installed/tested; compatibility, runtime cost and user-speech accuracy remain unknown|
|NVIDIA ParakeetTDT0.6Bv3|NVIDIA publishes a600M multilingual model and performance evaluations; its documented GPU optimization/test hardware is NVIDIA-oriented|Not installed/tested on this Radeon; do not infer impossibility or success from NVIDIA documentation alone|

Sources:
- [OpenAI Whisper Turbo model card](https://huggingface.co/openai/whisper-large-v3-turbo)
- [IBM Granite5.0 TurboCTC model card](https://huggingface.co/ibm-granite/granite-speech-5.0-470m-turboctc)
- [NVIDIA ParakeetTDTv3 model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)
- [Hugging Face Open ASR benchmark](https://huggingface.co/spaces/hf-audio/open_asr_leaderboard)

Granite's published WER is not comparable to the user's unlabeled dictation or to numbers from unrelated provider benchmarks. The published Parakeet/Granite options are credible comparison candidates, not a reason to install additional inference stacks before the GUI works. No extra model download took place during this task.

## Cloud shortlist

| Provider/model family | Why consider it | Status here |
|---|---|---|
|Groq WhisperLargeV3Turbo|Existing integrated provider; our observed recording had~0.54sec release-to-clipboard|Working incumbent; retained as sole wired cloud backend|
|ElevenLabs Scribev2 / Scribev2Realtime|Official docs offer batch and realtime transcription, keyterm support; realtime docs advertise~150ms latency|Researched only; advertised streaming latency is not end-to-end final dictation latency|
|Deepgram Nova3 / Flux|Official pricing page recommends Nova3 for general transcription, Flux for realtime voice agents|Researched only; agent turn detection is not automatically the best fit for push-to-talk dictation|
|Soniox STTv5Realtime|Official model docs identify current stt-rt-v5 for live audio|Researched only; no local integration or latency/accuracy measurement|
|AssemblyAI Universal3.6ProStreaming|Official roadmap identifies the current streaming default and code-switching/background-voice handling features|Researched only; no API call or local comparison|

Sources:
- [Groq speech-to-text](https://console.groq.com/docs/speech-to-text)
- [ElevenLabs transcription capabilities](https://elevenlabs.io/docs/overview/capabilities/speech-to-text)
- [Deepgram official pricing/product guidance](https://deepgram.com/pricing)
- [Soniox model documentation](https://docs.soniox.com/stt/models)
- [AssemblyAI official roadmap](https://www.assemblyai.com/roadmap)

No new provider account, credential, permission, subscription or paid test was used. The GUI does **not** pretend the research-only providers are implemented. New cloud backends need user-authorized account/key access and explicit authorization for any paid tests. Existing user-triggered Groq dictation remains unchanged.

## What would establish a useful winner

A consented set of20–30short recordings with exact reference text, covering ordinary dictation, IndianEnglish, product/library names, numbers, background noise and the actual Sony/headset microphones. Keep all candidates on the same recordings; measure normalized word error rate, named-entity/number mistakes, release-to-final-result time, RAM/VRAM, and hallucinations on silence. Use a small held-out set after choosing settings. Raw recordings/transcripts stay private and out of this public repository. No need to buy new hardware or configure more providers before that concrete comparison.
