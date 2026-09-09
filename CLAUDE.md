# Project working rules

- Preserve Python 3.12.10 and the existing venv. Explicitly use
  venv\Scripts\python.exe for every Python or pip command; do not rely on activation.
- Never install, remove or upgrade packages without authorization.
- Phases 1-3 are approved: foundation, explicit audio input and local STT.
  Never implement Phase 4 or later without separate approval.
- No wake word, speaker verification, LLM reasoning, LangGraph, computer control,
  command execution, browser/screen automation, history database, API or frontend.
- Treat recognized speech as text only. It must never execute commands.
- Microphone capture requires deliberate action. No continuous listening,
  startup recording or hardware/model access during imports/settings loading.
- Keep audio/transcripts in memory by default. STT must not persist recordings.
  Cancellation discards results; future speaker enrollment needs separate consent.
- Never log raw audio, transcripts, embeddings, credentials, sensitive paths or
  internal exception text. Use safe codes and suppress backend transcript logging.
- Recognition runs locally. Only an explicit real transcription may download model
  assets. Document first-use downloads and the cached-files-only setting.
- Do not automatically perform manual microphone, download or transcription tests.
- Automated STT tests must use fakes/mocks; no real model load, download, network,
  hardware, applications, personal-file access or system-setting changes.
- Generate WAV fixtures only in pytest temporary directories.
- Preserve ignored recordings/models and never create a real .env or credentials.
- Declare only direct dependencies; do not use pip freeze for project metadata.
- Run complete and phase-specific pytest, import/settings smoke tests, diff and
  ignore checks. Stop on failed baseline or repository/authentication safeguards.
- Phase 2 hardware and initial Phase 3 transcription are user-tested; accuracy
  mistakes and a slow first run were reported. Refinement hardware tests are pending.
  Never fabricate accuracy, WER, benchmarks or hardware/model verification.

- Phase 3 refinements permit optional fixed duration, Enter-to-stop capture,
  optional silence stop, a configurable 120s safety maximum, and explicit sessions.
- Never remove the finite recording cap or save audio automatically.
- Keep small/cpu/int8 as the default for this 16 GB laptop; no medium/large or GPU
  migration is authorized.
- Vocabulary is a decoding hint, not permission to rewrite arbitrary speech.
  Preserve raw and normalized transcript forms; normalization only joins/strips
  segment-boundary whitespace and never substitutes recognized words.
- Separate model-load/download time from inference. Label cold/warm only by
  whether the engine constructed/reused its model. Do not claim measured speedups
  from fake-clock tests.
- Reuse the model within a session; request fresh capture consent for each turn.
- Document silence/VAD cutoff risks, multilingual limitations and uncertain
  accuracy. Do not automatically run real microphone/model/performance tests.
