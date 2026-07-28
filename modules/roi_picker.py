"""Interactive ROI picker: draw a rectangle on a video frame (for motion tracking)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class _RoiCanvas(QWidget):
    roi_changed = Signal(object)  # QRect in image pixel coords, or None

    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self._image = image
        self._pixmap = QPixmap.fromImage(image)
        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._roi: QRect | None = None
        self.setMinimumSize(480, 360)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

    def sizeHint(self):
        return self._pixmap.size().boundedTo(self._pixmap.size().scaled(900, 700, Qt.AspectRatioMode.KeepAspectRatio))

    def _scale(self):
        w, h = self.width(), self.height()
        iw, ih = self._image.width(), self._image.height()
        if iw < 1 or ih < 1 or w < 1 or h < 1:
            return 1.0, 0, 0
        s = min(w / iw, h / ih)
        ox = int((w - iw * s) / 2)
        oy = int((h - ih * s) / 2)
        return s, ox, oy

    def _to_image(self, pos: QPoint) -> QPoint:
        s, ox, oy = self._scale()
        if s <= 0:
            return QPoint(0, 0)
        x = int((pos.x() - ox) / s)
        y = int((pos.y() - oy) / s)
        x = max(0, min(self._image.width() - 1, x))
        y = max(0, min(self._image.height() - 1, y))
        return QPoint(x, y)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            p = self._to_image(event.position().toPoint())
            self._origin = p
            self._current = p
            self._roi = None
            self.update()

    def mouseMoveEvent(self, event):
        if self._origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._current = self._to_image(event.position().toPoint())
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._origin is not None:
            self._current = self._to_image(event.position().toPoint())
            rect = QRect(self._origin, self._current).normalized()
            if rect.width() >= 8 and rect.height() >= 8:
                self._roi = rect
                self.roi_changed.emit(rect)
            else:
                self._roi = None
                self.roi_changed.emit(None)
            self._origin = None
            self._current = None
            self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0b1220"))
        s, ox, oy = self._scale()
        dw = int(self._image.width() * s)
        dh = int(self._image.height() * s)
        target = QRect(ox, oy, dw, dh)
        painter.drawPixmap(target, self._pixmap)
        rect = self._roi
        if rect is None and self._origin is not None and self._current is not None:
            rect = QRect(self._origin, self._current).normalized()
        if rect is not None and rect.isValid():
            draw = QRect(
                ox + int(rect.x() * s),
                oy + int(rect.y() * s),
                max(2, int(rect.width() * s)),
                max(2, int(rect.height() * s)),
            )
            painter.setPen(QPen(QColor("#38bdf8"), 2, Qt.PenStyle.SolidLine))
            painter.setBrush(QColor(56, 189, 248, 40))
            painter.drawRect(draw)

    def roi(self) -> QRect | None:
        return self._roi


def grab_frame_image(video_path, position_ms: int = 0) -> QImage:
    import cv2

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频：{Path(video_path).name}")
    try:
        if position_ms > 0:
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0, int(position_ms)))
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok or frame is None:
            raise RuntimeError("无法读取视频画面。")
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        return QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
    finally:
        cap.release()


class RoiPickerDialog(QDialog):
    """Draw a rectangle on the current video frame; returns percentages 0–100."""

    def __init__(self, video_path, position_ms: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("绘制追踪区域")
        self.resize(920, 640)
        self._video_path = str(video_path)
        self._position_ms = int(position_ms or 0)
        self._result = None  # (x,y,w,h) percent

        image = grab_frame_image(self._video_path, self._position_ms)
        root = QVBoxLayout(self)
        tip = QLabel(
            "在画面上按住左键拖拽框选要跟踪的物体（人脸、车牌等），松开后点「开始追踪」。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#7dd3fc;")
        root.addWidget(tip)
        self.canvas = _RoiCanvas(image)
        self.canvas.roi_changed.connect(self._on_roi)
        root.addWidget(self.canvas, 1)
        self.status = QLabel("尚未框选")
        self.status.setStyleSheet("color:#94a3b8;")
        root.addWidget(self.status)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("使用此区域")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._image_size = (image.width(), image.height())

    def _on_roi(self, rect: QRect | None):
        if rect is None or not rect.isValid():
            self._result = None
            self._ok.setEnabled(False)
            self.status.setText("尚未框选")
            return
        iw, ih = self._image_size
        x = rect.x() / iw * 100
        y = rect.y() / ih * 100
        w = rect.width() / iw * 100
        h = rect.height() / ih * 100
        self._result = (x, y, w, h)
        self._ok.setEnabled(True)
        self.status.setText(
            f"区域：X={x:.1f}%  Y={y:.1f}%  宽={w:.1f}%  高={h:.1f}%  （图像 {iw}×{ih}）"
        )

    def percentages(self):
        """Return (x, y, w, h) in 0–100 percent, or None."""
        return self._result
