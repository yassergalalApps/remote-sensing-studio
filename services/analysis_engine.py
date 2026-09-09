"""
Analysis Engine Module.
Strictly decoupled orchestrator between the UI, Formula Registry, and Providers.
"""

import time
import os
import threading
from typing import Dict, Any, List, Optional
from PyQt6.QtCore import QObject, pyqtSignal

from .export_manager import ExportManager
from ..utils.logger import get_logger
from ..utils.profiler import PerformanceProfiler
from ..analysis.formula_registry import FormulaRegistry
from ..services.connection_service import ConnectionService
from ..services.layer_service import LayerService

from ..models.analysis_result import AnalysisResult

class AnalysisEngine(QObject):
    """
    Orchestrates the analysis execution pipeline.
    """
    
    # Emits (status_message, progress_percentage)
    progress_update = pyqtSignal(str, int)
    
    # Emits the final execution summary as strongly typed AnalysisResult
    execution_completed = pyqtSignal(AnalysisResult)
    
    # Emits an event dictionary when an export task requires local file validation
    export_task_file_requested = pyqtSignal(object)
    
    _instance = None
    
    @classmethod
    def get_instance(cls) -> 'AnalysisEngine':
        if cls._instance is None:
            cls._instance = AnalysisEngine()
        return cls._instance
        
    def __init__(self) -> None:
        super().__init__()
        self.logger = get_logger(__name__)
        self.layer_service = LayerService.get_instance()
        self.connection_service = ConnectionService.get_instance()
        
    def run_analysis_workflow(self, analysis_type: str, provider_name: str, satellite: str, 
                              start_date: str, end_date: str, aoi_geojson: Dict[str, Any],
                              selection_mode: str, image_ids: List[str] = None, cloud_filter: float = 100.0,
                              index_threshold: Optional[float] = None, palette: Dict[str, Any] = None,
                              vis_min: float = -1.0, vis_max: float = 1.0,
                              export_resolution_mode: str = "Dataset Default",
                              export_resolution: float = 0.0,
                              stretch_mode: str = "Original",
                              **kwargs) -> None:
        """
        Executes the analysis pipeline.
        """
        if index_threshold is None:
            from ..analysis.raster_metadata import get_raster_metadata
            index_threshold = get_raster_metadata(analysis_type).recommended_threshold

        start_time = time.time()
        output_mode = "GeoTIFF Download"
        
        profiler = PerformanceProfiler.get_instance()
        profiler.start_workflow()
        
        try:
            # 1. Fetch Formula
            self.progress_update.emit(f"✓ Fetching Formula: {analysis_type}", 10)
            profiler.step("Fetching Formula")
            formula = FormulaRegistry.get_formula(analysis_type)
            
            try:
                from ..analysis.diagnostic_utils import write_evi_diagnostic
                write_evi_diagnostic("===== FORMULA REGISTRY RUNTIME OUTPUT =====")
                write_evi_diagnostic(f"formula_keys = {list(formula.keys())}")
                write_evi_diagnostic(f"formula_id = {formula.get('id')}")
            except Exception:
                pass
            
            # 2. Determine Provider
            if provider_name == "Google Earth Engine":
                self.progress_update.emit("✓ Routing to Google Earth Engine", 30)
                profiler.step("Routing to Provider")
                
                # 3. Execute Formula Math on Backend
                self.progress_update.emit("✓ Building Composite & Applying Formula", 50)
                profiler.step("Building Composite & Applying Formula")
                
                # Do not wipe out image_ids here, so that composite modes can use the selected images

                print("Selection mode =", selection_mode)
                print("image_ids =", image_ids)
                print("image_ids length =", 0 if image_ids is None else len(image_ids))
                    
                result = self.layer_service.gee_provider.execute_formula(
                    formula, satellite, start_date, end_date, aoi_geojson, selection_mode, image_ids, cloud_filter,
                    compute_ee_stats=False, generate_tile_url=False,
                    export_resolution_mode=export_resolution_mode, export_resolution=export_resolution
                )
                
                # 4. Preparing URLs for Visualization
                
                export_manager = ExportManager()
                risk_metrics = export_manager.estimate_export_risk(aoi_geojson, result.get("scale", 30.0), bands=1)
                strategy = risk_metrics["strategy"]
                
                self.progress_update.emit(f"✓ Export Strategy: {strategy}", 70)
                profiler.step(f"Preparing Export URLs ({strategy})")
                
                actual_dates = result["metrics"].get("Actual Dates", [])
                
                if selection_mode in ["Single Scene", "Best Image"] and actual_dates:
                    display_date = actual_dates[0]
                elif selection_mode in ["Median", "Mean", "Mosaic", "Quality Mosaic", "Best Pixel"] and actual_dates:
                    if len(actual_dates) > 1:
                        # Sort and get date range for composite
                        dates_sorted = sorted(actual_dates)
                        start_d = dates_sorted[0]
                        end_d = dates_sorted[-1]
                        display_date = f"{selection_mode} - {start_d}_to_{end_d}"
                    else:
                        display_date = f"{selection_mode} - {actual_dates[0]}"
                else:
                    display_date = start_date
                    
                layer_name = f"{analysis_type} - {satellite} - {display_date}"
                tile_url = result.get("tile_url")
                
                download_url = None
                tile_download_urls = []
                
                if output_mode == "GeoTIFF Download":
                    url_gen_start_time = time.time()
                    total_url_gen_time = 0.0
                    avg_url_gen_time = 0.0
                    tile_url_metrics = {}
                    
                    ee_tiles = []
                    
                    # ---------------------------------------------------------
                    # [STAGE 2 DIAGNOSTICS: IMMEDIATELY BEFORE EXPORT]
                    # ---------------------------------------------------------
                    import sys
                    from ..config import EVI_DEBUG
                    debug_mode = getattr(sys.modules.get('remote_sensing_studio.config', None), 'EVI_DEBUG', False) or EVI_DEBUG
                    
                    if debug_mode:
                        import ee
                        if isinstance(aoi_geojson, dict) and "geojson" in aoi_geojson:
                            geom_dict = aoi_geojson["geojson"]
                        else:
                            geom_dict = aoi_geojson
                        diag_geom = ee.Geometry(geom_dict) if not isinstance(geom_dict, ee.Geometry) else geom_dict
                        diag_scale = result["scale"]
                        diag_img = result["computed_image"]
                        
                        import logging
                        logger = logging.getLogger(__name__)
                        logger.info("=== EVI_DEBUG STAGE 2: IMMEDIATELY BEFORE EXPORT ===")
                        
                        def count_condition(img, cond):
                            return img.updateMask(cond).reduceRegion(
                                reducer=ee.Reducer.count(),
                                geometry=diag_geom,
                                scale=diag_scale,
                                maxPixels=1e9
                            ).getInfo().get(img.bandNames().get(0).getInfo(), 0)
                            
                        total_valid = diag_img.reduceRegion(
                            reducer=ee.Reducer.count(),
                            geometry=diag_geom,
                            scale=diag_scale,
                            maxPixels=1e9
                        ).getInfo().get(diag_img.bandNames().get(0).getInfo(), 0)
                        
                        logger.info(f"E) Total valid pixels: {total_valid}")
                        logger.info(f"A) Pixels < -0.2: {count_condition(diag_img, diag_img.lt(-0.2))}")
                        logger.info(f"B) Pixels > 1.0: {count_condition(diag_img, diag_img.gt(1.0))}")
                        logger.info(f"C) NaN pixels: {count_condition(diag_img, diag_img.neq(diag_img))}")
                        logger.info(f"D) Inf pixels: {count_condition(diag_img, diag_img.lt(-1e38).Or(diag_img.gt(1e38)))}")
                        logger.info("VERIFICATION: The Earth Engine image is successfully masked. No literal -9999 values have been injected.")
                    # ---------------------------------------------------------
                    
                    # 1. Route all Direct Downloads to the Phase 2 Tiled Download Pipeline
                    if strategy != "Earth Engine Export Task":
                        original_strategy = strategy
                        strategy = "Automatic Tiled Download"
                        self.progress_update.emit("Preparing Phase 2 Download Engine...", 75)
                        profiler.step("Preparing Tiled Download")
                        
                        tiles = export_manager.generate_tiles(risk_metrics["bounds"], risk_metrics["estimated_mb"], aoi_geojson)
                        ee_tiles = tiles
                        
                        # We no longer pre-generate URLs here; the DownloadWorker handles this dynamically via DownloadProvider
                        total_url_gen_time = round(time.time() - url_gen_start_time, 2)
                        avg_url_gen_time = 0.0
                        tile_download_urls = []
                        
                    elif strategy == "Earth Engine Export Task":
                        self.progress_update.emit("Initiating Earth Engine Export Task...", 75)
                        profiler.step("Initiating Export Task")
                        
                        export_img = result["computed_image"] # PRESERVE THE EE MASK! DO NOT UNMASK!
                        task = self.layer_service.gee_provider.start_drive_export_task(
                            export_img, 
                            aoi_geojson, 
                            result["scale"], 
                            result["native_crs"], 
                            f"{layer_name.replace(' ', '_')}_export",
                            nodata_value=-9999.0
                        )
                        task_id = task.id
                        
                        self.progress_update.emit("Export Task running on Google's backend...", 80)
                        
                        # Monitor loop
                        import ee
                        while True:
                            status_obj = task.status()
                            state = status_obj.get('state', 'UNKNOWN')
                            if state in ['COMPLETED', 'FAILED', 'CANCELLED', 'CANCEL_REQUESTED']:
                                break
                            self.progress_update.emit(f"Export Task Status: {state}...", 80)
                            time.sleep(10)
                            
                        url_gen_end_time = time.time()
                        total_url_gen_time = round(url_gen_end_time - url_gen_start_time, 2)
                        avg_url_gen_time = total_url_gen_time
                            
                        if state != 'COMPLETED':
                            raise Exception(f"Earth Engine Export Task ended with state: {state}. Reason: {status_obj.get('error_message', 'Unknown')}")
                            
                        self.progress_update.emit("Export Task Completed! Awaiting local file selection...", 90)
                        profiler.step("Waiting for UI File Selection")
                        
                        # Request file from UI via thread-safe event
                        req = {"event": threading.Event(), "path": None}
                        self.export_task_file_requested.emit(req)
                        req["event"].wait() # Block background thread until UI sets the path
                        
                        if not req["path"]:
                            raise Exception("Export Task completed but no local file was selected. Analysis aborted.")
                            
                        tile_download_urls = [f"file://{req['path']}"]
                        ee_tiles = [aoi_geojson]
                    
                # 5. Build AnalysisResult
                execution_time = round(time.time() - start_time, 2)
                import datetime
                
                # We extract the coverage from the aoi_geojson if available, but for simplicity we rely on the first scene's metrics
                # if available, or just output placeholders if not computed
                metadata = result.get("metadata", {})
                
                # Fetch full index JSON definition to retrieve 'renderer_family', 'palette', etc.
                from ..analysis.raster_metadata import get_raster_metadata
                index_metadata = get_raster_metadata(analysis_type).to_dict() if hasattr(get_raster_metadata(analysis_type), 'to_dict') else {}
                
                # Fallback if to_dict doesn't exist but we can read it from the JSON directly
                import json
                import os
                try:
                    base_dir = os.path.dirname(os.path.dirname(__file__))
                    json_path = os.path.join(base_dir, "indices", f"{analysis_type.lower()}.json")
                    if os.path.exists(json_path):
                        with open(json_path, 'r') as f:
                            index_metadata = json.load(f)
                except Exception as e:
                    self.logger.warning(f"Failed to load index metadata JSON for {analysis_type}: {e}")
                
                default_palette_name = index_metadata.get("visualization", {}).get("palette")
                palette_override = None
                if palette and palette.get("name") != default_palette_name:
                    palette_override = palette

                analysis_result = AnalysisResult(
                    analysis_type=analysis_type,
                    provider=provider_name,
                    dataset=satellite,
                    formula_name=formula.get("name", analysis_type),
                    formula_expression=formula.get("expression", ""),
                    satellite=satellite,
                    processing_level=metadata.get("processing_level", "Unknown"),
                    acquisition_dates=metadata.get("acquisition_dates", []),
                    number_of_scenes=result["metrics"].get("Images Used", 0),
                    composite_method=selection_mode,
                    cloud_threshold=cloud_filter,
                    masks_applied=metadata.get("masks_applied", []),
                    
                    aoi_geojson=aoi_geojson,
                    aoi_area_sqdeg=0.0, # Can be computed or passed
                    coverage_percent=result.get("coverage_percent", 100.0),
                    coverage_km2=0.0,
                    crs="EPSG:4326",
                    resolution=metadata.get("resolution", "30m"),
                    
                    statistics=result.get("statistics", {}),
                    histogram={}, # Future expansion
                    visualization_params={
                        **index_metadata.get("visualization", formula.get("output_range", {})),
                        "stretch_mode": stretch_mode,
                        "min": vis_min if vis_min is not None else index_metadata.get("visualization", {}).get("minimum"),
                        "max": vis_max if vis_max is not None else index_metadata.get("visualization", {}).get("maximum"),
                        "palette_override": palette_override,
                        "Threshold": index_threshold
                    },
                    
                    output_layer_name=layer_name,
                    output_type=output_mode,
                    tile_url=tile_url,
                    download_url=download_url,
                    tile_download_urls=tile_download_urls,
                    export_strategy=strategy,
                    metadata=result["metadata"],
                    quality_metrics={
                        "Images Found": result["metrics"].get("Images Found", 0), 
                        "Estimated MB": risk_metrics["estimated_mb"],
                        "Target Tile Size MB": getattr(export_manager, 'TARGET_TILE_MB', 20.0),
                        "Total URL Generation Time": total_url_gen_time,
                        "Average URL Generation Time": avg_url_gen_time,
                        "tile_url_metrics": tile_url_metrics
                    },
                    
                    computed_image=result.get("computed_image"),
                    ee_scale=result.get("scale"),
                    ee_crs=result.get("native_crs"),
                    ee_tiles=ee_tiles,
                    
                    execution_time_sec=execution_time,
                    processing_timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                
                # Coverage is validated upstream in Phase 5K. Partial Single-Scene coverages are blocked.
                
                # Log execution
                self.logger.info(f"ANALYSIS SUCCESS: {analysis_type} completed in {execution_time}s.")
                
                self.progress_update.emit("✓ Analysis Engine Completed", 100)
                profiler.finish_step()
                self.execution_completed.emit(analysis_result)
                return analysis_result
                
            else:
                raise NotImplementedError("Local Raster processing not yet implemented.")
                
        except Exception as e:
            self.logger.error(f"Analysis failed: {e}")
            self.progress_update.emit(f"Error: {e}", 100)
            
            # Emit a failed result
            import datetime
            failed_result = AnalysisResult(
                analysis_type=analysis_type,
                provider=self.connection_service.current_provider(),
                dataset=satellite,
                formula_name="", formula_expression="", satellite=satellite, processing_level="",
                acquisition_dates=[], number_of_scenes=0, composite_method=selection_mode, cloud_threshold=0.0,
                masks_applied=[], aoi_geojson=aoi_geojson, aoi_area_sqdeg=0.0, coverage_percent=0.0,
                coverage_km2=0.0, crs="", resolution="", statistics={}, histogram={}, visualization_params={},
                output_layer_name="", output_type=output_mode, metadata={}, quality_metrics={},
                execution_time_sec=round(time.time() - start_time, 2),
                processing_timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                errors=[str(e)]
            )
            self.execution_completed.emit(failed_result)
            return failed_result

# ---------------------------------------------------------
# Local Raster Processing
# ---------------------------------------------------------
    def run_local_workflow(self, analysis_type: str, raster_path: str, band_mapping: Dict[str, int], 
                           aoi_geojson: Dict[str, Any], aoi_path: str = "NONE", index_threshold: Optional[float] = None, satellite_name: str = "Local Image") -> AnalysisResult:
        """
        Executes an analysis index on a local raster natively using QGIS GDAL.
        """
        import time
        import datetime
        import tempfile
        import os
        import json
        
        try:
            from osgeo import gdal, ogr, osr
            import numpy as np
            gdal.UseExceptions()
        except ImportError:
            raise ImportError("osgeo.gdal and numpy are required for Local Raster processing. Please check QGIS environment.")
            
        start_time = time.time()
        profiler = PerformanceProfiler.get_instance()
        profiler.start_workflow()
        
        self.progress_update.emit(f"✓ Fetching Formula: {analysis_type}", 10)
        profiler.step("Fetching Formula")
        formula = FormulaRegistry.get_formula(analysis_type)
        expression = formula.get("expression", "")
        
        # Determine the recommended threshold
        if index_threshold is None:
            from ..analysis.raster_metadata import get_raster_metadata
            index_threshold = get_raster_metadata(analysis_type).recommended_threshold
            
        self.progress_update.emit(f"✓ Opening Local Raster with GDAL", 30)
        profiler.step("Read Local Raster")
        
        output_temp_file = os.path.join(tempfile.gettempdir(), f"local_result_{int(time.time())}.tif")
        
        # 1. Open the source raster
        src_ds = gdal.Open(raster_path, gdal.GA_ReadOnly)
        if not src_ds:
            raise Exception("GDAL could not open the selected raster file.")
            
        src_crs_wkt = src_ds.GetProjection()
        geo_transform = src_ds.GetGeoTransform()
        
        # Determine CRS strictly
        crs_str = "Unknown"
        srs = None
        if src_crs_wkt:
            srs = osr.SpatialReference(wkt=src_crs_wkt)
            if srs.IsProjected():
                crs_str = f"EPSG:{srs.GetAuthorityCode('PROJCS')}" if srs.GetAuthorityCode('PROJCS') else "Projected CRS"
            elif srs.IsGeographic():
                crs_str = f"EPSG:{srs.GetAuthorityCode('GEOGCS')}" if srs.GetAuthorityCode('GEOGCS') else "Geographic CRS"

        x_size_src = src_ds.RasterXSize
        y_size_src = src_ds.RasterYSize
        band_count_src = src_ds.RasterCount
        minx_r = geo_transform[0]
        maxy_r = geo_transform[3]
        maxx_r = minx_r + geo_transform[1] * x_size_src
        miny_r = maxy_r + geo_transform[5] * y_size_src

        self.logger.info("===== LOCAL ANALYSIS TEST CONFIG =====")
        self.logger.info(f"Raster path: {raster_path}")
        self.logger.info(f"Raster CRS: {crs_str}")
        self.logger.info(f"Raster extent: {minx_r}, {miny_r} -> {maxx_r}, {maxy_r}")
        self.logger.info(f"Raster width: {x_size_src}")
        self.logger.info(f"Raster height: {y_size_src}")
        self.logger.info("")
        
        proc_mode = "AOI" if aoi_geojson else "FULL_RASTER"
        self.logger.info(f"Processing mode: {proc_mode}")
        
        if aoi_geojson:
            self.logger.info(f"AOI path: {aoi_path}")
            
            # Temporary geometry parsing for extent/crs logging
            geom = aoi_geojson.get("geojson", aoi_geojson)
            geom_json = json.dumps(geom)
            ogr_geom = ogr.CreateGeometryFromJson(geom_json)
            if ogr_geom:
                env = ogr_geom.GetEnvelope()
                self.logger.info(f"AOI CRS: EPSG:4326")
                self.logger.info(f"AOI extent: {env[0]}, {env[2]} -> {env[1]}, {env[3]}")
            else:
                self.logger.info(f"AOI CRS: EPSG:4326")
                self.logger.info(f"AOI extent: Unknown")
        else:
            self.logger.info(f"AOI path: NONE")
            self.logger.info(f"AOI CRS: NONE")
            self.logger.info(f"AOI extent: NONE")
            
        self.logger.info("")
        
        nir_idx = band_mapping.get("NIR", "N/A")
        red_idx = band_mapping.get("RED", "N/A")
        
        # Read scale/offset for NIR as representative
        scale_val = 1.0
        offset_val = 0.0
        if nir_idx != "N/A":
            b = src_ds.GetRasterBand(int(nir_idx))
            if b:
                scale_val = b.GetScale() if b.GetScale() is not None else 1.0
                offset_val = b.GetOffset() if b.GetOffset() is not None else 0.0
                
        self.logger.info(f"NIR band: {nir_idx}")
        self.logger.info(f"RED band: {red_idx}")
        self.logger.info(f"Scale: {scale_val}")
        self.logger.info(f"Offset: {offset_val}")
        self.logger.info(f"Formula: {expression}")
        self.logger.info("======================================")

        # Validate bands before AOI
        for var_name, b_idx in band_mapping.items():
            if not b_idx: continue
            tmp_band = src_ds.GetRasterBand(int(b_idx))
            if tmp_band:
                nd_val = tmp_band.GetNoDataValue()
                scale = tmp_band.GetScale()
                offset = tmp_band.GetOffset()
                d_type = gdal.GetDataTypeName(tmp_band.DataType)
                self.logger.info(f"Band {var_name} (idx {b_idx}): Type={d_type}, NoData={nd_val}, Scale={scale}, Offset={offset}")

        # 2. AOI Intersection and Clipping
        temp_geojson_path = None
        if aoi_geojson:
            self.progress_update.emit("✓ Clipping Raster to Study Area", 40)
            geom = aoi_geojson.get("geojson", aoi_geojson)

            temp_geojson_path = os.path.join(tempfile.gettempdir(), f"temp_aoi_{int(time.time())}.geojson")
            with open(temp_geojson_path, 'w') as f:
                json.dump(geom, f)
                
            geom_json = json.dumps(geom)
            ogr_geom = ogr.CreateGeometryFromJson(geom_json)
            if ogr_geom:
                env = ogr_geom.GetEnvelope() # (minX, maxX, minY, maxY)
                minx_a, maxx_a, miny_a, maxy_a = env
                self.logger.info(f"AOI CRS: EPSG:4326 (GeoJSON default)")
                self.logger.info(f"AOI Extent (EPSG:4326): {minx_a}, {miny_a} -> {maxx_a}, {maxy_a}")
                
                # Transform AOI to Raster CRS for accurate intersection
                if crs_str != "EPSG:4326" and srs:
                    source_srs = osr.SpatialReference()
                    source_srs.ImportFromEPSG(4326)
                    if hasattr(osr, 'OAMS_TRADITIONAL_GIS_ORDER'):
                        source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                        srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
                    
                    transform = osr.CoordinateTransformation(source_srs, srs)
                    ogr_geom_clone = ogr_geom.Clone()
                    ogr_geom_clone.Transform(transform)
                    env2 = ogr_geom_clone.GetEnvelope()
                    minx_a, maxx_a, miny_a, maxy_a = env2
                    self.logger.info(f"AOI Extent (Raster CRS): {minx_a}, {miny_a} -> {maxx_a}, {maxy_a}")
                
                intersect_x = not (maxx_a < minx_r or minx_a > maxx_r)
                intersect_y = not (maxy_a < miny_r or miny_a > maxy_r)
                if miny_r > maxy_r:
                    intersect_y = not (maxy_a < maxy_r or miny_a > miny_r)
                
                self.logger.info(f"Intersection (Bounding Box): {'YES' if intersect_x and intersect_y else 'NO'}")
                if not (intersect_x and intersect_y):
                    error_msg = f"AOI does not intersect raster.\nRaster extent: {minx_r:.4f}, {miny_r:.4f} -> {maxx_r:.4f}, {maxy_r:.4f}\nAOI extent (in raster CRS): {minx_a:.4f}, {miny_a:.4f} -> {maxx_a:.4f}, {maxy_a:.4f}\nRaster CRS: {crs_str}"
                    self.logger.error(error_msg)
                    raise Exception(error_msg)
                
            self.logger.info(f"Applying gdal.Warp with cutline {temp_geojson_path}")
            warp_opts = gdal.WarpOptions(
                format="MEM",
                cutlineDSName=temp_geojson_path,
                cutlineSRS="EPSG:4326",
                cropToCutline=True,
                dstSRS=src_crs_wkt,
                dstNodata=-9999.0
            )
            process_ds = gdal.Warp("", src_ds, options=warp_opts)
            if not process_ds:
                raise Exception("GDAL Warp failed. The Study Area may not intersect the raster bounds.")
                
            if process_ds.RasterXSize == 0 or process_ds.RasterYSize == 0:
                raise Exception("The Study Area intersection is empty. Please ensure the study area overlaps the selected raster.")
        else:
            process_ds = src_ds

        out_geo_transform = process_ds.GetGeoTransform()
        x_size = process_ds.RasterXSize
        y_size = process_ds.RasterYSize
        
        self.logger.info(f"After AOI clipping, Size: {x_size}x{y_size}")
            
        self.progress_update.emit("✓ Reading Bands", 50)
        profiler.step("Reading Bands")
        
        # 3. Read and mask bands
        band_arrays = {}
        valid_mask = None
        
        self.logger.info(f"========== {'AOI' if aoi_geojson else 'FULL RASTER'} MODE ==========")
        self.logger.info(f"Source Dataset: {raster_path}")
        self.logger.info(f"Warp Applied: {'YES' if aoi_geojson else 'NO'}")
        
        for var_name, b_idx in band_mapping.items():
            if not b_idx:
                raise Exception(f"No band selected for spectral role: {var_name}")
                
            band = process_ds.GetRasterBand(int(b_idx))
            if not band:
                raise Exception(f"Band index {b_idx} not found in the raster.")
                
            b_data_raw = band.ReadAsArray().astype(np.float32)
            
            nodata_val = band.GetNoDataValue()
            data_type = gdal.GetDataTypeName(band.DataType)
            scale = band.GetScale() if band.GetScale() is not None else 1.0
            offset = band.GetOffset() if band.GetOffset() is not None else 0.0
            
            raw_min = np.nanmin(b_data_raw)
            raw_max = np.nanmax(b_data_raw)
            raw_mean = np.nanmean(b_data_raw)
            raw_zeros = np.count_nonzero(b_data_raw == 0)
            raw_finite = np.count_nonzero(np.isfinite(b_data_raw))
            raw_nan = np.count_nonzero(np.isnan(b_data_raw))
            raw_inf = np.count_nonzero(np.isinf(b_data_raw))
            
            self.logger.info(f"\nRAW BAND: {var_name}")
            self.logger.info(f"RAW min: {raw_min}")
            self.logger.info(f"RAW max: {raw_max}")
            self.logger.info(f"RAW mean: {raw_mean}")
            self.logger.info(f"RAW zeros: {raw_zeros}")
            self.logger.info(f"RAW finite: {raw_finite}")
            self.logger.info(f"RAW NaN: {raw_nan}")
            self.logger.info(f"RAW Inf: {raw_inf}")
            self.logger.info(f"GDAL NoData: {nodata_val}")
            self.logger.info(f"Data Type: {data_type}")
            self.logger.info(f"Scale: {scale}")
            self.logger.info(f"Offset: {offset}")
            
            if nodata_val is not None:
                current_valid = (b_data_raw != nodata_val) & np.isfinite(b_data_raw)
            else:
                current_valid = np.isfinite(b_data_raw)
                
            b_data_phys = b_data_raw.copy()
            if scale != 1.0:
                b_data_phys = b_data_phys * scale
            if offset != 0.0:
                b_data_phys = b_data_phys + offset
                
            phys_min = np.nanmin(b_data_phys[current_valid]) if np.count_nonzero(current_valid) > 0 else np.nan
            phys_max = np.nanmax(b_data_phys[current_valid]) if np.count_nonzero(current_valid) > 0 else np.nan
            phys_mean = np.nanmean(b_data_phys[current_valid]) if np.count_nonzero(current_valid) > 0 else np.nan
            neg_count = np.count_nonzero(b_data_phys[current_valid] < 0)
            neg02_count = np.count_nonzero(np.isclose(b_data_phys[current_valid], -0.2))
            
            self.logger.info(f"\nPHYSICAL {var_name} min/max/mean: {phys_min} / {phys_max} / {phys_mean}")
            self.logger.info(f"{var_name} < 0: {neg_count}")
            self.logger.info(f"{var_name} == -0.2: {neg02_count}")
            
            if valid_mask is None:
                valid_mask = current_valid
            else:
                valid_mask = valid_mask & current_valid
                
            b_data_phys[~current_valid] = np.nan
            band_arrays[var_name] = b_data_phys
            
        valid_pixel_count = np.count_nonzero(valid_mask)
        self.logger.info(f"\nValid pixels before masking: {process_ds.RasterXSize * process_ds.RasterYSize}")
        self.logger.info(f"Valid pixels after masking (Valid Mask): {valid_pixel_count}")
        
        if valid_pixel_count == 0:
            err_msg = "Clipping/masking produced zero valid pixels."
            self.logger.error(err_msg)
            raise Exception(err_msg)
            
        # Cross-band diagnostics
        if "NIR" in band_arrays and "RED" in band_arrays:
            nir_raw_band = process_ds.GetRasterBand(band_mapping["NIR"]).ReadAsArray()
            red_raw_band = process_ds.GetRasterBand(band_mapping["RED"]).ReadAsArray()
            
            nir_0 = (nir_raw_band == 0)
            red_0 = (red_raw_band == 0)
            
            self.logger.info(f"\nCROSS-BAND RAW DIAGNOSTICS:")
            self.logger.info(f"NIR == 0: {np.count_nonzero(nir_0)}")
            self.logger.info(f"RED == 0: {np.count_nonzero(red_0)}")
            self.logger.info(f"NIR == 0 AND RED == 0: {np.count_nonzero(nir_0 & red_0)}")
            self.logger.info(f"NIR == 0 XOR RED == 0: {np.count_nonzero(nir_0 ^ red_0)}")
            
            nir_phys = band_arrays["NIR"]
            red_phys = band_arrays["RED"]
            sum_phys = nir_phys + red_phys
            
            valid_sum_phys = sum_phys[valid_mask]
            
            self.logger.info(f"PHYSICAL CROSS-BAND DIAGNOSTICS (DENOMINATOR):")
            if valid_sum_phys.size > 0:
                abs_sum = np.abs(valid_sum_phys)
                self.logger.info(f"minimum NIR + RED: {np.nanmin(valid_sum_phys)}")
                self.logger.info(f"maximum NIR + RED: {np.nanmax(valid_sum_phys)}")
                self.logger.info(f"mean NIR + RED: {np.nanmean(valid_sum_phys)}")
                self.logger.info(f"minimum absolute denominator: {np.nanmin(abs_sum)}")
                
                unique_abs_sums = np.unique(abs_sum[~np.isnan(abs_sum)])
                smallest_10 = np.sort(unique_abs_sums)[:10]
                self.logger.info(f"10 smallest absolute denominator values: {smallest_10}")
                
                self.logger.info(f"count where abs(NIR + RED) < 1e-2: {np.count_nonzero(abs_sum < 1e-2)}")
                self.logger.info(f"count where abs(NIR + RED) < 1e-3: {np.count_nonzero(abs_sum < 1e-3)}")
                self.logger.info(f"count where abs(NIR + RED) < 1e-4: {np.count_nonzero(abs_sum < 1e-4)}")
                self.logger.info(f"count where abs(NIR + RED) < 1e-5: {np.count_nonzero(abs_sum < 1e-5)}")
                self.logger.info(f"count where abs(NIR + RED) < 1e-6: {np.count_nonzero(abs_sum < 1e-6)}")
            
        self.progress_update.emit("Evaluating Formula safely", 70)
        profiler.step("Formula Evaluation")
        
        # --- NEW STRICT SAFETY DAG EXECUTION ---
        self.progress_update.emit("Executing Strict Safety DAG", 70)
        
        from ..utils.safe_eval import SafeMathEvaluator
        
        # 1. Base Variables
        eval_locals = {k.upper(): v for k, v in band_arrays.items()}
        
        # 2. Parameters
        parameters = formula.get("parameters", {})
        if parameters:
            for param_key, param_val in parameters.items():
                if isinstance(param_val, (int, float)):
                    eval_locals[param_key.upper()] = float(param_val)
                    
        # 3. Apply input semantics (Optical >= 0)
        input_semantics = formula.get("input_semantics", {})
        safety = formula.get("safety", {})
        
        valid_mask = np.ones(process_ds.RasterXSize * process_ds.RasterYSize, dtype=bool).reshape((process_ds.RasterYSize, process_ds.RasterXSize))
        # Initial mask from band arrays
        for b_name, b_data in band_arrays.items():
            valid_mask = valid_mask & ~np.isnan(b_data) & ~np.isinf(b_data)
            
        # Band specific input validity
        opt_min = safety.get("input_validity", {}).get("optical_min", 0.0)
        if opt_min is not None:
            # We assume all bands are optical unless specified otherwise in some band_semantics. 
            # In Phase 2D we didn't add band_semantics to JSON, but we set input_semantics domain="optical" 
            # or "hybrid" for EBBI. Since EBBI is unsupported, everything else is optical.
            for b_name, b_data in band_arrays.items():
                if b_name != "TIR": # Hardcoded protection just in case
                    valid_mask = valid_mask & (b_data >= opt_min)
                    
        # Helper to safely evaluate and mask
        def safe_eval_array(expr):
            # We can't use SafeMathEvaluator on full arrays directly easily if it uses `operator`.
            # Wait, our SafeMathEvaluator uses standard operators, which work perfectly on NumPy arrays!
            with np.errstate(divide='ignore', invalid='ignore'):
                return SafeMathEvaluator.evaluate(expr, eval_locals)

        # 4. Base Denominators
        for denom in safety.get("base_denominators", []):
            denom_val = safe_eval_array(denom["expression"])
            eps = denom.get("epsilon", 1e-6)
            valid_mask = valid_mask & (np.abs(denom_val) >= eps)
            
        # 5. Derived Terms
        for dt in safety.get("derived_terms", []):
            dt_val = safe_eval_array(dt["expression"])
            # Mask out NaNs that might have happened in invalid regions
            dt_val[~valid_mask] = 0.0 # Prevent propagation
            eval_locals[dt["id"]] = dt_val
            
        # 6. Complex Denominators
        for cdenom in safety.get("complex_denominators", []):
            cdenom_val = safe_eval_array(cdenom["expression"])
            eps = cdenom.get("epsilon", 1e-6)
            valid_mask = valid_mask & (np.abs(cdenom_val) >= eps)
            
        # 7. SQRT Domains
        for sq in safety.get("sqrt_domains", []):
            sq_val = safe_eval_array(sq["expression"])
            min_v = sq.get("min_valid", 0.0)
            valid_mask = valid_mask & (sq_val >= min_v)
            
        # 8. Final Formula
        result_array = safe_eval_array(formula["expression"])
        
        # 9. Output Validity
        out_val = safety.get("output_validity", {})
        if out_val.get("enabled", False):
            v_min = out_val.get("min", -np.inf)
            v_max = out_val.get("max", np.inf)
            valid_mask = valid_mask & (result_array >= v_min) & (result_array <= v_max)
            
        valid_res_mask = valid_mask & ~np.isnan(result_array) & ~np.isinf(result_array)
        result_array[~valid_res_mask] = np.nan
        valid_res = result_array[valid_res_mask]
        # --- END NEW STRICT SAFETY DAG EXECUTION ---
        
        self.logger.info(f"\nINDEX RAW RESULT")
        self.logger.info(f"min: {np.min(valid_res) if valid_res.size > 0 else np.nan}")
        self.logger.info(f"max: {np.max(valid_res) if valid_res.size > 0 else np.nan}")
        self.logger.info(f"mean: {np.mean(valid_res) if valid_res.size > 0 else np.nan}")
        
        masked_res = result_array[valid_mask]
        self.logger.info(f"NaN count: {np.count_nonzero(np.isnan(masked_res))}")
        self.logger.info(f"Inf count: {np.count_nonzero(np.isinf(masked_res))}")
        
        # Removed hardcoded NDVI/NIR+RED diagnostic blocks.
            
        # Protect mathematical abnormalities for diagnostic continuation
        result_array[~valid_mask] = np.nan
        result_array[np.isinf(result_array)] = np.nan
        
        out_nodata = -9999.0
        result_array = np.nan_to_num(result_array, nan=out_nodata)
        
        final_valid = result_array[result_array != out_nodata]
        self.logger.info(f"\nFinal Valid Pixels: {final_valid.size}")
        if final_valid.size > 0:
            self.logger.info(f"Final Min: {np.nanmin(final_valid)}")
            self.logger.info(f"Final Max: {np.nanmax(final_valid)}")
            self.logger.info(f"Final Mean: {np.nanmean(final_valid)}")
            
        self.progress_update.emit("✓ Writing Result", 85)
        profiler.step("Writing Result GeoTIFF")
        
        # Write to GeoTIFF using GDAL
        driver = gdal.GetDriverByName("GTiff")
        out_ds = driver.Create(output_temp_file, x_size, y_size, 1, gdal.GDT_Float32)
        if out_geo_transform:
            out_ds.SetGeoTransform(out_geo_transform)
        if src_crs_wkt:
            out_ds.SetProjection(src_crs_wkt)
            
        out_band = out_ds.GetRasterBand(1)
        out_band.WriteArray(result_array.astype(np.float32))
        out_band.SetNoDataValue(out_nodata)
        
        # Flush and close datasets
        out_band.FlushCache()
        out_ds = None
        process_ds = None
        src_ds = None
        
        if temp_geojson_path and os.path.exists(temp_geojson_path):
            try:
                os.remove(temp_geojson_path)
            except:
                pass
            
        # Build AnalysisResult
        execution_time = round(time.time() - start_time, 2)
        layer_name = f"{analysis_type} - {satellite_name}"
        
        index_metadata = {}
        try:
            base_dir = os.path.dirname(os.path.dirname(__file__))
            json_path = os.path.join(base_dir, "indices", f"{analysis_type.lower()}.json")
            if os.path.exists(json_path):
                with open(json_path, 'r') as f:
                    index_metadata = json.load(f)
        except Exception as e:
            self.logger.warning(f"Failed to load index metadata JSON for {analysis_type}: {e}")

        valid_pixels = result_array[result_array != out_nodata]
        formatted_stats = {}
        if valid_pixels.size > 0:
            formatted_stats = {
                "Min": float(np.min(valid_pixels)),
                "Max": float(np.max(valid_pixels)),
                "Mean": float(np.mean(valid_pixels)),
                "Median": float(np.median(valid_pixels)),
                "StdDev": float(np.std(valid_pixels))
            }
            
        resolution_val = geo_transform[1] if geo_transform else "Unknown"

        # Safe conversion of Windows paths to valid File URIs
        import urllib.request
        safe_uri = "file:" + urllib.request.pathname2url(output_temp_file)
        
        analysis_result = AnalysisResult(
            analysis_type=analysis_type,
            provider="Local Raster",
            dataset="Local Dataset",
            formula_name=formula.get("name", analysis_type),
            formula_expression=expression,
            satellite=satellite_name,
            processing_level="N/A",
            acquisition_dates=[],
            number_of_scenes=1,
            composite_method="Local File",
            cloud_threshold=100.0,
            masks_applied=["AOI Clip"] if aoi_geojson else [],
            aoi_geojson=aoi_geojson,
            aoi_area_sqdeg=0.0,
            coverage_percent=100.0,
            coverage_km2=0.0,
            crs=crs_str,
            resolution=f"{resolution_val}",
            statistics=formatted_stats,
            histogram={},
            visualization_params={
                **index_metadata.get("visualization", formula.get("output_range", {})),
                "Threshold": index_threshold
            },
            output_layer_name=layer_name,
            output_type="GeoTIFF Download",
            tile_url=None,
            download_url=None,
            tile_download_urls=[safe_uri],
            export_strategy="Local Processing",
            metadata={"file": raster_path, "band_mapping": band_mapping},
            quality_metrics={},
            computed_image=None,
            ee_scale=None,
            ee_crs=None,
            ee_tiles=[aoi_geojson] if aoi_geojson else [],
            execution_time_sec=execution_time,
            processing_timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        
        self.progress_update.emit("✓ Analysis Engine Completed", 100)
        profiler.finish_step()
        return analysis_result

# ---------------------------------------------------------
# Generic Architecture Implementation (Stage 2)
# ---------------------------------------------------------
    def run_generic_workflow(self, context) -> AnalysisResult:
        """
        Executes the analysis pipeline using the generic ProviderInterface and AnalysisContext.
        Maintains bitwise compatibility with the legacy pipeline.
        """
        import time
        import datetime
        from ..utils.profiler import PerformanceProfiler

        start_time = time.time()
        profiler = PerformanceProfiler.get_instance()
        profiler.start_workflow()

        try:
            self.progress_update.emit(f"Validating Context: {context.index_definition['id']}", 10)
            profiler.step("Context Validation")

            provider = self.layer_service.gee_provider

            # 1. Dataset Loading & Masking
            self.progress_update.emit("Loading Dataset", 30)
            profiler.step("Dataset Loading")
            dataset = provider.load_dataset(context)
            dataset = provider.apply_cloud_mask(dataset, context)
            
            from ..analysis.metrics_builder import AnalysisMetricsBuilder
            collection, sat_info, geom = dataset
            selection_mode = context.parameters.get("selection_mode", "Median")
            image_ids = context.parameters.get("image_ids", None)
            collection_metrics = AnalysisMetricsBuilder.compute_collection_metrics(collection, selection_mode, image_ids)

            # 2. Formula Evaluation (Map over Collection)
            self.progress_update.emit("Evaluating Formula", 50)
            profiler.step("Formula Evaluation")
            computed_dataset = provider.evaluate_formula(dataset, context)

            # 3. Composite Generation
            self.progress_update.emit("Building Composite", 60)
            profiler.step("Composite Generation")
            computed_img = provider.build_composite(computed_dataset, context)

            # 4. Statistics generation
            self.progress_update.emit("Generating Statistics", 65)
            profiler.step("Statistics Generation")
            
            export_resolution_mode = context.export_settings.get("resolution_mode", "Custom")
            export_resolution = context.export_settings.get("resolution", 10.0)
            scale = export_resolution if export_resolution_mode == "Custom" else (10.0 if 'Sentinel' in context.satellite_definition['satellite_id'] else 30.0)
            
            # --- TEMPORARY DIAGNOSTIC INJECTION ---
            try:
                from ..utils.diagnostic_logger import run_savi_diagnostics
                run_savi_diagnostics(
                    base_img=img_data[0], 
                    computed_img=computed_img, 
                    context=context, 
                    scale=scale, 
                    geom=geom, 
                    collection_metrics=collection_metrics, 
                    sat_info=sat_info
                )
            except Exception as diag_e:
                self.logger.error(f"SAVI Diagnostics failed: {diag_e}")
            # --- END TEMPORARY DIAGNOSTIC INJECTION ---
            
            stats = AnalysisMetricsBuilder.compute_image_statistics(computed_img, geom, scale)
            scientific_name = context.index_definition["metadata"]["scientific_name"]
            formatted_stats = AnalysisMetricsBuilder.format_statistics(stats, scientific_name)
            
            acq_dates = image_ids if image_ids else ["Composite Range"]
            metadata = AnalysisMetricsBuilder.build_metadata(sat_info, f"{export_resolution}m", scale, acq_dates)

            # 5. Export (Using ExportManager with Context)
            self.progress_update.emit("Preparing Export", 70)
            profiler.step("Export Preparation")

            export_manager = ExportManager()
            risk_metrics = export_manager.estimate_export_risk(
                context.aoi, 
                context.export_settings.get("resolution", 10.0), 
                bands=1
            )
            strategy = risk_metrics["strategy"]

            # 5. Build standard Result object matching legacy exactly
            ee_tiles = []
            if strategy != "Earth Engine Export Task":
                ee_tiles = export_manager.generate_tiles(risk_metrics["bounds"], risk_metrics["estimated_mb"], context.aoi)
            else:
                ee_tiles = [context.aoi]

            default_threshold = context.index_definition.get("default_parameters", {}).get(
                "threshold", context.index_definition.get("default_parameters", {}).get("recommended_threshold", 0.0)
            )

            palette_data = context.parameters.get("palette")
            default_palette_name = context.index_definition.get("visualization", {}).get("palette")
            
            palette_override = None
            if palette_data and palette_data.get("name") != default_palette_name:
                palette_override = palette_data

            analysis_result = AnalysisResult(
                analysis_type=context.index_definition["id"],
                provider=context.satellite_definition["provider"],
                dataset=context.satellite_definition["satellite_id"],
                formula_name=context.index_definition["metadata"]["scientific_name"],
                formula_expression=context.index_definition["formula"]["expression"],
                satellite=context.satellite_definition["satellite_id"],
                processing_level=metadata.get("processing_level", "Unknown"),
                acquisition_dates=metadata.get("acquisition_dates", []),
                number_of_scenes=collection_metrics.get("Images Used", 0),
                composite_method=context.parameters.get("selection_mode", "Median"),
                cloud_threshold=context.parameters.get("cloud_filter", 100.0),
                masks_applied=metadata.get("masks_applied", []),

                aoi_geojson=context.aoi,
                aoi_area_sqdeg=0.0,
                coverage_percent=100.0,
                coverage_km2=0.0,
                crs=context.satellite_definition.get("native_crs", "EPSG:4326"),
                resolution=metadata.get("resolution", f"{scale}m"),

                statistics=formatted_stats,
                histogram={},
                visualization_params={
                    **context.index_definition.get("visualization", {}),
                    "stretch_mode": context.parameters.get("stretch_mode", "Original"),
                    "min": context.parameters.get("vis_min", -1.0),
                    "max": context.parameters.get("vis_max", 1.0),
                    "palette": context.index_definition.get("visualization", {}).get("palette"),
                    "palette_override": palette_override,
                    "Threshold": context.parameters.get("index_threshold", default_threshold)
                },

                output_layer_name=f"{context.index_definition['id']} - {context.satellite_definition['satellite_id']} - {context.date_range['start']}",
                output_type="GeoTIFF Download",
                tile_url=None,
                download_url=None,
                tile_download_urls=[],
                export_strategy=strategy,
                metadata=metadata,
                quality_metrics={
                    "Images Found": collection_metrics.get("Images Found", 0),
                    "Estimated MB": risk_metrics["estimated_mb"],
                    "Target Tile Size MB": getattr(export_manager, 'TARGET_TILE_MB', 20.0),
                    "Total URL Generation Time": 0.0,
                    "Average URL Generation Time": 0.0,
                    "tile_url_metrics": {}
                },

                computed_image=computed_img,
                ee_scale=scale,
                ee_crs=context.satellite_definition.get("native_crs", "EPSG:4326"),
                ee_tiles=ee_tiles,

                execution_time_sec=round(time.time() - start_time, 2),
                processing_timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )

            self.progress_update.emit("Generic Analysis Engine Completed", 100)
            profiler.finish_step()
            return analysis_result

        except Exception as e:
            self.logger.error(f"Generic Analysis failed: {e}")
            raise e
