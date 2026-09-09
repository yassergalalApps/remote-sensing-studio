"""
Image Model Module.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List

@dataclass
class ImageModel:
    """Represents a discovered or selected remote sensing image/composite."""
    image_id: str
    satellite: str
    acquisition_date: str
    cloud_cover: float
    bands: List[str]
    crs: str
    resolution: str
    tile_id: str = "N/A"
    processing_level: str = "N/A"
    preview_url: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
