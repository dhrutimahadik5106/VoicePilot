"""Controller-specific single-use pilot permits. Only trusted pipeline code issues them."""
from datetime import datetime, timezone, timedelta
from app.owner.models import OwnerError
from app.operations.authorization import binding as operation_binding
from app.operations.models import Permit as OperationPermit, OperationError, Code
from app.launch.authorization import digest as launch_binding
from app.launch.models import Permit as LaunchPermit
from app.speaker.artifacts import IDENTITY


class OperationAuthority:
    def __init__(self, pilot, plan):
        from app.owner.pilot import Pilot
        if type(pilot) is not Pilot:
            raise OwnerError()
        self.synthetic = pilot.calibration.engine.identity != IDENTITY
        guard, clock, expires = pilot._take_admission(plan, "operations")
        self._binding = operation_binding(plan)
        self._guard, self.clock, self.expires = guard, clock, expires
        self._permit = OperationPermit()
        self._used = False

    @property
    def permit(self):
        return self._permit

    def validate_live(self):
        try:
            self._guard()
        except Exception:
            raise OperationError(Code.DENIED) from None

    def consume(self, plan, permit):
        self.validate_live()
        if self._used or type(permit) is not OperationPermit or permit != self._permit:
            raise OperationError(Code.REPLAYED)
        self._used = True
        if operation_binding(plan) != self._binding:
            raise OperationError(Code.DENIED)
        return self.expires


class LaunchAuthority:
    mode = "authenticated_voice"

    def __init__(self, pilot, plan):
        from app.owner.pilot import Pilot
        if type(pilot) is not Pilot:
            raise OwnerError()
        self.synthetic = pilot.calibration.engine.identity != IDENTITY
        guard, clock, expires = pilot._take_admission(plan, "launch")
        remaining = expires - clock()
        self._binding = launch_binding(plan)
        self._guard = guard
        self.clock = lambda: datetime.now(timezone.utc)
        self.expires = self.clock() + timedelta(seconds=remaining)
        self._permit = LaunchPermit()
        self._used = False

    @property
    def permit(self):
        return self._permit

    def validate_live(self):
        self._guard()

    def consume(self, plan, permit):
        try:
            self.validate_live()
            if self._used or type(permit) is not LaunchPermit or permit != self._permit:
                return False
            self._used = True
            if launch_binding(plan) != self._binding or plan.mode != self.mode:
                return False
            return self.expires
        except Exception:
            return False
