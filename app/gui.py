"""Interfața grafică (tkinter / ttk)."""

from __future__ import annotations

import copy
import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext
import tkinter as tk
from tkinter import ttk

from . import APP_NAME, __version__
from .config import CLAUDE_MODELS, SOURCE_LANGUAGES, Settings, user_config_dir
from .engines import CancelledError, ENGINE_CHOICES, TranslationError, make_engine
from .glossary import Entry, Glossary
from .pipeline import Pipeline
from .tm_cache import TranslationMemory

PAD = {"padx": 6, "pady": 4}


def _open_path(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:  # noqa: BLE001
        messagebox.showerror(APP_NAME, f"Nu pot deschide {path}:\n{exc}")


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {__version__} - traducere fișe tehnice PDF în română")
        self.minsize(900, 640)
        self.geometry("1000x720")
        self.settings = Settings.load()
        self.glossary = Glossary.load()
        self.queue: queue.Queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.files: list[Path] = []
        self.last_outputs: list[Path] = []

        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)
        self.tab_main = ttk.Frame(self.notebook)
        self.tab_settings = ttk.Frame(self.notebook)
        self.tab_glossary = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_main, text="  Traducere  ")
        self.notebook.add(self.tab_settings, text="  Setări  ")
        self.notebook.add(self.tab_glossary, text="  Glosar  ")
        self._build_main()
        self._build_settings()
        self._build_glossary()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_queue)

    # ================================================================== tab Traducere
    def _build_main(self) -> None:
        f = self.tab_main
        f.columnconfigure(0, weight=1)
        f.rowconfigure(0, weight=1)
        f.rowconfigure(4, weight=1)

        # ---- fișiere
        lf = ttk.LabelFrame(f, text="Fișiere PDF de tradus")
        lf.grid(row=0, column=0, sticky="nsew", **PAD)
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(lf, selectmode="extended", height=7)
        self.listbox.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.listbox.yview)
        sb.grid(row=0, column=1, sticky="ns", pady=6)
        self.listbox.configure(yscrollcommand=sb.set)
        bf = ttk.Frame(lf)
        bf.grid(row=0, column=2, sticky="n", padx=6, pady=6)
        ttk.Button(bf, text="Adaugă PDF...", command=self._add_files).pack(fill="x", pady=2)
        ttk.Button(bf, text="Adaugă folder...", command=self._add_folder).pack(fill="x", pady=2)
        ttk.Button(bf, text="Elimină", command=self._remove_selected).pack(fill="x", pady=2)
        ttk.Button(bf, text="Golește lista", command=self._clear_files).pack(fill="x", pady=2)

        # ---- ieșire
        of = ttk.LabelFrame(f, text="Folder de ieșire")
        of.grid(row=1, column=0, sticky="ew", **PAD)
        of.columnconfigure(1, weight=1)
        self.var_same_dir = tk.BooleanVar(value=not bool(self.settings.last_out_dir))
        ttk.Checkbutton(of, text="Salvează lângă fișierul sursă", variable=self.var_same_dir,
                        command=self._toggle_out_dir).grid(row=0, column=0, sticky="w", **PAD)
        self.var_out_dir = tk.StringVar(value=self.settings.last_out_dir)
        self.ent_out = ttk.Entry(of, textvariable=self.var_out_dir)
        self.ent_out.grid(row=0, column=1, sticky="ew", **PAD)
        self.btn_out = ttk.Button(of, text="Alege...", command=self._choose_out_dir)
        self.btn_out.grid(row=0, column=2, **PAD)
        self._toggle_out_dir()

        # ---- opțiuni
        opt = ttk.LabelFrame(f, text="Opțiuni de traducere")
        opt.grid(row=2, column=0, sticky="ew", **PAD)
        for c in range(6):
            opt.columnconfigure(c, weight=1 if c in (1, 3, 5) else 0)
        ttk.Label(opt, text="Motor:").grid(row=0, column=0, sticky="e", **PAD)
        self.engine_names = {eid: name for eid, name in ENGINE_CHOICES}
        self.var_engine = tk.StringVar(value=self.engine_names.get(self.settings.engine, ENGINE_CHOICES[0][1]))
        cb = ttk.Combobox(opt, textvariable=self.var_engine, state="readonly",
                          values=[name for _, name in ENGINE_CHOICES])
        cb.grid(row=0, column=1, sticky="ew", **PAD)
        ttk.Label(opt, text="Limba sursă:").grid(row=0, column=2, sticky="e", **PAD)
        self.lang_names = {code: f"{name} ({code})" if code != "auto" else name
                           for code, name in SOURCE_LANGUAGES.items()}
        self.var_lang = tk.StringVar(value=self.lang_names.get(self.settings.source_lang, self.lang_names["auto"]))
        ttk.Combobox(opt, textvariable=self.var_lang, state="readonly",
                     values=list(self.lang_names.values())).grid(row=0, column=3, sticky="ew", **PAD)
        self.var_post_edit = tk.BooleanVar(value=self.settings.post_edit)
        ttk.Checkbutton(opt, text="Corectare contextuală cu Claude (post-editare)",
                        variable=self.var_post_edit).grid(row=0, column=4, columnspan=2, sticky="w", **PAD)

        self.var_out_pdf = tk.BooleanVar(value=self.settings.out_pdf)
        self.var_out_docx = tk.BooleanVar(value=self.settings.out_docx)
        self.var_out_report = tk.BooleanVar(value=self.settings.out_report)
        self.var_out_compare = tk.BooleanVar(value=self.settings.out_compare)
        ttk.Label(opt, text="Rezultate:").grid(row=1, column=0, sticky="e", **PAD)
        ttk.Checkbutton(opt, text="PDF tradus (aspect păstrat)", variable=self.var_out_pdf).grid(
            row=1, column=1, sticky="w", **PAD)
        ttk.Checkbutton(opt, text="DOCX bilingv (verificare)", variable=self.var_out_docx).grid(
            row=1, column=2, columnspan=2, sticky="w", **PAD)
        ttk.Checkbutton(opt, text="Raport de calitate (HTML)", variable=self.var_out_report).grid(
            row=1, column=4, sticky="w", **PAD)
        ttk.Checkbutton(opt, text="PDF comparativ (original/traducere)", variable=self.var_out_compare).grid(
            row=1, column=5, sticky="w", **PAD)

        # ---- acțiuni + progres
        af = ttk.Frame(f)
        af.grid(row=3, column=0, sticky="ew", **PAD)
        af.columnconfigure(3, weight=1)
        self.btn_start = ttk.Button(af, text="▶  Traduce", command=self._start)
        self.btn_start.grid(row=0, column=0, **PAD)
        self.btn_stop = ttk.Button(af, text="■  Oprește", command=self._stop, state="disabled")
        self.btn_stop.grid(row=0, column=1, **PAD)
        self.btn_open = ttk.Button(af, text="Deschide folderul de ieșire", command=self._open_out, state="disabled")
        self.btn_open.grid(row=0, column=2, **PAD)
        self.progress = ttk.Progressbar(af, mode="determinate", maximum=1000)
        self.progress.grid(row=0, column=3, sticky="ew", **PAD)
        self.var_status = tk.StringVar(value="Pregătit.")
        ttk.Label(af, textvariable=self.var_status).grid(row=1, column=0, columnspan=4, sticky="w", **PAD)

        # ---- jurnal
        jf = ttk.LabelFrame(f, text="Jurnal")
        jf.grid(row=4, column=0, sticky="nsew", **PAD)
        jf.columnconfigure(0, weight=1)
        jf.rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(jf, height=10, wrap="word", state="disabled",
                                                  font=("Consolas", 9))
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

    # ---------------------------------------------------------------- fișiere
    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Alege fișiere PDF", initialdir=self.settings.last_in_dir or None,
            filetypes=[("Fișiere PDF", "*.pdf"), ("Toate fișierele", "*.*")])
        if paths:
            self.settings.last_in_dir = str(Path(paths[0]).parent)
        self._append_files(Path(p) for p in paths)

    def _add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Alege un folder cu PDF-uri",
                                         initialdir=self.settings.last_in_dir or None)
        if folder:
            self.settings.last_in_dir = folder
            self._append_files(sorted(Path(folder).glob("*.pdf")))

    def _append_files(self, paths) -> None:
        for p in paths:
            p = Path(p)
            if p.suffix.lower() == ".pdf" and p.exists() and p not in self.files:
                self.files.append(p)
                self.listbox.insert("end", str(p))

    def _remove_selected(self) -> None:
        for idx in reversed(self.listbox.curselection()):
            self.listbox.delete(idx)
            del self.files[idx]

    def _clear_files(self) -> None:
        self.listbox.delete(0, "end")
        self.files.clear()

    def _toggle_out_dir(self) -> None:
        state = "disabled" if self.var_same_dir.get() else "normal"
        self.ent_out.configure(state=state)
        self.btn_out.configure(state=state)

    def _choose_out_dir(self) -> None:
        folder = filedialog.askdirectory(title="Folder de ieșire", initialdir=self.var_out_dir.get() or None)
        if folder:
            self.var_out_dir.set(folder)

    def _open_out(self) -> None:
        if self.last_outputs:
            _open_path(self.last_outputs[-1].parent)

    # ---------------------------------------------------------------- jurnal
    def log(self, msg: str) -> None:
        """Poate fi apelată din orice fir: mesajul este pus în coadă și afișat de firul GUI."""
        self.queue.put(("log", msg))

    def _append_log(self, msg: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ---------------------------------------------------------------- rulare
    def _collect_settings(self) -> Settings:
        s = self.settings
        s.engine = next((eid for eid, name in ENGINE_CHOICES if name == self.var_engine.get()), "google")
        s.source_lang = next((code for code, name in self.lang_names.items() if name == self.var_lang.get()), "auto")
        s.post_edit = self.var_post_edit.get()
        s.out_pdf = self.var_out_pdf.get()
        s.out_docx = self.var_out_docx.get()
        s.out_report = self.var_out_report.get()
        s.out_compare = self.var_out_compare.get()
        s.last_out_dir = "" if self.var_same_dir.get() else self.var_out_dir.get().strip()
        self._collect_settings_tab()
        return s

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if not self.files:
            messagebox.showinfo(APP_NAME, "Adaugă cel puțin un fișier PDF.")
            return
        s = self._collect_settings()
        if not (s.out_pdf or s.out_docx or s.out_report or s.out_compare):
            messagebox.showinfo(APP_NAME, "Alege cel puțin un tip de rezultat.")
            return
        if s.engine == "deepl" and not s.deepl_key.strip():
            messagebox.showwarning(APP_NAME, "Introdu cheia API DeepL în tab-ul Setări.")
            return
        if (s.engine == "claude" or s.post_edit) and not s.anthropic_key.strip():
            messagebox.showwarning(APP_NAME, "Introdu cheia API Anthropic (Claude) în tab-ul Setări.")
            return
        if not self.var_same_dir.get() and not s.last_out_dir:
            messagebox.showwarning(APP_NAME, "Alege folderul de ieșire sau bifează „Salvează lângă fișierul sursă”.")
            return
        s.save()
        self.cancel.clear()
        self.last_outputs = []
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_open.configure(state="disabled")
        self.progress["value"] = 0
        files = list(self.files)
        out_dir = None if self.var_same_dir.get() else Path(s.last_out_dir)
        # firul de lucru primește o copie, ca modificările ulterioare din interfață să nu-l afecteze
        self.worker = threading.Thread(target=self._run_worker, args=(copy.copy(s), files, out_dir), daemon=True)
        self.worker.start()

    def _run_worker(self, s: Settings, files: list[Path], out_dir: Path | None) -> None:
        pipeline = Pipeline(s, Glossary.load(), log=self.log,
                            progress=lambda frac, msg: self.queue.put(("progress", frac, msg)),
                            cancel=self.cancel)
        n_ok, n_err = 0, 0
        try:
            for i, pdf in enumerate(files, 1):
                if self.cancel.is_set():
                    break
                self.log(f"\n[{i}/{len(files)}] {pdf.name}")
                try:
                    res = pipeline.run_file(pdf, out_dir or pdf.parent)
                    self.queue.put(("outputs", res["outputs"]))
                    n_ok += 1
                except CancelledError:
                    self.log("Oprit de utilizator.")
                    break
                except TranslationError as exc:
                    n_err += 1
                    self.log(f"EROARE: {exc}")
                except Exception as exc:  # noqa: BLE001
                    n_err += 1
                    self.log(f"EROARE neașteptată: {exc}\n{traceback.format_exc()}")
        finally:
            pipeline.close()
            self.queue.put(("done", n_ok, n_err))

    def _stop(self) -> None:
        self.cancel.set()
        self.var_status.set("Se oprește după cererea curentă...")

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self.queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._append_log(item[1])
                elif kind == "progress":
                    self.progress["value"] = int(item[1] * 1000)
                    self.var_status.set(item[2])
                elif kind == "outputs":
                    self.last_outputs.extend(item[1])
                elif kind == "done":
                    n_ok, n_err = item[1], item[2]
                    self.btn_start.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                    if self.last_outputs:
                        self.btn_open.configure(state="normal")
                    if self.cancel.is_set():
                        self.var_status.set(f"Oprit. Fișiere finalizate: {n_ok}.")
                    else:
                        self.var_status.set(f"Gata. Fișiere traduse: {n_ok}, erori: {n_err}.")
                        if n_ok and not n_err:
                            self.progress["value"] = 1000
                            if messagebox.askyesno(APP_NAME, f"Traducerea s-a încheiat ({n_ok} fișiere).\n"
                                                             "Deschizi folderul cu rezultatele?"):
                                self._open_out()
                        elif n_err:
                            messagebox.showwarning(APP_NAME, f"Finalizat cu {n_err} erori. Vezi jurnalul.")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    # ================================================================== tab Setări
    def _build_settings(self) -> None:
        f = self.tab_settings
        f.columnconfigure(1, weight=1)
        s = self.settings
        row = 0

        def section(title: str) -> None:
            nonlocal row
            ttk.Label(f, text=title, font=("", 10, "bold")).grid(row=row, column=0, columnspan=3,
                                                                 sticky="w", padx=6, pady=(12, 2))
            row += 1

        section("Chei API (se salvează local, în profilul utilizatorului)")
        ttk.Label(f, text="Cheie DeepL:").grid(row=row, column=0, sticky="e", **PAD)
        self.var_deepl = tk.StringVar(value=s.deepl_key)
        ttk.Entry(f, textvariable=self.var_deepl, show="•").grid(row=row, column=1, sticky="ew", **PAD)
        ttk.Button(f, text="Obține cheie", command=lambda: webbrowser.open("https://www.deepl.com/pro-api")).grid(
            row=row, column=2, **PAD)
        row += 1
        ttk.Label(f, text="Cheie Anthropic (Claude):").grid(row=row, column=0, sticky="e", **PAD)
        self.var_anthropic = tk.StringVar(value=s.anthropic_key)
        ttk.Entry(f, textvariable=self.var_anthropic, show="•").grid(row=row, column=1, sticky="ew", **PAD)
        ttk.Button(f, text="Obține cheie", command=lambda: webbrowser.open("https://platform.claude.com/")).grid(
            row=row, column=2, **PAD)
        row += 1
        ttk.Label(f, text="Model Claude:").grid(row=row, column=0, sticky="e", **PAD)
        self.var_model = tk.StringVar(value=s.claude_model)
        ttk.Combobox(f, textvariable=self.var_model, values=CLAUDE_MODELS).grid(row=row, column=1, sticky="w", **PAD)
        row += 1
        ttk.Label(f, text="Formalitate DeepL:").grid(row=row, column=0, sticky="e", **PAD)
        self.formality_names = {"default": "implicit", "prefer_more": "formal (dvs.)", "prefer_less": "informal"}
        self.var_formality = tk.StringVar(value=self.formality_names.get(s.deepl_formality, "implicit"))
        ttk.Combobox(f, textvariable=self.var_formality, state="readonly",
                     values=list(self.formality_names.values())).grid(row=row, column=1, sticky="w", **PAD)
        row += 1
        ttk.Button(f, text="Testează motorul selectat", command=self._test_engine).grid(
            row=row, column=1, sticky="w", **PAD)
        row += 1

        section("Exactitate")
        self.var_protect = tk.BooleanVar(value=s.protect_tokens)
        ttk.Checkbutton(f, text="Protejează numerele, unitățile, codurile de produs și standardele "
                           "(nu pot fi modificate de traducere)", variable=self.var_protect).grid(
            row=row, column=0, columnspan=3, sticky="w", **PAD)
        row += 1
        self.var_decimal = tk.BooleanVar(value=s.decimal_comma)
        ttk.Checkbutton(f, text="Convertește separatorul zecimal la virgulă (1.5 → 1,5)",
                        variable=self.var_decimal).grid(row=row, column=0, columnspan=3, sticky="w", **PAD)
        row += 1
        self.var_tm = tk.BooleanVar(value=s.use_tm)
        ttk.Checkbutton(f, text="Folosește memoria de traducere (segmentele identice se traduc o singură dată)",
                        variable=self.var_tm).grid(row=row, column=0, columnspan=2, sticky="w", **PAD)
        ttk.Button(f, text="Golește memoria", command=self._clear_tm).grid(row=row, column=2, **PAD)
        row += 1

        section("Aspect PDF")
        self.var_expand = tk.BooleanVar(value=s.expand_boxes)
        ttk.Checkbutton(f, text="Extinde casetele de text în spațiul liber (textul românesc este mai lung)",
                        variable=self.var_expand).grid(row=row, column=0, columnspan=3, sticky="w", **PAD)
        row += 1
        ttk.Label(f, text="Avertizează când textul e micșorat sub:").grid(row=row, column=0, sticky="e", **PAD)
        self.var_min_scale = tk.DoubleVar(value=s.min_scale_warn)
        ttk.Spinbox(f, from_=0.3, to=1.0, increment=0.05, textvariable=self.var_min_scale, width=6).grid(
            row=row, column=1, sticky="w", **PAD)
        row += 1
        ttk.Label(f, text="Pauză între cereri (secunde):").grid(row=row, column=0, sticky="e", **PAD)
        self.var_delay = tk.DoubleVar(value=s.request_delay)
        ttk.Spinbox(f, from_=0.0, to=10.0, increment=0.1, textvariable=self.var_delay, width=6).grid(
            row=row, column=1, sticky="w", **PAD)
        row += 1
        ttk.Button(f, text="Salvează setările", command=self._save_settings).grid(row=row, column=1, sticky="w", **PAD)
        ttk.Button(f, text="Deschide folderul de configurare", command=lambda: _open_path(user_config_dir())).grid(
            row=row, column=2, **PAD)

    def _collect_settings_tab(self) -> None:
        s = self.settings
        s.deepl_key = self.var_deepl.get().strip()
        s.anthropic_key = self.var_anthropic.get().strip()
        s.claude_model = self.var_model.get().strip() or CLAUDE_MODELS[0]
        s.deepl_formality = next((k for k, v in self.formality_names.items() if v == self.var_formality.get()),
                                 "default")
        s.protect_tokens = self.var_protect.get()
        s.decimal_comma = self.var_decimal.get()
        s.use_tm = self.var_tm.get()
        s.expand_boxes = self.var_expand.get()
        try:
            s.min_scale_warn = float(self.var_min_scale.get())
        except (tk.TclError, ValueError):
            s.min_scale_warn = 0.6
        try:
            s.request_delay = float(self.var_delay.get())
        except (tk.TclError, ValueError):
            s.request_delay = 0.0

    def _save_settings(self) -> None:
        self._collect_settings()
        self.settings.save()
        messagebox.showinfo(APP_NAME, "Setările au fost salvate.")

    def _clear_tm(self) -> None:
        if messagebox.askyesno(APP_NAME, "Ștergi toată memoria de traducere?"):
            tm = TranslationMemory()
            tm.clear()
            tm.close()
            messagebox.showinfo(APP_NAME, "Memoria de traducere a fost golită.")

    def _test_engine(self) -> None:
        s = self._collect_settings()

        def work() -> None:
            try:
                engine = make_engine(s, glossary=self.glossary, log=self.log)
                out = engine.translate_batch(["Rated current ⟦0⟧, breaking capacity ⟦1⟧"])
                engine.close()
                self.queue.put(("log", f"Test {engine.name}: {out[0]}"))
                self.after(0, lambda: messagebox.showinfo(APP_NAME, f"{engine.name} funcționează:\n\n{out[0]}"))
            except Exception as exc:  # noqa: BLE001
                err = f"{type(exc).__name__}: {exc}"
                self.after(0, lambda: messagebox.showerror(APP_NAME, f"Testul a eșuat:\n{err}"))

        threading.Thread(target=work, daemon=True).start()

    # ================================================================== tab Glosar
    def _build_glossary(self) -> None:
        f = self.tab_glossary
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)
        ttk.Label(f, text="Termenii din glosar sunt transmiși motorului Claude și verificați în raport. "
                          "Marchează „păstrează” pentru nume de mărci/game care nu se traduc.",
                  wraplength=900).grid(row=0, column=0, columnspan=2, sticky="w", **PAD)
        cols = ("lang", "src", "ro", "keep")
        self.tree = ttk.Treeview(f, columns=cols, show="headings", selectmode="browse")
        for col, title, w in (("lang", "Limbă", 60), ("src", "Termen sursă", 320), ("ro", "Traducere RO", 380),
                              ("keep", "Păstrează", 80)):
            self.tree.heading(col, text=title, command=lambda c=col: self._sort_tree(c))
            self.tree.column(col, width=w, anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew", padx=(6, 0), pady=4)
        sb = ttk.Scrollbar(f, orient="vertical", command=self.tree.yview)
        sb.grid(row=1, column=1, sticky="ns", pady=4)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        ef = ttk.Frame(f)
        ef.grid(row=2, column=0, columnspan=2, sticky="ew", **PAD)
        ef.columnconfigure(3, weight=1)
        ef.columnconfigure(5, weight=1)
        ttk.Label(ef, text="Limbă:").grid(row=0, column=0, sticky="e", **PAD)
        self.var_g_lang = tk.StringVar(value="en")
        ttk.Combobox(ef, textvariable=self.var_g_lang, width=5,
                     values=["*"] + [c for c in SOURCE_LANGUAGES if c != "auto"]).grid(row=0, column=1, **PAD)
        ttk.Label(ef, text="Sursă:").grid(row=0, column=2, sticky="e", **PAD)
        self.var_g_src = tk.StringVar()
        ttk.Entry(ef, textvariable=self.var_g_src).grid(row=0, column=3, sticky="ew", **PAD)
        ttk.Label(ef, text="Română:").grid(row=0, column=4, sticky="e", **PAD)
        self.var_g_ro = tk.StringVar()
        ttk.Entry(ef, textvariable=self.var_g_ro).grid(row=0, column=5, sticky="ew", **PAD)
        self.var_g_keep = tk.BooleanVar(value=False)
        ttk.Checkbutton(ef, text="păstrează (nu traduce)", variable=self.var_g_keep).grid(row=0, column=6, **PAD)

        bf = ttk.Frame(f)
        bf.grid(row=3, column=0, columnspan=2, sticky="ew", **PAD)
        ttk.Button(bf, text="Adaugă / actualizează", command=self._glossary_add).pack(side="left", padx=3)
        ttk.Button(bf, text="Șterge selecția", command=self._glossary_delete).pack(side="left", padx=3)
        ttk.Button(bf, text="Import CSV...", command=self._glossary_import).pack(side="left", padx=3)
        ttk.Button(bf, text="Export CSV...", command=self._glossary_export).pack(side="left", padx=3)
        ttk.Button(bf, text="Salvează glosarul", command=self._glossary_save).pack(side="left", padx=12)
        self.var_g_filter = tk.StringVar()
        ttk.Label(bf, text="Caută:").pack(side="left", padx=(20, 3))
        ent = ttk.Entry(bf, textvariable=self.var_g_filter, width=24)
        ent.pack(side="left")
        ent.bind("<KeyRelease>", lambda e: self._fill_tree())
        self.var_g_count = tk.StringVar()
        ttk.Label(bf, textvariable=self.var_g_count).pack(side="right", padx=6)
        self._fill_tree()

    def _fill_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        flt = self.var_g_filter.get().strip().lower()
        n = 0
        for e in sorted(self.glossary.entries, key=lambda x: (x.lang, x.src.lower())):
            if flt and flt not in e.src.lower() and flt not in e.ro.lower():
                continue
            self.tree.insert("", "end", values=(e.lang, e.src, e.ro, "da" if e.keep else ""))
            n += 1
        self.var_g_count.set(f"{n} termeni")

    def _sort_tree(self, col: str) -> None:
        items = [(self.tree.set(k, col).lower(), k) for k in self.tree.get_children("")]
        items.sort()
        for idx, (_, k) in enumerate(items):
            self.tree.move(k, "", idx)

    def _on_tree_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        lang, src, ro, keep = self.tree.item(sel[0], "values")
        self.var_g_lang.set(lang)
        self.var_g_src.set(src)
        self.var_g_ro.set(ro)
        self.var_g_keep.set(keep == "da")

    def _glossary_add(self) -> None:
        src = self.var_g_src.get().strip()
        ro = self.var_g_ro.get().strip()
        if not src:
            return
        keep = self.var_g_keep.get()
        entry = Entry(lang=self.var_g_lang.get().strip() or "*", src=src, ro=ro or src, keep=keep)
        self.glossary.entries = [e for e in self.glossary.entries if e.key() != entry.key()]
        self.glossary.entries.append(entry)
        self.glossary.invalidate()
        self._fill_tree()

    def _glossary_delete(self) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        lang, src, *_ = self.tree.item(sel[0], "values")
        key = (lang.lower(), src.lower())
        self.glossary.entries = [e for e in self.glossary.entries if e.key() != key]
        self.glossary.invalidate()
        self._fill_tree()

    def _glossary_import(self) -> None:
        path = filedialog.askopenfilename(title="Import glosar CSV",
                                          filetypes=[("CSV", "*.csv;*.txt"), ("Toate", "*.*")])
        if not path:
            return
        try:
            entries = Glossary.import_csv(Path(path))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(APP_NAME, f"Nu pot citi fișierul:\n{exc}")
            return
        existing = {e.key(): e for e in self.glossary.entries}
        for e in entries:
            existing[e.key()] = e
        self.glossary.entries = list(existing.values())
        self.glossary.invalidate()
        self._fill_tree()
        messagebox.showinfo(APP_NAME, f"Importate {len(entries)} intrări. Apasă „Salvează glosarul” pentru a le păstra.")

    def _glossary_export(self) -> None:
        path = filedialog.asksaveasfilename(title="Export glosar CSV", defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            Glossary.export_csv(self.glossary.entries, Path(path))
            messagebox.showinfo(APP_NAME, "Glosarul a fost exportat.")

    def _glossary_save(self) -> None:
        path = Glossary.save_user(self.glossary.entries)
        messagebox.showinfo(APP_NAME, f"Glosarul a fost salvat:\n{path}")

    # ================================================================== închidere
    def _on_close(self) -> None:
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno(APP_NAME, "O traducere este în curs. Închizi aplicația?"):
                return
            self.cancel.set()
        try:
            self._collect_settings()
            self.settings.save()
        except Exception:  # noqa: BLE001
            pass
        self.destroy()


def run() -> None:
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # text clar pe ecrane HiDPI
        except Exception:  # noqa: BLE001
            pass
    app = App()
    app.mainloop()
