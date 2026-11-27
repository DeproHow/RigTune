"""RigTune GUI (customtkinter)."""
import os
import queue
import threading
import time
import tkinter.messagebox as mb

import customtkinter as ctk

from . import (APP_NAME, APP_VERSION, boost, checks, cleanup, display, freshstart, network, report, startup,
               storage, sysinfo, tweaks)
from .win import IS_WINDOWS, is_admin, open_url, relaunch_as_admin

ACCENT = "#8b5cf6"
ACCENT_HOVER = "#7c3aed"
BG = "#0f1115"
PANEL = "#161922"
CARD = "#1c2030"
MUTED = "#9ca3af"
COLORS = report.COLORS
LABELS = report.LABELS


def font(size=13, bold=False):
    return ctk.CTkFont(family="Segoe UI", size=size, weight="bold" if bold else "normal")


def clear(frame):
    for w in frame.winfo_children():
        w.destroy()


def header(parent, title, subtitle=None):
    ctk.CTkLabel(parent, text=title, font=font(26, True), anchor="w").pack(fill="x", padx=24, pady=(22, 0))
    if subtitle:
        ctk.CTkLabel(parent, text=subtitle, font=font(13), text_color=MUTED, anchor="w",
                     justify="left", wraplength=900).pack(fill="x", padx=24, pady=(2, 12))


def button(parent, text, cmd, primary=True, width=140, **kw):
    if primary:
        return ctk.CTkButton(parent, text=text, command=cmd, width=width, fg_color=ACCENT,
                             hover_color=ACCENT_HOVER, font=font(13, True), **kw)
    return ctk.CTkButton(parent, text=text, command=cmd, width=width, fg_color="#2a2f3f",
                         hover_color="#353b4f", font=font(13), **kw)


# =========================================================================== APP
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title(f"{APP_NAME} - PC gaming optimizer")
        self.geometry("1280x820")
        self.minsize(1100, 700)
        self.configure(fg_color=BG)
        self._q = queue.Queue()
        self.info = None
        self.results = []
        self.score = None
        self.last_scan = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.toast_lbl = ctk.CTkLabel(self, text="", font=font(13, True), corner_radius=8,
                                      fg_color="#000000", height=34)
        self.pages = {}
        self.current = None
        self.show("dashboard")
        self.after(80, self._poll)
        if not IS_WINDOWS:
            self.after(500, lambda: self.toast("Not on Windows - checks will be skipped (preview mode)", "warn"))

    # ------------------------------------------------------------ threading
    def call(self, fn, *args):
        """Thread-safe: run fn(*args) on the UI thread."""
        self._q.put((fn, args))

    def bg(self, work, done=None):
        def worker():
            try:
                res = work()
                if done:
                    self.call(done, res)
            except Exception as e:  # noqa: BLE001
                self.call(self.toast, f"Error: {e}", "bad")
        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        try:
            while True:
                fn, args = self._q.get_nowait()
                try:
                    fn(*args)
                except Exception as e:  # noqa: BLE001
                    print("UI callback error:", e)
        except queue.Empty:
            pass
        self.after(60, self._poll)

    # ------------------------------------------------------------ sidebar / nav
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=230, fg_color=PANEL, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsw")
        sb.grid_propagate(False)
        ctk.CTkLabel(sb, text="⚡ " + APP_NAME + " V2", font=font(24, True), text_color=ACCENT).pack(pady=(24, 2), padx=20, anchor="w")
        ctk.CTkLabel(sb, text="Real optimizations. No placebo.", font=font(11), text_color=MUTED).pack(padx=20, anchor="w")
        self.nav_btns = {}
        items = [("dashboard", "🏠  Dashboard"), ("results", "🔍  Scan results"), ("optimize", "🛠  Optimize"),
                 ("boost", "🚀  Game Boost"), ("startup", "⏻  Startup apps"), ("cleanup", "🧹  Cleanup"),
                 ("storage", "💾  Storage"), ("fresh", "✨  Fresh Start"),
                 ("network", "🌐  Network test"), ("system", "💻  System info"), ("tools", "🧰  Tools & history")]
        ctk.CTkFrame(sb, height=16, fg_color="transparent").pack()
        for key, label in items:
            b = ctk.CTkButton(sb, text=label, anchor="w", font=font(14), height=40, corner_radius=8,
                              fg_color="transparent", hover_color="#232838", text_color="#e5e7eb",
                              command=lambda k=key: self.show(k))
            b.pack(fill="x", padx=12, pady=2)
            self.nav_btns[key] = b
        bottom = ctk.CTkFrame(sb, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=14, pady=16)
        if is_admin():
            ctk.CTkLabel(bottom, text="✔ Running as admin", text_color=COLORS["good"], font=font(12, True)).pack(anchor="w")
        else:
            ctk.CTkLabel(bottom, text="Some fixes need admin", text_color=COLORS["warn"], font=font(12)).pack(anchor="w")
            button(bottom, "Restart as admin", self._elevate, width=190).pack(anchor="w", pady=(4, 0))
        ctk.CTkLabel(bottom, text=f"v{APP_VERSION}", text_color=MUTED, font=font(11)).pack(anchor="w", pady=(8, 0))

    def _elevate(self):
        if relaunch_as_admin():
            self.destroy()
        else:
            self.toast("Admin restart was cancelled", "warn")

    def show(self, key):
        page_classes = {"dashboard": DashboardPage, "results": ResultsPage, "optimize": OptimizePage,
                        "boost": BoostPage, "startup": StartupPage, "cleanup": CleanupPage,
                        "storage": StoragePage, "fresh": FreshStartPage,
                        "network": NetworkPage, "system": SystemPage, "tools": ToolsPage}
        if self.current:
            self.current.pack_forget()
        if key not in self.pages:
            self.pages[key] = page_classes[key](self.content, self)
        self.current = self.pages[key]
        self.current.pack(fill="both", expand=True)
        for k, b in self.nav_btns.items():
            b.configure(fg_color=ACCENT if k == key else "transparent")
        self.current.on_show()

    # ------------------------------------------------------------ toast
    def toast(self, text, kind="good"):
        self.toast_lbl.configure(text="  " + text + "  ", text_color=COLORS.get(kind, "#fff"))
        self.toast_lbl.place(relx=0.6, rely=0.97, anchor="s")
        self.toast_lbl.lift()
        tag = time.time()
        self._toast_tag = tag
        self.after(4500, lambda: self._hide_toast(tag))

    def _hide_toast(self, tag):
        if getattr(self, "_toast_tag", None) == tag:
            self.toast_lbl.place_forget()

    # ------------------------------------------------------------ scanning
    def start_scan(self):
        dash = self.pages.get("dashboard")
        if dash:
            dash.scanning(True)

        def work():
            return checks.run_all(progress=lambda f, t: self.call(self._progress, f, t))
        self.bg(work, self._scan_done)

    def _progress(self, frac, text):
        d = self.pages.get("dashboard")
        if d:
            d.set_progress(frac, text)

    def _scan_done(self, res):
        self.info, self.results = res
        self.score = checks.score(self.results)
        self.last_scan = checks.now_str()
        report.add_history(self.score, self.results)
        d = self.pages.get("dashboard")
        if d:
            d.scanning(False)
        for p in self.pages.values():
            p.dirty = True
        self.current.on_show()
        bad = sum(r.status == "bad" for r in self.results)
        self.toast(f"Scan done - score {self.score}/100, {bad} problem(s) found",
                   "good" if bad == 0 else "warn")

    def recompute(self):
        self.score = checks.score(self.results)
        for p in self.pages.values():
            p.dirty = True
        self.current.on_show()

    # ------------------------------------------------------------ fixes
    def do_fix(self, r):
        f = r.fix or ""
        if f.startswith("tweak:"):
            tid = f.split(":", 1)[1]
            t = tweaks.BY_ID[tid]
            if t.admin and not is_admin():
                if mb.askyesno(APP_NAME, f"'{t.name}' needs admin rights.\n\nRestart RigTune as admin now?"):
                    self._elevate()
                return

            def done(res):
                ok, msg = res
                self.toast(msg, "good" if ok else "bad")
                if ok:
                    self._mark_fixed(r)
            self.bg(lambda: tweaks.apply(tid), done)
        elif f.startswith("display:"):
            src, w, h, hz = f.split(":", 1)[1].split("|")
            if not mb.askyesno(APP_NAME, f"Change {src} to {w}x{h} @ {hz}Hz?\n\n"
                                         "Your screen may flicker for a second."):
                return
            ok, msg = display.set_mode(src, int(w), int(h), int(hz))
            self.toast(msg, "good" if ok else "bad")
            if ok:
                self._mark_fixed(r)
        elif f.startswith("page:"):
            self.show(f.split(":", 1)[1])
        elif f.startswith("open:"):
            open_url(f.split(":", 1)[1])
        elif f == "bios":
            self.restart_bios()

    def restart_bios(self):
        if not is_admin():
            if mb.askyesno(APP_NAME, "Restarting straight into BIOS needs admin.\n\nRestart RigTune as admin now?"):
                self._elevate()
            return
        if not mb.askyesno(APP_NAME, "Your PC will restart straight into the BIOS in 5 seconds.\n\n"
                                     "Save your stuff first! Continue?"):
            return
        ok, msg = tweaks.restart_to_bios()
        self.toast(msg, "good" if ok else "bad")
        if not ok:
            mb.showinfo(APP_NAME, msg)

    def _mark_fixed(self, r):
        r.status = "good"
        r.summary = "Fixed by RigTune ✔ (run a new scan to confirm)"
        r.fix = None
        self.recompute()


