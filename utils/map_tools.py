from typing import Optional
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor
import logging

try:
    from qgis.gui import QgsMapTool, QgsRubberBand
    from qgis.core import QgsWkbTypes, QgsGeometry, QgsPointXY
except ImportError:
    pass

class PolygonMapTool(QgsMapTool):
    """
    Native QGIS Map Tool for interactively drawing polygons.
    Maintains memory-only geometries via QgsRubberBand.
    Emits geometryCaptured when finished.
    """
    geometryCaptured = pyqtSignal(object)
    drawingCanceled = pyqtSignal()
    
    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.rubber_band = QgsRubberBand(canvas, QgsWkbTypes.GeometryType.PolygonGeometry)
        self.rubber_band.setColor(QColor(37, 99, 235, 100)) # Blue accent with transparency
        self.rubber_band.setWidth(2)
        self.points = []
        self.is_drawing = False
        
    def activate(self):
        super().activate()
        self.reset()
        
    def deactivate(self):
        self.reset()
        super().deactivate()
        
    def reset(self):
        """Cleans up the rubber band and resets state."""
        try:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage("PolygonMapTool: reset() called.", "RemoteSensingStudio", Qgis.MessageLevel.Info)
        except Exception as e:
            logging.getLogger(__name__).debug(f"[utils/map_tools.py:42] Suppressed exception: {e}")
            pass
        self.points = []
        self.rubber_band.reset(QgsWkbTypes.GeometryType.PolygonGeometry)
        self.is_drawing = False
        
    def canvasPressEvent(self, e):
        """Handle mouse clicks to add vertices or finalize drawing."""
        try:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"PolygonMapTool: canvasPressEvent received. Button: {e.button()}", "RemoteSensingStudio", Qgis.MessageLevel.Info)
        except Exception as e:
            logging.getLogger(__name__).debug(f"[utils/map_tools.py:53] Suppressed exception: {e}")
            pass
        if e.button() == Qt.MouseButton.LeftButton:
            self.is_drawing = True
            point = self.toMapCoordinates(e.pos())
            self.points.append(point)
            self.rubber_band.addPoint(point, True)
            try:
                QgsMessageLog.logMessage(f"PolygonMapTool: Point added. Total points: {len(self.points)}", "RemoteSensingStudio", Qgis.MessageLevel.Info)
            except Exception as e:
                logging.getLogger(__name__).debug(f"[utils/map_tools.py:62] Suppressed exception: {e}")
                pass
            
        elif e.button() == Qt.MouseButton.RightButton:
            self._finalize_polygon()

    def canvasDoubleClickEvent(self, e):
        """Alternative way to finish drawing."""
        try:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"PolygonMapTool: canvasDoubleClickEvent received. Button: {e.button()}", "RemoteSensingStudio", Qgis.MessageLevel.Info)
        except Exception as e:
            logging.getLogger(__name__).debug(f"[utils/map_tools.py:73] Suppressed exception: {e}")
            pass
        if e.button() == Qt.MouseButton.LeftButton:
            self._finalize_polygon()
            
    def keyPressEvent(self, e):
        """Cancel drawing on Escape."""
        if e.key() == Qt.Key.Key_Escape:
            self.reset()
            self.drawingCanceled.emit()

    def _finalize_polygon(self):
        """Constructs the geometry and emits the signal."""
        try:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(f"PolygonMapTool: _finalize_polygon executing. Points: {len(self.points)}", "RemoteSensingStudio", Qgis.MessageLevel.Info)
        except Exception as e:
            logging.getLogger(__name__).debug(f"[utils/map_tools.py:89] Suppressed exception: {e}")
            pass
        if len(self.points) >= 3:
            # Construct a closed ring
            ring = list(self.points)
            ring.append(self.points[0])
            
            geom = QgsGeometry.fromPolygonXY([ring])
            if geom and not geom.isEmpty() and geom.isGeosValid():
                try:
                    QgsMessageLog.logMessage("PolygonMapTool: Valid geometry constructed. Emitting geometryCaptured.", "RemoteSensingStudio", Qgis.MessageLevel.Info)
                except Exception as e:
                    logging.getLogger(__name__).debug(f"[utils/map_tools.py:100] Suppressed exception: {e}")
                    pass
                self.geometryCaptured.emit(geom)
            else:
                try:
                    QgsMessageLog.logMessage(f"PolygonMapTool: Geometry invalid (Empty: {geom.isEmpty() if geom else True}). Emitting drawingCanceled.", "RemoteSensingStudio", Qgis.MessageLevel.Warning)
                except Exception as e:
                    logging.getLogger(__name__).debug(f"[utils/map_tools.py:106] Suppressed exception: {e}")
                    pass
                self.drawingCanceled.emit()
        else:
            try:
                QgsMessageLog.logMessage(f"PolygonMapTool: Not enough points ({len(self.points)} < 3). Emitting drawingCanceled.", "RemoteSensingStudio", Qgis.MessageLevel.Warning)
            except Exception as e:
                logging.getLogger(__name__).debug(f"[utils/map_tools.py:112] Suppressed exception: {e}")
                pass
            self.drawingCanceled.emit()
            
        self.reset()
