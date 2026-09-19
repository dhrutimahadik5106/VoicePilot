"""Exact Notepad identities and private, request-local observation evidence."""
from dataclasses import dataclass
from pydantic import Field
from app.planning.models import Model

FAMILY = "Microsoft.WindowsNotepad_8wekyb3d8bbwe"
AUMID = FAMILY + "!App"
PACKAGE_PATTERN = r"Microsoft\.WindowsNotepad_[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+_(?:x64|x86|arm64)__8wekyb3d8bbwe"


class NotepadProcess(Model):
    pid: int = Field(gt=0, strict=True, repr=False, exclude=True)
    parent_pid: int = Field(ge=0, strict=True, repr=False, exclude=True)
    created: int = Field(gt=0, strict=True, repr=False, exclude=True)
    path: str = Field(max_length=32768, repr=False, exclude=True)
    family: str = Field(default="", max_length=256, repr=False, exclude=True)
    package: str = Field(default="", max_length=256, repr=False, exclude=True)
    aumid: str = Field(default="", max_length=256, repr=False, exclude=True)


@dataclass(repr=False)
class CreatedProcess:
    pid: int
    created: int
    handle: object


@dataclass(repr=False)
class NotepadAttempt:
    baseline: frozenset[tuple[int, int]]
    process: CreatedProcess
    started: float
    package_expected: bool

    def correlates(self, record):
        if (record.pid, record.created) in self.baseline:
            return False
        if record.pid == self.process.pid:
            return record.created == self.process.created
        return (record.parent_pid == self.process.pid
                and record.created >= self.process.created)
