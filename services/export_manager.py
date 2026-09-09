import os
import math
import tempfile
import urllib.request
import urllib.parse
from typing import Dict, Any, List, Tuple
from ..utils.logger import get_logger
import rasterio
from rasterio.merge import merge
from rasterio.transform import Affine

class ExportManager:
    """
    Dedicated manager for Earth Engine export strategies, risk estimation, 
    dynamic tile generation, and local merging.
    """
    
    # Configurable limits (in Megabytes)
    MAX_DIRECT_DOWNLOAD_MB = 30.0
    TARGET_TILE_MB = 20.0
    MAX_TILED_DOWNLOAD_MB = 500.0
    BYTES_PER_PIXEL = 4 # Assuming Float32
    
    def __init__(self):
        self.logger = get_logger(__name__)
        
    def _normalize_geojson(self, geojson: Dict[str, Any]) -> Dict[str, Any]:
        """Extracts the base geometry from wrappers, Features, or FeatureCollections."""
        if isinstance(geojson, dict) and "geojson" in geojson:
            geojson = geojson["geojson"]
            
        if geojson.get("type") == "FeatureCollection":
            features = geojson.get("features", [])
            if features:
                geojson = features[0].get("geometry", geojson)
        elif geojson.get("type") == "Feature":
            geojson = geojson.get("geometry", geojson)
            
        self.logger.info(f"ExportManager received GeoJSON type: {geojson.get('type')}")
        return geojson
        
    def _get_bounds(self, coords: list) -> Tuple[float, float, float, float]:
        """Recursively flattens coordinates to find the bounding box."""
        lons, lats = [], []
        def flatten(lst):
            if not isinstance(lst, list) or not lst: return
            if isinstance(lst[0], (int, float)):
                lons.append(lst[0])
                lats.append(lst[1])
            else:
                for item in lst: flatten(item)
        
        flatten(coords)
        if not lons or not lats:
            return 0.0, 0.0, 0.0, 0.0
        return min(lons), min(lats), max(lons), max(lats)
        
    def estimate_export_risk(self, aoi_geojson: Dict[str, Any], resolution: float, bands: int = 1) -> Dict[str, Any]:
        """
        Estimates the export size and returns risk metrics.
        """
        normalized_geom = self._normalize_geojson(aoi_geojson)
        coords = normalized_geom.get('coordinates', [])
        
        geom_type = normalized_geom.get('type', '')
        if not coords or geom_type not in ['Polygon', 'MultiPolygon']:
            self.logger.warning(f"Unsupported geometry type for estimation: {geom_type}")
            return {"estimated_mb": 0.0, "strategy": "Direct Download", "bounds": (0,0,0,0)}
            
        w, s, e, n = self._get_bounds(coords)
        
        # Rough square meters estimation (1 degree = ~111km)
        width_m = (e - w) * 111320 * math.cos(math.radians((s + n) / 2))
        height_m = (n - s) * 111320
        area_sqm = abs(width_m * height_m)
        
        # Pixels
        pixel_count = area_sqm / (resolution ** 2)
        bytes_size = pixel_count * bands * self.BYTES_PER_PIXEL
        
        # Add 20% overhead for GeoTIFF headers/compression
        estimated_mb = (bytes_size * 1.2) / (1024 * 1024)
        
        strategy = "Direct Download"
        if estimated_mb > self.MAX_TILED_DOWNLOAD_MB:
            strategy = "Earth Engine Export Task"
        elif estimated_mb > self.MAX_DIRECT_DOWNLOAD_MB:
            strategy = "Automatic Tiled Download"
            
        try:
            self.logger.info("==================================================")
            self.logger.info("[DIAGNOSTIC]")
            self.logger.info("==================================================")
            self.logger.info(f"[DIAGNOSTIC] Estimated Width: {width_m}")
            self.logger.info(f"[DIAGNOSTIC] Estimated Height: {height_m}")
            self.logger.info(f"[DIAGNOSTIC] Estimated Area: {area_sqm}")
            self.logger.info(f"[DIAGNOSTIC] Estimated Pixels: {pixel_count}")
            self.logger.info(f"[DIAGNOSTIC] Estimated MB: {estimated_mb}")
            self.logger.info(f"[DIAGNOSTIC] Selected Strategy: {strategy}")
            self.logger.info(f"[DIAGNOSTIC] Reason for selecting that strategy: Size vs Thresholds (Max Direct={self.MAX_DIRECT_DOWNLOAD_MB}, Max Tiled={self.MAX_TILED_DOWNLOAD_MB})")
        except Exception as diag_e:
            self.logger.error(f"[DIAGNOSTIC] Failed to log estimation diagnostics: {diag_e}")
            
        
        return {
            "estimated_mb": round(estimated_mb, 2),
            "pixel_count": pixel_count,
            "strategy": strategy,
            "bounds": (w, s, e, n)
        }
        
    def generate_tiles(self, bounds: Tuple[float, float, float, float], estimated_mb: float, aoi_geojson: Dict[str, Any], pixel_count: float = None) -> List[Dict[str, Any]]:
        """
        Dynamically generates geographic grid tiles targeting pixel-based thresholds 
        using a deterministic QuadTree spatial decomposition algorithm based on AOI intersection.
        """
        w, s, e, n = bounds
        
        if estimated_mb <= self.TARGET_TILE_MB:
            normalized_geom = self._normalize_geojson(aoi_geojson)
            try:
                import json
                self.logger.info("==================================================")
                self.logger.info("[DIAGNOSTIC]")
                self.logger.info("==================================================")
                self.logger.info(f"[DIAGNOSTIC] Tile Number: 1 (Small AOI - PRESERVING EXACT POLYGON)")
                self.logger.info(f"[DIAGNOSTIC] Bounding Box: [w={w}, s={s}, e={e}, n={n}]")
                self.logger.info(f"[DIAGNOSTIC] GeoJSON dictionary: {json.dumps(normalized_geom)}")
            except Exception as diag_e:
                self.logger.error(f"[DIAGNOSTIC] Failed to log small AOI tile diagnostics: {diag_e}")
            return [normalized_geom]
            
        from shapely.geometry import shape, box
        from .. import config
        
        aoi_shape = shape(self._normalize_geojson(aoi_geojson))
        total_aoi_area = aoi_shape.area
        
        if not pixel_count:
            pixel_count = (estimated_mb * 1024 * 1024 / 1.2) / self.BYTES_PER_PIXEL
            
        target_pixels_per_tile = config.TARGET_PIXELS_PER_TILE
        strategy = getattr(config, "TILE_SIZING_STRATEGY", "PHASE1")
        
        base_pixels = config.TARGET_PIXELS_PER_TILE
        base_over_partition = config.OVER_PARTITION_FACTOR
        
        if strategy == "GREEDY_x2":
            base_pixels = 20_000_000
            base_over_partition = 2
        elif strategy == "GREEDY_x4":
            base_pixels = 40_000_000
            base_over_partition = 1
        elif strategy == "MAXIMUM":
            base_pixels = 1_000_000_000 # GEE maxPixels
            base_over_partition = 1
        elif strategy == "AUTO_PROGRESSIVE":
            base_pixels = 160_000_000 # Let worker dynamically sub-divide
            base_over_partition = 1
            
        if pixel_count and pixel_count > 0:
            optimal_target = pixel_count / (config.CONCURRENT_DOWNLOADS * base_over_partition)
            # If AUTO_PROGRESSIVE or MAXIMUM, don't clip it down to optimal_target, let it be greedy
            if strategy in ["AUTO_PROGRESSIVE", "MAXIMUM"]:
                target_pixels_per_tile = base_pixels
            else:
                target_pixels_per_tile = max(config.MIN_TILE_PIXEL_COUNT, min(base_pixels, optimal_target))
        
        # Calculate the maximum area a single tile should cover to meet the target_pixels_per_tile
        target_area = total_aoi_area * (target_pixels_per_tile / pixel_count) if pixel_count > 0 else total_aoi_area
        
        tiles = []
        
        def subdivide(q_w, q_s, q_e, q_n):
            current_box = box(q_w, q_s, q_e, q_n)
            
            # Use intersection to determine if this quadrant contains valid AOI data
            try:
                intersection = aoi_shape.intersection(current_box)
            except Exception:
                # Fallback to true if shapely fails topology
                intersection = current_box
                
            if intersection.is_empty:
                return # Discard empty tile
                
            # If the intersecting data is small enough, or the quadrant is too small to split safely (e.g. 0.0001 deg)
            if intersection.area <= target_area or (q_e - q_w) < 0.0001:
                # Priority = expected pixel count
                expected_pixels = (intersection.area / total_aoi_area) * pixel_count if total_aoi_area > 0 else target_pixels_per_tile
                tile_dict = {
                    "type": "Polygon",
                    "depth": 0,
                    "expected_pixels": expected_pixels,
                    "priority": expected_pixels,
                    "parent_id": None,
                    "coordinates": [[
                        [q_w, q_s],
                        [q_e, q_s],
                        [q_e, q_n],
                        [q_w, q_n],
                        [q_w, q_s]
                    ]]
                }
                try:
                    import json
                    self.logger.info("==================================================")
                    self.logger.info("[DIAGNOSTIC]")
                    self.logger.info("==================================================")
                    self.logger.info(f"[DIAGNOSTIC] Tile Number: {len(tiles) + 1}")
                    self.logger.info(f"[DIAGNOSTIC] Bounding Box: [w={q_w}, s={q_s}, e={q_e}, n={q_n}]")
                    self.logger.info(f"[DIAGNOSTIC] Width: {q_e - q_w}")
                    self.logger.info(f"[DIAGNOSTIC] Height: {q_n - q_s}")
                    self.logger.info(f"[DIAGNOSTIC] Area: {(q_e - q_w) * (q_n - q_s)}")
                    self.logger.info(f"[DIAGNOSTIC] GeoJSON dictionary: {json.dumps(tile_dict)}")
                    self.logger.info(f"[DIAGNOSTIC] Vertex Count: 5")
                    self.logger.info(f"[DIAGNOSTIC] Whether ring is closed: {tile_dict['coordinates'][0][0] == tile_dict['coordinates'][0][-1]}")
                except Exception as diag_e:
                    self.logger.error(f"[DIAGNOSTIC] Failed to log tile diagnostics: {diag_e}")
                tiles.append(tile_dict)
            else:
                mid_x = q_w + (q_e - q_w) / 2
                mid_y = q_s + (q_n - q_s) / 2
                
                # Deterministic ordering: Bottom-Left, Bottom-Right, Top-Left, Top-Right
                subdivide(q_w, q_s, mid_x, mid_y)
                subdivide(mid_x, q_s, q_e, mid_y)
                subdivide(q_w, mid_y, mid_x, q_n)
                subdivide(mid_x, mid_y, q_e, q_n)
                
        subdivide(w, s, e, n)
        
        # Failsafe in case quadtree returns 0 tiles due to extreme floating point rounding
        if not tiles:
            tile_dict = {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}
            try:
                import json
                self.logger.info("==================================================")
                self.logger.info("[DIAGNOSTIC]")
                self.logger.info("==================================================")
                self.logger.info(f"[DIAGNOSTIC] Tile Number: 1 (Failsafe)")
                self.logger.info(f"[DIAGNOSTIC] Bounding Box: [w={w}, s={s}, e={e}, n={n}]")
                self.logger.info(f"[DIAGNOSTIC] Width: {e - w}")
                self.logger.info(f"[DIAGNOSTIC] Height: {n - s}")
                self.logger.info(f"[DIAGNOSTIC] Area: {(e - w) * (n - s)}")
                self.logger.info(f"[DIAGNOSTIC] GeoJSON dictionary: {json.dumps(tile_dict)}")
                self.logger.info(f"[DIAGNOSTIC] Vertex Count: 5")
                self.logger.info(f"[DIAGNOSTIC] Whether ring is closed: {tile_dict['coordinates'][0][0] == tile_dict['coordinates'][0][-1]}")
            except Exception as diag_e:
                self.logger.error(f"[DIAGNOSTIC] Failed to log failsafe tile diagnostics: {diag_e}")
            return [tile_dict]
            
        return tiles

    def merge_tiles_locally(self, tile_paths: List[str], output_path: str) -> bool:
        """
        Merges multiple GeoTIFF files into a single seamless GeoTIFF using rasterio.
        """
        if not tile_paths:
            return False
            
        if len(tile_paths) == 1:
            import shutil
            shutil.copy2(tile_paths[0], output_path)
            return True
            
        try:
            src_files_to_mosaic = []
            for fp in tile_paths:
                src = rasterio.open(fp)
                src_files_to_mosaic.append(src)
                
            mosaic, out_trans = merge(src_files_to_mosaic)
            
            # Copy metadata from the first tile
            out_meta = src_files_to_mosaic[0].meta.copy()
            out_meta.update({
                "driver": "GTiff",
                "height": mosaic.shape[1],
                "width": mosaic.shape[2],
                "transform": out_trans,
                "compress": "lzw"
            })
            
            with rasterio.open(output_path, "w", **out_meta) as dest:
                dest.write(mosaic)
                
            for src in src_files_to_mosaic:
                src.close()
                
            return True
        except Exception as e:
            self.logger.error(f"Error merging tiles locally: {e}")
            return False

    def mask_raster_locally(self, input_path: str, aoi_geojson: Dict[str, Any], output_path: str, nodata_value=None) -> bool:
        """
        Locally crops and masks the GeoTIFF to the exact polygon boundary using rasterio.
        Pixels outside the polygon are set to a safe NoData value.
        """
        try:
            import rasterio
            from rasterio.mask import mask
            import rasterio.warp
            import shapely.geometry
            import numpy as np
            
            normalized_geom = self._normalize_geojson(aoi_geojson)
            
            with rasterio.open(input_path) as src:
                src_crs = src.crs
                
                # Transform geometry if CRS is different
                if src_crs:
                    geom_crs = "EPSG:4326"
                    try:
                        normalized_geom = rasterio.warp.transform_geom(
                            geom_crs, 
                            src_crs, 
                            normalized_geom
                        )
                    except Exception as e:
                        self.logger.warning(f"Geometry CRS transformation failed: {e}")
                        
                geom_shape = shapely.geometry.shape(normalized_geom)
                
                # Determine safe NoData value to prevent Float64 upcasting
                dtype = src.profile['dtype']
                
                if nodata_value is None:
                    if src.nodata is not None:
                        nodata_value = src.nodata
                    else:
                        if np.issubdtype(dtype, np.integer):
                            if np.issubdtype(dtype, np.unsignedinteger):
                                nodata_value = np.iinfo(dtype).max # Use Max for UInt (e.g. 65535)
                            else:
                                nodata_value = -9999 # Use -9999 for signed ints
                        else:
                            nodata_value = -9999.0
                            
                out_image, out_transform = mask(src, [geom_shape], crop=True, nodata=nodata_value)
                
                # CRITICAL: Force preservation of input dtype to avoid Float64 upcasting
                if out_image.dtype != dtype:
                    out_image = out_image.astype(dtype)
                    
                out_meta = src.meta.copy()
                
                out_meta.update({
                    "driver": "GTiff",
                    "height": out_image.shape[1],
                    "width": out_image.shape[2],
                    "transform": out_transform,
                    "nodata": nodata_value
                })
                
                # Copy tags but strip stale GDAL statistics tags
                tags = src.tags().copy()
                stale_keys = [
                    "STATISTICS_MINIMUM", "STATISTICS_MAXIMUM", "STATISTICS_MEAN",
                    "STATISTICS_STDDEV", "STATISTICS_VALID_PERCENT"
                ]
                for key in list(tags.keys()):
                    if key in stale_keys or key.startswith("STATISTICS_"):
                        del tags[key]
                
                with rasterio.open(output_path, "w", **out_meta) as dest:
                    dest.update_tags(**tags)
                    dest.write(out_image)
                    
            # Remove any associated stale .aux.xml statistics file
            aux_file = output_path + ".aux.xml"
            import os
            if os.path.exists(aux_file):
                try:
                    os.remove(aux_file)
                except Exception as e:
                    self.logger.warning(f"Failed to remove stale aux file {aux_file}: {e}")
                    
            # Post-mask validation of NoData persistence
            with rasterio.open(output_path) as chk:
                if chk.nodata is None or not np.isclose(chk.nodata, nodata_value):
                    self.logger.warning(f"ExportManager: NoData value mismatch after masking. Expected {nodata_value}, got {chk.nodata}")
                    
            return True
        except Exception as e:
            self.logger.error(f"Error masking raster locally: {e}", exc_info=True)
            return False
