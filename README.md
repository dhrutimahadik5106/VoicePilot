# VoicePilot

VoicePilot is a planned voice-driven assistant with explicit authentication,
risk checks, verification and recovery. Only Phase 1 foundation is implemented:
validated settings, shared exceptions, console logging and isolated tests.
This is not production-ready and cannot listen, reason or control a computer.

## Existing environment

Use the preserved venv and Python 3.12.10 from the project root in PowerShell.
Activation is unnecessary. Do not recreate the environment or install, remove,
or upgrade packages for this phase.

```powershell
.\venv\Scripts\python.exe --version
.\venv\Scripts\python.exe -m pytest
.\venv\Scripts\python.exe -c "import app.core.config, app.core.errors, app.core.logging"
.\venv\Scripts\python.exe -c "from app.core.config import get_settings; s = get_settings(); assert s.app_name == 'VoicePilot'"
```

Runtime direct dependencies are pydantic and pydantic-settings; pytest is the
test dependency. They already exist in the venv. The metadata is not a lockfile.

## Configuration and logging

See .env.example for VOICEPILOT_ environment variables and safe defaults.
No real .env is created or automatically read. Settings do not create directories
or contact services. get_settings() caches one instance; use
get_settings.cache_clear() when intentionally reloading configuration.
Limits: plan steps 1?100, retries 0?10, timeout greater than 0 and at most 3600
seconds. Integration settings are placeholders and do not enable functionality.

configure_logging() configures the dedicated voicepilot logger on stderr.
Only fixed event codes foundation_ready, configuration_loaded and shutdown are
emitted; other messages are redacted. Arguments, exception text and stack traces
are never formatted. Do not add handlers that bypass this policy or log secrets,
raw audio, speaker embeddings, message contents or sensitive file contents.

## Limitations

All pipeline components in ARCHITECTURE.md are planned. No audio, STT,
authentication, wake word, LLM calls, orchestration, computer control, browser,
screen perception, memory, API or UI exists. Authentication defaults to disabled;
there is no executable action path. Tests inspect optional package metadata
without importing or exercising those packages. Environment tests intentionally
require the approved Python 3.12.10 venv.
