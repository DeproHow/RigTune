"""Motherboard-specific instructions for enabling XMP / EXPO."""
from urllib.parse import quote_plus

VENDORS = {
    "asus": {
        "name": "ASUS",
        "key": "DEL or F2",
        "support": "https://www.asus.com/support/",
        "steps_amd": [
            "Restart and spam DEL (or F2) as the PC boots to enter the BIOS.",
            "You land in EZ Mode. Find the 'EXPO / DOCP' (or 'D.O.C.P.') dropdown on the main screen.",
            "Set it to 'EXPO I' (or 'DOCP I'/'XMP I' if your kit only has XMP).",
            "No dropdown? Press F7 for Advanced Mode > Ai Tweaker > Ai Overclock Tuner > EXPO I.",
            "Press F10, confirm 'Save & Exit'.",
        ],
        "steps_intel": [
            "Restart and spam DEL (or F2) as the PC boots to enter the BIOS.",
            "In EZ Mode find the 'X.M.P.' dropdown and set it to 'XMP I'.",
            "Or press F7 for Advanced Mode > Ai Tweaker > Ai Overclock Tuner > XMP I.",
            "Press F10, confirm 'Save & Exit'.",
        ],
    },
    "msi": {
        "name": "MSI",
        "key": "DEL",
        "support": "https://www.msi.com/support",
        "steps_amd": [
            "Restart and spam DEL as the PC boots to enter the BIOS.",
            "In EZ Mode, look at the top-left: click the 'EXPO' (or 'A-XMP') button so it turns on, then pick Profile 1.",
            "Or press F7 for Advanced Mode > OC > 'Extended Memory Profile (EXPO)' > Profile 1.",
            "Press F10, confirm Yes to save and exit.",
        ],
        "steps_intel": [
            "Restart and spam DEL as the PC boots to enter the BIOS.",
            "In EZ Mode, click the 'XMP' button at the top-left so it turns on, then pick Profile 1.",
            "Or press F7 for Advanced Mode > OC > Extreme Memory Profile (XMP) > Profile 1.",
            "Press F10, confirm Yes to save and exit.",
        ],
    },
    "gigabyte": {
        "name": "Gigabyte / AORUS",
        "key": "DEL",
        "support": "https://www.gigabyte.com/Support",
        "steps_amd": [
            "Restart and spam DEL as the PC boots to enter the BIOS.",
            "In Easy Mode, find 'EXPO' / 'X.M.P.' and set it to 'Profile 1'.",
            "Or press F2 for Advanced Mode > Tweaker > Extreme Memory Profile (X.M.P.)/EXPO > Profile 1.",
            "Press F10, confirm to save and exit.",
        ],
        "steps_intel": [
            "Restart and spam DEL as the PC boots to enter the BIOS.",
            "In Easy Mode, set 'X.M.P.' to 'Profile 1'.",
            "Or press F2 for Advanced Mode > Tweaker > Extreme Memory Profile (X.M.P.) > Profile 1.",
            "Press F10, confirm to save and exit.",
        ],
    },
    "asrock": {
        "name": "ASRock",
        "key": "F2 or DEL",
        "support": "https://www.asrock.com/support/index.asp",
        "steps_amd": [
            "Restart and spam F2 (or DEL) as the PC boots to enter the BIOS.",
            "If you're in Easy Mode press F6 to switch to Advanced Mode.",
            "Go to OC Tweaker > DRAM Profile Setting (or 'Load EXPO/XMP Setting') > pick EXPO/XMP Profile 1.",
            "Press F10, confirm to save and exit.",
        ],
        "steps_intel": [
            "Restart and spam F2 (or DEL) as the PC boots to enter the BIOS.",
            "If you're in Easy Mode press F6 to switch to Advanced Mode.",
            "Go to OC Tweaker > DRAM Configuration > Load XMP Setting > XMP Profile 1.",
            "Press F10, confirm to save and exit.",
        ],
    },
    "biostar": {
        "name": "Biostar",
        "key": "DEL",
        "support": "https://www.biostar.com.tw/app/en/support/",
        "steps_amd": ["Enter BIOS with DEL.", "O.N.E. (or Tweaker) > Memory > set EXPO/XMP to Profile 1.", "F10 to save."],
        "steps_intel": ["Enter BIOS with DEL.", "O.N.E. (or Tweaker) > Memory > set XMP to Profile 1.", "F10 to save."],
    },
    "dell": {
        "name": "Dell / Alienware",
        "key": "F2",
        "support": "https://www.dell.com/support/home",
        "steps_amd": ["Enter BIOS with F2.", "Look under Performance > Memory (or 'Overclocking') for XMP/EXPO and enable Profile 1.",
                      "Many Dell desktops (non-Alienware) don't have this option at all - then the RAM speed is locked."],
        "steps_intel": ["Enter BIOS with F2.", "Look under Performance > Memory (or 'Overclocking') for XMP and enable Profile 1.",
                        "Many Dell desktops (non-Alienware) don't have this option at all - then the RAM speed is locked."],
    },
    "hp": {
        "name": "HP / OMEN",
        "key": "F10",
        "support": "https://support.hp.com",
        "steps_amd": ["Enter BIOS with F10.", "OMEN models: Advanced > Memory > enable 'Memory Overclocking'/XMP.",
                      "Most non-OMEN HP PCs don't support XMP - RAM speed is locked."],
        "steps_intel": ["Enter BIOS with F10.", "OMEN models: Advanced > Memory > enable 'Memory Overclocking'/XMP.",
                        "Most non-OMEN HP PCs don't support XMP - RAM speed is locked."],
    },
    "lenovo": {
        "name": "Lenovo / Legion",
        "key": "F1 or F2",
        "support": "https://pcsupport.lenovo.com",
        "steps_amd": ["Enter BIOS with F1/F2.", "Legion models: Advanced (or Overclocking) > Memory > XMP/EXPO enable.",
                      "Most non-Legion Lenovo PCs don't support XMP."],
        "steps_intel": ["Enter BIOS with F1/F2.", "Legion models: Advanced (or Overclocking) > Memory > XMP enable.",
                        "Most non-Legion Lenovo PCs don't support XMP."],
    },
}

