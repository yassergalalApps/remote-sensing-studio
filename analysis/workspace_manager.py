import os
import json
import logging
from typing import List, Dict, Any
from .index_registry import IndexRegistry

logger = logging.getLogger(__name__)

class WorkspaceManager:
    """
    Manages the semantic workspaces.
    Dynamically loads workspace definitions from workspaces.json.
    """
    
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
        
    def __init__(self):
        self.index_registry = IndexRegistry.get_instance()
        self.workspaces = []
        self.workspace_dict = {}
        self.load_workspaces()
        
    def load_workspaces(self):
        plugin_dir = os.path.dirname(os.path.dirname(__file__))
        json_path = os.path.join(plugin_dir, "workspaces.json")
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Sort by order if present
                self.workspaces = sorted(data, key=lambda w: w.get("order", 99))
                for ws in self.workspaces:
                    self.workspace_dict[ws["id"]] = ws
        except Exception as e:
            logger.error(f"Failed to load workspaces.json: {e}")
            
    def get_all_workspaces(self) -> List[Dict[str, Any]]:
        """Returns a list of all workspace definitions sorted by order."""
        return self.workspaces

    def get_display_name(self, workspace_id: str) -> str:
        """Returns the human-readable display name for the workspace."""
        ws = self.workspace_dict.get(workspace_id.lower())
        return ws.get("display_name", workspace_id.capitalize()) if ws else workspace_id.capitalize()
        
    def get_indices_for_workspace(self, workspace_id: str) -> List[Dict[str, Any]]:
        """
        Retrieves all index definitions belonging to the specified workspace ID.
        """
        workspace_id = workspace_id.lower()
        
        all_indices = self.index_registry.get_all_indices()
        
        filtered_indices = []
        for index in all_indices:
            # Safely get workspace, defaulting to empty string
            idx_ws = index.get("workspace", "").lower()
            if idx_ws == workspace_id:
                filtered_indices.append(index)
                
        # Sort indices by metadata order, fallback to alphabetically by ID
        filtered_indices.sort(key=lambda x: (x.get("metadata", {}).get("order", 999), x.get("id", "")))
        return filtered_indices
