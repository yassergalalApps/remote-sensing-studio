"""
Login Dialog Controller Module.
"""
import os
from PyQt6.QtWidgets import QDialog, QMessageBox
from PyQt6 import uic
from PyQt6.QtCore import QThread, pyqtSignal

from ..services.connection_service import ConnectionService

UI_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "login_dialog.ui")

class AuthWorker(QThread):
    finished = pyqtSignal(bool, str)
    
    def __init__(self, action, connection_service, parent=None):
        super().__init__(parent)
        self.action = action
        self.connection_service = connection_service
        
    def run(self):
        if self.action == "login":
            success, msg = self.connection_service.login_gee()
        else:
            success, msg = self.connection_service.logout_gee()
        self.finished.emit(success, msg)

class LogoutWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, connection_service, parent=None):
        super().__init__(parent)
        self.connection_service = connection_service

    def run(self):
        import logging
        logger = logging.getLogger(__name__)
        try:
            logger.info("[AUTH DEBUG] LogoutWorker.run() entered")
            logger.info("[AUTH DEBUG] Calling ConnectionService.logout_gee()")
            success, message = self.connection_service.logout_gee()
            logger.info(f"[AUTH DEBUG] ConnectionService.logout_gee() completed: {success}, {message}")
            logger.info("[AUTH DEBUG] LogoutWorker emitting finished")
            self.finished.emit(success, message)
        except Exception as e:
            logger.exception("[AUTH DEBUG] LogoutWorker failed")
            self.finished.emit(False, str(e))

class DiscoveryWorker(QThread):
    finished = pyqtSignal(list, str)
    
    def __init__(self, connection_service, parent=None):
        super().__init__(parent)
        self.connection_service = connection_service
        
    def run(self):
        projects, err = self.connection_service.discover_projects()
        self.finished.emit(projects, err)

class TestConnectionWorker(QThread):
    finished = pyqtSignal(bool, str, str)
    
    def __init__(self, connection_service, project_id, parent=None):
        super().__init__(parent)
        self.connection_service = connection_service
        self.project_id = project_id
        
    def run(self):
        success, msg = self.connection_service.test_and_set_project(self.project_id)
        self.finished.emit(success, msg, self.project_id)


