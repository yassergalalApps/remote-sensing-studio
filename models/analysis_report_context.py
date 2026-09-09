from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import io
import base64

@dataclass
class AnalysisReportContext:
    """
    Single source of truth for the Quality Assessment and Scientific Report modules.
    Aggregates data from AnalysisResult, StatisticsEngine, ClassificationEngine, and UI State.
    """
    # General Analysis Details
    formula_name: str
    formula_expression: str
    dataset: str
    satellite: str
    provider: str
    processing_level: str
    
    # Spatial & Temporal
    crs: str
    resolution: str
    number_of_scenes: int
    composite_method: str
    coverage_percent: float
    
    # Quality & System Metrics
    cloud_threshold: float
    masks_applied: List[str]
    images_found: Optional[int]
    images_used: Optional[int]
    execution_time_sec: float
    processing_timestamp: str
    
    # Base Raster Statistics
    stat_min: float
    stat_max: float
    stat_mean: float
    stat_median: float
    stat_std: float
    stat_valid_pixels: int
    
    # Area Statistics (Scientific Classification)
    classification_threshold: float
    negative_meaning: str
    negative_pixel_count: int
    negative_area_ha: float
    positive_meaning: str
    positive_pixel_count: int
    positive_area_ha: float
    
    # Visualization Settings
    vis_stretch_min: float
    vis_stretch_max: float
    vis_palette: str
    vis_classification_mode: str
    
    # Media for HTML Report (Base64 encoded strings)
    histogram_b64: Optional[str] = None
    legend_b64: Optional[str] = None
    preview_image_b64: Optional[str] = None
    
    validation_failed: bool = False
    
    # Scientific Documentation & Visualization Defaults
    scientific_reference: str = "N/A"
    vis_renderer_family: str = "N/A"
    
    def is_local_raster(self) -> bool:
        return self.provider.lower() in ["local", "local file", "cog", "local file / cog"]

    def get_images_found_display(self) -> str:
        if self.is_local_raster():
            return "Not Applicable (Local Raster)"
        return str(self.images_found) if self.images_found is not None else "Unknown"
        
    def get_images_used_display(self) -> str:
        if self.is_local_raster():
            return "Not Applicable (Local Raster)"
        return str(self.images_used) if self.images_used is not None else "Unknown"

    def validate(self):
        """
        Verifies that all mandatory fields are present and valid before presentation layer updates.
        Raises ValueError with a detailed message if verification fails.
        """
        missing = []
        
        # Check critical strings
        if not self.formula_name: missing.append("Formula Name")
        if not self.dataset: missing.append("Dataset")
        if not self.provider: missing.append("Provider")
        
        # Check statistics
        if self.stat_valid_pixels < 0: missing.append("Valid Pixels (Cannot be negative)")
        if self.stat_min > self.stat_max: missing.append("Min/Max Statistics (Min cannot be > Max)")
        
        # Check area stats
        if self.negative_area_ha < 0 or self.positive_area_ha < 0:
            missing.append("Computed Class Areas (Cannot be negative)")
            
        if not self.negative_meaning or not self.positive_meaning:
            missing.append("Raster Metadata Semantic Meanings (Negative/Positive meaning)")
            
        if missing:
            raise ValueError("AnalysisReportContext Validation Failed. The following mandatory data is missing or invalid:\n- " + "\n- ".join(missing))

    def generate_narrative_summary(self) -> str:
        """Generates a professional scientific narrative based on the data."""
        total_ha = self.negative_area_ha + self.positive_area_ha
        if total_ha == 0:
            pos_pct = 0.0
            neg_pct = 0.0
        else:
            pos_pct = (self.positive_area_ha / total_ha) * 100
            neg_pct = (self.negative_area_ha / total_ha) * 100
            
        provider_text = "local file processing" if self.is_local_raster() else f"the {self.provider} catalog"
        scenes_text = "a single local raster" if self.is_local_raster() else f"a composite of {self.number_of_scenes} scenes using the {self.composite_method} method"
        
        narrative = (
            f"This report details the {self.formula_name} ({self.formula_expression}) analysis performed on {self.dataset} imagery. "
            f"Data was acquired via {provider_text}, utilizing {scenes_text}. "
            f"The analyzed region covers approximately {total_ha:,.2f} hectares at a base resolution of {self.resolution}. "
            f"Quality assessment indicates {self.coverage_percent:.1f}% spatial coverage after applying {', '.join(self.masks_applied) if self.masks_applied else 'no'} masks, "
            f"with a cloud inclusion threshold of {self.cloud_threshold}%. "
            f"Statistical extraction revealed a mean {self.formula_name} of {self.stat_mean:.3f} (σ={self.stat_std:.3f}). "
            f"Applying a scientific threshold of {self.classification_threshold}, the region was classified into "
            f"'{self.positive_meaning}' ({self.positive_area_ha:,.2f} Ha, {pos_pct:.1f}%) and "
            f"'{self.negative_meaning}' ({self.negative_area_ha:,.2f} Ha, {neg_pct:.1f}%)."
        )
        return narrative
