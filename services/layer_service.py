"""
Layer Service Module.
"""
import logging
import json
import hashlib
from typing import Any, Dict, List, Optional
from PyQt6.QtCore import QObject, pyqtSignal

from ..providers.gee_provider import GEEProvider
from ..utils.logger import get_logger
from ..models.image_model import ImageModel
from ..models.project_model import ProjectModel

class LayerService(QObject):
    """
    Service class to manage local and cloud map layers.
    Includes metadata caching, discovery execution, and image selection.
    """
    
    task_notification = pyqtSignal(str, str, str)
    
    _instance = None
    
    @classmethod
    def get_instance(cls) -> 'LayerService':
        if cls._instance is None:
            cls._instance = LayerService()
        return cls._instance
        
    def __init__(self) -> None:
        super().__init__()
        self.logger = get_logger(__name__)
        from ..services.connection_service import ConnectionService
        self.gee_provider = ConnectionService.get_instance().gee_provider
        
        # Isolated Caches
        self._cache_meta: Dict[str, Dict[str, Any]] = {}
        self._cache_lists: Dict[str, List[Dict[str, Any]]] = {}
        self._cache_thumbs: Dict[str, Dict[str, Any]] = {}
        
        self.current_project = ProjectModel()
        
        self.logger.debug("LayerService initialized.")
        
    def clear_search_cache(self):
        """Clears the internal caches to force fresh queries on next search."""
        self._cache_meta.clear()
        self._cache_lists.clear()
        self._cache_thumbs.clear()
        self._notify_task("Cache Cleared", "Search cache has been manually cleared.", "success")
        
    def _generate_cache_key(self, prefix: str, satellite: str, start_date: str, end_date: str, aoi: Dict[str, Any], extra: str = "") -> str:
        key_string = f"{prefix}_{satellite}_{start_date}_{end_date}_{json.dumps(aoi, sort_keys=True)}_{extra}"
        return hashlib.md5(key_string.encode('utf-8')).hexdigest()

    def discover_imagery(self, satellite: str, start_date: str, end_date: str, aoi_geojson: Dict[str, Any]) -> Dict[str, Any]:
        cache_key = self._generate_cache_key("META", satellite, start_date, end_date, aoi_geojson)
        if cache_key in self._cache_meta:
            self._notify_task("Metadata Discovery", "Loaded metadata from cache.", "success")
            return self._cache_meta[cache_key]
            
        try:
            metadata = self.gee_provider.get_collection_metadata(satellite, start_date, end_date, aoi_geojson)
            self._cache_meta[cache_key] = metadata
            self._notify_task("Metadata Discovery", f"Successfully found {metadata.get('Images Found', 0)} images.", "success")
            return metadata
        except Exception as e:
            self._notify_task("Metadata Discovery Failed", str(e), "error")
            raise

    def get_image_list(self, satellite: str, start_date: str, end_date: str, aoi_geojson: Dict[str, Any], filters: Dict[str, Any] = None, sort_by: str = "Lowest Cloud") -> List[Dict[str, Any]]:
        """Returns a list of available images with full metadata, filtered and sorted."""
        cache_key = self._generate_cache_key("LIST", satellite, start_date, end_date, aoi_geojson, f"{json.dumps(filters)}_{sort_by}")
        if cache_key in self._cache_lists:
            self._notify_task("Image List", "Loaded image list from cache.", "success")
            return self._cache_lists[cache_key]
            
        try:
            self._notify_task("Image List", "Fetching and computing image list from Google Earth Engine...", "success")
            img_list = self.gee_provider.get_image_list(satellite, start_date, end_date, aoi_geojson, filters, sort_by)
            self._cache_lists[cache_key] = img_list
            self._notify_task("Image List", f"Successfully retrieved {len(img_list)} image records.", "success")
            return img_list
        except Exception as e:
            self._notify_task("Image List Failed", str(e), "error")
            raise

    def select_and_preview_image(self, satellite: str, start_date: str, end_date: str, aoi_geojson: Dict[str, Any], selection_mode: str, image_ids: List[str] = None, analysis_type: str = None, vis_params_override: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Selects an image or composite based on the mode and generates a preview.
        Stores the result in the active project state and caches thumbnails.
        """
        # Create a unique key for the thumbnail cache
        ids_str = ",".join(image_ids) if image_ids else "none"
        vis_str = json.dumps(vis_params_override) if vis_params_override else "none"
        cache_key = self._generate_cache_key("THUMB", satellite, start_date, end_date, aoi_geojson, f"{selection_mode}_{ids_str}_{analysis_type}_{vis_str}")
        
        if cache_key in self._cache_thumbs:
            self._notify_task("Image Selection", "Loaded preview from cache.", "success")
            return self._cache_thumbs[cache_key]

        try:
            self._notify_task("Image Selection", f"Generating {selection_mode} preview...", "success")
            
            data = self.gee_provider.get_selected_image_preview(satellite, start_date, end_date, aoi_geojson, selection_mode, image_ids, analysis_type, vis_params_override)
            
            # Save into cache
            self._cache_thumbs[cache_key] = data
            
            selected_image = ImageModel(
                image_id=data.get("Image ID", "Unknown"),
                satellite=data.get("Satellite", satellite),
                acquisition_date=data.get("Acquisition Date", "Unknown"),
                cloud_cover=data.get("Cloud Percentage", 0.0),
                bands=data.get("Available Bands", []),
                crs="Earth Engine Native", 
                resolution="Variable", 
                processing_level=data.get("Processing Level", "Unknown"),
                preview_url=data.get("Preview URL", "")
            )
            
            self.current_project.selected_image = selected_image
            
            self._notify_task("Preview Generated", f"Successfully generated preview for {selection_mode}.", "success")
            return data
            
        except Exception as e:
            self._notify_task("Image Selection Failed", str(e), "error")
            raise

    def _notify_task(self, title: str, message: str, level: str = "success"):
        if level == "error":
            self.logger.error(f"TASK ERROR - {title}: {message}")
        else:
            self.logger.info(f"TASK SUCCESS - {title}: {message}")
        self.task_notification.emit(title, message, level)
