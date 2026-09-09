import os
import json
import glob
from typing import Dict, Any, List
from .schema_validator import SchemaValidator

class WorkspaceRegistry:
    """
    Single source of truth for workspaces (e.g. Vegetation, Water, Urban).
    Automatically discovers and loads definitions from the workspaces/ directory.
    """
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
        
    def __init__(self):
        self.workspaces: Dict[str, Dict[str, Any]] = {}
        self.validator = SchemaValidator()
        self.load_workspaces()
        
    def load_workspaces(self):
        plugin_dir = os.path.dirname(os.path.dirname(__file__))
        workspaces_dir = os.path.join(plugin_dir, "workspaces")
        if not os.path.exists(workspaces_dir):
            return
            
        for filepath in glob.glob(os.path.join(workspaces_dir, "*.json")):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                if self.validator.validate_workspace(data, filepath):
                    ws_id = data["id"]
                    self.workspaces[ws_id] = data
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to load workspace from {filepath}: {e}")
                
    def get_workspace(self, workspace_id: str) -> Dict[str, Any]:
        if workspace_id not in self.workspaces:
            raise ValueError(f"Workspace {workspace_id} is not registered.")
        return self.workspaces[workspace_id]
        
    def get_all_workspaces(self) -> List[Dict[str, Any]]:
        # Sort by sorting_order
        workspaces = list(self.workspaces.values())
        return sorted(workspaces, key=lambda w: w.get("sorting_order", 999))
