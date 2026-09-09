import os
import urllib.request
import datetime
import threading
from typing import Optional, Dict, Any, List

try:
    from qgis.PyQt.QtWidgets import QMessageBox
    from PyQt6.QtWidgets import QDialog, QHeaderView, QFileDialog, QCheckBox, QAbstractItemView
    from PyQt6.QtGui import QStandardItemModel, QStandardItem, QPixmap, QImage, QColor
    from PyQt6 import uic, QtCore
    from qgis.core import QgsGeometry, QgsWkbTypes
    from qgis.gui import QgsRubberBand
except ImportError:
    pass

from ..services.connection_service import ConnectionService
from ..services.layer_service import LayerService
from ..services.analysis_engine import AnalysisEngine
from ..services.visualization_service import VisualizationService
from ..analysis.index_registry import IndexRegistry
from ..analysis.satellite_registry import SatelliteRegistry
from ..models.analysis_context import AnalysisContext
from ..models.analysis_result import AnalysisResult
from ..models.visualization_result import VisualizationResult
from ..utils.logger import get_logger
from ..utils import helpers
from ..utils.profiler import PerformanceProfiler
from ..utils.map_tools import PolygonMapTool

class AnalysisWorker(QtCore.QThread):
    """Runs the analysis pipeline in a background thread."""
    worker_failed = QtCore.pyqtSignal(str)
    worker_completed = QtCore.pyqtSignal(AnalysisResult)
    
    def __init__(self, engine, params):
        super().__init__()
        self.engine = engine
        self.params = params
        
    def run(self):
        import logging
        import traceback
        logger = logging.getLogger(__name__)
        logger.info("[Generic] Step 1: AnalysisWorker.run() invoked")
        
        # Lock the session to prevent project discovery from clobbering the active project
        from ..services.connection_service import ConnectionService
        gee_provider = ConnectionService.get_instance().gee_provider
        gee_provider.acquire_session_lock()
        
        try:
            if "context" in self.params:
                logger.info(f"[Generic] Step 2: Extracting context for {self.params['context'].index_definition['id']}")
                logger.info("[Generic] Step 3: Invoking AnalysisEngine.run_generic_workflow()")
                result = self.engine.run_generic_workflow(self.params["context"])
                logger.info("[Generic] Step 4: run_generic_workflow() returned successfully")
                self.worker_completed.emit(result)
            else:
                analysis_result = self.engine.run_analysis_workflow(**self.params)
                self.worker_completed.emit(analysis_result)
        except Exception as e:
            error_msg = traceback.format_exc()
            logger.error(f"[Generic] Exception caught in worker thread:\n{error_msg}")
            self.worker_failed.emit(str(e) + "\n\nTraceback:\n" + error_msg)
        finally:
            gee_provider.release_session_lock()

