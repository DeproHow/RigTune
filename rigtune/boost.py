"""Game Boost: close background apps before gaming, bring them back after."""
import os
import subprocess

import psutil

from . import tweaks
from .win import IS_WINDOWS, load_json, save_json

SESSION_FILE = "boost_session.json"

# Never touch these
PROTECTED = {
    "system", "system idle process", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "lsaiso.exe", "svchost.exe", "explorer.exe", "dwm.exe", "fontdrvhost.exe",
    "sihost.exe", "ctfmon.exe", "runtimebroker.exe", "searchhost.exe", "searchindexer.exe",
    "startmenuexperiencehost.exe", "shellexperiencehost.exe", "textinputhost.exe", "conhost.exe",
    "audiodg.exe", "msmpeng.exe", "nissrv.exe", "securityhealthservice.exe", "securityhealthsystray.exe",
    "spoolsv.exe", "taskhostw.exe", "dllhost.exe", "wudfhost.exe", "memory compression", "smartscreen.exe",
    "applicationframehost.exe", "lockapp.exe", "systemsettings.exe", "wmiprvse.exe", "dashost.exe",
    "nvcontainer.exe", "nvdisplay.container.exe", "atiesrxx.exe", "atieclxx.exe", "amdrsserv.exe",
    "python.exe", "pythonw.exe", "rigtune.exe", "powershell.exe", "cmd.exe", "windowsterminal.exe",
    "openconsole.exe", "taskmgr.exe", "audiosrv", "rtkaudusvc64.exe", "nahimicsvc64.exe",
    "steam.exe", "steamwebhelper.exe", "steamservice.exe", "epicgameslauncher.exe", "battle.net.exe",
    "easyanticheat.exe", "beservice.exe", "vgc.exe", "vgtray.exe", "faceit.exe", "faceitservice.exe",
}

# Common background hogs (lowercase substrings) - pre-ticked in Game Boost
BLOAT = [
    "onedrive", "ms-teams", "teams.exe", "icue", "armourycrate", "armoury", "lightingservice", "razer",
    "synapse", "wallpaper32", "wallpaper64", "lively", "overwolf", "medal", "outplayed", "ccleaner",
    "adobe", "creative cloud", "acrotray", "skype", "dropbox", "googledrivefs", "signalrgb", "nzxt cam", "msi center", "dragoncenter",
    "rgbfusion", "aorus", "phonelink", "yourphone", "widgets.exe", "widgetservice", "copilot",
    "eadesktop", "origin.exe", "upc.exe", "ubisoftconnect", "galaxyclient", "wemod",
]


def _is_bloat(name):
    n = name.lower()
    return any(b in n for b in BLOAT)


def list_processes():
    """Group processes by exe name; return list sorted by memory use."""
    me = os.getpid()
    groups = {}
    for p in psutil.process_iter(["pid", "name", "exe", "memory_info", "username"]):
        try:
            name = p.info["name"] or ""
            if not name or name.lower() in PROTECTED or p.info["pid"] in (0, 4, me):
                continue
            if IS_WINDOWS and p.info.get("username") is None:
                continue  # other-user/system processes we can't touch anyway
            g = groups.setdefault(name.lower(), {"name": name, "pids": [], "exe": p.info.get("exe"),
                                                 "mem": 0, "bloat": _is_bloat(name)})
            g["pids"].append(p.info["pid"])
            g["mem"] += (p.info["memory_info"].rss if p.info.get("memory_info") else 0)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return sorted((g for g in groups.values() if g["mem"] >= 5 * 1024 * 1024), key=lambda g: -g["mem"])


def boost(selected, switch_power=True):
    """selected: list of process groups from list_processes()."""
    killed, failed, relaunch = [], [], []
    for g in selected:
        # remember a launch command for the main (first) instance
        cmd = None
        for pid in g["pids"]:
            try:
                cmd = psutil.Process(pid).cmdline()
                if cmd:
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs = []
        for pid in g["pids"]:
            try:
                pr = psutil.Process(pid)
                pr.terminate()
                procs.append(pr)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        gone, alive = psutil.wait_procs(procs, timeout=3)
        for pr in alive:
            try:
                pr.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if procs:
            killed.append(g["name"])
            if g.get("exe"):
                relaunch.append({"name": g["name"], "exe": g["exe"], "cmd": cmd or [g["exe"]]})
        else:
            failed.append(g["name"])
    session = load_json(SESSION_FILE, {"relaunch": [], "power": None})
    session["relaunch"].extend(relaunch)
    if switch_power and IS_WINDOWS and session.get("power") is None:
        guid, _ = tweaks.active_power_plan()
        if guid and guid not in (tweaks.HIGH_PERF, tweaks.ULTIMATE):
            if tweaks.ensure_plan(tweaks.HIGH_PERF, "High performance"):
                session["power"] = guid
    save_json(SESSION_FILE, session)
    freed = sum(g["mem"] for g in selected if g["name"] in killed)
    return killed, failed, freed


def restore():
    session = load_json(SESSION_FILE, {"relaunch": [], "power": None})
    started = []
    seen = set()
    for item in session.get("relaunch", []):
        if item["exe"].lower() in seen:
            continue
        seen.add(item["exe"].lower())
        try:
            flags = 0x00000008 | 0x00000200 if IS_WINDOWS else 0  # DETACHED | NEW_PROCESS_GROUP
            subprocess.Popen(item["cmd"] or [item["exe"]], creationflags=flags, close_fds=True,
                             cwd=os.path.dirname(item["exe"]) or None)
            started.append(item["name"])
        except Exception:  # noqa: BLE001
            pass
    if session.get("power"):
        tweaks.set_power_plan(session["power"])
    save_json(SESSION_FILE, {"relaunch": [], "power": None})
    return started


def has_session():
    s = load_json(SESSION_FILE, {"relaunch": [], "power": None})
    return bool(s.get("relaunch") or s.get("power"))


PRIORITIES = {
    "High": psutil.HIGH_PRIORITY_CLASS if IS_WINDOWS else -10,
    "Above normal": psutil.ABOVE_NORMAL_PRIORITY_CLASS if IS_WINDOWS else -5,
    "Normal": psutil.NORMAL_PRIORITY_CLASS if IS_WINDOWS else 0,
}


def set_priority(group, level):
    ok = 0
    for pid in group["pids"]:
        try:
            psutil.Process(pid).nice(PRIORITIES[level])
            ok += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return ok
