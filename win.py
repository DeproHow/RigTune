"""Low-level Windows helpers: PowerShell, registry, admin, data folder.

Everything here degrades gracefully on non-Windows so the logic can be tested
anywhere; checks that need Windows just report "skip".
"""
import ctypes
import json
import os
import subprocess
import sys

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import winreg
else:  # pragma: no cover
    winreg = None

CREATE_NO_WINDOW = 0x08000000


# ---------------------------------------------------------------- processes
def run(cmd, timeout=30):
    """Run a command hidden. Returns (returncode, stdout, stderr)."""
    kw = {}
    if IS_WINDOWS:
        kw["creationflags"] = CREATE_NO_WINDOW
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           errors="replace", **kw)
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as e:  # noqa: BLE001
        return -1, "", str(e)


def ps(script, timeout=60):
    """Run a PowerShell script, return stdout or None."""
    if not IS_WINDOWS:
        return None
    code, out, _ = run(["powershell.exe", "-NoProfile", "-NonInteractive",
                        "-ExecutionPolicy", "Bypass", "-Command", script], timeout)
    return out if code == 0 else None


def ps_json(script, timeout=60):
    """Run PowerShell and parse JSON output. Returns parsed object or None."""
    out = ps(script, timeout)
    if not out or not out.strip():
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def as_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


# ---------------------------------------------------------------- registry
def _hive(h):
    return {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}[h]


TYPE_NAMES = {}
if IS_WINDOWS:
    TYPE_NAMES = {"DWORD": winreg.REG_DWORD, "SZ": winreg.REG_SZ,
                  "BINARY": winreg.REG_BINARY, "QWORD": winreg.REG_QWORD,
                  "EXPAND_SZ": winreg.REG_EXPAND_SZ}


def reg_get(hive, path, name, default=None):
    v, _ = reg_get_typed(hive, path, name)
    return default if v is None else v


def reg_get_typed(hive, path, name):
    """Return (value, type) or (None, None) if missing."""
    if not IS_WINDOWS:
        return None, None
    try:
        with winreg.OpenKey(_hive(hive), path, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            return winreg.QueryValueEx(k, name)
    except OSError:
        return None, None


def reg_key_exists(hive, path):
    if not IS_WINDOWS:
        return False
    try:
        with winreg.OpenKey(_hive(hive), path, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
            return True
    except OSError:
        return False


def reg_set(hive, path, name, value, rtype):
    """rtype: winreg type int or name like 'DWORD'."""
    if isinstance(rtype, str):
        rtype = TYPE_NAMES[rtype]
    with winreg.CreateKeyEx(_hive(hive), path, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
        winreg.SetValueEx(k, name, 0, rtype, value)


def reg_delete(hive, path, name):
    try:
        with winreg.OpenKey(_hive(hive), path, 0,
                            winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


def reg_values(hive, path, wow64_32=False):
    """List (name, value, type) of all values in a key."""
    if not IS_WINDOWS:
        return []
    flag = winreg.KEY_WOW64_32KEY if wow64_32 else winreg.KEY_WOW64_64KEY
    out = []
    try:
        with winreg.OpenKey(_hive(hive), path, 0, winreg.KEY_READ | flag) as k:
            i = 0
            while True:
                try:
                    out.append(winreg.EnumValue(k, i))
                except OSError:
                    break
                i += 1
    except OSError:
        pass
    return out


# ---------------------------------------------------------------- admin
def is_admin():
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001
        return False


def relaunch_as_admin():
    """Restart this program elevated. Returns True if the UAC prompt launched."""
    if not IS_WINDOWS:
        return False
    if getattr(sys, "frozen", False):
        exe = sys.executable
        params = " ".join(f'"{a}"' for a in sys.argv[1:])
    else:
        exe = sys.executable
        params = " ".join(f'"{a}"' for a in [os.path.abspath(sys.argv[0])] + sys.argv[1:])
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    return r > 32


# ---------------------------------------------------------------- storage
def data_dir():
    base = os.environ.get("APPDATA") if IS_WINDOWS else os.path.expanduser("~/.config")
    d = os.path.join(base or os.path.expanduser("~"), "RigTune")
    os.makedirs(d, exist_ok=True)
    return d


def load_json(name, default):
    p = os.path.join(data_dir(), name)
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(name, data):
    p = os.path.join(data_dir(), name)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, p)


def open_url(url):
    """Open a URL or ms-settings: / windowsdefender: link."""
    if IS_WINDOWS:
        try:
            os.startfile(url)  # noqa: S606
            return
        except OSError:
            pass
    import webbrowser
    webbrowser.open(url)