# =========================================================================== base page
class Page(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color=BG, corner_radius=0)
        self.app = app
        self.dirty = True
        self.build()

    def build(self):
        pass

    def on_show(self):
        pass


def result_card(parent, r, app, compact=False):
    card = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=10, border_width=2,
                        border_color=COLORS[r.status])
    card.pack(fill="x", padx=6, pady=5)
    top = ctk.CTkFrame(card, fg_color="transparent")
    top.pack(fill="x", padx=14, pady=(10, 0))
    ctk.CTkLabel(top, text=f" {LABELS[r.status]} ", fg_color=COLORS[r.status], text_color="#000",
                 corner_radius=6, font=font(11, True)).pack(side="left")
    ctk.CTkLabel(top, text=r.title, font=font(15, True), anchor="w").pack(side="left", padx=10)
    ctk.CTkLabel(top, text=r.category, font=font(11), text_color=MUTED).pack(side="right")
    ctk.CTkLabel(card, text=r.summary, font=font(13, True), anchor="w", justify="left",
                 wraplength=860).pack(fill="x", padx=14, pady=(6, 0))
    if r.detail and not compact:
        ctk.CTkLabel(card, text=r.detail, font=font(12), text_color="#c7cbd6", anchor="w", justify="left",
                     wraplength=860).pack(fill="x", padx=14, pady=(4, 0))
    if r.steps and not compact:
        txt = "\n".join(f"{i}. {s}" for i, s in enumerate(r.steps, 1))
        ctk.CTkLabel(card, text=txt, font=font(12), anchor="w", justify="left", wraplength=860,
                     text_color="#e5e7eb").pack(fill="x", padx=24, pady=(6, 0))
    btns = ctk.CTkFrame(card, fg_color="transparent")
    btns.pack(fill="x", padx=14, pady=(8, 10))
    if r.fix:
        button(btns, r.fix_label, lambda: app.do_fix(r), width=170).pack(side="left", padx=(0, 8))
    if not compact:
        for label, url in r.links:
            button(btns, "🔗 " + label, lambda u=url: open_url(u), primary=False, width=120).pack(side="left", padx=(0, 8))
    return card


# =========================================================================== dashboard
class DashboardPage(Page):
    def build(self):
        header(self, "Dashboard", "Scan your PC to find what's actually holding your FPS back.")
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=24)
        # score panel
        sp = ctk.CTkFrame(row, fg_color=PANEL, corner_radius=14, width=330, height=250)
        sp.pack(side="left", padx=(0, 14))
        sp.pack_propagate(False)
        ctk.CTkLabel(sp, text="PC SCORE", font=font(12, True), text_color=MUTED).pack(pady=(18, 0))
        self.score_lbl = ctk.CTkLabel(sp, text="--", font=font(72, True))
        self.score_lbl.pack()
        self.grade_lbl = ctk.CTkLabel(sp, text="Run a scan to get your score", font=font(15, True), text_color=MUTED)
        self.grade_lbl.pack()
        self.delta_lbl = ctk.CTkLabel(sp, text="", font=font(12), text_color=MUTED)
        self.delta_lbl.pack(pady=(4, 0))
        # actions panel
        ap = ctk.CTkFrame(row, fg_color=PANEL, corner_radius=14, height=250)
        ap.pack(side="left", fill="x", expand=True)
        ap.pack_propagate(False)
        self.scan_btn = ctk.CTkButton(ap, text="🔍  RUN FULL SCAN", height=56, font=font(18, True),
                                      fg_color=ACCENT, hover_color=ACCENT_HOVER, command=self.app.start_scan)
        self.scan_btn.pack(fill="x", padx=22, pady=(22, 10))
        self.prog = ctk.CTkProgressBar(ap, progress_color=ACCENT)
        self.prog.set(0)
        self.prog.pack(fill="x", padx=22)
        self.status = ctk.CTkLabel(ap, text="Takes about 10-20 seconds.", font=font(12), text_color=MUTED)
        self.status.pack(pady=(6, 6))
        tiles = ctk.CTkFrame(ap, fg_color="transparent")
        tiles.pack(fill="x", padx=16)
        self.tiles = {}
        for key, label in (("bad", "Problems"), ("warn", "To improve"), ("good", "OK")):
            t = ctk.CTkFrame(tiles, fg_color=CARD, corner_radius=10)
            t.pack(side="left", fill="x", expand=True, padx=6)
            n = ctk.CTkLabel(t, text="-", font=font(26, True), text_color=COLORS[key])
            n.pack(pady=(6, 0))
            ctk.CTkLabel(t, text=label, font=font(11), text_color=MUTED).pack(pady=(0, 6))
            self.tiles[key] = n
        # quick fix + issues
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24, pady=(18, 4))
        ctk.CTkLabel(bar, text="Biggest issues", font=font(18, True)).pack(side="left")
        self.qf_btn = button(bar, "⚡ Quick-fix all one-click issues", self.quick_fix, width=260)
        self.qf_btn.pack(side="right")
        button(bar, "See all results", lambda: self.app.show("results"), primary=False).pack(side="right", padx=8)
        self.issues = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.issues.pack(fill="both", expand=True, padx=18, pady=(0, 14))

    def scanning(self, on):
        self.scan_btn.configure(state="disabled" if on else "normal",
                                text="Scanning..." if on else "🔍  RUN FULL SCAN")
        if on:
            self.prog.set(0)

    def set_progress(self, f, t):
        self.prog.set(f)
        self.status.configure(text=t)

    def on_show(self):
        if not self.dirty:
            return
        self.dirty = False
        a = self.app
        clear(self.issues)
        if a.score is None:
            ctk.CTkLabel(self.issues, text="No scan yet. Hit RUN FULL SCAN above.", text_color=MUTED,
                         font=font(14)).pack(pady=30)
            return
        g, color = checks.grade(a.score)
        self.score_lbl.configure(text=str(a.score), text_color=color)
        self.grade_lbl.configure(text=g, text_color=color)
        h = report.history()
        if len(h) >= 2:
            d = h[-1]["score"] - h[-2]["score"]
            self.delta_lbl.configure(text=f"{'+' if d >= 0 else ''}{d} since last scan ({h[-2]['time']})")
        else:
            self.delta_lbl.configure(text=f"Scanned {a.last_scan}")
        for k, lbl in self.tiles.items():
            lbl.configure(text=str(sum(r.status == k for r in a.results)))
        self.status.configure(text=f"Last scan: {a.last_scan}")
        top = [r for r in checks.ordered(a.results) if r.status in ("bad", "warn")][:8]
        if not top:
            ctk.CTkLabel(self.issues, text="🎉 Nothing to fix - your PC is tuned.", font=font(16, True),
                         text_color=COLORS["good"]).pack(pady=30)
        for r in top:
            result_card(self.issues, r, a, compact=True)

    def quick_fix(self):
        a = self.app
        todo = [r for r in a.results if r.status in ("bad", "warn") and r.fix and
                (r.fix.startswith("tweak:") or (r.fix.startswith("display:") and r.id.startswith("hz")))]
        if not todo:
            self.app.toast("Nothing left that can be fixed with one click", "info")
            return
        lines = "\n".join("• " + r.title for r in todo)
        if not mb.askyesno(APP_NAME, f"RigTune will fix:\n\n{lines}\n\nEverything can be undone in Optimize/Tools. Go?"):
            return
        need_admin = [r for r in todo if r.fix.startswith("tweak:") and tweaks.BY_ID[r.fix[6:]].admin]
        fixed, failed = 0, []
        for r in todo:
            if r in need_admin and not is_admin():
                failed.append(r.title + " (needs admin)")
                continue
            if r.fix.startswith("tweak:"):
                ok, msg = tweaks.apply(r.fix[6:])
            else:
                src, w, h, hz = r.fix[8:].split("|")
                ok, msg = display.set_mode(src, int(w), int(h), int(hz))
            if ok:
                r.status, r.summary, r.fix = "good", "Fixed by RigTune ✔ (re-scan to confirm)", None
                fixed += 1
            else:
                failed.append(f"{r.title}: {msg}")
        a.recompute()
        msg = f"Fixed {fixed} thing(s)."
        if failed:
            msg += "\n\nNot fixed:\n" + "\n".join(failed)
        if any(r.fix is None and r.id == "hags" for r in todo):
            msg += "\n\nSome changes need a PC restart."
        mb.showinfo(APP_NAME, msg)


