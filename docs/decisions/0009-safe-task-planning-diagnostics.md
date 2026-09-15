# 0009: Safe task planning and observable diagnostics

Phase 5A implements deterministic proposals and simulation only. No executable
adapter exists. Every plan, step, result and capability has execution disabled.
Nothing opens an application, searches the network, controls input, sends messages,
changes settings, accesses user documents or runs generated code. Existing phases
and the venv are preserved; no dependencies were installed or changed.

## Planner and risk boundaries

`app/planning/models.py` defines bounded frozen contracts and safe errors. The
planner accepts an existing Resolution object, revalidates it and checks it against
the unchanged resolver before selecting a fixed template. Intent, entities,
canonical text, resolution status/reasons and candidate match types remain distinct
from raw STT and STT-normalized text. A source resolution is private in memory;
public plan serialization excludes raw source and objective text.

Supported templates: application launch plus simulated observation; Spotify launch,
media search, playback and observation; playback controls; volume controls; help.
Arguments are closed registry identifiers, not command lines, executable code, paths
or URLs. Unknown/missing/fuzzy/ambiguous/observed-ASR entities remain deferred. Negation,
unsupported compounds and unsupported intents abstain. Only the existing resolver's
explicit Spotify open-and-play workflow is decomposed. Search/research and cafe
comparison remain unsupported: the current resolver has no validated research intent.
Dilbar is not in the current media registry; it is not invented as a resolved entity.

Validation checks action/capability/target/argument combinations, exact supported
sequences, observations, consistent media IDs, unique ordered step IDs, earlier-step
dependencies, cycles, dependency depth, step counts and retry/timeout budgets. Stable
IDs need not equal sequence numbers: dependencies are checked using actual IDs.
Only the supported linear templates are accepted in this phase, not arbitrary DAGs.
The total budget includes every permitted retry. No numeric timeout or retry setting
can enable execution. Plan IDs/timestamps differ between runs; template steps are
deterministic for equivalent validated input/configuration.

The versioned closed capability registry contains data only, never callables.
Application launch, media search/play/control, volume and response presentation are
simulated. Browser search/read and research comparison are unavailable. Messaging is
high-risk and unavailable. Payment, destructive file changes, system configuration,
credential exposure and arbitrary code execution are prohibited. Unknown capabilities
fail closed. Volume adjustment is its own bounded simulated category, not a generic
system-settings capability.

Risk classes: informational, low, moderate, high, prohibited. The registry records
proposed external effects, reversibility and information/application/media/
communication/financial/file/system/credential/code impacts. Action argument validation
limits the targets and possible effects. Input risk handles unresolved ambiguity and
conservative dangerous/sensitive-language patterns; credentials are withheld from
trace text. Authentication is a separate gate and never lowers risk or substitutes
for confirmation. Registry risk and confirmation requirements are rechecked when a
plan reaches the simulator; risk errors block the plan. These rules are engineering
heuristics, not a complete multilingual security classifier.

## Confirmation and simulation

Confirmation requests bind to plan UUID, planner version, the exact structured steps,
objective, arguments, dependencies and all serialized plan fields through an in-memory
digest. Requests carry the proposed steps, risk reason, expiry and explicit simulation
summary: no real side effect occurs. Accepted receipts are opaque, expiring and
single-use. Changed plans, replayed/forged receipts and plain booleans do not confirm
anything. Declined, cancelled and expired states cannot later approve a request.
Prohibited/deferred plans cannot obtain confirmation. Confirmation does not repair
unresolved ASR entities; the user must supply a clear command. It never authorizes
execution. This phase supplies the confirmation API; the diagnostic CLI does not
silently answer or automatically approve requests.

The simulator implements replaceable simulation, observation, verification and
recovery contracts. Observations are explicitly simulated matches/mismatches, never
claims about a real application. Trusted test-only failure injection exercises bounded
attempts, cancellation, retry exhaustion and aborting dependent steps. No generated
text selects imports, handlers or callables. There is no runtime failure-injection CLI
or execution flag. Injected Python dependencies are trusted application/test code;
these interfaces are not a sandbox for malicious Python running in the same process.

## Separate diagnostic and authenticated flows

`unauthenticated-text`: explicit text -> resolver -> planner -> risk -> simulator.
`unauthenticated-voice`: deliberate capture -> local STT safety service -> resolver
-> planner -> risk -> simulator. Both clearly say unauthenticated diagnostic/simulation
and are unsuitable for production authorization. They cannot reach an execution
adapter. The voice path uses cached models only; it cannot download missing models.
The raw and STT-normalized forms are retained separately from resolver normalization,
canonical interpretation and proposed objective. Rejected STT text and private decoder
segments never enter a trace. A text command longer than the resolver's 500-character
limit is blocked, rather than truncated into a different request.

`authenticated`: deliberate capture -> established Phase 4B protected-policy and
verification boundary -> authorization check -> STT only on a fresh authorized result.
The selected protected profile and optional reviewed policy are loaded only in this
explicit flow. Missing/pending policy blocks before inference/STT. No dummy similarity
calculation imitates verification. A valid policy delegates to Phase 4B
VerificationService; the global enabled flag, validated policy and matching fresh
profile/audio IDs are still required. The identical buffer reaches STT only after all
checks pass. Similarity, embeddings, profiles and biometric provenance are discarded
from trace construction. Calibration remains pending and is not approved by Phase 5A.

One-shot and bounded sessions are supported. Every voice turn requires Enter before
capture; recording controls and finite caps remain those of the existing audio layer.
Cancellation discards unsaved trace/text/audio references. Already explicitly saved
artifacts are not silently removed. Python cannot guarantee secure memory erasure.

## Explicit private artifacts

