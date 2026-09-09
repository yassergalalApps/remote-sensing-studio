import os
import time
from typing import Optional, Dict, Any, List

try:
    from qgis.PyQt.QtWidgets import (QDialog, QMessageBox, QFileDialog, QCheckBox, 
                                 QLabel, QComboBox, QHBoxLayout, QGroupBox, QRadioButton, QVBoxLayout)
    from PyQt6.QtGui import QColor
    from PyQt6 import uic, QtCore
    from qgis.core import QgsGeometry, QgsWkbTypes
    from qgis.gui import QgsRubberBand
except ImportError:
    pass

from ..services.analysis_engine import AnalysisEngine
from ..analysis.formula_registry import FormulaRegistry
from ..models.analysis_result import AnalysisResult
from ..utils.logger import get_logger
from ..utils import helpers
from ..utils.map_tools import PolygonMapTool
from ..analysis.sensor_profiles import SensorBandRegistry

class LocalAnalysisWorker(QtCore.QThread):
    worker_failed = QtCore.pyqtSignal(str)
    worker_completed = QtCore.pyqtSignal(AnalysisResult)
    progress_update = QtCore.pyqtSignal(str, int)
    
    def __init__(self, engine, params):
        super().__init__()
        self.engine = engine
        self.params = params
        self.engine.progress_update.connect(self._on_progress)
        
    def _on_progress(self, msg: str, val: int):
        self.progress_update.emit(msg, val)
        
    def run(self):
        import logging
        import traceback
        logger = logging.getLogger(__name__)
        try:
            result = self.engine.run_local_workflow(**self.params)
            self.worker_completed.emit(result)
        except Exception as e:
            error_msg = traceback.format_exc()
            logger.error(f"Exception in local worker thread:\n{error_msg}")
            self.worker_failed.emit(str(e) + "\n\nTraceback:\n" + error_msg)

