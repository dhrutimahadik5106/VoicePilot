"""Pure text interpretation. No execution adapter, audio access or model calls."""
import re
from difflib import SequenceMatcher

from app.commands.models import Candidate, Resolution, ResolverConfig, SLOTS
from app.commands.registry import canonical_command, load_registries, normalize

_NEGATION = re.compile(r"(?:^| )(?:don't|dont|do not|never|not|मत|नहीं|नको|नका|नाही)(?: |$)")
_COMPOUND = re.compile(r"(?:^| )(?:and|then|also|और|फिर|आणि|नंतर)(?: |$)")


class CommandResolver:
    def __init__(self, aliases, intents, config=None):
        self.aliases = aliases
        self.intents = intents
        self.config = config or ResolverConfig()
        self._patterns = []
        for spec in intents.intents:
            for pattern in spec.patterns:
                slot = SLOTS.get(spec.intent)
                if slot:
                    prefix, suffix = pattern.text.split("{" + slot + "}")
                    # Normalize pieces separately, preserving the slot boundaries.
                    left, right = normalize(prefix), normalize(suffix)
                    expression = (re.escape(left) + r"\s+" if left else "") + r"(?P<entity>.+?)"
                    expression += (r"\s+" + re.escape(right)) if right else ""
                    missing = normalize(prefix + " " + suffix)
                    self._patterns.append((spec.intent, re.compile(expression), missing))
                else:
                    self._patterns.append((spec.intent, re.compile(re.escape(normalize(pattern.text))), None))

    @classmethod
    def from_directory(cls, directory=None, config=None):
        aliases, intents = load_registries() if directory is None else load_registries(directory)
        return cls(aliases, intents, config)

    def _entity_candidates(self, text, kind):
        found = []
        for entity in self.aliases.entities:
            if entity.kind != kind:
                continue
            choices = [(entity.canonical_name, "canonical", "Versioned canonical vocabulary", False)]
            choices += [(a.text, a.kind, a.provenance, a.requires_confirmation) for a in entity.aliases]
            candidates = []
            for label, match_type, provenance, confirm in choices:
                alias = normalize(label)
                if text == alias:
                    score = 1.0 if match_type == "canonical" else .75 if match_type == "observed_asr_error" else .98
                else:
                    score = SequenceMatcher(None, text, alias, autojunk=False).ratio() * .85
                    if score < self.config.suggestion_threshold:
                        continue
                    match_type, confirm = "fuzzy", True
                candidates.append(Candidate(
                    entity_id=entity.entity_id, canonical_name=entity.canonical_name,
                    entity_kind=entity.kind, matched_alias=label, match_type=match_type,
                    heuristic_score=score, requires_confirmation=confirm, provenance=provenance,
                ))
            if candidates:
                found.append(max(candidates, key=lambda c: (c.match_type != "fuzzy", c.heuristic_score)))
        # Exact vocabulary hits outrank fuzzy suggestions, even observed-error hits.
        found.sort(key=lambda c: (c.match_type == "fuzzy", -c.heuristic_score, c.entity_id))
        return tuple(found[:self.config.max_candidates])

    def resolve_stt(self, result):
        # Consume the raw property, never the prior STT normalized/compatibility text.
        if result.status != "succeeded":
            return Resolution(raw_transcript="",
                              normalized_transcript="", language="mixed",
                              status="unknown", requires_confirmation=True, reasons=("unsuccessful_stt",))
        language = result.language if result.language in {"en", "hi", "mr"} else "mixed"
        return self.resolve(result.raw_transcript, language=language)

    def resolve(self, raw: str, *, language="mixed"):
        if not isinstance(raw, str) or len(raw) > 500:
            raise ValueError("Transcript must be text of at most 500 characters")
        text = normalize(raw)
        base = dict(raw_transcript=raw, normalized_transcript=text, language=language)
        def unknown(reason):
            return Resolution(**base, status="unknown", requires_confirmation=True, reasons=(reason,))
        if not text:
            return unknown("empty_transcript")
        if _NEGATION.search(text):
            return unknown("negated_command")
        if any(token in raw for token in (";", "&", "|")) or "\n" in raw.strip():
            return unknown("compound_command")
        # Remove only a recognized, unambiguous assistant invocation from matching.
        assistant_names = set()
        for item in self.aliases.entities:
            if item.kind == "assistant":
                assistant_names.add(normalize(item.canonical_name))
                assistant_names.update(normalize(a.text) for a in item.aliases
                                       if not a.requires_confirmation)
        invocations = [prefix + name for name in assistant_names for prefix in ("", "hey ", "हे ")]
        for invocation in sorted(invocations, key=len, reverse=True):
            if text.startswith(invocation + " "):
                text = text[len(invocation):].strip()
                break
        for polite in ("please ", "कृपया "):
            if text.startswith(polite):
                text = text[len(polite):]
                break
        workflow = False
        workflow_application = None
        observed_address = False
        workflow_text = text
        # Only the reported address error before a complete Spotify/play workflow.
        for name in sorted(assistant_names, key=len, reverse=True):
            prefix = "play " + name + " "
            if workflow_text.startswith(prefix):
                workflow_text = workflow_text[len(prefix):]
                observed_address = True
                break
        coordinated = re.fullmatch(r"open (.+?) and play(?: (.+))?", workflow_text)
        if coordinated:
            app_text, media_text = coordinated.groups()
            apps = self._entity_candidates(app_text, "application")
            exact_apps = [a for a in apps if a.match_type != "fuzzy"]
            if (len(exact_apps) == 1 and exact_apps[0].entity_id == "spotify"
                    and not exact_apps[0].requires_confirmation
                    and not _COMPOUND.search(media_text or "")):
                workflow = True
                workflow_application = exact_apps[0].canonical_name
                text = "play" + (" " + media_text if media_text else "")
                base["normalized_transcript"] = text
        if _COMPOUND.search(text):
            return unknown("compound_command")
        if observed_address and not workflow:
            return unknown("unsupported_command")
        matches = set()
        for intent, pattern, missing in self._patterns:
            match = pattern.fullmatch(text)
            if match:
                matches.add((intent, match.groupdict().get("entity", "")))
            elif missing and text == missing:
                matches.add((intent, ""))
        if not matches:
            return unknown("unsupported_command")
        if len(matches) != 1:
            return unknown("ambiguous_intent")
        intent, entity_text = next(iter(matches))
        slot = SLOTS.get(intent)
        if slot is None:
            return Resolution(**base, intent=intent, canonical_command=canonical_command(intent, {}),
                              heuristic_score=1, status="resolved", requires_confirmation=False,
                              reasons=("exact_intent_pattern",))
        candidates = self._entity_candidates(entity_text, slot) if entity_text else ()
        entities = {"application": workflow_application} if workflow_application is not None else {}
        reasons = []
        score = candidates[0].heuristic_score if candidates else 0.0
        if not entity_text:
            reasons.append("missing_entity")
        elif not candidates:
            reasons.append("unknown_entity")
        else:
            top = candidates[0]
            exact = [candidate for candidate in candidates if candidate.match_type != "fuzzy"]
            ambiguous = len(exact) > 1 or (not exact and len(candidates) > 1 and
                          top.heuristic_score - candidates[1].heuristic_score <= self.config.ambiguity_margin)
            if ambiguous:
                reasons.append("ambiguous_entity")
            elif top.match_type == "fuzzy":
                reasons.append("fuzzy_entity_suggestion")
            else:
                # This is a visible proposal, never a replacement of input text.
                entities[slot] = top.canonical_name
                if top.requires_confirmation:
                    reasons.append("observed_asr_error" if top.match_type == "observed_asr_error" else "alias_requires_confirmation")
            if score < self.config.acceptance_threshold:
                reasons.append("low_heuristic_score")
        if observed_address:
            reasons.append("observed_address_form")
        confirm = bool(reasons)
        if workflow:
            reasons.append("spotify_play_workflow")
        return Resolution(
            **base, intent=intent, entities=entities, canonical_command=canonical_command(intent, entities),
            heuristic_score=score, candidates=candidates, status="needs_confirmation" if confirm else "resolved",
            requires_confirmation=confirm, reasons=tuple(reasons) or ("exact_entity_match",),
        )
