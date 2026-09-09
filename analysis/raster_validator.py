import numpy as np
from osgeo import gdal
import logging

class RasterValidator:
    """
    Validates that a GeoTIFF meets the scientific contract for analysis outputs.
    Operates completely offline using GDAL and NumPy.
    """

    @staticmethod
    def _base_validation(file_path: str, expected_nodata: float) -> dict:
        dataset = gdal.Open(file_path)
        if not dataset:
            return {"passed": False, "reason": "Could not open raster file."}

        band = dataset.GetRasterBand(1)
        nodata_val = band.GetNoDataValue()
        
        if nodata_val is None or not np.isclose(nodata_val, expected_nodata):
            return {
                "passed": False, 
                "reason": f"NoData value mismatch. Expected {expected_nodata}, got {nodata_val}."
            }

        array = band.ReadAsArray()
        if array is None:
            return {"passed": False, "reason": "Failed to read raster data array."}
            
        dtype_name = gdal.GetDataTypeName(band.DataType)
        if dtype_name != "Float32":
            return {
                "passed": False,
                "reason": f"Expected Float32 datatype, got {dtype_name}."
            }

        # Create a mask for VALID pixels (not nodata)
        if np.isnan(expected_nodata):
            valid_mask = ~np.isnan(array)
        else:
            valid_mask = array != expected_nodata

        valid_pixels = array[valid_mask]
        
        nan_count = int(np.isnan(valid_pixels).sum())
        inf_count = int(np.isinf(valid_pixels).sum())
        
        # --- NEW DIAGNOSTIC LOGGING ---
        try:
            logger = logging.getLogger(__name__)
            logger.info("=== RASTER VALIDATOR DIAGNOSTICS ===")
            logger.info(f"Raster path: {file_path}")
            logger.info(f"Raster dtype: {dtype_name}")
            logger.info(f"Raster nodata (metadata): {nodata_val}")
            logger.info(f"Raster nodata (expected): {expected_nodata}")
            logger.info(f"Total pixels: {array.size}")
            logger.info(f"NoData pixels: {array.size - valid_pixels.size}")
            
            all_finite = np.isfinite(array).sum()
            all_nan = np.isnan(array).sum()
            all_inf = np.isinf(array).sum()
            
            logger.info(f"Global Finite pixels: {all_finite}")
            logger.info(f"Global NaN pixels: {all_nan}")
            logger.info(f"Global Inf pixels: {all_inf}")
            
            logger.info(f"Valid-data (non-nodata) Finite pixels: {valid_pixels.size - nan_count - inf_count}")
            logger.info(f"Valid-data (non-nodata) NaN pixels: {nan_count}")
            logger.info(f"Valid-data (non-nodata) Inf pixels: {inf_count}")
            logger.info("====================================")
        except Exception:
            pass
        # ------------------------------

        if nan_count > 0 or inf_count > 0:
            return {
                "passed": False,
                "reason": f"Raster contains NaN ({nan_count}) or Inf ({inf_count}) in valid data regions.",
                "nan_count": nan_count,
                "inf_count": inf_count
            }

        return {
            "passed": True,
            "valid_pixels": valid_pixels,
            "total_pixels": array.size,
            "nodata_count": array.size - valid_pixels.size
        }


    @staticmethod
    def validate_evi_raster(file_path: str, valid_min: float = -0.2, valid_max: float = 1.0, expected_nodata: float = -9999.0) -> dict:
        """
        Specific scientific validation for EVI ensuring values remain within physical limits.
        """
        report = RasterValidator._base_validation(file_path, expected_nodata)
        if not report["passed"]:
            return report
            
        valid_pixels = report.pop("valid_pixels")
        if valid_pixels.size == 0:
            return {"passed": True, "reason": "Raster contains only NoData. Trivially valid.", **report}
            
        out_of_range_mask = (valid_pixels < valid_min) | (valid_pixels > valid_max)
        out_of_range_count = out_of_range_mask.sum()
        
        if out_of_range_count > 0:
            return {
                "passed": False,
                "reason": f"Found {out_of_range_count} pixels outside valid EVI range [{valid_min}, {valid_max}].",
                "out_of_range_count": int(out_of_range_count)
            }
            
        report["passed"] = True
        return report

    @staticmethod
    def validate_generic_raster(file_path: str, expected_nodata: float = -9999.0) -> dict:
        """
        Generic validation for indices without strict bounds, checking only for NaN/Inf.
        """
        report = RasterValidator._base_validation(file_path, expected_nodata)
        if "valid_pixels" in report:
            del report["valid_pixels"]
        return report