class LoginDialog(QDialog):
    """
    Controller class for the Earth Engine Login Dialog.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        uic.loadUi(UI_PATH, self)
        
        self.connection_service = ConnectionService.get_instance()
        
        if hasattr(self, 'btnSignIn'):
            self.btnSignIn.clicked.connect(self.on_login_clicked)
        if hasattr(self, 'btnSwitchAccount'):
            self.btnSwitchAccount.clicked.connect(self.on_switch_account_clicked)
        if hasattr(self, 'btnTestConnection'):
            self.btnTestConnection.clicked.connect(self.on_test_connection_clicked)
        if hasattr(self, 'btnRefreshProjects'):
            self.btnRefreshProjects.clicked.connect(self.on_refresh_clicked)
        if hasattr(self, 'btnCancel'):
            self.btnCancel.clicked.connect(self.reject)
        if hasattr(self, 'btnContinue'):
            self.btnContinue.clicked.connect(self.accept)
            
        if hasattr(self, 'txtDiscoveryError'):
            self.txtDiscoveryError.setVisible(False)
            
        self._discovered_projects = []
        self._active_workers = []
        self._is_closing = False
        self._discovery_attempted = False
        self._manual_project_input = False
        
        from PyQt6.QtWidgets import QPushButton
        self.btnWebAssist = QPushButton("View My Earth Engine Projects")
        self.btnWebAssist.setStyleSheet("background-color: #2B6CB0; color: white; font-weight: bold; border-radius: 4px; padding: 8px;")
        self.btnWebAssist.setVisible(False)
        from PyQt6.QtCore import Qt
        self.btnWebAssist.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btnWebAssist.clicked.connect(lambda: __import__('webbrowser').open("https://console.cloud.google.com/projectselector2/home/dashboard"))
        
        if hasattr(self, 'statusGroupBox'):
            layout = self.statusGroupBox.layout()
            if layout:
                layout.addWidget(self.btnWebAssist, 6, 0, 1, 2)
        
        self.refresh_status()
        
    def showEvent(self, event):
        super().showEvent(event)
        if self.property("auto_start_auth"):
            self.setProperty("auto_start_auth", False) # Run only once
            # If they are authenticated, we don't need to sign out first because force=True will just
            # overwrite the token with a new OAuth flow anyway, but to be strictly safe and clear the state,
            # we should just trigger the login flow.
            # However, on_login_clicked signs OUT if authenticated.
            # So if we want to force re-auth without explicitly signing out, we can just run AuthWorker directly,
            # or we can force the state to be unauthenticated before calling on_login_clicked.
            # The safest supported path without breaking the UX is to just trigger the AuthWorker directly for login.
            import logging
            logger = logging.getLogger(__name__)
            logger.info("[AUTH DEBUG] Terminating current session before Switch Account")
            self.connection_service.logout_gee()
            logger.info("[AUTH DEBUG] Creating AuthWorker for login")
            from PyQt6.QtWidgets import QApplication
            if hasattr(self, 'btnSignIn'):
                self.btnSignIn.setText("⏳ Authenticating...")
            if hasattr(self, 'lblStatus'):
                self.lblStatus.setText('<font color="#D97706"><b>⏳ Authenticating with Google...</b></font>')
            QApplication.processEvents()
            
            worker = AuthWorker("login", self.connection_service, parent=None)
            self._register_worker(worker, self._on_login_finished)
            
    def on_switch_account_clicked(self):
        import logging
        logger = logging.getLogger(__name__)
        logger.info("[AUTH DEBUG] Switch Account clicked")
        
        from PyQt6.QtWidgets import QApplication
        if hasattr(self, 'btnSwitchAccount'):
            self.btnSwitchAccount.setEnabled(False)
        if hasattr(self, 'btnSignIn'):
            self.btnSignIn.setText("⏳ Authenticating...")
        if hasattr(self, 'lblStatus'):
            self.lblStatus.setText('<font color="#D97706"><b>⏳ Switching Account...</b></font>')
        QApplication.processEvents()
        
        worker = AuthWorker("login", self.connection_service, parent=None)
        self._register_worker(worker, self._on_login_finished)
        
    def _register_worker(self, worker, slot):
        """
        Safely registers a worker to ensure its QThread isn't garbage collected
        prematurely, and hooks up deterministic lifecycle signals.
        """
        # Store the slot so we can disconnect exactly this slot later
        worker._gui_slot = slot
        self._active_workers.append(worker)
        
        if slot:
            worker.finished.connect(slot)
            
        # Register an internal cleanup slot to remove it from tracking
        worker.finished.connect(self._on_worker_finished_cleanup)
        # Ensure the underlying C++ thread cleans itself up safely
        worker.finished.connect(worker.deleteLater)
        
        worker.start()
        
    def _on_worker_finished_cleanup(self):
        """
        Internal cleanup. Safely removes the finished worker from the
        active tracking list to avoid memory leaks.
        """
        worker = self.sender()
        if worker in self._active_workers:
            self._active_workers.remove(worker)
            
    def _disconnect_workers(self):
        """
        Safely disconnects GUI callbacks from running background workers
        so they don't crash when the dialog closes.
        """
        self._is_closing = True
        for worker in list(self._active_workers):
            try:
                gui_slot = getattr(worker, '_gui_slot', None)
                if gui_slot:
                    worker.finished.disconnect(gui_slot)
            except (TypeError, RuntimeError):
                pass
            
            try:
                # Also disconnect the internal list-cleanup to avoid touching self
                worker.finished.disconnect(self._on_worker_finished_cleanup)
            except (TypeError, RuntimeError):
                pass
                
        self._active_workers.clear()
        
    def on_refresh_clicked(self):
        self._populate_projects()
        self.refresh_status()
        
    def _populate_projects(self):
        """Populate the project combo box with discovered projects asynchronously."""
        if not self.connection_service.is_authenticated():
            return
            
        self._discovery_attempted = True
        
        if hasattr(self, 'lblStatus'):
            self.lblStatus.setText('<font color="#D97706"><b>● Discovering Earth Engine projects...</b></font>')
            
        if hasattr(self, 'btnSignIn'): self.btnSignIn.setEnabled(False)
        if hasattr(self, 'btnRefreshProjects'): self.btnRefreshProjects.setEnabled(False)
        if hasattr(self, 'btnContinue'): self.btnContinue.setEnabled(False)
        
        if hasattr(self, 'cmbProject'):
            self.cmbProject.setEnabled(True)
            self.cmbProject.setEditable(True)
            self.cmbProject.editTextChanged.connect(self.on_project_text_edited)
        
        if hasattr(self, 'btnTestConnection'): self.btnTestConnection.setEnabled(True)
        if hasattr(self, 'btnWebAssist'): self.btnWebAssist.setVisible(True)
        
        # State: DISCOVERING_PROJECTS
        worker = DiscoveryWorker(self.connection_service, parent=None)
        self._register_worker(worker, self._on_discovery_finished)

    def on_project_text_edited(self, text):
        """Record that the user manually edited the project ID to avoid overwriting it during discovery."""
        if text.strip():
            self._manual_project_input = True

    def on_web_assist_clicked(self):
        import webbrowser
        webbrowser.open("https://console.cloud.google.com/projectselector2/home/dashboard")
    def _on_discovery_finished(self, projects, error_msg):
        if self._is_closing: return
        
        self._discovered_projects = projects
        self._discovery_error = error_msg
        self._discovery_attempted = True
        
        if hasattr(self, 'cmbProject'):
            if not self._manual_project_input:
                self.cmbProject.clear()
                
                if error_msg in ("SERVICE_DISABLED", "PROJECT_DISCOVERY_UNAVAILABLE"):
                    self.cmbProject.setEditable(True)
                    history = self.connection_service.get_saved_projects()
                    for p in history:
                        self.cmbProject.addItem(p, userData=p)
                    self.cmbProject.lineEdit().setPlaceholderText("Enter your Project ID (e.g. ee-myproject)")
                else:
                    # Keep it editable so user can always manually override
                    self.cmbProject.setEditable(True)
                    for p in projects:
                        display_name = f"{p['name']} ({p['id']})" if p['name'] != p['id'] else p['id']
                        self.cmbProject.addItem(display_name, userData=p['id'])
                
            active = self.connection_service.get_active_project()
            if active and not self._manual_project_input:
                if self.cmbProject.isEditable():
                    self.cmbProject.setCurrentText(active)
                else:
                    for i in range(self.cmbProject.count()):
                        if self.cmbProject.itemData(i) == active:
                            self.cmbProject.setCurrentIndex(i)
                            break
            elif self._manual_project_input and projects:
                # Add discovered projects passively to the dropdown without changing current text
                current_text = self.cmbProject.currentText()
                # Store existing items to avoid duplicates
                existing_items = [self.cmbProject.itemText(i) for i in range(self.cmbProject.count())]
                for p in projects:
                    display_name = f"{p['name']} ({p['id']})" if p['name'] != p['id'] else p['id']
                    if display_name not in existing_items:
                        self.cmbProject.addItem(display_name, userData=p['id'])
                # Restore the user's manual text
                self.cmbProject.setCurrentText(current_text)
                        
        if hasattr(self, 'btnSignIn'):
            self.btnSignIn.setEnabled(True)
            
        self.refresh_status()

    def refresh_status(self):
        """Update UI based on current status."""
        if self._is_closing: return
        
        gee_status = self.connection_service.get_gee_status()
        has_cred = gee_status.get('has_credentials', False)
        connected = gee_status.get('connected', False)
        active_proj = gee_status.get('project', '')
        
        if not has_cred:
            if hasattr(self, 'lblUser'):
                self.lblUser.setText('<font color="#D97706"><b>Not Authenticated</b></font>')
            if hasattr(self, 'btnSignIn'):
                self.btnSignIn.setText("Sign in with Google")
            if hasattr(self, 'btnSwitchAccount'):
                self.btnSwitchAccount.setVisible(False)
            if hasattr(self, 'lblStatus'):
                self.lblStatus.setText('<font color="#D97706"><b>● Not Connected</b></font>')
            if hasattr(self, 'cmbProject'): self.cmbProject.setEnabled(False)
            if hasattr(self, 'btnTestConnection'): self.btnTestConnection.setEnabled(False)
            if hasattr(self, 'btnRefreshProjects'): self.btnRefreshProjects.setEnabled(False)
            if hasattr(self, 'btnContinue'): self.btnContinue.setEnabled(False)
            if hasattr(self, 'btnWebAssist'): self.btnWebAssist.setVisible(False)
            if hasattr(self, 'lblProjectHelp'):
                self.lblProjectHelp.setText('<small>Sign in to select a project.</small>')
                
        else:
            # We are authenticated, so ensure projects are populated if we haven't yet
            if not self._discovery_attempted and not self._discovered_projects and hasattr(self, 'cmbProject') and self.cmbProject.count() == 0:
                self._populate_projects()
                
            account = gee_status.get("account", "Google account authenticated")
            if "@" in account:
                account_html = f'<a href="mailto:{account}">{account}</a>'
            else:
                account_html = account
                
            if hasattr(self, 'lblUser'):
                self.lblUser.setText(f'<font color="#059669"><b>{account_html}</b></font>')
            if hasattr(self, 'btnSignIn'):
                self.btnSignIn.setText("Sign Out")
            if hasattr(self, 'btnSwitchAccount'):
                self.btnSwitchAccount.setVisible(True)
            if hasattr(self, 'btnRefreshProjects'):
                self.btnRefreshProjects.setEnabled(True)
                
            # The logic strictly isolates connection success from discovery success
            if connected:
                if hasattr(self, 'cmbProject'): self.cmbProject.setEnabled(True)
                if hasattr(self, 'btnTestConnection'): self.btnTestConnection.setEnabled(True)
                if hasattr(self, 'lblProjectHelp'):
                    self.lblProjectHelp.setText('<small>Select or enter your Google Cloud Project for Earth Engine.</small>')
                if hasattr(self, 'txtDiscoveryError'):
                    self.txtDiscoveryError.setVisible(False)
                if hasattr(self, 'lblStatus'):
                    self.lblStatus.setText(f'<font color="#059669"><b>● Earth Engine Ready ({active_proj})</b></font>')
                if hasattr(self, 'btnContinue'): self.btnContinue.setEnabled(True)
            else:
                # State 3: PROJECT_REQUIRED
                if hasattr(self, 'cmbProject'): self.cmbProject.setEnabled(True)
                if hasattr(self, 'btnTestConnection'): self.btnTestConnection.setEnabled(True)
                if hasattr(self, 'btnContinue'): self.btnContinue.setEnabled(False)
                if hasattr(self, 'btnWebAssist'): self.btnWebAssist.setVisible(True)
                
                if not self._discovered_projects:
                    if hasattr(self, 'lblProjectHelp'):
                        self.lblProjectHelp.setText('<small>No Earth Engine project has been selected yet.<br>Click <b>View My Earth Engine Projects</b> to open Google\'s official project page.<br>Copy an available Project ID and paste it above.<br><br><font color="#D97706"><b>IMPORTANT:</b> Copy the <b>Project ID</b>, not the project name or number.</font></small>')
                else:
                    if hasattr(self, 'lblProjectHelp'):
                        self.lblProjectHelp.setText('<small>Select your Google Cloud Project for Earth Engine.</small>')
                
                if hasattr(self, 'txtDiscoveryError'):
                    self.txtDiscoveryError.setVisible(False)
                if hasattr(self, 'lblStatus'):
                    self.lblStatus.setText('<font color="#D97706"><b>● Authenticated — Project Required</b></font>')

    def on_test_connection_clicked(self):
        """Test Earth Engine connection with selected project."""
        import logging
        logger = logging.getLogger(__name__)
        
        if not hasattr(self, 'cmbProject'):
            return
            
        if self.cmbProject.isEditable():
            project_id = self.cmbProject.currentText().strip()
        else:
            project_id = self.cmbProject.currentData() or self.cmbProject.currentText().strip()
            
        if not project_id:
            QMessageBox.warning(self, "Input Error", "Please enter or select a valid Earth Engine Project ID.")
            return
            
        # State: TESTING_PROJECT
        if hasattr(self, 'lblStatus'):
            self.lblStatus.setText('<font color="#059669"><b>● Testing Connection...</b></font>')
        if hasattr(self, 'btnTestConnection'):
            self.btnTestConnection.setEnabled(False)
        if hasattr(self, 'btnSignIn'):
            self.btnSignIn.setEnabled(False)
        if hasattr(self, 'btnContinue'):
            self.btnContinue.setEnabled(False)
        if hasattr(self, 'btnRefreshProjects'):
            self.btnRefreshProjects.setEnabled(False)
            
        worker = TestConnectionWorker(self.connection_service, project_id, parent=None)
        self._register_worker(worker, self._on_test_finished)
        
    def _on_test_finished(self, success, msg, project_id):
        if self._is_closing: return
        
        if hasattr(self, 'btnTestConnection'):
            self.btnTestConnection.setEnabled(True)
        if hasattr(self, 'btnSignIn'):
            self.btnSignIn.setEnabled(True)
            
        if success:
            QMessageBox.information(self, "Success", "Earth Engine connection verified successfully!")
        else:
            if msg == "INVALID_PROJECT_FORMAT":
                QMessageBox.warning(self, "Invalid Project ID", "Invalid Project ID format.\nUse the Google Cloud Project ID, not a project name.")
            elif msg == "PROJECT_NOT_FOUND":
                QMessageBox.warning(self, "Project Not Found", "Project not found or you do not have access to this project.")
            elif msg == "PROJECT_ACCESS_DENIED":
                QMessageBox.warning(self, "Access Denied", "Project not found or you do not have access to this project.")
            elif msg == "EARTH_ENGINE_NOT_ENABLED":
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Icon.Warning)
                box.setWindowTitle("Earth Engine Not Enabled")
                box.setText("Earth Engine is not enabled for this project.")
                setup_btn = box.addButton("Open Earth Engine Setup", QMessageBox.ButtonRole.ActionRole)
                box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
                box.exec()
                if box.clickedButton() == setup_btn:
                    import webbrowser
                    webbrowser.open("https://developers.google.com/earth-engine/cloud/earthengine_cloud_project_setup")
            elif msg == "BILLING_OR_QUOTA_ISSUE":
                QMessageBox.warning(self, "Execution Failed", "Earth Engine cannot execute requests using this project. Check project registration, billing, quota, and permissions.")
            else:
                QMessageBox.warning(self, "Validation Failed", f"Validation failed:\n\n{msg}")
            
        self.refresh_status()

    def on_login_clicked(self):
        import logging
        logger = logging.getLogger(__name__)
        logger.info("[AUTH DEBUG] Sign In/Out button clicked")
        
        authenticated = self.connection_service.is_authenticated()
        logger.info(f"[AUTH DEBUG] authenticated={authenticated}")
        
        # Check session locking
        if authenticated and self.connection_service.gee_provider.is_session_locked:
            logger.info("[AUTH DEBUG] Logout blocked: session is locked")
            QMessageBox.warning(self, "Logout Blocked", "Cannot sign out while an Earth Engine operation is running. Please wait for it to finish.")
            return
        
        # State: AUTHENTICATING / LOGGING_OUT
        if hasattr(self, 'btnSignIn'): self.btnSignIn.setEnabled(False)
        if hasattr(self, 'btnRefreshProjects'): self.btnRefreshProjects.setEnabled(False)
        if hasattr(self, 'btnTestConnection'): self.btnTestConnection.setEnabled(False)
        if hasattr(self, 'cmbProject'): self.cmbProject.setEnabled(False)
        if hasattr(self, 'btnContinue'): self.btnContinue.setEnabled(False)
        
        from PyQt6.QtWidgets import QApplication
        
        if authenticated:
            logger.info("[AUTH DEBUG] Entering logout flow")
            if hasattr(self, 'btnSignIn'):
                self.btnSignIn.setText("● Signing out...")
            if hasattr(self, 'lblStatus'):
                self.lblStatus.setText('<font color="#D97706"><b>● Signing Out...</b></font>')
            QApplication.processEvents()
            
            logger.info("[AUTH DEBUG] Creating LogoutWorker")
            worker = LogoutWorker(self.connection_service, parent=None)
            logger.info("[AUTH DEBUG] Starting LogoutWorker")
            self._register_worker(worker, self._on_logout_finished)
        else:
            logger.info("[AUTH DEBUG] Entering login flow")
            if hasattr(self, 'btnSignIn'):
                self.btnSignIn.setText("● Authenticating...")
            if hasattr(self, 'lblStatus'):
                self.lblStatus.setText('<font color="#D97706"><b>● Authenticating with Google...</b></font>')
            QApplication.processEvents()
            
            worker = AuthWorker("login", self.connection_service, parent=None)
            self._register_worker(worker, self._on_login_finished)
            
    def _on_logout_finished(self, success, msg):
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[AUTH DEBUG] _on_logout_finished() entered (success={success})")
        
        if self._is_closing: return
        
        if hasattr(self, 'btnSignIn'): self.btnSignIn.setEnabled(True)
        if success:
            self._discovered_projects = []
            self._discovery_attempted = False
            if hasattr(self, 'cmbProject'): self.cmbProject.clear()
            QMessageBox.information(self, "Logged Out", "You have been successfully signed out.")
        else:
            QMessageBox.warning(self, "Logout Failed", f"Sign out could not be completed. Please try again.\n\n{msg}")
            
        self.refresh_status()
        logger.info("[AUTH DEBUG] UI reset complete")
        
    def _on_login_finished(self, success, msg):
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[AUTH DEBUG] _on_login_finished() entered (success={success})")
        if self._is_closing: return
        
        if hasattr(self, 'btnSignIn'): self.btnSignIn.setEnabled(True)
        if hasattr(self, 'btnSwitchAccount'): self.btnSwitchAccount.setEnabled(True)
        if success:
            self._discovery_attempted = False
            self._populate_projects()
        else:
            if "cancelled" in msg.lower() or "timeout" in msg.lower():
                pass # Silent cancel
            else:
                QMessageBox.warning(self, "Login Failed", msg)
            self.refresh_status()

    def reject(self):
        self._disconnect_workers()
        super().reject()
        
    def closeEvent(self, event):
        self._disconnect_workers()
        super().closeEvent(event)