# =========================================================================== results
class ResultsPage(Page):
    def build(self):
        header(self, "Scan results", "Every check, grouped by category. Problems first.")
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24)
        self.filter = ctk.CTkSegmentedButton(bar, values=["Problems", "All", "Passed"],
                                             command=lambda _v: self._render(), selected_color=ACCENT,
                                             selected_hover_color=ACCENT_HOVER)
        self.filter.set("Problems")
        self.filter.pack(side="left")
        button(bar, "Re-scan", self.app.start_scan, primary=False).pack(side="right")
        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list.pack(fill="both", expand=True, padx=18, pady=12)

    def on_show(self):
        if self.dirty:
            self.dirty = False
            self._render()

    def _render(self):
        clear(self.list)
        res = self.app.results
        if not res:
            ctk.CTkLabel(self.list, text="No scan yet - go to the Dashboard and run one.", text_color=MUTED,
                         font=font(14)).pack(pady=30)
            return
        f = self.filter.get()
        if f == "Problems":
            res = [r for r in res if r.status in ("bad", "warn", "info")]
        elif f == "Passed":
            res = [r for r in res if r.status == "good"]
        cats = []
        for r in res:
            if r.category not in cats:
                cats.append(r.category)
        rank = {"bad": 0, "warn": 1, "info": 2, "good": 3, "skip": 4}
        cats.sort(key=lambda c: min(rank[r.status] for r in res if r.category == c))
        for c in cats:
            ctk.CTkLabel(self.list, text=c, font=font(17, True), anchor="w").pack(fill="x", padx=8, pady=(14, 2))
            for r in checks.ordered([r for r in res if r.category == c]):
                result_card(self.list, r, self.app)
        if not res:
            ctk.CTkLabel(self.list, text="Nothing here 👍", text_color=MUTED, font=font(14)).pack(pady=30)


# =========================================================================== optimize
class OptimizePage(Page):
    def build(self):
        header(self, "Optimize", "One-click tweaks. Every change is backed up first and can be undone. "
                                 "Only stuff that actually does something - no placebo registry hacks.")
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24)
        button(bar, "⚡ Apply all recommended", self.apply_recommended, width=220).pack(side="left")
        button(bar, "↩ Undo everything", self.undo_all, primary=False, width=170).pack(side="left", padx=8)
        button(bar, "🛟 Create restore point", self.restore_point, primary=False, width=190).pack(side="left")
        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list.pack(fill="both", expand=True, padx=18, pady=12)

    def on_show(self):
        self._render()

    def _render(self):
        clear(self.list)
        cats = []
        for t in tweaks.TWEAKS:
            if t.category not in cats:
                cats.append(t.category)
        for c in cats:
            ctk.CTkLabel(self.list, text=c, font=font(17, True), anchor="w").pack(fill="x", padx=8, pady=(14, 2))
            for t in [t for t in tweaks.TWEAKS if t.category == c]:
                self._row(t)

    def _row(self, t):
        applied = tweaks.safe_applied(t)
        row = ctk.CTkFrame(self.list, fg_color=CARD, corner_radius=10)
        row.pack(fill="x", padx=6, pady=4)
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True, padx=14, pady=10)
        top = ctk.CTkFrame(left, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=t.name, font=font(14, True), anchor="w").pack(side="left")
        tags = []
        if t.recommended:
            tags.append(("Recommended", ACCENT))
        if t.admin:
            tags.append(("Admin", "#f59e0b"))
        if t.reboot:
            tags.append(("Restart needed", "#3b82f6"))
        for txt, col in tags:
            ctk.CTkLabel(top, text=f" {txt} ", fg_color=col, text_color="#000", corner_radius=6,
                         font=font(10, True)).pack(side="left", padx=4)
        ctk.CTkLabel(left, text=t.desc, font=font(12), text_color="#c7cbd6", anchor="w", justify="left",
                     wraplength=720).pack(fill="x", pady=(3, 0))
        right = ctk.CTkFrame(row, fg_color="transparent")
        right.pack(side="right", padx=14)
        ctk.CTkLabel(right, text="● Applied" if applied else "○ Not applied", font=font(12, True),
                     text_color=COLORS["good"] if applied else MUTED).pack()
        if applied and tweaks.has_backup(t.id if not isinstance(t, tweaks.PowerPlanTweak) else "power_plan"):
            button(right, "Undo", lambda: self._do(tweaks.revert, t), primary=False, width=110).pack(pady=4)
        elif not applied:
            button(right, "Apply", lambda: self._do(tweaks.apply, t), width=110).pack(pady=4)

    def _do(self, fn, t):
        if t.admin and not is_admin():
            if mb.askyesno(APP_NAME, f"'{t.name}' needs admin.\n\nRestart RigTune as admin?"):
                self.app._elevate()
            return
        ok, msg = fn(t.id)
        self.app.toast(msg, "good" if ok else "bad")
        self._render()

    def apply_recommended(self):
        todo = [t for t in tweaks.TWEAKS if t.recommended and not tweaks.safe_applied(t)]
        # skip High Performance on dual-CCD X3D CPUs and laptops
        info = self.app.info or {}
        cpu = info.get("cpu", {}).get("Name", "") if info else ""
        if ("X3D" in cpu and any(x in cpu for x in ("7950", "7900", "9950", "9900"))) or (info and sysinfo.is_laptop(info)):
            todo = [t for t in todo if t.id != "power_high"]
        if not todo:
            self.app.toast("All recommended tweaks are already applied ✔")
            return
        if not mb.askyesno(APP_NAME, "Apply these?\n\n" + "\n".join("• " + t.name for t in todo)):
            return
        done, failed = 0, []
        for t in todo:
            ok, msg = tweaks.apply(t.id)
            if ok:
                done += 1
            else:
                failed.append(f"{t.name}: {msg}")
        text = f"Applied {done} tweak(s)."
        if failed:
            text += "\n\nSkipped:\n" + "\n".join(failed)
        if any(t.reboot for t in todo):
            text += "\n\nRestart your PC for everything to kick in."
        mb.showinfo(APP_NAME, text)
        self._render()

    def undo_all(self):
        if not mb.askyesno(APP_NAME, "Put every setting RigTune changed back to how it was?"):
            return
        res = tweaks.undo_all()
        self.app.toast(f"Undid {sum(1 for _, ok, _ in res if ok)} change(s)" if res else "Nothing to undo", "good")
        self._render()

    def restore_point(self):
        self.app.toast("Creating restore point... (can take a minute)", "info")
        self.app.bg(tweaks.create_restore_point, lambda r: mb.showinfo(APP_NAME, r[1]))


# =========================================================================== boost
class BoostPage(Page):
    def build(self):
        header(self, "Game Boost", "Close background apps before you play, then bring them all back with one "
                                   "click after. Heavy apps are pre-ticked. System and anti-cheat processes "
                                   "are protected and never shown.")
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24)
        self.boost_btn = ctk.CTkButton(bar, text="🚀  BOOST", width=180, height=46, font=font(18, True),
                                       fg_color="#16a34a", hover_color="#15803d", command=self.do_boost)
        self.boost_btn.pack(side="left")
        button(bar, "↩ Restore apps", self.do_restore, primary=False, width=150).pack(side="left", padx=8)
        button(bar, "⟳ Refresh list", self.refresh, primary=False, width=130).pack(side="left")
        self.power_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(bar, text="Switch to High Performance while boosted", variable=self.power_var,
                        fg_color=ACCENT).pack(side="left", padx=16)
        self.info_lbl = ctk.CTkLabel(self, text="", font=font(12), text_color=MUTED, anchor="w")
        self.info_lbl.pack(fill="x", padx=24, pady=(6, 0))
        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list.pack(fill="both", expand=True, padx=18, pady=8)
        pr = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        pr.pack(fill="x", padx=24, pady=(0, 16))
        ctk.CTkLabel(pr, text="Set a running game to high priority:", font=font(13, True)).pack(side="left", padx=12, pady=10)
        self.prio_proc = ctk.CTkOptionMenu(pr, values=["(refresh list)"], width=260, fg_color="#2a2f3f",
                                           button_color="#353b4f")
        self.prio_proc.pack(side="left", padx=6)
        self.prio_lvl = ctk.CTkOptionMenu(pr, values=list(boost.PRIORITIES), width=140, fg_color="#2a2f3f",
                                          button_color="#353b4f")
        self.prio_lvl.pack(side="left", padx=6)
        button(pr, "Set", self.set_prio, width=80).pack(side="left", padx=6)
        ctk.CTkLabel(pr, text="(resets when the game closes)", font=font(11), text_color=MUTED).pack(side="left", padx=6)
        self.groups = []
        self.vars = []

    def on_show(self):
        if not self.groups:
            self.refresh()

    def refresh(self):
        self.info_lbl.configure(text="Loading processes...")
        self.app.bg(boost.list_processes, self._fill)

    def _fill(self, groups):
        self.groups = groups
        clear(self.list)
        self.vars = []
        for g in groups:
            v = ctk.BooleanVar(value=g["bloat"])
            self.vars.append(v)
            row = ctk.CTkFrame(self.list, fg_color=CARD, corner_radius=8)
            row.pack(fill="x", padx=6, pady=2)
            ctk.CTkCheckBox(row, text=g["name"], variable=v, font=font(13), fg_color=ACCENT,
                            width=360).pack(side="left", padx=10, pady=6)
            ctk.CTkLabel(row, text=cleanup.human(g["mem"]), font=font(12, True), width=90).pack(side="left")
            if len(g["pids"]) > 1:
                ctk.CTkLabel(row, text=f"{len(g['pids'])} processes", font=font(11), text_color=MUTED).pack(side="left", padx=8)
            if g["bloat"]:
                ctk.CTkLabel(row, text=" heavy background app ", fg_color=COLORS["warn"], text_color="#000",
                             corner_radius=6, font=font(10, True)).pack(side="left", padx=8)
        names = [g["name"] for g in groups] or ["(none)"]
        self.prio_proc.configure(values=names)
        self.prio_proc.set(names[0])
        total = sum(g["mem"] for g in groups)
        pre = sum(1 for g in groups if g["bloat"])
        state = "  |  ⚠ A boost is active - hit Restore when you're done gaming" if boost.has_session() else ""
        self.info_lbl.configure(text=f"{len(groups)} apps using {cleanup.human(total)} RAM. "
                                     f"{pre} heavy ones pre-selected.{state}")

    def do_boost(self):
        sel = [g for g, v in zip(self.groups, self.vars) if v.get()]
        if not sel:
            self.app.toast("Tick at least one app to close", "warn")
            return
        if not mb.askyesno(APP_NAME, f"Close {len(sel)} app(s)?\n\nSave anything open in them first. "
                                     "'Restore apps' will start them again."):
            return

        def done(res):
            killed, failed, freed = res
            self.app.toast(f"Boosted! Closed {len(killed)} app(s), freed ~{cleanup.human(freed)}")
            self.refresh()
        self.app.bg(lambda: boost.boost(sel, self.power_var.get()), done)

    def do_restore(self):
        def done(started):
            self.app.toast(f"Restored {len(started)} app(s)" if started else "Nothing to restore", "good")
            self.refresh()
        self.app.bg(boost.restore, done)

    def set_prio(self):
        name = self.prio_proc.get()
        g = next((g for g in self.groups if g["name"] == name), None)
        if not g:
            return
        n = boost.set_priority(g, self.prio_lvl.get())
        self.app.toast(f"{name} set to {self.prio_lvl.get()} priority" if n else
                       "Couldn't change priority (try running as admin)", "good" if n else "bad")


