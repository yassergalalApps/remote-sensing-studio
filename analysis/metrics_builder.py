import logging
from typing import Any, Dict, List

class AnalysisMetricsBuilder:
    """
    Authoritative shared component for computing scientific reporting metrics.
    Ensures that both legacy and generic pipelines generate identical, scientifically accurate reports.
    """
    
    @staticmethod
    def compute_collection_metrics(collection: Any, selection_mode: str, image_ids: List[str] = None) -> Dict[str, Any]:
        """Computes the number of scenes found and used in the composite."""
        metrics = {"Images Found": 0, "Images Used": 0, "Images Rejected": 0, "Method": selection_mode}
        
        if image_ids and len(image_ids) > 0:
            metrics["Images Found"] = len(image_ids)
            metrics["Images Used"] = len(image_ids)
            
        try:
            import ee
            # Extract actual dates and IDs from the final collection
            def get_metadata(img):
                return ee.Feature(None, {
                    'system:time_start': img.get('system:time_start'),
                    'system:index': img.get('system:index'),
                    'system:id': img.get('system:id')
                })
                
            features = collection.map(get_metadata).getInfo()
            actual_dates = []
            actual_ids = []
            
            if features and 'features' in features:
                from datetime import datetime, UTC
                for f in features['features']:
                    props = f.get('properties', {})
                    ts = props.get('system:time_start')
                    sys_id = props.get('system:id')
                    idx = props.get('system:index')
                    final_id = sys_id if sys_id else idx
                    
                    if ts:
                        dt = datetime.fromtimestamp(ts / 1000.0, UTC).strftime('%Y-%m-%d')
                        actual_dates.append(dt)
                    if final_id:
                        actual_ids.append(final_id)
            
            metrics["Actual Dates"] = actual_dates
            metrics["Actual IDs"] = actual_ids

            # Synchronously count scenes in Earth Engine
            count = len(actual_dates) if actual_dates else collection.size().getInfo()
            metrics["Images Found"] = count
            
            if selection_mode in ['Median', 'Mean', 'Mosaic', 'Quality Mosaic', 'Best Pixel']:
                metrics["Images Used"] = count
            else:
                metrics["Images Used"] = 1 if count > 0 else 0
        except Exception as e:
            logging.getLogger(__name__).warning(f"Failed to compute collection size: {e}")
            metrics["Images Found"] = 1
            metrics["Images Used"] = 1
            
        return metrics

    @staticmethod
    def compute_image_statistics(img: Any, geom: Any, scale: float) -> Dict[str, Any]:
        """Executes a Reducer on Earth Engine to extract standard raster statistics."""
        try:
            import ee
            stats_reducer = ee.Reducer.minMax().combine(ee.Reducer.mean(), '', True)\
                                               .combine(ee.Reducer.median(), '', True)\
                                               .combine(ee.Reducer.stdDev(), '', True)
                                               
            stats = img.reduceRegion(
                reducer=stats_reducer,
                geometry=geom,
                scale=scale,
                maxPixels=1e9
            ).getInfo()
            return stats
        except Exception as e:
            logging.getLogger(__name__).error(f"Failed to compute statistics: {e}")
            return {}

    @staticmethod
    def format_statistics(stats: Dict[str, Any], band_name: str) -> Dict[str, float]:
        """Formats raw Earth Engine statistics into a clean dictionary."""
        if not stats:
            return {"Min": 0.0, "Max": 0.0, "Mean": 0.0, "Median": 0.0, "StdDev": 0.0}
            
        return {
            "Min": round(stats.get(f"{band_name}_min", 0), 4),
            "Max": round(stats.get(f"{band_name}_max", 0), 4),
            "Mean": round(stats.get(f"{band_name}_mean", 0), 4),
            "Median": round(stats.get(f"{band_name}_median", 0), 4),
            "StdDev": round(stats.get(f"{band_name}_stdDev", 0), 4)
        }

    @staticmethod
    def build_metadata(sat_info: Dict[str, Any], req_res_str: str, scale: float, acq_dates: List[str]) -> Dict[str, Any]:
        """Constructs standardized metadata for the scientific report."""
        return {
            "processing_level": sat_info.get("level", "Unknown"),
            "masks_applied": sat_info.get("qa_masks", []),
            "requested_resolution": req_res_str,
            "actual_resolution": f"{scale}m",
            "resolution": f"{scale}m (Mode: {req_res_str})",
            "acquisition_dates": acq_dates
        }
