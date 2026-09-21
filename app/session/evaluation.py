"""Ten deterministic in-process review scenarios; no server or real resources."""
from app.execution.cancellation import CancellationHub
from app.session.service import SessionService
from app.session.models import DemoMarker, State
from app.session.demo import TEXT


def evaluate():
    expected = {"read_volume":State.COMPLETED,"calculator_confirm":State.COMPLETED,
        "chrome_cancel":State.CANCELLED,"ambiguous_application":State.COMPLETED,
        "unknown_application":State.BLOCKED,"wrong_speaker":State.BLOCKED,
        "confirmation_expiry":State.TIMED_OUT,"emergency_stop":State.STOPPED,
        "verification_failure":State.FAILED,"history_entry":State.COMPLETED}
    outcomes = []
    for scenario in TEXT:
        now = [0.]
        service = SessionService(clock=lambda:now[0],hub=CancellationHub())
        try:
            view = service.create(scenario)
            key = view.session_id
            service.action(key,"activate")
            if scenario == "emergency_stop": service.emergency_stop()
            else:
                view = service.action(key,"stop_capture")
                if view.clarification:
                    view = service.action(key,"clarify",request_id=view.clarification.request_id,
                                          candidate_id=view.clarification.candidates[0].candidate_id)
                if view.confirmation:
                    if scenario == "confirmation_expiry": now[0] = 31.
                    else:
                        service.action(key,"confirm",request_id=view.confirmation.request_id,
                                       decision="cancel" if scenario == "chrome_cancel" else "confirm")
            view = service.action(key,"view")
            outcomes.append({"scenario":scenario,"state":view.state.value,"correct":view.state == expected[scenario],
                             "history_entries":len(service.history)})
        finally:
            service.close()
    return DemoMarker().model_dump() | {"cases":outcomes,"correct":{"numerator":sum(row["correct"] for row in outcomes),
                                                                  "denominator":len(outcomes)}}
