from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont


class HexView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self._header = QLabel("")
        self._header.setWordWrap(True)
        self._header.setVisible(False)
        self._header.setStyleSheet("color: #8fa0b2;")
        root.addWidget(self._header)

        self._table = QTableWidget(0, 18)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        font = QFont("Consolas", 9)
        self._table.setFont(font)
        headers = ["Offset"] + [f"{i:02X}" for i in range(16)] + ["ASCII"]
        self._table.setHorizontalHeaderLabels(headers)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 84)
        for i in range(1, 17):
            self._table.setColumnWidth(i, 34)
        root.addWidget(self._table, stretch=1)

    def set_bytes(self, data: bytes, header: str = "", max_rows: int | None = None):
        self._header.setVisible(bool(header))
        self._header.setText(header)
        if max_rows is not None:
            data = data[: max_rows * 16]
        rows = (len(data) + 15) // 16 if data else 0
        self._table.clearContents()
        self._table.setRowCount(rows)
        ascii_brush = QBrush(QColor("#b9c7d4"))
        offset_brush = QBrush(QColor("#8fa0b2"))
        for row in range(rows):
            offset = row * 16
            chunk = data[offset:offset + 16]
            off_item = QTableWidgetItem(f"{offset:06X}")
            off_item.setForeground(offset_brush)
            self._table.setItem(row, 0, off_item)
            ascii_chars = []
            for idx in range(16):
                col = idx + 1
                if idx < len(chunk):
                    value = chunk[idx]
                    item = QTableWidgetItem(f"{value:02X}")
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self._table.setItem(row, col, item)
                    ascii_chars.append(chr(value) if 32 <= value < 127 else ".")
                else:
                    item = QTableWidgetItem("")
                    self._table.setItem(row, col, item)
                    ascii_chars.append(" ")
            ascii_item = QTableWidgetItem("".join(ascii_chars))
            ascii_item.setForeground(ascii_brush)
            self._table.setItem(row, 17, ascii_item)
        self._table.setUpdatesEnabled(True)

    def set_message(self, text: str):
        self._header.setVisible(True)
        self._header.setText(text)
        self._table.clearContents()
        self._table.setRowCount(0)
