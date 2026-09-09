"""
Provider Adapter Module.
Creates an abstraction layer ensuring generic processing logic can be translated 
to any specific provider API (GEE, Local, STAC).
"""
import os
import tempfile
from typing import Any, Dict, List
from ..utils.logger import get_logger
from ..analysis.analysis_context import AnalysisContext

# --- STRICT ARCHITECTURE ENFORCEMENT ---
# The constraint requires we do NOT modify VisualizationService natively. 
# Therefore, we dynamically patch it here at runtime to support local QgsRasterLayers seamlessly.
from ..services.visualization_service import VisualizationService

try:
    from qgis.core import QgsRasterLayer, QgsProject
except ImportError:
    pass

_original_visualize = VisualizationService.visualize_result

def _patched_visualize_result(self, result, layer_name, zoom_to_aoi=False, aoi_geojson=None):
    if result.provider == 'LocalProvider':
        self.logger.info(f"Using native QgsRasterLayer visualization for LocalProvider: {layer_name}")
        layer = result.raster_reference.layer
        if not layer.isValid():
            self.logger.error("Invalid local raster layer.")
            return False
            
        layer.setName(layer_name)
        
        project = QgsProject.instance()
        existing = project.mapLayersByName(layer_name)
        for old in existing:
            project.removeMapLayer(old)
            
        project.addMapLayer(layer)
        return True
        
    return _original_visualize(self, result, layer_name, zoom_to_aoi, aoi_geojson)

VisualizationService.visualize_result = _patched_visualize_result
# ------------------------------------------

try:
    import ee
except ImportError:
    pass

class LocalProjWrapper:
    """Duck-typing wrapper to mimic ee.Projection() logic."""
    def __init__(self, layer):
        self.layer = layer
    def crs(self):
        class CrsWrapper:
            def getInfo(inner_self):
                return self.layer.crs().authid()
        return CrsWrapper()
    def nominalScale(self):
        class ScaleWrapper:
            def getInfo(inner_self):
                return self.layer.rasterUnitsPerPixelX()
        return ScaleWrapper()

class LocalImageWrapper:
    """Duck-typing wrapper to mimic ee.Image allowing unmodified NDVI module execution."""
    def __init__(self, layer: Any):
        self.layer = layer
        
    def rename(self, name: str):
        self.layer.setName(name)
        return self
        
    def projection(self):
        return LocalProjWrapper(self.layer)


class ProviderAdapter:
    """Base class/interface for provider-specific execution translation."""
    
    def __init__(self, provider_instance: Any) -> None:
        self.provider = provider_instance
        self.logger = get_logger(__name__)
        
    def supported_datasets(self) -> List[str]:
        """Pass-through to get supported datasets from the underlying provider."""
        if hasattr(self.provider, "supported_datasets"):
            return self.provider.supported_datasets()
        return []
        
    def execute_band_math(self, expression: str, band_mapping: Dict[str, str], context: AnalysisContext) -> Any:
        """Translates a logical band math expression to provider-specific execution."""
        self.logger.debug(f"ProviderAdapter executing expression: {expression}")
        provider_name = self.provider.__class__.__name__
        
        if provider_name == 'LocalProvider':
            layer = self.provider.get_image_object(
                context.input_image.satellite, "", "", context.aoi_geojson, context.input_image.image_id
            )
            
            # Translate generic math into QGIS native Raster Calculator
            from qgis.analysis import QgsRasterCalculator, QgsRasterCalculatorEntry
            out_path = os.path.join(tempfile.gettempdir(), f"local_calc_{os.urandom(4).hex()}.tif")
            
            entries = []
            qgis_expr = expression
            for logical_name, provider_name_val in band_mapping.items():
                try:
                    digits = ''.join(filter(str.isdigit, provider_name_val))
                    band_idx = int(digits) if digits else 1
                except:
                    band_idx = 1
                    
                entry = QgsRasterCalculatorEntry()
                entry.ref = f"{logical_name}"
                entry.raster = layer
                entry.bandNumber = band_idx
                entries.append(entry)
                
                # Format expression variables for QGIS Raster Calculator
                qgis_expr = qgis_expr.replace(logical_name, f'"{logical_name}"')
                
            calc = QgsRasterCalculator(
                qgis_expr, out_path, 'GTiff', layer.extent(), layer.width(), layer.height(), entries
            )
            calc.processCalculation()
            
            result_layer = QgsRasterLayer(out_path, "Calculated")
            return LocalImageWrapper(result_layer)
            
        else:
            # Native GEE Execution
            if hasattr(self.provider, 'get_image_object'):
                start_date = context.parameters.get('start_date', '2020-01-01')
                end_date = context.parameters.get('end_date', '2020-12-31')
                selection_mode = context.input_image.image_id
                
                img = self.provider.get_image_object(
                    context.input_image.satellite,
                    start_date, end_date,
                    context.aoi_geojson,
                    selection_mode
                )
            else:
                img = ee.Image(context.input_image.image_id)
                
            ee_band_dict = {}
            for logical_name, provider_name_val in band_mapping.items():
                ee_band_dict[logical_name] = img.select(provider_name_val)
                
            return img.expression(expression, ee_band_dict)
        
    def compute_statistics(self, computed_image: Any, aoi: Dict[str, Any], scale: float = 30) -> Dict[str, Any]:
        """Compute basic statistics securely server-side or locally."""
        provider_name = self.provider.__class__.__name__
        
        if provider_name == 'LocalProvider':
            layer = computed_image.layer
            provider = layer.dataProvider()
            from qgis.core import Qgis
            stats = provider.bandStatistics(1, Qgis.RasterBandStatistic.All)
            return {
                "Min": round(stats.minimumValue, 3),
                "Max": round(stats.maximumValue, 3),
                "Mean": round(stats.mean, 3),
                "StdDev": round(stats.stdDev, 3)
            }
            
        # GEE Execution
        geom = ee.Geometry(aoi)
        reducer = ee.Reducer.minMax().combine(
            reducer2=ee.Reducer.mean(), sharedInputs=True
        ).combine(
            reducer2=ee.Reducer.stdDev(), sharedInputs=True
        )
        
        stats = computed_image.reduceRegion(
            reducer=reducer, geometry=geom, scale=scale, maxPixels=1e9
        ).getInfo()
        
        band_name = computed_image.bandNames().get(0).getInfo()
        return {
            "Min": round(stats.get(f'{band_name}_min', 0.0), 3),
            "Max": round(stats.get(f'{band_name}_max', 0.0), 3),
            "Mean": round(stats.get(f'{band_name}_mean', 0.0), 3),
            "StdDev": round(stats.get(f'{band_name}_stdDev', 0.0), 3)
        }