class LocalRasterWizardDialog(QDialog):
    analysis_workflow_finished = QtCore.pyqtSignal(AnalysisResult, object)
    
    def __init__(self, parent: Optional[QDialog], iface: Any = None, analysis_type: str = ""):
        super().__init__(parent)
        self.logger = get_logger(__name__)
        self.iface = iface
        self.analysis_engine = AnalysisEngine.get_instance()
        self.initial_analysis_type = analysis_type
        
        # State
        self.current_aoi_geojson: Optional[Dict[str, Any]] = None
        self.map_tool: Optional[PolygonMapTool] = None
        self.previous_map_tool = None
        self.highlight_band: Optional[QgsRubberBand] = None
        self.worker = None
        self.selected_raster_path = ""
        self.band_comboboxes = {} # var_name -> QComboBox
        self.user_band_overrides = {} # var_name -> int
        self.num_raster_bands = 0
        
        # Caching basic raster details to avoid reopening repeatedly
        self.raster_descriptions = []
        self.raster_metadata_dicts = []
        self.raster_colorinterp = []
        
        ui_path = os.path.join(os.path.dirname(__file__), '..', 'ui', 'local_raster_wizard.ui')
        uic.loadUi(ui_path, self)
        
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowType.WindowMaximizeButtonHint | QtCore.Qt.WindowType.WindowMinimizeButtonHint)
        self.resize(900, 600)
        
        # Apply plugin scrollbar styling
        from ..utils.helpers import apply_scrollbar_style
        apply_scrollbar_style(self)
        
        self.stackedWidget.setCurrentIndex(0)
        self.btnFinish.setVisible(False)
        self.btnBack.setVisible(False)
        
        self.analysis_type = analysis_type
        self.setup_ui()
        self.connect_signals()
        
    def setup_ui(self):
        # AOI
        self.AOI_MODES = [
            ("Selected Features in Active Layer", "SELECTED_FEATURES"),
            ("✔ Active Study Area (Detected Automatically)", "AUTO_SINGLE_POLYGON"),
            ("Use Entire Local Raster as Study Area", "FULL_RASTER"),
            ("Browse Vector File", "VECTOR_FILE"),
            ("Draw Polygon", "DRAW_POLYGON"),
            ("Current Map Extent", "MAP_EXTENT"),
            ("Active Layer Bounding Box", "LAYER_BBOX")
        ]
        
        self.cmbAoi.clear()
        for text, mode_id in self.AOI_MODES:
            self.cmbAoi.addItem(text, mode_id)
            
        if self.initial_analysis_type:
            if hasattr(self, 'lblAnalysisName'):
                self.lblAnalysisName.setText(f"Analysis: {self.initial_analysis_type}")
                
        # Populate Sensors
        if hasattr(self, 'cmbSensor'):
            self.cmbSensor.clear()
            self.cmbSensor.addItems(SensorBandRegistry.get_available_sensors())
        
        self.update_aoi_controls()
        self.try_extract_standard_aoi()
        
        # Inject QGIS Layer Source Selector
        self.radioBrowse = QRadioButton("Browse Raster")
        self.radioLayer = QRadioButton("QGIS Layer")
        self.radioBrowse.setChecked(True)
        
        # Apply custom styling (Data/Local: Blue)
        from ..utils.helpers import apply_custom_radio_style
        apply_custom_radio_style([self.radioBrowse, self.radioLayer], accent_color="#3B82F6", hover_color="#60A5FA")
        
        radio_layout = QHBoxLayout()
        radio_layout.addWidget(QLabel("Source:"))
        radio_layout.addWidget(self.radioBrowse)
        radio_layout.addWidget(self.radioLayer)
        radio_layout.addStretch()
        
        self.grpDataset.layout().insertLayout(0, radio_layout)
        
        self.cmbQgisLayer = QComboBox()
        self.cmbQgisLayer.setVisible(False)
        self.grpDataset.layout().insertWidget(2, self.cmbQgisLayer)
        
        # Show empty state for band mapping
        self.update_band_mapping_ui()

        # Output Visualization setup
        self.grpOutputVisualization = QGroupBox("Output Visualization")
        vis_layout = QVBoxLayout()
        
        self.radioDefaultVis = QRadioButton("Use Default Visualization")
        self.radioCustomVis = QRadioButton("Use Custom Palette")
        self.radioDefaultVis.setChecked(True)
        
        # Apply custom styling (Primary/Analysis: Cyan)
        apply_custom_radio_style([self.radioDefaultVis, self.radioCustomVis], accent_color="#27D8F7", hover_color="#67E8F9")
        
        radio_vis_layout = QHBoxLayout()
        radio_vis_layout.addWidget(self.radioDefaultVis)
        radio_vis_layout.addWidget(self.radioCustomVis)
        radio_vis_layout.addStretch()
        vis_layout.addLayout(radio_vis_layout)
        
        palette_layout = QHBoxLayout()
        palette_layout.addWidget(QLabel("Palette:"))
        self.cmbCustomPalette = QComboBox()
        self.cmbCustomPalette.setEnabled(False)
        palette_layout.addWidget(self.cmbCustomPalette)
        palette_layout.addStretch()
        vis_layout.addLayout(palette_layout)
        
        self.grpOutputVisualization.setLayout(vis_layout)
        
        # Insert between Dataset and BandMapping
        parent_layout = self.grpDataset.parentWidget().layout()
        idx = parent_layout.indexOf(self.grpDataset)
        if idx >= 0:
            parent_layout.insertWidget(idx + 1, self.grpOutputVisualization)
        
        # Connect signals
        self.radioCustomVis.toggled.connect(self.cmbCustomPalette.setEnabled)
        
        # Populate Palette Combo using shared PaletteManager
        from ..visualization.palette_manager import PaletteManager
        import os
        palettes_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "palettes")
        self.palette_manager = PaletteManager(palettes_dir)
        self.palette_manager.populate_palette_combo(self.cmbCustomPalette)

    def connect_signals(self):
        self.cmbAoi.currentIndexChanged.connect(self.update_aoi_controls)
        self.btnBrowseAoi.clicked.connect(self.browse_vector_file)
        self.btnStartDrawing.clicked.connect(self.start_drawing)
        self.btnBrowseRaster.clicked.connect(self.browse_raster_file)
        
        self.radioBrowse.toggled.connect(self.on_source_toggled)
        self.cmbQgisLayer.currentIndexChanged.connect(self.on_qgis_layer_selected)
        
        if hasattr(self, 'cmbSensor'):
            self.cmbSensor.currentIndexChanged.connect(self.update_band_mapping_ui)
        
        self.btnCancel.clicked.connect(self.reject)
        self.btnRun.clicked.connect(self.on_run_clicked)
        self.btnFinish.clicked.connect(self.on_finish_clicked)

    # ------------------
    # Raster Logic
    # ------------------
    def on_source_toggled(self):
        if self.radioLayer.isChecked():
            self.txtRasterFile.setVisible(False)
            self.btnBrowseRaster.setVisible(False)
            self.cmbQgisLayer.setVisible(True)
            self.populate_qgis_raster_layers()
        else:
            self.txtRasterFile.setVisible(True)
            self.btnBrowseRaster.setVisible(True)
            self.cmbQgisLayer.setVisible(False)

    def populate_qgis_raster_layers(self):
        self.cmbQgisLayer.blockSignals(True)
        self.cmbQgisLayer.clear()
        if not self.iface: 
            self.cmbQgisLayer.blockSignals(False)
            return
            
        from qgis.core import QgsProject, QgsRasterLayer
        layers = QgsProject.instance().mapLayers().values()
        raster_layers = [l for l in layers if isinstance(l, QgsRasterLayer) and l.isValid()]
        
        if not raster_layers:
            self.cmbQgisLayer.addItem("No raster layers available in the current QGIS project.", None)
            self.cmbQgisLayer.setEnabled(False)
        else:
            self.cmbQgisLayer.setEnabled(True)
            self.cmbQgisLayer.addItem("-- Select QGIS Raster Layer --", None)
            for layer in raster_layers:
                self.cmbQgisLayer.addItem(layer.name(), layer.source())
        self.cmbQgisLayer.blockSignals(False)

    def on_qgis_layer_selected(self):
        source = self.cmbQgisLayer.currentData()
        if source:
            self._load_raster_from_path(source)
            
    def browse_raster_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Local Raster", "", "Raster Files (*.tif *.tiff *.vrt *.img)")
        if not path: return
        self._load_raster_from_path(path)
        
    def _load_raster_from_path(self, path):
        try:
            from osgeo import gdal
            gdal.UseExceptions()
        except ImportError:
            QMessageBox.critical(self, "Dependencies Missing", "osgeo (GDAL) is required for Local Raster processing. Please check your QGIS environment.")
            return

        self.txtRasterFile.setText(path)
        self.selected_raster_path = path
        
        try:
            ds = gdal.Open(path)
            if not ds:
                raise Exception("GDAL could not open the dataset.")
                
            self.num_raster_bands = ds.RasterCount
            self.user_band_overrides.clear()
            
            # Cache basic info for fast detection
            self.raster_descriptions = []
            self.raster_metadata_dicts = []
            self.raster_colorinterp = []
            
            for i in range(1, self.num_raster_bands + 1):
                band = ds.GetRasterBand(i)
                self.raster_descriptions.append((band.GetDescription() or "").lower())
                self.raster_metadata_dicts.append(band.GetMetadata() or {})
                self.raster_colorinterp.append(gdal.GetColorInterpretationName(band.GetColorInterpretation()).lower())
                
            # Basic stats for display
            geo_transform = ds.GetGeoTransform()
            if geo_transform:
                res_x, res_y = geo_transform[1], abs(geo_transform[5])
                x_size, y_size = ds.RasterXSize, ds.RasterYSize
                minx = geo_transform[0]
                maxy = geo_transform[3]
                maxx = minx + geo_transform[1] * x_size
                miny = maxy + geo_transform[5] * y_size
                self.raster_extent = [minx, miny, maxx, maxy]
            else:
                res_x, res_y = 0.0, 0.0
                self.raster_extent = None
            
            crs = "Unknown CRS"
            proj = ds.GetProjection()
            self.raster_srs = None
            if proj:
                from osgeo import osr
                srs = osr.SpatialReference(wkt=proj)
                self.raster_srs = srs
                if srs.IsProjected():
                    crs = f"EPSG:{srs.GetAuthorityCode('PROJCS')}" if srs.GetAuthorityCode('PROJCS') else "Projected CRS"
                elif srs.IsGeographic():
                    crs = f"EPSG:{srs.GetAuthorityCode('GEOGCS')}" if srs.GetAuthorityCode('GEOGCS') else "Geographic CRS"
                else:
                    crs = "Custom CRS"
            self.raster_crs_str = crs
                
            meta_text = f"<b>Bands:</b> {self.num_raster_bands} &nbsp;|&nbsp; <b>CRS:</b> {crs} &nbsp;|&nbsp; <b>Resolution:</b> {res_x:.2f}x{res_y:.2f}"
            self.txtRasterMetadata.setHtml(meta_text)
            
            ds = None # close dataset
            
            self.update_band_mapping_ui()
            if self.cmbAoi.currentData() == "FULL_RASTER":
                self.update_aoi_controls()
            
        except Exception as e:
            QMessageBox.critical(self, "Error Reading Raster", f"Could not read metadata from raster:\n{e}")
            self.txtRasterMetadata.setHtml("<b style='color:red;'>Invalid raster file.</b>")
            self.num_raster_bands = 0
            self.update_band_mapping_ui()

    def _determine_band_index(self, requirement: str, sensor_id: str):
        """
        Determines the appropriate band index (1-based) based on priority.
        Returns: (index, status_type) where status_type in ["Recommended", "Auto-detected", "Conflict", "Not detected"]
        """
        req_lower = requirement.lower()
        
        aliases = {
            "nir": ["nir", "near-infrared", "near infrared", "near_infrared"],
            "red": ["red"],
            "green": ["green"],
            "blue": ["blue"],
            "swir1": ["swir1", "swir 1", "shortwave infrared 1"],
            "swir2": ["swir2", "swir 2", "shortwave infrared 2"],
            "red_edge": ["red_edge", "red edge", "red-edge"]
        }
        search_terms = [req_lower] + aliases.get(req_lower, [])
        
        # 1. Check metadata strictly
        meta_match_idx = None
        for i in range(self.num_raster_bands):
            desc = self.raster_descriptions[i]
            meta = self.raster_metadata_dicts[i]
            meta_str = " ".join([str(v).lower() for v in meta.values()])
            color = self.raster_colorinterp[i]
            
            for term in search_terms:
                if term in desc.split() or term in meta_str or term in color:
                    meta_match_idx = i + 1
                    break
            if meta_match_idx: break
            
        if not meta_match_idx:
            # Try substring fallback
            for i in range(self.num_raster_bands):
                desc = self.raster_descriptions[i]
                for term in search_terms:
                    if term in desc:
                        meta_match_idx = i + 1
                        break
                if meta_match_idx: break

        # 2. Check sensor profile recommendation
        rec_band = SensorBandRegistry.get_band_recommendation(sensor_id, requirement)
        
        if rec_band:
            rec_idx = None
            try:
                rec_idx = int(rec_band.replace("Band ", "").strip())
            except:
                pass
                
            if rec_idx and rec_idx <= self.num_raster_bands:
                if meta_match_idx and meta_match_idx != rec_idx:
                    return (rec_idx, "Conflict")
                else:
                    return (rec_idx, "Recommended")
                    
        # 3. If no recommendation, rely on metadata
        if meta_match_idx:
            return (meta_match_idx, "Auto-detected")
            
        return (None, "Not detected")

    def _clear_layout(self, layout):
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
                elif item.layout() is not None:
                    self._clear_layout(item.layout())
                    item.layout().deleteLater()

    def update_band_mapping_ui(self):
        self._clear_layout(self.layoutBands)
        self.band_comboboxes.clear()
        
        if not self.initial_analysis_type:
            return
            
        formula = FormulaRegistry.get_formula(self.initial_analysis_type)
        req_bands = formula.get("required_bands", [])
        
        if not self.selected_raster_path or self.num_raster_bands == 0:
            lbl = QLabel("<i>Select a raster to view band requirements.</i>")
            lbl.setStyleSheet("color: #AFC4D8;")
            self.layoutBands.addWidget(lbl)
            self.btnRun.setEnabled(False)
            return

        sensor_id = "Auto Detect / Unknown"
        if hasattr(self, 'cmbSensor'):
            sensor_id = self.cmbSensor.currentText()

        all_detected = True
        
        for band_var in req_bands:
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(0, 0, 0, 5)
            
            override_idx = self.user_band_overrides.get(band_var)
            idx, status_type = self._determine_band_index(band_var, sensor_id)
            
            active_idx = override_idx if override_idx is not None else idx
            
            if active_idx is None:
                all_detected = False
            
            # Label
            lbl = QLabel(f"<b>{band_var}</b>")
            lbl.setMinimumWidth(80)
            
            # ComboBox
            cmb = QComboBox()
            cmb.addItem("-- Select Band --", None)
            
            # Populate options dynamically
            for i in range(1, self.num_raster_bands + 1):
                item_text = f"Band {i}"
                
                # Suffixes
                if i == override_idx:
                    item_text += " — User selected"
                elif i == idx:
                    if status_type in ["Recommended", "Conflict"]:
                        item_text += " — Recommended"
                    elif status_type == "Auto-detected":
                        item_text += " — Auto-detected"
                        
                cmb.addItem(item_text, i)
                
            if active_idx is not None:
                # Our indices match the combobox item indices (1-based for bands, index 0 is "-- Select Band --")
                cmb.setCurrentIndex(active_idx)
                
            def make_on_change(b_var, combo):
                def on_change(index):
                    combo.blockSignals(True)
                    current_data = combo.itemData(index)
                    
                    if current_data is not None:
                        self.user_band_overrides[b_var] = current_data
                        
                        # Re-evaluate text dynamically without rebuilding
                        c_idx, c_status_type = self._determine_band_index(b_var, sensor_id)
                        for i in range(1, self.num_raster_bands + 1):
                            item_text = f"Band {i}"
                            if i == current_data:
                                item_text += " — User selected"
                            elif i == c_idx:
                                if c_status_type in ["Recommended", "Conflict"]:
                                    item_text += " — Recommended"
                                elif c_status_type == "Auto-detected":
                                    item_text += " — Auto-detected"
                            combo.setItemText(i, item_text)
                    else:
                        if b_var in self.user_band_overrides:
                            del self.user_band_overrides[b_var]
                            
                    combo.blockSignals(False)
                    self.validate_run_state()
                return on_change
                
            cmb.currentIndexChanged.connect(make_on_change(band_var, cmb))
            
            row_layout.addWidget(lbl)
            row_layout.addWidget(cmb)
            row_layout.addStretch()
            
            self.band_comboboxes[band_var] = cmb
            self.layoutBands.addLayout(row_layout)
            
        self.lblPreFlight = QLabel("")
        self.lblPreFlight.setWordWrap(True)
        self.lblPreFlight.setStyleSheet("background-color: #0f172a; padding: 12px; border-radius: 6px; margin-top: 15px; border: 1px solid #334155; color: white;")
        self.layoutBands.addWidget(self.lblPreFlight)
            
        self.validate_run_state()
        
    def validate_run_state(self):
        all_mapped = True
        for cb in self.band_comboboxes.values():
            if cb.currentData() is None:
                all_mapped = False
                break
                
        is_intersecting = True
        intersection_msg = ""
        is_full_raster = self.cmbAoi.currentData() == "FULL_RASTER"
        
        if self.selected_raster_path and hasattr(self, 'raster_extent') and self.raster_extent:
            if is_full_raster:
                is_intersecting = True
            elif self.current_aoi_geojson:
                try:
                    import json
                    from osgeo import ogr, osr
                    geom_json = json.dumps(self.current_aoi_geojson.get("geojson", self.current_aoi_geojson))
                    ogr_geom = ogr.CreateGeometryFromJson(geom_json)
                    
                    if ogr_geom:
                        env = ogr_geom.GetEnvelope() # minX, maxX, minY, maxY
                        minx_a, maxx_a, miny_a, maxy_a = env
                        
                        if hasattr(self, 'raster_crs_str') and self.raster_crs_str != "EPSG:4326" and hasattr(self, 'raster_srs') and self.raster_srs:
                            source_srs = osr.SpatialReference()
                            source_srs.ImportFromEPSG(4326)
                            if hasattr(osr, 'OAMS_TRADITIONAL_GIS_ORDER'):
                                source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                                self.raster_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                            
                            transform = osr.CoordinateTransformation(source_srs, self.raster_srs)
                            ogr_geom_clone = ogr_geom.Clone()
                            ogr_geom_clone.Transform(transform)
                            minx_a, maxx_a, miny_a, maxy_a = ogr_geom_clone.GetEnvelope()
                            
                        minx_r, miny_r, maxx_r, maxy_r = self.raster_extent
                        
                        intersect_x = not (maxx_a < minx_r or minx_a > maxx_r)
                        intersect_y = not (maxy_a < miny_r or miny_a > maxy_r)
                        if miny_r > maxy_r:
                            intersect_y = not (maxy_a < maxy_r or miny_a > miny_r)
                            
                        is_intersecting = intersect_x and intersect_y
                        
                        if is_intersecting:
                            intersection_msg = "✓ Study Area overlaps Raster"
                        else:
                            intersection_msg = f"⚠ Study Area is outside the selected Raster coverage.<br>&nbsp;&nbsp;&nbsp;&nbsp;Raster Extent ({self.raster_crs_str}): {minx_r:.4f}, {miny_r:.4f} → {maxx_r:.4f}, {maxy_r:.4f}<br>&nbsp;&nbsp;&nbsp;&nbsp;AOI Extent ({self.raster_crs_str}): {minx_a:.4f}, {miny_a:.4f} → {maxx_a:.4f}, {maxy_a:.4f}"
                except Exception as e:
                    intersection_msg = f"⚠ Spatial check failed: {e}"
                    is_intersecting = False

        if hasattr(self, 'lblPreFlight'):
            status_html = "<b>Pre-flight Validation</b><br><br>"
            
            if self.selected_raster_path:
                status_html += "<span style='color:#10B981;'>✓ Raster loaded</span><br>"
                status_html += "<span style='color:#10B981;'>✓ CRS detected</span><br>"
            else:
                status_html += "<span style='color:#94a3b8;'>○ Raster not loaded</span><br>"
                
            if is_full_raster:
                status_html += "<span style='color:#10B981;'>✓ Study Area = Full Local Raster</span><br>"
            elif self.current_aoi_geojson:
                status_html += "<span style='color:#10B981;'>✓ Study Area detected</span><br>"
            else:
                status_html += "<span style='color:#94a3b8;'>○ Study Area not configured (Optional)</span><br>"
                
            if self.selected_raster_path and not is_full_raster and self.current_aoi_geojson:
                if is_intersecting:
                    status_html += f"<span style='color:#10B981;'>{intersection_msg}</span><br>"
                else:
                    status_html += f"<span style='color:#ef4444;'>{intersection_msg}</span><br>"
            elif self.selected_raster_path and is_full_raster:
                status_html += "<span style='color:#10B981;'>✓ Valid pixels available</span><br>"
            
            if self.selected_raster_path:
                if all_mapped:
                    status_html += "<span style='color:#10B981;'>✓ Required spectral bands resolved</span>"
                else:
                    status_html += "<span style='color:#f59e0b;'>⚠ Missing required spectral bands</span>"
                
            self.lblPreFlight.setText(status_html)
                
        self.btnRun.setEnabled(all_mapped and self.selected_raster_path != "" and is_intersecting)

    # ------------------
    # AOI Logic
    # ------------------
    def update_aoi_controls(self):
        mode = self.cmbAoi.currentData()
        if mode == "FULL_RASTER":
            self.stkAoiControls.setCurrentIndex(0)
            self.clear_highlight()
            self.current_aoi_geojson = None
            if self.selected_raster_path and hasattr(self, 'raster_extent') and self.raster_extent:
                minx, miny, maxx, maxy = self.raster_extent
                self.lblAoiSummary.setText(
                    f"<b>✓ Full Local Raster selected as Study Area</b><br>"
                    f"Raster Extent: [{minx:.4f}, {miny:.4f}, {maxx:.4f}, {maxy:.4f}]<br>"
                    f"Spatial Coverage: 100% of Raster Extent"
                )
            else:
                self.lblAoiSummary.setText("<i>Pending Local Raster Selection...</i>")
            self.validate_run_state()
        elif mode == "DRAW_POLYGON":
            self.stkAoiControls.setCurrentIndex(1)
            self.clear_highlight()
            self.current_aoi_geojson = None
            self.lblAoiSummary.setText("<i>Pending AOI Configuration...</i>")
            self.validate_run_state()
        elif mode == "VECTOR_FILE":
            self.stkAoiControls.setCurrentIndex(2)
            path = self.txtAoiFile.text().strip()
            if path and not self.current_aoi_geojson:
                try:
                    geom, crs = helpers.get_vector_file_geometry(path)
                    self._process_geometry(geom, crs)
                except:
                    self.current_aoi_geojson = None
                    self.lblAoiSummary.setText("<i>Pending AOI Configuration...</i>")
                    self.validate_run_state()
            elif not path:
                self.clear_highlight()
                self.current_aoi_geojson = None
                self.lblAoiSummary.setText("<i>Pending AOI Configuration...</i>")
                self.validate_run_state()
        else:
            self.stkAoiControls.setCurrentIndex(0)
            self.try_extract_standard_aoi()

    def try_extract_standard_aoi(self):
        mode = self.cmbAoi.currentData()
        if mode in ["MAP_EXTENT", "LAYER_BBOX", "SELECTED_FEATURES", "AUTO_SINGLE_POLYGON"]:
            self.extract_aoi(silent=True)

    def _process_geometry(self, geom, crs):
        try:
            metrics = helpers.normalize_and_validate_geometry(geom, crs)
            self.current_aoi_geojson = metrics
            
            self.clear_highlight()
            if self.iface:
                self.highlight_band = QgsRubberBand(self.iface.mapCanvas(), QgsWkbTypes.PolygonGeometry)
                self.highlight_band.setColor(QColor(234, 179, 8, 120))
                self.highlight_band.setWidth(3)
                
                canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
                temp_geom = QgsGeometry(geom)
                if crs != canvas_crs:
                    from qgis.core import QgsCoordinateTransform, QgsProject
                    xform = QgsCoordinateTransform(crs, canvas_crs, QgsProject.instance())
                    temp_geom.transform(xform)
                self.highlight_band.addGeometry(temp_geom, None)
            
            bbox = metrics["bbox"]
            summary_html = f"<b>AOI Captured Successfully</b><br>Area: {metrics['area_sqdeg']:.6f} sq deg"
            self.lblAoiSummary.setText(summary_html)
            self.validate_run_state()
            
        except Exception as e:
            self.current_aoi_geojson = None
            self.clear_highlight()
            self.lblAoiSummary.setText(f"<b style='color:red;'>Validation Failed:</b> {e}")
            self.validate_run_state()

    def browse_vector_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Vector File", "", "Vector Files (*.shp *.gpkg *.geojson *.kml)")
        if not path: return
        self.txtAoiFile.setText(path)
        try:
            geom, crs = helpers.get_vector_file_geometry(path)
            self._process_geometry(geom, crs)
        except Exception as e:
            QMessageBox.critical(self, "File Error", str(e))

    def start_drawing(self):
        if not self.iface: return
        self.hide()
        self.iface.mainWindow().activateWindow()
        self.previous_map_tool = self.iface.mapCanvas().mapTool()
        self.map_tool = PolygonMapTool(self.iface.mapCanvas())
        self.map_tool.geometryCaptured.connect(self.on_geometry_captured)
        self.map_tool.drawingCanceled.connect(self.on_drawing_canceled)
        self.iface.mapCanvas().setMapTool(self.map_tool)

    def on_geometry_captured(self, geom):
        self._restore_from_drawing()
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        self._process_geometry(geom, canvas_crs)

    def on_drawing_canceled(self):
        self._restore_from_drawing()
        self.lblAoiSummary.setText("<b style='color:red;'>Drawing canceled.</b>")

    def _restore_from_drawing(self):
        if self.iface and self.previous_map_tool:
            self.iface.mapCanvas().setMapTool(self.previous_map_tool)
        self.map_tool = None
        self.show()
        self.activateWindow()
        self.raise_()

    def extract_aoi(self, silent=False) -> bool:
        mode = self.cmbAoi.currentData()
        if mode == "VECTOR_FILE":
            path = self.txtAoiFile.text().strip()
            if not path or not self.current_aoi_geojson:
                if not silent: QMessageBox.warning(self, "AOI Required", "Please provide an AOI.")
                return False
            return True
        elif mode == "DRAW_POLYGON":
            if not self.current_aoi_geojson:
                if not silent: QMessageBox.warning(self, "AOI Required", "Please provide an AOI.")
                return False
            return True
            
        try:
            if mode == "MAP_EXTENT": geom, crs = helpers.get_map_extent_geometry(self.iface)
            elif mode == "LAYER_BBOX": geom, crs = helpers.get_active_layer_extent_geometry(self.iface)
            elif mode == "SELECTED_FEATURES": geom, crs = helpers.get_selected_feature_geometry(self.iface)
            elif mode == "AUTO_SINGLE_POLYGON": geom, crs = helpers.get_all_features_geometry(self.iface)
            else: return False
            self._process_geometry(geom, crs)
            return self.current_aoi_geojson is not None
        except Exception as e:
            if not silent: QMessageBox.critical(self, "AOI Error", f"Failed: {e}")
            return False

    def clear_highlight(self):
        if self.highlight_band and self.iface:
            self.iface.mapCanvas().scene().removeItem(self.highlight_band)
            self.highlight_band = None

    # ------------------
    # Execution Logic
    # ------------------
    def on_run_clicked(self):
        # Validate that GDAL can open it natively
        try:
            from osgeo import gdal
            ds = gdal.Open(self.selected_raster_path)
            if not ds:
                raise Exception("Unable to open the selected raster with the current QGIS/GDAL environment.")
            ds = None
        except Exception as e:
            QMessageBox.critical(self, "Native GDAL Error", str(e))
            return
            
        # Allow running without AOI
        mode = self.cmbAoi.currentData()
        if mode not in ["MAP_EXTENT", "LAYER_BBOX", "FULL_RASTER"]: 
            if mode in ["DRAW_POLYGON", "VECTOR_FILE"] and not self.current_aoi_geojson:
                if not self.extract_aoi():
                    return
        
        band_mapping = {var: cb.currentData() for var, cb in self.band_comboboxes.items()}
        sensor_name = self.cmbSensor.currentText() if hasattr(self, 'cmbSensor') else "Local Image"
        
        params = {
            "analysis_type": self.initial_analysis_type,
            "raster_path": self.selected_raster_path,
            "band_mapping": band_mapping,
            "aoi_geojson": self.current_aoi_geojson,
            "aoi_path": self.txtAoiFile.text().strip() if self.cmbAoi.currentData() == "VECTOR_FILE" else "UI/Map Canvas",
            "index_threshold": None,
            "satellite_name": sensor_name
        }
        
        self.stackedWidget.setCurrentIndex(1) # Progress
        self.btnRun.setVisible(False)
        self.btnCancel.setEnabled(False)
        
        self.worker = LocalAnalysisWorker(self.analysis_engine, params)
        self.worker.progress_update.connect(self.update_progress)
        self.worker.worker_completed.connect(self.on_worker_completed)
        self.worker.worker_failed.connect(self.on_worker_failed)
        self.worker.start()


    def update_progress(self, message, percent):
        self.lblStatus.setText(message)
        self.progressBar.setValue(percent)

    def on_worker_completed(self, result: AnalysisResult):
        self.worker = None
        
        self.lblStatus.setText("<span style='color: green; font-weight: bold;'>✓ Analysis Complete. Loading into QGIS...</span>")
        self.progressBar.setValue(100)
        
        from ..services.visualization_service import VisualizationService
        vis_service = VisualizationService.get_instance()
        try:
            vis_service.visualization_completed.disconnect(self.on_visualization_completed)
            vis_service.progress_update.disconnect(self.update_progress)
        except TypeError:
            pass
            
        vis_service.visualization_completed.connect(self.on_visualization_completed)
        vis_service.progress_update.connect(self.update_progress)
        
        self.final_result = result
        
        # Inject Custom Palette override into rendering pipeline if selected
        if hasattr(self, 'radioCustomVis') and self.radioCustomVis.isChecked():
            try:
                palette_data = self.palette_manager.load(self.cmbCustomPalette.currentText())
                if palette_data:
                    if not result.visualization_params:
                        result.visualization_params = {}
                    result.visualization_params["palette"] = palette_data
            except Exception as e:
                self.logger.error(f"Failed to inject custom palette for Local Raster: {e}", exc_info=True)
                # Failsafe: Continue with default visualization
                
        vis_service.visualize_local_result(result)
        
    def on_visualization_completed(self, vis_result):
        self.stackedWidget.setCurrentIndex(2) # Summary
        self.final_vis_result = vis_result
        
        if not vis_result.success:
            html = f"<h3 style='color:red;'>Visualization Failed</h3><p>{vis_result.error_message}</p>"
            self.txtSummary.setHtml(html)
        else:
            html = f"<h3>{self.final_result.formula_name}</h3><p>Successfully processed local raster and loaded into QGIS.</p>"
            self.txtSummary.setHtml(html)
            
        self.btnCancel.setVisible(False)
        self.btnFinish.setVisible(True)

    def on_worker_failed(self, error_msg):
        self.worker = None
        QMessageBox.critical(self, "Analysis Failed", error_msg)
        self.stackedWidget.setCurrentIndex(0)
        self.btnRun.setVisible(True)
        self.btnCancel.setEnabled(True)
        
    def on_finish_clicked(self):
        if hasattr(self, 'final_result') and hasattr(self, 'final_vis_result'):
            self.analysis_workflow_finished.emit(self.final_result, self.final_vis_result)
        self.accept()

    def reject(self):
        self.clear_highlight()
        if getattr(self, 'map_tool', None) and self.iface:
            self.iface.mapCanvas().setMapTool(getattr(self, 'previous_map_tool', None))
        super().reject()

    def accept(self):
        self.clear_highlight()
        if getattr(self, 'map_tool', None) and self.iface:
            self.iface.mapCanvas().setMapTool(getattr(self, 'previous_map_tool', None))
        super().accept()
