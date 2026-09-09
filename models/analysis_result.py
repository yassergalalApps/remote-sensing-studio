from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

@dataclass(frozen=True)
class AnalysisResult:
    """
    Immutable single source of truth for an executed analysis.
    Every UI component strictly reads from this object.
    """
    analysis_type: str
    provider: str
    dataset: str
    formula_name: str
    formula_expression: str
    satellite: str
    processing_level: str
    acquisition_dates: List[str]
    number_of_scenes: int
    composite_method: str
    cloud_threshold: float
    masks_applied: List[str]
    
    aoi_geojson: Dict[str, Any]
    aoi_area_sqdeg: float
    coverage_percent: float
    coverage_km2: float
    crs: str
    resolution: str
    
    statistics: Dict[str, Any]
    histogram: Dict[str, Any]
    visualization_params: Dict[str, Any]
    
    output_layer_name: str
    output_type: str
    execution_time_sec: float
    processing_timestamp: str
    
    tile_url: Optional[str] = None
    download_url: Optional[str] = None
    tile_download_urls: List[str] = field(default_factory=list)
    export_strategy: str = "Unknown"
    metadata: Dict[str, Any] = field(default_factory=dict)
    quality_metrics: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    
    # Context for dynamic URL regeneration during download
    computed_image: Any = None
    ee_scale: float = 0.0
    ee_crs: str = ""
    ee_tiles: List[Dict[str, Any]] = field(default_factory=list)
