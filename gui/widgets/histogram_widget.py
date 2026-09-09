from typing import Optional, Any, Dict, List, Tuple, Union, Callable
try:
    from PyQt6.QtWidgets import QWidget
    from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPolygonF, QFont
    from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QPointF
except ImportError:
    from qgis.PyQt.QtWidgets import QWidget
    from qgis.PyQt.QtGui import QPainter, QColor, QPen, QBrush, QPolygonF, QFont
    from qgis.PyQt.QtCore import Qt, pyqtSignal, QRectF, QPointF
import numpy as np

class HistogramWidget(QWidget):
    """
    Plots the frequency distribution of the currently active raster layer.
    It is completely index-agnostic.
    Includes interactive markers for thresholds and an indicator pin for inspected pixels.
    """
    
    thresholdChanged = pyqtSignal(float)
    displayRangeChanged = pyqtSignal(float, float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self._counts = None
        self._bin_edges = None
        self._min_val = 0.0
        self._max_val = 1.0
        self._threshold = 0.5
        self._is_dragging_threshold = False
        self._inspected_value: Optional[float] = None
        self._selected_bin: Optional[Any] = None
        self._hover_bin: Optional[Any] = None
        self._highlighted_bin: Optional[Any] = None

    def set_data(self, counts: np.ndarray, bin_edges: np.ndarray):
        """Updates the histogram data and requests a repaint."""
        self._counts = counts
        self._bin_edges = bin_edges
        if len(bin_edges) > 1:
            self._min_val = float(bin_edges[0])
            self._max_val = float(bin_edges[-1])
        self.update()

    def set_threshold(self, threshold: float):
        """Sets the current threshold marker position without emitting."""
        self._threshold = threshold
        self.update()
        
    def set_inspected_value(self, value: Optional[float]):
        """Highlights the currently inspected pixel value on the distribution histogram."""
        self._inspected_value = value
        self.update()

    def clear_inspected_value(self):
        """Removes the inspected pixel value highlight and refreshes the histogram canvas."""
        self.clear_all_inspection_artifacts()

    def clear_all_inspection_artifacts(self):
        """Completely clears every inspection artifact, bin selection, hover state, and tooltip (Phase 8)."""
        self._inspected_value = None
        self._selected_bin = None
        self._hover_bin = None
        self._highlighted_bin = None
        if hasattr(self, 'setToolTip'):
            try:
                self.setToolTip("")
            except Exception:
                pass
        self.update()

    def _value_to_x(self, value: float, width: int) -> float:
        """Converts a data value to an X pixel coordinate."""
        if self._max_val == self._min_val:
            return width / 2.0
        normalized = (value - self._min_val) / (self._max_val - self._min_val)
        return float(normalized * width)
        
    def _x_to_value(self, x: float, width: int) -> float:
        """Converts an X pixel coordinate to a data value."""
        if width == 0:
            return self._min_val
        normalized = x / width
        return float(self._min_val + normalized * (self._max_val - self._min_val))

    def paintEvent(self, event):
        if self._counts is None or self._bin_edges is None or len(self._counts) == 0:
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = self.rect()
        width = rect.width()
        height = rect.height()
        
        # Draw background
        painter.fillRect(rect, QColor("#0C1B30"))
        
        max_count = float(np.max(self._counts))
        if max_count == 0:
            max_count = 1.0
            
        # Draw bars
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#7E8EA5")))
        
        bin_width_pixels = width / len(self._counts)
        
        for i in range(len(self._counts)):
            bar_height = (self._counts[i] / max_count) * height
            x = i * bin_width_pixels
            y = height - bar_height
            painter.drawRect(QRectF(x, y, bin_width_pixels, bar_height))
            
        # Draw threshold line
        threshold_x = self._value_to_x(self._threshold, width)
        
        pen = QPen(QColor("#E11D48"), 2)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(threshold_x, 0), QPointF(threshold_x, height))
        
        # Handle (Triangle at top for threshold)
        painter.setBrush(QBrush(QColor("#E11D48")))
        painter.setPen(Qt.PenStyle.NoPen)
        poly = QPolygonF([
            QPointF(threshold_x, 0),
            QPointF(threshold_x - 6, 8),
            QPointF(threshold_x + 6, 8)
        ])
        painter.drawPolygon(poly)

        # Draw inspected pixel indicator pin (if currently inspecting a pixel)
        if self._inspected_value is not None and self._min_val <= self._inspected_value <= self._max_val:
            inspected_x = self._value_to_x(self._inspected_value, width)
            
            # Draw solid vertical marker pin line (Vibrant Blue accent #2563EB)
            pin_pen = QPen(QColor("#27D8F7"), 2)
            pin_pen.setStyle(Qt.PenStyle.SolidLine)
            painter.setPen(pin_pen)
            painter.drawLine(QPointF(inspected_x, 14), QPointF(inspected_x, height))
            
            # Draw circular pin head
            painter.setBrush(QBrush(QColor("#27D8F7")))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(inspected_x, 14), 4.5, 4.5)
            
            # Draw Px value annotation tag above pin head
            painter.setPen(QPen(QColor("#FFFFFF"), 1))
            try:
                from qgis.PyQt.QtGui import QFont
                painter.setFont(QFont("Inter", 8, QFont.Weight.Bold))
            except Exception:
                pass
            val_text = f"Px: {self._inspected_value:.3f}"
            text_x = max(2.0, min(float(width) - 60.0, float(inspected_x) - 25.0))
            painter.drawText(QRectF(text_x, 0, 70, 14), Qt.AlignmentFlag.AlignCenter, val_text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            width = self.rect().width()
            # Enforce PyQt6 event.position().x() (replaces deprecated PyQt5 event.x())
            x_coord = float(event.position().x()) if hasattr(event, "position") else float(event.pos().x())
            click_val = self._x_to_value(x_coord, width)
            # If clicked somewhat near the threshold, start dragging
            if abs(click_val - self._threshold) < (self._max_val - self._min_val) * 0.1:
                self._is_dragging_threshold = True
            else:
                # Snap threshold to click
                self._threshold = click_val
                self.thresholdChanged.emit(self._threshold)
                self.update()

    def mouseMoveEvent(self, event):
        if self._is_dragging_threshold:
            width = self.rect().width()
            # Enforce PyQt6 event.position().x() (replaces deprecated PyQt5 event.x())
            x_coord = float(event.position().x()) if hasattr(event, "position") else float(event.pos().x())
            new_val = self._x_to_value(x_coord, width)
            # Clamp to range
            new_val = max(self._min_val, min(self._max_val, new_val))
            self._threshold = new_val
            self.thresholdChanged.emit(self._threshold)
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging_threshold = False
