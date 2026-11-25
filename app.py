"""RigTune GUI (customtkinter)."""
import queue
import threading
import time
import tkinter.messagebox as mb

import customtkinter as ctk

from . import (APP_NAME, APP_VERSION, boost, checks, cleanup, display, network, report, startup,
               sysinfo, tweaks)
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
        ctk.CTkLabel(sb, text="⚡ " + APP_NAME, font=font(24, True), text_color=ACCENT).pack(pady=(24, 2), padx=20, anchor="w")
        ctk.CTkLabel(sb, text="Real optimizations. No placebo.", font=font(11), text_color=MUTED).pack(padx=20, anchor="w")
        self.nav_btns = {}
        items = [("dashboard", "🏠  Dashboard"), ("results", "🔍  Scan results"), ("optimize", "🛠  Optimize"),
                 ("boost", "🚀  Game Boost"), ("startup", "⏻  Startup apps"), ("cleanup", "🧹  Cleanup"),
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


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
