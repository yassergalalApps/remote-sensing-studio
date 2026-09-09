"""
Pixel Inspector Tool Module.
Provides an interactive QGIS Map Tool that inspects raster pixels on left click,
places a visual vertex marker on the map canvas, extracts multi-band values using modern QGIS 4 APIs,
transforms coordinates to WGS84 Lat/Lon, and emits structured metadata for rich display.
"""
import logging
import math
from typing import Optional, Dict, Any
try:
    from qgis.PyQt.QtCore import Qt, pyqtSignal, QObject
    from qgis.PyQt.QtGui import QColor, QCursor
except ImportError:
    from PyQt6.QtCore import Qt, pyqtSignal, QObject
    from PyQt6.QtGui import QColor, QCursor

try:
    from qgis.gui import QgsMapTool, QgsVertexMarker
    from qgis.core import (
        QgsPointXY, QgsRasterLayer, QgsRaster, QgsProject,
        QgsCoordinateReferenceSystem, QgsCoordinateTransform,
        QgsCoordinateTransformContext
    )
except ImportError:
    class QgsMapTool(QObject):
        def __init__(self, canvas=None): super().__init__()
        def setCursor(self, cursor): pass
        def activate(self): pass
        def deactivate(self): pass
        def keyPressEvent(self, event): pass
    QgsVertexMarker = None
    QgsPointXY = QgsRasterLayer = QgsRaster = QgsProject = None
    QgsCoordinateReferenceSystem = QgsCoordinateTransform = QgsCoordinateTransformContext = None

logger = logging.getLogger("RemoteSensingStudio")


