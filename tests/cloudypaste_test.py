import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from util.client.cloud_clipboard_show_qrcode import CloudClipboardShowQRCode


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.resize(425, 425)
        self.setWindowTitle("Window Title")
        self.setWindowOpacity(0.9)

        self.text_box = QTextEdit()
        self.text_box_wordCountLabel = QLabel("字数: 0", self)
        self.text_box_wordCountLabel.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.text_box.textChanged.connect(self.updateWordCount)
        self.text_box.selectionChanged.connect(self.updateWordCount)
        self.checkbox = QCheckBox("勾选")
        self.checkbox2 = QCheckBox("置顶")
        self.checkbox2.stateChanged.connect(self.toggle_window_stay_on_top)
        self.checkbox2.setChecked(True)
        self.button = QPushButton("清空")
        self.button.clicked.connect(lambda: self.text_box.clear())
        self.button2 = QPushButton("云贴")
        self.button2.clicked.connect(lambda: self.cloudy_text_box())

        self.layout = QVBoxLayout()
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.layout2 = QHBoxLayout()
        self.layout2.setSpacing(0)
        self.layout2.setContentsMargins(0, 0, 0, 0)

        self.layout.addWidget(self.text_box)
        self.layout2.addWidget(self.checkbox)
        self.layout2.addWidget(self.checkbox2)
        self.layout2.addWidget(self.text_box_wordCountLabel)
        self.layout2.addWidget(self.button2)
        self.layout2.addWidget(self.button)
        self.layout.addLayout(self.layout2)

        central_widget = QWidget()
        central_widget.setLayout(self.layout)
        self.setCentralWidget(central_widget)

        self.text_box.append("Hello World...")

    def cloudy_text_box(self):
        text = self.text_box.toPlainText()
        CloudClipboardShowQRCode(text)

    def toggle_window_stay_on_top(self):
        if self.windowFlags() & Qt.WindowStaysOnTopHint:
            self.setWindowFlags(self.windowFlags() ^ Qt.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.show()

    def enterEvent(self, event):
        super().enterEvent(event)
        for i in range(self.layout2.count()):
            widget = self.layout2.itemAt(i).widget()
            if widget is not None:
                widget.setVisible(True)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        for i in range(self.layout2.count()):
            widget = self.layout2.itemAt(i).widget()
            if widget is not None:
                widget.setVisible(False)

    def updateWordCount(self):
        self.text_box_wordCountLabel.setText(
            f"{len(self.text_box.textCursor().selectedText())} / {len(self.text_box.toPlainText())}"
        )


def test_gui():
    app = QApplication([])
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    test_gui()
