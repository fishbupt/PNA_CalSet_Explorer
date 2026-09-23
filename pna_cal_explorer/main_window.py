from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QMainWindow, QMessageBox, QPushButton, QProgressBar,
    QSplitter, QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit,
    QVBoxLayout, QWidget,
)

from .models import CalSetSnapshot, ComplexSeries
from .reader import PnaClient, PnaCalSetReader
from .dump_service import dump_snapshot, write_manifest
from .workers import FunctionWorker
from .scpi import format_frequency, parse_csv_strings


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PNA CalSet Explorer")
        self.resize(1500, 920)
        self.client = PnaClient()
        self.reader: PnaCalSetReader | None = None
        self.current_snapshot: CalSetSnapshot | None = None
        self.thread_pool = QThreadPool.globalInstance()
        self._busy = False
        self._current_series: ComplexSeries | None = None
        self._build_ui()
        self._set_connected(False)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        row = QHBoxLayout()
        row.addWidget(QLabel("VISA Resource:"))
        self.resource_edit = QLineEdit("TCPIP0::127.0.0.1::hislip0::INSTR")
        row.addWidget(self.resource_edit, 1)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        row.addWidget(self.connect_btn)
        self.refresh_btn = QPushButton("Refresh CalSets")
        self.refresh_btn.clicked.connect(self.refresh_calsets)
        row.addWidget(self.refresh_btn)
        self.status_label = QLabel("Disconnected")
        row.addWidget(self.status_label)
        root.addLayout(row)

        self.idn_label = QLabel("Instrument: —")
        root.addWidget(self.idn_label)

        main_split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(main_split, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("CalSets"))
        self.calset_list = QListWidget()
        self.calset_list.currentTextChanged.connect(self.load_selected_calset)
        left_layout.addWidget(self.calset_list, 1)
        main_split.addWidget(left)

        right_split = QSplitter(Qt.Orientation.Vertical)
        main_split.addWidget(right_split)
        main_split.setSizes([280, 1100])

        upper = QWidget()
        upper_layout = QVBoxLayout(upper)

        self.info_table = QTableWidget(0, 2)
        self.info_table.setHorizontalHeaderLabels(["Field", "Value"])
        self.info_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.info_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.info_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.info_table.setMaximumHeight(220)
        upper_layout.addWidget(self.info_table)

        self.tabs = QTabWidget()
        upper_layout.addWidget(self.tabs, 1)
        self.standard_table = self._make_catalog_table()
        self.error_term_table = self._make_catalog_table()
        self.item_table = QTableWidget(0, 2)
        self.item_table.setHorizontalHeaderLabels(["Item", "Value"])
        self.item_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.item_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.item_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.tabs.addTab(self.standard_table, "Standards")
        self.tabs.addTab(self.error_term_table, "Error Terms")
        self.tabs.addTab(self.item_table, "CalSet Items")

        self.standard_table.cellClicked.connect(lambda row, col: self.show_series("standard", row))
        self.error_term_table.cellClicked.connect(lambda row, col: self.show_series("error_term", row))
        right_split.addWidget(upper)

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        view_row = QHBoxLayout()
        view_row.addWidget(QLabel("Plot:"))
        self.plot_mode = QComboBox()
        self.plot_mode.addItems(["Magnitude (dB)", "Magnitude", "Phase (deg)", "Real", "Imag"])
        self.plot_mode.currentIndexChanged.connect(self.redraw_current_series)
        view_row.addWidget(self.plot_mode)
        view_row.addStretch(1)
        lower_layout.addLayout(view_row)

        data_split = QSplitter(Qt.Orientation.Horizontal)
        self.data_table = QTableWidget(0, 6)
        self.data_table.setHorizontalHeaderLabels(["Index", "Frequency (Hz)", "Real", "Imag", "Magnitude", "Phase (deg)"])
        self.data_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        data_split.addWidget(self.data_table)
        data_split.addWidget(self.plot)
        data_split.setSizes([650, 650])
        lower_layout.addWidget(data_split, 1)

        right_split.addWidget(lower)
        right_split.setSizes([430, 390])

        action_row = QHBoxLayout()
        self.dump_selected_btn = QPushButton("Dump Selected CalSet")
        self.dump_selected_btn.clicked.connect(self.dump_selected)
        action_row.addWidget(self.dump_selected_btn)
        self.dump_all_btn = QPushButton("Dump All CalSets")
        self.dump_all_btn.clicked.connect(self.dump_all)
        action_row.addWidget(self.dump_all_btn)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        action_row.addWidget(self.progress, 1)
        root.addLayout(action_row)

        root.addWidget(QLabel("Log"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(180)
        root.addWidget(self.log_box)

    @staticmethod
    def _make_catalog_table() -> QTableWidget:
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Name", "Points", "Start", "Stop"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 4):
            table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        return table

    def log(self, message: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.append(f"{stamp}  {message}")

    def _set_busy(self, value: bool):
        self._busy = value
        self.connect_btn.setEnabled(not value)
        self.refresh_btn.setEnabled(self.client.connected and not value)
        self.dump_selected_btn.setEnabled(self.client.connected and not value)
        self.dump_all_btn.setEnabled(self.client.connected and not value)

    def _set_connected(self, value: bool):
        self.status_label.setText("Connected" if value else "Disconnected")
        self.connect_btn.setText("Disconnect" if value else "Connect")
        self.refresh_btn.setEnabled(value)
        self.dump_selected_btn.setEnabled(value)
        self.dump_all_btn.setEnabled(value)

    def toggle_connection(self):
        if self.client.connected:
            self.client.disconnect()
            self.reader = None
            self.calset_list.clear()
            self.current_snapshot = None
            self.idn_label.setText("Instrument: —")
            self._set_connected(False)
            self.log("Disconnected.")
            return

        self._set_busy(True)
        self.client = PnaClient(resource=self.resource_edit.text().strip())

        def task(progress):
            return self.client.connect()

        worker = FunctionWorker(task)
        worker.signals.result.connect(self._on_connected)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(lambda: self._set_busy(False))
        self.thread_pool.start(worker)

    def _on_connected(self, idn: str):
        self.reader = PnaCalSetReader(self.client, self.log)
        self.idn_label.setText(f"Instrument: {idn}")
        self._set_connected(True)
        self.log(f"Connected: {idn}")
        self.refresh_calsets()

    def refresh_calsets(self):
        if not self.client.connected or self._busy:
            return
        self._set_busy(True)

        def task(progress):
            raw = self.client.get_calset_catalog_raw()
            return {"raw": raw, "names": parse_csv_strings(raw)}

        worker = FunctionWorker(task)
        worker.signals.result.connect(self._populate_calsets)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(lambda: self._set_busy(False))
        self.thread_pool.start(worker)

    def _populate_calsets(self, result):
        raw = result.get("raw", "") if isinstance(result, dict) else ""
        names = result.get("names", []) if isinstance(result, dict) else result
        self.log(f"CSET:CAT? raw response: {raw}")
        self.calset_list.blockSignals(True)
        self.calset_list.clear()
        self.calset_list.addItems(names)
        self.calset_list.blockSignals(False)
        self.log(f"Parsed {len(names)} CalSet(s): {names}")
        if names:
            self.calset_list.setCurrentRow(0)

    def load_selected_calset(self, name: str):
        if not name or self._busy or not self.reader:
            return
        self._set_busy(True)
        self.progress.setValue(0)
        self.log(f"Loading CalSet: {name}")

        worker = FunctionWorker(self.reader.read_snapshot, name, True)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(self._show_snapshot)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(lambda: self._set_busy(False))
        self.thread_pool.start(worker)

    def _on_progress(self, text: str, current: int, total: int):
        self.log(text)
        self.progress.setValue(int(current * 100 / total) if total else 0)

    def _show_snapshot(self, snapshot: CalSetSnapshot):
        self.current_snapshot = snapshot
        self.progress.setValue(100)
        self._fill_info(snapshot)
        self._fill_series_catalog(self.standard_table, snapshot.standards)
        self._fill_series_catalog(self.error_term_table, snapshot.error_terms)
        self._fill_items(snapshot.items)
        self.log(f"Loaded {snapshot.name}: {len(snapshot.standards)} Standards, {len(snapshot.error_terms)} Error Terms.")
        if snapshot.standards:
            self.show_series("standard", 0)
        elif snapshot.error_terms:
            self.show_series("error_term", 0)

    def _fill_info(self, snapshot: CalSetSnapshot):
        rows = [("CalSet", snapshot.name)]
        for k, v in snapshot.info.items():
            if k not in ("standard_names", "error_term_names", "name"):
                rows.append((k, v))
        for k, v in snapshot.properties.items():
            if not k.endswith("_raw") and not isinstance(v, list):
                rows.append((k, v))
        self.info_table.setRowCount(len(rows))
        for r, (k, v) in enumerate(rows):
            self.info_table.setItem(r, 0, QTableWidgetItem(str(k)))
            self.info_table.setItem(r, 1, QTableWidgetItem("" if v is None else str(v)))

    @staticmethod
    def _fill_series_catalog(table: QTableWidget, series: list[ComplexSeries]):
        table.setRowCount(len(series))
        for r, s in enumerate(series):
            vals = [s.name, str(s.point_count), format_frequency(s.start_hz), format_frequency(s.stop_hz)]
            for c, value in enumerate(vals):
                table.setItem(r, c, QTableWidgetItem(value))

    def _fill_items(self, items: dict):
        self.item_table.setRowCount(len(items))
        for r, (k, v) in enumerate(items.items()):
            self.item_table.setItem(r, 0, QTableWidgetItem(str(k)))
            self.item_table.setItem(r, 1, QTableWidgetItem(str(v)))

    def show_series(self, kind: str, row: int):
        if not self.current_snapshot:
            return
        series_list = self.current_snapshot.standards if kind == "standard" else self.current_snapshot.error_terms
        if not (0 <= row < len(series_list)):
            return
        self._current_series = series_list[row]
        self._fill_data_table(self._current_series)
        self.redraw_current_series()

    def _fill_data_table(self, s: ComplexSeries):
        n = max(s.data.size, s.frequency_hz.size)
        shown = min(n, 10000)
        self.data_table.setRowCount(shown)
        for i in range(shown):
            freq = s.frequency_hz[i] if i < s.frequency_hz.size else np.nan
            z = s.data[i] if i < s.data.size else np.nan + 1j * np.nan
            vals = [
                str(i),
                f"{freq:.12g}" if np.isfinite(freq) else "",
                f"{z.real:.12g}" if np.isfinite(z.real) else "",
                f"{z.imag:.12g}" if np.isfinite(z.imag) else "",
                f"{abs(z):.12g}" if np.isfinite(abs(z)) else "",
                f"{np.angle(z, deg=True):.12g}" if np.isfinite(z.real) and np.isfinite(z.imag) else "",
            ]
            for c, value in enumerate(vals):
                self.data_table.setItem(i, c, QTableWidgetItem(value))
        if n > shown:
            self.log(f"Table view limited to first {shown} of {n} points; dump contains all points.")

    def redraw_current_series(self):
        s = self._current_series
        self.plot.clear()
        if not s or not s.data.size:
            return
        n = min(s.data.size, s.frequency_hz.size) if s.frequency_hz.size else s.data.size
        if not n:
            return
        x = s.frequency_hz[:n] / 1e9 if s.frequency_hz.size else np.arange(n)
        z = s.data[:n]
        mode = self.plot_mode.currentText()
        if mode == "Magnitude (dB)":
            with np.errstate(divide="ignore"):
                y = 20 * np.log10(np.abs(z))
            ylabel = "Magnitude (dB)"
        elif mode == "Magnitude":
            y, ylabel = np.abs(z), "Magnitude"
        elif mode == "Phase (deg)":
            y, ylabel = np.angle(z, deg=True), "Phase (deg)"
        elif mode == "Real":
            y, ylabel = z.real, "Real"
        else:
            y, ylabel = z.imag, "Imag"
        self.plot.plot(x, y)
        self.plot.setLabel("bottom", "Frequency", units="GHz" if s.frequency_hz.size else None)
        self.plot.setLabel("left", ylabel)
        self.plot.setTitle(s.name)

    def dump_selected(self):
        name = self.calset_list.currentItem().text() if self.calset_list.currentItem() else ""
        if not name or not self.reader:
            return
        directory = QFileDialog.getExistingDirectory(self, "Select dump directory")
        if not directory:
            return
        self._set_busy(True)
        self.progress.setValue(0)

        def task(progress):
            snapshot = self.reader.read_snapshot(name, True, progress)
            return str(dump_snapshot(snapshot, directory))

        worker = FunctionWorker(task)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(lambda path: self.log(f"Dump complete: {path}"))
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(lambda: self._set_busy(False))
        self.thread_pool.start(worker)

    def dump_all(self):
        if not self.reader:
            return
        directory = QFileDialog.getExistingDirectory(self, "Select parent directory for full dump")
        if not directory:
            return

        names = [self.calset_list.item(i).text() for i in range(self.calset_list.count())]
        if not names:
            return

        target = Path(directory) / f"PNA_CalSet_Dump_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        target.mkdir(parents=True, exist_ok=True)
        self._set_busy(True)
        self.progress.setValue(0)

        def task(progress):
            manifest = []
            for idx, name in enumerate(names):
                progress(f"[{idx + 1}/{len(names)}] {name}", idx, len(names))
                snapshot = self.reader.read_snapshot(name, True)
                path = dump_snapshot(snapshot, target)
                manifest.append({
                    "name": name,
                    "folder": path.name,
                    "standard_count": len(snapshot.standards),
                    "error_term_count": len(snapshot.error_terms),
                    "failed_query_count": len([a for a in snapshot.audit if not a.ok]),
                })
            write_manifest(target, self.client.idn, self.client.resource, manifest)
            progress("Done", len(names), len(names))
            return str(target)

        worker = FunctionWorker(task)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(lambda path: self.log(f"Full dump complete: {path}"))
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(lambda: self._set_busy(False))
        self.thread_pool.start(worker)

    def _on_worker_error(self, text: str):
        self.log(text)
        QMessageBox.critical(self, "Operation failed", text)

    def closeEvent(self, event):
        self.client.disconnect()
        event.accept()


def run_app() -> int:
    app = QApplication(sys.argv)
    pg.setConfigOptions(antialias=True)
    window = MainWindow()
    window.show()
    return app.exec()
