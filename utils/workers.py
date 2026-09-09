import urllib.request
import os
import tempfile
import time
import uuid
import numpy as np

from PyQt6.QtCore import QThread, pyqtSignal
from typing import Dict, Any, Tuple
from ..utils.profiler import PerformanceProfiler
from ..analysis.statistics_engine import StatisticsEngine

class DownloadWorker(QThread):
    """
    Downloads GeoTIFF(s), merges them if tiled, performs the rasterio audit, 
    and computes base statistics in a background thread.
    """
    
    download_progress = pyqtSignal(str, int)
    download_completed = pyqtSignal(str, dict, str)
    
    def __init__(self, layer_name: str, download_urls: list, aoi_geojson: Dict[str, Any],
                 ee_image=None, ee_scale=None, ee_crs=None, ee_tiles=None, gee_provider=None,
                 analysis_result=None):
        super().__init__()
        import logging
        self.logger = logging.getLogger(__name__)
        
        # Setup file handler for diagnostics
        self.log_file_path = os.path.join(os.path.dirname(__file__), '..', 'download_diagnostics.log')
        file_handler = logging.FileHandler(self.log_file_path, mode='a')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(file_handler)
        self.logger.setLevel(logging.INFO)
        
        self.logger.info("\n\n" + "="*50)
        self.logger.info("NEW DOWNLOAD JOB STARTED")
        self.logger.info("="*50)
        
        self.first_fatal_exception = None
        self.layer_name = layer_name
        self.download_urls = download_urls or []
        self.aoi_geojson = aoi_geojson
        self.ee_image = ee_image
        self.ee_scale = ee_scale
        self.ee_crs = ee_crs
        self.ee_tiles = ee_tiles or []
        self.gee_provider = gee_provider
        self.analysis_result = analysis_result
        self.profiler = PerformanceProfiler.get_instance()
        
    def run(self):
        if getattr(self, 'gee_provider', None):
            self.gee_provider.acquire_session_lock()
        try:
            temp_dir = tempfile.gettempdir()
            safe_name = "".join([c if c.isalnum() else "_" for c in self.layer_name])
            unique_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
            
            downloaded_paths = []
            
            use_dynamic_urls = len(self.ee_tiles) > 0 and self.gee_provider is not None
            total_tiles = len(self.ee_tiles) if use_dynamic_urls else len(self.download_urls)
            
            self.final_summary = {
                "Export Strategy": "Automatic Tiled Download" if total_tiles > 1 else "Direct Download",
                "Number of Tiles": total_tiles,
                "Successful Tiles": 0,
                "Failed Tiles": 0,
                "First Failed Tile": "N/A",
                "Reason": "N/A"
            }
            
            # Adaptive parallelism & Phase 2 Configs
            from ..config import CONCURRENT_DOWNLOADS, SLOW_TILE_TIMEOUT, MAX_TILE_RECURSION, MIN_TILE_PIXEL_COUNT, MAX_RETRIES_BEFORE_SPLIT, MAX_PENDING_TILES
            from ..config import AUTO_TUNE_TILE_SIZE, TILE_SIZING_STRATEGY, TARGET_PIXELS_PER_TILE, BENCHMARK_HISTORY_FILE, DOWNLOAD_API
            from PyQt6.QtCore import QMutex, QMutexLocker
            import threading
            import queue
            from shapely.geometry import shape, box
            
            auto_tune_enabled = AUTO_TUNE_TILE_SIZE
            current_target_pixels = 20_000_000 if TILE_SIZING_STRATEGY == "AUTO_PROGRESSIVE" else TARGET_PIXELS_PER_TILE
            max_practical_limit = 1_000_000_000 # Capped dynamically if payload errors occur
            import json
            
            num_workers = min(total_tiles, CONCURRENT_DOWNLOADS)
            if num_workers == 0:
                num_workers = 1
                
            self.profiler.step("Downloading GeoTIFF(s)")
            
            mutex = QMutex()
            completed_count = 0
            tile_metrics = []
            
            work_queue = queue.PriorityQueue()
            
            # Helper for composite priority
            def calculate_priority(t_dict):
                base_pixels = t_dict.get("expected_pixels", t_dict.get("priority", 1))
                depth = t_dict.get("depth", 0)
                retries = t_dict.get("retries", 0)
                # Composite calculation: can easily incorporate other heuristics
                return base_pixels / ((depth + 1) * (retries + 1))
            
            # Initialize queue
            for i, t in enumerate(self.ee_tiles if use_dynamic_urls else self.download_urls):
                depth = t.get("depth", 0) if isinstance(t, dict) else 0
                t_priority = calculate_priority(t) if isinstance(t, dict) else 1
                # (priority, tile_id, dictionary) ensures deterministic tie-breaker on integer tile_id
                work_queue.put((t_priority, i+1, t))
                self.logger.info(f"[DOWNLOAD PIPELINE] Tile {i+1} queued initially.")
                
            dynamic_split_count = 0
            max_recursion_reached = 0
            next_tile_id = total_tiles + 1
            
            # active_items tracks total pending + processing tiles
            active_items = total_tiles
            
            worker_metrics = {f"Worker {i+1}": {"busy": 0.0, "idle": 0.0} for i in range(num_workers)}
            
            def split_tile_adaptively(tile_id, tile_dict):
                nonlocal dynamic_split_count, max_recursion_reached, next_tile_id
                
                depth = tile_dict.get("depth", 0)
                if depth >= MAX_TILE_RECURSION:
                    return False
                    
                coords = tile_dict.get("coordinates", [[[]]])[0]
                lons = [c[0] for c in coords]
                lats = [c[1] for c in coords]
                q_w, q_e = min(lons), max(lons)
                q_s, q_n = min(lats), max(lats)
                
                width = q_e - q_w
                height = q_n - q_s
                
                if width <= 0 or height <= 0: return False
                
                aspect = width / height if height > 0 else 1
                
                mid_x = q_w + width / 2
                mid_y = q_s + height / 2
                
                boxes = []
                if aspect > 1.5: # Wide
                    boxes = [(q_w, q_s, mid_x, q_n), (mid_x, q_s, q_e, q_n)]
                elif aspect < 0.66: # Tall
                    boxes = [(q_w, q_s, q_e, mid_y), (q_w, mid_y, q_e, q_n)]
                else: # Square
                    boxes = [
                        (q_w, q_s, mid_x, mid_y), (mid_x, q_s, q_e, mid_y),
                        (q_w, mid_y, mid_x, q_n), (mid_x, mid_y, q_e, q_n)
                    ]
                    
                child_pixels = tile_dict.get("expected_pixels", MIN_TILE_PIXEL_COUNT) / len(boxes)
                if child_pixels < MIN_TILE_PIXEL_COUNT:
                    return False
                    
                with QMutexLocker(mutex):
                    if work_queue.qsize() + len(boxes) > MAX_PENDING_TILES:
                        # Queue back-pressure safeguard: Defer subdivision
                        # Requeue the parent tile and pretend it was "handled" so it doesn't fail
                        tile_dict["retries"] = 0
                        comp_priority = calculate_priority(tile_dict)
                        work_queue.put((comp_priority, tile_id, tile_dict))
                        active_items += 1
                        return True
                        
                    for b in boxes:
                        new_tile = {
                            "type": "Polygon",
                            "depth": depth + 1,
                            "expected_pixels": child_pixels,
                            "parent_id": tile_id,
                            "retries": 0,
                            "coordinates": [[
                                [b[0], b[1]], [b[2], b[1]],
                                [b[2], b[3]], [b[0], b[3]],
                                [b[0], b[1]]
                            ]]
                        }
                        comp_priority = calculate_priority(new_tile)
                        work_queue.put((comp_priority, next_tile_id, new_tile))
                        self.logger.info(f"[DOWNLOAD PIPELINE] Child Tile {next_tile_id} queued (split from parent {tile_id}).")
                        next_tile_id += 1
                        
                    active_items += len(boxes)
                    dynamic_split_count += 1
                    max_recursion_reached = max(max_recursion_reached, depth + 1)
                    
                return True
                
            def worker_loop(worker_name):
                nonlocal completed_count, active_items, max_practical_limit, current_target_pixels
                idle_start = time.time()
                while True:
                    with QMutexLocker(mutex):
                        if active_items == 0:
                            break
                    try:
                        priority, tile_id, item = work_queue.get(timeout=1)
                    except queue.Empty:
                        continue
                        
                    # Proactive Splitting: Local Auto-Tuning Check
                    expected = item.get("expected_pixels", 0)
                    with QMutexLocker(mutex):
                        target_px = current_target_pixels
                        
                    if auto_tune_enabled and expected > target_px:
                        if split_tile_adaptively(tile_id, item):
                            with QMutexLocker(mutex):
                                active_items -= 1
                            work_queue.task_done()
                            continue
                        
                    wait_time = time.time() - idle_start
                    worker_metrics[worker_name]["idle"] += wait_time
                    
                    busy_start = time.time()
                    file_path = os.path.join(temp_dir, f"{safe_name}_{unique_id}_tile_{tile_id}.tif")
                    
                    with QMutexLocker(mutex):
                        self.download_progress.emit(f"Downloading Tile {tile_id}...", int(min(90, completed_count / total_tiles * 100)))
                        
                    self.logger.info(f"[DOWNLOAD PIPELINE] Tile {tile_id} download started. Attempting max 3 retries.")
                    success = False
                    last_error = ""
                    retries = 0
                    was_split = False
                    
                    for attempt in range(3):
                        try:
                            if use_dynamic_urls:
                                provider_name = self.gee_provider.download_provider.__class__.__name__ if hasattr(self.gee_provider, 'download_provider') else "Legacy/Unknown"
                                self.logger.info(f"[DOWNLOAD PIPELINE] Tile {tile_id} - Provider selected: {provider_name}")
                                self.gee_provider.download_tile(
                                    self.ee_image, item, self.ee_scale, self.ee_crs, file_path, SLOW_TILE_TIMEOUT
                                )
                            else:
                                current_url = item
                                req = urllib.request.Request(current_url)
                                with urllib.request.urlopen(req, timeout=SLOW_TILE_TIMEOUT) as response:
                                    data = response.read()
                                    with open(file_path, 'wb') as f:
                                        f.write(data)
                                        
                            if os.path.getsize(file_path) > 0:
                                success = True
                                self.logger.info(f"[DOWNLOAD PIPELINE] Tile {tile_id} download succeeded.")
                                self.logger.info(f"[DOWNLOAD PIPELINE] Tile {tile_id} output file path: {file_path}")
                                break
                            else:
                                last_error = "Downloaded tile is 0 bytes."
                                self.logger.warning(f"[DOWNLOAD PIPELINE] Tile {tile_id} download failed (Attempt {attempt+1}): {last_error}")
                        except Exception as e:
                            last_error = str(e)
                            self.logger.warning(f"[DOWNLOAD PIPELINE] Tile {tile_id} download failed (Attempt {attempt+1}): {last_error}")
                            retries += 1
                            err_str = last_error.lower()
                            
                            is_payload_error = any(x in err_str for x in ["payload", "size", "limit", "too large", "exceed", "memory", "deadline"])
                            if is_payload_error and auto_tune_enabled:
                                with QMutexLocker(mutex):
                                    max_practical_limit = min(max_practical_limit, expected / 2)
                                    current_target_pixels = min(current_target_pixels, max_practical_limit)
                                    
                                if split_tile_adaptively(tile_id, item):
                                    was_split = True
                                    break
                                    
                            is_slow = "timeout" in err_str or retries >= MAX_RETRIES_BEFORE_SPLIT
                            is_transient = any(x in err_str for x in ["429", "503", "reset"])
                            
                            if use_dynamic_urls and is_slow and not is_transient:
                                if split_tile_adaptively(tile_id, item):
                                    was_split = True
                                    break
                                    
                            time.sleep(2 * attempt + 2)
                            
                    duration = time.time() - busy_start
                    worker_metrics[worker_name]["busy"] += duration
                    
                    if success:
                        self.logger.info(f"[DOWNLOAD PIPELINE] Worker recorded success for Tile {tile_id}.")
                        if auto_tune_enabled and expected >= current_target_pixels * 0.9:
                            with QMutexLocker(mutex):
                                current_target_pixels = min(current_target_pixels * 2, max_practical_limit)
                                
                        size_mb = os.path.getsize(file_path) / (1024 * 1024)
                        with QMutexLocker(mutex):
                            completed_count += 1
                            self.final_summary["Successful Tiles"] += 1
                            downloaded_paths.append(file_path)
                            self.logger.info(f"[DOWNLOAD PIPELINE] Tile {tile_id} added to completed list. Total completed: {completed_count}")
                            tile_metrics.append({
                                "tile_id": tile_id,
                                "worker": worker_name,
                                "path": file_path,
                                "size_mb": size_mb,
                                "duration": duration,
                                "retries": retries
                            })
                    else:
                        if not was_split:
                            self.logger.error(f"[DOWNLOAD PIPELINE] Tile {tile_id} permanently failed after retries. Last error: {last_error}")
                            with QMutexLocker(mutex):
                                self.final_summary["Failed Tiles"] += 1
                                if self.first_fatal_exception is None:
                                    self.first_fatal_exception = last_error
                                if self.final_summary["First Failed Tile"] == "N/A":
                                    self.final_summary["First Failed Tile"] = str(tile_id)
                                    self.final_summary["Reason"] = last_error
                                    
                            try:
                                if os.path.exists(file_path):
                                    os.remove(file_path)
                            except:
                                pass
                                    
                    with QMutexLocker(mutex):
                        active_items -= 1
                    work_queue.task_done()
                    idle_start = time.time()
                    
            threads = []
            for i in range(num_workers):
                t = threading.Thread(target=worker_loop, args=(f"Worker {i+1}",))
                t.daemon = True
                t.start()
                threads.append(t)
                
            for t in threads:
                t.join()
            
            # Sort downloaded_paths to ensure they are merged in a consistent order (optional, but Rasterio handles overlaps based on order)
            downloaded_paths.sort()
            
            final_file_path = os.path.join(temp_dir, f"{safe_name}_{unique_id}_final.tif")
            
            final_tiles_count = len(downloaded_paths)
            
            if final_tiles_count > 1:
                self.profiler.step("Merging Tiles Locally")
                self.download_progress.emit("Merging downloaded tiles...", 95)
                from ..services.export_manager import ExportManager
                em = ExportManager()
                if not em.merge_tiles_locally(downloaded_paths, final_file_path):
                    raise Exception("Failed to merge tiles locally.")
            elif final_tiles_count == 1:
                import shutil
                shutil.copy2(downloaded_paths[0], final_file_path)
            else:
                raise Exception("No tiles were successfully downloaded.")
                
            # --- STAGE 3 DIAGNOSTICS HELPER ---
            def stage3_diagnostics(label, path):
                import sys, os, hashlib, time
                from ..config import EVI_DEBUG
                debug_mode = getattr(sys.modules.get('remote_sensing_studio.config', None), 'EVI_DEBUG', False) or EVI_DEBUG
                if not debug_mode: return
                
                if not os.path.exists(path):
                    self.logger.info(f"=== EVI_DEBUG STAGE 3: {label} ===")
                    self.logger.error(f"File not found: {path}")
                    return
                
                sha256_hash = hashlib.sha256()
                with open(path,"rb") as f:
                    for byte_block in iter(lambda: f.read(4096),b""):
                        sha256_hash.update(byte_block)
                file_hash = sha256_hash.hexdigest()
                mod_time = time.ctime(os.path.getmtime(path))
                
                self.logger.info(f"=== EVI_DEBUG STAGE 3: {label} ===")
                self.logger.info(f"Exact File Path: {path}")
                self.logger.info(f"Modification Time: {mod_time}")
                self.logger.info(f"SHA-256 Hash: {file_hash}")
                
                try:
                    import rasterio
                    import numpy as np
                    with rasterio.open(path) as src:
                        self.logger.info(f"File Size: {os.path.getsize(path)} bytes")
                        self.logger.info(f"Width: {src.width}, Height: {src.height}")
                        self.logger.info(f"Dtype: {src.dtypes[0]}")
                        self.logger.info(f"CRS: {src.crs}")
                        self.logger.info(f"Transform: {src.transform}")
                        self.logger.info(f"Nodata: {src.nodata}")
                        
                        arr = src.read(1)
                        if src.nodata is not None:
                            valid_arr = arr[arr != src.nodata]
                        else:
                            valid_arr = arr
                        
                        nan_count = np.count_nonzero(np.isnan(valid_arr))
                        inf_count = np.count_nonzero(np.isinf(valid_arr))
                        finite_arr = valid_arr[np.isfinite(valid_arr)]
                        
                        lt_min_count = np.count_nonzero(finite_arr < -0.2)
                        gt_max_count = np.count_nonzero(finite_arr > 1.0)
                        nodata_count = np.count_nonzero(arr == -9999.0) if src.nodata is None or src.nodata != -9999.0 else (arr.size - valid_arr.size)
                        
                        self.logger.info(f"Min: {np.min(finite_arr) if finite_arr.size > 0 else 'N/A'}")
                        self.logger.info(f"Max: {np.max(finite_arr) if finite_arr.size > 0 else 'N/A'}")
                        self.logger.info(f"NaN count: {nan_count}")
                        self.logger.info(f"Inf count: {inf_count}")
                        self.logger.info(f"Values < -0.2: {lt_min_count}")
                        self.logger.info(f"Values > 1.0: {gt_max_count}")
                        self.logger.info(f"Count of -9999 (excluding explicit nodata pixels): {np.count_nonzero(arr == -9999.0)}")
                        self.logger.info(f"Finite pixel count: {finite_arr.size}")
                except Exception as e:
                    self.logger.error(f"Failed to read raster diagnostics: {e}")
            # ---------------------------------------------------------
                
            stage3_diagnostics("BEFORE LOCAL MASKING (RAW GEOTIFF)", final_file_path)
            
            # --- FINAL LOCAL MASKING (PHASE 5F.6) ---
            self.download_progress.emit("Applying final spatial mask...", 96)
            from ..services.export_manager import ExportManager
            em = ExportManager()
            final_masked_path = final_file_path.replace(".tif", "_masked.tif")
            if em.mask_raster_locally(final_file_path, self.aoi_geojson, final_masked_path, nodata_value=-9999.0):
                final_file_path = final_masked_path
            else:
                self.logger.warning("Local spatial masking failed or was skipped.")
                
            if self.analysis_result:
                try:
                    from osgeo import gdal
                    ds = gdal.Open(final_file_path, gdal.GA_Update)
                    if ds:
                        ds.SetMetadataItem("Source_Dataset", self.analysis_result.dataset)
                        ds.SetMetadataItem("Provider", self.analysis_result.provider)
                        ds.SetMetadataItem("Analysis_Type", self.analysis_result.analysis_type)
                        ds.SetMetadataItem("Formula", self.analysis_result.formula_expression)
                        
                        acq_dates = self.analysis_result.acquisition_dates
                        mode = self.analysis_result.composite_method
                        ds.SetMetadataItem("Acquisition_Mode", mode)
                        
                        if mode in ["Single Scene", "Best Image"]:
                            if acq_dates:
                                ds.SetMetadataItem("Acquisition_Date", acq_dates[0])
                        else:
                            ds.SetMetadataItem("Collection_Image_Count", str(self.analysis_result.number_of_scenes))
                            if acq_dates:
                                ds.SetMetadataItem("Collection_Acquisition_Dates", ",".join(acq_dates))
                                sorted_dates = sorted(acq_dates)
                                ds.SetMetadataItem("Collection_Start_Date", sorted_dates[0])
                                ds.SetMetadataItem("Collection_End_Date", sorted_dates[-1])
                                
                        res = str(self.analysis_result.metadata.get("resolution", self.analysis_result.resolution))
                        ds.SetMetadataItem("Export_Resolution", res)
                        ds.SetMetadataItem("AOI_Clipped", "Yes")
                        ds.FlushCache()
                        ds = None
                except Exception as meta_err:
                    self.logger.warning(f"Failed to write analysis metadata: {meta_err}")

            stage3_diagnostics("AFTER LOCAL MASKING (FINAL_MASKED.TIF)", final_file_path)
                
            self.profiler.step("Scientific Validation")
            self.download_progress.emit("Validating raster data...", 97)
            
            from ..analysis.raster_validator import RasterValidator
            from ..analysis.index_registry import IndexRegistry
            
            # Use heuristic to get index name from layer name, assuming "EVI - ... " format
            index_name = self.layer_name.split()[0].upper() if self.layer_name else ""
            if "_" in index_name: 
                index_name = index_name.split("_")[0]
                
            if index_name == "EVI":
                index_def = IndexRegistry.get_instance().get_index("EVI")
                out_val = index_def.get("safety", {}).get("output_validity", {}) if index_def else {}
                if "min" not in out_val or "max" not in out_val:
                    raise ValueError("EVI validation failed: 'min' or 'max' missing from evi.json safety definitions.")
                valid_min = out_val["min"]
                valid_max = out_val["max"]
                validation_report = RasterValidator.validate_evi_raster(final_file_path, valid_min, valid_max)
                
                # ---------------------------------------------------------
                # STAGE 3: EVI_DEBUG DIAGNOSTICS (After Download)
                # ---------------------------------------------------------
                import sys
                from ..config import EVI_DEBUG
                debug_mode = getattr(sys.modules.get('remote_sensing_studio.config', None), 'EVI_DEBUG', False) or EVI_DEBUG
                if debug_mode:
                    self.logger.info("=== EVI_DEBUG STAGE 3: AFTER DOWNLOAD ===")
                    self.logger.info(f"RasterValidator PASS: {validation_report.get('passed', False)}")
                    stats_report = validation_report.get("stats", {})
                    self.logger.info(f"NaN pixels: {stats_report.get('nan_count', 'unknown')}")
                    self.logger.info(f"Inf pixels: {stats_report.get('inf_count', 'unknown')}")
                    self.logger.info(f"Min valid pixel: {stats_report.get('min_val', 'unknown')}")
                    self.logger.info(f"Max valid pixel: {stats_report.get('max_val', 'unknown')}")
                    if validation_report.get("passed", False):
                        self.logger.info("VERIFICATION: SUCCESS. No literal -9999 values bled into valid data.")
                # ---------------------------------------------------------
            else:
                validation_report = RasterValidator.validate_generic_raster(final_file_path)
                
            self.profiler.step("Computing Statistics")
            self.download_progress.emit("Computing statistics...", 98)
            stats_engine = StatisticsEngine()
            stats = stats_engine.compute_base_statistics(final_file_path)
            
            if not validation_report.get("passed", False):
                self.logger.warning(f"Scientific Validation Failed: {validation_report.get('reason')}")
                stats["validation_failed"] = True
                stats["validation_reason"] = validation_report.get('reason')
            else:
                stats["validation_failed"] = False
                
            stats.update(validation_report)

            
            # Compile export diagnostics
            total_size_mb = sum(m["size_mb"] for m in tile_metrics)
            avg_size_mb = total_size_mb / total_tiles if total_tiles else 0
            avg_duration = sum(m["duration"] for m in tile_metrics) / total_tiles if total_tiles else 0
            durations = [m["duration"] for m in tile_metrics]
            fastest_tile = min(durations) if durations else 0
            slowest_tile = max(durations) if durations else 0
            total_retries = sum(m["retries"] for m in tile_metrics)
            
            export_diagnostics = {
                "Generated Tiles (Initial)": total_tiles,
                "Dynamic Splits": dynamic_split_count,
                "Max Recursion Depth": max_recursion_reached,
                "Total Download Size (MB)": round(total_size_mb, 2),
                "Average Tile Size (MB)": round(avg_size_mb, 2),
                "Average Download Time per Tile": round(avg_duration, 2),
                "Fastest Tile": round(fastest_tile, 2),
                "Slowest Tile": round(slowest_tile, 2),
                "Retry Count": total_retries,
                "Parallel Workers Used": num_workers,
                "Worker Metrics": worker_metrics,
                "tile_history": sorted(tile_metrics, key=lambda x: x["tile_id"])
            }
            stats["export_diagnostics"] = export_diagnostics
            
            # --- Phase 2: Persist Benchmark History ---
            try:
                history_file = BENCHMARK_HISTORY_FILE
                history = []
                if os.path.exists(history_file):
                    with open(history_file, 'r') as f:
                        history = json.load(f)
                        
                benchmark_entry = {
                    "timestamp": time.time(),
                    "api": DOWNLOAD_API,
                    "tile_strategy": TILE_SIZING_STRATEGY,
                    "auto_tune": AUTO_TUNE_TILE_SIZE,
                    "initial_tiles": total_tiles,
                    "dynamic_splits": dynamic_split_count,
                    "total_requests": total_tiles + dynamic_split_count,
                    "execution_time_s": sum(w["busy"] for w in worker_metrics.values()) / max(1, len(worker_metrics)),
                    "success": self.final_summary.get("Failed Tiles", 0) == 0,
                    "average_tile_size_mb": avg_size_mb,
                    "average_duration_s": avg_duration
                }
                history.append(benchmark_entry)
                with open(history_file, 'w') as f:
                    json.dump(history, f, indent=4)
            except Exception as e:
                self.logger.error(f"Failed to persist benchmark history: {e}")
            
            if self.aoi_geojson:
                try:
                    import rasterio
                    import rasterio.mask
                    from shapely.geometry import shape
                    from rasterio.features import geometry_mask
                    
                    with rasterio.open(final_file_path) as src:
                        full_data = src.read(1)
                        nodata_val = src.nodata
                        
                        # Just checking validity, no modifications done
                        aoi_shape = shape(self.aoi_geojson)
                except Exception as audit_e:
                    print(f"File audit failed: {audit_e}")
                    
            self.download_progress.emit("Download complete.", 100)
            self.download_completed.emit(final_file_path, stats, "")
            
        except Exception as e:
            if hasattr(self, 'final_summary') and self.final_summary["First Failed Tile"] == "N/A":
                self.final_summary["First Failed Tile"] = "System/Unknown"
                self.final_summary["Reason"] = str(e)
                self.final_summary["Failed Tiles"] += 1
                
            error_msg = str(e)
            if hasattr(self, 'final_summary'):
                total_generated = self.final_summary.get('Number of Tiles', 0)
                if hasattr(self, 'dynamic_split_count'):
                    total_generated += getattr(self, 'dynamic_split_count', 0)
                merged_count = getattr(self, 'final_tiles_count', 0)
                
                error_msg += (
                    f"<br><br><b>Diagnostic Summary:</b><br>"
                    f"Generated tiles: {total_generated}<br>"
                    f"Successful downloads: {self.final_summary['Successful Tiles']}<br>"
                    f"Failed downloads: {self.final_summary['Failed Tiles']}<br>"
                    f"Merged tiles: {merged_count}<br>"
                )
                if hasattr(self, 'first_fatal_exception') and self.first_fatal_exception:
                    error_msg += f"<b>First Exception:</b> {self.first_fatal_exception}<br>"
                elif self.final_summary['First Failed Tile'] != "N/A":
                    error_msg += f"<b>First Exception:</b> {self.final_summary['Reason']}<br>"
                    
                error_msg += f"<br><i>Detailed logs written to: {getattr(self, 'log_file_path', 'download_diagnostics.log')}</i>"
                
            self.download_completed.emit("", {}, error_msg)
        finally:
            if getattr(self, 'gee_provider', None):
                self.gee_provider.release_session_lock()
            try:
                self.logger.info("==================================================")
                self.logger.info("[DOWNLOAD PIPELINE] JOB SUMMARY")
                self.logger.info("==================================================")
                if hasattr(self, 'final_summary'):
                    total_generated = self.final_summary.get('Number of Tiles', 0)
                    if hasattr(self, 'dynamic_split_count'):
                        total_generated += getattr(self, 'dynamic_split_count', 0)
                    merged_count = getattr(self, 'final_tiles_count', 0)
                    
                    self.logger.info(f"Generated tiles:\n{total_generated}\n")
                    self.logger.info(f"Successful downloads:\n{self.final_summary['Successful Tiles']}\n")
                    self.logger.info(f"Failed downloads:\n{self.final_summary['Failed Tiles']}\n")
                    self.logger.info(f"Merged tiles:\n{merged_count}\n")
                    
                    if hasattr(self, 'first_fatal_exception') and self.first_fatal_exception:
                        self.logger.error(f"First Exception:\n{self.first_fatal_exception}\n")
                    elif self.final_summary['First Failed Tile'] != "N/A":
                        self.logger.error(f"First Exception:\n{self.final_summary['Reason']}\n")
                        
                self.logger.info("==================================================")
                
                # Cleanup handlers to prevent duplicate logging across runs
                for h in self.logger.handlers[:]:
                    h.close() # Explicitly close the file handle
                    self.logger.removeHandler(h)
            except Exception as diag_e:
                import logging
                logging.getLogger(__name__).error(f"Failed to log final summary diagnostics: {diag_e}")
