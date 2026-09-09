"""
Connection Service Module.
"""
import logging
from typing import Dict, Any, Tuple, List
from PyQt6.QtCore import QSettings
from ..providers.gee_provider import GEEProvider
from ..utils.logger import get_logger

class ConnectionService:
    """
    Service class to manage connection states for UI.
    Ensures UI never communicates directly with providers.
    """
    
    _instance = None
    
    @classmethod
    def get_instance(cls) -> 'ConnectionService':
        if cls._instance is None:
            cls._instance = ConnectionService()
        return cls._instance
        
    def __init__(self) -> None:
        self.logger: logging.Logger = get_logger(__name__)
        self.gee_provider = GEEProvider()
        self._current_provider = "Google Earth Engine"
        
        val = self.get_settings().value("earth_engine/explicitly_signed_out", False)
        is_signed_out = val in (True, 'true', 'True', 1, '1')
        # FIX 1: Defer EE validation to WelcomeDialog.on_continue instead of running synchronously here.
            
        self.logger.debug("ConnectionService initialized.")

    def get_settings(self) -> QSettings:
        return QSettings("RemoteSensingStudio", "Config")

    def get_active_project(self) -> str:
        return self.get_settings().value("earth_engine/active_project", "", type=str)

    def _history_key(self) -> str:
        user = self.current_user()
        if user and user not in ["authenticated_user", "Google User", "Google account authenticated", "Google account could not be determined"]:
            import re
            clean_email = re.sub(r'[^a-zA-Z0-9]', '_', user)
            return f"earth_engine/project_history_{clean_email}"
        return "earth_engine/project_history"

    def get_saved_projects(self) -> List[str]:
        if not self.is_authenticated():
            return []
            
        val = self.get_settings().value(self._history_key(), [])
        if isinstance(val, str):
            return [val] if val else []
        return val if isinstance(val, list) else []

    def _save_project_success(self, project_id: str) -> None:
        settings = self.get_settings()
        settings.setValue("earth_engine/active_project", project_id)
        
        history_key = self._history_key()
        history = self.get_saved_projects()
        if project_id in history:
            history.remove(project_id)
        history.insert(0, project_id)
        # Keep only last 10
        settings.setValue(history_key, history[:10])

    def check_saved_connection(self) -> None:
        """Explicitly validates the saved project. Should be called safely from the UI."""
        val = self.get_settings().value("earth_engine/explicitly_signed_out", False)
        is_signed_out = val in (True, 'true', 'True', 1, '1')
        if not is_signed_out:
            saved_project = self.get_active_project()
            if saved_project:
                self.gee_provider.check_connection(saved_project)

    def test_and_set_project(self, project_id: str) -> Tuple[bool, str]:
        """Tests the given project ID. If successful, saves it as active."""
        if not project_id or not project_id.strip():
            return False, "Project ID cannot be empty."
            
        project_id = project_id.strip()
        
        import re
        if not re.match(r"^[a-z][a-z0-9\-]{4,28}[a-z0-9]$|^[a-z0-9\-\.\:]+$", project_id):
            return False, "INVALID_PROJECT_FORMAT"
            
        self.logger.info(f"Testing EE connection with project: {project_id}")
        success, msg = self.gee_provider.test_connection(project_id)
        
        if success:
            self._save_project_success(project_id)
        return success, msg

    def current_provider(self) -> str:
        """Get the active provider."""
        return self._current_provider

    def set_current_provider(self, provider: str) -> None:
        """Set the active provider."""
        if provider in ["Google Earth Engine", "Local Raster", "Microsoft Planetary Computer"]:
            self._current_provider = provider
        else:
            self.logger.warning(f"Unknown provider: {provider}")

    def has_credentials(self) -> bool:
        """Check if Google Auth credentials exist."""
        val = self.get_settings().value("earth_engine/explicitly_signed_out", False)
        is_signed_out = val in (True, 'true', 'True', 1, '1')
        if is_signed_out:
            self.logger.info("[AUTH DEBUG] Automatic authentication suppressed due to explicit logout.")
            return False
        return self.gee_provider.has_credentials()

    def is_authenticated(self) -> bool:
        """Check if the user is authenticated (regardless of project status)."""
        val = self.get_settings().value("earth_engine/explicitly_signed_out", False)
        is_signed_out = val in (True, 'true', 'True', 1, '1')
        if is_signed_out:
            return False
        return self.has_credentials()
        
    def is_project_ready(self) -> bool:
        """Check if Earth Engine is fully initialized and ready for analysis."""
        return self.gee_provider.is_connected
        
    def discover_projects(self) -> Tuple[List[Dict[str, str]], str]:
        """Retrieve accessible GCP projects."""
        history = self.get_saved_projects()
        return self.gee_provider.discover_projects(history_projects=history)
        
    def login_gee(self) -> Tuple[bool, str]:
        """Trigger GEE login process."""
        self.logger.info("ConnectionService initiating GEE login...")
        settings = self.get_settings()
        settings.remove("earth_engine/explicitly_signed_out")
        settings.sync()
        return self.gee_provider.login()
        
    def logout_gee(self) -> Tuple[bool, str]:
        """Trigger GEE logout process and clear project config."""
        self.logger.info("ConnectionService initiating GEE logout...")
        success, msg = self.gee_provider.logout()
        if success:
            settings = self.get_settings()
            settings.remove("earth_engine/active_project")
            settings.setValue("earth_engine/explicitly_signed_out", True)
            settings.sync()
            self.logger.info("[AUTH DEBUG] Logout completed successfully")
            self.logger.info("[AUTH DEBUG] Authentication state = False")
            self.logger.info("[AUTH DEBUG] Explicit signed-out state = True")
            self.logger.info("[AUTH DEBUG] Active project cleared")
            self.logger.info("[AUTH DEBUG] UI project history cleared")
            
            # Account isolation: Clear LayerService caches
            from .layer_service import LayerService
            LayerService.get_instance().clear_search_cache()
            self.logger.info("[AUTH DEBUG] LayerService cache cleared")
            
        return success, msg

    def current_user(self) -> str:
        """Get the current authenticated user or None if unavailable."""
        if self.is_authenticated():
            # Current GEEProvider implementation sets current_account to "authenticated_user"
            return self.gee_provider.current_account
        return None
        
    def connection_status(self) -> str:
        """Get a formatted HTML connection status string for the UI."""
        if self.is_authenticated():
            return '<b style="color: #059669;">● Connected</b>'
        else:
            return '<font color="#D97706"><b>● Not Connected</b></font>'
        
    def get_gee_status(self) -> Dict[str, Any]:
        """Retrieve current GEE connection status."""
        status = self.gee_provider.get_status()
        val = self.get_settings().value("earth_engine/explicitly_signed_out", False)
        is_signed_out = val in (True, 'true', 'True', 1, '1')
        if is_signed_out:
            status["has_credentials"] = False
            status["connected"] = False
            status["account"] = ""
            status["project"] = ""
        return status