# =========================================================================== startup
class StartupPage(Page):
    def build(self):
        header(self, "Startup apps", "Everything that launches when Windows starts. Turning one off doesn't "
                                     "uninstall it - it just stops it auto-starting (same as Task Manager).")
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24)
        button(bar, "⟳ Refresh", self.refresh, primary=False).pack(side="left")
        button(bar, "Turn off all heavy ones", self.off_heavy, width=200).pack(side="left", padx=8)
        self.lbl = ctk.CTkLabel(bar, text="", text_color=MUTED, font=font(12))
        self.lbl.pack(side="left", padx=10)
        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list.pack(fill="both", expand=True, padx=18, pady=12)
        self.entries = []

    def on_show(self):
        self.refresh()

    def refresh(self):
        self.app.bg(startup.list_entries, self._fill)

    def _fill(self, entries):
        self.entries = entries
        clear(self.list)
        if not entries:
            ctk.CTkLabel(self.list, text="No startup entries found.", text_color=MUTED).pack(pady=30)
        for e in sorted(entries, key=lambda e: (not e["heavy"], e["name"].lower())):
            row = ctk.CTkFrame(self.list, fg_color=CARD, corner_radius=8)
            row.pack(fill="x", padx=6, pady=3)
            sw = ctk.CTkSwitch(row, text="", width=50, progress_color=ACCENT,
                               command=lambda e=e: None)
            sw.pack(side="left", padx=12)
            if e["enabled"]:
                sw.select()
            sw.configure(command=lambda e=e, sw=sw: self.toggle(e, sw))
            mid = ctk.CTkFrame(row, fg_color="transparent")
            mid.pack(side="left", fill="x", expand=True, pady=6)
            t = ctk.CTkFrame(mid, fg_color="transparent")
            t.pack(fill="x")
            ctk.CTkLabel(t, text=e["name"], font=font(13, True), anchor="w").pack(side="left")
            if e["heavy"]:
                ctk.CTkLabel(t, text=" often heavy ", fg_color=COLORS["warn"], text_color="#000", corner_radius=6,
                             font=font(10, True)).pack(side="left", padx=6)
            if e["admin"]:
                ctk.CTkLabel(t, text=" all users (admin) ", fg_color="#374151", corner_radius=6,
                             font=font(10)).pack(side="left", padx=2)
            cmd = e["command"] if len(e["command"]) < 110 else e["command"][:107] + "..."
            ctk.CTkLabel(mid, text=f"{e['location']}  •  {cmd}", font=font(11), text_color=MUTED,
                         anchor="w").pack(fill="x")
        on = sum(1 for e in entries if e["enabled"])
        self.lbl.configure(text=f"{on} of {len(entries)} enabled")

    def toggle(self, e, sw):
        want = bool(sw.get())
        ok, msg = startup.set_enabled(e, want)
        if not ok:
            sw.toggle()
        self.app.toast(msg, "good" if ok else "bad")

    def off_heavy(self):
        heavy = [e for e in self.entries if e["heavy"] and e["enabled"]]
        if not heavy:
            self.app.toast("No heavy startup apps enabled ✔")
            return
        if not mb.askyesno(APP_NAME, "Stop these from auto-starting?\n\n" + "\n".join("• " + e["name"] for e in heavy)
                           + "\n\n(Keep anything you need for your mouse/headset software!)"):
            return
        n = sum(1 for e in heavy if startup.set_enabled(e, False)[0])
        self.app.toast(f"Disabled {n} startup app(s)")
        self.refresh()


# =========================================================================== cleanup
class CleanupPage(Page):
    def build(self):
        header(self, "Cleanup", "Clear junk that piles up. Files that are in use get skipped automatically. "
                                "Shader caches are off by default - only clear them if games stutter or glitch "
                                "after a driver update.")
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24)
        button(bar, "🔍 Scan sizes", self.scan).pack(side="left")
        button(bar, "🧹 Clean selected", self.clean, width=170).pack(side="left", padx=8)
        self.lbl = ctk.CTkLabel(bar, text="", text_color=MUTED, font=font(12))
        self.lbl.pack(side="left", padx=10)
        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list.pack(fill="both", expand=True, padx=18, pady=12)
        self.items = []

    def on_show(self):
        if not self.items:
            self.scan()

    def scan(self):
        self.lbl.configure(text="Measuring...")
        self.app.bg(cleanup.scan, self._fill)

    def _fill(self, items):
        clear(self.list)
        self.items = []
        for it in items:
            v = ctk.BooleanVar(value=it["default"] and it["size"] > 0)
            self.items.append((it, v))
            row = ctk.CTkFrame(self.list, fg_color=CARD, corner_radius=8)
            row.pack(fill="x", padx=6, pady=3)
            ctk.CTkCheckBox(row, text=it["name"], variable=v, font=font(13, True), fg_color=ACCENT,
                            width=320).pack(side="left", padx=10, pady=8)
            ctk.CTkLabel(row, text=cleanup.human(it["size"]), font=font(13, True), width=90).pack(side="left")
            ctk.CTkLabel(row, text=it["note"], font=font(11), text_color=MUTED, anchor="w", justify="left",
                         wraplength=520).pack(side="left", padx=10, fill="x", expand=True)
        total = sum(i["size"] for i in items)
        self.lbl.configure(text=f"{cleanup.human(total)} found in total")

    def clean(self):
        sel = [it for it, v in self.items if v.get()]
        if not sel:
            self.app.toast("Nothing selected", "warn")
            return
        if not mb.askyesno(APP_NAME, "Delete:\n\n" + "\n".join(f"• {i['name']} ({cleanup.human(i['size'])})" for i in sel)):
            return
        self.lbl.configure(text="Cleaning...")

        def work():
            return sum(cleanup.clean(i) for i in sel)

        def done(freed):
            self.app.toast(f"Freed {cleanup.human(freed)} 🧹")
            self.scan()
        self.app.bg(work, done)


