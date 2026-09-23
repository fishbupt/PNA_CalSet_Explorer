from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QThreadPool
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu,
    QMessageBox, QPushButton, QProgressBar, QProgressDialog, QSplitter,
    QTabWidget, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
    QWidget,
)

from .models import CalSetSnapshot, ComplexSeries
from .reader import PnaClient, PnaCalSetReader
from .dump_service import dump_snapshot, write_manifest
from .workers import FunctionWorker
from .scpi import format_frequency, parse_csv_strings


APP_STYLE = """
QMainWindow, QWidget {
    background-color: #0f172a;
    color: #e5e7eb;
    font-family: "Segoe UI", "Microsoft YaHei UI";
    font-size: 13px;
}

QFrame#TopBar, QFrame#SideCard, QFrame#ContentCard, QFrame#ActionCard, QFrame#LogCard {
    background-color: #111827;
    border: 1px solid #243041;
    border-radius: 12px;
}

QLabel#Title {
    font-size: 22px;
    font-weight: 700;
    color: #f8fafc;
}

QLabel#Subtitle {
    font-size: 12px;
    color: #94a3b8;
}

QLabel#SectionTitle {
    font-size: 13px;
    font-weight: 700;
    color: #cbd5e1;
}

QLabel#ConnectionStatus {
    padding: 5px 10px;
    border-radius: 10px;
    font-weight: 700;
}

QLineEdit, QComboBox {
    background-color: #0b1220;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 7px 10px;
    min-height: 20px;
    color: #e5e7eb;
    selection-background-color: #2563eb;
}

QLineEdit:focus, QComboBox:focus {
    border: 1px solid #3b82f6;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QPushButton {
    background-color: #1e293b;
    color: #e5e7eb;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 7px 14px;
    min-height: 20px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #273449;
    border-color: #475569;
}

QPushButton:pressed {
    background-color: #0f172a;
}

QPushButton:disabled {
    color: #64748b;
    background-color: #111827;
    border-color: #1f2937;
}

QPushButton#PrimaryButton {
    background-color: #2563eb;
    border-color: #2563eb;
    color: white;
}

QPushButton#PrimaryButton:hover {
    background-color: #1d4ed8;
}

QPushButton#SuccessButton {
    background-color: #047857;
    border-color: #047857;
    color: white;
}

QPushButton#SuccessButton:hover {
    background-color: #059669;
}

QListWidget, QTableWidget, QTextEdit {
    background-color: #0b1220;
    alternate-background-color: #0f172a;
    border: 1px solid #243041;
    border-radius: 8px;
    gridline-color: #1f2937;
    color: #dbeafe;
    selection-background-color: #1d4ed8;
    selection-color: white;
}

QListWidget {
    padding: 6px;
    outline: none;
}

QListWidget::item {
    padding: 8px 10px;
    margin: 2px 0;
    border-radius: 6px;
}

QListWidget::item:hover {
    background-color: #172033;
}

QListWidget::item:selected {
    background-color: #1d4ed8;
}

QHeaderView::section {
    background-color: #162033;
    color: #cbd5e1;
    border: none;
    border-right: 1px solid #243041;
    border-bottom: 1px solid #243041;
    padding: 7px 8px;
    font-weight: 700;
}

QTableWidget {
    outline: none;
}

QTableWidget::item {
    padding: 4px 6px;
}

QTabWidget::pane {
    border: 1px solid #243041;
    border-radius: 8px;
    background-color: #0b1220;
    top: -1px;
}

QTabBar::tab {
    background-color: transparent;
    color: #94a3b8;
    padding: 8px 16px;
    margin-right: 2px;
    border-bottom: 2px solid transparent;
}

QTabBar::tab:hover {
    color: #e2e8f0;
}

QTabBar::tab:selected {
    color: #60a5fa;
    border-bottom: 2px solid #3b82f6;
}

QProgressBar {
    background-color: #0b1220;
    border: 1px solid #243041;
    border-radius: 7px;
    height: 12px;
    text-align: center;
    color: transparent;
}

QProgressBar::chunk {
    background-color: #3b82f6;
    border-radius: 6px;
}

QSplitter::handle {
    background-color: #0f172a;
}

QSplitter::handle:hover {
    background-color: #334155;
}

QScrollBar:vertical {
    background: #0b1220;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #334155;
    border-radius: 5px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background: #475569;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PNA CalSet Explorer")
        self.resize(1560, 960)

        self.client = PnaClient()
        self.reader: PnaCalSetReader | None = None
        self.current_snapshot: CalSetSnapshot | None = None
        self.thread_pool = QThreadPool.globalInstance()
        self._busy = False
        self._current_series: ComplexSeries | None = None
        self._loading_dialog: QProgressDialog | None = None

        self._build_ui()
        self._configure_plot()
        self._set_connected(False)

    def _make_card(self, object_name: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName(object_name)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        return card, layout

    def _section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        header_row = QHBoxLayout()
        title_group = QVBoxLayout()
        title_group.setSpacing(1)
        title = QLabel("PNA CalSet Explorer")
        title.setObjectName("Title")
        subtitle = QLabel("Keysight PNA / PNA-X 校准集浏览与 Golden Data 导出工具")
        subtitle.setObjectName("Subtitle")
        title_group.addWidget(title)
        title_group.addWidget(subtitle)
        header_row.addLayout(title_group)
        header_row.addStretch(1)
        root.addLayout(header_row)

        top_card, top_layout = self._make_card("TopBar")
        connection_row = QHBoxLayout()
        connection_row.setSpacing(10)
        connection_row.addWidget(QLabel("VISA 地址"))

        self.resource_edit = QLineEdit("TCPIP0::127.0.0.1::hislip0::INSTR")
        self.resource_edit.setPlaceholderText("输入 VISA Resource")
        connection_row.addWidget(self.resource_edit, 1)

        self.connect_btn = QPushButton("连接")
        self.connect_btn.setObjectName("PrimaryButton")
        self.connect_btn.clicked.connect(self.toggle_connection)
        connection_row.addWidget(self.connect_btn)

        self.refresh_btn = QPushButton("刷新 CalSet")
        self.refresh_btn.clicked.connect(self.refresh_calsets)
        connection_row.addWidget(self.refresh_btn)

        self.status_label = QLabel("未连接")
        self.status_label.setObjectName("ConnectionStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        connection_row.addWidget(self.status_label)
        top_layout.addLayout(connection_row)

        self.idn_label = QLabel("仪表：—")
        self.idn_label.setObjectName("Subtitle")
        top_layout.addWidget(self.idn_label)
        root.addWidget(top_card)

        main_split = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(main_split, 1)

        side_card, side_layout = self._make_card("SideCard")
        side_layout.addWidget(self._section_title("CalSet"))
        self.calset_list = QListWidget()
        self.calset_list.currentTextChanged.connect(self.load_selected_calset)
        self.calset_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.calset_list.customContextMenuRequested.connect(
            self._show_calset_context_menu
        )
        side_layout.addWidget(self.calset_list, 1)
        main_split.addWidget(side_card)

        content_card, content_layout = self._make_card("ContentCard")
        right_split = QSplitter(Qt.Orientation.Vertical)
        content_layout.addWidget(right_split, 1)
        main_split.addWidget(content_card)
        main_split.setSizes([300, 1200])

        upper = QWidget()
        upper_layout = QVBoxLayout(upper)
        upper_layout.setContentsMargins(0, 0, 0, 0)
        upper_layout.setSpacing(8)

        self.tabs = QTabWidget()
        upper_layout.addWidget(self.tabs, 1)

        self.standard_table = self._make_catalog_table()
        self.error_term_table = self._make_catalog_table()
        self.item_table = QTableWidget(0, 2)
        self.item_table.setHorizontalHeaderLabels(["Item", "值"])
        self.item_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.item_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.item_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.item_table.setAlternatingRowColors(True)

        self.tabs.addTab(self.standard_table, "Standards")
        self.tabs.addTab(self.error_term_table, "Error Terms")
        self.tabs.addTab(self.item_table, "CalSet Items")

        self.standard_table.cellClicked.connect(lambda row, col: self.show_series("standard", row))
        self.error_term_table.cellClicked.connect(lambda row, col: self.show_series("error_term", row))
        right_split.addWidget(upper)

        lower = QWidget()
        lower_layout = QVBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.setSpacing(8)

        plot_toolbar = QHBoxLayout()
        plot_toolbar.addWidget(self._section_title("数据查看"))
        plot_toolbar.addStretch(1)
        plot_toolbar.addWidget(QLabel("显示格式"))
        self.plot_mode = QComboBox()
        self.plot_mode.addItems(["Magnitude (dB)", "Magnitude", "Phase (deg)", "Real", "Imag"])
        self.plot_mode.currentIndexChanged.connect(self.redraw_current_series)
        plot_toolbar.addWidget(self.plot_mode)
        lower_layout.addLayout(plot_toolbar)

        data_split = QSplitter(Qt.Orientation.Horizontal)
        self.data_table = QTableWidget(0, 6)
        self.data_table.setHorizontalHeaderLabels(
            ["序号", "Frequency (Hz)", "Real", "Imag", "Magnitude", "Phase (deg)"]
        )
        self.data_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.data_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.data_table.setAlternatingRowColors(True)

        self.plot = pg.PlotWidget()
        data_split.addWidget(self.data_table)
        data_split.addWidget(self.plot)
        data_split.setSizes([620, 720])
        lower_layout.addWidget(data_split, 1)

        right_split.addWidget(lower)
        right_split.setSizes([430, 410])

        action_card, action_layout = self._make_card("ActionCard")
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.dump_selected_btn = QPushButton("导出当前 CalSet")
        self.dump_selected_btn.setObjectName("SuccessButton")
        self.dump_selected_btn.clicked.connect(self.dump_selected)
        action_row.addWidget(self.dump_selected_btn)

        self.dump_all_btn = QPushButton("导出全部 CalSet")
        self.dump_all_btn.clicked.connect(self.dump_all)
        action_row.addWidget(self.dump_all_btn)

        action_row.addStretch(1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedWidth(320)
        action_row.addWidget(self.progress)
        action_layout.addLayout(action_row)
        root.addWidget(action_card)

        log_card, log_layout = self._make_card("LogCard")
        log_layout.addWidget(self._section_title("运行日志"))
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumHeight(155)
        log_layout.addWidget(self.log_box)
        root.addWidget(log_card)

    def _configure_plot(self):
        self.plot.setBackground("#0b1220")
        self.plot.showGrid(x=True, y=True, alpha=0.18)
        self.plot.getAxis("bottom").setPen(pg.mkPen("#64748b"))
        self.plot.getAxis("left").setPen(pg.mkPen("#64748b"))
        self.plot.getAxis("bottom").setTextPen(pg.mkPen("#cbd5e1"))
        self.plot.getAxis("left").setTextPen(pg.mkPen("#cbd5e1"))

    @staticmethod
    def _make_catalog_table() -> QTableWidget:
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["名称", "点数", "起始频率", "终止频率"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setAlternatingRowColors(True)
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
        self.status_label.setText("已连接" if value else "未连接")
        self.connect_btn.setText("断开" if value else "连接")
        self.refresh_btn.setEnabled(value)
        self.dump_selected_btn.setEnabled(value)
        self.dump_all_btn.setEnabled(value)

        if value:
            self.status_label.setStyleSheet(
                "background-color:#064e3b; color:#6ee7b7; border:1px solid #047857;"
            )
        else:
            self.status_label.setStyleSheet(
                "background-color:#3f1d1d; color:#fca5a5; border:1px solid #7f1d1d;"
            )

    def toggle_connection(self):
        if self.client.connected:
            self.client.disconnect()
            self.reader = None
            self.calset_list.clear()
            self._clear_calset_content()
            self.idn_label.setText("仪表：—")
            self._set_connected(False)
            self.log("已断开连接。")
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
        self.idn_label.setText(f"仪表：{idn}")
        self._set_connected(True)
        self.log(f"连接成功：{idn}")
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
        self.log(f"CSET:CAT? 原始返回：{raw}")

        self.calset_list.blockSignals(True)
        self.calset_list.clear()
        self.calset_list.addItems(names)
        self.calset_list.blockSignals(False)

        self.log(f"解析得到 {len(names)} 个 CalSet：{names}")
        if names:
            self.calset_list.setCurrentRow(0)

    def load_selected_calset(self, name: str):
        if not name or self._busy or not self.reader:
            return

        self._set_busy(True)
        self._clear_calset_content()
        self.progress.setValue(0)
        self.log(f"正在读取 CalSet：{name}")
        self._show_loading_dialog(name)

        worker = FunctionWorker(self.reader.read_snapshot, name, True)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(self._show_snapshot)
        worker.signals.error.connect(self._on_calset_load_error)
        worker.signals.finished.connect(self._finish_calset_load)
        self.thread_pool.start(worker)

    def _on_progress(self, text: str, current: int, total: int):
        self.log(text)
        value = int(current * 100 / total) if total else 0
        self.progress.setValue(value)
        if self._loading_dialog is not None:
            self._loading_dialog.setLabelText(text)
            self._loading_dialog.setValue(value)

    def _show_snapshot(self, snapshot: CalSetSnapshot):
        self.current_snapshot = snapshot
        self.progress.setValue(100)
        self._fill_series_catalog(self.standard_table, snapshot.standards)
        self._fill_series_catalog(self.error_term_table, snapshot.error_terms)
        self._fill_items(snapshot.items)

        self.log(
            f"读取完成 {snapshot.name}："
            f"{len(snapshot.standards)} 个 Standard，"
            f"{len(snapshot.error_terms)} 个 Error Term。"
        )

        if snapshot.standards:
            self.show_series("standard", 0)
        elif snapshot.error_terms:
            self.show_series("error_term", 0)

    def _clear_calset_content(self):
        """切换 CalSet 时立即清空旧内容，避免误以为旧数据属于新 CalSet。"""
        self.current_snapshot = None
        self._current_series = None

        self.standard_table.setRowCount(0)
        self.error_term_table.setRowCount(0)
        self.item_table.setRowCount(0)
        self.data_table.setRowCount(0)
        self.plot.clear()

    def _show_loading_dialog(self, calset_name: str):
        dialog = QProgressDialog(
            f"正在从 PNA 读取 CalSet：{calset_name}\n请稍候…",
            "",
            0,
            100,
            self,
        )
        dialog.setWindowTitle("正在更新数据")
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setValue(0)
        dialog.setMinimumWidth(430)
        dialog.show()
        self._loading_dialog = dialog

    def _finish_calset_load(self):
        if self._loading_dialog is not None:
            self._loading_dialog.close()
            self._loading_dialog.deleteLater()
            self._loading_dialog = None
        self._set_busy(False)

    def _on_calset_load_error(self, text: str):
        self._clear_calset_content()
        self._on_worker_error(text)

    def _show_calset_context_menu(self, pos):
        item = self.calset_list.itemAt(pos)
        if item is None:
            return

        menu = QMenu(self)
        info_action = menu.addAction("查看 CalSet 信息")
        action = menu.exec(self.calset_list.viewport().mapToGlobal(pos))

        if action == info_action:
            self._show_calset_info_dialog(item.text())

    def _show_calset_info_dialog(self, calset_name: str):
        snapshot = self.current_snapshot
        if snapshot is None or snapshot.name != calset_name:
            QMessageBox.information(
                self,
                "CalSet 信息",
                "请先左键选择该 CalSet，等待读取完成后再查看详细信息。",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"CalSet 信息 - {calset_name}")
        dialog.resize(760, 620)

        layout = QVBoxLayout(dialog)
        title = QLabel(calset_name)
        title.setObjectName("Title")
        layout.addWidget(title)

        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["字段", "值"])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )

        rows = [("CalSet", snapshot.name)]
        for key, value in snapshot.info.items():
            if key != "name":
                rows.append((key, value))
        for key, value in snapshot.properties.items():
            rows.append((key, value))
        for key, value in snapshot.items.items():
            rows.append((f"ITEM / {key}", value))

        table.setRowCount(len(rows))
        for row, (key, value) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(str(key)))
            table.setItem(row, 1, QTableWidgetItem("" if value is None else str(value)))

        layout.addWidget(table, 1)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        dialog.exec()

    @staticmethod
    def _fill_series_catalog(table: QTableWidget, series: list[ComplexSeries]):
        table.setRowCount(len(series))

        for r, s in enumerate(series):
            vals = [
                s.name,
                str(s.point_count),
                format_frequency(s.start_hz),
                format_frequency(s.stop_hz),
            ]

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

        series_list = (
            self.current_snapshot.standards
            if kind == "standard"
            else self.current_snapshot.error_terms
        )

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
                f"{np.angle(z, deg=True):.12g}"
                if np.isfinite(z.real) and np.isfinite(z.imag)
                else "",
            ]

            for c, value in enumerate(vals):
                self.data_table.setItem(i, c, QTableWidgetItem(value))

        if n > shown:
            self.log(f"表格仅显示前 {shown}/{n} 个点；Dump 会保存全部数据。")

    def redraw_current_series(self):
        s = self._current_series
        self.plot.clear()

        if not s or not s.data.size:
            return

        n = (
            min(s.data.size, s.frequency_hz.size)
            if s.frequency_hz.size
            else s.data.size
        )

        if not n:
            return

        x = (
            s.frequency_hz[:n] / 1e9
            if s.frequency_hz.size
            else np.arange(n)
        )
        z = s.data[:n]
        mode = self.plot_mode.currentText()

        if mode == "Magnitude (dB)":
            with np.errstate(divide="ignore"):
                y = 20 * np.log10(np.abs(z))
            ylabel = "Magnitude (dB)"
        elif mode == "Magnitude":
            y = np.abs(z)
            ylabel = "Magnitude"
        elif mode == "Phase (deg)":
            y = np.angle(z, deg=True)
            ylabel = "Phase (deg)"
        elif mode == "Real":
            y = z.real
            ylabel = "Real"
        else:
            y = z.imag
            ylabel = "Imag"

        pen = pg.mkPen("#60a5fa", width=1.6)
        self.plot.plot(x, y, pen=pen)
        self.plot.setLabel(
            "bottom",
            "Frequency",
            units="GHz" if s.frequency_hz.size else None,
        )
        self.plot.setLabel("left", ylabel)
        self.plot.setTitle(
            f"<span style='color:#e2e8f0;font-size:12pt'>{s.name}</span>"
        )

    def dump_selected(self):
        name = (
            self.calset_list.currentItem().text()
            if self.calset_list.currentItem()
            else ""
        )

        if not name or not self.reader:
            return

        directory = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not directory:
            return

        self._set_busy(True)
        self.progress.setValue(0)

        def task(progress):
            snapshot = self.reader.read_snapshot(name, True, progress)
            return str(dump_snapshot(snapshot, directory))

        worker = FunctionWorker(task)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(
            lambda path: self.log(f"导出完成：{path}")
        )
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(lambda: self._set_busy(False))
        self.thread_pool.start(worker)

    def dump_all(self):
        if not self.reader:
            return

        directory = QFileDialog.getExistingDirectory(
            self,
            "选择全部 CalSet 的导出目录",
        )

        if not directory:
            return

        names = [
            self.calset_list.item(i).text()
            for i in range(self.calset_list.count())
        ]

        if not names:
            return

        target = (
            Path(directory)
            / f"PNA_CalSet_Dump_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        target.mkdir(parents=True, exist_ok=True)

        self._set_busy(True)
        self.progress.setValue(0)

        def task(progress):
            manifest = []

            for idx, name in enumerate(names):
                progress(
                    f"[{idx + 1}/{len(names)}] {name}",
                    idx,
                    len(names),
                )

                snapshot = self.reader.read_snapshot(name, True)
                path = dump_snapshot(snapshot, target)

                manifest.append(
                    {
                        "name": name,
                        "folder": path.name,
                        "standard_count": len(snapshot.standards),
                        "error_term_count": len(snapshot.error_terms),
                        "failed_query_count": len(
                            [a for a in snapshot.audit if not a.ok]
                        ),
                    }
                )

            write_manifest(
                target,
                self.client.idn,
                self.client.resource,
                manifest,
            )

            progress("完成", len(names), len(names))
            return str(target)

        worker = FunctionWorker(task)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.result.connect(
            lambda path: self.log(f"全部 CalSet 导出完成：{path}")
        )
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(lambda: self._set_busy(False))
        self.thread_pool.start(worker)

    def _on_worker_error(self, text: str):
        self.log(text)
        QMessageBox.critical(self, "操作失败", text)

    def closeEvent(self, event):
        self.client.disconnect()
        event.accept()


def run_app() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)

    font = QFont("Segoe UI", 10)
    app.setFont(font)

    pg.setConfigOptions(antialias=True)

    window = MainWindow()
    window.show()

    return app.exec()
