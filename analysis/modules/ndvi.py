"""
NDVI Analysis Module.
"""
import logging
import time
from typing import Any
from ..analysis_context import AnalysisContext
from ..analysis_result import AnalysisResult
from ...processing.processing_engine import ProcessingEngine
from ...processing.provider_adapter import ProviderAdapter
from ...utils.logger import get_logger

class NDVIAnalysis:
    """NDVI algorithm implementation utilizing the generic processing architecture."""
    
    def __init__(self) -> None:
        self.logger: logging.Logger = get_logger(__name__)
        
    def run(self, context: AnalysisContext) -> AnalysisResult:
        """
        Executes the NDVI algorithm through abstract generic dispatch.
        """
        start_time = time.time()
        self.logger.info("NDVIAnalysis.run() initiated.")
        
        try:
            # 1. Execute formula via Processing Engine (Purely agnostic)
            engine = ProcessingEngine()
            result_img = engine.execute("NDVI", context)
            
            # Explicitly rename the output band to NDVI
            result_img = result_img.rename('NDVI')
            
            # 2. Extract metadata and compute stats via provider adapter
            adapter = ProviderAdapter(context.provider)
            
            # Request dynamic resolution and projection parameters
            proj = result_img.projection()
            crs = proj.crs().getInfo()
            res = proj.nominalScale().getInfo()
            
            # Process basic statistics server-side (Min, Max, Mean, StdDev)
            stats = adapter.compute_statistics(result_img, context.aoi_geojson, scale=res)
            
            # 3. Apply Visualization Guidelines
            vis_params = {
                "min": -0.1,
                "max": 0.8,
                "palette": [
                    'FFFFFF', 'CE7E45', 'DF923D', 'F1B555', 'FCD163', 
                    '99B718', '74A901', '66A000', '529400', '3E8601', 
                    '207401', '056201', '004C00', '023B01', '012E01', 
                    '011D01', '011301'
                ]
            }
            
            metadata = {
                "Index": "Normalized Difference Vegetation Index (NDVI)",
                "Statistics": stats,
                "Visualization": vis_params
            }
            
            elapsed = time.time() - start_time
            self.logger.info("NDVI analysis completed successfully.")
            
            return AnalysisResult(
                success=True,
                raster_reference=result_img,
                processing_time_sec=elapsed,
                provider=context.provider.__class__.__name__ if context.provider else "Unknown",
                projection=crs,
                resolution=f"{round(res, 2)}m",
                metadata=metadata
            )
            
        except Exception as e:
            self.logger.error(f"NDVI execution failed: {e}", exc_info=True)
            return AnalysisResult(success=False, error_message=str(e))

def register(registry: Any) -> None:
    """Register this module with the provided registry."""
    registry.register("NDVI", NDVIAnalysis)
