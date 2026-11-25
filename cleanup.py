"""Junk / cache cleanup with size preview."""
import os
import shutil

from .win import IS_WINDOWS


def _targets():
    la = os.environ.get("LOCALAPPDATA", "")
    temp = os.environ.get("TEMP", "")
    win = os.environ.get("SystemRoot", r"C:\Windows")
    return [
        {"id": "user_temp", "name": "Your temp files", "paths": [temp], "default": True,
         "note": "Leftovers from installers and apps. Safe."},
        {"id": "win_temp", "name": "Windows temp files", "paths": [os.path.join(win, "Temp")], "default": True,
         "note": "Needs admin for everything to be removed. Safe."},
        {"id": "wu_cache", "name": "Windows Update download cache",
         "paths": [os.path.join(win, "SoftwareDistribution", "Download")], "default": False,
         "note": "Already-installed update files. Needs admin. Safe, can be GBs."},
        {"id": "crash", "name": "Crash dumps & error reports",
         "paths": [os.path.join(la, "CrashDumps"), os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                                                                 r"Microsoft\Windows\WER\ReportArchive")],
         "default": True, "note": "Old crash logs. Safe."},
        {"id": "dx_cache", "name": "DirectX shader cache", "paths": [os.path.join(la, "D3DSCache")],
         "default": False, "note": "Only clear if games stutter/glitch after a driver update. "
                                    "Games rebuild it, so first launch will stutter a bit."},
        {"id": "nv_cache", "name": "NVIDIA shader cache",
         "paths": [os.path.join(la, r"NVIDIA\DXCache"), os.path.join(la, r"NVIDIA\GLCache"),
                   os.path.join(os.path.dirname(la), r"LocalLow\NVIDIA\PerDriverVersion\DXCache")],
         "default": False, "note": "Same as above - only if you have stutter/corruption problems."},
        {"id": "amd_cache", "name": "AMD shader cache",
         "paths": [os.path.join(la, r"AMD\DxCache"), os.path.join(la, r"AMD\DxcCache"), os.path.join(la, r"AMD\VkCache")],
         "default": False, "note": "Same as above - only if you have stutter/corruption problems."},
        {"id": "thumbs", "name": "Thumbnail cache",
         "paths": [os.path.join(la, r"Microsoft\Windows\Explorer")], "default": False, "pattern": "thumbcache_",
         "note": "File Explorer thumbnails. Safe, they regenerate."},
    ]


def _walk_size(path, pattern=None):
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            if pattern and not f.startswith(pattern):
                continue
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def scan():
    out = []
    if not IS_WINDOWS:
        return out
    for t in _targets():
        size = sum(_walk_size(p, t.get("pattern")) for p in t["paths"] if p and os.path.isdir(p))
        out.append({**t, "size": size})
    return out


def clean(target):
    freed = 0
    pattern = target.get("pattern")
    for base in target["paths"]:
        if not base or not os.path.isdir(base):
            continue
        for entry in os.listdir(base):
            full = os.path.join(base, entry)
            if pattern and not entry.startswith(pattern):
                continue
            try:
                if os.path.isdir(full) and not os.path.islink(full):
                    size = _walk_size(full)
                    shutil.rmtree(full, ignore_errors=True)
                    if not os.path.exists(full):
                        freed += size
                    else:
                        freed += max(0, size - _walk_size(full))
                else:
                    size = os.path.getsize(full)
                    os.remove(full)
                    freed += size
            except OSError:
                continue  # file in use - skip
    return freed


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"