Nothing is saved by default. --show-transcript authorizes local display only.
--save-audio and --save-trace enable only the current invocation and request separate
per-operation confirmation. Transcript-containing saves explicitly say they include
text/entities. Setting an environment saving flag alone never starts retention.

The default root is LOCALAPPDATA/VoicePilot/diagnostics. A custom root must be absolute,
outside the repository and known OneDrive paths, with no symlink/junction ancestors.
No directory is created on import/settings load. Known sync-root rejection cannot
detect every third-party synchronization or backup application.

Artifacts use UUID filenames ending in .vp-audio.wav or .vp-trace.json. Trace/audio
sizes and audio duration are bounded. Same-directory temporary writes are flushed
before atomic no-overwrite hard-link publication. Filesystems without that primitive
fail closed. Cleanup is best effort if the OS refuses access. No overwrite option is
provided. Saved items are labelled explicitly approved diagnostics, not automatic
history. Listing reveals UUIDs only; inspection selects one UUID and hides text unless
--show-transcript is supplied; deletion requires confirmation and deletes only that
trace. Associated WAV files are separate and may be removed manually by the user.

Approved fields are trace/session UUIDs, timestamps with UTC/local offsets, capture
format/duration, stage statuses/timings, resolver intent/reason/match-type evidence,
closed structured plans, risk/confirmation state and simulated results. Explicitly
approved text adds raw/STT-normalized/resolver-normalized forms, entities, canonical
command and proposed objective. Metadata-only plans still reveal intentions and
registry entity IDs; they are not anonymous. All trace writes require consent.

No embeddings, similarity values, enrollment digests, protected/decrypted profiles,
credentials, decoder diagnostic segments or personal file contents are serialized.
Known credential patterns reject text display/persistence and suppress the associated
diagnostic audio save. Language metadata is restricted to short language codes. Users must not dictate
credentials: pattern matching cannot identify every secret. No personal-file reader
exists. Approved diagnostic text/WAVs are sensitive plaintext, not DPAPI profiles;
protect the account/directory and choose a suitable retention period. Git ignore is
not encryption or access control. No artifact is uploaded or committed.

## Exact manual commands (user only)

Use the existing venv from the repository. These syntax paths are tested with fake
capture/STT/verifiers and temporary artifacts; no real microphone test was run.
Replace UUID placeholders with the IDs you explicitly selected; do not commit them.

```powershell
.\venv\Scripts\python.exe -m app.pipeline.cli unauthenticated-text "open Spotify" --show-transcript
.\venv\Scripts\python.exe -m app.pipeline.cli unauthenticated-text "play Taare Zameen Par" --json
.\venv\Scripts\python.exe -m app.pipeline.cli unauthenticated-voice --seconds 8 --show-transcript
.\venv\Scripts\python.exe -m app.pipeline.cli unauthenticated-voice --seconds 8 --save-audio --show-transcript
.\venv\Scripts\python.exe -m app.pipeline.cli unauthenticated-voice --seconds 8 --save-trace --show-transcript
.\venv\Scripts\python.exe -m app.pipeline.cli unauthenticated-voice --session --show-transcript
.\venv\Scripts\python.exe -m app.pipeline.cli traces list
.\venv\Scripts\python.exe -m app.pipeline.cli traces inspect --id TRACE_UUID --show-transcript
.\venv\Scripts\python.exe -m app.pipeline.cli traces delete --id TRACE_UUID
.\venv\Scripts\python.exe -m app.pipeline.cli authenticated --profile PROFILE_UUID --seconds 8
.\venv\Scripts\python.exe -m app.planning.cli validate-dataset
.\venv\Scripts\python.exe -m app.planning.cli evaluate
```

Omit the positional text to enter it interactively instead of placing it in shell
history. --json emits JSON records; interactive prompts go to stderr in real CLI use.
Readable output remains default. Saved audio prints its exact local path for manual
playback. No playback is performed by VoicePilot. Authenticated inspection without an
approved policy reports access denied and STT not called. An optional --policy UUID
selects an existing reviewed Phase 4B policy; it cannot approve one or enable the flag.

## Evaluation and next-phase boundary

The versioned dataset contains 39 independently labelled synthetic development cases:
supported/media controls, English/Hindi/Marathi/mixed forms, incomplete/ambiguous/fuzzy/
observed errors, negation/compounds, unsupported research, injection-like inputs,
code/shell, payment/purchase, destructive operations, system changes and communication.
It contains fictional personal names/locations and no private recordings or profiles.

Report exact numerators/denominators/percentages for plan validity, expected order,
dependencies, capabilities, status, risk, confirmation, prohibited blocking,
unsupported abstention and simulation-only enforcement. Ordering/dependency metrics
use the 19 expected supported plans; risk/status/validity metrics use all 39 cases.
False-safe = dangerous-labelled cases classified below high/prohibited / all 10
labelled dangerous cases, even when an unrelated gate blocks them. The reproduced
result is 0/10 false-safe, 8/8 prohibited blocking, 6/6 unsupported abstention, 19/19
ordering/dependencies and 39/39 for the other metrics. This small development result
is not a real-world safety guarantee or held-out research finding.

Publication requires a preregistered threat taxonomy, independently annotated locked
held-out cases, richer multilingual/adversarial coverage, error analysis, confidence
intervals and explicit disclosure of abstention/coverage. Synthetic code tests do not
measure speech accuracy, speaker accuracy, real observations or application outcomes.
No dependency/model/biometric calibration changes were made.

Proposed Phase 5B: separately review a narrowly scoped execution-adapter design,
process isolation, OS permissions, exact side-effect confirmation, independent
observation and rollback/idempotency. Resolve biometric calibration and additional
factors before considering authorization. None of that execution scope is approved
or implemented here. No browser/application control, wake word, TTS, frontend,
permanent history database or LLM is part of Phase 5A.
