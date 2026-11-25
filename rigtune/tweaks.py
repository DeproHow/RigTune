"""Reversible tweaks. Every change backs up the original value first so
'Undo' puts things back exactly as they were."""
import re

from . import mouse
from .win import (IS_WINDOWS, is_admin, load_json, ps, reg_delete, reg_get, reg_get_typed,
                  reg_set, run, save_json)

BACKUP_FILE = "backups.json"

# Power plan GUIDs
BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"
HIGH_PERF = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
POWER_SAVER = "a1841308-3541-4fab-bc81-f71556f20b4a"
ULTIMATE = "e9a42b02-d5df-448d-aa00-03f14749eb61"

GUID_RE = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


# ------------------------------------------------------------- power plans
def active_power_plan():
    """Return (guid, name) or (None, None)."""
    code, out, _ = run(["powercfg", "/getactivescheme"])
    if code != 0:
        return None, None
    m = GUID_RE.search(out)
    name = out.split("(")[-1].rstrip(")\r\n ") if "(" in out else ""
    return (m.group(1).lower() if m else None), name


def list_power_plans():
    code, out, _ = run(["powercfg", "/list"])
    plans = []
    for line in out.splitlines():
        m = GUID_RE.search(line)
        if m:
            name = line.split("(")[-1].split(")")[0] if "(" in line else m.group(1)
            plans.append((m.group(1).lower(), name))
    return plans


def set_power_plan(guid):
    code, _, err = run(["powercfg", "/setactive", guid])
    return code == 0


def ensure_plan(template_guid, name_hint):
    """Activate a built-in plan; if hidden (Modern Standby PCs), duplicate it."""
    if set_power_plan(template_guid):
        return template_guid
    for g, n in list_power_plans():
        if name_hint.lower() in n.lower():
            if set_power_plan(g):
                return g
    code, out, _ = run(["powercfg", "-duplicatescheme", template_guid])
    m = GUID_RE.search(out)
    if code == 0 and m and set_power_plan(m.group(1)):
        return m.group(1).lower()
    return None


# ------------------------------------------------------------- backups
def _backups():
    return load_json(BACKUP_FILE, {})


def _save_backups(b):
    save_json(BACKUP_FILE, b)


def _backup_reg(tid, entries):
    b = _backups()
    if tid in b:  # keep the very first original
        return
    saved = []
    for hive, path, name, *_ in entries:
        v, t = reg_get_typed(hive, path, name)
        if isinstance(v, bytes):
            v = {"hex": v.hex()}
        saved.append([hive, path, name, v, t])
    b[tid] = {"kind": "reg", "values": saved}
    _save_backups(b)


def _backup_custom(tid, data):
    b = _backups()
    if tid not in b:
        b[tid] = {"kind": "custom", "data": data}
        _save_backups(b)


def _restore(tid):
    b = _backups()
    entry = b.get(tid)
    if not entry:
        return False
    if entry["kind"] == "reg":
        for hive, path, name, v, t in entry["values"]:
            if v is None:
                reg_delete(hive, path, name)
            else:
                if isinstance(v, dict) and "hex" in v:
                    v = bytes.fromhex(v["hex"])
                reg_set(hive, path, name, v, t)
    del b[tid]
    _save_backups(b)
    return True


def has_backup(tid):
    return tid in _backups()


# ------------------------------------------------------------- tweak class
class Tweak:
    def __init__(self, tid, name, desc, category, recommended=True,
                 admin=False, reboot=False, warning=None):
        self.id = tid
        self.name = name
        self.desc = desc
        self.category = category
        self.recommended = recommended
        self.admin = admin
        self.reboot = reboot
        self.warning = warning

    def is_applied(self):
        raise NotImplementedError

    def apply(self):
        raise NotImplementedError

    def revert(self):
        raise NotImplementedError

    def can_run(self):
        if not IS_WINDOWS:
            return False, "Windows only"
        if self.admin and not is_admin():
            return False, "Needs admin - click 'Restart as admin' in the sidebar"
        return True, ""


class RegTweak(Tweak):
    """entries: list of (hive, path, name, type, value)."""

    def __init__(self, tid, name, desc, category, entries, **kw):
        super().__init__(tid, name, desc, category, **kw)
        self.entries = entries

    def is_applied(self):
        for hive, path, name, _t, value in self.entries:
            if reg_get(hive, path, name) != value:
                return False
        return True

    def apply(self):
        _backup_reg(self.id, self.entries)
        for hive, path, name, t, value in self.entries:
            reg_set(hive, path, name, value, t)
        return True, "Applied" + (" - restart your PC to take effect" if self.reboot else "")

    def revert(self):
        if _restore(self.id):
            return True, "Restored original setting"
        return False, "No backup found (this was already like this before RigTune)"