# =========================================================================== network
class NetworkPage(Page):
    def build(self):
        header(self, "Network test", "Tests ping, jitter (how stable your ping is) and packet loss. "
                                     "For a fair result, stop downloads/streams first.")
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24)
        ctk.CTkLabel(bar, text="Extra host (e.g. a game server IP):", font=font(12)).pack(side="left")
        self.host = ctk.CTkEntry(bar, width=200, placeholder_text="optional")
        self.host.pack(side="left", padx=8)
        self.count = ctk.CTkOptionMenu(bar, values=["30 pings", "60 pings", "100 pings"], width=110,
                                       fg_color="#2a2f3f", button_color="#353b4f")
        self.count.pack(side="left", padx=6)
        self.btn = button(bar, "▶ Run test", self.run_test)
        self.btn.pack(side="left", padx=8)
        self.prog = ctk.CTkProgressBar(self, progress_color=ACCENT)
        self.prog.set(0)
        self.prog.pack(fill="x", padx=24, pady=10)
        self.adapter = ctk.CTkLabel(self, text="", font=font(12), text_color=MUTED, anchor="w")
        self.adapter.pack(fill="x", padx=24)
        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list.pack(fill="both", expand=True, padx=18, pady=8)

    def on_show(self):
        n = (self.app.info or {}).get("net")
        if n:
            self.adapter.configure(text=f"Connection: {n.get('Name')} - {n.get('Desc')} ({n.get('Speed')})")

    def run_test(self):
        targets = list(network.DEFAULT_TARGETS)
        h = self.host.get().strip()
        if h:
            targets.append(("Your host", h))
        count = int(self.count.get().split()[0])
        self.btn.configure(state="disabled")
        clear(self.list)
        self.prog.set(0)
        total = count * len(targets)

        def work():
            res = []
            for i, (label, host) in enumerate(targets):
                r = network.ping(host, count, progress=lambda d, _n, i=i: self.app.call(self.prog.set, (i * count + d) / total))
                r["label"] = label
                res.append(r)
            return res
        self.app.bg(work, self._show)

    def _show(self, results):
        self.btn.configure(state="normal")
        self.prog.set(1)
        for r in results:
            st, note = network.verdict(r)
            card = ctk.CTkFrame(self.list, fg_color=CARD, corner_radius=10, border_width=2, border_color=COLORS[st])
            card.pack(fill="x", padx=6, pady=5)
            ctk.CTkLabel(card, text=f"{r['label']}  ({r['host']})", font=font(15, True), anchor="w").pack(fill="x", padx=14, pady=(10, 2))
            if "avg" in r:
                stats = ctk.CTkFrame(card, fg_color="transparent")
                stats.pack(fill="x", padx=10)
                for k, v in (("Ping", f"{r['avg']:.0f} ms"), ("Jitter", f"{r['jitter']:.1f} ms"),
                             ("Loss", f"{r['loss']:.0f}%"), ("Min / Max", f"{r['min']:.0f} / {r['max']:.0f} ms")):
                    t = ctk.CTkFrame(stats, fg_color=PANEL, corner_radius=8)
                    t.pack(side="left", padx=4, pady=4, fill="x", expand=True)
                    ctk.CTkLabel(t, text=v, font=font(18, True)).pack(pady=(6, 0))
                    ctk.CTkLabel(t, text=k, font=font(11), text_color=MUTED).pack(pady=(0, 6))
            ctk.CTkLabel(card, text=note, font=font(12), anchor="w", justify="left", wraplength=860,
                         text_color=COLORS[st]).pack(fill="x", padx=14, pady=(4, 10))


# =========================================================================== system
class SystemPage(Page):
    def build(self):
        header(self, "System info", "What RigTune detected about your PC.")
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24)
        button(bar, "⟳ Refresh", self.refresh, primary=False).pack(side="left")
        button(bar, "Copy to clipboard", self.copy, primary=False, width=160).pack(side="left", padx=8)
        self.box = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Consolas", size=13), fg_color=PANEL)
        self.box.pack(fill="both", expand=True, padx=24, pady=12)

    def on_show(self):
        if self.app.info:
            self._fill(self.app.info)
        else:
            self.refresh()

    def refresh(self):
        self._set("Reading hardware...")
        self.app.bg(lambda: sysinfo.collect(force=True), self._got)

    def _got(self, info):
        self.app.info = info
        self._fill(info)

    def _fill(self, info):
        lines = sysinfo.summary_lines(info)
        mons = display.list_monitors()
        for i, m in enumerate(mons, 1):
            lines.append(f"Monitor {i}:   {m['name']} - {m['width']}x{m['height']} @ {m['hz']}Hz "
                         f"(max {m['max_hz_native']}Hz at {m['native_width']}x{m['native_height']}) on {m['adapter']}")
        self._set("\n".join(lines))

    def _set(self, text):
        self.box.configure(state="normal")
        self.box.delete("1.0", "end")
        self.box.insert("1.0", text)
        self.box.configure(state="disabled")

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.box.get("1.0", "end"))
        self.app.toast("Copied")


