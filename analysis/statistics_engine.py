import numpy as np
from osgeo import gdal
import logging
from typing import Dict, Any, Tuple, Optional

logger = logging.getLogger("RemoteSensingStudio")

class StatisticsEngine:
    """
    A reusable statistics engine that calculates advanced statistics for any continuous raster.
    Aggressively caches results so that histograms and base statistics are not recomputed unnecessarily.
    """
    def __init__(self):
        self._cache_file: Optional[str] = None
        self._cached_array: Optional[np.ndarray] = None
        self._cached_nodata: Optional[float] = None
        self._cached_stats: Dict[str, Any] = {}
        self._cached_histogram: Optional[Tuple[np.ndarray, np.ndarray]] = None

    def _load_raster(self, raster_path: str) -> Tuple[np.ndarray, float]:
        """Loads the raster array and nodata value into memory."""
        if self._cache_file == raster_path and self._cached_array is not None:
            return self._cached_array, self._cached_nodata

        logger.info(f"StatisticsEngine: Loading raster for analysis: {raster_path}")
        dataset = gdal.Open(raster_path)
        if not dataset:
            raise ValueError(f"Failed to open raster: {raster_path}")
            
        band = dataset.GetRasterBand(1)
        nodata = band.GetNoDataValue()
        array = band.ReadAsArray()
        
        # Ensure it's treated as float
        array = array.astype(np.float32)
        
        self._cache_file = raster_path
        self._cached_array = array
        self._cached_nodata = nodata
        
        # Clear stats cache when a new file is loaded
        self._cached_stats.clear()
        self._cached_histogram = None
        
        return array, nodata

    def compute_base_statistics(self, raster_path: str) -> Dict[str, Any]:
        """Computes Minimum, Maximum, Mean, Median, StdDev, Valid Pixels, NoData Pixels."""
        if self._cache_file == raster_path and "min" in self._cached_stats:
            return self._cached_stats

        array, nodata = self._load_raster(raster_path)
        
        if nodata is not None:
            if np.isnan(nodata):
                valid_mask = ~np.isnan(array)
            else:
                valid_mask = (array != nodata)
        else:
            valid_mask = np.ones_like(array, dtype=bool)
            
        valid_pixels = array[valid_mask]
        
        nan_count = int(np.isnan(valid_pixels).sum())
        inf_count = int(np.isinf(valid_pixels).sum())
        
        # Keep only finite pixels for statistical math
        finite_pixels = valid_pixels[np.isfinite(valid_pixels)]
        
        total_pixels = array.size
        valid_count = finite_pixels.size
        nodata_count = total_pixels - valid_pixels.size
        
        if valid_count == 0:
            stats = {
                "min": 0, "max": 0, "mean": 0, "median": 0, "std": 0,
                "total_pixels": total_pixels, "valid_pixels": 0, "nodata_pixels": total_pixels,
                "nan_count": nan_count, "inf_count": inf_count
            }
        else:
            stats = {
                "min": float(np.min(finite_pixels)),
                "max": float(np.max(finite_pixels)),
                "mean": float(np.mean(finite_pixels)),
                "median": float(np.median(finite_pixels)),
                "std": float(np.std(finite_pixels)),
                "total_pixels": int(total_pixels),
                "valid_pixels": int(valid_count),
                "nodata_pixels": int(nodata_count),
                "nan_count": nan_count,
                "inf_count": inf_count
            }
            
        self._cached_stats.update(stats)
        return stats

    def compute_histogram(self, raster_path: str, bins: int = 100) -> Tuple[np.ndarray, np.ndarray]:
        """Computes and caches the histogram for the given raster."""
        if self._cache_file == raster_path and self._cached_histogram is not None:
            if len(self._cached_histogram[0]) == bins:
                return self._cached_histogram

        array, nodata = self._load_raster(raster_path)
        
        if nodata is not None:
            if np.isnan(nodata):
                valid_pixels = array[np.isfinite(array)]
            else:
                valid_pixels = array[(array != nodata) & np.isfinite(array)]
        else:
            valid_pixels = array[np.isfinite(array)]
            
        if valid_pixels.size == 0:
            counts, bin_edges = np.zeros(bins), np.linspace(0, 1, bins + 1)
        else:
            counts, bin_edges = np.histogram(valid_pixels, bins=bins)
            
        self._cached_histogram = (counts, bin_edges)
        return counts, bin_edges

    def compute_class_areas(self, raster_path: str, pixel_area_sqm: float, classes_mask: np.ndarray, num_classes: int) -> Dict[str, Dict[str, float]]:
        """
        Computes area and percentage statistics per class.
        classes_mask should be an array of the same shape as raster, containing class indices (0 to num_classes-1).
        Negative values in classes_mask mean NoData or unclassified.
        """
        results = {}
        total_valid_pixels = np.sum(classes_mask >= 0)
        
        for cls_idx in range(num_classes):
            cls_pixels = np.sum(classes_mask == cls_idx)
            area_sqm = cls_pixels * pixel_area_sqm
            
            percentage = (cls_pixels / total_valid_pixels * 100) if total_valid_pixels > 0 else 0.0
            
            results[f"class_{cls_idx}"] = {
                "pixel_count": int(cls_pixels),
                "percentage": float(percentage),
                "area_sqm": float(area_sqm),
                "area_ha": float(area_sqm / 10000.0),
                "area_km2": float(area_sqm / 1000000.0),
                "area_acres": float(area_sqm * 0.000247105),
                "area_feddans": float(area_sqm * 0.000238)
            }
            
        return results