class MouseAccelTweak(Tweak):
    def is_applied(self):
        return mouse.accel_on() is False

    def apply(self):
        cur = mouse.get_accel()
        _backup_custom(self.id, cur)
        ok = mouse.set_accel([0, 0, 0])
        return ok, "Mouse acceleration OFF (raw 1:1 aim)" if ok else "Failed"

    def revert(self):
        b = _backups().get(self.id)
        if not b:
            return False, "No backup"
        mouse.set_accel(b["data"])
        _restore(self.id)
        return True, "Restored"


class MouseSpeedTweak(Tweak):
    def is_applied(self):
        return mouse.get_speed() == 10

    def apply(self):
        _backup_custom(self.id, mouse.get_speed())
        ok = mouse.set_speed(10)
        return ok, "Pointer speed set to 10/20 (6/11 notch, no skipped pixels)" if ok else "Failed"

    def revert(self):
        b = _backups().get(self.id)
        if not b:
            return False, "No backup"
        mouse.set_speed(b["data"] or 10)
        _restore(self.id)
        return True, "Restored"


class PowerPlanTweak(Tweak):
    def __init__(self, tid, name, desc, category, template, hint, **kw):
        super().__init__(tid, name, desc, category, **kw)
        self.template = template
        self.hint = hint

    def is_applied(self):
        g, n = active_power_plan()
        return g == self.template or (n and self.hint.lower() in n.lower())

    def apply(self):
        g, _ = active_power_plan()
        _backup_custom("power_plan", g)
        new = ensure_plan(self.template, self.hint)
        return (bool(new), f"Activated {self.hint}" if new else "Couldn't activate this plan")

    def revert(self):
        b = _backups().get("power_plan")
        if not b:
            return False, "No backup"
        set_power_plan(b["data"] or BALANCED)
        _restore("power_plan")
        return True, "Restored previous power plan"


DX_PATH = r"Software\Microsoft\DirectX\UserGpuPreferences"


class DxSettingTweak(Tweak):
    """Edits a key=value; pair inside DirectXUserGlobalSettings."""

    def __init__(self, tid, name, desc, category, key, value, **kw):
        super().__init__(tid, name, desc, category, **kw)
        self.key, self.value = key, value

    @staticmethod
    def _parse(s):
        d = {}
        for part in (s or "").split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                d[k.strip()] = v.strip()
        return d

    def is_applied(self):
        return self._parse(reg_get("HKCU", DX_PATH, "DirectXUserGlobalSettings")).get(self.key) == self.value

    def apply(self):
        _backup_reg(self.id, [("HKCU", DX_PATH, "DirectXUserGlobalSettings")])
        d = self._parse(reg_get("HKCU", DX_PATH, "DirectXUserGlobalSettings"))
        d[self.key] = self.value
        reg_set("HKCU", DX_PATH, "DirectXUserGlobalSettings", "".join(f"{k}={v};" for k, v in d.items()), "SZ")
        return True, "Applied - restart your games"

    def revert(self):
        return (True, "Restored") if _restore(self.id) else (False, "No backup")


# ------------------------------------------------------------- the list
GB = r"Software\Microsoft\GameBar"
GCS = r"System\GameConfigStore"
DVR = r"Software\Microsoft\Windows\CurrentVersion\GameDVR"
ACC = r"Control Panel\Accessibility"

