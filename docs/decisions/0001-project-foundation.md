# 0001: Project foundation

Status: accepted for Phase 1.

Preserve Python 3.12.10 and the existing venv without dependency changes.
Use pydantic-settings for typed environment configuration, bounded numeric
settings and a cached accessor. Do not automatically load .env, create
directories or initiate integrations. Use standard-library console logging with
an allowlist of fixed operational events and shared application exceptions.
Initialize Git on main and exclude credentials, generated files and sensitive
runtime artifacts while retaining .env.example.

Heavy dependencies and speaker-verification implementation are deferred until
their requirements, security boundaries and Windows compatibility can be
evaluated in an approved phase. Existing installed packages do not imply
approval to import or use them.

Resemblyzer and webrtcvad will not be used currently because of maintenance
and Windows build concerns. This records the project's selection constraint,
not a new audit of their current upstream status. A maintained ONNX-compatible
alternative will be evaluated in a later phase; no alternative is selected yet.

Tests cover settings, limits, exceptions, imports, safe logging and package
metadata detection. No audio, STT, speaker verification, wake word, LLM calls,
LangGraph, computer control, screen perception, browser automation, memory,
API or UI is implemented. The project is not production-ready.
