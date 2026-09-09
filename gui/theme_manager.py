from ..analysis.workspace_manager import WorkspaceManager

class ThemeManager:
    """
    Centralizes all styling, theme, and color generation for the UI.
    Reads metadata from WorkspaceManager to dynamically theme the application.
    """
    
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
        
    def __init__(self):
        self.workspace_manager = WorkspaceManager.get_instance()
        
    def get_theme(self, workspace_id: str) -> dict:
        """
        Retrieves the visual theme metadata for a specific workspace.
        Defaults to a neutral blue theme if not defined.
        """
        for ws in self.workspace_manager.get_all_workspaces():
            if ws["id"] == workspace_id:
                return {
                    "primary_color": ws.get("primary_color", "#2563EB"),
                    "accent_color": ws.get("accent_color", "#EFF6FF"),
                    "icon": ws.get("icon", ":/plugins/remote_sensing_studio/icons/plugin_icon.png")
                }
                
        # Neutral fallback theme
        return {
            "primary_color": "#2563EB",
            "accent_color": "#EFF6FF",
            "icon": ":/plugins/remote_sensing_studio/icons/plugin_icon.png"
        }