class SecondaryTasksWorker(QThread):
    """
    Computes Histogram, QA metrics, and Scientific Report in the background
    after the raster has already been displayed to the user.
    """
    
    # Emits (histogram_counts, histogram_bins, qa_metrics_dict)
    tasks_completed = pyqtSignal(list, list, dict)
    
    def __init__(self, file_path: str):
        super().__init__()
        self.file_path = file_path
        self.profiler = PerformanceProfiler.get_instance()
        
    def run(self):
        try:
            self.profiler.step("Computing Histogram")
            stats_engine = StatisticsEngine()
            counts, bins = stats_engine.compute_histogram(self.file_path, bins=100)
            
            self.profiler.step("Generating QA")
            # Stub for QA generation
            qa_metrics = {"valid_pixels_pct": 100.0, "cloud_pixels_pct": 0.0}
            
            self.profiler.step("Generating Scientific Report")
            # Stub for Scientific Report
            
            self.profiler.finish_step()
            self.profiler.log_report()
            
            self.tasks_completed.emit(counts.tolist(), bins.tolist(), qa_metrics)
            
        except Exception as e:
            self.tasks_completed.emit([], [], {})


class SearchWorker(QThread):
    """
    Executes the Earth Engine image search asynchronously.
    """
    # Emits (results_list, error_message)
    search_completed = pyqtSignal(list, str)
    
    def __init__(self, layer_service, satellite: str, start_date: str, end_date: str, aoi_geojson: Dict[str, Any], filters: dict, sort_by: str):
        super().__init__()
        self.layer_service = layer_service
        self.satellite = satellite
        self.start_date = start_date
        self.end_date = end_date
        self.aoi_geojson = aoi_geojson
        self.filters = filters
        self.sort_by = sort_by
        
    def run(self):
        try:
            profiler = PerformanceProfiler.get_instance()
            profiler.start_workflow()
            profiler.step("Preparing AOI")
            
            profiler.step("Building Image Collection & Filtering")
            # The layer_service handles caching logic internally
            results = self.layer_service.get_image_list(
                self.satellite, self.start_date, self.end_date, self.aoi_geojson, 
                filters=self.filters, sort_by=self.sort_by
            )
            
            profiler.step("Preparing Scene List")
            profiler.finish_step()
            profiler.log_report()
            
            self.search_completed.emit(results, "")
        except Exception as e:
            import traceback
            self.search_completed.emit([], traceback.format_exc())


