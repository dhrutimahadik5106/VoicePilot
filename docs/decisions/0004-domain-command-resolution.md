# 0004: Domain command resolution foundation

Phase: 3B only. The decision number is sequential, not Phase 4.
Status: accepted for a non-executing local text subsystem.

Build app/commands independently of audio capture and Whisper loading. It accepts
explicit text or an existing successful STT result's raw_transcript property.
Preserve raw, matching-normalized, and canonical proposal values separately.
No execution adapter, operating-system action, Spotify integration, history
database, LLM, speaker verification or frontend is introduced.

Use the standard library and existing Pydantic. Version schema, entity aliases,
intent patterns and the 80-row synthetic development/test seed as separate files.
Define vocabulary and grammar before the seed; never use seed rows for runtime
matching or create an alias per sentence. Cover twelve interpretation labels and
four illustrative language categories. Include hard negatives and paraphrases
outside the supported grammar; seed perfection is not a target.

Prefer full-command patterns and exact vocabulary. Limit fuzzy matching to entity
suggestions requiring confirmation. Preserve observed-error provenance, especially
Tharism Infer -> Taare Zameen Par; never call it a genuine pronunciation.
Ambiguity, negation, compounds, unknown/incomplete entities and low heuristic
scores cannot silently become accepted proposals. Heuristic scores are not
probabilities, calibrated confidence, ASR confidence or execution authorization.

Use typed data contracts and a matching exported JSON Schema. Reject duplicate
IDs, unsupported schema versions, inconsistent intent/entity/command labels and
invented recording metadata on synthetic rows. Future consented-recording
metadata requires a speaker pseudonym and consent reference; no audio is collected.

Evaluation reports exact metric counts, denominators and percentages, coverage
and explicitly defined false-accept rates. It is a local development sanity check,
not held-out research evidence. Distinguish interpretation metrics from ASR
accuracy. Do not tune repeatedly for perfect seed scores or fabricate results.

Automated tests block model/hardware imports, socket connections and system-action
entry points. Tests inspect only project data or temporary files. Import smoke
checks verify the text subsystem loads without audio/model backends. Existing
STT code remains unchanged. Publication, new collection, model integration and
all later phases require separate approval.

## Manual-validation refinement: Spotify play workflow

Only the full English form open <exact Spotify alias> and play <media> is treated
as one play_media proposal. Optional recognized assistant address prefixes are
context. Other coordinators/actions, negation, shell separators and unknown/fuzzy
application names remain blocked. Missing/unknown media remains unresolved.
No proposal is executed. The normalized matching view of this workflow is
play <media>; raw input is unchanged and no alias text is substituted into it.

The user-observed prefix Play VoicePilot is recognized only before this complete
workflow and requires confirmation as observed_address_form. Tharism Infer
continues to carry observed_asr_error provenance and requires confirmation.

Punctuation already became spaces, so reported punctuation-related token joining
was not reproduced in the inspected code. Zero-width space/BOM separators now
also become spaces; ordinary word boundaries are preserved. The CLI/resolver
returns the exact string received, including already joined TaareZameen.
Upstream STT concatenates raw segment text without inserted spaces and could
produce that boundary across segments. Without original arguments/segments,
application-versus-terminal-copy provenance cannot be determined. No raw STT
text is rewritten by this fix.

One seed annotation, open Spotify and play Taare Zameen Par, changes from rejected
compound to the newly approved play_media workflow. No other labels, aliases,
thresholds or unrelated rules were tuned. Metrics before/after therefore include
this disclosed specification change; they remain synthetic development metrics.

## Final Phase 3B context and raw-text contract correction

Coordinated Spotify/play proposals now retain both application=Spotify and
media=<title>, with canonical command Play <title> on Spotify. Observed ASR
variants still require confirmation; missing media keeps the known application
but yields no complete canonical command. Only the corresponding workflow seed
annotation is updated. Ordinary media requests without app context are unchanged.

Controlled pre-edit tracing preserved the exact spaced input through PowerShell
argv reception, direct resolution, Pydantic round-trip, supplied CLI argument
list, and a Python subprocess CLI with byte-equal UTF-8 round trips. No loss
reproduced in address/workflow stripping or JSON serialization. Thus the earlier
manual discrepancy remains unlocated; it is not assumed to be copying. The
resolver preserves the exact Unicode string received (and its UTF-8 encoding);
JSON escaping is representation, not deletion of whitespace. Strict raw-string
typing and regressions cover this contract without normalizing raw text.

The registry already stored Phase 3B instructions with its space intact. A
regression locks that provenance formatting and observed_asr_error status.
Subprocess regression is restricted to the existing venv's non-executing CLI,
with shell disabled and child network/system-action entry points blocked.
No dependency, audio, model, automation or later-phase changes are made.