# =========================================================================== tools
class ToolsPage(Page):
    def build(self):
        header(self, "Tools & history")
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(fill="x", padx=24)
        tools = [
            ("🛟 Create restore point", self.restore_point),
            ("🖥 Restart into BIOS", self.app.restart_bios),
            ("📄 Export HTML report", self.export),
            ("↩ Undo all RigTune changes", self.undo_all),
        ]
        for i, (t, cmd) in enumerate(tools):
            button(grid, t, cmd, width=250, height=44).grid(row=0, column=i, padx=6, pady=6, sticky="ew")
        ctk.CTkLabel(self, text="Windows shortcuts", font=font(17, True), anchor="w").pack(fill="x", padx=24, pady=(18, 4))
        sc = ctk.CTkFrame(self, fg_color="transparent")
        sc.pack(fill="x", padx=24)
        shortcuts = [("Display", "ms-settings:display"), ("Graphics (per-app GPU)", "ms-settings:display-advancedgraphics"),
                     ("Game Mode", "ms-settings:gaming-gamemode"), ("Startup apps", "ms-settings:startupapps"),
                     ("Power", "ms-settings:powersleep"), ("Mouse", "ms-settings:mousetouchpad"),
                     ("Windows Update", "ms-settings:windowsupdate"), ("Core isolation", "windowsdefender://coreisolation"),
                     ("Storage", "ms-settings:storagesense"), ("Sound", "ms-settings:sound")]
        for i, (t, url) in enumerate(shortcuts):
            button(sc, t, lambda u=url: open_url(u), primary=False, width=200).grid(row=i // 5, column=i % 5, padx=5, pady=5)
        ctk.CTkLabel(self, text="Score history", font=font(17, True), anchor="w").pack(fill="x", padx=24, pady=(18, 4))
        self.hist = ctk.CTkScrollableFrame(self, fg_color="transparent", height=250)
        self.hist.pack(fill="both", expand=True, padx=18, pady=(0, 16))

    def on_show(self):
        clear(self.hist)
        h = report.history()
        if not h:
            ctk.CTkLabel(self.hist, text="No scans yet.", text_color=MUTED).pack(pady=20)
        for e in reversed(h):
            g, color = checks.grade(e["score"])
            row = ctk.CTkFrame(self.hist, fg_color=CARD, corner_radius=8)
            row.pack(fill="x", padx=6, pady=2)
            ctk.CTkLabel(row, text=e["time"], font=font(12), width=150, anchor="w").pack(side="left", padx=12, pady=6)
            ctk.CTkLabel(row, text=f"{e['score']}/100", font=font(14, True), text_color=color, width=80).pack(side="left")
            # bar
            barf = ctk.CTkProgressBar(row, width=300, progress_color=color)
            barf.set(e["score"] / 100)
            barf.pack(side="left", padx=10)
            ctk.CTkLabel(row, text=f"{e['bad']} problems, {e['warn']} to improve", font=font(11),
                         text_color=MUTED).pack(side="left", padx=10)

    def restore_point(self):
        if not is_admin():
            self.app.toast("Needs admin - use 'Restart as admin'", "warn")
            return
        self.app.toast("Creating restore point... (can take a minute)", "info")
        self.app.bg(tweaks.create_restore_point, lambda r: mb.showinfo(APP_NAME, r[1]))

    def export(self):
        if not self.app.results:
            self.app.toast("Run a scan first", "warn")
            return
        path = report.export_html(self.app.info, self.app.results, self.app.score)
        open_url(path)
        self.app.toast("Report saved to Documents")

    def undo_all(self):
        if not mb.askyesno(APP_NAME, "Put every setting RigTune changed back to how it was?"):
            return
        res = tweaks.undo_all()
        self.app.toast(f"Undid {sum(1 for _, ok, _ in res if ok)} change(s)" if res else "Nothing to undo")

# =========================================================================== dialogs
def choose(app, title, text, options, danger=None):
    """Small modal with custom buttons. Returns the chosen option or None."""
    win = ctk.CTkToplevel(app)
    win.title(title)
    win.configure(fg_color=PANEL)
    win.resizable(False, False)
    win.transient(app)
    res = {"v": None}
    ctk.CTkLabel(win, text=text, font=font(13), justify="left", anchor="w", wraplength=520).pack(
        fill="x", padx=22, pady=(20, 14))
    row = ctk.CTkFrame(win, fg_color="transparent")
    row.pack(fill="x", padx=18, pady=(0, 18))
    for opt in options:
        def pick(o=opt):
            res["v"] = o
            win.destroy()
        b = button(row, opt, pick, primary=(opt == options[0]), width=170)
        if opt == danger:
            b.configure(fg_color="#7f1d1d", hover_color="#991b1b")
        b.pack(side="left", padx=4)
    button(row, "Cancel", win.destroy, primary=False, width=90).pack(side="right", padx=4)
    win.update_idletasks()
    x = app.winfo_rootx() + (app.winfo_width() - win.winfo_width()) // 2
    y = app.winfo_rooty() + (app.winfo_height() - win.winfo_height()) // 3
    win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    win.after(50, win.grab_set)
    app.wait_window(win)
    return res["v"]


SAFETY_COLORS = {"green": "#22c55e", "yellow": "#f59e0b", "red": "#ef4444"}


# =========================================================================== storage
class StoragePage(Page):
    MAX_ROWS = 120

    def build(self):
        header(self, "Storage", "Find what's eating your space. Green = safe, yellow = check first, "
                                "red = part of Windows (RigTune won't let you delete it). "
                                "Deleting goes to the Recycle Bin unless you pick 'Delete forever'.")
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24)
        self.drive_menu = ctk.CTkOptionMenu(bar, values=["Loading drives..."], width=300,
                                            fg_color="#2a2f3f", button_color="#353b4f")
        self.drive_menu.pack(side="left")
        self.scan_btn = button(bar, "🔍 Scan drive", self.scan)
        self.scan_btn.pack(side="left", padx=8)
        self.stop_btn = button(bar, "■ Stop", self.stop, primary=False, width=80)
        self.status = ctk.CTkLabel(bar, text="", text_color=MUTED, font=font(12), anchor="w")
        self.status.pack(side="left", padx=10, fill="x", expand=True)
        self.prog = ctk.CTkProgressBar(self, progress_color=ACCENT, mode="indeterminate")
        self.wins = ctk.CTkFrame(self, fg_color="transparent", height=1)
        self.wins.pack(fill="x", padx=24, pady=(8, 0))
        self.tabs = ctk.CTkTabview(self, fg_color=PANEL, segmented_button_selected_color=ACCENT,
                                   segmented_button_selected_hover_color=ACCENT_HOVER,
                                   command=self._tab_changed)
        self.tabs.pack(fill="both", expand=True, padx=18, pady=(6, 14))
        self.tab_names = ["📁 Folders", "📄 Biggest files", "📊 Categories", "🎮 Games", "🕸 Old files",
                          "👯 Duplicates"]
        self.frames = {}
        for t in self.tab_names:
            tab = self.tabs.add(t)
            top = ctk.CTkFrame(tab, fg_color="transparent")
            top.pack(fill="x")
            body = ctk.CTkScrollableFrame(tab, fg_color="transparent")
            body.pack(fill="both", expand=True)
            self.frames[t] = (top, body)
        self.res = None
        self.cur = None          # current folder Node
        self.cancel = None
        self.drives = []
        self.games = None
        self.dups = None
        self._placeholder()

    def on_show(self):
        if not self.drives:
            self.app.bg(storage.drives, self._got_drives)

    def _got_drives(self, ds):
        self.drives = ds
        if not ds:
            self.drive_menu.configure(values=["No drives found"])
            self.drive_menu.set("No drives found")
            return
        vals = [f"{d['path']}   {storage.human(d['used'])} used of {storage.human(d['total'])}" for d in ds]
        self.drive_menu.configure(values=vals)
        self.drive_menu.set(vals[0])

    def _placeholder(self):
        for t in self.tab_names:
            top, body = self.frames[t]
            clear(top)
            clear(body)
            body._parent_canvas.yview_moveto(0)
            ctk.CTkLabel(body, text="Pick a drive and click Scan.\nA full drive takes about 1-3 minutes.",
                         text_color=MUTED, font=font(14)).pack(pady=60)

    # ---------------------------------------------------------- scan
    def _drive_path(self):
        v = self.drive_menu.get()
        for d in self.drives:
            if v.startswith(d["path"]):
                return d["path"]
        return None

    def scan(self):
        path = self._drive_path()
        if not path:
            self.app.toast("Pick a drive first", "warn")
            return
        import threading
        self.cancel = threading.Event()
        self.scan_btn.configure(state="disabled")
        self.stop_btn.pack(side="left", padx=(0, 8), after=self.scan_btn)
        self.prog.pack(fill="x", padx=24, pady=(8, 0), after=self.scan_btn.master)
        self.prog.start()
        self.status.configure(text="Scanning...")
        self.games = None
        self.dups = None
        cancel = self.cancel

        def prog(files, dirs, cur):
            short = cur if len(cur) < 70 else "..." + cur[-67:]
            self.app.call(lambda: self.status.configure(text=f"{files:,} files, {dirs:,} folders  •  {short}"))

        self.app.bg(lambda: storage.scan(path, prog, cancel), self._scan_done)

    def stop(self):
        if self.cancel:
            self.cancel.set()

    def _scan_done(self, res):
        self.prog.stop()
        self.prog.pack_forget()
        self.stop_btn.pack_forget()
        self.scan_btn.configure(state="normal")
        self.res = res
        self.cur = res.root
        extra = " (stopped early - sizes are partial)" if res.cancelled else ""
        denied = f", {res.denied:,} skipped (no access - run as admin to see more)" if res.denied else ""
        self.status.configure(text=f"{storage.human(res.root.size)} in {res.file_count:,} files, "
                                   f"scanned in {res.seconds:.0f}s{denied}{extra}")
        self._render_wins()
        self._render(self.tabs.get())

    def _tab_changed(self):
        if self.res:
            self._render(self.tabs.get())

    def _render(self, tab):
        {"📁 Folders": self._folders, "📄 Biggest files": self._biggest, "📊 Categories": self._cats,
         "🎮 Games": self._games, "🕸 Old files": self._old, "👯 Duplicates": self._dups}[tab]()

    def _refresh(self):
        self.status.configure(text=f"{storage.human(self.res.root.size)} in {self.res.root.files:,} files")
        self._render(self.tabs.get())

    # ---------------------------------------------------------- quick wins
    def _render_wins(self):
        clear(self.wins)
        wins = storage.quick_wins(self.res)
        if not wins:
            return
        ctk.CTkLabel(self.wins, text="⚡ Quick wins", font=font(15, True), anchor="w").pack(fill="x")
        row = ctk.CTkFrame(self.wins, fg_color="transparent")
        row.pack(fill="x")
        for w in wins:
            c = ctk.CTkFrame(row, fg_color=CARD, corner_radius=10, border_width=1, border_color=COLORS["good"])
            c.pack(side="left", fill="both", expand=True, padx=4, pady=4)
            t = ctk.CTkFrame(c, fg_color="transparent")
            t.pack(fill="x", padx=12, pady=(8, 0))
            ctk.CTkLabel(t, text=w["title"], font=font(13, True), anchor="w").pack(side="left")
            ctk.CTkLabel(t, text=storage.human(w["size"]), font=font(13, True),
                         text_color=COLORS["good"]).pack(side="right")
            ctk.CTkLabel(c, text=w["desc"], font=font(11), text_color=MUTED, wraplength=360, justify="left",
                         anchor="w").pack(fill="x", padx=12)
            button(c, w["label"], lambda w=w: self._do_win(w), width=150).pack(anchor="w", padx=12, pady=8)

    def _do_win(self, w):
        if w.get("admin") and not is_admin():
            if mb.askyesno(APP_NAME, "This needs admin.\n\nRestart RigTune as admin now?"):
                self.app._elevate()
            return
        if w["id"] == "recycle" and not mb.askyesno(APP_NAME, "Empty the Recycle Bin?\n\nThis is permanent."):
            return
        ok, msg = storage.run_quick_win(w["id"])
        self.app.toast(msg, "good" if ok else "bad")
        if ok and w["id"] in ("recycle", "hiber"):
            if w["id"] == "hiber":
                self.res.system_files.pop("hiberfil.sys", None)
            self._render_wins()

    # ---------------------------------------------------------- rows
    def _row(self, body, name, path, size, total, is_dir=False, sub="", on_drill=None, color=None,
             extra_btn=None):
        level, why = storage.safety(path)
        row = ctk.CTkFrame(body, fg_color=CARD, corner_radius=8)
        row.pack(fill="x", padx=4, pady=2)
        ctk.CTkLabel(row, text="●", text_color=SAFETY_COLORS[level], font=font(16), width=18).pack(
            side="left", padx=(10, 2))
        mid = ctk.CTkFrame(row, fg_color="transparent")
        mid.pack(side="left", fill="x", expand=True, padx=6, pady=5)
        label = ("📁 " if is_dir else "📄 ") + name
        if on_drill:
            lb = ctk.CTkButton(mid, text=label, anchor="w", font=font(13, True), fg_color="transparent",
                               hover_color="#2a2f3f", text_color="#e5e7eb", height=24, command=on_drill)
        else:
            lb = ctk.CTkLabel(mid, text=label, anchor="w", font=font(13, True))
        lb.pack(fill="x")
        if sub:
            ctk.CTkLabel(mid, text=sub, anchor="w", font=font(11), text_color=MUTED).pack(fill="x", padx=(4, 0))
        frac = (size / total) if total else 0
        pb = ctk.CTkProgressBar(row, width=160, progress_color=color or ACCENT)
        pb.set(min(frac, 1))
        pb.pack(side="left", padx=6)
        ctk.CTkLabel(row, text=storage.human(size), font=font(13, True), width=80, anchor="e").pack(side="left")
        ctk.CTkLabel(row, text=f"{frac * 100:.1f}%", font=font(11), text_color=MUTED, width=50).pack(side="left")
        button(row, "📂", lambda: self._open(path, is_dir), primary=False, width=36).pack(side="left", padx=(6, 2))
        if extra_btn:
            button(row, extra_btn[0], extra_btn[1], primary=False, width=90).pack(side="left", padx=2)
        if level != "red":
            button(row, "🗑", lambda: self._delete(path, size, level, why), primary=False, width=36).pack(
                side="left", padx=(2, 10))
        else:
            ctk.CTkLabel(row, text="🔒", width=36).pack(side="left", padx=(2, 10))
        return row

    def _open(self, path, is_dir):
        if not IS_WINDOWS:
            return
        import subprocess
        if is_dir:
            subprocess.Popen(["explorer", path])
        else:
            subprocess.Popen(["explorer", "/select,", path])

    def _delete(self, path, size, level, why):
        name = os.path.basename(path.rstrip("\\/")) or path
        warn = "\n\n⚠ " + why if level == "yellow" else ""
        pick = choose(self.app, "Delete", f"Delete '{name}' ({storage.human(size)})?\n\n{path}{warn}",
                      ["Recycle Bin", "Delete forever"], danger="Delete forever")
        if not pick:
            return
        ok, msg = storage.delete(path, permanent=(pick == "Delete forever"))
        self.app.toast(msg, "good" if ok else "bad")
        if ok:
            storage.forget(self.res, path, size)
            if self.dups:
                for g in self.dups:
                    g["paths"] = [p for p in g["paths"] if p != path]
                self.dups = [g for g in self.dups if len(g["paths"]) > 1]
            if self.games:
                self.games = [g for g in self.games if os.path.normcase(g["path"]) != os.path.normcase(path)]
            self._refresh()

    def _more(self, body, n):
        if n > self.MAX_ROWS:
            ctk.CTkLabel(body, text=f"+ {n - self.MAX_ROWS} smaller items not shown", text_color=MUTED,
                         font=font(11)).pack(pady=6)

    # ---------------------------------------------------------- tabs
    def _folders(self):
        top, body = self.frames["📁 Folders"]
        clear(top)
        clear(body)
        body._parent_canvas.yview_moveto(0)
        node = self.cur or self.res.root
        if node.parent is not None:
            button(top, "⬆ Up", lambda: self._go(node.parent), primary=False, width=70).pack(side="left", padx=4)
        ctk.CTkLabel(top, text=f"{node.path}   •   {storage.human(node.size)}, {node.files:,} files",
                     font=font(13, True), anchor="w").pack(side="left", padx=8, pady=4)
        items = [(c.size, True, c) for c in node.children]
        items += [(s, False, p) for s, p, _m in storage.folder_files(node.path)]
        items.sort(key=lambda x: x[0], reverse=True)
        total = node.size or 1
        for size, is_dir, obj in items[:self.MAX_ROWS]:
            if is_dir:
                self._row(body, obj.name, obj.path, size, total, True,
                          sub=f"{obj.files:,} files  •  {storage.CATEGORIES[obj.cat][0]}",
                          on_drill=lambda c=obj: self._go(c), color=storage.CATEGORIES[obj.cat][1])
            else:
                self._row(body, os.path.basename(obj), obj, size, total)
        if not items:
            ctk.CTkLabel(body, text="Empty folder.", text_color=MUTED).pack(pady=30)
        self._more(body, len(items))

    def _go(self, node):
        self.cur = node
        self._folders()

    def _biggest(self):
        top, body = self.frames["📄 Biggest files"]
        clear(top)
        clear(body)
        body._parent_canvas.yview_moveto(0)
        ctk.CTkLabel(top, text="The biggest single files on this drive.", text_color=MUTED,
                     font=font(12)).pack(side="left", padx=6, pady=4)
        total = self.res.root.size or 1
        files = self.res.biggest(self.MAX_ROWS)
        for size, path, mtime, used in files:
            self._row(body, os.path.basename(path), path, size, total,
                      sub=f"{os.path.dirname(path)}  •  last used {storage.ago(used)}")

    def _cats(self):
        top, body = self.frames["📊 Categories"]
        clear(top)
        clear(body)
        body._parent_canvas.yview_moveto(0)
        ctk.CTkLabel(top, text="Where your space goes, by type.", text_color=MUTED,
                     font=font(12)).pack(side="left", padx=6, pady=4)
        cats = sorted(self.res.cats.items(), key=lambda x: x[1], reverse=True)
        total = sum(v for _k, v in cats) or 1
        for k, v in cats:
            if v <= 0:
                continue
            name, color = storage.CATEGORIES[k]
            row = ctk.CTkFrame(body, fg_color=CARD, corner_radius=8)
            row.pack(fill="x", padx=4, pady=3)
            ctk.CTkLabel(row, text=name, font=font(14, True), width=240, anchor="w").pack(side="left", padx=14, pady=10)
            pb = ctk.CTkProgressBar(row, progress_color=color, height=14)
            pb.set(v / total)
            pb.pack(side="left", fill="x", expand=True, padx=8)
            ctk.CTkLabel(row, text=storage.human(v), font=font(14, True), width=90, anchor="e").pack(side="left")
            ctk.CTkLabel(row, text=f"{v / total * 100:.1f}%", font=font(12), text_color=MUTED, width=60).pack(
                side="left", padx=(0, 10))
            if k == "junk":
                button(row, "Clean", lambda: self.app.show("cleanup"), width=80).pack(side="left", padx=(0, 10))
            elif k == "games":
                button(row, "See games", lambda: self.tabs.set("🎮 Games") or self._games(), width=90,
                       primary=False).pack(side="left", padx=(0, 10))

    def _games(self):
        top, body = self.frames["🎮 Games"]
        clear(top)
        clear(body)
        body._parent_canvas.yview_moveto(0)
        if self.games is None:
            ctk.CTkLabel(body, text="Measuring your games...", text_color=MUTED).pack(pady=30)
            res = self.res
            self.app.bg(lambda: storage.games_with_sizes(res), self._got_games)
            self.games = []
            return
        ctk.CTkLabel(top, text="Your installed games. 'Uninstall' goes through the launcher so it stays happy.",
                     text_color=MUTED, font=font(12)).pack(side="left", padx=6, pady=4)
        if not self.games:
            ctk.CTkLabel(body, text="No games found.", text_color=MUTED).pack(pady=30)
            return
        total = sum(g["size"] for g in self.games) or 1
        for g in self.games:
            played = storage.ago(g.get("last_played")) if g.get("last_played") else "unknown"
            sub = f"{g['store']}  •  drive {g.get('drive', '?')}:  •  last played {played}"
            if g.get("last_played") and (time.time() - g["last_played"]) > 90 * 86400:
                sub += "   💤 not played in 3+ months"
            if g["store"] == "Steam" and g.get("appid"):
                act = ("Uninstall", lambda a=g["appid"]: open_url(f"steam://uninstall/{a}"))
            else:
                act = ("Uninstall", lambda: open_url("ms-settings:appsfeatures"))
            self._row(body, g["name"], g["path"], g["size"], total, True, sub=sub,
                      color=storage.CATEGORIES["games"][1], extra_btn=act)

    def _got_games(self, gs):
        self.games = gs
        if self.tabs.get() == "🎮 Games":
            self._games()

    def _old(self):
        top, body = self.frames["🕸 Old files"]
        clear(top)
        clear(body)
        body._parent_canvas.yview_moveto(0)
        ctk.CTkLabel(top, text=f"Files over 100 MB you haven't touched in {storage.OLD_DAYS}+ days "
                               "(games, apps and Windows are left out).", text_color=MUTED,
                     font=font(12)).pack(side="left", padx=6, pady=4)
        files = self.res.old_files
        if not files:
            ctk.CTkLabel(body, text="Nothing old and big found ✔", text_color=MUTED).pack(pady=30)
        total = sum(f[0] for f in files) or 1
        for size, path, used in files[:self.MAX_ROWS]:
            self._row(body, os.path.basename(path), path, size, total,
                      sub=f"{os.path.dirname(path)}  •  last used {storage.ago(used)}")
        self._more(body, len(files))

    def _dups(self):
        top, body = self.frames["👯 Duplicates"]
        clear(top)
        clear(body)
        body._parent_canvas.yview_moveto(0)
        button(top, "🔍 Find duplicates", self._find_dups, width=170).pack(side="left", padx=4, pady=4)
        self.dup_lbl = ctk.CTkLabel(top, text="Compares file contents (not just names). Files over 5 MB.",
                                    text_color=MUTED, font=font(12))
        self.dup_lbl.pack(side="left", padx=8)
        if self.dups is None:
            return
        if not self.dups:
            ctk.CTkLabel(body, text="No duplicates found ✔", text_color=MUTED).pack(pady=30)
            return
        wasted = sum(g["wasted"] for g in self.dups)
        self.dup_lbl.configure(text=f"{len(self.dups)} groups  •  {storage.human(wasted)} wasted. "
                                    "Keep one copy of each, delete the rest.")
        shown = 0
        for g in self.dups:
            if shown > self.MAX_ROWS:
                break
            ctk.CTkLabel(body, text=f"{len(g['paths'])} copies × {storage.human(g['size'])}  →  "
                                    f"{storage.human(g['wasted'])} wasted", font=font(13, True),
                         anchor="w").pack(fill="x", padx=8, pady=(10, 2))
            for p in g["paths"]:
                self._row(body, os.path.basename(p), p, g["size"], g["size"] * len(g["paths"]),
                          sub=os.path.dirname(p))
                shown += 1

    def _find_dups(self):
        import threading
        self.cancel = threading.Event()
        cancel = self.cancel
        res = self.res
        self.dup_lbl.configure(text="Comparing files...")

        def prog(i, n):
            self.app.call(lambda: self.dup_lbl.configure(text=f"Comparing files... {i}/{n}"))

        def done(groups):
            self.dups = groups
            self._dups()
        self.app.bg(lambda: storage.find_duplicates(res, prog, cancel), done)


