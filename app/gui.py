"""gui.py — Tahap 9: antarmuka desktop PySide6.

Alur: pilih video -> atur opsi -> Analisis (rencana edit, bisa
centang-matikan efek) -> Generate (progress bertahap, bisa Batal) ->
ringkasan QA. Proses berat di QThread agar UI tak membeku.
"""
from __future__ import annotations

import json
import logging
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QThread, Signal  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QScrollArea, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

import yaml  # noqa: E402

from app.pipeline import Pipeline, PipelineOptions  # noqa: E402
from app.presets import list_presets  # noqa: E402
from app.registry import EffectRegistry  # noqa: E402
from app.utils import app_dirs, resource_path, sanitize_proxy_env  # noqa: E402

log = logging.getLogger("auto_video_editor.gui")


class Worker(QThread):
    progress = Signal(str, float)
    logline = Signal(str)
    finished_ok = Signal(dict)
    finished_err = Signal(str)

    def __init__(self, pipeline_cls, config, opt: "PipelineOptions",
                 cancel_event):
        super().__init__()
        self._pipeline_cls = pipeline_cls
        self._config = config
        self.opt = opt
        self._cancel_event = cancel_event

    def run(self):  # noqa: D102
        try:
            # Pipeline dibuat di dalam worker thread; callback-nya
            # memancarkan signal Qt (aman lintas thread), bukan
            # menyentuh widget GUI langsung.
            pipe = self._pipeline_cls(
                self._config,
                on_progress=lambda s, f: self.progress.emit(s, f),
                on_log=lambda m: self.logline.emit(m),
                cancel_event=self._cancel_event)
            res = pipe.run(self.opt)
            self.finished_ok.emit(res)
        except Exception as e:  # noqa: BLE001
            self.finished_err.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Auto Video Editor")
        self.resize(900, 700)
        self.setAcceptDrops(True)
        self.dirs = app_dirs()
        self.config = yaml.safe_load(
            (resource_path("config.yaml")).read_text(encoding="utf-8"))
        self.registry = EffectRegistry(resource_path("catalog"),
                                       resource_path("assets")).load()
        self.cancel_event = threading.Event()
        self.worker: Worker | None = None
        self.edl_path: Path | None = None
        self._build_ui()

    # -- UI -----------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # --- input ---
        g_in = QGroupBox("Video sumber")
        l_in = QHBoxLayout(g_in)
        self.ed_input = QLineEdit()
        self.ed_input.setPlaceholderText(
            "Seret video ke sini atau klik Pilih...")
        btn_browse = QPushButton("Pilih...")
        btn_browse.clicked.connect(self._browse_input)
        l_in.addWidget(self.ed_input, 1)
        l_in.addWidget(btn_browse)
        root.addWidget(g_in)

        split = QSplitter(Qt.Horizontal)
        root.addWidget(split, 1)

        # --- opsi ---
        g_opt = QGroupBox("Opsi")
        f_opt = QFormLayout(g_opt)
        self.cb_mode = QComboBox()
        self.cb_mode.addItems(["auto", "preset"])
        self.cb_mode.currentTextChanged.connect(self._mode_changed)
        f_opt.addRow("Mode:", self.cb_mode)
        self.cb_preset = QComboBox()
        self.cb_preset.addItems(list_presets())
        self.cb_preset.setEnabled(False)
        f_opt.addRow("Paket gaya:", self.cb_preset)
        self.cb_aspect = QComboBox()
        self.cb_aspect.addItems(["auto", "9:16", "16:9", "1:1", "4:5"])
        self.cb_aspect.setCurrentText("9:16")
        f_opt.addRow("Rasio output:", self.cb_aspect)
        self.cb_reframe = QComboBox()
        self.cb_reframe.addItems(
            ["auto", "smart_crop", "blur_fill", "letterbox", "none"])
        f_opt.addRow("Penyesuaian bingkai:", self.cb_reframe)
        self.cb_lang = QComboBox()
        self.cb_lang.addItems(["auto", "id", "en"])
        f_opt.addRow("Bahasa ucapan:", self.cb_lang)
        self.cb_intensity = QComboBox()
        self.cb_intensity.addItems(
            ["auto", "calm", "medium", "aggressive"])
        f_opt.addRow("Intensitas:", self.cb_intensity)
        self.ed_notes = QLineEdit()
        self.ed_notes.setPlaceholderText(
            "Arahan opsional, mis. 'lebih kalem'")
        f_opt.addRow("Arahan:", self.ed_notes)
        self.ed_key = QLineEdit()
        self.ed_key.setEchoMode(QLineEdit.Password)
        self.ed_key.setPlaceholderText("API key Gemini (disimpan lokal)")
        self._load_key()
        f_opt.addRow("API key:", self.ed_key)
        self.chk_sfx = QCheckBox("Tanpa SFX")
        f_opt.addRow("", self.chk_sfx)

        # kunci efek (auto+kunci)
        g_lock = QGroupBox("Matikan efek (auto+kunci)")
        l_lock = QVBoxLayout(g_lock)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        w_lock = QWidget()
        self.lock_boxes: dict[str, QCheckBox] = {}
        ll = QVBoxLayout(w_lock)
        for eid in sorted(self.registry.all_ids()):
            cb = QCheckBox(eid)
            self.lock_boxes[eid] = cb
            ll.addWidget(cb)
        scroll.setWidget(w_lock)
        l_lock.addWidget(scroll)

        left = QWidget()
        ll_left = QVBoxLayout(left)
        ll_left.addWidget(g_opt)
        ll_left.addWidget(g_lock, 1)
        split.addWidget(left)

        # --- rencana + log ---
        right = QWidget()
        lr = QVBoxLayout(right)
        g_plan = QGroupBox("Rencana edit (hasil Analisis)")
        l_plan = QVBoxLayout(g_plan)
        self.txt_plan = QTextEdit()
        self.txt_plan.setReadOnly(True)
        self.txt_plan.setPlaceholderText(
            "Klik Analisis untuk melihat rencana edit...")
        l_plan.addWidget(self.txt_plan)
        g_log = QGroupBox("Log")
        l_log = QVBoxLayout(g_log)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        l_log.addWidget(self.txt_log)
        lr.addWidget(g_plan, 1)
        lr.addWidget(g_log, 1)
        split.addWidget(right)
        split.setSizes([320, 560])

        # --- tombol + progress ---
        row = QHBoxLayout()
        self.btn_analyze = QPushButton("Analisis")
        self.btn_analyze.clicked.connect(self._on_analyze)
        self.btn_generate = QPushButton("Generate")
        self.btn_generate.clicked.connect(self._on_generate)
        self.btn_generate.setEnabled(False)
        self.btn_cancel = QPushButton("Batal")
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_cancel.setEnabled(False)
        self.btn_out = QPushButton("Buka folder hasil")
        self.btn_out.clicked.connect(self._open_output)
        self.btn_logdir = QPushButton("Buka folder log")
        self.btn_logdir.clicked.connect(self._open_logdir)
        for b in (self.btn_analyze, self.btn_generate, self.btn_cancel,
                  self.btn_out, self.btn_logdir):
            row.addWidget(b)
        root.addLayout(row)

        prow = QHBoxLayout()
        self.lbl_stage = QLabel("Siap.")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        prow.addWidget(self.lbl_stage)
        prow.addWidget(self.bar, 1)
        root.addLayout(prow)

    # -- events ---------------------------------------------------------------
    def _mode_changed(self, mode: str):
        self.cb_preset.setEnabled(mode == "preset")

    def _browse_input(self):
        fp, _ = QFileDialog.getOpenFileName(
            self, "Pilih video", "",
            "Video (*.mp4 *.mov *.mkv *.avi *.webm)")
        if fp:
            self.ed_input.setText(fp)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            self.ed_input.setText(urls[0].toLocalFile())

    def _load_key(self):
        kf = Path(self.dirs["base"]) / "gemini_key.txt"
        if kf.is_file():
            self.ed_key.setText(kf.read_text(encoding="utf-8").strip())

    def _save_key(self):
        key = self.ed_key.text().strip()
        if key:
            kf = Path(self.dirs["base"]) / "gemini_key.txt"
            kf.parent.mkdir(parents=True, exist_ok=True)
            kf.write_text(key, encoding="utf-8")
            try:
                kf.chmod(0o600)
            except OSError:
                pass
        return key or None

    def _make_opt(self, dry_run: bool) -> PipelineOptions | None:
        src = self.ed_input.text().strip()
        if not src or not Path(src).is_file():
            QMessageBox.warning(self, "Input", "Pilih video sumber dulu.")
            return None
        mode = self.cb_mode.currentText()
        intensity = self.cb_intensity.currentText()
        return PipelineOptions(
            input=Path(src),
            aspect=self.cb_aspect.currentText(),
            reframe=self.cb_reframe.currentText(),
            mode=mode,
            preset=self.cb_preset.currentText() if mode == "preset" else None,
            disable=[eid for eid, cb in self.lock_boxes.items()
                     if cb.isChecked()],
            intensity=None if intensity == "auto" else intensity,
            user_notes=self.ed_notes.text().strip(),
            lang=None if self.cb_lang.currentText() == "auto"
            else self.cb_lang.currentText(),
            no_sfx=self.chk_sfx.isChecked(),
            dry_run=dry_run,
            api_key=self._save_key(),
        )

    def _start_worker(self, opt: PipelineOptions, on_done):
        self.cancel_event.clear()
        self.worker = Worker(Pipeline, self.config, opt,
                             self.cancel_event)
        self.worker.progress.connect(self._on_progress)
        self.worker.logline.connect(self._on_logline)
        self.worker.finished_ok.connect(on_done)
        self.worker.finished_err.connect(self._on_error)
        self.worker.finished_ok.connect(self._work_done)
        self.worker.finished_err.connect(self._work_done)
        self.btn_analyze.setEnabled(False)
        self.btn_generate.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.worker.start()

    def _on_analyze(self):
        opt = self._make_opt(dry_run=True)
        if not opt:
            return
        self.txt_plan.setPlainText("Menganalisis...")
        self._start_worker(opt, self._analyze_done)

    def _analyze_done(self, res: dict):
        self.edl_path = Path(res["edl"])
        why = Path(res["why"]).read_text(encoding="utf-8")
        self.txt_plan.setPlainText(why)
        self.btn_generate.setEnabled(True)
        self.lbl_stage.setText("Analisis selesai. Klik Generate.")

    def _on_generate(self):
        if not self.edl_path or not self.edl_path.is_file():
            QMessageBox.warning(self, "Rencana",
                                "Klik Analisis dulu.")
            return
        opt = self._make_opt(dry_run=False)
        if not opt:
            return
        opt.from_edl = self.edl_path  # render dari rencana yg disetujui
        self._start_worker(opt, self._generate_done)

    def _generate_done(self, res: dict):
        qa = res["qa"]
        lines = [f"SELESAI: {res['output']}",
                 f"QA: {'LULUS' if qa['passed'] else 'GAGAL'}"]
        for n, c in qa["checks"].items():
            if c["status"] != "pass":
                lines.append(f"  {n}: {c['status']} — {c['detail']}")
        self._on_logline("\n".join(lines))
        QMessageBox.information(
            self, "Selesai",
            f"Video tersimpan.\nQA: {'LULUS' if qa['passed'] else 'GAGAL'}")

    def _on_cancel(self):
        self.cancel_event.set()
        self._on_logline("Membatalkan...")

    def _work_done(self, *a):
        self.btn_analyze.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        if self.edl_path:
            self.btn_generate.setEnabled(True)

    def _on_progress(self, stage: str, frac: float):
        self.lbl_stage.setText(f"Tahap: {stage}")
        self.bar.setValue(int(frac * 100))

    def _on_logline(self, msg: str):
        self.txt_log.append(msg)

    def _on_error(self, msg: str):
        box = QMessageBox(self)
        box.setWindowTitle("Galat")
        box.setText("Terjadi galat (bahasa manusia):\n\n"
                    + self._human_error(msg))
        box.setDetailedText(msg)
        copy = box.addButton("Salin detail galat",
                             QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if box.clickedButton() == copy:
            QApplication.clipboard().setText(msg)

    @staticmethod
    def _human_error(msg: str) -> str:
        m = msg.lower()
        if "api key" in m:
            return "API key Gemini belum diisi atau salah. " \
                   "Isi kolom API key lalu coba lagi."
        if "quota" in m or "429" in m:
            return "Kuota Gemini habis. Tunggu beberapa menit lalu coba lagi."
        if "503" in m or "unavailable" in m:
            return "Server Gemini sibuk. Coba lagi sebentar."
        if "ffmpeg" in m:
            return "FFmpeg gagal. Pastikan ffmpeg terpasang dan video tidak rusak."
        if "dibatalkan" in m:
            return "Proses dibatalkan."
        return msg[:300]

    def _open_output(self):
        import subprocess
        d = self.dirs["output"]
        Path(d).mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(d)])

    def _open_logdir(self):
        import subprocess
        d = self.dirs["work"]
        Path(d).mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", str(d)])


def main():
    sanitize_proxy_env()
    logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
