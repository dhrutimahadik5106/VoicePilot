# Project working rules

- Require Python 3.12; preserve the approved Python 3.12.10 interpreter.
- Preserve venv. Never delete or recreate it. Explicitly use
  venv\Scripts\python.exe for every Python or pip command, without activation.
- Work only in approved phases. Phase 1 foundation and Phase 2 audio input are
  approved; never implement Phase 3 or later without approval.
- Keep direct dependencies minimal. No installation, removal or upgrades without
  authorization. Do not use pip freeze as project dependency metadata.
- Never commit credentials or create a real .env as part of these phases.
- Microphone capture requires deliberate user action. No continuous listening,
  automatic recording or hardware access during imports/settings construction.
- Never log audio, secrets, embeddings, message contents, sensitive paths or file
  contents. Use safe error codes, not backend exception text.
- Keep recordings in memory by default. Cancellation discards captured audio.
  Persistence requires an explicit export request and permission.
- Future speaker enrollment requires separate explicit consent.
- Automated audio tests must use fakes/mocks and pytest temporary directories.
  Never access hardware, network, personal files, applications or system settings.
- Detect installed packages through metadata. Keep sounddevice imports lazy.
- Run complete pytest and audio tests, import/settings smoke tests, diff checks,
  and ignore checks. Keep manual hardware tests separate and user-executed.
- Do not claim hardware works until the user verifies it.
- No wake word, speaker verification, STT, LLM, LangGraph, computer control,
  browser automation, screen perception, memory, API or GUI in Phase 2.
- Enforce identity and permission checks before any future action execution.
