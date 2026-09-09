"""
Local Raster Provider Module.
"""
import os
import datetime
from typing import Any, Dict, List
from ..utils.logger import get_logger

try:
    from qgis.core import QgsRasterLayer
except ImportError:
    pass

class LocalProvider:
    """Provider for local GeoTIFF and COG datasets."""
    def __init__(self) -> None:
        self.logger = get_logger(__name__)
        
    def supported_datasets(self) -> List[str]:
        """Returns the list of supported datasets for this provider."""
        return ["Local File / COG"]
        
    def get_image_object(self, satellite: str, start_date: str, end_date: str, aoi_geojson: Dict[str, Any], selection_mode: str) -> Any:
        """For local provider, selection_mode acts as the absolute filepath."""
        filepath = selection_mode
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Local raster not found: {filepath}")
        layer = QgsRasterLayer(filepath, "Local Raster")
        if not layer.isValid():
            raise ValueError(f"Invalid local raster: {filepath}")
        return layer

    def get_selected_image_preview(self, filepath: str) -> Dict[str, Any]:
        """Reads metadata from local file to build the preview ImageModel dictionary."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")
            
        layer = QgsRasterLayer(filepath, "Preview")
        if not layer.isValid():
            raise ValueError("Invalid raster")
            
        crs = layer.crs().authid()
        bands = [layer.bandName(i) for i in range(1, layer.bandCount() + 1)]
        res_x = layer.rasterUnitsPerPixelX()
        extent = layer.extent()
        
        return {
            "Image ID": filepath,
            "Acquisition Date": datetime.datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%Y-%m-%d %H:%M:%S'),
            "Cloud Percentage": 0.0,
            # We map to Sentinel-2 to allow seamless BandMapper integration for proof-of-concept
            "Satellite": "Sentinel-2", 
            "Available Bands": bands,
            "Processing Level": "Local File / COG",
            "Preview URL": "local", 
            "CRS": crs,
            "Native Resolution": f"{res_x:.2f}m",
            "Extent": f"[{extent.xMinimum():.2f}, {extent.yMinimum():.2f}, {extent.xMaximum():.2f}, {extent.yMaximum():.2f}]"
        }