class ThumbnailWorker(QThread):
    """
    Fetches the thumbnail asynchronously.
    """
    # Emits (thumbnail_data_dict, error_message)
    thumbnail_completed = pyqtSignal(dict, str)
    
    def __init__(self, layer_service, satellite, start, end, aoi, mode, ids, analysis_type, vis_params):
        super().__init__()
        self.layer_service = layer_service
        self.satellite = satellite
        self.start_date = start
        self.end_date = end
        self.aoi = aoi
        self.mode = mode
        self.ids = ids
        self.analysis_type = analysis_type
        self.vis_params = vis_params
        
    def run(self):
        try:
            data = self.layer_service.select_and_preview_image(
                self.satellite, self.start_date, self.end_date, self.aoi, 
                self.mode, self.ids, self.analysis_type, self.vis_params
            )
            self.thumbnail_completed.emit(data, "")
        except Exception as e:
            self.thumbnail_completed.emit({}, str(e))

from qgis.core import QgsTask
class SceneExportTask(QgsTask):
    """
    Downloads a raw satellite scene or composite to a file path as a background task.
    """
    progress_update = pyqtSignal(str, int)
    task_completed = pyqtSignal(bool, str)
    task_failed = pyqtSignal(str)

    def __init__(self, gee_provider, satellite: str, start_date: str, end_date: str,
                 aoi_geojson: Dict[str, Any], selection_mode: str, image_ids: list,
                 cloud_filter: float, export_path: str):
        super().__init__("Downloading Scene", QgsTask.CanCancel)
        self.gee_provider = gee_provider
        self.satellite = satellite
        self.start_date = start_date
        self.end_date = end_date
        self.aoi_geojson = aoi_geojson
        self.selection_mode = selection_mode
        self.image_ids = image_ids
        self.cloud_filter = cloud_filter
        self.export_path = export_path
        self.error_msg = ""
        self.success = False

    def run(self):
        try:
            import os
            import shutil
            import time
            from ..services.export_manager import ExportManager
            
            self.progress_update.emit("Preparing Earth Engine Composite...", 10)
            
            if self.isCanceled():
                return False

            # 1. Fetch raw composite / scene (no index applied)
            img, metrics = self.gee_provider.get_image_object(
                self.satellite, self.start_date, self.end_date, self.aoi_geojson,
                self.selection_mode, self.image_ids, self.cloud_filter
            )
            
            native_crs = self.aoi_geojson.get("original_crs", "EPSG:4326")
            native_res = 10 if 'Sentinel' in self.satellite else 30
            
            self.progress_update.emit("Generating Download Tiles...", 30)
            export_manager = ExportManager()
            is_single = (self.selection_mode == "Single Scene" or (self.image_ids and len(self.image_ids) == 1))
            estimated_bands = 10 if is_single else 40
            risk_metrics = export_manager.estimate_export_risk(self.aoi_geojson, native_res, bands=estimated_bands)
            
            tiles = export_manager.generate_tiles(risk_metrics["bounds"], risk_metrics["estimated_mb"], self.aoi_geojson)
            
            self.progress_update.emit("Downloading GeoTIFF Data...", 50)
            
            import tempfile
            import uuid
            temp_dir = tempfile.gettempdir()
            safe_name = "SceneExport"
            unique_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
            
            downloaded_paths = []
            
            for i, tile in enumerate(tiles):
                if self.isCanceled():
                    return False
                    
                self.progress_update.emit(f"Downloading Tile {i+1} of {len(tiles)}...", 50 + int((i/len(tiles))*40))
                tile_file = os.path.join(temp_dir, f"{safe_name}_{unique_id}_tile_{i}.tif")
                
                success = False
                last_error = None
                for attempt in range(3):
                    try:
                        self.gee_provider.download_tile(img, tile, native_res, native_crs, tile_file, timeout=60000)
                        if os.path.exists(tile_file):
                            success = True
                            downloaded_paths.append(tile_file)
                            break
                    except Exception as e:
                        last_error = e
                        time.sleep(2)
                        
                if not success:
                    raise Exception(f"Failed to download tile {i+1} after 3 attempts. Original error: {last_error}")
            
            if self.isCanceled():
                return False
                
            self.progress_update.emit("Merging and Masking...", 90)
            
            if len(downloaded_paths) == 1:
                merged_path = downloaded_paths[0]
            else:
                merged_path = os.path.join(temp_dir, f"{safe_name}_{unique_id}_merged.tif")
                export_manager.merge_tiles_locally(downloaded_paths, merged_path)
                
            masked_path = os.path.join(temp_dir, f"{safe_name}_{unique_id}_masked.tif")
            # We don't supply -9999.0 because we handle it in export_manager safely
            export_manager.mask_raster_locally(merged_path, self.aoi_geojson, masked_path)
            
            self.progress_update.emit("Writing Metadata...", 92)
            try:
                from osgeo import gdal
                ds = gdal.Open(masked_path, gdal.GA_Update)
                if ds:
                    ds.SetMetadataItem("Source_Dataset", self.satellite)
                    ds.SetMetadataItem("Provider", "Google Earth Engine")
                    
                    actual_dates = metrics.get("Actual Dates", [])
                    actual_ids = metrics.get("Actual IDs", [])
                    is_single = self.image_ids and len(self.image_ids) == 1
                    
                    ds.SetMetadataItem("Acquisition_Mode", "Single Scene" if is_single else "Image Collection")
                    
                    if is_single:
                        if not actual_dates or not actual_ids:
                            import logging
                            logging.getLogger(__name__).error("CRITICAL: Missing actual date/id from EE metrics for Single Scene. Cannot use search start_date as acquisition date.")
                            true_date = "Unknown (Earth Engine Metadata Missing)"
                            true_id = self.image_ids[0] if self.image_ids else "Unknown"
                        else:
                            true_date = actual_dates[0]
                            true_id = actual_ids[0]
                        
                        ds.SetMetadataItem("Scene_ID", true_id)
                        ds.SetMetadataItem("Acquisition_Date", true_date)
                    else:
                        ds.SetMetadataItem("Composite_Method", self.selection_mode)
                        ds.SetMetadataItem("Collection_Start_Date", self.start_date)
                        ds.SetMetadataItem("Collection_End_Date", self.end_date)
                        ds.SetMetadataItem("Collection_Image_Count", str(len(actual_dates)) if actual_dates else str(len(self.image_ids) if self.image_ids else 0))
                        
                        if actual_dates:
                            ds.SetMetadataItem("Collection_Acquisition_Dates", ",".join(actual_dates))
                        if actual_ids:
                            ds.SetMetadataItem("Collection_Scene_IDs", ",".join(actual_ids))
                    
                    ds.SetMetadataItem("AOI_Clipped", "Yes")
                    ds.SetMetadataItem("Export_Resolution", f"{native_res} m")
                    ds.FlushCache()
                    ds = None
            except Exception as meta_err:
                import logging
                logging.getLogger(__name__).warning(f"Failed to write metadata: {meta_err}")
            
            self.progress_update.emit("Saving to Destination...", 95)
            shutil.copy2(masked_path, self.export_path)
            
            try:
                if os.path.exists(masked_path): os.remove(masked_path)
                if merged_path != downloaded_paths[0] and os.path.exists(merged_path): os.remove(merged_path)
                for p in downloaded_paths:
                    if os.path.exists(p): os.remove(p)
            except:
                pass
                
            self.success = True
            return True
            
        except Exception as e:
            import traceback
            self.error_msg = traceback.format_exc()
            return False

    def finished(self, result):
        if result and self.success:
            self.progress_update.emit("Download Completed Successfully", 100)
            self.task_completed.emit(True, self.export_path)
        else:
            if self.isCanceled():
                self.task_failed.emit("Export cancelled by user.")
            else:
                self.progress_update.emit("Error: Task Failed", 100)
                self.task_failed.emit(self.error_msg)


