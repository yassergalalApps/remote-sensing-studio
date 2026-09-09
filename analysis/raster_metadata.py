"""
Raster Metadata Definition.
Defines semantic meanings and recommended visualization defaults for continuous raster products.
Reads dynamically from the single source of truth: the JSON metadata files in the indices/ directory.
"""

import os
import json
from dataclasses import dataclass
from typing import Dict, Any, Tuple

@dataclass
class RasterMetadata:
    """
    Data model defining the semantics and visualization defaults for a continuous raster.
    """
    display_name: str
    scientific_name: str
    units: str
    recommended_display_range: Tuple[float, float]
    recommended_threshold: float
    recommended_classification_mode: str
    positive_meaning: str
    negative_meaning: str
    recommended_palette: str = "Standard"
    scientific_reference: str = "General Remote Sensing Literature"
    renderer_family: str = "continuous"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "display_name": self.display_name,
            "scientific_name": self.scientific_name,
            "units": self.units,
            "recommended_display_range": self.recommended_display_range,
            "recommended_threshold": self.recommended_threshold,
            "recommended_classification_mode": self.recommended_classification_mode,
            "positive_meaning": self.positive_meaning,
            "negative_meaning": self.negative_meaning,
            "recommended_palette": self.recommended_palette,
            "scientific_reference": self.scientific_reference,
            "renderer_family": self.renderer_family
        }

def get_raster_metadata(index_name: str) -> RasterMetadata:
    """
    Returns the metadata for a given index name by parsing its respective JSON file.
    Defaulting to CUSTOM if the file does not exist or fails to parse.
    """
    base_dir = os.path.dirname(os.path.dirname(__file__))
    json_path = os.path.join(base_dir, "indices", f"{index_name.lower()}.json")
    
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            meta = data.get("metadata", {})
            vis = data.get("visualization", {})
            report = data.get("report", {})
            params = data.get("default_parameters", {})
            formula = data.get("formula", {})
            
            ref = meta.get("scientific_reference") or formula.get("reference") or (meta.get("references", [""])[0] if meta.get("references") else "General Remote Sensing Literature")
            
            return RasterMetadata(
                display_name=meta.get("display_name", index_name),
                scientific_name=meta.get("scientific_name", index_name),
                units=meta.get("units", "Index"),
                recommended_display_range=(vis.get("minimum", -1.0), vis.get("maximum", 1.0)),
                recommended_threshold=params.get("threshold", 0.0),
                recommended_classification_mode=data.get("classification", {}).get("mode", "Continuous").title(),
                positive_meaning=report.get("positive_class", "Positive"),
                negative_meaning=report.get("negative_class", "Negative"),
                recommended_palette=vis.get("palette", "Standard"),
                scientific_reference=ref,
                renderer_family=vis.get("renderer_family", "continuous")
            )
        except Exception as e:
            import logging
            logger = logging.getLogger("RemoteSensingStudio")
            logger.error(f"Failed to load raster metadata for {index_name}: {e}")

    # Fallback for completely custom/unknown indices
    return RasterMetadata(
        display_name="Custom Index",
        scientific_name="User Defined Index",
        units="Value",
        recommended_display_range=(0.0, 1.0),
        recommended_threshold=0.5,
        recommended_classification_mode="Continuous",
        positive_meaning="High Value",
        negative_meaning="Low Value",
        recommended_palette="Grayscale",
        scientific_reference="N/A",
        renderer_family="continuous"
    )

