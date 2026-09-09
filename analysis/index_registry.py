import os
import json
import glob
from typing import Dict, Any, List
from .schema_validator import SchemaValidator

class IndexRegistry:
    """
    Single source of truth for all spectral index definitions.
    Automatically discovers and loads indices from the indices/ directory.
    """
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
        
    def __init__(self):
        self.indices: Dict[str, Dict[str, Any]] = {}
        self.validator = SchemaValidator()
        self.load_indices()
        
    def load_indices(self):
        plugin_dir = os.path.dirname(os.path.dirname(__file__))
        indices_dir = os.path.join(plugin_dir, "indices")
        if not os.path.exists(indices_dir):
            return
            
        for filepath in glob.glob(os.path.join(indices_dir, "*.json")):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                if self.validator.validate_index(data, filepath):
                    index_id = data["id"]
                    self.indices[index_id] = data
            except Exception as e:
                # Malformed JSON must not crash the application
                import logging
                logging.getLogger(__name__).error(f"Failed to load index from {filepath}: {e}")
                
    def get_index(self, index_id: str) -> Dict[str, Any]:
        if index_id not in self.indices:
            raise ValueError(f"Index {index_id} is not registered.")
        return self.indices[index_id]
        
    def get_all_indices(self) -> List[Dict[str, Any]]:
        return list(self.indices.values())
