from typing import Dict, Any

class CapabilityManager:
    """
    Decides dynamically which features are supported based on the active index and satellite definitions.
    """
    def __init__(self, index_def: Dict[str, Any], satellite_def: Dict[str, Any]):
        self.index_def = index_def
        self.satellite_def = satellite_def
        self.index_caps = self.index_def.get("capabilities", {})
        self.sat_caps = self.satellite_def.get("capabilities", {})
        
    def supports_statistics(self) -> bool:
        return self.index_caps.get("statistics", False)
        
    def supports_histogram(self) -> bool:
        return self.index_caps.get("histogram", False)
        
    def supports_classification(self) -> bool:
        return self.index_caps.get("classification", False)
        
    def supports_area(self) -> bool:
        return self.index_caps.get("area", False)
        
    def supports_export(self) -> bool:
        return self.index_caps.get("export", True)
        
    def supports_renderer(self) -> bool:
        return self.index_caps.get("renderer", True)