TWEAKS = [
    MouseAccelTweak("mouse_accel", "Turn off mouse acceleration",
                    "Disables 'Enhance pointer precision' so your aim is 1:1 with your hand movement. "
                    "Every competitive player does this.", "Mouse & Input"),
    MouseSpeedTweak("mouse_speed", "Windows pointer speed to default (10/20)",
                    "At 10/20 Windows doesn't skip or multiply pixels. Change sensitivity in-game or in "
                    "your mouse software (DPI) instead.", "Mouse & Input"),
    RegTweak("sticky_keys", "Disable Sticky/Filter/Toggle Keys shortcuts",
             "Stops the 'Do you want to turn on Sticky Keys?' popup when you spam Shift mid-game.",
             "Mouse & Input",
             [("HKCU", ACC + r"\StickyKeys", "Flags", "SZ", "506"),
              ("HKCU", ACC + r"\Keyboard Response", "Flags", "SZ", "122"),
              ("HKCU", ACC + r"\ToggleKeys", "Flags", "SZ", "58")]),
    RegTweak("game_mode", "Turn on Game Mode",
             "Windows prioritises the game and pauses Windows Update installs/notifications while you play.",
             "Windows Gaming",
             [("HKCU", GB, "AutoGameModeEnabled", "DWORD", 1),
              ("HKCU", GB, "AllowAutoGameMode", "DWORD", 1)]),
    RegTweak("game_dvr", "Turn off Xbox Game Bar background recording",
             "Background recording constantly captures your gameplay and costs FPS. "
             "You lose Win+Alt+G clips - use NVIDIA ShadowPlay / AMD ReLive / OBS for clips instead.",
             "Windows Gaming",
             [("HKCU", GCS, "GameDVR_Enabled", "DWORD", 0),
              ("HKCU", DVR, "AppCaptureEnabled", "DWORD", 0),
              ("HKCU", DVR, "HistoricalCaptureEnabled", "DWORD", 0)]),
    RegTweak("hags", "Turn on Hardware-Accelerated GPU Scheduling (HAGS)",
             "Lets the GPU manage its own memory scheduling. Required for DLSS Frame Generation. "
             "Usually small gains / lower latency on RTX 30/40/50 and RX 6000+.",
             "Graphics",
             [("HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", "DWORD", 2)],
             admin=True, reboot=True),
    DxSettingTweak("windowed_opt", "Turn on 'Optimizations for windowed games'",
                   "Makes borderless/windowed DX10/11 games use the modern flip model: lower latency and "
                   "VRR/G-Sync works in borderless.", "Graphics", "SwapEffectUpgradeEnable", "1"),
    DxSettingTweak("vrr_opt", "Turn on Variable Refresh Rate for all games",
                   "Allows VRR (G-Sync/FreeSync) in games that don't support it natively.",
                   "Graphics", "VRROptimizeEnable", "1"),
    PowerPlanTweak("power_high", "Use the High Performance power plan",
                   "Keeps the CPU from downclocking aggressively. Small but real boost on desktops. "
                   "Not recommended on laptops on battery.", "Power & CPU", HIGH_PERF, "High performance"),
    PowerPlanTweak("power_ultimate", "Use the Ultimate Performance power plan",
                   "Even more aggressive than High Performance (no idle power saving at all). "
                   "On most desktops it's the same FPS as High Performance, just more power draw.",
                   "Power & CPU", ULTIMATE, "Ultimate Performance", recommended=False),
    RegTweak("transparency", "Turn off transparency effects",
             "Removes blur behind taskbar/Start. Tiny effect on strong PCs, helps weaker ones.",
             "Windows Visuals",
             [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "EnableTransparency", "DWORD", 0)],
             recommended=False),
    RegTweak("animations", "Reduce window animations",
             "Makes Windows feel snappier (minimise/maximise animations off).",
             "Windows Visuals",
             [("HKCU", r"Control Panel\Desktop\WindowMetrics", "MinAnimate", "SZ", "0")],
             recommended=False),
    RegTweak("bg_apps", "Stop Store apps running in the background",
             "Prevents Microsoft Store apps (Weather, News, etc.) from running when you're not using them.",
             "Windows Gaming",
             [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications", "GlobalUserDisabled", "DWORD", 1)],
             recommended=False),
    RegTweak("tips_off", "Turn off Windows tips & suggestions popups",
             "Stops 'Get tips and suggestions' notifications that can pop over your game.",
             "Windows Gaming",
             [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SubscribedContent-338389Enabled", "DWORD", 0),
              ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager", "SoftLandingEnabled", "DWORD", 0)],
             recommended=False),
]

BY_ID = {t.id: t for t in TWEAKS}


def safe_applied(t):
    try:
        return t.is_applied() if IS_WINDOWS else False
    except Exception:  # noqa: BLE001
        return False


def apply(tid):
    t = BY_ID[tid]
    ok, why = t.can_run()
    if not ok:
        return False, why
    try:
        return t.apply()
    except PermissionError:
        return False, "Access denied - restart RigTune as admin"
    except Exception as e:  # noqa: BLE001
        return False, f"Error: {e}"


def revert(tid):
    t = BY_ID[tid]
    ok, why = t.can_run()
    if not ok:
        return False, why
    try:
        return t.revert()
    except PermissionError:
        return False, "Access denied - restart RigTune as admin"
    except Exception as e:  # noqa: BLE001
        return False, f"Error: {e}"


def undo_all():
    results = []
    for t in TWEAKS:
        if has_backup(t.id) or (isinstance(t, PowerPlanTweak) and has_backup("power_plan")):
            results.append((t.name, *revert(t.id)))
    return results


def create_restore_point():
    if not is_admin():
        return False, "Needs admin"
    out = ps("try { Checkpoint-Computer -Description 'RigTune backup' -RestorePointType MODIFY_SETTINGS -ErrorAction Stop; 'OK' } "
             "catch { 'ERR: ' + $_.Exception.Message }", timeout=180)
    if out and out.strip().startswith("OK"):
        return True, "Restore point created"
    msg = (out or "").strip()
    if "1440" in msg or "frequency" in msg.lower():
        return False, "Windows only allows one restore point every 24h - one was already made recently, you're covered"
    return False, (msg or "Failed") + "\nTip: make sure System Protection is ON for C: (search 'Create a restore point')."


def restart_to_bios():
    if not is_admin():
        return False, "Needs admin"
    code, out, err = run(["shutdown", "/r", "/fw", "/t", "5"])
    if code == 0:
        return True, "Restarting into BIOS in 5 seconds..."
    return False, "Your PC doesn't support direct boot to BIOS (old/legacy BIOS). Restart and spam DEL instead."
