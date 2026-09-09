import abc
import urllib.request
import os

class DownloadProvider(abc.ABC):
    """
    Abstract base class for Earth Engine download strategies.
    Provides a standardized interface for fetching tiles, allowing A/B benchmarking 
    between different EE REST APIs.
    """
    @abc.abstractmethod
    def download_tile(self, image, tile_geojson, scale, crs, file_path, timeout):
        pass


class LegacyDownloadProvider(DownloadProvider):
    """
    Current implementation using getDownloadURL.
    """
    def download_tile(self, image, tile_geojson, scale, crs, file_path, timeout):
        import ee
        
        # Unwrap if it's passed from aoi_geojson format
        if isinstance(tile_geojson, dict) and "geojson" in tile_geojson:
            tile_geojson = tile_geojson["geojson"]
            
        geom = ee.Geometry(tile_geojson)
        final_img = image.clip(geom)
        
        
        params = dict(
            region=geom,
            scale=scale,
            format='GEO_TIFF',
            crs=crs,
            maxPixels=1e9, # Rely on GEE's internal backend limits
            filePerBand=False
        )
        
        url = final_img.getDownloadURL(params)
        
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = response.read()
            with open(file_path, 'wb') as f:
                f.write(data)
                
        # CRITICAL FIX: Inform GDAL/QGIS that -9999.0 is NoData
        try:
            import logging
            logger = logging.getLogger(__name__)
            import sys
            from ..config import EVI_DEBUG
            debug_mode = getattr(sys.modules.get('remote_sensing_studio.config', None), 'EVI_DEBUG', False) or EVI_DEBUG
            
            def diag_tiff_str(stage_letter, stage_name, fp):
                try:
                    import rasterio
                    import numpy as np
                    with rasterio.open(fp) as src:
                        nd = src.nodata
                        arr = src.read(1)
                        if nd is not None:
                            valid_arr = arr[arr != nd]
                        else:
                            valid_arr = arr
                            
                        fin = valid_arr[np.isfinite(valid_arr)]
                        nan_c = np.count_nonzero(np.isnan(valid_arr))
                        inf_c = np.count_nonzero(np.isinf(valid_arr))
                        mi = np.min(fin) if fin.size > 0 else "N/A"
                        ma = np.max(fin) if fin.size > 0 else "N/A"
                        
                        lines = [
                            f"{stage_letter}. {stage_name}",
                            f"dtype: {src.dtypes[0]}",
                            f"existing NoData: {nd}",
                            f"finite count: {len(fin)}",
                            f"NaN count: {nan_c}",
                            f"Inf count: {inf_c}",
                            f"finite min: {mi}",
                            f"finite max: {ma}",
                            ""
                        ]
                        return "\n".join(lines)
                except Exception as e:
                    return f"{stage_letter}. {stage_name}\nFailed to read TIFF: {e}\n"
                    
            if debug_mode:
                try:
                    from ..analysis.diagnostic_utils import write_evi_diagnostic
                    out_f = diag_tiff_str("F", "DOWNLOAD TIFF BEFORE SetNoDataValue", file_path)
                    write_evi_diagnostic(out_f)
                except Exception as e:
                    logger.error(f"Failed to log Phase F: {e}")

            from osgeo import gdal
            ds = gdal.Open(file_path, gdal.GA_Update)
            if ds:
                band = ds.GetRasterBand(1)
                band.SetNoDataValue(-9999.0)
                band.FlushCache()
                ds = None
                
                if debug_mode:
                    try:
                        out_g = diag_tiff_str("G", "TIFF AFTER SetNoDataValue(-9999)", file_path)
                        write_evi_diagnostic(out_g)
                        write_evi_diagnostic("===== EVI DIAGNOSTIC END =====\n")
                    except Exception as e:
                        logger.error(f"Failed to log Phase G: {e}")
                
                # Validation step
                ds_verify = gdal.Open(file_path)
                verify_band = ds_verify.GetRasterBand(1)
                if verify_band.GetNoDataValue() != -9999.0:
                    logger.warning("LegacyDownloadProvider: GDAL failed to persist NoData metadata.")
                ds_verify = None
            else:
                logger.warning("GDAL SetNoDataValue FAILED: ds is None")
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"GDAL SetNoDataValue FAILED with Exception: {e}")


class ComputePixelsProvider(DownloadProvider):
    """
    New experimental implementation using the High-Volume Compute API (ee.data.computePixels).
    This API scales better for concurrency and returns bytes directly without a 2-step URL process.
    """
    def download_tile(self, image, tile_geojson, scale, crs, file_path, timeout):
        import ee
        
        if isinstance(tile_geojson, dict) and "geojson" in tile_geojson:
            tile_geojson = tile_geojson["geojson"]
            
        geom = ee.Geometry(tile_geojson)
        final_img = image.clip(geom)
        
        params = dict(
            expression=final_img,
            region=geom,
            scale=scale,
            fileFormat='GEO_TIFF',
            crs=crs,
            grid=None
        )
        
        # computePixels fetches the raw binary payload directly.
        # It manages its own internal timeouts via the ee python client httplib2/google-auth stack.
        data = ee.data.computePixels(params)
        with open(file_path, 'wb') as f:
            f.write(data)
            
        # CRITICAL FIX: Inform GDAL/QGIS that -9999.0 is NoData
        try:
            from osgeo import gdal
            ds = gdal.Open(file_path, gdal.GA_Update)
            if ds:
                band = ds.GetRasterBand(1)
                band.SetNoDataValue(-9999.0)
                band.FlushCache()
                ds = None
                
                ds_verify = gdal.Open(file_path)
                if ds_verify.GetRasterBand(1).GetNoDataValue() != -9999.0:
                    import logging
                    logging.getLogger(__name__).warning("ComputePixelsProvider: GDAL failed to persist NoData metadata.")
                ds_verify = None
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"ComputePixelsProvider SetNoDataValue failed: {e}")
