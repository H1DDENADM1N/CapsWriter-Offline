import sys
import webbrowser

import qrcode
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from util.client.cloud_clipboard import CloudClipboard


class QRCODE(QWidget):
    def __init__(self, text, qr_data):
        super().__init__()
        self.qr_data = qr_data  # Store the URL for opening later

        self.setWindowTitle("Text and QR Code Display")
        layout = QVBoxLayout(self)

        # Create a label for the text
        text_label = QLabel(text)
        text_label.setOpenExternalLinks(True)
        text_label.setTextFormat(Qt.TextFormat.RichText)
        text_label.setText(f"<a href='{text}'>{text}</a>")
        layout.addWidget(text_label)

        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(qr_data)
        qr.make(fit=True)

        # Create QR code image using Qt instead of PIL
        qr_matrix = qr.get_matrix()
        self.create_qr_image_from_matrix(qr_matrix, layout)

    def create_qr_image_from_matrix(self, qr_matrix, layout):
        """Create QR code image from matrix data using Qt"""
        # Calculate image size
        matrix_size = len(qr_matrix)
        box_size = 10  # Pixel size for each QR code module
        border = 4
        size = (matrix_size + 2 * border) * box_size

        # Create QImage
        image = QImage(size, size, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))

        # Create painter
        painter = QPainter(image)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("black"))

        # Draw QR code modules
        for y in range(matrix_size):
            for x in range(matrix_size):
                if qr_matrix[y][x]:
                    # Draw black square for QR module
                    rect_x = (x + border) * box_size
                    rect_y = (y + border) * box_size
                    painter.drawRect(rect_x, rect_y, box_size, box_size)

        painter.end()

        # Create pixmap and label for the QR code
        qr_pixmap = QPixmap.fromImage(image)
        qr_label = QLabel()
        qr_label.setPixmap(qr_pixmap)
        qr_label.mousePressEvent = self.open_url
        layout.addWidget(qr_label)

    def open_url(self, event):
        webbrowser.open(self.qr_data)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()


def utf8_byte_count(s):
    return len(s.encode("utf-8"))


def truncate_utf8(s, max_bytes=1024):
    byte_count = len(s.encode("utf-8"))

    if byte_count > max_bytes:
        # Encoding the string to UTF-8 and then slicing the byte array
        truncated_bytes = s.encode("utf-8")[:max_bytes]
        # Decoding the sliced byte array back to string
        s = truncated_bytes.decode("utf-8", errors="ignore")

    return s


def CloudClipboardShowQRCode(text):
    url = CloudClipboard().post_data(text)
    qrcode = QRCODE(url, url)
    qrcode.show()


if __name__ == "__main__":
    args = sys.argv
    text = " ".join(args[1:])
    app = QApplication([])
    CloudClipboardShowQRCode(text)
    sys.exit(app.exec())
