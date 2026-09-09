"""
Welcome Dialog Controller Module.
"""
import os
from PyQt6.QtWidgets import QDialog
from PyQt6 import uic

from .login_dialog import LoginDialog
from ..services.connection_service import ConnectionService

UI_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "welcome_dialog.ui")

class WelcomeDialog(QDialog):
    """
    Controller class for the Welcome Dialog.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        print("\n--- WelcomeDialog __init__ START ---")
        uic.loadUi(UI_PATH, self)
        
        # Load hero image dynamically
        if hasattr(self, 'lblHeroImage'):
            print(f"__init__: lblHeroImage found. objectName={self.lblHeroImage.objectName()}, address={hex(id(self.lblHeroImage))}")
            from PyQt6.QtGui import QPixmap
            img_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "pics", "welcome_hero.png")
            self._original_hero_pixmap = None
            if os.path.exists(img_path):
                pixmap = QPixmap(img_path)
                print(f"__init__: Loaded welcome_hero.png, original size={pixmap.width()}x{pixmap.height()}")
                pixmap.setDevicePixelRatio(self.devicePixelRatioF())
                self._original_hero_pixmap = pixmap
                
                print(f"__init__: Calling setScaledContents(False)")
                self.lblHeroImage.setScaledContents(False)
                from PyQt6.QtCore import Qt
                self.lblHeroImage.setAlignment(Qt.AlignmentFlag.AlignCenter)
                print(f"__init__: Calling update_hero_image()")
                self.update_hero_image()
        
        self.connection_service = ConnectionService.get_instance()
        
        # Apply custom styling (Data/Local provider: Blue)
        if hasattr(self, 'rbGEE') and hasattr(self, 'rbLocal'):
            from ..utils.helpers import apply_custom_radio_style
            apply_custom_radio_style([self.rbGEE, self.rbLocal], accent_color="#3B82F6", hover_color="#60A5FA")
            
        if hasattr(self, 'btnContinue'):
            self.btnContinue.clicked.connect(self.on_continue)
            
        if hasattr(self, 'btnContactSupport'):
            self.btnContactSupport.clicked.connect(self.on_contact_support)
            
        if hasattr(self, 'btnWebDemo'):
            self.btnWebDemo.clicked.connect(self.on_web_demo)
            
        print("--- WelcomeDialog __init__ END ---\n")

    def on_contact_support(self):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl("https://tally.so/r/9qAzW1"))

    def on_web_demo(self):
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        from ..config import WEB_DEMO_URL
        QDesktopServices.openUrl(QUrl(WEB_DEMO_URL))

    def resizeEvent(self, event):
        print(f"resizeEvent: new size={event.size().width()}x{event.size().height()}")
        super().resizeEvent(event)
        self.update_hero_image()

    def showEvent(self, event):
        print("showEvent: Dialog is becoming visible.")
        super().showEvent(event)
        self.update_hero_image()

    def update_hero_image(self):
        print("update_hero_image: START")
        if hasattr(self, 'lblHeroImage') and getattr(self, '_original_hero_pixmap', None) is not None:
            from PyQt6.QtCore import Qt
            size = self.lblHeroImage.size()
            
            print(f"  lblHeroImage stats -> size={size.width()}x{size.height()}, "
                  f"geometry={self.lblHeroImage.geometry()}, "
                  f"minSize={self.lblHeroImage.minimumSize().width()}x{self.lblHeroImage.minimumSize().height()}, "
                  f"maxSize={self.lblHeroImage.maximumSize().width()}x{self.lblHeroImage.maximumSize().height()}, "
                  f"scaledContents={self.lblHeroImage.hasScaledContents()}")
                  
            if size.width() > 0 and size.height() > 0:
                dpr = self.devicePixelRatioF()
                
                # Target 90% of the container size, converted to device pixels for High-DPI
                target_w = int(size.width() * dpr * 0.90)
                target_h = int(size.height() * dpr * 0.90)
                
                print(f"  target device pixels for scaling -> {target_w}x{target_h} (dpr={dpr})")
                if target_w > 0 and target_h > 0:
                    scaled_pixmap = self._original_hero_pixmap.scaled(
                        target_w, target_h,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    scaled_pixmap.setDevicePixelRatio(dpr)
                    print(f"  Calling setPixmap with scaled pixmap size={scaled_pixmap.width()}x{scaled_pixmap.height()}")
                    self.lblHeroImage.setPixmap(scaled_pixmap)
                    print(f"  lblHeroImage pixmap().size() = {self.lblHeroImage.pixmap().size().width()}x{self.lblHeroImage.pixmap().size().height()}")
        print("update_hero_image: END\n")

    def on_continue(self):
        try:
            from ..utils.timing_profiler import TimingProfiler
            TimingProfiler.get_instance().record("T0", "Continue clicked / on_continue entry")
        except Exception:
            pass

        if hasattr(self, 'rbGEE') and self.rbGEE.isChecked():
            self.connection_service.set_current_provider("Google Earth Engine")
            # We no longer perform synchronous check_saved_connection() here.
            # We only check if credentials exist locally (instant) to determine if login is needed.
            # Actual EE initialization is deferred to the MainDialog background worker.
            if self.connection_service.is_authenticated():
                try:
                    from ..utils.timing_profiler import TimingProfiler
                    TimingProfiler.get_instance().record("T1", "WelcomeDialog.accept() called (Authenticated)")
                except Exception:
                    pass
                self.accept()
            else:
                dialog = LoginDialog(self)
                dialog.exec()
                # If they successfully logged in, accept
                if self.connection_service.is_authenticated():
                    try:
                        from ..utils.timing_profiler import TimingProfiler
                        TimingProfiler.get_instance().record("T1", "WelcomeDialog.accept() called (After Login)")
                    except Exception:
                        pass
                    self.accept()
        else:
            self.connection_service.set_current_provider("Local Raster")
            self.accept()
