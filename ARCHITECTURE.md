# Planned architecture

Status: Phase 1 foundation only. The entire pipeline below is planned,
not implemented.

Perceive ? Authenticate ? Transcribe ? Understand ? Retrieve Context ? Plan ?
Risk Check ? Execute ? Observe ? Verify ? Recover ? Respond ? Update Memory

Future responsibilities:
- Perceive: obtain approved input; Authenticate: establish authorized identity.
- Transcribe: convert speech; Understand: interpret intent.
- Retrieve Context: obtain permitted context; Plan: propose bounded actions.
- Risk Check: enforce permissions; Execute: run approved tools.
- Observe: inspect outcomes; Verify: check success; Recover: handle failures.
- Respond: communicate results; Update Memory: retain only approved information.

Current modules: app/core/config.py loads bounded configuration;
app/core/errors.py defines shared exception types; app/core/logging.py emits
allowlisted operational events to the console. These modules start no services
and access no devices. Tests live in tests/. No future-module directories exist.

Future integrations require separate phase approval, dependency review and
tests. Identity and risk checks must be enforced before future action execution.
Configuration flags alone are not authorization.
