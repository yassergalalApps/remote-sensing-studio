"""
Main plugin module.
Handles initialization, UI integration (menus, toolbars), and unloading of the plugin.
"""
import os
from PyQt6.QtWidgets import QMessageBox, QDialog
from PyQt6.QtGui import QIcon, QAction

from .gui.welcome_dialog import WelcomeDialog
from .gui.main_dialog import MainDialog
from .utils.logger import get_logger

class RemoteSensingStudioPlugin:
    """
    Main plugin class for Remote Sensing Studio.
    """
    
    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.logger = get_logger(__name__)
        self.actions = []
        self.menu = "&Remote Sensing Studio"
        self.toolbar = self.iface.addToolBar("Remote Sensing Studio")
        self.toolbar.setObjectName("RemoteSensingStudioToolBar")
        
        self.main_dialog = None
        self.welcome_dialog = None
        
        # Ensure RemoteSensingStudio root logger has QgsLogHandler attached
        get_logger("RemoteSensingStudio")
        self.logger.info("Plugin initialized.")
        
    def initGui(self):
        try:
            icon_path = os.path.join(self.plugin_dir, "icons", "plugin_icon.png")
            icon = QIcon(icon_path)
            
            action = QAction(icon, "Remote Sensing Studio", self.iface.mainWindow())
            action.setObjectName("RemoteSensingStudioAction")
            action.setWhatsThis("Launch Remote Sensing Studio")
            action.setStatusTip("Launch Remote Sensing Studio")
            action.triggered.connect(self.run)
            
            self.iface.addPluginToMenu(self.menu, action)
            self.toolbar.addAction(action)
            self.actions.append(action)
            
            self.logger.info("GUI initialized successfully.")
        except Exception as e:
            self.logger.error(f"Error during initGui: {e}", exc_info=True)
        
    def unload(self):
        try:
            if self.main_dialog:
                if hasattr(self.main_dialog, 'pixel_inspector_session') and self.main_dialog.pixel_inspector_session:
                    self.main_dialog.pixel_inspector_session.destroy()
                elif hasattr(self.main_dialog, 'deactivate_pixel_inspector'):
                    self.main_dialog.deactivate_pixel_inspector()
                
                if hasattr(self.main_dialog, 'stop_workers'):
                    self.main_dialog.stop_workers()
                    
            for action in self.actions:
                self.iface.removePluginMenu(self.menu, action)
                self.toolbar.removeAction(action)
            del self.actions[:]
            
            # Remove custom toolbar from main window
            if self.toolbar:
                self.iface.mainWindow().removeToolBar(self.toolbar)
                del self.toolbar
                
            self.logger.info("Plugin unloaded.")
        except Exception as e:
            self.logger.error(f"Error unloading plugin: {e}", exc_info=True)
        
    def run(self):
        self.logger.info("Running plugin...")
        try:
            if not self.welcome_dialog:
                self.welcome_dialog = WelcomeDialog(self.iface.mainWindow())
            
            result = self.welcome_dialog.exec()
            
            if result == 1 or result == int(QDialog.DialogCode.Accepted):
                try:
                    from .utils.timing_profiler import TimingProfiler
                    TimingProfiler.get_instance().record("T2", "remote_sensing_studio.run() resumes")
                except Exception:
                    pass
                
                if not self.main_dialog:
                    try:
                        from .utils.timing_profiler import TimingProfiler
                        TimingProfiler.get_instance().record("T3", "MainDialog construction starts")
                    except Exception:
                        pass
                    self.main_dialog = MainDialog(self.iface, self.iface.mainWindow())
                else:
                    self.main_dialog._current_workspace_id = None
                    self.main_dialog.apply_provider_state()
                    
                # Explicitly establish startup tab as Dashboard (index 0) immediately before showing
                if hasattr(self.main_dialog, 'tabWidget'):
                    self.main_dialog.tabWidget.setCurrentIndex(0)
                    
                try:
                    from .utils.timing_profiler import TimingProfiler
                    TimingProfiler.get_instance().record("T10", "MainDialog.show() called")
                except Exception:
                    pass
                self.main_dialog.show()
                self.main_dialog.raise_()
                self.main_dialog.activateWindow()
        except Exception as e:
            self.logger.error(f"Error launching plugin: {e}", exc_info=True)
            QMessageBox.critical(self.iface.mainWindow(), "Error", f"Could not launch plugin:\n{e}")
