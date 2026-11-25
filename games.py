"""Find installed games (Steam, Epic, EA, Ubisoft, Battle.net, Xbox) and which drive they're on."""
import glob
import json
import os
import re

from .win import IS_WINDOWS, reg_get


def _steam_libraries():
    steam = reg_get("HKCU", r"Software\Valve\Steam", "SteamPath")
    if not steam:
        return []
    steam = steam.replace("/", "\\")
    libs = {steam}
    vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
    try:
        with open(vdf, "r", encoding="utf-8", errors="ignore") as f:
            for m in re.finditer(r'"path"\s+"([^"]+)"', f.read()):
                libs.add(m.group(1).replace("\\\\", "\\"))
    except OSError:
        pass
    return list(libs)


def steam_games():
    games = []
    for lib in _steam_libraries():
        for acf in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
            try:
                with open(acf, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read()
                name = re.search(r'"name"\s+"([^"]+)"', txt)
                inst = re.search(r'"installdir"\s+"([^"]+)"', txt)
                if name:
                    path = os.path.join(lib, "steamapps", "common", inst.group(1) if inst else "")
                    games.append({"name": name.group(1), "path": path, "store": "Steam"})
            except OSError:
                pass
    return [g for g in games if not g["name"].lower().startswith(("steamworks", "steam linux", "proton"))]


def epic_games():
    games = []
    folder = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                          r"Epic\EpicGamesLauncher\Data\Manifests")
    for item in glob.glob(os.path.join(folder, "*.item")):
        try:
            with open(item, "r", encoding="utf-8", errors="ignore") as f:
                d = json.load(f)
            if d.get("InstallLocation"):
                games.append({"name": d.get("DisplayName", "?"), "path": d["InstallLocation"], "store": "Epic"})
        except (OSError, ValueError):
            pass
    return games


def common_folders():
    """Other launchers: look for typical folders on every drive."""
    names = ["XboxGames", r"Program Files\EA Games", r"Program Files (x86)\Ubisoft\Ubisoft Game Launcher\games",
             r"Program Files (x86)\Battle.net", "Riot Games", r"Program Files\Riot Games", "Games"]
    found = []
    for letter in "CDEFGHIJ":
        for n in names:
            p = f"{letter}:\\{n}"
            if os.path.isdir(p):
                try:
                    for sub in os.listdir(p):
                        full = os.path.join(p, sub)
                        if os.path.isdir(full):
                            found.append({"name": sub, "path": full, "store": n.split("\\")[-1]})
                except OSError:
                    pass
    return found


def all_games():
    if not IS_WINDOWS:
        return []
    seen = set()
    out = []
    for g in steam_games() + epic_games() + common_folders():
        key = g["path"].lower()
        if key not in seen:
            seen.add(key)
            g["drive"] = os.path.splitdrive(g["path"])[0].rstrip(":").upper()
            out.append(g)
    return out