class AnalysisWizardDialog(QDialog):
    """Generic wizard for discovering imagery and executing analysis."""
    
    analysis_workflow_finished = QtCore.pyqtSignal(AnalysisResult, VisualizationResult)
    
    def __init__(self, parent: Optional[QDialog], analysis_type: str, iface: Any = None):
        super().__init__(parent)
        self.main_dialog_ref = parent
        self.logger = get_logger(__name__)
        self.analysis_type = analysis_type
        self.iface = iface
        self.layer_service = LayerService.get_instance()
        self.connection_service = ConnectionService.get_instance()
        self.analysis_engine = AnalysisEngine.get_instance()
        
        # State
        self.current_aoi_geojson: Optional[Dict[str, Any]] = None
        self.cached_image_list = []
        self.map_tool: Optional[PolygonMapTool] = None
        self.previous_map_tool = None
        self.highlight_band: Optional[QgsRubberBand] = None
        self.mask_checkboxes: List[QCheckBox] = []
        self.worker = None
        
        # UI Setup
        ui_path = os.path.join(os.path.dirname(__file__), '..', 'ui', 'analysis_wizard.ui')
        uic.loadUi(ui_path, self)
        
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowType.WindowMaximizeButtonHint | QtCore.Qt.WindowType.WindowMinimizeButtonHint)
        
        # Apply plugin scrollbar styling globally to the dialog
        from ..utils.helpers import apply_scrollbar_style, apply_custom_radio_style, apply_custom_checkbox_style
        apply_scrollbar_style(self)
        
        # FIX: The inline styleSheets on txtSummary and txtMetadata override 
        # the QScrollBar pseudo-controls if applied to the parent dialog.
        # To fix this, we must wrap their inline, selector-less styles in an explicit
        # QTextBrowser { ... } selector. This preserves the dark navy background while
        # allowing us to apply the QScrollBar subcontrols safely to the QTextBrowser itself,
        # which restores native PM_ScrollBarExtent metrics and paints the green handle perfectly.
        if hasattr(self, 'txtSummary'):
            base_style = self.txtSummary.styleSheet()
            if base_style and not base_style.strip().startswith('QTextBrowser'):
                self.txtSummary.setStyleSheet(f"QTextBrowser {{ {base_style} }}")
            apply_scrollbar_style(self.txtSummary)
            # Ensure the width is set globally for this widget's scrollbar
            self.txtSummary.setStyleSheet(self.txtSummary.styleSheet() + " QScrollBar:vertical { width: 14px; }")
            
        if hasattr(self, 'txtMetadata'):
            base_style = self.txtMetadata.styleSheet()
            if base_style and not base_style.strip().startswith('QTextBrowser'):
                self.txtMetadata.setStyleSheet(f"QTextBrowser {{ {base_style} }}")
            apply_scrollbar_style(self.txtMetadata)
            self.txtMetadata.setStyleSheet(self.txtMetadata.styleSheet() + " QScrollBar:vertical { width: 14px; }")
        
        # Style Acquisition Mode Radio Buttons (Primary/Cyan)
        if hasattr(self, 'radSingle') and hasattr(self, 'radCollection'):
            apply_custom_radio_style([self.radSingle, self.radCollection], accent_color="#27D8F7", hover_color="#67E8F9")
        
        # Surgical scoped styling for Download Method radio indicators
        # Maintains exact 20x20px overall footprint (16+2+2 = 10+5+5) to prevent layout shift
        radio_style = """
            QRadioButton#radDirectDownload::indicator, QRadioButton#radGoogleDrive::indicator {
                width: 16px;
                height: 16px;
                border-radius: 10px;
                border: 2px solid #5A7494;
                background-color: transparent;
            }
            QRadioButton#radDirectDownload::indicator:hover, QRadioButton#radGoogleDrive::indicator:hover {
                border: 2px solid #14C8A0;
            }
            QRadioButton#radDirectDownload::indicator:checked, QRadioButton#radGoogleDrive::indicator:checked {
                width: 10px;
                height: 10px;
                border: 5px solid #10B981;
                background-color: #FFFFFF;
            }
            QRadioButton#radDirectDownload::indicator:checked:hover, QRadioButton#radGoogleDrive::indicator:checked:hover {
                border: 5px solid #14C8A0;
            }
        """
        current_style = self.styleSheet() or ""
        self.setStyleSheet(current_style + radio_style)
        
        if analysis_type == "download_scene":
            self.lblTitle.setText("Download Scene")
        else:
            self.lblTitle.setText(f"New {analysis_type} Calculation")
            
        # --- SURGICAL GEOMETRY FIX: QSizePolicy ---
        # The hidden pageScene forces a massive minimum height that exceeds 
        # the available screen size (720px) due to grpPreview's internal requirements.
        # By setting its size policy to Ignored, we decouple it from QStackedWidget's
        # layout calculations. This completely prevents the minimum-height inflation
        # without altering the visual hierarchy, scrollbars, or layout ownership of Page 2.
        from PyQt6 import QtWidgets
        if hasattr(self, 'pageScene'):
            self.pageScene.setSizePolicy(
                QtWidgets.QSizePolicy.Policy.Ignored,
                QtWidgets.QSizePolicy.Policy.Ignored
            )
            
        # Set a reasonable default dialog height that safely fits within a 720px screen constraint
        self.resize(900, 660)
        
        # -----------------------------
            
        self.stackedWidget.setCurrentWidget(self.pageConfig)
        self.btnFinish.setVisible(False)
        
        # Models
        self.scenes_model = QStandardItemModel()
        self.scenes_model.setHorizontalHeaderLabels(["Select", "Image ID", "Date", "Cloud %", "Cov %", "Cov km²", "Score"])
        self.tblScenes.setModel(self.scenes_model)
        
        # Apply custom centered checkbox delegate to the Select column
        from .widgets.centered_checkbox_delegate import CenteredCheckboxDelegate
        self.centered_checkbox_delegate = CenteredCheckboxDelegate(self.tblScenes)
        self.tblScenes.setItemDelegateForColumn(0, self.centered_checkbox_delegate)
        
        # Disable row selection so users rely on checkboxes
        self.tblScenes.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.tblScenes.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tblScenes.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tblScenes.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        
        self.setup_ui()
        
        # Setup AOI combo box with fixed order and mode identifiers
        self.AOI_MODES = [
            ("Selected Features in Active Layer", "SELECTED_FEATURES"),
            ("✔ Active Study Area (Detected Automatically)", "AUTO_SINGLE_POLYGON"),
            ("Browse Vector File", "VECTOR_FILE"),
            ("Draw Polygon", "DRAW_POLYGON"),
            ("Current Map Extent", "MAP_EXTENT"),
            ("Active Layer Bounding Box", "LAYER_BBOX")
        ]
        
        self.cmbAoi.clear()
        for text, mode_id in self.AOI_MODES:
            self.cmbAoi.addItem(text, mode_id)
            
        self.connect_signals()
        
        # Analyze project state for smart AOI detection
        from qgis.core import QgsProject, QgsMapLayerType, QgsWkbTypes
        layer = helpers.get_current_layer(self.iface)
        
        has_polygon_layer = False
        is_single_polygon = False
        has_selected_features = False
        
        if layer and layer.type() == QgsMapLayerType.VectorLayer and layer.geometryType() == QgsWkbTypes.PolygonGeometry:
            has_polygon_layer = True
            if layer.featureCount() == 1:
                is_single_polygon = True
            if layer.selectedFeatureCount() > 0:
                has_selected_features = True

        # Enable/Disable items based on state
        model = self.cmbAoi.model()
        for i in range(self.cmbAoi.count()):
            mode_id = self.cmbAoi.itemData(i)
            item = model.item(i)
            
            if mode_id == "AUTO_SINGLE_POLYGON":
                item.setEnabled(is_single_polygon)
            elif mode_id == "SELECTED_FEATURES":
                item.setEnabled(has_polygon_layer)

        # Smart detection priority
        if has_selected_features:
            self.cmbAoi.setCurrentIndex(self.cmbAoi.findData("SELECTED_FEATURES"))
        elif is_single_polygon:
            self.cmbAoi.setCurrentIndex(self.cmbAoi.findData("AUTO_SINGLE_POLYGON"))
        else:
            self.cmbAoi.setCurrentIndex(self.cmbAoi.findData("VECTOR_FILE"))
            
        self.update_aoi_controls()
        self.toggle_acquisition_mode()
        self.update_dataset_filters()
        self.try_extract_standard_aoi()
        
        # Restore default Image Collection behavior for analytical workspaces (Vegetation, Water, etc.)
        if self.analysis_type != "download_scene":
            self.radCollection.setChecked(True)
        else:
            self.radSingle.setChecked(True)
            
        self.toggle_acquisition_mode()
        
    def setup_ui(self):
        end_date = datetime.date.today()
        start_date = end_date - datetime.timedelta(days=90)
        self.dateStart.setDate(start_date)
        self.dateEnd.setDate(end_date)
        
        provider_name = self.connection_service.current_provider()
        if provider_name == "Google Earth Engine":
            datasets = self.layer_service.gee_provider.supported_datasets()
        else:
            datasets = ["Local File / COG"]
            
        self.cmbDataset.clear()
        self.cmbDataset.addItems(datasets)
        self.btnBack.setVisible(False)
        self.btnNext.setText("Search Images")
        
        self.cmbComposite.setItemData(0, "Median value. Excellent for removing clouds.", QtCore.Qt.ItemDataRole.ToolTipRole)
        self.cmbComposite.setItemData(1, "Average value. Fast but susceptible to clouds.", QtCore.Qt.ItemDataRole.ToolTipRole)
        
        from PyQt6.QtWidgets import QPushButton
        self.btnRefresh = QPushButton("Force Refresh")
        self.btnRefresh.setToolTip("Clear cache and force a new Earth Engine query.")
        self.btnRefresh.clicked.connect(self.on_refresh_clicked)
        if hasattr(self, 'btnNext'):
            parent_layout = self.btnNext.parentWidget().layout()
            if parent_layout:
                parent_layout.insertWidget(parent_layout.indexOf(self.btnNext), self.btnRefresh)
        
        # Group Radio Buttons to isolate Acquisition Mode from Download Method
        from PyQt6.QtWidgets import QButtonGroup
        self.acqButtonGroup = QButtonGroup(self)
        self.acqButtonGroup.addButton(self.radSingle)
        self.acqButtonGroup.addButton(self.radCollection)
        
        self.dlButtonGroup = QButtonGroup(self)
        if hasattr(self, 'radDirectDownload'):
            self.dlButtonGroup.addButton(self.radDirectDownload)
        if hasattr(self, 'radGoogleDrive'):
            self.dlButtonGroup.addButton(self.radGoogleDrive)
            
        # Hide visualization controls if Download Scene mode
        if self.analysis_type == "download_scene":
            if hasattr(self, 'cmbOutputMode'):
                self.cmbOutputMode.setVisible(False)
                # Hide the label preceding it if possible by parent layout, but the prompt says 
                # "hide their corresponding labels". 
                # Because we don't have object names for labels in the UI, we can iterate the layout.
            
        self._setup_dynamic_controls()

    def _setup_dynamic_controls(self):
        from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QLabel, QComboBox, QDoubleSpinBox
        from ..analysis.raster_metadata import get_raster_metadata
        
        metadata = get_raster_metadata(self.analysis_type)
        
        # 1. Scientific Threshold & Export Resolution (Page 1)
        self.spinThreshold = QDoubleSpinBox()
        self.spinThreshold.setRange(-10000, 10000)
        self.spinThreshold.setSingleStep(0.05)
        self.spinThreshold.setValue(metadata.recommended_threshold)
        
        layout_threshold = QHBoxLayout()
        lbl_thresh = QLabel("Index Threshold (Scientific):")
        lbl_thresh.setMinimumWidth(150)
        lbl_thresh.setToolTip("Determines binary classification (e.g. Vegetation vs Non-Vegetation) for scientific area analysis.")
        layout_threshold.addWidget(lbl_thresh)
        layout_threshold.addWidget(self.spinThreshold)
        
        # Add Export Resolution controls
        self.cmbResMode = QComboBox()
        self.cmbResMode.addItems(["Dataset Default (Recommended)", "Automatic (Optimize for large AOIs)", "Custom"])
        self.cmbResMode.setToolTip("Control the pixel size (spatial resolution) of the exported raster.")
        
        self.spinCustomRes = QDoubleSpinBox()
        self.spinCustomRes.setRange(1, 10000)
        self.spinCustomRes.setSuffix(" m")
        self.spinCustomRes.setDecimals(1)
        self.spinCustomRes.setValue(10.0)
        self.spinCustomRes.setEnabled(False)
        
        self.lblResWarning = QLabel("")
        self.lblResWarning.setStyleSheet("color: #EAB308; font-size: 8pt;")
        self.lblResWarning.setVisible(False)
        
        self.cmbResMode.currentTextChanged.connect(self.on_res_mode_changed)
        self.spinCustomRes.valueChanged.connect(self.on_custom_res_changed)
        
        layout_res = QHBoxLayout()
        lbl_res = QLabel("Export Resolution:")
        lbl_res.setMinimumWidth(150)
        layout_res.addWidget(lbl_res)
        layout_res.addWidget(self.cmbResMode)
        layout_res.addWidget(self.spinCustomRes)
        
        if hasattr(self, 'grpParameters'):
            self.grpParameters.layout().addLayout(layout_threshold)
            self.grpParameters.layout().addLayout(layout_res)
            self.grpParameters.layout().addWidget(self.lblResWarning)
            
            if self.analysis_type == "download_scene":
                lbl_thresh.setVisible(False)
                self.spinThreshold.setVisible(False)
            
        # 2. Visualization Preview Settings (Page 2)
        from ..visualization.palette_manager import PaletteManager
        palettes_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "palettes")
        self.palette_manager = PaletteManager(palettes_dir)
        
        self.cmbPreviewPalette = QComboBox()
        self._populate_palette_combo()
        
        # Determine visualization range defaults based on loaded metadata
        idx = self.cmbPreviewPalette.findText(metadata.recommended_palette)
        if idx >= 0:
            self.cmbPreviewPalette.setCurrentIndex(idx)
            
        self.spinPreviewMin = QDoubleSpinBox()
        self.spinPreviewMin.setRange(-10000, 10000)
        self.spinPreviewMin.setValue(metadata.recommended_display_range[0])
        self.spinPreviewMax = QDoubleSpinBox()
        self.spinPreviewMax.setRange(-10000, 10000)
        self.spinPreviewMax.setValue(metadata.recommended_display_range[1])
        
        preview_controls_lay = QVBoxLayout()
        
        pal_lay = QHBoxLayout()
        pal_lay.addWidget(QLabel("Palette:"))
        pal_lay.addWidget(self.cmbPreviewPalette)
        preview_controls_lay.addLayout(pal_lay)
        
        stretch_lay = QHBoxLayout()
        self.cmbStretchMode = QComboBox()
        self.cmbStretchMode.addItems(["Original", "Custom"])
        self.cmbStretchMode.setCurrentText("Original")
        stretch_lay.addWidget(QLabel("Stretch Mode:"))
        stretch_lay.addWidget(self.cmbStretchMode)
        preview_controls_lay.addLayout(stretch_lay)
        
        minmax_lay = QHBoxLayout()
        minmax_lay.addWidget(QLabel("Min/Max:"))
        minmax_lay.addWidget(self.spinPreviewMin)
        minmax_lay.addWidget(self.spinPreviewMax)
        preview_controls_lay.addLayout(minmax_lay)
        
        if hasattr(self, 'grpPreview'):
            self.grpPreview.layout().insertLayout(0, preview_controls_lay)
            
        # Isolate Download Scene visibility
        if self.analysis_type == "download_scene":
            self.cmbPreviewPalette.setVisible(False)
            self.spinPreviewMin.setVisible(False)
            self.spinPreviewMax.setVisible(False)
            for i in range(pal_lay.count()):
                w = pal_lay.itemAt(i).widget()
                if w: w.setVisible(False)
            for i in range(minmax_lay.count()):
                w = minmax_lay.itemAt(i).widget()
                if w: w.setVisible(False)
            if hasattr(self, 'cmbOutputMode'):
                self.cmbOutputMode.setVisible(False)
                # Find and hide its preceding label
                try:
                    layout = self.cmbOutputMode.parentWidget().layout()
                    for i in range(layout.count()):
                        item = layout.itemAt(i)
                        if item.widget() == self.cmbOutputMode and i > 0:
                            prev = layout.itemAt(i-1).widget()
                            if prev: prev.setVisible(False)
                except Exception:
                    pass
            
        # Connect signals for live preview updates
        self.cmbPreviewPalette.currentTextChanged.connect(self.on_preview_setting_changed)
        self.spinPreviewMin.valueChanged.connect(self.on_preview_setting_changed)
        self.spinPreviewMax.valueChanged.connect(self.on_preview_setting_changed)
        self._update_default_resolution_display()

    def _populate_palette_combo(self):
        self.palette_manager.populate_palette_combo(self.cmbPreviewPalette)

    def _update_default_resolution_display(self, *args):
        if not hasattr(self, 'cmbResMode') or not hasattr(self, 'spinCustomRes') or not hasattr(self, 'cmbDataset'):
            return
            
        mode = self.cmbResMode.currentText()
        satellite = self.cmbDataset.currentText()
        native_res = 10.0 if "Sentinel" in satellite else 30.0
        
        if "Dataset Default" in mode:
            self.spinCustomRes.blockSignals(True)
            self.spinCustomRes.setValue(native_res)
            self.spinCustomRes.blockSignals(False)

    def on_res_mode_changed(self, mode):
        self.spinCustomRes.setEnabled(mode == "Custom")
        self._update_default_resolution_display()
        self.on_custom_res_changed()
        
    def on_custom_res_changed(self, *args):
        if self.cmbResMode.currentText() != "Custom":
            self.lblResWarning.setVisible(False)
            return
            
        satellite = self.cmbDataset.currentText()
        native_res = 10 if "Sentinel" in satellite else 30
        
        if self.spinCustomRes.value() < native_res:
            self.lblResWarning.setText(f"Warning: Requesting {self.spinCustomRes.value()}m from {native_res}m native dataset is only resampling. It does not increase true spatial resolution.")
            self.lblResWarning.setVisible(True)
        else:
            self.lblResWarning.setVisible(False)
            
    def on_preview_setting_changed(self, *args):
        # Refresh the thumbnail with the new visualization parameters
        if hasattr(self, 'stackedWidget') and self.stackedWidget.currentIndex() == 1:
            QtCore.QTimer.singleShot(100, self.load_thumbnail)
        
    def connect_signals(self):
        self.btnNext.clicked.connect(self.on_next)
        self.btnBack.clicked.connect(self.on_back)
        self.btnCancel.clicked.connect(self.reject)
        self.btnFinish.clicked.connect(self.on_finish_clicked)
        
        if hasattr(self, 'btnDownloadScene'):
            self.btnDownloadScene.clicked.connect(self.on_download_scene_clicked)
        
        self.cmbDataset.currentIndexChanged.connect(self.update_dataset_filters)
        self.cmbDataset.currentIndexChanged.connect(self._update_default_resolution_display)
        self.radSingle.toggled.connect(self.toggle_acquisition_mode)
        self.radCollection.toggled.connect(self.toggle_acquisition_mode)
        
        # Also connect the button group as a fallback guarantee
        if hasattr(self, 'acqButtonGroup'):
            self.acqButtonGroup.buttonClicked.connect(self.toggle_acquisition_mode)
        
        self.cmbAoi.currentIndexChanged.connect(self.update_aoi_controls)
        self.btnStartDrawing.clicked.connect(self.start_drawing)
        self.btnBrowseAoi.clicked.connect(self.browse_vector_file)
        
        if hasattr(self, 'btnSelectAll'):
            self.btnSelectAll.clicked.connect(self.select_all_scenes)
            self.btnDeselectAll.clicked.connect(self.deselect_all_scenes)
            self.btnInvertSelection.clicked.connect(self.invert_selection)
            self.btnRecommendOnly.clicked.connect(self.select_recommended_only)
            
        self.scenes_model.itemChanged.connect(self.on_checkbox_toggled)
        
        # Engine Signals
        self.analysis_engine.progress_update.connect(self.on_engine_progress)
        self.analysis_engine.export_task_file_requested.connect(self.on_export_task_file_requested)
        
    def select_all_scenes(self):
        if self.radSingle.isChecked(): return
        self._set_all_checkboxes(True)
        
    def deselect_all_scenes(self):
        self._set_all_checkboxes(False)
        
    def invert_selection(self):
        if self.radSingle.isChecked(): return
        for row in range(self.scenes_model.rowCount()):
            item = self.scenes_model.item(row, 0)
            item.setCheckState(QtCore.Qt.CheckState.Unchecked if item.checkState() == QtCore.Qt.CheckState.Checked else QtCore.Qt.CheckState.Checked)
        self.load_thumbnail()
            
    def select_recommended_only(self):
        self.deselect_all_scenes()
        if self.scenes_model.rowCount() > 0:
            self.scenes_model.item(0, 0).setCheckState(QtCore.Qt.CheckState.Checked)
            
    def _set_all_checkboxes(self, state: bool):
        s = QtCore.Qt.CheckState.Checked if state else QtCore.Qt.CheckState.Unchecked
        for row in range(self.scenes_model.rowCount()):
            self.scenes_model.item(row, 0).setCheckState(s)
        self.load_thumbnail()

    def on_checkbox_toggled(self, item):
        """Handle single-select enforcement and trigger preview."""
        if item.column() != 0: return

        # Enforce single selection
        if self.radSingle.isChecked():
            if item.checkState() == QtCore.Qt.CheckState.Checked:
                try: self.scenes_model.itemChanged.disconnect(self.on_checkbox_toggled)
                except TypeError: pass
                
                for row in range(self.scenes_model.rowCount()):
                    other_item = self.scenes_model.item(row, 0)
                    if other_item != item and other_item.checkState() == QtCore.Qt.CheckState.Checked:
                        other_item.setCheckState(QtCore.Qt.CheckState.Unchecked)
                        
                self.scenes_model.itemChanged.connect(self.on_checkbox_toggled)
            else:
                # If they try to uncheck the only scene in Single Mode, force it back
                checked = self.get_selected_image_ids()
                if len(checked) == 0:
                    try: self.scenes_model.itemChanged.disconnect(self.on_checkbox_toggled)
                    except TypeError: pass
                    item.setCheckState(QtCore.Qt.CheckState.Checked)
                    self.scenes_model.itemChanged.connect(self.on_checkbox_toggled)
                    return # no change, so skip thumbnail update

        # Update preview (debounce lightly)
        QtCore.QTimer.singleShot(100, self.load_thumbnail)
        
    def get_selected_image_ids(self) -> List[str]:
        ids = []
        for row in range(self.scenes_model.rowCount()):
            if self.scenes_model.item(row, 0).checkState() == QtCore.Qt.CheckState.Checked:
                # Use the model's textual value instead of the original unsorted list index
                ids.append(self.scenes_model.item(row, 1).text())
        return ids

    def toggle_acquisition_mode(self):
        is_collection = self.radCollection.isChecked()
        if hasattr(self, 'panelComposite'): self.panelComposite.setVisible(is_collection)
        if hasattr(self, 'panelSelectionControls'): self.panelSelectionControls.setVisible(is_collection)

        # Ensure multi-scene selection controls are visible exactly when Image Collection is selected
        if hasattr(self, 'btnSelectAll'): self.btnSelectAll.setVisible(is_collection)
        if hasattr(self, 'btnDeselectAll'): self.btnDeselectAll.setVisible(is_collection)
        if hasattr(self, 'btnInvertSelection'): self.btnInvertSelection.setVisible(is_collection)
        if hasattr(self, 'btnRecommendOnly'): self.btnRecommendOnly.setVisible(is_collection)

        if not is_collection:
            checked = self.get_selected_image_ids()
            if len(checked) == 0:
                self.select_recommended_only()
            elif len(checked) > 1:
                # Keep the first checked scene, uncheck the rest
                first_found = False
                try: self.scenes_model.itemChanged.disconnect(self.on_checkbox_toggled)
                except TypeError: pass
                
                for row in range(self.scenes_model.rowCount()):
                    item = self.scenes_model.item(row, 0)
                    if item.checkState() == QtCore.Qt.CheckState.Checked:
                        if not first_found:
                            first_found = True
                        else:
                            item.setCheckState(QtCore.Qt.CheckState.Unchecked)
                            
                self.scenes_model.itemChanged.connect(self.on_checkbox_toggled)
                self.load_thumbnail()

    def update_dataset_filters(self):
        satellite = self.cmbDataset.currentText()
        if not satellite or satellite == "Local File / COG": return
        sat_info = self.layer_service.gee_provider.SATELLITE_MAPPING.get(satellite, {})
        masks = sat_info.get("qa_masks", [])
        
        for cb in self.mask_checkboxes:
            self.grpQuality.layout().removeWidget(cb)
            cb.deleteLater()
        self.mask_checkboxes = []
        
        for mask in masks:
            cb = QCheckBox(f"Apply {mask} Mask")
            cb.setChecked(True)
            self.grpQuality.layout().addWidget(cb)
            
            # Apply custom styling (Warning/Amber)
            from ..utils.helpers import apply_custom_checkbox_style
            apply_custom_checkbox_style(cb, accent_color="#F59E0B", hover_color="#FCD34D")
            
            self.mask_checkboxes.append(cb)

    def update_aoi_controls(self):
        mode = self.cmbAoi.currentData()
        if mode == "DRAW_POLYGON":
            self.stkAoiControls.setCurrentIndex(1)
            self.clear_highlight()
            self.current_aoi_geojson = None
            self.lblAoiSummary.setText("<i>Pending AOI Configuration...</i>")
        elif mode == "VECTOR_FILE":
            self.stkAoiControls.setCurrentIndex(2)
            # Retain geometry if path already exists
            path = self.txtAoiFile.text().strip()
            if path and not self.current_aoi_geojson:
                try:
                    geom, crs = helpers.get_vector_file_geometry(path)
                    self._process_geometry(geom, crs)
                except:
                    self.current_aoi_geojson = None
                    self.lblAoiSummary.setText("<i>Pending AOI Configuration...</i>")
            elif not path:
                self.clear_highlight()
                self.current_aoi_geojson = None
                self.lblAoiSummary.setText("<i>Pending AOI Configuration...</i>")
        else:
            self.stkAoiControls.setCurrentIndex(0)
            self.try_extract_standard_aoi()
            
            # Issue 4: Display warning for rectangular extents
            if mode in ["MAP_EXTENT", "LAYER_BBOX"] and self.current_aoi_geojson:
                self.lblAoiSummary.setText(self.lblAoiSummary.text() + "<br><b style='color:#ea580c;'>Warning: This option exports a rectangular area rather than the polygon boundary.</b>")
            return

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
            summary_html = f"""
            <b>AOI Captured Successfully</b><br>
            <table style="color:#D7E3F4;">
                <tr><td><b>Area (sq degrees):</b></td><td>{metrics['area_sqdeg']:.6f}</td></tr>
                <tr><td><b>Bounding Box:</b></td><td>[{bbox[0]:.2f}, {bbox[1]:.2f}, {bbox[2]:.2f}, {bbox[3]:.2f}]</td></tr>
            </table>
            """
            self.lblAoiSummary.setText(summary_html)
            
        except Exception as e:
            self.current_aoi_geojson = None
            self.clear_highlight()
            self.lblAoiSummary.setText(f"<b style='color:red;'>Validation Failed:</b> {e}")

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
        
        # 1. Preserve exact wizard state before leaving
        self.preserved_page_index = self.stackedWidget.currentIndex()
        
        # 2. Temporarily hide both the wizard and the main plugin window
        if self.parent():
            self.parent()._active_wizard = self # Anti-GC reference
            self.parent().hide()
        self.hide()
        
        # 3. Ensure QGIS map canvas receives focus
        self.iface.mainWindow().activateWindow()
        
        # 4. Activate existing drawing tool
        self.previous_map_tool = self.iface.mapCanvas().mapTool()
        self.map_tool = PolygonMapTool(self.iface.mapCanvas())
        self.map_tool.geometryCaptured.connect(self.on_geometry_captured)
        self.map_tool.drawingCanceled.connect(self.on_drawing_canceled)
        self.iface.mapCanvas().setMapTool(self.map_tool)

    def on_geometry_captured(self, geom):
        try:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage("GEE Wizard: on_geometry_captured executing.", "RemoteSensingStudio", Qgis.Info)
        except:
            pass
        self._restore_from_drawing()
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        self._process_geometry(geom, canvas_crs)

    def on_drawing_canceled(self):
        try:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage("GEE Wizard: on_drawing_canceled executing.", "RemoteSensingStudio", Qgis.Info)
        except:
            pass
        self._restore_from_drawing()
        self.lblAoiSummary.setText("<b style='color:red;'>Drawing canceled.</b>")

    def _restore_from_drawing(self):
        try:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage("GEE Wizard: _restore_from_drawing executing.", "RemoteSensingStudio", Qgis.Info)
        except:
            pass
            
        # 1. Restore previous QGIS map tool
        if self.iface and self.previous_map_tool:
            self.iface.mapCanvas().setMapTool(self.previous_map_tool)
        self.map_tool = None
        
        # 2. Restore main plugin window
        if self.parent():
            self.parent().show()
        
        # 3. Restore exact wizard state
        if hasattr(self, 'preserved_page_index'):
            self.stackedWidget.setCurrentIndex(self.preserved_page_index)
            
        # 4. Restore wizard visibility and focus (without nested exec)
        self.show()
        self.activateWindow()
        self.raise_()
        
        try:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage("GEE Wizard: _restore_from_drawing finished.", "RemoteSensingStudio", Qgis.Info)
        except:
            pass

    def extract_aoi(self, silent=False) -> bool:
        mode = self.cmbAoi.currentData()
        if mode == "VECTOR_FILE":
            path = self.txtAoiFile.text().strip()
            if path and not self.current_aoi_geojson:
                try:
                    geom, crs = helpers.get_vector_file_geometry(path)
                    self._process_geometry(geom, crs)
                except Exception as e:
                    if not silent: QMessageBox.critical(self, "File Error", str(e))
                    return False
            
            if not self.current_aoi_geojson:
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
        except ValueError as ve:
            error_msg = str(ve)
            if "No features selected" in error_msg and mode == "SELECTED_FEATURES":
                if not silent:
                    msg = QMessageBox(self)
                    msg.setIcon(QMessageBox.Icon.Warning)
                    msg.setWindowTitle("AOI Required")
                    msg.setText("The active layer contains multiple polygons.\nPlease select one or more features, or choose another AOI source.")
                    
                    layer = helpers.get_current_layer(self.iface)
                    if layer and layer.featureCount() > 0:
                        btn_select_all = msg.addButton("Select All Features", QMessageBox.ButtonRole.ActionRole)
                        msg.addButton("Continue", QMessageBox.ButtonRole.RejectRole)
                        msg.exec()
                        if msg.clickedButton() == btn_select_all:
                            layer.selectAll()
                            return self.extract_aoi(silent=silent)
                    else:
                        msg.exec()
                else:
                    self.lblAoiSummary.setText("<b style='color:red;'>Please select one or more polygon features in QGIS.</b>")
                return False
            
            if not silent: QMessageBox.critical(self, "AOI Error", f"Failed: {ve}")
            return False
        except Exception as e:
            if not silent: QMessageBox.critical(self, "AOI Error", f"Failed: {e}")
            return False

    def clear_highlight(self):
        if self.highlight_band and self.iface:
            self.iface.mapCanvas().scene().removeItem(self.highlight_band)
            self.highlight_band = None

    def _disconnect_worker_signals(self):
        if hasattr(self, 'worker') and self.worker:
            try:
                self.worker.worker_completed.disconnect(self.on_engine_completed)
            except Exception:
                pass
                
        if hasattr(self, 'analysis_engine') and self.analysis_engine:
            try:
                self.analysis_engine.progress_update.disconnect(self.on_engine_progress)
            except Exception:
                pass
            try:
                self.analysis_engine.export_task_file_requested.disconnect(self.on_export_task_file_requested)
            except Exception:
                pass

    def closeEvent(self, event):
        self._disconnect_worker_signals()
        super().closeEvent(event)

    def reject(self):
        self._disconnect_worker_signals()
        if hasattr(self, 'clear_highlight'):
            self.clear_highlight()
        if hasattr(self, 'map_tool') and self.map_tool and self.iface:
            self.iface.mapCanvas().setMapTool(getattr(self, 'previous_map_tool', None))
        super().reject()

    def accept(self):
        self._disconnect_worker_signals()
        if hasattr(self, 'clear_highlight'):
            self.clear_highlight()
        if hasattr(self, 'map_tool') and self.map_tool and self.iface:
            self.iface.mapCanvas().setMapTool(getattr(self, 'previous_map_tool', None))
        super().accept()

    def on_export_task_file_requested(self, req_dict: Dict[str, Any]):
        """Slot to handle file selection when Earth Engine Export Task finishes."""
        from PyQt6.QtWidgets import QFileDialog
        
        QMessageBox.information(
            self,
            "Export Task Completed",
            "The Earth Engine Export Task has completed successfully on Google's backend.\n\n"
            "Please select the downloaded GeoTIFF file from your local drive to resume the local analysis workflow."
        )
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Exported GeoTIFF",
            "",
            "GeoTIFF Files (*.tif *.tiff);;All Files (*)"
        )
        
        req_dict["path"] = file_path
        # Unblock the background thread
        req_dict["event"].set()

    def on_refresh_clicked(self):
        self.layer_service.clear_search_cache()
        self.fetch_scenes()

    # --- Scene Selection and Execution ---
    
    def fetch_scenes(self):
        if self.connection_service.current_provider() == "Google Earth Engine":
            if not self.connection_service.is_project_ready():
                QMessageBox.warning(self, "Earth Engine Required", "Your Earth Engine Project is not configured or validated. Please go to Settings -> Login and test your connection.")
                return
                
        if not self.extract_aoi(): return
            
        satellite = self.cmbDataset.currentText()
        if self.analysis_type not in ["NDVI", "Scene Selection", "download_scene"]:
            try:
                ir = IndexRegistry.get_instance()
                idx_meta = ir.get_index(self.analysis_type)
                if idx_meta:
                    supported_sats = idx_meta.get("supported_satellites", [])
                    if supported_sats and satellite not in supported_sats:
                        if "Landsat" in "".join(supported_sats) and "Sentinel" not in "".join(supported_sats):
                            msg = "This index requires Thermal Infrared (TIR) bands and is currently supported only by Landsat datasets."
                        else:
                            msg = f"The index '{self.analysis_type}' is not supported on {satellite}. Supported datasets: {', '.join(supported_sats)}."
                        QMessageBox.warning(self, "Incompatible Dataset", msg)
                        return
            except Exception as e:
                self.logger.debug(f"Satellite compatibility check skipped: {e}")

        start = self.dateStart.date().toString("yyyy-MM-dd")
        end = self.dateEnd.date().toString("yyyy-MM-dd")
        
        if not start or not end:
            QMessageBox.warning(self, "Invalid Dates", "Please provide valid Start and End dates.")
            return
            
        if self.dateStart.date() >= self.dateEnd.date():
            QMessageBox.warning(self, "Invalid Date Range", "Start Date must be strictly before End Date. Earth Engine requires a non-empty date range.")
            return
            
        filters = {"max_cloud": float(self.spinCloud.value())}
        sort_by = self.cmbSort.currentText()
        
        self.lblTitle.setText(f"Searching for {satellite} Images...")
        self.btnNext.setEnabled(False)
        self.btnRefresh.setEnabled(False)
        self.cmbDataset.setEnabled(False)
        self.cmbAoi.setEnabled(False)
        
        # Show progress in UI instead of freezing
        self.txtAoiFile.setText("Starting asynchronous search...")
        QtCore.QCoreApplication.processEvents()
        
        from ..utils.workers import SearchWorker
        self.search_worker = SearchWorker(
            self.layer_service, satellite, start, end, 
            self.current_aoi_geojson, filters, sort_by
        )
        self.search_worker.search_completed.connect(self._on_search_completed)
        self.search_worker.start()

    def _on_search_completed(self, results: list, error: str):
        self.btnNext.setEnabled(True)
        self.btnRefresh.setEnabled(True)
        self.cmbDataset.setEnabled(True)
        self.cmbAoi.setEnabled(True)
        
        if error:
            QMessageBox.critical(self, "Search Failed", f"Failed to discover images:\n{error}")
            if self.analysis_type == "download_scene":
                self.lblTitle.setText("Download Scene")
            else:
                self.lblTitle.setText(f"New {self.analysis_type} Calculation")
            return
            
        self.cached_image_list = results
        self.scenes_model.removeRows(0, self.scenes_model.rowCount())
        
        for img in self.cached_image_list:
            item_select = QStandardItem()
            item_select.setCheckable(True)
            item_select.setCheckState(QtCore.Qt.CheckState.Unchecked)
            
            row = [
                item_select,
                QStandardItem(str(img.get("Image ID", ""))),
                QStandardItem(str(img.get("Acquisition Date", "")).split()[0]),
                QStandardItem(f"{img.get('Cloud Percentage', 0)}%"),
                QStandardItem(f"{img.get('Coverage %', 0)}%"),
                QStandardItem(f"{img.get('Coverage km²', 0)}"),
                QStandardItem(f"{img.get('Score', 0)}")
            ]
            self.scenes_model.appendRow(row)
            
        self.lblTitle.setText(f"Select Scene ({len(self.cached_image_list)} Found)")
        self.stackedWidget.setCurrentWidget(self.pageScene)
        self.btnBack.setVisible(True)
        if self.analysis_type == "download_scene":
            self.btnNext.setVisible(False)
            if hasattr(self, 'btnDownloadScene'):
                self.btnDownloadScene.setVisible(True)
        else:
            self.btnNext.setText("Run Analysis")
            self.btnNext.setVisible(True)
            if hasattr(self, 'btnDownloadScene'):
                self.btnDownloadScene.setVisible(False)
        self.btnRefresh.setVisible(False)
        
        if self.cached_image_list:
            if not self.radSingle.isChecked():
                self.select_recommended_only()
        else:
            self.btnNext.setEnabled(False)

    def load_thumbnail(self):
        # Phase 5K.3: Do not execute scene-selection side effects if we are not on the Scene page
        if getattr(self, 'stackedWidget', None) and self.stackedWidget.currentWidget() != self.pageScene:
            return

        image_ids = self.get_selected_image_ids()
        
        # Update selection feedback text
        self.lblTitle.setText(f"Select Scene ({len(image_ids)} Selected)")
        
        if not image_ids:
            self.btnNext.setEnabled(False)
            if hasattr(self, 'btnDownloadScene'):
                self.btnDownloadScene.setEnabled(False)
            self.lblThumbnail.setText("Check a scene to preview")
            self.txtMetadata.clear()
            return
            
        if len(image_ids) > 1:
            self.btnNext.setEnabled(True)
            if hasattr(self, 'btnDownloadScene'):
                self.btnDownloadScene.setEnabled(True)
            self.lblThumbnail.setText("Multiple scenes selected.\nPreview disabled.")
            self.txtMetadata.clear()
            return
            
        self.btnNext.setEnabled(True)
        if hasattr(self, 'btnDownloadScene'):
            self.btnDownloadScene.setEnabled(True)
        satellite = self.cmbDataset.currentText()
        start = self.dateStart.date().toString("yyyy-MM-dd")
        end = self.dateEnd.date().toString("yyyy-MM-dd")
        selection_mode = "Best Image" if self.radSingle.isChecked() else self.cmbComposite.currentText()
        
        if self.analysis_type == "EVI" and self.radSingle.isChecked():
            self.lblThumbnail.setText("EVI Single Scene is temporarily unavailable.\nPlease try again later.")
            self.txtMetadata.setHtml("<span style='color: #F59E0B;'>EVI Single Scene is temporarily unavailable. Please try again later.</span>")
            self.btnNext.setEnabled(False)
            if hasattr(self, 'btnDownloadScene'):
                self.btnDownloadScene.setEnabled(False)
            return
            
        try:
            self.lblThumbnail.setText("Generating clipped preview...\n(This happens in the background)")
            self.btnNext.setEnabled(False)
            if hasattr(self, 'btnDownloadScene'):
                self.btnDownloadScene.setEnabled(False)
            QtCore.QCoreApplication.processEvents()
            
            # Fetch visualization parameters
            palette_data = self.palette_manager.load(self.cmbPreviewPalette.currentText())
            vis_params_override = {
                'min': self.spinPreviewMin.value(),
                'max': self.spinPreviewMax.value(),
                'palette': [stop['color'] for stop in palette_data.get('color_stops', [])]
            }
            
            from ..utils.workers import ThumbnailWorker
            self.thumb_worker = ThumbnailWorker(
                self.layer_service, satellite, start, end, self.current_aoi_geojson, 
                selection_mode, image_ids, self.analysis_type, vis_params_override
            )
            self.thumb_worker.thumbnail_completed.connect(self._on_thumbnail_completed)
            self.thumb_worker.start()
            self.thumb_worker.start()
            
        except Exception as e:
            import traceback
            self.logger.error(f"Preview generation failed: {traceback.format_exc()}")
            self.lblThumbnail.setText(f"Preview Error: Check Logs")
            self.btnNext.setEnabled(True)
            if hasattr(self, 'btnDownloadScene'):
                self.btnDownloadScene.setEnabled(True)
            
    def _on_thumbnail_completed(self, data: dict, error: str):
        self.btnNext.setEnabled(True)
        if hasattr(self, 'btnDownloadScene'):
            self.btnDownloadScene.setEnabled(True)
        if error:
            self.lblThumbnail.setText(f"Failed to load preview: {error}")
            return
            
        url = data.get("Preview URL")
        if url and url != "local":
            try:
                import urllib.request
                img_data = urllib.request.urlopen(url).read()
                image = QImage()
                image.loadFromData(img_data)
                self.lblThumbnail.setPixmap(QPixmap(image).scaled(
                    self.lblThumbnail.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation
                ))
            except Exception as e:
                self.lblThumbnail.setText(f"Error downloading thumbnail bytes: {e}")
        else:
            self.lblThumbnail.setText("No Preview Available")
            
        self.format_metadata_panel(data)

    def format_metadata_panel(self, data: Dict[str, Any]):
        resolutions = data.get("Resolutions", {})
        bands = data.get("Available Bands", [])
        metrics = data.get("Metrics", {})
        
        bands_html = ""
        for res, res_bands in resolutions.items():
            avail = [b for b in res_bands if b in bands]
            if avail: bands_html += f"<b>{res}:</b> {', '.join(avail)}<br>"
                
        if not bands_html: bands_html = ", ".join(bands) if bands else "N/A"
        masks = ", ".join(data.get("QA Masks", [])) or "None"
        
        # Add coverage warning if necessary
        coverage = data.get("Metrics", {}).get("Images Used", 1) # Simplified for now, real metric in stats
        
        html = f"""
        <h3 style="color:#FFFFFF;">Metadata</h3><hr>
        <b>[ General ]</b><br>
        • Satellite: {data.get('Satellite')}<br>
        • Date: {data.get('Acquisition Date')}<br>
        • Score Formula: 0.5 × Coverage% + 0.5 × (100 - Cloud%)<br><br>
        <b>[ Quality & Processing ]</b><br>
        • Processing Level: {data.get('Processing Level')}<br>
        • Cloud Cover: {data.get('Cloud Percentage')}%<br>
        • Available QA Masks: {masks}<br><br>
        <b>[ Compositing Metrics ]</b><br>
        • Mode: {metrics.get('Method', 'Single')}<br>
        • Scenes Found: {metrics.get('Images Found', 0)}<br>
        • Scenes Used: {metrics.get('Images Used', 0)}<br><br>
        <b>[ Available Bands ]</b><br>
        {bands_html}
        """
        self.txtMetadata.setHtml(html)

    def run_analysis(self):
        """Execute the real pipeline via AnalysisEngine in a thread."""
        if self.connection_service.current_provider() == "Google Earth Engine":
            if not self.connection_service.is_project_ready():
                QMessageBox.warning(self, "Earth Engine Required", "Your Earth Engine Project is not configured or validated. Please go to Settings -> Login and test your connection.")
                return

        
        if self.analysis_type == "EVI" and self.radSingle.isChecked():
            QMessageBox.information(self, "Temporarily Unavailable", "EVI Single Scene is temporarily unavailable. Please try again later.")
            return

        selection_mode = "Best Image" if self.radSingle.isChecked() else self.cmbComposite.currentText()
        
        image_ids = self.get_selected_image_ids()
        
        # UI Selection Validation (Phase 5K.2)
        if self.radSingle.isChecked():
            if len(image_ids) != 1:
                QMessageBox.warning(self, "Selection Required", "Single Scene mode requires exactly one selected scene.")
                return
        else: # Multi / Image Collection
            if len(image_ids) < 2:
                QMessageBox.warning(self, "Selection Required", "Image Collection mode requires at least 2 selected scenes.")
                return
        
        if not image_ids: 
            return
        
        self.stackedWidget.setCurrentWidget(self.pageProgress)
        self.lblTitle.setText("Executing Analysis Workflow")
        self.btnBack.setVisible(False)
        self.btnNext.setVisible(False)
        # Clear summary and start progress
        self.txtSummary.clear()
        
        profiler = PerformanceProfiler.get_instance()
        profiler.start_workflow()
        self.lblStatus.setText("<span style='color: green; font-weight: bold;'>✓ Preparing AOI</span>")
        profiler.step("Preparing AOI")
        self.progressBar.setValue(0)
        
        if hasattr(self, 'cmbResMode'):
            export_mode = self.cmbResMode.currentText().split(' (')[0] # E.g., 'Dataset Default' or 'Automatic'
            export_res = self.spinCustomRes.value()
        else:
            export_mode = "Dataset Default"
            export_res = 0.0
            
        # Get palette settings
        palette_data = self.palette_manager.load(self.cmbPreviewPalette.currentText()) if hasattr(self, 'cmbPreviewPalette') else None
            
        params = {
            "analysis_type": self.analysis_type,
            "provider_name": "Google Earth Engine",
            "satellite": self.cmbDataset.currentText(),
            "start_date": self.dateStart.date().toString("yyyy-MM-dd"),
            "end_date": self.dateEnd.date().toString("yyyy-MM-dd"),
            "aoi_geojson": self.current_aoi_geojson,
            "selection_mode": selection_mode,
            "image_ids": image_ids,
            "cloud_filter": float(self.spinCloud.value()),
            "index_threshold": self.spinThreshold.value(),
            "palette": palette_data,
            "stretch_mode": self.cmbStretchMode.currentText() if hasattr(self, 'cmbStretchMode') else "Original",
            "vis_min": self.spinPreviewMin.value() if hasattr(self, 'spinPreviewMin') else -1.0,
            "vis_max": self.spinPreviewMax.value() if hasattr(self, 'spinPreviewMax') else 1.0,
            "export_resolution_mode": export_mode,
            "export_resolution": export_res
        }
        if self.analysis_type not in ["NDVI", "Scene Selection"]:
            try:
                ir = IndexRegistry.get_instance()
                sr = SatelliteRegistry.get_instance()
                context = AnalysisContext(
                    index_definition=ir.get_index(self.analysis_type),
                    satellite_definition=sr.get_satellite(self.cmbDataset.currentText()),
                    workspace_definition={},
                    aoi=self.current_aoi_geojson,
                    date_range={"start": params["start_date"], "end": params["end_date"]},
                    dataset=params["satellite"],
                    parameters=params,
                    export_settings={"resolution": params["export_resolution"]}
                )
                params["context"] = context
            except Exception as e:
                self.logger.error(f"Failed to build AnalysisContext: {e}")
                
        self.worker = AnalysisWorker(self.analysis_engine, params)
        self.worker.worker_failed.connect(self.on_worker_failed)
        self.worker.worker_completed.connect(self.on_engine_completed)
        self.worker.start()

    def on_download_scene_clicked(self):
        if self.connection_service.current_provider() == "Google Earth Engine":
            if not self.connection_service.is_project_ready():
                QMessageBox.warning(self, "Earth Engine Required", "Your Earth Engine Project is not configured or validated. Please go to Settings -> Login and test your connection.")
                return
                
        from PyQt6.QtWidgets import QFileDialog
        
        selection_mode = "Best Image" if self.radSingle.isChecked() else self.cmbComposite.currentText()
        image_ids = self.get_selected_image_ids()
        
        if self.radSingle.isChecked():
            if len(image_ids) != 1:
                QMessageBox.warning(self, "Selection Required", "Single Scene mode requires exactly one selected scene.")
                return
        else:
            if len(image_ids) < 2:
                QMessageBox.warning(self, "Selection Required", "Image Collection mode requires at least 2 selected scenes.")
                return
                
        if not image_ids: 
            return

        satellite = self.cmbDataset.currentText()
        if self.radGoogleDrive.isChecked():
            self.start_drive_export(satellite, selection_mode, image_ids)
            return
            
        date_str = self.dateStart.date().toString("yyyy-MM-dd")
        
        actual_date_str = date_str
        if self.radSingle.isChecked() and image_ids:
            for row in range(self.scenes_model.rowCount()):
                if self.scenes_model.item(row, 0).checkState() == QtCore.Qt.CheckState.Checked:
                    actual_date_str = self.scenes_model.item(row, 2).text()
                    break

        if self.radSingle.isChecked():
            default_name = f"{satellite.replace('-', '')}_SingleScene_{actual_date_str}_AOI.tif"
        else:
            end_str = self.dateEnd.date().toString("yyyy-MM-dd")
            default_name = f"{satellite.replace('-', '')}_{selection_mode.replace(' ', '')}_{date_str}_to_{end_str}_AOI.tif"
            
        import os
        from pathlib import Path
        default_path = os.path.join(str(Path.home()), "Downloads", default_name)
        
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Scene As", default_path, "GeoTIFF (*.tif *.tiff)")
        if not file_path:
            return
            
        self.stackedWidget.setCurrentWidget(self.pageProgress)
        self.lblTitle.setText("Downloading Scene")
        self.btnBack.setVisible(False)
        self.btnNext.setVisible(False)
        if hasattr(self, 'btnDownloadScene'):
            self.btnDownloadScene.setVisible(False)
        self.txtSummary.clear()
        
        self.lblStatus.setText("<span style='color: green; font-weight: bold;'>✓ Starting Download</span>")
        self.progressBar.setValue(0)
        
        from ..utils.workers import SceneExportTask
        from qgis.core import QgsApplication
        
        self.export_task = SceneExportTask(
            gee_provider=self.layer_service.gee_provider,
            satellite=satellite,
            start_date=self.dateStart.date().toString("yyyy-MM-dd"),
            end_date=self.dateEnd.date().toString("yyyy-MM-dd"),
            aoi_geojson=self.current_aoi_geojson,
            selection_mode=selection_mode,
            image_ids=image_ids,
            cloud_filter=float(self.spinCloud.value()),
            export_path=file_path
        )
        
        # Connect task signals safely
        self.export_task.progress_update.connect(self.on_engine_progress)
        self.export_task.task_completed.connect(self.on_download_scene_completed)
        self.export_task.task_failed.connect(lambda msg: self.on_download_scene_completed(False, msg))
        
        # Keep wizard open and responsive
        self.btnDownloadScene.setVisible(True)
        self.btnDownloadScene.setText("Cancel Export")
        
        # Disconnect old clicked signal and connect to cancel
        try: self.btnDownloadScene.clicked.disconnect()
        except Exception: pass
        self.btnDownloadScene.clicked.connect(self.cancel_download_task)
        
        QgsApplication.taskManager().addTask(self.export_task)
        self.txtSummary.setHtml("<span style='color: #27D8F7;'>Export task dispatched to QGIS Background Tasks. You may close this wizard and continue working in QGIS.</span>")

    def cancel_download_task(self):
        if hasattr(self, 'export_task') and self.export_task:
            self.export_task.cancel()
            self.lblStatus.setText("Export Cancelled")
            
        self.btnDownloadScene.setText("Download Scene")
        try: self.btnDownloadScene.clicked.disconnect()
        except Exception: pass
        self.btnDownloadScene.clicked.connect(self.on_download_scene_clicked)
        
    def start_drive_export(self, satellite, selection_mode, image_ids):
        
        self.lblTitle.setText("Initializing Google Drive Export")
        self.stackedWidget.setCurrentWidget(self.pageProgress)
        self.btnBack.setVisible(False)
        self.btnNext.setVisible(False)
        if hasattr(self, 'btnDownloadScene'):
            self.btnDownloadScene.setVisible(False)
        self.lblStatus.setText("Authenticating with Google Drive...")
        QtCore.QCoreApplication.processEvents()
        
        try:
            # Check auth status without breaking the wizard state
            status = self.layer_service.gee_provider.get_status()
            # Start drive export (gee_provider will handle EE logic)
            bounds = (0,0,0,0) # Bounding box extraction handled inside
            
            from ..utils.workers import DriveExportWorker
            self.drive_worker = DriveExportWorker(
                self.layer_service.gee_provider, satellite, self.dateStart.date().toString("yyyy-MM-dd"), 
                self.dateEnd.date().toString("yyyy-MM-dd"), self.current_aoi_geojson, selection_mode, image_ids, float(self.spinCloud.value())
            )
            self.drive_worker.progress_update.connect(self.on_engine_progress)
            self.drive_worker.export_completed.connect(self.on_download_scene_completed)
            self.drive_worker.start()
        except Exception as e:
            self.on_download_scene_completed(False, str(e))
        
    def _add_export_buttons(self):
        if not hasattr(self, 'btnOpenDrive'):
            from PyQt6.QtWidgets import QPushButton, QHBoxLayout, QWidget
            from PyQt6.QtGui import QDesktopServices
            from PyQt6.QtCore import QUrl
            
            btn_layout = QHBoxLayout()
            self.btnOpenDrive = QPushButton("Open Google Drive")
            self.btnOpenEETasks = QPushButton("Open Earth Engine Tasks")
            
            self.btnOpenDrive.setStyleSheet("padding: 8px; font-weight: bold; background-color: #0F9D58; color: white; border-radius: 4px;")
            self.btnOpenEETasks.setStyleSheet("padding: 8px; font-weight: bold; background-color: #4285F4; color: white; border-radius: 4px;")
            
            btn_layout.addWidget(self.btnOpenDrive)
            btn_layout.addWidget(self.btnOpenEETasks)
            
            container = QWidget()
            container.setLayout(btn_layout)
            self.export_btns_container = container
            self.pageSummary.layout().addWidget(container)
            
            self.btnOpenDrive.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://drive.google.com/drive/my-drive")))
            self.btnOpenEETasks.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://code.earthengine.google.com/tasks")))
            
        self.export_btns_container.setVisible(True)

    def on_download_scene_completed(self, success: bool, message: str, task_id: str = "", task_name: str = ""):
        self.stackedWidget.setCurrentWidget(self.pageSummary)
        self.btnFinish.setVisible(True)
        
        is_drive_export = getattr(self, 'radGoogleDrive', None) and self.radGoogleDrive.isChecked()
        
        if success and is_drive_export and task_id:
            if hasattr(self, 'main_dialog_ref') and hasattr(self.main_dialog_ref, 'register_ee_task_signal'):
                self.main_dialog_ref.register_ee_task_signal.emit(task_id, task_name)
        
        if hasattr(self, 'export_btns_container'):
            self.export_btns_container.setVisible(False)
            
        if success:
            if is_drive_export:
                self.lblTitle.setText("Export Task Submitted")
                self.lblSummaryTitle.setText("Export Task Submitted")
                self.lblSummaryTitle.setStyleSheet("font-size: 18pt; font-weight: bold; color: #10B981;")
                self.txtSummary.setHtml(f"<span style='color: #D7E3F4;'>Export task successfully submitted to Google Earth Engine.</span><br><br><b style='color: #FFFFFF;'>Task details:</b><br>{message}<br><br><span style='color: #9CA3AF;'>The file will appear in Google Drive after Earth Engine finishes processing it.</span>")
                self._add_export_buttons()
            else:
                self.lblTitle.setText("Download Successful")
                self.lblSummaryTitle.setText("Download Successful")
                self.lblSummaryTitle.setStyleSheet("font-size: 18pt; font-weight: bold; color: #10B981;")
                self.txtSummary.setHtml(f"<span style='color: #D7E3F4;'>Scene successfully downloaded to:</span><br><br><b style='color: #FFFFFF;'>{message}</b>")
        else:
            if is_drive_export:
                self.lblTitle.setText("Export Failed")
                self.lblSummaryTitle.setText("Export Failed")
            else:
                self.lblTitle.setText("Download Failed")
                self.lblSummaryTitle.setText("Download Failed")
                
            self.lblSummaryTitle.setStyleSheet("font-size: 18pt; font-weight: bold; color: #DC2626;")
            self.txtSummary.setHtml(f"<b style='color:red;'>{message}</b>")

    def on_worker_failed(self, error_msg: str):
        self.lblProgress.setText(f"<b style='color:#EF4444;'>Error:</b> {error_msg}")
        self.stackedWidget.setCurrentWidget(self.pageConfig)
        self.logger.error(f"Worker failed: {error_msg}")
        QMessageBox.critical(self, "Analysis Failed", f"A critical error occurred in the background thread:\n\n{error_msg}")

    def on_engine_progress(self, message: str, percent: int):
        # Allow HTML styling for checkmarks
        if message.startswith("✓"):
            self.lblStatus.setText(f"<span style='color: green; font-weight: bold;'>{message}</span>")
        else:
            self.lblStatus.setText(message)
        self.progressBar.setValue(percent)

    def on_engine_completed(self, result: AnalysisResult):
        try:
            # Native PyQt fallback: accessing a deleted QWidget raises RuntimeError
            _ = self.isVisible()
            _ = self.lblTitle.isVisible()
        except RuntimeError:
            return

        if result.errors:
            if result.errors[0].startswith("COVERAGE_BLOCK:"):
                cov_str = result.errors[0].split(":")[1]
                try:
                    cov_val = float(cov_str)
                except ValueError:
                    cov_val = 0.0
                
                self.btnFinish.setVisible(True)
                self.stackedWidget.setCurrentWidget(self.pageSummary)
                self.lblTitle.setText("Analysis Blocked")
                self.lblSummaryTitle.setText("Single Scene does not fully cover the selected AOI.")
                self.lblSummaryTitle.setStyleSheet("font-size: 14pt; font-weight: bold; color: #F59E0B;")
                
                html = f"""
                <table style="width:100%; border-collapse: collapse;">
                    <tr><td style="padding: 5px;"><b style="color: #D7E3F4;">AOI Coverage:</b></td><td style="color: #F59E0B; font-weight: bold;">{cov_val:.2f}%</td></tr>
                    <tr><td style="padding: 5px; background: #1E3A5F;"><b style="color: #D7E3F4;">Required Coverage:</b></td><td style="background: #1E3A5F; color: #FFFFFF;">100%</td></tr>
                    <tr><td style="padding: 5px;"><b style="color: #D7E3F4;">Selection Mode:</b></td><td style="color: #FFFFFF;">Single Scene</td></tr>
                </table>
                <br>
                <div style="background: #4B1113; border-left: 4px solid #EF4444; padding: 10px; border-radius: 4px;">
                    <span style="color: #FCA5A5; font-weight: bold;">WARNING — Single Scene Coverage Insufficient<br><br>The selected Sentinel-2 scene does not cover the complete study area.<br><br>Single Scene analysis requires 100% AOI coverage. Please switch to <b>Multi/Mosaic</b> mode to analyze the complete AOI.</span>
                </div>
                """
                self.txtSummary.setHtml(html)
                return
            
            self.stackedWidget.setCurrentWidget(self.pageSummary)
            self.lblTitle.setText("Analysis Failed")
            self.lblSummaryTitle.setText("Analysis Failed")
            self.lblSummaryTitle.setStyleSheet("font-size: 18pt; font-weight: bold; color: #DC2626;")
            self.txtSummary.setHtml(f"<b style='color:red;'>{result.errors[0]}</b>")
            self.btnFinish.setVisible(True)
            return
            
        self.lblStatus.setText("<span style='color: green; font-weight: bold;'>✓ Analysis Complete. Starting Download...</span>")
        self.progressBar.setValue(100)
        
        vis_service = VisualizationService.get_instance()
        try:
            vis_service.visualization_completed.disconnect(self.on_visualization_completed)
            vis_service.progress_update.disconnect(self.on_engine_progress)
        except TypeError:
            pass
            
        vis_service.visualization_completed.connect(self.on_visualization_completed)
        vis_service.progress_update.connect(self.on_engine_progress)
        vis_service.visualize_result_async(result)
        
        # We will also pass the original AnalysisResult into the final step
        self.final_result = result
        
    def on_visualization_completed(self, vis_result: VisualizationResult):
        self.stackedWidget.setCurrentWidget(self.pageSummary)
        self.lblTitle.setText("Analysis Finished")
        self.final_vis_result = vis_result
        
        if not vis_result.success:
            self.lblSummaryTitle.setText("Visualization Failed")
            self.lblSummaryTitle.setStyleSheet("font-size: 18pt; font-weight: bold; color: #DC2626;")
            self.txtSummary.setHtml(f"<b style='color:red;'>{vis_result.error_message}</b>")
            self.btnFinish.setVisible(True)
            return
        stats = vis_result.statistics or (self.final_result.statistics if self.final_result else {})
        validation_failed = stats.get("validation_failed", False)
        
        if validation_failed:
            self.lblTitle.setText("Analysis Completed with Scientific Warning")
            self.lblSummaryTitle.setText("Scientific Validation: FAIL")
            self.lblSummaryTitle.setStyleSheet("font-size: 18pt; font-weight: bold; color: #F59E0B;")
            
            reason = stats.get("validation_reason", "Final raster contains invalid/out-of-range pixels.")
            
            html = f"""
            <table style="width:100%; border-collapse: collapse;">
                <tr><td style="padding: 5px;"><b style="color: #D7E3F4;">Process Status:</b></td><td style="color: #10B981; font-weight: bold;">Success</td></tr>
                <tr><td style="padding: 5px;"><b style="color: #D7E3F4;">Scientific Validation:</b></td><td style="color: #F59E0B; font-weight: bold;">FAIL</td></tr>
            </table>
            <br>
            <div style="background: #4B1113; border-left: 4px solid #EF4444; padding: 10px; border-radius: 4px;">
                <span style="color: #FCA5A5; font-weight: bold;">Reason:<br>{reason}</span>
            </div>
            """
            self.txtSummary.setHtml(html)
            self.btnFinish.setVisible(True)
            return
            
        self.lblTitle.setText("Analysis Successful")
        self.lblSummaryTitle.setText("Analysis Successful")
        self.lblSummaryTitle.setStyleSheet("font-size: 18pt; font-weight: bold; color: #10B981;")
        self.btnFinish.setVisible(True)
        
        # Since stats are generated asynchronously now, we extract them from the VisualizationResult 
        # which computed them locally using Rasterio, bypassing Earth Engine entirely.
        stats = vis_result.statistics or self.final_result.statistics
        
        def get_stat(key_upper, key_lower):
            if key_upper in stats: return stats[key_upper]
            if key_lower in stats: return stats[key_lower]
            return 'N/A'
            
        stats_html = f"""
        <b style="color: #D7E3F4;">Min:</b> <span style="color: #FFFFFF;">{get_stat('Min', 'min')}</span><br>
        <b style="color: #D7E3F4;">Max:</b> <span style="color: #FFFFFF;">{get_stat('Max', 'max')}</span><br>
        <b style="color: #D7E3F4;">Mean:</b> <span style="color: #FFFFFF;">{get_stat('Mean', 'mean')}</span><br>
        <b style="color: #D7E3F4;">Median:</b> <span style="color: #FFFFFF;">{get_stat('Median', 'median')}</span><br>
        <b style="color: #D7E3F4;">StdDev:</b> <span style="color: #FFFFFF;">{get_stat('StdDev', 'std')}</span>
        """
        
        warnings_html = ""
        if hasattr(self.final_result, 'warnings') and self.final_result.warnings:
            for w in self.final_result.warnings:
                # Replace newlines with <br> for HTML rendering
                w_br = w.replace('\n', '<br>')
                warnings_html += f"""
                <div style="background: #4B1113; border-left: 4px solid #EF4444; padding: 10px; margin-top: 10px; border-radius: 4px;">
                    <span style="color: #FCA5A5; font-weight: bold;">{w_br}</span>
                </div>
                """

        cov_val = getattr(self.final_result, 'coverage_percent', 100.0)
        cov_status = "FULL" if cov_val >= 99.9 else "PARTIAL"
        cov_color = "#10B981" if cov_status == "FULL" else "#F59E0B"

        html = f"""
        <table style="width:100%; border-collapse: collapse;">
            <tr><td style="padding: 5px;"><b style="color: #D7E3F4;">Analysis Name:</b></td><td style="color: #FFFFFF;">{self.final_result.formula_name}</td></tr>
            <tr><td style="padding: 5px; background: #1E3A5F;"><b style="color: #D7E3F4;">Dataset:</b></td><td style="background: #1E3A5F; color: #FFFFFF;">{self.final_result.dataset}</td></tr>
            <tr><td style="padding: 5px;"><b style="color: #D7E3F4;">Scenes Used:</b></td><td style="color: #FFFFFF;">{self.final_result.number_of_scenes}</td></tr>
            <tr><td style="padding: 5px; background: #1E3A5F;"><b style="color: #D7E3F4;">Execution Time:</b></td><td style="background: #1E3A5F; color: #FFFFFF;">{self.final_result.execution_time_sec} s</td></tr>
            <tr><td style="padding: 5px;"><b style="color: #D7E3F4;">Provider:</b></td><td style="color: #FFFFFF;">{self.final_result.provider}</td></tr>
            <tr><td style="padding: 5px; background: #1E3A5F;"><b style="color: #D7E3F4;">Output Type:</b></td><td style="background: #1E3A5F; color: #FFFFFF;">{self.final_result.output_type}</td></tr>
            <tr><td style="padding: 5px;"><b style="color: #D7E3F4;">Export Strategy:</b></td><td style="color: #FFFFFF;">{self.final_result.export_strategy} ({self.final_result.quality_metrics.get('Estimated MB', 'Unknown')} MB)</td></tr>
            <tr><td style="padding: 5px; background: #1E3A5F;"><b style="color: #D7E3F4;">Result Layer:</b></td><td style="background: #1E3A5F; color: #FFFFFF;">{self.final_result.output_layer_name}</td></tr>
            <tr><td style="padding: 5px;"><b style="color: #D7E3F4;">AOI Coverage:</b></td><td style="color: {cov_color}; font-weight: bold;">{cov_val}% ({cov_status})</td></tr>
            <tr><td style="padding: 5px; background: #1E3A5F;"><b style="color: #D7E3F4;">Status:</b></td><td style="background: #1E3A5F; color: #10B981; font-weight: bold;">Success</td></tr>
        </table>
        {warnings_html}
        <br>
        <h3 style="color: #FFFFFF;">Computed Statistics</h3>
        <div style="background: #12243B; padding: 10px; border-radius: 4px; border: 1px solid rgba(255, 255, 255, 0.1);">
            {stats_html}
        </div>
        """
        
        self.txtSummary.setHtml(html)

    def on_finish_clicked(self):
        if hasattr(self, 'final_result') and hasattr(self, 'final_vis_result'):
            self.analysis_workflow_finished.emit(self.final_result, self.final_vis_result)
            
        self.accept()

    def on_next(self):
        current = self.stackedWidget.currentWidget()
        if current == self.pageConfig:
            self.fetch_scenes()
        elif current == self.pageScene:
            self.run_analysis()

    def on_back(self):
        self.stackedWidget.setCurrentWidget(self.pageConfig)
        if self.analysis_type == "download_scene":
            self.lblTitle.setText("Download Scene")
        else:
            self.lblTitle.setText(f"New {self.analysis_type} Calculation")
        self.btnBack.setVisible(False)
        self.btnRefresh.setVisible(True)
        self.btnNext.setText("Search Images")
        self.btnNext.setEnabled(True)
        self.btnNext.setVisible(True)
