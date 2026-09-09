import json
import logging
from typing import Dict, Any

class SchemaValidator:
    """
    Validates JSON definition files before loading them into the Registries.
    Prevents malformed JSON from crashing the application.
    """
    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def validate_index(self, data: Dict[str, Any], filepath: str) -> bool:
        required_keys = [
            "schema_version", "id", "metadata", "workspace", 
            "formula", "visualization", "classification", 
            "capabilities", "supported_satellites"
        ]
        for key in required_keys:
            if key not in data:
                self.logger.error(f"Validation failed for {filepath}: Missing required key '{key}'")
                return False
                
        # Validate formula schema
        formula = data.get("formula", {})
        if "engine" not in formula or "expression" not in formula or "required_bands" not in formula:
            self.logger.error(f"Validation failed for {filepath}: Formula missing engine, expression, or required_bands")
            return False
            
        return True

    def validate_satellite(self, data: Dict[str, Any], filepath: str) -> bool:
        required_keys = [
            "schema_version", "satellite_id", "display_name", "provider", 
            "collection_id", "native_resolution", "band_mapping", 
            "capabilities"
        ]
        for key in required_keys:
            if key not in data:
                self.logger.error(f"Validation failed for {filepath}: Missing required key '{key}'")
                return False
        return True
        
    def validate_workspace(self, data: Dict[str, Any], filepath: str) -> bool:
        required_keys = ["schema_version", "id", "display_name"]
        for key in required_keys:
            if key not in data:
                self.logger.error(f"Validation failed for {filepath}: Missing required key '{key}'")
                return False
        return True
