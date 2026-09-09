"""
Main Dialog Controller Module.
"""
import os
from typing import Any, Optional, Dict, List, Union, Callable, Tuple
from PyQt6.QtWidgets import QDialog, QComboBox, QLabel, QVBoxLayout, QGroupBox
from PyQt6 import uic
try:
    from qgis.core import QgsProject, QgsVectorLayer, QgsWkbTypes, Qgis
    from qgis.PyQt.QtCore import Qt
except ImportError:
    from PyQt6.QtCore import Qt

from ..utils.logger import get_logger
from ..services.connection_service import ConnectionService
from .login_dialog import LoginDialog, LogoutWorker
from .analysis_wizard import AnalysisWizardDialog
from ..models.analysis_result import AnalysisResult
from ..models.visualization_result import VisualizationResult
from ..services.analysis_engine import AnalysisEngine
from ..analysis.index_registry import IndexRegistry
from .theme_manager import ThemeManager

UI_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "main_dialog.ui")

class MainDialog(QDialog):
    """
    Controller class for the Main Dialog of the plugin.
    """
    from PyQt6.QtCore import pyqtSignal
    register_ee_task_signal = pyqtSignal(str, str)

    
    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.logger = get_logger(__name__)
        self.connection_service = ConnectionService.get_instance()
        
        try:
            try:
                from ..utils.timing_profiler import TimingProfiler
                TimingProfiler.get_instance().record("T4", "uic.loadUi starts")
            except Exception:
                pass
            uic.loadUi(UI_PATH, self)
            try:
                from ..utils.timing_profiler import TimingProfiler
                TimingProfiler.get_instance().record("T4_end", "uic.loadUi ends")
            except Exception:
                pass
            
            # Restore standard window flags to ensure minimize/maximize buttons, 
            # and allow dragging via native title bar like a standard desktop app.
            if hasattr(Qt, 'WindowType'):
                self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowMaximizeButtonHint | Qt.WindowType.WindowCloseButtonHint)
            else:
                self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
                
            self.logger.info("MainDialog loaded.")
            
            # Global plugin-wide QScrollBar handle styling
            from ..utils.helpers import apply_scrollbar_style
            apply_scrollbar_style(self)
            
            if hasattr(self, 'tabWidget'):
                self.tabWidget.currentChanged.connect(self.on_tab_changed)
                
            # Ensure the dashboard grid layout distributes vertical space properly
            if hasattr(self, 'tabDashboard'):
                layout = self.tabDashboard.layout()
                if layout:
                    layout.setRowStretch(0, 0) # Analysis Status prefers its own height
                    layout.setRowStretch(1, 1) # Quick Start and Scenes Processed can expand
                
            if hasattr(self, 'lblUserAvatar'):
                self.lblUserAvatar.mousePressEvent = self.on_avatar_clicked
                
            if hasattr(self, 'btnSettingsSignInOut'):
                self.btnSettingsSignInOut.clicked.connect(self.on_settings_sign_in_out_clicked)
                
            if hasattr(self, 'btnSettingsSwitchAccount'):
                self.btnSettingsSwitchAccount.clicked.connect(self.on_settings_switch_account_clicked)
                
            if hasattr(self, 'btnSettingsManageAccess'):
                self.btnSettingsManageAccess.clicked.connect(self.on_settings_manage_access_clicked)
                
            if hasattr(self, 'btnExportPDF'):
                self.btnExportPDF.clicked.connect(self.export_report_pdf)
                
            if hasattr(self, 'btnHelpWebDemo'):
                self.btnHelpWebDemo.clicked.connect(self.on_help_web_demo)
                
            if hasattr(self, 'btnHelpContactSupport'):
                self.btnHelpContactSupport.clicked.connect(self.on_help_contact_support)
                
            # Update Version Info
            version = "Unknown"
            try:
                import os
                metadata_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "metadata.txt")
                with open(metadata_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("version="):
                            version = line.strip().split("=")[1]
                            break
            except Exception:
                pass
            if hasattr(self, 'lblProjectInfo'):
                self.lblProjectInfo.setText(f'<b>PROJECT INFORMATION</b><br/>Developer: Yasser Galal<br/>Version: {version}')
                
            if hasattr(self, 'lblAppIcon'):
                self.load_illustration("logo.webp", self.lblAppIcon, target_height=60)
                
            # Initial workspace load
            from ..analysis.workspace_manager import WorkspaceManager
            self.workspace_manager = WorkspaceManager.get_instance()
            self.theme_manager = ThemeManager.get_instance()
            
            # Dynamically build sidebar navigation
            self.sidebar_buttons = {}
            if hasattr(self, 'btnWsCustom'):
                layout = self.btnWsCustom.parentWidget().layout()
                if layout:
                    from PyQt6.QtWidgets import QPushButton
                    workspaces = self.workspace_manager.get_all_workspaces()
                    
                    for ws in workspaces:
                        ws_id = ws["id"]
                        btn = QPushButton(f"  {ws.get('display_name', ws_id)}")
                        btn.setProperty("cssClass", "sidebar")
                        btn.clicked.connect(lambda checked=False, w_id=ws_id: self.load_workspace(w_id))
                        
                        # Find index of btnWsCustom to insert before it
                        insert_index = layout.count() - 1
                        for i in range(layout.count()):
                            if layout.itemAt(i).widget() == self.btnWsCustom:
                                insert_index = i
                                break
                                
                        layout.insertWidget(insert_index, btn)
                        self.sidebar_buttons[ws_id] = btn
            
            # Initialize _current_workspace_id
            self._current_workspace_id = None


                
            self.refresh_header()
            
            self.setup_aoi_selector()
            self.connect_signals()
            self.populate_layers()
            
            # FIX 2: Defer heavy module discovery (AnalysisEngine) until after UI paints
            from PyQt6.QtCore import QTimer
            self.analysis_engine = None
            QTimer.singleShot(100, self._deferred_heavy_init)
            
            self.setup_visualization_workspace()
            
            self.update_project_info()
            
            self.check_initial_gee_status()
            
            self.setup_source_switch()
            self.setup_custom_menu()
            
            # Setup EE Background Monitor
            from PyQt6.QtCore import QThread
            from ..utils.workers import EETaskMonitorWorker
            self.ee_monitor_thread = QThread()
            self.ee_monitor_worker = EETaskMonitorWorker()
            self.ee_monitor_worker.moveToThread(self.ee_monitor_thread)
            
            # Use Qt signal-slot mechanism for lifecycle to avoid deadlock
            self.ee_monitor_thread.started.connect(self.ee_monitor_worker.start_monitoring)
            self.ee_monitor_worker.finished.connect(self.ee_monitor_thread.quit)
            
            # Connect the main dialog's registration signal to the worker
            self.register_ee_task_signal.connect(self.ee_monitor_worker.register_task)
            
            # Connect worker's status updates back to main dialog
            self.ee_monitor_worker.task_status_changed.connect(self.on_ee_task_status_changed)
            
            self.ee_monitor_thread.start()
            
            # Apply the initial provider state which sets the UI and loads the workspace
            self.apply_provider_state()
            
            try:
                from ..utils.timing_profiler import TimingProfiler
                TimingProfiler.get_instance().record("T6", "__init__ ends")
            except Exception:
                pass
                
        except Exception as e:
            self.logger.error(f"Error initializing MainDialog: {e}", exc_info=True)
            
    def _deferred_heavy_init(self):
        """Safely perform heavy initialization after the UI is visible."""
        try:
            try:
                from ..utils.timing_profiler import TimingProfiler
                TimingProfiler.get_instance().record("T8", "_deferred_heavy_init begins")
            except Exception:
                pass
                
            from ..services.analysis_engine import AnalysisEngine
            try:
                from ..utils.timing_profiler import TimingProfiler
                TimingProfiler.get_instance().record("T5", "AnalysisEngine.get_instance starts")
            except Exception:
                pass
            self.analysis_engine = AnalysisEngine.get_instance()
            try:
                from ..utils.timing_profiler import TimingProfiler
                TimingProfiler.get_instance().record("T5_end", "AnalysisEngine.get_instance ends")
            except Exception:
                pass
            self.logger.info("Deferred heavy initialization completed.")
            
            # Start background EE initialization if using GEE
            if self.connection_service.current_provider() == "Google Earth Engine":
                if not getattr(self, '_ee_initialization_started', False):
                    self._ee_initialization_started = True
                    from PyQt6.QtCore import QThread
                    from ..utils.workers import EEConnectionWorker
                    
                    self.ee_connection_worker = EEConnectionWorker(self.connection_service)
                    self.ee_connection_thread = QThread()
                    self.ee_connection_worker.moveToThread(self.ee_connection_thread)
                    
                    self.ee_connection_thread.started.connect(self.ee_connection_worker.start_check)
                    self.ee_connection_worker.finished.connect(self.ee_connection_thread.quit)
                    # Safely refresh UI on the main thread when finished
                    self.ee_connection_worker.finished.connect(self.refresh_header)
                    
                    self.ee_connection_thread.start()
                    
        except Exception as e:
            self.logger.error(f"Error in deferred init: {e}", exc_info=True)

    def stop_workers(self):
        if hasattr(self, 'ee_monitor_worker'):
            from PyQt6.QtCore import QMetaObject, Qt
            # Asynchronously request the worker to stop. It will emit finished() -> thread.quit()
            QMetaObject.invokeMethod(self.ee_monitor_worker, "stop", Qt.ConnectionType.QueuedConnection)
            # FIX 3: Do NOT call self.ee_monitor_thread.wait(3000) here as it synchronously blocks QGIS shutdown.
            
        if hasattr(self, 'ee_connection_thread') and self.ee_connection_thread.isRunning():
            self.ee_connection_thread.quit()

    def on_ee_task_status_changed(self, task_id: str, task_name: str, state: str, error_msg: str):
        from qgis.core import Qgis
        if state == "COMPLETED":
            from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
            from PyQt6.QtCore import Qt
            from PyQt6.QtGui import QFontMetrics
            
            widget = QWidget()
            widget.setStyleSheet("""
                QWidget {
                    background-color: #12243B;
                    border: 1px solid #10B981;
                    border-radius: 4px;
                }
                QLabel {
                    background: transparent;
                    border: none;
                }
            """)
            
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(15)
            
            lbl_icon = QLabel("✓")
            lbl_icon.setStyleSheet("color: #10B981; font-weight: bold; font-size: 24px;")
            lbl_icon.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(lbl_icon)
            
            text_layout = QVBoxLayout()
            text_layout.setSpacing(4)
            
            lbl_title = QLabel("Export Completed")
            lbl_title.setStyleSheet("color: #FFFFFF; font-weight: bold; font-size: 14px;")
            text_layout.addWidget(lbl_title)
            
            metrics = QFontMetrics(lbl_title.font())
            elided_task = metrics.elidedText(task_name, Qt.TextElideMode.ElideMiddle, 350)
            lbl_task = QLabel(elided_task)
            lbl_task.setStyleSheet("color: #D7E3F4; font-family: monospace; font-size: 12px;")
            lbl_task.setToolTip(task_name)
            text_layout.addWidget(lbl_task)
            
            lbl_desc = QLabel("Earth Engine has finished exporting your scene.\nThe file should now be available in Google Drive.")
            lbl_desc.setStyleSheet("color: #9CA3AF; font-size: 11px;")
            text_layout.addWidget(lbl_desc)
            
            layout.addLayout(text_layout)
            layout.addStretch(1)
            
            self.iface.messageBar().pushWidget(widget, Qgis.MessageLevel.Success, 0)
        elif state == "FAILED":
            self.iface.messageBar().pushMessage(
                "Export Failed", 
                f"The Earth Engine export '{task_name}' failed. Check the Earth Engine task details.\nError: {error_msg}", 
                level=Qgis.MessageLevel.Critical, duration=0
            )
        elif state == "CANCELLED":
            self.iface.messageBar().pushMessage(
                "Export Cancelled", 
                f"The Earth Engine export '{task_name}' was cancelled.", 
                level=Qgis.MessageLevel.Warning, duration=0
            )
            
    def load_illustration(self, image_name: str, target_label, target_height: int = 80):
        """Single reusable helper function to load and cache UI illustrations dynamically."""
        if not hasattr(self, '_image_cache'):
            self._image_cache = {}
            
        if image_name in self._image_cache:
            pixmap = self._image_cache[image_name]
        else:
            from PyQt6.QtGui import QPixmap
            import os
            plugin_dir = os.path.dirname(os.path.dirname(__file__))
            img_path = os.path.join(plugin_dir, "pics", image_name)
            
            if os.path.exists(img_path):
                pixmap = QPixmap(img_path)
                # Ensure High-DPI support
                pixmap.setDevicePixelRatio(self.devicePixelRatioF())
                self._image_cache[image_name] = pixmap
            else:
                return False
                
        from PyQt6.QtCore import Qt
        target_label.setScaledContents(False)
        target_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        is_hero = (target_label.objectName() == "lblDashBigIcon")
        if is_hero:
            target_height = max(target_height, 240)
            
        aspect_ratio = pixmap.width() / pixmap.height() if pixmap.height() > 0 else 1.0
        target_width = int(target_height * aspect_ratio)
        
        if is_hero:
            target_label.setMinimumSize(80, 80)
            target_label.setMaximumSize(16777215, 16777215)
        else:
            target_label.setMinimumSize(target_width, target_height)
            target_label.setMaximumSize(target_width, target_height)
        
        scaled_pixmap = pixmap.scaled(
            target_width, target_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        target_label.setPixmap(scaled_pixmap)
        target_label.setStyleSheet("background: transparent; border: none;")
        return True

    def open_login_dialog(self):
        """Open the GEE authentication dialog."""
        dialog = LoginDialog(self)
        dialog.exec()
        self.check_initial_gee_status()
        self.refresh_header()
        
    def on_help_web_demo(self):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        from ..config import WEB_DEMO_URL
        QDesktopServices.openUrl(QUrl(WEB_DEMO_URL))
        
    def on_help_contact_support(self):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl("https://tally.so/r/9qAzW1"))

    def setup_source_switch(self):
        if hasattr(self, 'btnSourceLocal') and hasattr(self, 'btnSourceGEE'):
            self.btnSourceLocal.clicked.connect(lambda: self.on_source_changed("LOCAL"))
            self.btnSourceGEE.clicked.connect(lambda: self.on_source_changed("GEE"))

    def apply_provider_state(self):
        try:
            from ..utils.timing_profiler import TimingProfiler
            TimingProfiler.get_instance().record("T7", "apply_provider_state begins")
        except Exception:
            pass
        """
        Applies the current provider state as the single source of truth.
        This forces the UI, workspace, and available actions to match the current provider,
        overriding any incompatible history.
        """
        is_local = (self.connection_service.current_provider() == "Local Raster")
        
        # 1. Sync UI Highlight precisely with provider state
        if hasattr(self, 'btnSourceLocal'):
            self.btnSourceLocal.setChecked(is_local)
        if hasattr(self, 'btnSourceGEE'):
            self.btnSourceGEE.setChecked(not is_local)
            
        # 2. Handle Download Scene workspace presence
        if hasattr(self, 'sidebar_buttons') and "environmental" in self.sidebar_buttons:
            self.sidebar_buttons["environmental"].setVisible(not is_local)
            
        if hasattr(self, 'btnSceneSelector'):
            self.btnSceneSelector.setVisible(not is_local)
            
        # 3. Handle Workspace Restoration/Switching
        current_ws = getattr(self, '_current_workspace_id', None)
        
        if is_local and current_ws == "environmental":
            # Switch away from the hidden Download Scene workspace
            for ws_id, btn in self.sidebar_buttons.items():
                if ws_id != "environmental":
                    self.load_workspace(ws_id)
                    break
        elif current_ws:
            # Reload the current valid workspace in the new provider context
            self.load_workspace(current_ws)
        else:
            # No workspace loaded yet, load the default Vegetation + Dashboard state
            if hasattr(self, 'sidebar_buttons'):
                if "vegetation" in self.sidebar_buttons:
                    self.load_workspace("vegetation")
                else:
                    for ws_id, btn in self.sidebar_buttons.items():
                        if ws_id != "environmental" or not is_local:
                            self.load_workspace(ws_id)
                            break
                            
            if hasattr(self, 'tabWidget'):
                for i in range(self.tabWidget.count()):
                    if self.tabWidget.widget(i).objectName() == "tabDashboard":
                        self.tabWidget.setCurrentIndex(i)
                        break
                    
        # 4. Trigger header refresh
        self.refresh_header()
        try:
            from ..utils.timing_profiler import TimingProfiler
            TimingProfiler.get_instance().record("T7_end", "apply_provider_state ends")
        except Exception:
            pass

    def on_source_changed(self, selected: str):
        # 1. Update the Provider state as the single source of truth
        if selected == "GEE":
            if not self.connection_service.is_authenticated():
                try:
                    from qgis.core import Qgis
                    self.iface.messageBar().pushMessage("Earth Engine", "GEE must be connected before it can be used.", level=Qgis.MessageLevel.Warning, duration=5)
                except Exception:
                    pass
            self.connection_service.set_current_provider("Google Earth Engine")
        else:
            self.connection_service.set_current_provider("Local Raster")
            
        # 2. Apply the new provider state to the UI
        self.apply_provider_state()

    def setup_custom_menu(self):
        if hasattr(self, 'btnWsCustom'):
            self.btnWsCustom.clicked.connect(self.on_time_series_clicked)

    def on_time_series_clicked(self):
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(self, "Time Series", "Coming Soon")

    def open_analysis_wizard(self, analysis_type: str):
        """Open the unified analysis wizard for a specific workflow."""
        provider = self.connection_service.current_provider()
        

        self.deactivate_pixel_inspector()
        
        if provider == "Local Raster":
            if analysis_type == "download_scene":
                self.logger.warning("Download scene routed to Local Raster - blocking.")
                return
                
            from .local_raster_wizard import LocalRasterWizardDialog
            dialog = LocalRasterWizardDialog(self, self.iface, analysis_type)
        else:
            dialog = AnalysisWizardDialog(self, analysis_type, self.iface)
            
        dialog.analysis_workflow_finished.connect(self.on_analysis_completed)
        dialog.exec()

    def load_workspace(self, workspace_id: str):
        """Dynamically load and configure the UI for the selected workspace."""
        self.logger.info(f"Loading workspace: {workspace_id}")
        self._current_workspace_id = workspace_id
        
        try:
            from ..utils.timing_profiler import TimingProfiler
            TimingProfiler.get_instance().record("WS_SWITCH", f"load_workspace START: {workspace_id}")
        except Exception:
            pass
        # Suppress repaints to prevent white/gray flashes during heavy layout and styling operations
        self.setUpdatesEnabled(False)
        try:
            # 0. Get Theme from ThemeManager
            theme = self.theme_manager.get_theme(workspace_id)
            primary = theme.get("primary_color", "#2563EB")
            accent = theme.get("accent_color", "#EFF6FF")
            icon_path = theme.get("icon", ":/plugins/remote_sensing_studio/icons/plugin_icon.png")
            
            # 1. Update Sidebar Active State
            for ws_id, btn in getattr(self, 'sidebar_buttons', {}).items():
                if ws_id == workspace_id:
                    btn.setProperty("cssClass", "sidebarActive")
                    # Apply dynamic theme for active button
                    btn.setStyleSheet(f"""
                        background-color: {accent};
                        color: {primary};
                        border: 1px solid {primary}40;
                        border-radius: 12px;
                        font-weight: 700;
                        text-align: left;
                        padding: 14px 20px;
                    """)
                    # Optionally set the icon on the sidebar button
                    from PyQt6.QtGui import QIcon
                    btn.setIcon(QIcon(icon_path))
                else:
                    btn.setProperty("cssClass", "sidebar")
                    btn.setStyleSheet("")
                    from PyQt6.QtGui import QIcon
                    btn.setIcon(QIcon())
                # Force style re-evaluation
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                
            try:
                from ..utils.timing_profiler import TimingProfiler
                TimingProfiler.get_instance().record("WS_SWITCH", "stylesheet/layout work begins")
            except Exception:
                pass
            # Global Dynamic Tab Style Injection
            if hasattr(self, 'tabWidget'):
                self.tabWidget.setStyleSheet(f"""
                    QTabWidget::pane {{ border: none; background: transparent; }}
                    QTabBar::tab {{ background: transparent; color: #AFC4D8; padding: 16px 24px; border: none; font-size: 12pt; font-weight: 600; margin-right: 8px; }}
                    QTabBar::tab:selected {{ color: #FFFFFF; background-color: transparent; border-bottom: 3px solid {primary}; }}
                    QTabBar::tab:hover:!selected {{ color: #FFFFFF; background-color: rgba(255,255,255,0.03); border-radius: 12px; }}
                """)
        finally:
            try:
                from ..utils.timing_profiler import TimingProfiler
                TimingProfiler.get_instance().record("WS_SWITCH", "load_workspace END")
            except Exception:
                pass
            self.setUpdatesEnabled(True)
            
        # 2. Get Metadata from WorkspaceManager
        display_name = self.workspace_manager.get_display_name(workspace_id)
        indices = self.workspace_manager.get_indices_for_workspace(workspace_id)
        
        # 3. Update Dashboard Labels
        if hasattr(self, 'lblDashAnalysisType'):
            self.lblDashAnalysisType.setText(f'<b style="font-size:24pt; color:#FFFFFF;">{display_name} Workspace</b>')
            
        # If there's an icon container for the dashboard (like lblAppIcon or a custom one), update it.
        if hasattr(self, 'lblDashBigIcon'):
            img_name = "vegetation.webp"
            if workspace_id == "vegetation":
                img_name = "vegetation.webp"
            elif workspace_id == "water":
                img_name = "water.webp"
            elif workspace_id == "urban":
                img_name = "building.webp"
            elif workspace_id == "environmental":
                # TODO: Replace with environmental illustration when available
                img_name = "vegetation.webp"
                
            success = self.load_illustration(img_name, self.lblDashBigIcon, target_height=130)
            
            if not success:
                self.lblDashBigIcon.setStyleSheet(f"background-color: {accent}; border-radius: 40px; padding: 20px;")
                # Using QPixmap from icon to display on QLabel
                from PyQt6.QtGui import QIcon, QPixmap
                from PyQt6.QtCore import QSize
                icon = QIcon(icon_path)
                # Render icon as a 40x40 pixmap
                pixmap = icon.pixmap(QSize(40, 40))
                self.lblDashBigIcon.setPixmap(pixmap)
            
        if hasattr(self, 'lblDashScenes'):
            self.lblDashScenes.setText(f'<b style="font-size:32pt; color:{primary};">0</b>')
            
        if hasattr(self, 'lblDashDetails'):
            if workspace_id == 'environmental':
                self.lblDashDetails.setText('Download satellite scenes or composite datasets for local and offline analysis.')
            elif not indices:
                self.lblDashDetails.setText('Analysis tools will automatically appear here as they are implemented.')
            else:
                self.lblDashDetails.setText(f'Select an analysis tool from the {display_name} suite.')
            
        # 4. Rebuild Quick Start Buttons
        print(f"\nEntering populate_quick_start() - workspace: {workspace_id}")
        print(f"Indices found: {len(indices) if indices else 0}")
        try:
            grp_box = getattr(self, 'grpQuickStart', None)
            if not grp_box:
                from PyQt6.QtWidgets import QGroupBox
                for gb in self.findChildren(QGroupBox):
                    if gb.title() == "Quick Start":
                        grp_box = gb
                        break
            
            print(f"Quick Start group box found: {grp_box is not None}")
                        
            if grp_box:
                parent_widget = grp_box
                layout = parent_widget.layout()
                if not layout:
                    from PyQt6.QtWidgets import QVBoxLayout
                    layout = QVBoxLayout()
                    parent_widget.setLayout(layout)
                
                if layout:
                    from PyQt6.QtWidgets import QPushButton, QWidget, QSizePolicy
                    from PyQt6.QtCore import Qt
                    from .flow_layout import FlowLayout
                    
                    # Setup grid layout once
                    if not hasattr(self, 'quick_start_grid'):
                        self.quick_start_widget = QWidget()
                        self.quick_start_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
                        self.quick_start_grid = FlowLayout(margin=0, spacing=10)
                        self.quick_start_widget.setLayout(self.quick_start_grid)
                        # Insert the widget at index 0 (above btnSceneSelector)
                        layout.insertWidget(0, self.quick_start_widget)
                    
                    try:
                        from ..utils.timing_profiler import TimingProfiler
                        TimingProfiler.get_instance().record("WS_SWITCH", "old widget removal begins")
                    except Exception:
                        pass
                    # Clear existing dynamic buttons from grid layout
                    while self.quick_start_grid.count() > 0:
                        item = self.quick_start_grid.takeAt(0)
                        widget = item.widget()
                        if widget:
                            if widget.objectName() == "btnSceneSelector":
                                widget.hide()
                                widget.setParent(None)
                            else:
                                widget.deleteLater()
                            
                    try:
                        from ..utils.timing_profiler import TimingProfiler
                        TimingProfiler.get_instance().record("WS_SWITCH", "new widget construction begins")
                    except Exception:
                        pass
                    print("Rebuilding buttons from metadata...")
                    # Rebuild buttons based strictly on metadata
                    if not indices:
                        if workspace_id == 'environmental':
                            btn_text = "Select an AOI, search satellite scenes, choose a single scene or composite,\nand download a GIS-ready GeoTIFF."
                        else:
                            btn_text = "This workspace is ready.\n\nAnalysis tools will automatically appear here as they are implemented."
                        # Empty state
                        btn = QPushButton(btn_text)
                        btn.setStyleSheet("text-align: center; padding: 20px; color: #B8C6D8; font-size: 11pt; background: #12243B; border: 1px dashed rgba(255, 255, 255, 0.1);")
                        btn.setEnabled(False)
                        self.quick_start_grid.addWidget(btn)
                    else:
                        for index_def in indices:
                            index_id = index_def["id"]
                            subtitle = index_def.get("metadata", {}).get("display_name", index_id)
                            
                            btn = QPushButton(f" {index_id}")
                            btn.setToolTip(subtitle)
                            # Uniform compact cards, exactly the same size for a perfect grid
                            btn.setFixedSize(130, 42)
                            btn.setCursor(Qt.CursorShape.PointingHandCursor)
                            
                            # Apply Theme to Quick Start Buttons
                            btn.setStyleSheet(f"""
                                QPushButton {{
                                    background-color: {primary};
                                    color: white;
                                    border-radius: 8px;
                                    padding: 8px;
                                    text-align: left;
                                    font-weight: bold;
                                    font-size: 11pt;
                                }}
                                QPushButton:hover {{
                                    background-color: {primary}ee;
                                    border-bottom: 2px solid rgba(0,0,0,0.15);
                                }}
                                QPushButton:pressed {{
                                    background-color: {primary}aa;
                                    margin-top: 1px;
                                }}
                            """)
                            from PyQt6.QtGui import QIcon
                            btn.setIcon(QIcon(icon_path))
                            
                            # Connect using default argument to avoid late binding issues
                            btn.clicked.connect(lambda checked=False, i_id=index_id: self.open_analysis_wizard(i_id))
                            self.quick_start_grid.addWidget(btn)
                            
                    # Integrate Open Scene Selector as the final grid item
                    btn_scene = getattr(self, 'btnSceneSelector', None)
                    if btn_scene:
                        # Remove from outer QVBoxLayout to avoid duplication/layout conflicts
                        layout.removeWidget(btn_scene)
                        
                        provider = getattr(self, 'connection_service', None)
                        is_local = (provider and provider.current_provider() == "Local Raster")
                        
                        if is_local:
                            self.quick_start_grid.addWidget(btn_scene)
                            btn_scene.setVisible(False)
                        else:
                            btn_scene.setFixedSize(180, 42)
                            btn_scene.setCursor(Qt.CursorShape.PointingHandCursor)
                            
                            try: btn_scene.clicked.disconnect()
                            except: pass
                            btn_scene.clicked.connect(lambda checked=False: self.open_analysis_wizard("download_scene"))
                            
                            app_blue = "#2563EB"
                            btn_scene.setStyleSheet(f"""
                                QPushButton {{
                                    background-color: {app_blue};
                                    color: white;
                                    border-radius: 8px;
                                    padding: 8px;
                                    text-align: left;
                                    font-weight: bold;
                                    font-size: 11pt;
                                }}
                                QPushButton:hover {{
                                    background-color: {app_blue}ee;
                                    border-bottom: 2px solid rgba(0,0,0,0.15);
                                }}
                                QPushButton:pressed {{
                                    background-color: {app_blue}aa;
                                    margin-top: 1px;
                                }}
                            """)
                            
                            self.quick_start_grid.addWidget(btn_scene)
                            btn_scene.setVisible(True)
                        
                    # FIX: Prevent vertical clipping during Restore caused by QGroupBox CSS size-hint bug.
                    # FlowLayout required height: 146px
                    # QVBoxLayout default margins: 18px (9px top/bottom)
                    # QGroupBox CSS overhead: 95px (45px margin-top, 24px padding top/bottom, 2px borders)
                    # Total required outer height: 146 + 18 + 95 = 259px
                    grp_box.setMinimumHeight(259)
                    
        except Exception as e:
            import traceback
            with open(r"c:\Users\user\sandbox\quick_start_error.log", "w") as f:
                f.write(traceback.format_exc())
            self.logger.error(f"Error rebuilding quick start: {e}", exc_info=True)
                    

                        
    def refresh_header(self):
        try:
            from ..utils.timing_profiler import TimingProfiler
            TimingProfiler.get_instance().record("T12", "refresh_header called")
        except Exception:
            pass
        """Update header UI with live data from ConnectionService and QgsProject."""
        try:
            # Update Project Name
            self.update_project_info()
            
            # Update Connection Status
            if hasattr(self, 'lblConnectionStatus'):
                self.lblConnectionStatus.setText(self.connection_service.connection_status())
                
            # Update User Avatar
            if hasattr(self, 'lblUserAvatar'):
                provider = self.connection_service.current_provider()
                if provider == "Local Raster":
                    initials = "L"
                elif self.connection_service.is_authenticated():
                    user = self.connection_service.current_user()
                    if user:
                        parts = user.split()
                        if len(parts) >= 2:
                            initials = f"{parts[0][0]}{parts[1][0]}".upper()
                        elif len(parts) == 1:
                            initials = f"{parts[0][0:2]}".upper()
                        else:
                            initials = "GU"
                    else:
                        initials = "GU"
                else:
                    initials = "G"
                    
                self.lblUserAvatar.setText(f'<div style="background-color:#1E3A5F; border-radius:18px; width:36px; height:36px; text-align:center; line-height:36px; font-weight:bold; color:#FFFFFF;">{initials}</div>')
                
            # Update Settings Tab
            if hasattr(self, 'lblSettingsAuthStatus'):
                self.lblSettingsAuthStatus.setText(self.connection_service.connection_status())
                
            if hasattr(self, 'lblSettingsAccount'):
                provider = self.connection_service.current_provider()
                if provider == "Local Raster":
                    self.lblSettingsAccount.setText("Local Provider Active")
                    if hasattr(self, 'lblSettingsProject'): self.lblSettingsProject.setText("N/A")
                    if hasattr(self, 'lblSettingsValidation'): self.lblSettingsValidation.setText("N/A")
                    
                    if hasattr(self, 'btnSettingsSignInOut'): self.btnSettingsSignInOut.setVisible(False)
                    if hasattr(self, 'btnSettingsSwitchAccount'): self.btnSettingsSwitchAccount.setVisible(False)
                    if hasattr(self, 'btnSettingsManageAccess'): self.btnSettingsManageAccess.setVisible(False)
                elif self.connection_service.is_authenticated():
                    user = self.connection_service.current_user()
                    self.lblSettingsAccount.setText(user if user else "—")
                    
                    status = self.connection_service.get_gee_status()
                    project = status.get('project', '')
                    is_ready = self.connection_service.is_project_ready()
                    
                    if hasattr(self, 'lblSettingsProject'):
                        self.lblSettingsProject.setText(project if project else "Not configured")
                    if hasattr(self, 'lblSettingsValidation'):
                        if is_ready:
                            self.lblSettingsValidation.setText('<font color="#059669">✓ Earth Engine Ready</font>')
                        else:
                            self.lblSettingsValidation.setText('<font color="#D97706">⚠ Project Required</font>')
                            
                    if hasattr(self, 'btnSettingsSignInOut'):
                        self.btnSettingsSignInOut.setText("Sign Out")
                        self.btnSettingsSignInOut.setVisible(True)
                    if hasattr(self, 'btnSettingsSwitchAccount'):
                        self.btnSettingsSwitchAccount.setVisible(True)
                    if hasattr(self, 'btnSettingsManageAccess'): self.btnSettingsManageAccess.setVisible(True)
                else:
                    self.lblSettingsAccount.setText("—")
                    if hasattr(self, 'lblSettingsProject'): self.lblSettingsProject.setText("—")
                    if hasattr(self, 'lblSettingsValidation'): self.lblSettingsValidation.setText("—")
                    
                    if hasattr(self, 'btnSettingsSignInOut'):
                        self.btnSettingsSignInOut.setText("Sign In with Google")
                        self.btnSettingsSignInOut.setVisible(True)
                    if hasattr(self, 'btnSettingsSwitchAccount'):
                        self.btnSettingsSwitchAccount.setVisible(False)
                    if hasattr(self, 'btnSettingsManageAccess'): self.btnSettingsManageAccess.setVisible(False)
                    
        except Exception as e:
            self.logger.error(f"Error refreshing header: {e}", exc_info=True)

    def on_settings_manage_access_clicked(self):
        """Handle clicks on the Manage Access button in the Settings tab."""
        import webbrowser
        from PyQt6.QtWidgets import QMessageBox
        self.logger.info("Opening Google Earth Engine access settings in browser.")
        QMessageBox.information(self, "Manage Access", "Google account permissions will open in your default browser.")
        try:
            webbrowser.open("https://myaccount.google.com/permissions")
        except Exception as e:
            self.logger.error(f"Failed to open browser: {e}")
            QMessageBox.critical(self, "Error", f"Failed to open browser: {e}")

    def on_settings_sign_in_out_clicked(self):
        """Handle Sign In / Sign Out exclusively from Settings."""
        if self.connection_service.is_authenticated():
            from PyQt6.QtWidgets import QMessageBox
            self.logger.info("Signing out from Settings")
            success, msg = self.connection_service.logout_gee()
            if success:
                QMessageBox.information(self, "Logged Out", "You have been successfully signed out.")
            else:
                QMessageBox.warning(self, "Logout Failed", f"Could not complete sign out:\n\n{msg}")
            self.refresh_header()
        else:
            self.logger.info("Opening LoginDialog from Settings to start authentication")
            dialog = LoginDialog(self)
            dialog.setProperty("auto_start_auth", True)
            dialog.exec()
            self.refresh_header()

    def on_settings_switch_account_clicked(self):
        """Handle Switch Account explicitly by opening LoginDialog in force-auth mode."""
        self.logger.info("Opening LoginDialog from Settings for Switch Account")
        dialog = LoginDialog(self)
        dialog.setProperty("auto_start_auth", True)
        dialog.exec()
        self.refresh_header()
    def on_avatar_clicked(self, event):
        """Handle clicks on the user avatar label."""
        provider = self.connection_service.current_provider()
        if provider == "Local Raster":
            self.iface.messageBar().pushMessage("Provider Info", "Currently using Local Raster provider.", level=Qgis.MessageLevel.Info, duration=5)
        elif self.connection_service.is_authenticated():
            # LoginDialog currently serves as the Account Information & Logout dialog
            self.open_login_dialog()
            self.refresh_header()
        else:
            self.open_login_dialog()
            self.refresh_header()

    def check_initial_gee_status(self):
        """Check GEE status and display lightweight notification."""
        try:
            provider = self.connection_service.current_provider()
            if provider == "Local Raster":
                self.iface.messageBar().pushMessage("Earth Engine", "Working with Local Raster Provider.", level=Qgis.MessageLevel.Info, duration=5)
            elif self.connection_service.is_authenticated():
                self.iface.messageBar().pushMessage("Earth Engine", "Earth Engine connected successfully.", level=Qgis.MessageLevel.Success, duration=5)
        except Exception as e:
            self.logger.error(f"Could not push notification: {e}")

    def on_tab_changed(self, index):
        self.logger.info(f"Navigated to tab index: {index}")

    def on_analysis_completed(self, result: AnalysisResult, vis_result: VisualizationResult):
        """Update the MVVM view directly from the immutable AnalysisResult model."""
            
        try:
            # Update Dashboard
            if hasattr(self, 'lblDashAnalysisType'): self.lblDashAnalysisType.setText(f'<b style="font-size:24pt; color:#FFFFFF;">{result.formula_name}</b>')
            if hasattr(self, 'lblDashDetails'): self.lblDashDetails.setText(f'Provider: {result.provider} | Dataset: {result.dataset}')
            if hasattr(self, 'lblDashScenes'): self.lblDashScenes.setText(f'<b style="font-size:32pt; color:#2563EB;">{result.number_of_scenes}</b>')
            if hasattr(self, 'lblDashExecutionTime'): self.lblDashExecutionTime.setText(f'Execution Time: {result.execution_time_sec} s')
            
            # Update Results Map Tab
            # The new interactive visualization workspace handles its own updates,
            # but we can notify it that a new layer is available.
            self.last_analysis_result = result
            if hasattr(self, 'on_new_layer_ready'):
                self.on_new_layer_ready(vis_result.layer_name, result.analysis_type)
            
            if hasattr(self, 'lblMapPreview'): 
                if vis_result.success:
                    self.lblMapPreview.setText(f'Layer {result.output_layer_name} loaded into workspace.')
                    self.lblMapPreview.setStyleSheet("color: #10B981; font-size: 14pt;")
                else:
                    self.lblMapPreview.setText('Visualization Failed')
                    self.lblMapPreview.setStyleSheet("color: #DC2626; font-size: 14pt;")

            # We now defer the Scientific Report and QA detailed stats generation to `on_new_layer_ready`
            # so it can combine both GEE metadata and local Raster Statistics/Classification!
                
            self.logger.info("MainDialog views partially synchronized with AnalysisResult. Awaiting local statistics.")
        except Exception as e:
            self.logger.error(f"Error updating UI from AnalysisResult: {e}")

    # ----------------------------------------------------------------------
    # Export Functions
    # ----------------------------------------------------------------------
    def export_report_pdf(self):
        try:
            from PyQt6.QtWidgets import QFileDialog
            from PyQt6.QtGui import QPdfWriter
            from PyQt6.QtCore import QMarginsF
            
            if not hasattr(self, 'txtScientificReport') or not self.txtScientificReport.toPlainText():
                return
                
            path, _ = QFileDialog.getSaveFileName(self, "Export Report as PDF", "", "PDF Files (*.pdf)")
            if path:
                # Additive integration: use Universal Scientific PDF Report Engine if context is available
                if getattr(self, 'current_report_context', None) is not None:
                    from ..services.report_builder import ReportBuilder
                    target_layer = getattr(self, 'current_layer', None)
                    success = ReportBuilder.export_pdf("", path, context=self.current_report_context, target_layer=target_layer)
                    if success:
                        self.logger.info(f"Report exported to publication PDF via ScientificPdfEngine: {path}")
                        return

                # Fallback to direct HTML print if context is unavailable
                writer = QPdfWriter(path)
                writer.setPageMargins(QMarginsF(15, 15, 15, 15))
                self.txtScientificReport.document().print(writer)
                self.logger.info(f"Report exported to basic PDF: {path}")
        except Exception as e:
            self.logger.error(f"Failed to export PDF: {e}")

    def export_report_html(self):
        try:
            from PyQt6.QtWidgets import QFileDialog
            if not hasattr(self, 'txtScientificReport') or not self.txtScientificReport.toPlainText():
                return
                
            path, _ = QFileDialog.getSaveFileName(self, "Export Report as HTML", "", "HTML Files (*.html)")
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.txtScientificReport.toHtml())
                self.logger.info(f"Report exported to HTML: {path}")
        except Exception as e:
            self.logger.error(f"Failed to export HTML: {e}")

    def export_report_md(self):
        try:
            from PyQt6.QtWidgets import QFileDialog
            if not hasattr(self, 'txtScientificReport') or not self.txtScientificReport.toPlainText():
                return
                
            path, _ = QFileDialog.getSaveFileName(self, "Export Report as Markdown", "", "Markdown Files (*.md)")
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    # Very simple HTML to Markdown translation for our specific report format
                    html_text = self.txtScientificReport.toPlainText()
                    f.write(html_text)
                self.logger.info(f"Report exported to Markdown: {path}")
        except Exception as e:
            self.logger.error(f"Failed to export Markdown: {e}")

    def setup_aoi_selector(self):
        try:
            if not hasattr(self, 'tabParameters'):
                return
                
            layout = self.tabParameters.layout()
            while layout.count():
                child = layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
                    
            self.gbAOI = QGroupBox("Area of Interest (AOI) Selection")
            self.gbAOI.setProperty("cssClass", "card")
            aoi_layout = QVBoxLayout()
            aoi_layout.setSpacing(15)
            
            self.cmbAOI = QComboBox()
            self.cmbAOI.currentIndexChanged.connect(self.on_aoi_changed)
            aoi_layout.addWidget(self.cmbAOI)
            
            self.lblLayerInfo = QLabel("No layer selected.")
            self.lblLayerInfo.setStyleSheet("color: #B8C6D8; font-size: 12pt; line-height: 1.5;")
            self.lblLayerInfo.setWordWrap(True)
            aoi_layout.addWidget(self.lblLayerInfo)
            
            self.gbAOI.setLayout(aoi_layout)
            layout.addWidget(self.gbAOI)
            layout.addStretch()
        except Exception as e:
            self.logger.error(f"Error setting up AOI selector: {e}", exc_info=True)

    def connect_signals(self):
        try:
            project = QgsProject.instance()
            project.layersAdded.connect(self.populate_layers)
            project.layersRemoved.connect(self.populate_layers)
            project.readProject.connect(self.update_project_info)
            project.projectSaved.connect(self.update_project_info)
        except Exception as e:
            pass
            
    def update_project_info(self, *args, **kwargs):
        try:
            if hasattr(self, 'lblCurrentProject'):
                project = QgsProject.instance()
                title = project.title() or project.baseName()
                if not title:
                    title = "Untitled Project"
                self.lblCurrentProject.setText(f'<b style="color: #FFFFFF;">{title}</b>')
        except Exception:
            pass

    def populate_layers(self, *args, **kwargs):
        try:
            if not hasattr(self, 'cmbAOI'):
                return
                
            self.cmbAOI.blockSignals(True)
            self.cmbAOI.clear()
            
            project = QgsProject.instance()
            layers = project.mapLayers().values()
            
            for layer in layers:
                if isinstance(layer, QgsVectorLayer) and layer.geometryType() == QgsWkbTypes.PolygonGeometry:
                    self.cmbAOI.addItem(layer.name(), layer.id())
                    
            self.cmbAOI.blockSignals(False)
            self.on_aoi_changed()
        except Exception:
            pass
            
    def on_aoi_changed(self):
        try:
            if not hasattr(self, 'cmbAOI') or not hasattr(self, 'lblLayerInfo'):
                return
                
            layer_id = self.cmbAOI.currentData()
            if not layer_id:
                self.lblLayerInfo.setText("No valid polygon layer available in the current project.")
                return
                
            layer = QgsProject.instance().mapLayer(layer_id)
            if layer:
                name = layer.name()
                geom_type = QgsWkbTypes.displayString(layer.wkbType())
                crs = layer.crs().authid()
                count = layer.featureCount()
                
                info_text = (
                    f"<b>Layer Name:</b> {name}<br><br>"
                    f"<b>Geometry Type:</b> {geom_type}<br><br>"
                    f"<b>Coordinate System:</b> {crs}<br><br>"
                    f"<b>Feature Count:</b> {count}"
                )
                self.lblLayerInfo.setText(info_text)
            else:
                self.lblLayerInfo.setText("Layer not found.")
        except Exception:
            pass

    def setup_visualization_workspace(self):
        """Dynamically sets up the Interactive Visualization UI inside tabResults."""
        try:
            from ..visualization.palette_manager import PaletteManager
            from ..visualization.renderer_manager import RendererManager
            from ..visualization.symbology_manager import SymbologyManager
            from ..visualization.pixel_inspector import PixelInspectorTool
            from ..visualization.pixel_inspector_session import PixelInspectorSession
            from ..analysis.statistics_engine import StatisticsEngine
            from ..analysis.classification_engine import ClassificationEngine
            from ..analysis.raster_metadata import get_raster_metadata
            from .widgets.histogram_widget import HistogramWidget
            from .widgets.pixel_inspector_dialog import PixelInspectorDialog
            from PyQt6.QtWidgets import QVBoxLayout, QHBoxLayout, QSplitter, QWidget, QPushButton, QComboBox, QDoubleSpinBox, QFormLayout, QTableWidget, QHeaderView
            from PyQt6.QtCore import Qt
            
            # Initialize managers
            palettes_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "palettes")
            templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "templates")
            
            self.palette_manager = PaletteManager(palettes_dir)
            self.renderer_manager = RendererManager()
            self.symbology_manager = SymbologyManager(templates_dir)
            self.statistics_engine = StatisticsEngine()
            
            self.current_layer = None
            self.current_metadata = get_raster_metadata("CUSTOM")
            
            if not hasattr(self, 'tabResults'):
                return
                
            layout = self.tabResults.layout()
            if layout:
                while layout.count():
                    item = layout.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()
            else:
                layout = QVBoxLayout(self.tabResults)
                
            # Splitter
            splitter = QSplitter(Qt.Orientation.Horizontal)
            layout.addWidget(splitter)
            
            # Left: Controls
            left_w = QWidget()
            left_lay = QVBoxLayout(left_w)
            
            # Layer Info Panel
            self.lblVisLayerInfo = QLabel("Layer Info: None")
            self.lblVisLayerInfo.setStyleSheet("color: #B8C6D8; font-size: 10pt;")
            left_lay.addWidget(self.lblVisLayerInfo)
            
            # Controls Group
            ctrl_group = QGroupBox("Visualization Settings")
            ctrl_lay = QFormLayout(ctrl_group)
            
            self.cmbPalette = QComboBox()
            self._populate_palette_combo()
            self.cmbPalette.currentTextChanged.connect(self.on_vis_setting_changed)
            ctrl_lay.addRow("Palette:", self.cmbPalette)
            
            self.cmbClassMode = QComboBox()
            self.cmbClassMode.addItems(["Continuous", "Binary", "Equal Interval", "Quantile", "Natural Breaks (Jenks)"])
            self.cmbClassMode.currentTextChanged.connect(self.on_vis_setting_changed)
            ctrl_lay.addRow("Classification:", self.cmbClassMode)
            
            self.spnMin = QDoubleSpinBox()
            self.spnMin.setRange(-10000, 10000)
            self.spnMin.valueChanged.connect(self.on_vis_setting_changed)
            self.spnMax = QDoubleSpinBox()
            self.spnMax.setRange(-10000, 10000)
            self.spnMax.setValue(1.0)
            self.spnMax.valueChanged.connect(self.on_vis_setting_changed)
            
            range_lay = QHBoxLayout()
            range_lay.addWidget(self.spnMin)
            range_lay.addWidget(self.spnMax)
            lbl_range = QLabel("Display Range:")
            lbl_range.setToolTip("Color Stretch (Visualization Only). Does not affect scientific area calculations.")
            ctrl_lay.addRow(lbl_range, range_lay)
            
            self.spnThreshold = QDoubleSpinBox()
            self.spnThreshold.setRange(-10000, 10000)
            self.spnThreshold.setSingleStep(0.05)
            self.spnThreshold.valueChanged.connect(self.on_threshold_spinner_changed)
            ctrl_lay.addRow("Threshold:", self.spnThreshold)
            
            left_lay.addWidget(ctrl_group)
            
            # FIX: Prevent Results & Maps Visualization Settings vertical clipping
            # caused by QGroupBox CSS size-hint behavior during window restore.
            # Calculated from QFormLayout defaults + QGroupBox CSS overhead:
            # 4 rows (~24px each) = 96px
            # 3 vertical spacing gaps (6px each) = 18px
            # Form layout margins = 22px
            # CSS overhead (45px margin-top, 48px padding, 2px borders) = 95px
            # Total proven minimum size hint height = 231px
            ctrl_group.setMinimumHeight(231)
            
            # Histogram
            self.histogram_widget = HistogramWidget()
            self.histogram_widget.thresholdChanged.connect(self.on_histogram_threshold_changed)
            left_lay.addWidget(self.histogram_widget)
            
            # Right: Statistics Panel
            right_w = QWidget()
            right_lay = QVBoxLayout(right_w)
            
            stats_group = QGroupBox("ROI Statistics")
            stats_lay = QVBoxLayout(stats_group)
            
            self.lblStatsSummary = QLabel("No statistics computed.")
            self.lblStatsSummary.setWordWrap(True)
            stats_lay.addWidget(self.lblStatsSummary)
            
            self.tblStats = QTableWidget(0, 3)
            self.tblStats.setHorizontalHeaderLabels(["Class", "Pixels", "Area (km²)"])
            self.tblStats.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            self.tblStats.setStyleSheet("""
                QTableWidget {
                    color: #FFFFFF;
                    background-color: #0A192F;
                    gridline-color: #374151;
                    border: 1px solid #374151;
                }
                QHeaderView::section {
                    background-color: #12243B;
                    color: #D7E3F4;
                    font-weight: bold;
                    border: 1px solid #374151;
                }
                QTableWidget::item {
                    color: #FFFFFF;
                    background-color: #0A192F;
                }
                QTableWidget::item:selected {
                    background-color: #2563EB;
                    color: #FFFFFF;
                }
            """)
            stats_lay.addWidget(self.tblStats)
            
            export_lay = QHBoxLayout()
            btnExportCSV = QPushButton("Export CSV")
            btnExportGeo = QPushButton("Export Binary Mask")
            export_lay.addWidget(btnExportCSV)
            export_lay.addWidget(btnExportGeo)
            stats_lay.addLayout(export_lay)
            
            right_lay.addWidget(stats_group)
            
            splitter.addWidget(left_w)
            splitter.addWidget(right_w)
            splitter.setSizes([500, 400])
            splitter.setStretchFactor(0, 0)
            splitter.setStretchFactor(1, 1)
            
            # Inspector Session Controller
            self.pixel_inspector = PixelInspectorTool(self.iface.mapCanvas(), None)
            self.pixel_inspector_dialog = PixelInspectorDialog(self)
            
            self.btnInspect = QPushButton("Toggle Pixel Inspector")
            self.btnInspect.setObjectName("btnTogglePixelInspector")
            self.btnInspect.setCheckable(True)
            self.btnInspect.toggled.connect(self.toggle_inspector)
            left_lay.addWidget(self.btnInspect)

            self.pixel_inspector_session = PixelInspectorSession(self.iface, self)
            
            # Alias histogram to histogram_widget so both attribute names refer to the constructed widget
            self.histogram = getattr(self, "histogram_widget", None)
            
            if all([self.pixel_inspector, self.pixel_inspector_dialog, self.histogram, self.btnInspect]):
                self.pixel_inspector_session.set_components(
                    self.pixel_inspector,
                    self.pixel_inspector_dialog,
                    self.histogram,
                    self.btnInspect
                )
            else:
                self.logger.error("Cannot execute set_components(): one or more required inspection components are missing or None!")
            try:
                QgsProject.instance().layersRemoved.connect(self._on_project_layers_removed)
            except Exception:
                pass
            
            # Try to restore session state
            state = self.symbology_manager.load_session_state()
            if state:
                if state.get("Palette") in self.palette_manager.get_palette_names():
                    self.cmbPalette.setCurrentText(state["Palette"])
                if state.get("Classification Method"):
                    self.cmbClassMode.setCurrentText(state["Classification Method"])
                display_range = state.get("Display Range", [0, 1])
                self.spnMin.setValue(display_range[0])
                self.spnMax.setValue(display_range[1])
                if state.get("Threshold"):
                    self.spnThreshold.setValue(state["Threshold"])
            
            self.logger.info("Visualization workspace initialized.")
            
            # Temporary geometry diagnostics
            self._vis_ctrl_group = ctrl_group
            self._vis_right_group = stats_group
            self._vis_splitter = splitter
            self._vis_range_lay = range_lay
            self._geom_log_enabled = True
            
            # Give UI a moment to layout before initial logging
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(500, lambda: self._log_geometry("INITIAL"))
            
        except Exception as e:
            self.logger.error(f"Failed to setup visualization workspace: {e}", exc_info=True)

    def _populate_palette_combo(self):
        from qgis.core import QgsStyle, QgsGradientColorRamp, QgsSymbolLayerUtils, QgsGradientStop
        from qgis.PyQt.QtGui import QIcon, QColor
        from qgis.PyQt.QtCore import QSize, Qt
        from qgis.PyQt.QtWidgets import QStyledItemDelegate
        
        self.cmbPalette.clear()
        self.cmbPalette.setIconSize(QSize(80, 14))
        
        class PaletteDelegate(QStyledItemDelegate):
            def initStyleOption(self, option, index):
                super().initStyleOption(option, index)
                display_role = Qt.ItemDataRole.DisplayRole if hasattr(Qt, 'ItemDataRole') else Qt.DisplayRole
                if index.data(display_role) == "Standard NDVI":
                    option.text = ""
        self.cmbPalette.setItemDelegate(PaletteDelegate(self.cmbPalette))
        
        custom_palettes = self.palette_manager.get_palette_names()
        model = self.cmbPalette.model()
        
        # 1. Custom Remote Sensing Studio Palettes
        self.cmbPalette.addItem("Remote Sensing Studio")
        idx = self.cmbPalette.count() - 1
        item = model.item(idx)
        if item:
            item.setEnabled(False)
            if hasattr(Qt, 'ItemFlag'):
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            else:
                item.setFlags(Qt.NoItemFlags)
        
        for name in custom_palettes:
            data = self.palette_manager.load(name)
            color_stops = data.get("color_stops", [])
            icon = QIcon()
            if color_stops:
                sorted_stops = sorted(color_stops, key=lambda s: s["value"])
                if sorted_stops:
                    color1 = QColor(sorted_stops[0]["color"])
                    color2 = QColor(sorted_stops[-1]["color"])
                    orig_min = sorted_stops[0]["value"]
                    orig_range = sorted_stops[-1]["value"] - orig_min
                    if orig_range == 0: orig_range = 1.0
                    
                    stops = []
                    if len(sorted_stops) > 2:
                        for stop in sorted_stops[1:-1]:
                            offset = (stop["value"] - orig_min) / orig_range
                            stops.append(QgsGradientStop(offset, QColor(stop["color"])))
                            
                    ramp = QgsGradientColorRamp(color1, color2, False, stops)
                    pixmap = QgsSymbolLayerUtils.colorRampPreviewPixmap(ramp, QSize(80, 14))
                    if not pixmap.isNull():
                        icon = QIcon(pixmap)
            else:
                style = QgsStyle.defaultStyle()
                ramp = style.colorRamp(name)
                if isinstance(ramp, QgsGradientColorRamp):
                    pixmap = QgsSymbolLayerUtils.colorRampPreviewPixmap(ramp, QSize(80, 14))
                    if not pixmap.isNull():
                        icon = QIcon(pixmap)
            self.cmbPalette.addItem(icon, name)
            
        # 2. QGIS Native Ramps
        self.cmbPalette.addItem("QGIS Color Ramps")
        idx = self.cmbPalette.count() - 1
        item = model.item(idx)
        if item:
            item.setEnabled(False)
            if hasattr(Qt, 'ItemFlag'):
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            else:
                item.setFlags(Qt.NoItemFlags)
        
        style = QgsStyle.defaultStyle()
        for ramp_name in style.colorRampNames():
            if ramp_name in custom_palettes:
                continue
                
            ramp = style.colorRamp(ramp_name)
            if isinstance(ramp, QgsGradientColorRamp):
                pixmap = QgsSymbolLayerUtils.colorRampPreviewPixmap(ramp, QSize(80, 14))
                if not pixmap.isNull():
                    self.cmbPalette.addItem(QIcon(pixmap), ramp_name)

    def on_new_layer_ready(self, layer_name: str, index_type: str = "CUSTOM"):
        """Called when a new layer is downloaded and added to project."""
        self.deactivate_pixel_inspector()
        try:
            from ..analysis.raster_metadata import get_raster_metadata
            from qgis.core import QgsProject
            import os
            
            layers = QgsProject.instance().mapLayersByName(layer_name)
            if not layers:
                self.logger.error(f"Raster layer '{layer_name}' not found in QGIS.")
                return
            
            self.current_layer = layers[0]
            
            self.logger.debug("STEP: Raster loaded into QGIS")
            self.logger.debug(f"RUNTIME TRACE: Downloaded GeoTIFF Path: {self.current_layer.source()}")
            self.logger.debug(f"RUNTIME TRACE: Exists? {os.path.exists(self.current_layer.source())}")
            self.logger.debug(f"RUNTIME TRACE: Raster size: {self.current_layer.width()}x{self.current_layer.height()}")
            self.logger.debug(f"RUNTIME TRACE: Band count: {self.current_layer.bandCount()}")
            
            self.current_metadata = get_raster_metadata(index_type)
            
            try:
                if hasattr(self, 'pixel_inspector'):
                    self.pixel_inspector.set_layer(self.current_layer)
            except Exception as e:
                self.logger.warning(f"Failed to update optional pixel_inspector: {e}")
            
            # Compute actual stats for spinner initialization
            stats = self.statistics_engine.compute_base_statistics(self.current_layer.source())
            actual_min = stats.get('min', self.current_metadata.recommended_display_range[0])
            actual_max = stats.get('max', self.current_metadata.recommended_display_range[1])
            
            # Apply recommended metadata or inherited threshold from AnalysisResult
            self.cmbClassMode.blockSignals(True)
            self.cmbClassMode.setCurrentText(self.current_metadata.recommended_classification_mode)
            self.cmbClassMode.blockSignals(False)
            
            self.cmbPalette.blockSignals(True)
            self.cmbPalette.setCurrentText(self.current_metadata.recommended_palette)
            self.cmbPalette.blockSignals(False)
            
            self.spnMin.blockSignals(True)
            self.spnMin.setValue(actual_min)
            self.spnMin.blockSignals(False)
            
            self.spnMax.blockSignals(True)
            self.spnMax.setValue(actual_max)
            self.spnMax.blockSignals(False)
            
            # Inherit threshold from AnalysisResult if available
            inherited_threshold = self.current_metadata.recommended_threshold
            if hasattr(self, 'last_analysis_result') and self.last_analysis_result:
                inherited_threshold = self.last_analysis_result.visualization_params.get("Threshold", inherited_threshold)
            self.spnThreshold.blockSignals(True)
            self.spnThreshold.setValue(inherited_threshold)
            self.spnThreshold.blockSignals(False)
            
            self.lblVisLayerInfo.setText(f"<b>Layer:</b> {layer_name} | <b>Index:</b> {self.current_metadata.display_name}")
            
            self.update_statistics()
            
        except Exception as e:
            self.logger.error(f"Failed in on_new_layer_ready: {e}", exc_info=True)

    def on_vis_setting_changed(self, *args):
        self.update_renderer()
        self.save_session_state()

    def on_threshold_spinner_changed(self, value: float):
        if hasattr(self, 'histogram_widget'):
            self.histogram_widget.set_threshold(value)
        self.update_statistics_classes_only()
        self.update_renderer()
        self.save_session_state()

    def on_histogram_threshold_changed(self, value: float):
        self.spnThreshold.blockSignals(True)
        self.spnThreshold.setValue(value)
        self.spnThreshold.blockSignals(False)
        self.update_statistics_classes_only()
        self.update_renderer()
        self.save_session_state()

    def update_renderer(self):
        if not hasattr(self, 'current_layer') or not self.current_layer:
            return
            
        template = {
            "Classification Method": self.cmbClassMode.currentText(),
            "Display Range": [self.spnMin.value(), self.spnMax.value()],
            "Threshold": self.spnThreshold.value()
        }
        palette_data = self.palette_manager.load(self.cmbPalette.currentText())
        self.renderer_manager.updateRenderer(self.current_layer, template, palette_data)

    def update_statistics(self):
        """Recomputes base stats and histogram."""
        if not hasattr(self, 'current_layer') or not self.current_layer:
            return
            
        path = self.current_layer.source()
        stats = self.statistics_engine.compute_base_statistics(path)
        self.logger.debug("STEP: Statistics computed")
        
        self.logger.debug(f"RUNTIME TRACE: StatisticsEngine outputs:\n"
                          f"Minimum: {stats.get('min')}\n"
                          f"Maximum: {stats.get('max')}\n"
                          f"Mean: {stats.get('mean')}\n"
                          f"Valid Pixels: {stats.get('valid_pixels')}\n"
                          f"NoData Pixels: {stats.get('nodata_pixels')}")
        
        summary_text = (f"<span style='color: #D7E3F4;'><b>Min:</b></span> <span style='color: #FFFFFF;'>{stats['min']:.3f}</span> | <span style='color: #D7E3F4;'><b>Max:</b></span> <span style='color: #FFFFFF;'>{stats['max']:.3f}</span> | "
                        f"<span style='color: #D7E3F4;'><b>Mean:</b></span> <span style='color: #FFFFFF;'>{stats['mean']:.3f}</span><br>"
                        f"<span style='color: #D7E3F4;'><b>Valid Pixels:</b></span> <span style='color: #FFFFFF;'>{stats['valid_pixels']}</span> | <span style='color: #D7E3F4;'><b>NoData:</b></span> <span style='color: #FFFFFF;'>{stats['nodata_pixels']}</span>")
                        
        self.logger.debug(f"RUNTIME TRACE: Setting lblStatsSummary to: {summary_text}")
        self.lblStatsSummary.setText(summary_text)
        
        counts, edges = self.statistics_engine.compute_histogram(path)
        self.histogram_widget.set_data(counts, edges)
        
        self.update_statistics_classes_only()

    def update_statistics_classes_only(self):
        """Updates just the class areas when threshold changes (without reloading array)."""
        if not hasattr(self, 'current_layer') or not self.current_layer:
            return
            
        path = self.current_layer.source()
        from ..analysis.classification_engine import ClassificationEngine
        
        array, nodata = self.statistics_engine._load_raster(path)
        
        # Determine cell size for area calculation safely in m²
        try:
            from qgis.core import QgsDistanceArea, QgsGeometry, QgsPointXY, QgsProject
            layer_crs = self.current_layer.crs()
            
            pixel_width = abs(self.current_layer.rasterUnitsPerPixelX())
            pixel_height = abs(self.current_layer.rasterUnitsPerPixelY())
            
            da = QgsDistanceArea()
            da.setSourceCrs(layer_crs, QgsProject.instance().transformContext())
            ellipsoid = layer_crs.ellipsoidAcronym()
            if not ellipsoid or ellipsoid == 'NONE':
                ellipsoid = QgsProject.instance().ellipsoid()
            da.setEllipsoid(ellipsoid)
            
            ext = self.current_layer.extent()
            center = ext.center()
            cx, cy = center.x(), center.y()
            
            pixel_poly = QgsGeometry.fromPolygonXY([[
                QgsPointXY(cx - pixel_width/2, cy - pixel_height/2),
                QgsPointXY(cx + pixel_width/2, cy - pixel_height/2),
                QgsPointXY(cx + pixel_width/2, cy + pixel_height/2),
                QgsPointXY(cx - pixel_width/2, cy + pixel_height/2),
                QgsPointXY(cx - pixel_width/2, cy - pixel_height/2)
            ]])
            
            pixel_area = da.measureArea(pixel_poly)
            calc_method = "QgsDistanceArea (Geodesic)"
            
            if pixel_area <= 0:
                import math
                if layer_crs.isGeographic():
                    lat_m = pixel_height * 111320.0
                    lon_m = pixel_width * 111320.0 * math.cos(math.radians(cy))
                    pixel_area = abs(lat_m * lon_m)
                    calc_method = "Mathematical Approximation (Geographic)"
                else:
                    pixel_area = abs(pixel_width * pixel_height)
                    calc_method = "Planar Cartesian Math (Projected)"
                    
            self.logger.info(f"DIAGNOSTIC: Raster CRS: {layer_crs.authid()}\n"
                             f"DIAGNOSTIC: Pixel size: {pixel_width:.10f} x {pixel_height:.10f} units\n"
                             f"DIAGNOSTIC: Pixel area method: {calc_method}\n"
                             f"DIAGNOSTIC: Pixel area: approximately {pixel_area:.4f} m²")
            
        except Exception as e:
            self.logger.error(f"Failed to compute robust pixel area: {e}")
            pixel_width = abs(self.current_layer.rasterUnitsPerPixelX())
            pixel_height = abs(self.current_layer.rasterUnitsPerPixelY())
            if self.current_layer.crs().isGeographic():
                pixel_area = pixel_width * pixel_height * 111320.0 * 111320.0 # Extreme fallback
            else:
                pixel_area = pixel_width * pixel_height
        
        # Always compute the binary scientific statistics for the table and reports based on the threshold
        self.logger.debug("STEP: ClassificationEngine initialized")
        threshold_val = self.spnThreshold.value()
        classes = ClassificationEngine.classify(array, "Binary", nodata, breaks=[threshold_val], num_classes=2)
        results = self.statistics_engine.compute_class_areas(path, pixel_area, classes, 2)
        
        total_valid = results.get('class_0', {}).get('pixel_count', 0) + results.get('class_1', {}).get('pixel_count', 0)
        total_area_ha = results.get('class_0', {}).get('area_ha', 0) + results.get('class_1', {}).get('area_ha', 0)
        
        self.logger.info(f"DIAGNOSTIC: Valid pixels: {total_valid}\n"
                         f"DIAGNOSTIC: Negative Class pixels: {results.get('class_0', {}).get('pixel_count', 0)} (Area: {results.get('class_0', {}).get('area_ha', 0):.4f} Ha)\n"
                         f"DIAGNOSTIC: Positive Class pixels: {results.get('class_1', {}).get('pixel_count', 0)} (Area: {results.get('class_1', {}).get('area_ha', 0):.4f} Ha)\n"
                         f"DIAGNOSTIC: Total valid area: approximately {total_area_ha:.4f} Ha")
                         
        self.logger.debug("STEP: ROI Statistics populated")
        
        from PyQt6.QtWidgets import QTableWidgetItem
        self.tblStats.setRowCount(2)
        
        neg = self.current_metadata.negative_meaning
        pos = self.current_metadata.positive_meaning
        
        self.logger.debug("RUNTIME TRACE: ROI Statistics UI Update (Table rows):")
        self.logger.debug(f"Row 0: {neg} | {results.get('class_0', {}).get('pixel_count', 0)} | {results.get('class_0', {}).get('area_ha', 0):.2f}")
        self.logger.debug(f"Row 1: {pos} | {results.get('class_1', {}).get('pixel_count', 0)} | {results.get('class_1', {}).get('area_ha', 0):.2f}")
        
        self.logger.debug(f"RUNTIME VERIFY WIDGET: tblStats type={type(self.tblStats)} objectName={self.tblStats.objectName()} isVisible={self.tblStats.isVisible()}")
        
        c0_km2 = results.get("class_0", {}).get("area_ha", 0) / 100.0
        c1_km2 = results.get("class_1", {}).get("area_ha", 0) / 100.0
        
        self.tblStats.setItem(0, 0, QTableWidgetItem(neg))
        self.tblStats.setItem(0, 1, QTableWidgetItem(str(results.get("class_0", {}).get("pixel_count", 0))))
        self.tblStats.setItem(0, 2, QTableWidgetItem(f"{c0_km2:.2f}"))
        
        self.tblStats.setItem(1, 0, QTableWidgetItem(pos))
        self.tblStats.setItem(1, 1, QTableWidgetItem(str(results.get("class_1", {}).get("pixel_count", 0))))
        self.tblStats.setItem(1, 2, QTableWidgetItem(f"{c1_km2:.2f}"))
            
        # Execute Presentation Layer Pipeline
        try:
            context = self.build_report_context(results)
            context.validate()
            
            self.update_qa_tab(context)
            self.generate_scientific_report(context)
        except Exception as e:
            self.logger.error(f"Failed in Presentation Pipeline: {e}", exc_info=True)
            
    def build_report_context(self, class_results: dict):
        from ..models.analysis_report_context import AnalysisReportContext
        result = getattr(self, 'last_analysis_result', None)
        if not result:
            raise ValueError("No AnalysisResult found in state.")
            
        stats = self.statistics_engine.compute_base_statistics(self.current_layer.source())
        
        # Generate Histogram Base64
        histogram_b64 = None
        try:
            counts, edges = self.statistics_engine.compute_histogram(self.current_layer.source())
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import io
            import base64
            
            fig, ax = plt.subplots(figsize=(6, 4))
            # Edges is length N+1, counts is length N
            ax.hist(edges[:-1], bins=edges, weights=counts, color='#3B82F6', alpha=0.8, edgecolor='black')
            ax.set_title(f"{result.formula_name} Distribution", color='#FFFFFF')
            ax.set_xlabel(self.current_metadata.units)
            ax.set_ylabel("Pixel Frequency")
            ax.grid(axis='y', alpha=0.3)
            plt.tight_layout()
            
            buf = io.BytesIO()
            fig.savefig(buf, format='png', bbox_inches='tight', dpi=100)
            plt.close(fig)
            buf.seek(0)
            histogram_b64 = base64.b64encode(buf.read()).decode('utf-8')
        except Exception as e:
            self.logger.warning(f"Could not generate base64 histogram: {e}")
            
        context = AnalysisReportContext(
            formula_name=result.formula_name,
            formula_expression=result.formula_expression,
            dataset=result.dataset,
            satellite=result.satellite,
            provider=result.provider,
            processing_level=result.processing_level,
            crs=result.crs,
            resolution=result.metadata.get("actual_resolution", result.resolution),
            number_of_scenes=result.number_of_scenes,
            composite_method=result.composite_method,
            coverage_percent=result.coverage_percent,
            cloud_threshold=result.cloud_threshold,
            masks_applied=result.masks_applied,
            images_found=result.quality_metrics.get("Images Found", "Unknown"),
            images_used=result.number_of_scenes,
            execution_time_sec=result.execution_time_sec,
            processing_timestamp=result.processing_timestamp,
            stat_min=stats.get('min', 0.0),
            stat_max=stats.get('max', 0.0),
            stat_mean=stats.get('mean', 0.0),
            stat_median=stats.get('median', 0.0),
            stat_std=stats.get('std', 0.0),
            stat_valid_pixels=stats.get('valid_pixels', 0),
            classification_threshold=self.spnThreshold.value(),
            negative_meaning=self.current_metadata.negative_meaning,
            negative_pixel_count=class_results.get("class_0", {}).get("pixel_count", 0),
            negative_area_ha=class_results.get("class_0", {}).get("area_ha", 0.0),
            positive_meaning=self.current_metadata.positive_meaning,
            positive_pixel_count=class_results.get("class_1", {}).get("pixel_count", 0),
            positive_area_ha=class_results.get("class_1", {}).get("area_ha", 0.0),
            vis_stretch_min=self.spnMin.value(),
            vis_stretch_max=self.spnMax.value(),
            vis_palette=self.cmbPalette.currentText(),
            vis_classification_mode=self.cmbClassMode.currentText(),
            histogram_b64=histogram_b64,
            validation_failed=self.final_result.statistics.get("validation_failed", False) if hasattr(self, 'final_result') and self.final_result and self.final_result.statistics else False,
            scientific_reference=getattr(self.current_metadata, 'scientific_reference', "General Remote Sensing Literature"),
            vis_renderer_family=getattr(self.current_metadata, 'renderer_family', "continuous")
        )
        
        self.current_report_context = context
        return context
            
    def update_qa_tab(self, context):
        try:
            is_full_local = (context.provider == "Local Raster" and not context.masks_applied)
            
            if is_full_local:
                study_area_def = "Full Local Raster Extent"
                spatial_mask = "None — Full Raster"
                proc_mode = "Local Raster — Full Extent"
            else:
                study_area_def = "Custom AOI Polygon" if context.masks_applied else "Not Specified"
                spatial_mask = ", ".join(context.masks_applied) if context.masks_applied else "None"
                proc_mode = f"{context.provider} Analysis"

            if context.validation_failed:
                stats_title = "<b style='color:#DC2626;'>Diagnostic Statistics (SCIENTIFIC VALIDATION FAILED):</b>"
            else:
                stats_title = "<b>Local Image Statistics:</b>"

            qa_html = f"""
            <b>Study Area Definition:</b> {study_area_def}<br>
            <b>Spatial Mask:</b> {spatial_mask}<br>
            <b>Processing Mode:</b> {proc_mode}<br><br>
            <b>Images Found:</b> {context.get_images_found_display()}<br>
            <b>Images Used:</b> {context.get_images_used_display()}<br>
            <b>Coverage:</b> {context.coverage_percent}%<br><br>
            {stats_title}<br>
            - Min: {context.stat_min:.4f}<br>
            - Max: {context.stat_max:.4f}<br>
            - Mean: {context.stat_mean:.4f}<br>
            - Median: {context.stat_median:.4f}<br>
            - StdDev: {context.stat_std:.4f}<br>
            - Valid Pixels: {context.stat_valid_pixels}
            """
            
            self.logger.debug(f"RUNTIME TRACE: QA Tab Dict Context:\n"
                              f"Cloud Threshold: {context.cloud_threshold}\n"
                              f"QA HTML Content: {qa_html}")
            
            has_qa_cloud = hasattr(self, 'lblQaCloud')
            has_qa_details = hasattr(self, 'lblQaDetails')
            
            if has_qa_cloud: 
                self.lblQaCloud.setText(f'<b style="font-size:24pt; color:#059669;">{context.cloud_threshold}%</b> <span style="font-size:12pt;color:#B8C6D8;">Max Cloud Filter</span>')
            
            if has_qa_details:
                self.lblQaDetails.setText(qa_html)
                
        except Exception as e:
            self.logger.error(f"Failed to populate QA Tab: {e}", exc_info=True)
            
    def generate_scientific_report(self, context):
        if not hasattr(self, 'txtScientificReport'):
            return
            
        try:
            histogram_section = ""
            if context.histogram_b64:
                histogram_section = f"""
                <br>
                <b style="color: #D7E3F4;">Histogram:</b><br>
                <img src="data:image/png;base64,{context.histogram_b64}" width="500" style="border: 1px solid rgba(255, 255, 255, 0.1); margin-top: 10px;"/><br>
                """
                
            stats_title_report = "Base Raster Statistics"
            if context.validation_failed:
                stats_title_report = "Diagnostic Statistics (SCIENTIFIC VALIDATION FAILED)"

            report_html = f"""
            <h2 style="color: #111827; font-family: sans-serif;">Scientific Analysis Report</h2>
            <hr>
            
            <h3 style="color: #111827;">Executive Summary</h3>
            <p style="font-size: 11pt; line-height: 1.6; color: #374151;">
                {context.generate_narrative_summary()}
            </p>
            
            <h3 style="color: #111827;">Analysis Details</h3>
            <b style="color: #111827;">Formula:</b> <span style="color: #374151;">{context.formula_name} ({context.formula_expression})</span><br>
            <b style="color: #111827;">Scientific Reference:</b> <span style="color: #374151;">{context.scientific_reference}</span><br>
            <b style="color: #111827;">Dataset:</b> <span style="color: #374151;">{context.dataset} ({context.satellite})</span><br>
            <b style="color: #111827;">Provider:</b> <span style="color: #374151;">{context.provider}</span><br>
            <b style="color: #111827;">Processing Level:</b> <span style="color: #374151;">{context.processing_level}</span><br>
            <br>
            <b style="color: #111827;">Spatial & Temporal Parameters:</b><br>
            <span style="color: #374151;">- Projection (CRS): {context.crs}<br>
            - Requested Resolution: {self.last_analysis_result.metadata.get("requested_resolution", "Unknown") if hasattr(self, 'last_analysis_result') and self.last_analysis_result else "Unknown"}<br>
            - Actual Resolution: {context.resolution}<br>
            - Scenes Used: {context.number_of_scenes}<br>
            - Composite Method: {context.composite_method}<br>
            - Export Strategy: {self.last_analysis_result.export_strategy if hasattr(self, 'last_analysis_result') and self.last_analysis_result else "Unknown"}<br></span>
            <br>
            <b style="color: #111827;">Computed Area Statistics (Local Raster):</b><br>
            <span style="color: #374151;">- Total Valid Pixels: {context.stat_valid_pixels}<br>
            - {context.negative_meaning}: {context.negative_area_ha:,.2f} Ha ({context.negative_pixel_count} pixels)<br>
            - {context.positive_meaning}: {context.positive_area_ha:,.2f} Ha ({context.positive_pixel_count} pixels)<br></span>
            <br>
            <b style="color: #111827;">{stats_title_report}:</b><br>
            <span style="color: #374151;">- Minimum: {context.stat_min:.4f}<br>
            - Maximum: {context.stat_max:.4f}<br>
            - Mean: {context.stat_mean:.4f}<br></span>
            <br>
            <b style="color: #111827;">Visualization Settings:</b><br>
            <span style="color: #374151;">- Default Visualization: {context.vis_palette} Palette<br>
            - Color Stretch (Min/Max): [{context.vis_stretch_min}, {context.vis_stretch_max}]<br>
            - Palette: {context.vis_palette}<br>
            - Scientific Classification Threshold: {context.classification_threshold}<br>
            - Classification Mode: {context.vis_classification_mode}<br></span>
            {histogram_section}
            <br>
            <b style="color: #111827;">System:</b><br>
            <span style="color: #374151;">- Execution Time: {context.execution_time_sec}s<br>
            - Timestamp: {context.processing_timestamp}<br></span>
            """
            
            # Append detailed export diagnostics if available
            if hasattr(self, 'last_analysis_result') and self.last_analysis_result:
                qm = self.last_analysis_result.quality_metrics
                if qm.get("Generated Tiles"):
                    diagnostics_html = f"""
                    <br>
                    <b style="color: #111827;">Tiled Export Diagnostics:</b><br>
                    <span style="color: #374151;">- Estimated Export Size: {qm.get('Estimated MB', 0):.2f} MB<br>
                    - Target Tile Size: {qm.get('Target Tile Size MB', 20.0):.2f} MB<br>
                    - Generated Tiles: {qm.get('Generated Tiles', 0)}<br>
                    - Total Download Size: {qm.get('Total Download Size (MB)', 0)} MB<br>
                    - Average Tile Size: {qm.get('Average Tile Size (MB)', 0)} MB<br>
                    - Parallel Workers Used: {qm.get('Parallel Workers Used', 1)}<br>
                    - Total URL Generation Time: {qm.get('Total URL Generation Time', 0)} s<br>
                    - Average URL Generation Time: {qm.get('Average URL Generation Time', 0)} s<br>
                    - Average Download Time per Tile: {qm.get('Average Download Time per Tile', 0)} s<br>
                    - Fastest Tile: {qm.get('Fastest Tile', 0)} s<br>
                    - Slowest Tile: {qm.get('Slowest Tile', 0)} s<br>
                    - Retry Count: {qm.get('Retry Count', 0)}<br></span>
                    """
                    
                    if "tile_history" in qm:
                        url_metrics = qm.get("tile_url_metrics", {})
                        diagnostics_html += "<br><b style='color: #111827;'>Tile Balance Breakdown:</b><br><span style='color: #374151;'>"
                        for tile in qm["tile_history"]:
                            tid = tile['tile_id']
                            worker = tile['worker']
                            size = tile['size_mb']
                            dl_dur = tile['duration']
                            retries = tile['retries']
                            
                            u_metric = url_metrics.get(tid, {})
                            url_dur = u_metric.get('url_duration', 0)
                            
                            diagnostics_html += f"- {worker} &rarr; Tile {tid} : {size:.2f} MB : {url_dur:.1f} s URL Gen : {dl_dur:.1f} s Download (Retries: {retries})<br>"
                        diagnostics_html += "</span>"
                            
                    report_html += diagnostics_html
            
            self.logger.debug(f"RUNTIME TRACE: Scientific Report Context successfully generated (Length: {len(report_html)})")
            
            has_txt_report = hasattr(self, 'txtScientificReport')
            if has_txt_report:
                self.txtScientificReport.setHtml(report_html)
        except Exception as e:
            self.logger.error(f"Failed generating Scientific Report: {e}", exc_info=True)

    def toggle_inspector(self, checked):
        self.logger.info(f"Toggle clicked -> toggle_inspector entered with checked={checked}")
        if not hasattr(self, 'pixel_inspector_session') or not self.pixel_inspector_session:
            self.logger.warning("Cannot toggle inspector: pixel_inspector_session is not initialized.")
            return
            
        def is_valid_raster(l: Any) -> bool:
            return l is not None and getattr(l, "isValid", lambda: False)() and ("Raster" in type(l).__name__ or hasattr(l, "rasterUnitsPerPixelX") or hasattr(l, "bandCount"))

        if checked:
            target_layer = getattr(self, 'current_layer', None)
            if not is_valid_raster(target_layer):
                if self.iface and hasattr(self.iface, 'activeLayer') and is_valid_raster(self.iface.activeLayer()):
                    target_layer = self.iface.activeLayer()
                    self.current_layer = target_layer
                elif QgsProject and hasattr(QgsProject, "instance"):
                    try:
                        for l in QgsProject.instance().mapLayers().values():
                            if is_valid_raster(l):
                                target_layer = l
                                self.current_layer = target_layer
                                break
                    except Exception:
                        pass

            if is_valid_raster(target_layer):
                success = self.pixel_inspector_session.start(target_layer)
                if not success:
                    self.btnInspect.blockSignals(True)
                    self.btnInspect.setChecked(False)
                    self.btnInspect.blockSignals(False)
                    if self.iface and hasattr(self.iface, 'messageBar') and self.iface.messageBar():
                        try: self.iface.messageBar().pushMessage("Pixel Inspector", "Failed to activate map tool in QGIS canvas.", level=getattr(Qgis, "Warning", getattr(Qgis.MessageLevel, "Warning", 1)), duration=4)
                        except Exception: pass
                else:
                    if self.iface and hasattr(self.iface, 'messageBar') and self.iface.messageBar():
                        try: self.iface.messageBar().pushMessage("Pixel Inspector", f"Active on layer '{getattr(target_layer, 'name', lambda: 'Raster')()}'! Click on any point on the map canvas to inspect.", level=getattr(Qgis, "Info", getattr(Qgis.MessageLevel, "Info", 0)), duration=5)
                        except Exception: pass
            else:
                self.logger.warning("No active raster layer available for pixel inspection.")
                self.btnInspect.blockSignals(True)
                self.btnInspect.setChecked(False)
                self.btnInspect.blockSignals(False)
                if self.iface and hasattr(self.iface, 'messageBar') and self.iface.messageBar():
                    try: self.iface.messageBar().pushMessage("Pixel Inspector", "Please select or generate a raster layer in QGIS before toggling Pixel Inspector.", level=getattr(Qgis, "Warning", getattr(Qgis.MessageLevel, "Warning", 1)), duration=5)
                    except Exception: pass
        else:
            self.deactivate_pixel_inspector()
            if self.iface and hasattr(self.iface, 'messageBar') and self.iface.messageBar():
                try: self.iface.messageBar().pushMessage("Pixel Inspector", "Deactivated.", level=getattr(Qgis, "Info", getattr(Qgis.MessageLevel, "Info", 0)), duration=2)
                except Exception: pass

    def on_pixel_inspected(self, data):
        """Routes pixel inspection events directly to the authoritative PixelInspectorSession controller."""
        if hasattr(self, 'pixel_inspector_session') and self.pixel_inspector_session:
            self.pixel_inspector_session.inspect(data)

    def save_session_state(self):
        state = {
            "Palette": self.cmbPalette.currentText(),
            "Classification Method": self.cmbClassMode.currentText(),
            "Display Range": [self.spnMin.value(), self.spnMax.value()],
            "Threshold": self.spnThreshold.value()
        }
        self.symbology_manager.save_session_state(state)

    def deactivate_pixel_inspector(self, *args: Any) -> None:
        """
        Centralized lifecycle cleanup routing to the authoritative PixelInspectorSession controller.
        Executes uniform shutdown across all exit triggers without memory leaks or orphaned objects.
        """
        if hasattr(self, 'pixel_inspector_session') and self.pixel_inspector_session:
            self.pixel_inspector_session.close(*args)

    def _on_project_layers_removed(self, layers: Any) -> None:
        """Monitors layer removals and deactivates inspection session if target raster is unloaded."""
        if hasattr(self, 'pixel_inspector_session') and self.pixel_inspector_session:
            self.pixel_inspector_session._on_layers_removed(layers)

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        from PyQt6.QtCore import QTimer
        def on_paint_done():
            try:
                from ..utils.timing_profiler import TimingProfiler
                TimingProfiler.get_instance().record("T11", "First post-show paint (QTimer 0)")
            except Exception:
                pass
        QTimer.singleShot(0, on_paint_done)

    def closeEvent(self, event: Any) -> None:
        """Handles window close attempts (titlebar X button) without disrupting active map inspection tools."""
        try:
            self.save_session_state()
        except Exception:
            pass
        if hasattr(event, "accept"):
            event.accept()

    def _log_geometry(self, state_name):
        try:
            import logging
            log = logging.getLogger("GeometryDiag")
            if not log.handlers:
                log.setLevel(logging.INFO)
                ch = logging.StreamHandler()
                ch.setFormatter(logging.Formatter('%(message)s'))
                log.addHandler(ch)
                
            log.info(f"\\n[RSS GEOM] STATE={state_name}")
            
            log.info(f"MainDialog:")
            log.info(f"  size: {self.size().width()}x{self.size().height()}")
            log.info(f"  minimumSize: {self.minimumSize().width()}x{self.minimumSize().height()}")
            log.info(f"  maximumSize: {self.maximumSize().width()}x{self.maximumSize().height()}")
            
            if hasattr(self, 'tabResults'):
                log.info(f"Results Maps:")
                log.info(f"  geometry: {self.tabResults.geometry().getRect()}")
                log.info(f"  size: {self.tabResults.size().width()}x{self.tabResults.size().height()}")
            
            if hasattr(self, '_vis_ctrl_group'):
                cg = self._vis_ctrl_group
                log.info(f"Visualization Settings (ctrl_group):")
                log.info(f"  geometry: {cg.geometry().getRect()}")
                log.info(f"  size: {cg.size().width()}x{cg.size().height()}")
                log.info(f"  sizeHint: {cg.sizeHint().width()}x{cg.sizeHint().height()}")
                log.info(f"  minimumSizeHint: {cg.minimumSizeHint().width()}x{cg.minimumSizeHint().height()}")
                log.info(f"  minimumSize: {cg.minimumSize().width()}x{cg.minimumSize().height()}")
                log.info(f"  contentsMargins: {cg.contentsMargins().left()}, {cg.contentsMargins().top()}, {cg.contentsMargins().right()}, {cg.contentsMargins().bottom()}")
                if cg.layout():
                    log.info(f"  layout margins: {cg.layout().contentsMargins().left()}, {cg.layout().contentsMargins().top()}, {cg.layout().contentsMargins().right()}, {cg.layout().contentsMargins().bottom()}")
                    log.info(f"  layout spacing: {cg.layout().spacing()}")
                log.info(f"  styleSheet: {cg.styleSheet()[:100]}...")
                log.info(f"  font: pointSize={cg.font().pointSize()}, pixelSize={cg.font().pixelSize()}")

            if hasattr(self, '_vis_right_group'):
                rg = self._vis_right_group
                log.info(f"ROI Statistics (right_group):")
                log.info(f"  geometry: {rg.geometry().getRect()}")
                log.info(f"  size: {rg.size().width()}x{rg.size().height()}")

            if hasattr(self, '_vis_splitter'):
                sp = self._vis_splitter
                log.info(f"Splitter:")
                log.info(f"  size: {sp.size().width()}x{sp.size().height()}")
                log.info(f"  sizes(): {sp.sizes()}")
                
            controls = [
                ('Palette', getattr(self, 'cmbPalette', None)),
                ('Classification', getattr(self, 'cmbClassMode', None)),
                ('Display Range (Layout)', getattr(self, '_vis_range_lay', None)),
                ('Display Range (spnMin)', getattr(self, 'spnMin', None)),
                ('Threshold', getattr(self, 'spnThreshold', None))
            ]
            for name, widget in controls:
                if widget:
                    log.info(f"{name} Control:")
                    if hasattr(widget, 'geometry'):
                        log.info(f"  geometry: {widget.geometry().getRect()}")
                    if hasattr(widget, 'sizeHint'):
                        log.info(f"  sizeHint: {widget.sizeHint().width()}x{widget.sizeHint().height()}")
                    if hasattr(widget, 'minimumSizeHint'):
                        log.info(f"  minimumSizeHint: {widget.minimumSizeHint().width()}x{widget.minimumSizeHint().height()}")
                    if hasattr(widget, 'minimumWidth'):
                        log.info(f"  minimumWidth: {widget.minimumWidth()}")
                    if hasattr(widget, 'minimumHeight'):
                        log.info(f"  minimumHeight: {widget.minimumHeight()}")
                    if hasattr(widget, 'sizePolicy'):
                        sp = widget.sizePolicy()
                        log.info(f"  sizePolicy: H={sp.horizontalPolicy().name}, V={sp.verticalPolicy().name}")
            
        except Exception as e:
            print("LOG GEOM ERROR:", e)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, '_geom_log_enabled', False):
            self._log_geometry("RESIZE")

    def changeEvent(self, event):
        super().changeEvent(event)
        from PyQt6.QtCore import QEvent, Qt
        if event.type() == QEvent.Type.WindowStateChange and getattr(self, '_geom_log_enabled', False):
            state = self.windowState()
            if state & Qt.WindowState.WindowMaximized:
                self._log_geometry("MAXIMIZED")
            elif state == Qt.WindowState.WindowNoState:
                self._log_geometry("RESTORED")

    def reject(self) -> None:
        """Handles dialog rejection to save state and dismiss UI without disrupting active map inspection tools."""
        try:
            self.save_session_state()
        except Exception:
            pass
        super().reject()

    def keyPressEvent(self, event: Any) -> None:
        """Captures ESC key press across the main dialog to cancel an active Pixel Inspector session."""
        if hasattr(event, "key") and event.key() == Qt.Key.Key_Escape and hasattr(self, 'btnInspect') and self.btnInspect.isChecked():
            self.deactivate_pixel_inspector()
            if hasattr(event, "accept"):
                event.accept()
        else:
            super().keyPressEvent(event)
