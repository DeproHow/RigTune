"""Startup apps manager using Windows' own StartupApproved mechanism
(the same thing Task Manager's Startup tab toggles)."""
import os
import struct
import time

from .win import IS_WINDOWS, reg_get, reg_set, reg_values

RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN32 = r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run"
APPROVED = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved"

HEAVY = ["onedrive", "teams", "icue", "armoury", "armourycrate", "synapse", "razer", "wallpaper",
         "overwolf", "medal", "epicgames", "eadesktop", "origin", "ubisoft", "uplay", "battle.net",
         "adobe", "creative cloud", "ccleaner", "skype", "spotify", "discord", "steam", "opera",
         "msedge", "chrome", "cortana", "lghub", "signalrgb", "nzxt", "msi center", "dragon center",
         "gigabyte", "rgbfusion", "aura", "mcafee", "norton", "avast", "avg", "googledrive", "dropbox"]


def _sources():
    appdata = os.environ.get("APPDATA", "")
    progdata = os.environ.get("ProgramData", r"C:\ProgramData")
    return [
        {"label": "Registry (you)", "kind": "reg", "hive": "HKCU", "path": RUN, "wow": False,
         "approved": ("HKCU", APPROVED + r"\Run")},
        {"label": "Registry (all users)", "kind": "reg", "hive": "HKLM", "path": RUN, "wow": False,
         "approved": ("HKLM", APPROVED + r"\Run")},
        {"label": "Registry (all users, 32-bit)", "kind": "reg", "hive": "HKLM", "path": RUN, "wow": True,
         "approved": ("HKLM", APPROVED + r"\Run32")},
        {"label": "Startup folder (you)", "kind": "folder",
         "path": os.path.join(appdata, r"Microsoft\Windows\Start Menu\Programs\Startup"),
         "approved": ("HKCU", APPROVED + r"\StartupFolder")},
        {"label": "Startup folder (all users)", "kind": "folder",
         "path": os.path.join(progdata, r"Microsoft\Windows\Start Menu\Programs\StartUp"),
         "approved": ("HKLM", APPROVED + r"\StartupFolder")},
    ]


def _is_enabled(approved, name):
    hive, path = approved
    v = reg_get(hive, path, name)
    if isinstance(v, (bytes, bytearray)) and len(v) >= 1:
        return (v[0] & 1) == 0
    return True


def list_entries():
    if not IS_WINDOWS:
        return []
    out = []
    for s in _sources():
        if s["kind"] == "reg":
            for name, cmd, _t in reg_values(s["hive"], s["path"], wow64_32=s["wow"]):
                out.append(_entry(name, str(cmd), s))
        else:
            try:
                for f in os.listdir(s["path"]):
                    if f.lower() == "desktop.ini":
                        continue
                    out.append(_entry(f, os.path.join(s["path"], f), s))
            except OSError:
                pass
    return out


def _entry(name, cmd, s):
    low = (name + " " + cmd).lower()
    return {
        "name": name, "command": cmd, "location": s["label"],
        "approved": s["approved"], "enabled": _is_enabled(s["approved"], name),
        "heavy": any(h in low for h in HEAVY),
        "admin": s["approved"][0] == "HKLM",
    }


def _filetime_now():
    return int((time.time() + 11644473600) * 10_000_000)


def set_enabled(entry, enabled):
    hive, path = entry["approved"]
    if enabled:
        data = bytes([2]) + bytes(11)
    else:
        data = bytes([3, 0, 0, 0]) + struct.pack("<Q", _filetime_now())
    try:
        reg_set(hive, path, entry["name"], data, "BINARY")
        return True, ("Enabled" if enabled else "Disabled") + f": {entry['name']}"
    except PermissionError:
        return False, "Needs admin for all-users entries"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def enabled_count():
    return sum(1 for e in list_entries() if e["enabled"])
