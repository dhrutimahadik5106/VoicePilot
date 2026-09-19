"""Versioned fixed application identities and conservative lexical resolution."""
from pathlib import PureWindowsPath
from types import MappingProxyType
from app.launch.models import Entry, LaunchError, Status

ALLOWLIST = MappingProxyType({
    "notepad": Entry(application_id="notepad", display_name="Notepad", executable_names=("notepad.exe",), original_filenames=("notepad.exe", "notepad.exe.mui"),
                     publishers=("Microsoft Corporation", "Microsoft Windows"), discovery=("system_directory",)),
    "calculator": Entry(application_id="calculator", display_name="Calculator", executable_names=("calc.exe", "CalculatorApp.exe"), original_filenames=("calc.exe", "CalculatorApp.exe"),
                        publishers=("Microsoft Corporation", "Microsoft Windows"), discovery=("system_directory",)),
    "chrome": Entry(application_id="chrome", display_name="Google Chrome", executable_names=("chrome.exe",), original_filenames=("chrome.exe",),
                    publishers=("Google LLC", "Google Inc"), discovery=("program_files",)),
    "spotify": Entry(application_id="spotify", display_name="Spotify", executable_names=("Spotify.exe",), original_filenames=("Spotify.exe",),
                     publishers=("Spotify AB",), discovery=("program_files",)),
})
ALIASES = MappingProxyType({"notepad": "notepad", "calculator": "calculator", "calc": "calculator",
                           "chrome": "chrome", "google chrome": "chrome", "spotify": "spotify"})


def resolve_application(text):
    if type(text) is not str or len(text) > 40:
        raise LaunchError(Status.UNSUPPORTED)
    result = ALIASES.get(text.strip().casefold())
    if result is None:
        raise LaunchError(Status.UNSUPPORTED)
    return result


def validate_path(path, root, names):
    """Lexical gate before any filesystem or signer query on a candidate."""
    p, r = PureWindowsPath(path), PureWindowsPath(root)
    if (not p.is_absolute() or not r.is_absolute() or len(p.drive) != 2 or p.drive[1:] != ":"
            or p.drive.casefold() != r.drive.casefold() or ".." in p.parts
            or any(c in path for c in ('%', '"', '*', '?', '|', '<', '>', '\x00'))
            or any(':' in part for part in p.parts[1:])
            or any(part.endswith((' ', '.')) for part in p.parts[1:])
            or p.name.casefold() not in {name.casefold() for name in names}
            or not p.is_relative_to(r) or p == r):
        raise LaunchError(Status.IDENTITY_MISMATCH)
    return p