GENERIC = {
    "name": "your motherboard",
    "key": "DEL (most boards) or F2",
    "support": None,
    "steps_amd": ["Restart and spam DEL (or F2) to enter BIOS.",
                  "Look for 'EXPO', 'DOCP', 'A-XMP' or 'Memory Profile' (often under OC / Tweaker / Ai Tweaker).",
                  "Set it to Profile 1, then F10 to save and exit."],
    "steps_intel": ["Restart and spam DEL (or F2) to enter BIOS.",
                    "Look for 'XMP' or 'Memory Profile' (often under OC / Tweaker / Ai Tweaker).",
                    "Set it to Profile 1, then F10 to save and exit."],
}


def vendor_key(manufacturer):
    m = (manufacturer or "").lower()
    for k, needle in (("asus", "asus"), ("msi", "micro-star"), ("msi", "msi"), ("gigabyte", "gigabyte"),
                      ("asrock", "asrock"), ("biostar", "biostar"), ("dell", "dell"), ("dell", "alienware"),
                      ("hp", "hewlett"), ("hp", "hp"), ("lenovo", "lenovo")):
        if needle in m:
            return k
    return None


def guide(board_manufacturer, board_product, cpu_vendor, mem_type):
    v = VENDORS.get(vendor_key(board_manufacturer), GENERIC)
    profile = "EXPO" if (cpu_vendor == "AMD" and mem_type == "DDR5") else "XMP"
    if cpu_vendor == "AMD" and mem_type == "DDR4":
        profile = "DOCP / A-XMP / XMP"
    steps = v["steps_amd"] if cpu_vendor == "AMD" else v["steps_intel"]
    model = f"{v['name'] if v is not GENERIC else ''} {board_product or ''}".strip()
    q = quote_plus(f"{model} enable {profile.split(' ')[0]} BIOS")
    links = []
    if v.get("support"):
        links.append((f"{v['name']} support & BIOS downloads", v["support"]))
    links.append(("Google: how to enable on your board", f"https://www.google.com/search?q={q}"))
    links.append(("YouTube video guides", f"https://www.youtube.com/results?search_query={q}"))
    return {"vendor": v["name"], "key": v["key"], "profile": profile, "steps": steps, "links": links}
