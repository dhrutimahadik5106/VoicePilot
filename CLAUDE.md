# Project working rules

- Require Python 3.12; preserve the approved Python 3.12.10 interpreter.
- Preserve venv. Never delete or recreate it. Use venv\Scripts\python.exe
  explicitly for every Python or pip command; do not rely on activation.
- Work in approved phases. Never implement beyond an approved phase.
- Keep direct dependencies minimal. Do not install, remove or upgrade packages
  without authorization. Do not use pip freeze to define project dependencies.
- Phase 1 permits only configuration, exceptions, logging, tests and documentation.
- Never commit credentials or create a real .env as part of foundation work.
- Never log secrets, raw audio, embeddings, message contents or sensitive files.
  Use the foundation logger's fixed event codes; do not bypass its formatter.
- No hardware, network, personal-file or system-setting access in tests.
- Validate changes with the venv's pytest and import/settings smoke tests.
- Inspect packages through distribution metadata; never import future integrations
  merely to detect installation.
- Require explicit permission checks before future actions; feature flags do not
  establish user identity or authorize execution.
- Keep documentation honest about implemented and planned features.
