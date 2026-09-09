"""
Visualization Service Module.
Handles injecting computed data layers natively into QGIS.
Must ONLY be called from the main GUI thread.
"""

import os
import tempfile
import urllib.request
import urllib.parse
from typing import Dict, Any
from ..utils.logger import get_logger
from ..models.visualization_result import VisualizationResult
from ..models.analysis_result import AnalysisResult

try:
    import qgis.utils
    from qgis.core import QgsRasterLayer, QgsProject
    from PyQt6.QtCore import QObject, pyqtSignal
    HAS_QGIS = True
except ImportError:
    HAS_QGIS = False
    class QObject:
        pass
    def pyqtSignal(*args, **kwargs):
        pass

class VisualizationService(QObject):
    """
    Takes computed data (XYZ Tile URLs or GeoTIFF Downloads)
    and natively loads them into the QGIS Layer Tree.
    """
    
    task_notification = pyqtSignal(str, str, str)
    visualization_completed = pyqtSignal(VisualizationResult)
    progress_update = pyqtSignal(str, int)
    
    _instance = None
    
    @classmethod
    def get_instance(cls) -> 'VisualizationService':
        if cls._instance is None:
            cls._instance = VisualizationService()
        return cls._instance
        
    def __init__(self) -> None:
        super().__init__()
        self.logger = get_logger(__name__)
        
    def visualize_result_async(self, result: AnalysisResult) -> None:
        from ..utils.workers import DownloadWorker

        # Use tile URLs if provided (like local file path from Export Task), else empty and rely on dynamic generation
        urls = result.tile_download_urls if result.tile_download_urls else ([result.download_url] if result.download_url else [])

        from ..services.layer_service import LayerService
        self.download_worker = DownloadWorker(
            layer_name=result.output_layer_name,
            download_urls=urls,
            aoi_geojson=result.aoi_geojson,
            ee_image=result.computed_image,
            ee_scale=result.ee_scale,
            ee_crs=result.ee_crs,
            ee_tiles=result.ee_tiles,
            gee_provider=LayerService.get_instance().gee_provider,
            analysis_result=result
        )
        # Pass progress updates through VisualizationService
        self.download_worker.download_progress.connect(self.progress_update.emit)
        # Use a lambda to pass the AnalysisResult forward
        self.download_worker.download_completed.connect(
            lambda path, stats, err: self._on_download_completed(path, stats, err, result)
        )
        self._notify_task("Visualization", "Downloading GeoTIFF from Provider...", "success")
        self.download_worker.start()

    def visualize_local_result(self, result: AnalysisResult) -> None:
        """Loads a locally computed GeoTIFF directly into QGIS, skipping all download logic."""
        import os
        try:
            self._notify_task("Visualization", "Loading local GeoTIFF directly into QGIS...", "success")
            
            # Extract local path from metadata or tile_download_urls
            file_path = result.metadata.get("local_output_path")
            if not file_path and result.tile_download_urls:
                file_path = result.tile_download_urls[0].replace("file:///", "").replace("file://", "")
                
            if not file_path or not os.path.exists(file_path):
                error_msg = f"Local result was created successfully, but QGIS could not load the output raster (File not found: {file_path})."
                raise ValueError(error_msg)
                
            from ..analysis.statistics_engine import StatisticsEngine
            stats_engine = StatisticsEngine()
            precomputed_stats = stats_engine.compute_base_statistics(file_path)
            
            vis_result = self._finish_add_geotiff_layer(file_path, precomputed_stats, result.output_layer_name, result.visualization_params)
            self.visualization_completed.emit(vis_result)
            
            if vis_result.success:
                from ..utils.workers import SecondaryTasksWorker
                self.secondary_worker = SecondaryTasksWorker(file_path)
                self.secondary_worker.start()
                
        except Exception as e:
            self.logger.error(f"Local visualization failed: {e}", exc_info=True)
            self._notify_task("Visualization Failed", str(e), "error")
            self.visualization_completed.emit(VisualizationResult(False, "", result.output_layer_name, "", "", "", "", str(e)))

    def _on_download_completed(self, file_path: str, precomputed_stats: dict, error: str, analysis_result: AnalysisResult) -> None:
        if error:
            self.logger.error(f"Download failed: {error}")
            self._notify_task("Visualization Failed", error, "error")
            self.visualization_completed.emit(VisualizationResult(False, "", analysis_result.output_layer_name, "", "", "", "", error))
            return
            
        self._notify_task("Visualization", "GeoTIFF downloaded successfully.", "success")
        
        try:
            if "export_diagnostics" in precomputed_stats:
                analysis_result.quality_metrics.update(precomputed_stats["export_diagnostics"])
                
            vis_result = self._finish_add_geotiff_layer(file_path, precomputed_stats, analysis_result.output_layer_name, analysis_result.visualization_params)
            self.visualization_completed.emit(vis_result)
            
            # Start Secondary Tasks now that the raster is on screen
            from ..utils.workers import SecondaryTasksWorker
            self.secondary_worker = SecondaryTasksWorker(file_path)
            # The UI can connect to self.secondary_worker.tasks_completed if needed
            self.secondary_worker.start()
            
        except Exception as e:
            self.logger.error(f"Visualization failed: {e}", exc_info=True)
            self.visualization_completed.emit(VisualizationResult(False, "", analysis_result.output_layer_name, "", "", "", "", str(e)))

    def _finish_add_geotiff_layer(self, file_path: str, precomputed_stats: dict, layer_name: str, vis_params: Dict[str, Any] = None) -> VisualizationResult:
        """Strict GeoTIFF validation pipeline and native injection on the main UI thread."""
        if not HAS_QGIS:
            return VisualizationResult(False, "", layer_name, "", "", "", "", "QGIS core not available.")
            
        from qgis.core import (
            QgsProject,
            QgsRasterLayer,
            QgsSingleBandPseudoColorRenderer,
            QgsRasterShader,
            QgsColorRampShader,
            QgsStyle
        )
        import qgis.utils
        from ..utils.profiler import PerformanceProfiler
        
        profiler = PerformanceProfiler.get_instance()
        profiler.step("Opening Raster")
            
        # 1. Create the QgsRasterLayer
        layer = QgsRasterLayer(file_path, layer_name)
        
        self.logger.info(f"========== OBJECT LIFECYCLE: STAGE 1 (Layer Creation) ==========")
        self.logger.info(f"id(layer): {id(layer)}")
        self.logger.info(f"id(layer.renderer()): {id(layer.renderer()) if layer.renderer() else 'None'}")
        self.logger.info(f"layer.renderer().type(): {layer.renderer().type() if layer.renderer() else 'None'}")
        self.logger.info(f"================================================================")
        
        # --- Raster Validation Checks ---
        self.logger.info("--- Raster Validation Checks ---")
        
        if not layer.isValid():
            raise ValueError("Validation Failed: The QgsRasterLayer is completely invalid and cannot be loaded by QGIS.")
            
        self.logger.info(f"Extent: {layer.extent().toString()}")
        self.logger.info(f"CRS: {layer.crs().authid()}")
        self.logger.info(f"Width: {layer.width()}")
        self.logger.info(f"Height: {layer.height()}")
        self.logger.info(f"Provider: {layer.dataProvider().name()}")
        
        # Source path validation
        import os
        # Normalize paths to handle backslashes vs forward slashes on Windows
        if os.path.normpath(layer.source()) != os.path.normpath(file_path):
            raise ValueError(f"Validation Failed: Layer source path ({layer.source()}) does not match the downloaded TIFF ({file_path}).")
            
        # Dimension validation
        if layer.width() <= 0 or layer.height() <= 0 or layer.extent().isEmpty():
            raise ValueError("Validation Failed: Raster has invalid dimensions (width/height <= 0) or an empty geometric extent.")
            
        # The image will load with the CRS generated during the Earth Engine export phase.
        self.logger.info(f"Loaded Native CRS: {layer.crs().authid()}")
            
        provider = layer.dataProvider()
        if not provider or not provider.isValid():
            raise ValueError("Validation Failed: Raster Data Provider is invalid or missing.")
            
        import math
        
        # 2. Detect NoData correctly
        if hasattr(provider, "sourceNoDataValue"):
            source_nodata = provider.sourceNoDataValue(1)
        elif hasattr(provider, "srcNoDataValue"):
            source_nodata = provider.srcNoDataValue(1)
        else:
            source_nodata = None
            
        self.logger.info(f"Native NoData Value: {source_nodata}")
        
        # Force the provider to use the native NoData value for transparency and statistics
        if hasattr(provider, "setUseSourceNoDataValue"):
            provider.setUseSourceNoDataValue(1, True)
        elif hasattr(provider, "setUseSrcNoDataValue"):
            provider.setUseSrcNoDataValue(1, True)
        
        # 3. Apply pre-computed statistics instead of blocking QGIS UI thread
        
        # Extract from precomputed_stats dictionary
        if 'min' not in precomputed_stats or 'max' not in precomputed_stats:
            raise ValueError("Visualization Error: Raster statistics are missing. Refusing to fabricate fake scientific values (e.g. 0.0 to 1.0).")
            
        raster_min = precomputed_stats['min']
        raster_max = precomputed_stats['max']
        
        self.logger.info(f"Applied Pre-computed Statistics - Min: {raster_min}, Max: {raster_max}")
        
        if math.isnan(raster_min) or math.isnan(raster_max):
            raise ValueError("Validation Failed: Pre-computed raster statistics computation yielded NaN. The layer contains no valid numeric pixels.")
            
        elif raster_min == raster_max:
            raster_min -= 0.1
            raster_max += 0.1

        # 4. Renderer redesign
        profiler.step("Renderer")
        vis_min = raster_min
        vis_max = raster_max
        
        stretch_mode = vis_params.get("stretch_mode", "Original") if vis_params else "Original"
        
        if vis_params and stretch_mode == "Custom":
            if 'min' in vis_params and vis_params['min'] is not None:
                vis_min = vis_params['min']
            if 'max' in vis_params and vis_params['max'] is not None:
                vis_max = vis_params['max']
        
        from ..visualization.renderers.renderer_factory import RendererFactory
        
        # vis_params contains the full index definitions visualization block
        self.logger.info(f"--- VISUALIZATION SERVICE DIAGNOSTICS ---")
        self.logger.info(f"Calling RendererFactory.create_renderer with vis_params: {vis_params}")
        renderer = RendererFactory.create_renderer(provider, vis_min, vis_max, vis_params if vis_params else {})
        self.logger.info(f"RendererFactory returned: {type(renderer).__name__ if renderer else 'None'}")
        
        if not renderer:
            # Fallback to standard grayscale if no renderer is generated by the factory
            from qgis.core import QgsSingleBandGrayRenderer, QgsContrastEnhancement
            renderer = QgsSingleBandGrayRenderer(provider, 1)
            ce = QgsContrastEnhancement(provider.dataType(1))
            ce.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
            ce.setMinimumValue(vis_min)
            ce.setMaximumValue(vis_max)
            renderer.setContrastEnhancement(ce)
            
        if isinstance(renderer, QgsSingleBandPseudoColorRenderer) and renderer.shader():
            # Requested Logging: Before Adding to Project
            self.logger.info("--- BEFORE ADDING TO PROJECT: COLOR RAMP VERIFICATION ---")
            r_shader = renderer.shader().rasterShaderFunction()
            if r_shader and r_shader.sourceColorRamp():
                self.logger.info(f"sourceColorRamp(): {r_shader.sourceColorRamp()}")
                self.logger.info(f"type(): {r_shader.sourceColorRamp().type()}")
                if hasattr(r_shader.sourceColorRamp(), 'name'):
                    self.logger.info(f"name(): {r_shader.sourceColorRamp().name()}")
            self.logger.info("---------------------------------------------------------")
            
        # ==============================================================================================
        # CRITICAL LIFECYCLE INITIALIZATION SEQUENCE
        # ==============================================================================================
        # 1. We MUST set the custom renderer on the active layer BEFORE adding it to the QgsProject.
        # 2. If the layer is added to the project first, QGIS natively intercepts the `layersAdded` event
        #    and immediately dispatches a background render job using its default (e.g., Grayscale) renderer.
        # 3. Setting the custom renderer afterward creates a race condition where the initial draw cache
        #    contains a distorted artifact or gray rectangle, requiring the user to manually trigger
        #    a canvas extent change (e.g., "Zoom to Layer") to invalidate the cache and fix the display.
        # DO NOT reverse this order. DO NOT add forced canvas extent changes to compensate.
        # ==============================================================================================
        
        self.logger.info(f"========== OBJECT LIFECYCLE: STAGE 2 (Before setRenderer) ==========")
        self.logger.info(f"id(layer): {id(layer)}")
        self.logger.info(f"id(layer.renderer()): {id(layer.renderer()) if layer.renderer() else 'None'}")
        self.logger.info(f"layer.renderer().type(): {layer.renderer().type() if layer.renderer() else 'None'}")
        self.logger.info(f"====================================================================")
        
        if renderer:
            self.logger.info(f"Executing layer.setRenderer(renderer)")
            layer.setRenderer(renderer)
            self.logger.info(f"Immediately after setRenderer(), type(layer.renderer()).__name__ = {type(layer.renderer()).__name__ if layer.renderer() else 'None'}")
            
            self.logger.info(f"========== OBJECT LIFECYCLE: STAGE 3 (After setRenderer) ==========")
            self.logger.info(f"id(layer): {id(layer)}")
            self.logger.info(f"id(layer.renderer()): {id(layer.renderer()) if layer.renderer() else 'None'}")
            self.logger.info(f"layer.renderer().type(): {layer.renderer().type() if layer.renderer() else 'None'}")
            self.logger.info(f"===================================================================")
            
            self.logger.info(f"Immediately before adding to project, layer.renderer().type() = {layer.renderer().type() if layer.renderer() else 'None'}")
        
        self.logger.info(f"========== OBJECT LIFECYCLE: STAGE 4 (Before addMapLayer) ==========")
        self.logger.info(f"id(layer): {id(layer)}")
        self.logger.info(f"id(layer.renderer()): {id(layer.renderer()) if layer.renderer() else 'None'}")
        self.logger.info(f"layer.renderer().type(): {layer.renderer().type() if layer.renderer() else 'None'}")
        self.logger.info(f"====================================================================")
        
        # Add to project - This automatically triggers a native, clean canvas render event
        # using the custom renderer we just configured.
        QgsProject.instance().addMapLayer(layer)
        
        self.logger.info(f"========== OBJECT LIFECYCLE: STAGE 5 (After addMapLayer) ==========")
        self.logger.info(f"id(layer): {id(layer)}")
        self.logger.info(f"id(layer.renderer()): {id(layer.renderer()) if layer.renderer() else 'None'}")
        self.logger.info(f"layer.renderer().type(): {layer.renderer().type() if layer.renderer() else 'None'}")
        self.logger.info(f"===================================================================")
        
        self.logger.info(f"Immediately after adding to project, layer.renderer().type() = {layer.renderer().type() if layer.renderer() else 'None'}")
        self.logger.info(f"-----------------------------------------")
        
        # Refresh Symbology in the Layer Tree
        layer.triggerRepaint()
        if hasattr(layer, 'emitStyleChanged'):
            layer.emitStyleChanged()
            
        if qgis.utils.iface:
            try:
                # Explicitly refresh the layer tree legend node
                root = QgsProject.instance().layerTreeRoot()
                node = root.findLayer(layer.id())
                if node:
                    self.logger.info(f"========== OBJECT LIFECYCLE: STAGE 6 (Tree Node Refresh) ==========")
                    self.logger.info(f"id(node.layer()): {id(node.layer()) if node.layer() else 'None'}")
                    self.logger.info(f"id(node.layer().renderer()): {id(node.layer().renderer()) if node.layer() and node.layer().renderer() else 'None'}")
                    self.logger.info(f"node.layer().renderer().type(): {node.layer().renderer().type() if node.layer() and node.layer().renderer() else 'None'}")
                    self.logger.info(f"===================================================================")
                    
                    model = qgis.utils.iface.layerTreeView().layerTreeModel()
                    model.refreshLayerLegend(node)
                    
                qgis.utils.iface.layerTreeView().refreshLayerSymbology(layer.id())
            except Exception as ex:
                self.logger.warning(f"Could not fully refresh layer legend: {ex}")
        
        # --- RUNTIME DEBUGGING: RASTER STATE ---
        self.logger.info("========== RUNTIME RASTER DEBUGGING ==========")
        self.logger.info(f"layer.source(): {layer.source()}")
        self.logger.info(f"provider.dataSourceUri(): {provider.dataSourceUri()}")
        self.logger.info(f"layer.extent(): {layer.extent().toString()}")
        self.logger.info(f"provider.extent(): {provider.extent().toString()}")
        self.logger.info(f"layer.width(): {layer.width()}")
        self.logger.info(f"layer.height(): {layer.height()}")
        self.logger.info(f"layer.crs(): {layer.crs().authid()}")
        if hasattr(provider, "srcNoDataValue"):
            self.logger.info(f"provider.srcNoDataValue(1): {provider.srcNoDataValue(1)}")
        if hasattr(provider, "sourceNoDataValue"):
            self.logger.info(f"provider.sourceNoDataValue(1): {provider.sourceNoDataValue(1)}")
        if hasattr(provider, "userNoDataValues"):
            self.logger.info(f"provider.userNoDataValues(1): {provider.userNoDataValues(1)}")
        
        renderer_type = layer.renderer().type() if layer.renderer() else "None"
        self.logger.info(f"layer.renderer().type(): {renderer_type}")
        self.logger.info("===============================================")
        
        self._notify_task("Visualization", f"Successfully added and validated layer: {layer_name}", "success")
        return VisualizationResult(
            success=True,
            layer_id=layer.id(),
            layer_name=layer.name(),
            extent=layer.extent().toString(),
            crs=layer.crs().authid(),
            pixel_size=f"{layer.width()}x{layer.height()}",
            renderer=layer.providerType(),
            statistics=precomputed_stats
        )

    def _notify_task(self, title: str, message: str, level: str = "success"):
        if level == "error":
            self.logger.error(f"VISUALIZATION ERROR - {title}: {message}")
        else:
            self.logger.info(f"VISUALIZATION - {title}: {message}")
        self.task_notification.emit(title, message, level)