# =========================================================================== fresh start
class FreshStartPage(Page):
    def build(self):
        header(self, "Fresh Start", "Like resetting your PC, but your games, files and apps stay. Repairs "
                                    "Windows with its own tools, resets the stuff that usually breaks, turns back "
                                    "on services that 'optimizer' tools disabled, and removes bloatware. "
                                    "A restore point is made first so you can roll back.")
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=24)
        self.run_btn = button(bar, "✨ Run Fresh Start", self.start, width=200, height=40)
        self.run_btn.pack(side="left")
        button(bar, "⟳ Refresh lists", self.refresh, primary=False, width=140).pack(side="left", padx=8)
        self.lbl = ctk.CTkLabel(bar, text="", text_color=MUTED, font=font(12))
        self.lbl.pack(side="left", padx=10)
        self.prog = ctk.CTkProgressBar(self, progress_color=ACCENT)
        self.prog.set(0)
        self.prog.pack(fill="x", padx=24, pady=(10, 0))
        self.list = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.list.pack(fill="both", expand=True, padx=18, pady=(8, 4))
        self.log_box = ctk.CTkTextbox(self, height=130, fg_color=PANEL, font=ctk.CTkFont(family="Consolas", size=12))
        self.log_box.pack(fill="x", padx=24, pady=(0, 14))
        self.log_box.configure(state="disabled")
        self.step_vars = {}
        self.svc_vars = []
        self.bloat_vars = []
        self.services = None
        self.bloat = None
        self.running = False
        self._render()

    def on_show(self):
        if self.services is None:
            self.refresh()

    def refresh(self):
        self.lbl.configure(text="Checking services and installed apps...")

        def work():
            return freshstart.disabled_services(), freshstart.installed_bloat()

        def done(r):
            self.services, self.bloat = r
            self.lbl.configure(text="")
            self._render()
        self.app.bg(work, done)

    def _section(self, title, sub):
        ctk.CTkLabel(self.list, text=title, font=font(17, True), anchor="w").pack(fill="x", padx=8, pady=(14, 0))
        ctk.CTkLabel(self.list, text=sub, font=font(12), text_color=MUTED, anchor="w", justify="left",
                     wraplength=900).pack(fill="x", padx=8, pady=(0, 4))

    def _check_row(self, text, desc, var, tags=()):
        row = ctk.CTkFrame(self.list, fg_color=CARD, corner_radius=8)
        row.pack(fill="x", padx=6, pady=2)
        top = ctk.CTkFrame(row, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 0))
        ctk.CTkCheckBox(top, text=text, variable=var, font=font(13, True), fg_color=ACCENT).pack(side="left")
        for t, col in tags:
            ctk.CTkLabel(top, text=f" {t} ", fg_color=col, text_color="#000", corner_radius=6,
                         font=font(10, True)).pack(side="left", padx=3)
        ctk.CTkLabel(row, text=desc, font=font(11), text_color=MUTED, anchor="w", justify="left",
                     wraplength=880).pack(fill="x", padx=40, pady=(0, 8))

    def _render(self):
        clear(self.list)
        old = {k: v.get() for k, v in self.step_vars.items()}
        self.step_vars = {}
        self._section("🔧 Repair & reset", "The core of Fresh Start. Defaults are safe for everyone.")
        for sid, name, desc, _f, admin, mins, reboot, default in freshstart.STEPS:
            v = ctk.BooleanVar(value=old.get(sid, default))
            self.step_vars[sid] = v
            tags = [(mins, "#374151")]
            if admin:
                tags.append(("Admin", "#f59e0b"))
            if reboot:
                tags.append(("Restart needed", "#3b82f6"))
            self._check_row(name, desc, v, tags)

        self._section("⚙ Services that are turned off",
                      "Windows services that were disabled (usually by an 'optimizer' or debloat script) and "
                      "that break things when they're off. Ticked ones go back to the Windows default.")
        self.svc_vars = []
        if self.services is None:
            ctk.CTkLabel(self.list, text="Checking...", text_color=MUTED).pack(anchor="w", padx=14)
        elif not self.services:
            ctk.CTkLabel(self.list, text="✔ None - all the important ones are on.", text_color=COLORS["good"],
                         font=font(12, True)).pack(anchor="w", padx=14)
        for s in self.services or []:
            v = ctk.BooleanVar(value=s["default"])
            self.svc_vars.append((s, v))
            self._check_row(f"{s['friendly']}  →  {freshstart.SC_NAMES[s['start']]}", s["why"], v,
                            [("Disabled", COLORS["bad"])])

        self._section("🗑 Bloatware", "Apps Windows installed that most people never use. Removing them is "
                                     "safe - you can reinstall any of them from the Microsoft Store.")
        self.bloat_vars = []
        if self.bloat is None:
            ctk.CTkLabel(self.list, text="Checking...", text_color=MUTED).pack(anchor="w", padx=14)
        elif not self.bloat:
            ctk.CTkLabel(self.list, text="✔ No bloatware found.", text_color=COLORS["good"],
                         font=font(12, True)).pack(anchor="w", padx=14)
        for b in self.bloat or []:
            v = ctk.BooleanVar(value=b["default"])
            self.bloat_vars.append((b, v))
            self._check_row(b["friendly"], b["note"] or b["name"], v)

    # ---------------------------------------------------------- run
    def log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def start(self):
        if self.running:
            return
        if not IS_WINDOWS:
            self.app.toast("Fresh Start only works on Windows", "warn")
            return
        if not is_admin():
            if mb.askyesno(APP_NAME, "Fresh Start needs admin to repair Windows.\n\nRestart RigTune as admin now?"):
                self.app._elevate()
            return
        steps = [sid for sid, v in self.step_vars.items() if v.get()]
        svcs = [s for s, v in self.svc_vars if v.get()]
        apps = [b for b, v in self.bloat_vars if v.get()]
        if not (steps or svcs or apps):
            self.app.toast("Nothing ticked", "warn")
            return
        names = [freshstart.STEP_BY_ID[s][1] for s in steps]
        if svcs:
            names.append(f"Turn {len(svcs)} service(s) back on")
        if apps:
            names.append(f"Remove {len(apps)} bloatware app(s): " + ", ".join(b["friendly"] for b in apps[:6])
                         + ("..." if len(apps) > 6 else ""))
        if not mb.askyesno(APP_NAME, "Fresh Start will:\n\n• Create a restore point\n" +
                           "\n".join("• " + n for n in names) +
                           "\n\nThis can take 15-45 minutes. Close your games, keep the PC plugged in "
                           "and don't turn it off. You can keep using it for light stuff.\n\nStart?"):
            return
        self.running = True
        self.run_btn.configure(state="disabled", text="Running...")
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.log("🛟 Creating a restore point...")
        self.prog.set(0)
        self.app.bg(tweaks.create_restore_point, lambda r: self._after_rp(r, steps, svcs, apps))

    def _after_rp(self, r, steps, svcs, apps):
        ok, msg = r
        self.log(("  ✔ " if ok else "  ⚠ ") + msg.splitlines()[0])
        if not ok and "24h" not in msg:
            if not mb.askyesno(APP_NAME, "Couldn't create a restore point:\n\n" + msg +
                               "\n\nContinue without one? (Not recommended)"):
                self._finish([], cancelled=True)
                return
        total = len(steps) + len(svcs) + len(apps)

        def work():
            results = []
            n = 0

            def tick(label, res):
                nonlocal n
                n += 1
                results.append((label, *res))
                self.app.call(self.log, ("  ✔ " if res[0] else "  ✖ ") + res[1])
                self.app.call(self.prog.set, n / total)

            for sid in steps:
                s = freshstart.STEP_BY_ID[sid]
                self.app.call(self.log, f"▶ {s[1]}  ({s[5]})")
                self.app.call(lambda t=s[1]: self.lbl.configure(text=f"Now: {t}"))
                tick(s[1], freshstart.run_step(sid))
            if svcs:
                self.app.call(self.log, "▶ Turning services back on")
            for s in svcs:
                tick(s["friendly"], freshstart.restore_service(s["name"]))
            if apps:
                self.app.call(self.log, "▶ Removing bloatware")
            for b in apps:
                tick(b["friendly"], freshstart.remove_app(b))
            return results
        self.app.bg(work, lambda res: self._finish(res, steps=steps))

    def _finish(self, results, cancelled=False, steps=()):
        self.running = False
        self.run_btn.configure(state="normal", text="✨ Run Fresh Start")
        self.lbl.configure(text="")
        if cancelled:
            self.log("Cancelled.")
            return
        good = sum(1 for r in results if r[1])
        bad = [r for r in results if not r[1]]
        self.log(f"Done: {good} worked, {len(bad)} failed.")
        need_restart = any(freshstart.STEP_BY_ID[s][6] for s in steps) or "sfc" in steps or "dism" in steps
        text = f"Fresh Start finished ✨\n\n{good} step(s) worked."
        if bad:
            text += "\n\nDidn't work:\n" + "\n".join(f"• {r[0]}: {r[2]}" for r in bad[:8])
        if need_restart:
            text += "\n\nRestart your PC to finish the repairs. Restart now?"
            if mb.askyesno(APP_NAME, text):
                freshstart.restart_pc()
                self.app.toast("Restarting in 15 seconds - save your stuff", "warn")
        else:
            mb.showinfo(APP_NAME, text)
        self.refresh()



def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
