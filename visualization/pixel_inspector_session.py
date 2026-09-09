"""
Pixel Inspector Session Controller Module.
Manages the entire lifecycle, state, signal wiring, and shutdown choreography of the Pixel Inspector,
unifying the map tool, interactive canvas marker, histogram pin, floating diagnostics dialog, and toggle state into a single coherent session.
"""
import logging
from typing import Optional, Dict, Any, List, Tuple, Callable, Union, Sequence, Set, Type
try:
    from PyQt6.QtCore import Qt, QObject, pyqtSignal
except ImportError:
    from qgis.PyQt.QtCore import Qt, QObject, pyqtSignal

try:
    from qgis.core import QgsProject, Qgis, QgsRasterLayer
except ImportError:
    QgsProject = Qgis = QgsRasterLayer = None

logger = logging.getLogger("RemoteSensingStudio")


class PixelInspectorSession(QObject):
    """
    Dedicated controller managing activation, deactivation, event wiring, and state cleanup
    for spectral pixel inspection sessions across QGIS and Remote Sensing Studio.
    
    Responsibilities:
    - start() / activate(): Safely captures previous QGIS map tool and activates inspection crosshair.
    - inspect(): Processes canvas click pixel data and computes diagnostic deltas and classifications.
    - update(): Synchronizes live diagnostic telemetry with floating dialog and interactive histogram.
    - clear(): Erases canvas marker graphics, cached spectral states, and histogram pins.
    - close() / deactivate(): Single centralized shutdown routine restoring previous QGIS map tool without leaking memory.
    - destroy(): Detaches project listeners and dereferences visual components on plugin shutdown.
    """
    session_deactivated = pyqtSignal()

    def __init__(self, iface: Any, parent_dialog: Any) -> None:
        super().__init__()
        self.iface = iface
        self.parent_dialog = parent_dialog
        self.canvas = getattr(iface, "mapCanvas", lambda: None)()
        
        # Managed components
        self.tool: Optional[Any] = None
        self.dialog: Optional[Any] = None
        self.histogram: Optional[Any] = None
        self.toggle_btn: Optional[Any] = None

        # State tracking
        self._is_active: bool = False
        self._previous_map_tool: Optional[Any] = None
        self._deactivating_guard: bool = False

        # Cached Inspection State (Phase 7 - cleanly reset to None upon shutdown)
        self.last_pixel: Optional[Dict[str, Any]] = None
        self.last_coordinate: Optional[Tuple[float, float]] = None
        self.last_band_values: Optional[Dict[int, float]] = None
        self.last_index_value: Optional[float] = None
        self.last_classification: Optional[str] = None
        self.last_delta: Optional[float] = None
        self.last_wgs84: Optional[Tuple[float, float]] = None
        self.last_marker: Optional[Any] = None

        self._wire_project_events()

    def set_components(self, tool: Any, dialog: Any, histogram: Any, toggle_btn: Any) -> None:
        """Assigns the managed visual components and establishes unified event routing."""
        self.tool = tool
        self.dialog = dialog
        self.histogram = histogram
        self.toggle_btn = toggle_btn

        if self.tool and hasattr(self.tool, "request_deactivation"):
            self.tool.request_deactivation.connect(self.close)
            if hasattr(self.tool, "pixel_inspected"):
                self.tool.pixel_inspected.connect(self.inspect)

        if self.dialog and hasattr(self.dialog, "inspector_closed"):
            self.dialog.inspector_closed.connect(self.close)

    def _wire_project_events(self) -> None:
        """Connects authoritative QGIS project and canvas event hooks to trigger automatic teardown (Phase 9)."""
        if QgsProject and hasattr(QgsProject, "instance"):
            try:
                proj = QgsProject.instance()
                if hasattr(proj, "readProject"):
                    proj.readProject.connect(self.close)
                if hasattr(proj, "cleared"):
                    proj.cleared.connect(self.close)
                if hasattr(proj, "projectClosed"):
                    proj.projectClosed.connect(self.close)
                if hasattr(proj, "layersRemoved"):
                    proj.layersRemoved.connect(self._on_layers_removed)
            except Exception as err:
                logger.debug(f"Could not wire QgsProject event hooks: {err}")

    def _on_layers_removed(self, layers: Any) -> None:
        """Terminates session if the currently inspected raster layer is removed or unloaded."""
        if not self._is_active:
            return
        current = getattr(self.parent_dialog, "current_layer", None)
        try:
            if current:
                _ = current.id()
        except RuntimeError:
            self.parent_dialog.current_layer = None
            self.close()
            return
            
        if not current or not getattr(current, "isValid", lambda: True)() or (isinstance(layers, (list, tuple)) and current in layers):
            self.close()

    def check_current_layer_valid(self) -> None:
        """Called when active analysis layer switches; tears down session if target becomes invalid or replaced."""
        if self._is_active:
            current = getattr(self.parent_dialog, "current_layer", None)
            try:
                if current:
                    _ = current.id()
            except RuntimeError:
                self.parent_dialog.current_layer = None
                self.close()
                return
                
            if not current or not getattr(current, "isValid", lambda: True)():
                self.close()

    def start(self, layer: Any) -> bool:
        """
        Activates the inspection session without triggering accidental teardowns.
        Safely records the previously active QGIS map tool before asserting the inspection crosshair tool (Phase 4).
        """
        if not self.tool or not self.canvas:
            logger.warning("Cannot start PixelInspectorSession: tool or canvas not initialized.")
            return False

        if not layer:
            logger.warning("Cannot start PixelInspectorSession: no active raster layer provided.")
            if self.toggle_btn and hasattr(self.toggle_btn, "setChecked"):
                self.toggle_btn.blockSignals(True)
                self.toggle_btn.setChecked(False)
                self.toggle_btn.blockSignals(False)
            return False

        # Phase 4: Record previous active map tool without overwriting with our own tool reference
        current_tool = getattr(self.canvas, "mapTool", lambda: None)()
        if current_tool and current_tool != self.tool:
            self._previous_map_tool = current_tool

        # Re-instantiate fresh map tool to prevent QGIS 4 stale scene event filter disconnection
        try:
            from .pixel_inspector import PixelInspectorTool
            if self.tool and hasattr(self.tool, "request_deactivation"):
                try: self.tool.request_deactivation.disconnect(self.close)
                except Exception: pass
                if hasattr(self.tool, "pixel_inspected"):
                    try: self.tool.pixel_inspected.disconnect(self.inspect)
                    except Exception: pass
            
            self.tool = PixelInspectorTool(self.canvas, layer)
            self.tool.set_layer(layer)
            self.tool.request_deactivation.connect(self.close)
            self.tool.pixel_inspected.connect(self.inspect)
            if hasattr(self.parent_dialog, "pixel_inspector"):
                self.parent_dialog.pixel_inspector = self.tool
            logger.info("Fresh PixelInspectorTool instantiated and wired to canvas.")
        except Exception as err:
            logger.error(f"Failed to instantiate PixelInspectorTool: {err}", exc_info=True)
            raise

        # Assert active map tool on QGIS Map Canvas
        try:
            self.canvas.setMapTool(self.tool)
            if hasattr(self.canvas, "setFocus"):
                try: self.canvas.setFocus()
                except Exception: pass
        except Exception as err:
            logger.error(f"Failed to set map tool on canvas: {err}", exc_info=True)
            raise

        actual_tool = getattr(self.canvas, "mapTool", lambda: None)()
        if actual_tool is None:
            logger.error("Activation verification failed: canvas.mapTool() returned None.")
            if self.toggle_btn and hasattr(self.toggle_btn, "setChecked"):
                self.toggle_btn.blockSignals(True)
                self.toggle_btn.setChecked(False)
                self.toggle_btn.blockSignals(False)
            return False
        else:
            if actual_tool != self.tool or actual_tool is not self.tool:
                logger.debug("canvas.mapTool() proxy identity differs from self.tool, proceeding safely.")

        self._is_active = True
        logger.info("PixelInspectorSession fully active on map canvas.")
        return True

    def activate(self, layer: Any) -> bool:
        """Alias for start() to support extensible session nomenclature."""
        return self.start(layer)

    def inspect(self, data: Dict[str, Any]) -> None:
        """
        Receives raw pixel metadata upon canvas click, updates cached inspection state,
        computes classification status, and synchronizes diagnostics across UI and histogram.
        """
        if not self._is_active:
            return

        val = data.get("value", 0.0)
        coord_x = data.get("x", 0.0)
        coord_y = data.get("y", 0.0)

        # Cache state (Phase 7)
        self.last_pixel = data
        self.last_coordinate = (coord_x, coord_y)
        self.last_band_values = data.get("bands", {})
        self.last_index_value = val
        self.last_wgs84 = (data.get("lat", 0.0), data.get("lon", 0.0))
        if hasattr(self.tool, "marker") and self.tool.marker:
            self.last_marker = self.tool.marker

        threshold = getattr(self.parent_dialog.spnThreshold, "value", lambda: 0.0)() if hasattr(self.parent_dialog, "spnThreshold") else 0.0
        meta = getattr(self.parent_dialog, "current_metadata", None)
        pos_meaning = getattr(meta, "positive_meaning", "Target Class") if meta else "Target Class"
        neg_meaning = getattr(meta, "negative_meaning", "Background Matrix") if meta else "Background Matrix"
        formula = getattr(meta, "formula_name", "Spectral Index") if meta else "Spectral Index"

        sat_meta = getattr(meta, "satellite", None) if meta else None
        res_meta = str(getattr(meta, "resolution", "")) if meta else None
        if not sat_meta and hasattr(self.parent_dialog, "last_analysis_context") and self.parent_dialog.last_analysis_context:
            sat_meta = getattr(self.parent_dialog.last_analysis_context, "satellite", None)
            res_meta = str(getattr(self.parent_dialog.last_analysis_context, "resolution", ""))

        status = pos_meaning if val >= threshold else neg_meaning
        delta = val - threshold

        self.last_classification = status
        self.last_delta = delta

        self.update(data, threshold, pos_meaning, neg_meaning, formula, sat_meta, res_meta, status, coord_x, coord_y, val)

    def update(
        self,
        data: Dict[str, Any],
        threshold: float,
        pos_meaning: str,
        neg_meaning: str,
        formula: str,
        satellite: Optional[str],
        resolution: Optional[str],
        status: str,
        coord_x: float,
        coord_y: float,
        val: float
    ) -> None:
        """Synchronizes observed diagnostics with floating dialog panel and histogram distribution chart."""
        # 1. Update histogram pin indicator
        if self.histogram and hasattr(self.histogram, "set_inspected_value"):
            self.histogram.set_inspected_value(val)

        # 2. Update floating diagnostics dialog
        if self.dialog and hasattr(self.dialog, "update_inspection_data"):
            self.dialog.update_inspection_data(
                inspection_data=data,
                threshold=threshold,
                positive_meaning=pos_meaning,
                negative_meaning=neg_meaning,
                formula_name=formula,
                satellite=satellite,
                resolution_meta=resolution
            )

        # 3. Push summary to QGIS message bar
        if self.iface and hasattr(self.iface, "messageBar") and self.iface.messageBar():
            try:
                msg = f"<b>{formula} Index:</b> {val:.4f} | <b>Class:</b> {status} | <b>Map Coordinates:</b> X: {coord_x:.2f}, Y: {coord_y:.2f}"
                if Qgis:
                    self.iface.messageBar().pushMessage("Pixel Inspection", msg, level=Qgis.MessageLevel.Success, duration=5)
            except Exception:
                pass

    def clear(self) -> None:
        """
        Executes exhaustive cleanup of all visual markers, cached attributes, and histogram artifacts.
        Guarantees zero orphan graphics or stale references in memory.
        """
        # Phase 6: Marker cleanup (scene.removeItem + deleteLater)
        if self.tool and hasattr(self.tool, "clean_marker"):
            self.tool.clean_marker()
        self.last_marker = None

        # Phase 7: Clear all cached inspection state
        self.last_pixel = None
        self.last_coordinate = None
        self.last_band_values = None
        self.last_index_value = None
        self.last_classification = None
        self.last_delta = None
        self.last_wgs84 = None
        if self.dialog and hasattr(self.dialog, "_current_data_cache"):
            self.dialog._current_data_cache = {}

        # Phase 8: Comprehensive Histogram cleanup
        if self.histogram:
            if hasattr(self.histogram, "clear_all_inspection_artifacts"):
                self.histogram.clear_all_inspection_artifacts()
            elif hasattr(self.histogram, "clear_inspected_value"):
                self.histogram.clear_inspected_value()

    def close(self, *args: Any) -> None:
        """
        Single centralized shutdown routine executed by all exit paths:
        Close button, Window X, ESC, Plugin unload, Layer removed, Project events, New analysis, Toggle OFF.
        Restores exact previous map tool without forcing Pan mode (Phase 4 & 5).
        """
        if self._deactivating_guard or not self._is_active:
            return
        self._deactivating_guard = True
        try:
            self._is_active = False

            # 1. Synchronize UI toggle button OFF without signal recursion
            if self.toggle_btn and getattr(self.toggle_btn, "isChecked", lambda: False)():
                self.toggle_btn.blockSignals(True)
                self.toggle_btn.setChecked(False)
                self.toggle_btn.blockSignals(False)

            # 2. Restore exact previous map tool (Phase 4)
            if self.canvas:
                current = getattr(self.canvas, "mapTool", lambda: None)()
                if current == self.tool:
                    if self._previous_map_tool and self._previous_map_tool != self.tool:
                        try:
                            self.canvas.setMapTool(self._previous_map_tool)
                        except Exception as err:
                            logger.debug(f"Could not restore previous map tool: {err}")
                            self.canvas.unsetMapTool(self.tool)
                    else:
                        self.canvas.unsetMapTool(self.tool)

            # 3. Exhaustive cleanup of markers, cached state, and histogram artifacts (Phase 6, 7, 8)
            self.clear()

            # 4. Dismiss floating diagnostic tool dialog
            if self.dialog and getattr(self.dialog, "isVisible", lambda: False)():
                self.dialog.hide()

            self.session_deactivated.emit()
            logger.info("PixelInspectorSession terminated cleanly; previous map tool restored.")
        except Exception as err:
            logger.debug(f"Error during PixelInspectorSession close: {err}")
        finally:
            self._deactivating_guard = False
            self._previous_map_tool = None

    def deactivate(self, *args: Any) -> None:
        """Alias for close() to maintain interface consistency with QGIS lifecycle events."""
        self.close(*args)

    def destroy(self) -> None:
        """Completely shuts down the session, disconnects hooks, and dereferences objects on plugin unload."""
        self.close()
        if QgsProject and hasattr(QgsProject, "instance"):
            try:
                proj = QgsProject.instance()
                if hasattr(proj, "readProject"):
                    try: proj.readProject.disconnect(self.close)
                    except Exception: pass
                if hasattr(proj, "cleared"):
                    try: proj.cleared.disconnect(self.close)
                    except Exception: pass
                if hasattr(proj, "projectClosed"):
                    try: proj.projectClosed.disconnect(self.close)
                    except Exception: pass
                if hasattr(proj, "layersRemoved"):
                    try: proj.layersRemoved.disconnect(self._on_layers_removed)
                    except Exception: pass
            except Exception:
                pass
        self.tool = None
        self.dialog = None
        self.histogram = None
        self.toggle_btn = None
        self.parent_dialog = None
        self.canvas = None
        self.iface = None