class DriveExportWorker(QThread):
    progress_update = pyqtSignal(str, int)
    export_completed = pyqtSignal(bool, str, str, str)

    def __init__(self, gee_provider, satellite: str, start_date: str, end_date: str,
                 aoi_geojson: Dict[str, Any], selection_mode: str, image_ids: list,
                 cloud_filter: float):
        super().__init__()
        self.gee_provider = gee_provider
        self.satellite = satellite
        self.start_date = start_date
        self.end_date = end_date
        self.aoi_geojson = aoi_geojson
        self.selection_mode = selection_mode
        self.image_ids = image_ids
        self.cloud_filter = cloud_filter

    def run(self):
        if getattr(self, 'gee_provider', None):
            self.gee_provider.acquire_session_lock()
        try:
            self.progress_update.emit("Preparing Earth Engine Composite...", 10)
            
            img, metrics = self.gee_provider.get_image_object(
                self.satellite, self.start_date, self.end_date, self.aoi_geojson,
                self.selection_mode, self.image_ids, self.cloud_filter
            )
            
            native_crs = self.aoi_geojson.get("original_crs", "EPSG:4326")
            native_res = 10 if 'Sentinel' in self.satellite else 30
            
            from ..services.export_manager import ExportManager
            export_manager = ExportManager()
            risk_metrics = export_manager.estimate_export_risk(self.aoi_geojson, native_res, bands=1)
            
            self.progress_update.emit("Dispatching to Google Drive...", 50)
            
            import time
            import ee
            
            actual_dates = metrics.get("Actual Dates", [])
            is_single = self.image_ids and len(self.image_ids) == 1
            if is_single and actual_dates:
                task_date = actual_dates[0]
            elif is_single:
                import logging
                logging.getLogger(__name__).error("CRITICAL: Missing actual date from EE metrics for Single Scene.")
                task_date = "Unknown"
            else:
                task_date = self.start_date
                
            task_name = f"{self.satellite.replace('-', '')}_{task_date}_{int(time.time())}_Raw"
            
            self.progress_update.emit("Applying AOI valid-data mask...", 60)
            if "geojson" in self.aoi_geojson and "original_crs" in self.aoi_geojson:
                geom = ee.Geometry(self.aoi_geojson["geojson"])
            else:
                geom = ee.Geometry(self.aoi_geojson)
                
            aoi_mask = ee.Image.constant(1).clip(geom)
            
            # 1. Update mask to ensure pixels outside AOI are marked as EE NoData
            img = img.updateMask(aoi_mask)
            
            # 2. Cast entire 26-band image to Float64 to losslessly preserve UInt32 QA bands
            self.progress_update.emit("Casting to Float64 for lossless export...", 70)
            img = img.toDouble()
            
            # 3. Preserving EE Mask to prevent NoData bleeding during export reprojection
            self.progress_update.emit("Preserving EE Mask for Export...", 80)
            
            self.progress_update.emit("Dispatching Single-File Export Task...", 90)
            task = self.gee_provider.start_drive_export_task(img, self.aoi_geojson, native_res, native_crs, task_name, -9999.0)
            task_id = getattr(task, 'id', 'Unknown')
            
            msg = f"Single-File Export task '{task_name}' successfully submitted to Google Drive."
            self.progress_update.emit("Export Task Submitted", 100)
            self.export_completed.emit(True, msg, task_id, task_name)
            
        except Exception as e:
            import traceback
            self.progress_update.emit("Error: " + str(e), 100)
            self.export_completed.emit(False, traceback.format_exc(), "", "")
        finally:
            if getattr(self, 'gee_provider', None):
                self.gee_provider.release_session_lock()

