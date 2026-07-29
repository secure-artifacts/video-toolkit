"""Interactive ROI picker: rectangle or free polygon on a video frame."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QPolygon
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
    roi_changed = Signal(object)  # {"rect": QRect, "polygon": [QPoint, ...]} or None

    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self._image = image
        self._pixmap = QPixmap.fromImage(image)
        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._roi: QRect | None = None
        self._mode = "rect"
        self._polygon: list[QPoint] = []
        self._hover: QPoint | None = None
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
        if self._mode == "polygon":
            if event.button() == Qt.MouseButton.LeftButton:
                point = self._to_image(event.position().toPoint())
                self._polygon.append(point)
                self._hover = point
                self._emit_polygon()
                self.update()
            elif event.button() == Qt.MouseButton.RightButton:
                self.finish_polygon()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            p = self._to_image(event.position().toPoint())
            self._origin = p
            self._current = p
            self._roi = None
            self.update()

    def mouseMoveEvent(self, event):
        if self._mode == "polygon":
            self._hover = self._to_image(event.position().toPoint())
            self.update()
            return
        if self._origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._current = self._to_image(event.position().toPoint())
            self.update()

    def mouseReleaseEvent(self, event):
        if self._mode == "polygon":
            return
        if event.button() == Qt.MouseButton.LeftButton and self._origin is not None:
            self._current = self._to_image(event.position().toPoint())
            rect = QRect(self._origin, self._current).normalized()
            if rect.width() >= 8 and rect.height() >= 8:
                self._roi = rect
                self.roi_changed.emit({"rect": rect, "polygon": []})
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
        if self._polygon:
            points = [
                QPoint(ox + int(point.x() * s), oy + int(point.y() * s))
                for point in self._polygon
            ]
            painter.setPen(QPen(QColor("#f59e0b"), 2, Qt.PenStyle.SolidLine))
            painter.setBrush(QColor(245, 158, 11, 48) if len(points) >= 3 else Qt.BrushStyle.NoBrush)
            if len(points) >= 3:
                painter.drawPolygon(QPolygon(points))
            elif len(points) >= 2:
                painter.drawPolyline(QPolygon(points))
            for point in points:
                painter.setBrush(QColor("#f8fafc"))
                painter.drawEllipse(point, 4, 4)
            if self._hover is not None and points:
                hover = QPoint(
                    ox + int(self._hover.x() * s),
                    oy + int(self._hover.y() * s),
                )
                painter.setPen(QPen(QColor("#fbbf24"), 1, Qt.PenStyle.DashLine))
                painter.drawLine(points[-1], hover)

    def roi(self) -> QRect | None:
        return self._roi

    def set_mode(self, mode: str):
        self._mode = "polygon" if mode == "polygon" else "rect"
        self._origin = None
        self._current = None
        self._roi = None
        self._polygon = []
        self._hover = None
        self.roi_changed.emit(None)
        self.update()

    def undo_polygon_point(self):
        if self._polygon:
            self._polygon.pop()
        self._emit_polygon()
        self.update()

    def finish_polygon(self):
        if len(self._polygon) >= 3:
            self._emit_polygon()

    def _emit_polygon(self):
        if len(self._polygon) < 3:
            self.roi_changed.emit(None)
            return
        xs = [point.x() for point in self._polygon]
        ys = [point.y() for point in self._polygon]
        rect = QRect(
            min(xs), min(ys),
            max(1, max(xs) - min(xs)),
            max(1, max(ys) - min(ys)),
        )
        if rect.width() >= 8 and rect.height() >= 8:
            self._roi = rect
            self.roi_changed.emit({
                "rect": rect,
                "polygon": [QPoint(point) for point in self._polygon],
            })
        else:
            self.roi_changed.emit(None)


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
    """Draw a rectangle or polygon; returns bbox percentages and optional shape."""

    def __init__(self, video_path, position_ms: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("绘制追踪区域")
        self.resize(920, 640)
        self._video_path = str(video_path)
        self._position_ms = int(position_ms or 0)
        self._result = None  # (x,y,w,h) percent
        self._shape = []  # polygon vertices relative to bounding box, 0–100

        image = grab_frame_image(self._video_path, self._position_ms)
        root = QVBoxLayout(self)
        tip = QLabel(
            "矩形：按住左键拖拽。 不规则：依次点击轮廓顶点，至少 3 点；右键结束。"
            "追踪使用外接框判断运动，但模糊只作用在自定义多边形内部。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#7dd3fc;")
        root.addWidget(tip)
        modes = QHBoxLayout()
        self.rect_mode = QPushButton("矩形框选")
        self.polygon_mode = QPushButton("不规则多边形")
        self.rect_mode.setCheckable(True); self.polygon_mode.setCheckable(True)
        self.rect_mode.setChecked(True)
        self.undo_point = QPushButton("撤销顶点")
        modes.addWidget(self.rect_mode); modes.addWidget(self.polygon_mode)
        modes.addWidget(self.undo_point); modes.addStretch()
        root.addLayout(modes)
        self.canvas = _RoiCanvas(image)
        self.rect_mode.clicked.connect(lambda:self._set_mode("rect"))
        self.polygon_mode.clicked.connect(lambda:self._set_mode("polygon"))
        self.undo_point.clicked.connect(self.canvas.undo_polygon_point)
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

    def _set_mode(self, mode):
        polygon = mode == "polygon"
        self.rect_mode.setChecked(not polygon)
        self.polygon_mode.setChecked(polygon)
        self.undo_point.setEnabled(polygon)
        self.canvas.set_mode(mode)
        self.status.setText("依次点击轮廓顶点，右键结束" if polygon else "拖拽绘制矩形")

    def _on_roi(self, selection):
        rect = selection.get("rect") if isinstance(selection, dict) else selection
        if rect is None or not rect.isValid():
            self._result = None
            self._shape = []
            self._ok.setEnabled(False)
            self.status.setText("尚未框选")
            return
        iw, ih = self._image_size
        x = rect.x() / iw * 100
        y = rect.y() / ih * 100
        w = rect.width() / iw * 100
        h = rect.height() / ih * 100
        self._result = (x, y, w, h)
        polygon = selection.get("polygon", []) if isinstance(selection, dict) else []
        self._shape = [
            {
                "x": max(0.0, min(100.0, (point.x() - rect.x()) / max(1, rect.width()) * 100)),
                "y": max(0.0, min(100.0, (point.y() - rect.y()) / max(1, rect.height()) * 100)),
            }
            for point in polygon
        ]
        self._ok.setEnabled(True)
        self.status.setText(
            f"{'不规则区域' if self._shape else '矩形区域'}："
            f"X={x:.1f}%  Y={y:.1f}%  宽={w:.1f}%  高={h:.1f}%"
            + (f"  · {len(self._shape)} 个顶点" if self._shape else "")
        )

    def percentages(self):
        """Return (x, y, w, h) in 0–100 percent, or None."""
        return self._result

    def shape_percentages(self):
        """Return polygon vertices relative to the tracked bbox, or an empty list."""
        return [dict(point) for point in self._shape]