class PixelInspectorTool(QgsMapTool):
    """
    Attaches to the QGIS map canvas. On left click, it reads pixel values from all bands
    of the active raster layer using QGIS 4 compliant APIs (identify and sample),
    displays an interactive canvas marker, and emits detailed geospatial and spectral metadata.
    """
    
    pixel_inspected = pyqtSignal(dict)
    request_deactivation = pyqtSignal()
    
    def __init__(self, canvas: Any, layer: Optional[QgsRasterLayer] = None) -> None:
        super().__init__(canvas)
        self.canvas = canvas
        self.layer = layer
        self.marker: Optional[QgsVertexMarker] = None
        
        # Enforce PyQt6 QCursor instantiation syntax (strictly requires QCursor instance in QGIS 4 bindings)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    def activate(self) -> None:
        """Called by QGIS when this map tool becomes the active tool on the canvas; explicitly sets crosshair cursor."""
        cross_cursor = QCursor(Qt.CursorShape.CrossCursor)
        self.setCursor(cross_cursor)
        super().activate()
        if hasattr(self, 'canvas') and self.canvas and hasattr(self.canvas, 'setCursor'):
            try:
                self.canvas.setCursor(cross_cursor)
                logger.debug("Crosshair cursor applied to map canvas.")
            except Exception as err:
                logger.error(f"Failed setting crosshair cursor on map canvas: {err}")
                raise

    def set_layer(self, layer: Optional[QgsRasterLayer]) -> None:
        """Assigns or updates the target raster layer for inspection."""
        self.layer = layer
        if not layer:
            self.clean_marker()

    def clean_marker(self) -> None:
        """Completely removes and destroys the visual canvas marker without leaving orphaned graphics."""
        if self.marker:
            if self.canvas and hasattr(self.canvas, 'scene') and self.canvas.scene():
                try:
                    self.canvas.scene().removeItem(self.marker)
                except Exception as err:
                    logger.debug(f"Error removing inspection marker from scene: {err}")
            try:
                if hasattr(self.marker, 'deleteLater'):
                    self.marker.deleteLater()
            except Exception as err:
                logger.debug(f"Error calling deleteLater on marker: {err}")
            self.marker = None

    def deactivate(self) -> None:
        """Called by QGIS when another map tool is selected or tool is unset."""
        self.clean_marker()
        super().deactivate()

    def keyPressEvent(self, event: Any) -> None:
        """Captures ESC key presses on the map canvas to terminate the inspection session."""
        if hasattr(event, "key") and event.key() == Qt.Key.Key_Escape:
            self.request_deactivation.emit()
            if hasattr(event, "ignore"):
                event.ignore()
        else:
            super().keyPressEvent(event)

    def canvasPressEvent(self, event: Any) -> None:
        """Handles mouse press events on the map canvas to immediately capture left clicks and prevent QGIS from treating the press as a map drag/pan."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._inspect_at_event(event)
            if hasattr(event, "accept"):
                event.accept()

    def canvasReleaseEvent(self, event: Any) -> None:
        """Handles mouse release events on the map canvas."""
        if event.button() == Qt.MouseButton.LeftButton:
            if hasattr(event, "accept"):
                event.accept()
        elif event.button() == Qt.MouseButton.RightButton:
            self.request_deactivation.emit()
            if hasattr(event, "ignore"):
                event.ignore()

    def _inspect_at_event(self, event: Any) -> None:
        """Performs pixel identification at the clicked coordinates and emits inspection diagnostics."""
        if not self.layer or not hasattr(self.layer, "isValid") or not self.layer.isValid():
            logger.warning("PixelInspectorTool: No valid target raster layer selected for inspection.")
            return
            
        # Enforce modern QGIS/PyQt6 map coordinates extraction (replaces legacy event.pos())
        if hasattr(event, "mapPoint"):
            point: QgsPointXY = event.mapPoint()
        elif hasattr(event, "position") and hasattr(event.position(), "toPoint"):
            point: QgsPointXY = self.toMapCoordinates(event.position().toPoint())
        else:
            point: QgsPointXY = self.toMapCoordinates(event.pos())
        
        # Step 1: Place or update visual marker on the map canvas at clicked coordinates
        if not self.marker and self.canvas:
            try:
                self.marker = QgsVertexMarker(self.canvas)
                if hasattr(QgsVertexMarker, "IconType") and hasattr(QgsVertexMarker.IconType, "ICON_CIRCLE"):
                    self.marker.setIconType(QgsVertexMarker.IconType.ICON_CIRCLE)
                elif hasattr(QgsVertexMarker, "ICON_CIRCLE"):
                    self.marker.setIconType(QgsVertexMarker.ICON_CIRCLE)
                self.marker.setColor(QColor("#2563EB"))  # Vibrant royal blue highlight
                self.marker.setIconSize(11)
                self.marker.setPenWidth(3)
            except Exception as m_err:
                logger.debug(f"Could not instantiate QgsVertexMarker: {m_err}")
                
        if self.marker:
            try:
                self.marker.setCenter(point)
            except Exception as center_err:
                logger.debug(f"Error repositioning marker: {center_err}")

        # Step 2: Retrieve pixel values using modern QGIS 4 APIs
        band_values: Dict[int, float] = {}
        band_count: int = getattr(self.layer, "bandCount", lambda: 1)()
        
        # Determine future-proof QGIS 4 IdentifyFormat enum (replaces deprecated QgsRasterLayer.IdentifyFormatValue)
        id_format = None
        if hasattr(QgsRaster, "IdentifyFormatValue"):
            id_format = QgsRaster.IdentifyFormatValue
        elif hasattr(QgsRaster, "IdentifyFormat") and hasattr(QgsRaster.IdentifyFormat, "IdentifyFormatValue"):
            id_format = QgsRaster.IdentifyFormat.IdentifyFormatValue
        else:
            id_format = 1  # Standard fallback enum integer value in QGIS C++ core
            
        try:
            data_provider = self.layer.dataProvider()
            if data_provider:
                ident = data_provider.identify(point, id_format)
                if ident and ident.isValid():
                    res = ident.results()
                    if isinstance(res, dict):
                        for b_idx, val in res.items():
                            if val is not None and str(val) != "nan":
                                try:
                                    band_values[int(b_idx)] = float(val)
                                except (ValueError, TypeError):
                                    pass

                # Resilient sample() fallback for any unpopulated bands
                for b_idx in range(1, band_count + 1):
                    if b_idx not in band_values and hasattr(data_provider, "sample"):
                        try:
                            sample_res = data_provider.sample(point, b_idx)
                            if isinstance(sample_res, tuple) and len(sample_res) == 2:
                                val, ok = sample_res
                                if ok and val is not None and str(val) != "nan":
                                    band_values[b_idx] = float(val)
                            elif isinstance(sample_res, (int, float)):
                                band_values[b_idx] = float(sample_res)
                        except Exception as sample_err:
                            logger.debug(f"Could not sample band {b_idx}: {sample_err}")
        except Exception as id_err:
            logger.error(f"Error reading raster values in PixelInspectorTool: {id_err}", exc_info=True)
            return

        if not band_values:
            logger.debug("Pixel inspection clicked outside valid raster data domain (no valid band returns).")
            return

        primary_value = band_values.get(1, next(iter(band_values.values()), 0.0))

        # Step 3: Transform native map coordinates to WGS84 Lat/Lon (EPSG:4326)
        lat, lon = point.y(), point.x()
        try:
            source_crs = self.layer.crs()
            wgs84_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            if source_crs.isValid() and source_crs != wgs84_crs:
                project = QgsProject.instance()
                ctx = project.transformContext() if hasattr(project, "transformContext") else QgsCoordinateTransformContext()
                xform = QgsCoordinateTransform(source_crs, wgs84_crs, ctx)
                transformed_pt = xform.transform(point)
                lat, lon = transformed_pt.y(), transformed_pt.x()
        except Exception as xform_err:
            logger.debug(f"Could not transform coordinates to WGS84 Lat/Lon: {xform_err}")

        # Step 4: Extract pixel dimensions and coordinate reference system metadata
        px_size_x: float = getattr(self.layer, "rasterUnitsPerPixelX", lambda: 0.0)()
        px_size_y: float = getattr(self.layer, "rasterUnitsPerPixelY", lambda: 0.0)()
        if (px_size_x == 0.0 or px_size_y == 0.0) and hasattr(self.layer, "dataProvider") and self.layer.dataProvider():
            try:
                extent = self.layer.dataProvider().extent()
                w = self.layer.dataProvider().xSize()
                h = self.layer.dataProvider().ySize()
                if w > 0: px_size_x = abs(extent.width() / float(w))
                if h > 0: px_size_y = abs(extent.height() / float(h))
            except Exception:
                pass

        crs_obj = self.layer.crs() if hasattr(self.layer, "crs") else None
        crs_authid = crs_obj.authid() if crs_obj and hasattr(crs_obj, "authid") else "N/A"
        crs_desc = crs_obj.description() if crs_obj and hasattr(crs_obj, "description") else "Local Raster System"
        
        # Calculate metric ground dimensions if raster operates in geographic degrees (EPSG:4326)
        is_geographic = crs_obj.isGeographic() if crs_obj and hasattr(crs_obj, "isGeographic") else (0.0 < abs(px_size_x) < 0.1)
        px_meters_x: float = abs(px_size_x)
        px_meters_y: float = abs(px_size_y)
        if is_geographic and px_size_x != 0.0:
            # WGS84 degree approximation at target latitude
            lat_rad = math.radians(abs(lat))
            px_meters_x = abs(px_size_x) * 111320.0 * math.cos(lat_rad)
            px_meters_y = abs(px_size_y) * 111320.0

        # Step 5: Emit structured inspection metadata package
        inspection_data: Dict[str, Any] = {
            "x": point.x(),
            "y": point.y(),
            "lat": lat,
            "lon": lon,
            "value": primary_value,
            "bands": band_values,
            "pixel_size_x": abs(px_size_x),
            "pixel_size_y": abs(px_size_y),
            "pixel_meters_x": px_meters_x,
            "pixel_meters_y": px_meters_y,
            "is_geographic": is_geographic,
            "crs_authid": crs_authid,
            "crs_desc": crs_desc,
            "layer_name": getattr(self.layer, "name", lambda: "Active Index Raster")()
        }
        
        logger.debug(f"Pixel inspected successfully at ({point.x():.2f}, {point.y():.2f}): value={primary_value:.4f}")
        self.pixel_inspected.emit(inspection_data)
