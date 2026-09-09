import os
import json
import glob
from typing import Dict, Any, List
from .schema_validator import SchemaValidator

class SatelliteRegistry:
    """
    Single source of truth for all satellite and provider metadata.
    Automatically discovers and loads definitions from the satellites/ directory.
    """
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
        
    def __init__(self):
        self.satellites: Dict[str, Dict[str, Any]] = {}
        self.validator = SchemaValidator()
        self.load_satellites()
        
    def load_satellites(self):
        plugin_dir = os.path.dirname(os.path.dirname(__file__))
        satellites_dir = os.path.join(plugin_dir, "satellites")
        if not os.path.exists(satellites_dir):
            return
            
        for filepath in glob.glob(os.path.join(satellites_dir, "*.json")):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                if self.validator.validate_satellite(data, filepath):
                    sat_id = data["satellite_id"]
                    self.satellites[sat_id] = data
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to load satellite from {filepath}: {e}")
                
    def get_satellite(self, satellite_id: str) -> Dict[str, Any]:
        if satellite_id not in self.satellites:
            raise ValueError(f"Satellite {satellite_id} is not registered.")
        return self.satellites[satellite_id]
        
    def get_all_satellites(self) -> List[Dict[str, Any]]:
        return list(self.satellites.values())
        
    def translate_bands(self, satellite_id: str, generic_bands: List[str]) -> Dict[str, str]:
        sat = self.get_satellite(satellite_id)
        mapping = sat.get("band_mapping", {})
        result = {}
        for band in generic_bands:
            if band in mapping:
                result[band] = mapping[band]
        return result