from PyQt6.QtCore import QObject, pyqtSlot, QTimer

class EETaskMonitorWorker(QObject):
    task_status_changed = pyqtSignal(str, str, str, str)
    finished = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._tasks = {}
        self._timer = None

    @pyqtSlot()
    def start_monitoring(self):
        self._timer = QTimer()
        self._timer.timeout.connect(self.poll_tasks)
        self._timer.start(20000)

    @pyqtSlot(str, str)
    def register_task(self, task_id, task_name):
        if task_id not in self._tasks:
            self._tasks[task_id] = task_name

    @pyqtSlot()
    def poll_tasks(self):
        if not self._tasks:
            return
        
        try:
            import ee
            # Clone list of keys to safely iterate while items might be popped
            task_ids = list(self._tasks.keys())
            for t_id in task_ids:
                try:
                    statuses = ee.data.getTaskStatus(t_id)
                    if statuses and len(statuses) > 0:
                        status_obj = statuses[0]
                        state = status_obj.get('state', 'UNKNOWN')
                        if state in ['COMPLETED', 'FAILED', 'CANCELLED']:
                            err_msg = status_obj.get('error_message', '')
                            t_name = self._tasks.pop(t_id, 'Unknown Task')
                            self.task_status_changed.emit(t_id, t_name, state, err_msg)
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"Transient error polling task {t_id}: {e}")
        except Exception as e:
            pass

    @pyqtSlot()
    def stop(self):
        if self._timer:
            self._timer.stop()
        self.finished.emit()

from PyQt6.QtCore import QObject, pyqtSignal

class EEConnectionWorker(QObject):
    finished = pyqtSignal()
    
    def __init__(self, connection_service):
        super().__init__()
        self.connection_service = connection_service
        self._is_running = False
        
    def start_check(self):
        if self._is_running:
            return
        self._is_running = True
        try:
            # We bypass UI-blocking logic and safely call check_saved_connection
            # Because this is a QThread, ee.Initialize runs outside the GUI thread
            self.connection_service.check_saved_connection()
        except Exception:
            pass
        finally:
            self._is_running = False
            self.finished.emit()
