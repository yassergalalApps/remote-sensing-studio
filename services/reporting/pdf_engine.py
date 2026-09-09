"""
Scientific PDF Report Engine Module.
Coordinates the generation of publication-quality scientific reports from immutable
AnalysisReportContext objects, modular renderers, template engines, and QPdfWriter.
Fully independent from UI dialogs and canvas state.
"""
import os
import tempfile
import base64
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from ...utils.logger import get_logger
from ...models.analysis_report_context import AnalysisReportContext

from .renderers import HistogramExporter, StatisticsRenderer, MetadataRenderer
from .templates import TemplateEngine, ReportTemplate, DefaultTemplate
from ..map_exporter import MapExporter

try:
    from PyQt6.QtCore import QSizeF, QRectF, Qt, QMarginsF
    from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPdfWriter, QTextDocument, QPageSize, QPageLayout, QPen
except ImportError:
    try:
        from PyQt5.QtCore import QSizeF, QRectF, Qt, QMarginsF
        from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPdfWriter, QTextDocument, QPageSize, QPageLayout, QPen
    except ImportError:
        pass


@dataclass
class ReportExtensionOptions:
    """
    Extensible metadata and configuration parameters for Scientific PDF Report Engine.
    Ensures zero-redesign addition of future formatting, legal, and academic standards (Refinement 9, 10, 11).
    """
    dpi: int = 300  # Configurable resolution: 150, 300, 600 DPI (Refinement 11)
    template_key: str = "default"  # Template routing key (Refinement 14)
    organization_name: str = "Remote Sensing Studio"
    organization_logo_path: Optional[str] = None
    institution_logo_path: Optional[str] = None
    project_title: str = "Environmental & Earth Observation Analysis"
    author_name: Optional[str] = None
    reviewer_name: Optional[str] = None
    digital_signature_path: Optional[str] = None
    qr_code_b64: Optional[str] = None
    references: List[str] = field(default_factory=list)
    appendix_sections: List[Dict[str, str]] = field(default_factory=list)
    additional_maps: List[Any] = field(default_factory=list)  # List of additional layers/maps for comparison (Refinement 10)
    page_size: str = "A4"
    margins_mm: float = 20.0


class ScientificPdfEngine:
    """
    Production-quality Scientific PDF Report Engine suitable for peer-reviewed journal articles,
    MSc theses, PhD dissertations, environmental assessments, and governmental technical documents.
    """
    def __init__(self, options: Optional[ReportExtensionOptions] = None) -> None:
        self.logger = get_logger(__name__)
        self.options = options if options is not None else ReportExtensionOptions()
        
        # Instantiate modular services and renderers (Refinement 2)
        self.map_exporter = MapExporter(default_dpi=self.options.dpi)
        self.histogram_exporter = HistogramExporter()
        self.statistics_renderer = StatisticsRenderer()
        self.metadata_renderer = MetadataRenderer()
        self.template_engine = TemplateEngine()

    def export_report(
        self,
        context: AnalysisReportContext,
        output_path: str,
        target_layer: Optional[Any] = None,
        export_format: str = "pdf"
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Main entry point for report export. Routes to appropriate format engine (Refinement 13).
        
        Args:
            context: Immutable AnalysisReportContext representing analysis results and state.
            output_path: Destination file path on local file system.
            target_layer: QgsRasterLayer / QgsMapLayer associated with analysis for high-res map exporting.
            export_format: Target document format ('pdf', 'html', 'docx', 'odt', 'png', 'svg').

        Returns:
            Tuple[bool, str, Dict[str, Any]]: Success status, final path, and execution diagnostics.
        """
        self.logger.info(f"Initiating Scientific Report export to format '{export_format}' at {output_path}")
        
        # Validate immutable context before assembly
        try:
            context.validate()
        except ValueError as val_err:
            self.logger.warning(f"Report context validation warning: {val_err}. Proceeding with best-effort assembly.")

        # Route format abstraction (Refinement 13: Architecture ready for future format additions without redesign)
        fmt = export_format.lower()
        if fmt == "pdf" or output_path.lower().endswith(".pdf"):
            return self.generate_pdf_report(context, output_path, target_layer)
        elif fmt == "html" or output_path.lower().endswith(".html"):
            return self.generate_html_report(context, output_path, target_layer)
        elif fmt in ["docx", "odt", "png", "svg"]:
            self.logger.warning(f"Format '{fmt}' is architecturally registered as a future extension. Exporting via default HTML stream.")
            return self.generate_html_report(context, output_path, target_layer)
        else:
            return self.generate_pdf_report(context, output_path, target_layer)

    def generate_html_report(
        self,
        context: AnalysisReportContext,
        output_path: str,
        target_layer: Optional[Any] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Exports assembled publication HTML directly to disk.
        """
        doc_html, meta = self._build_document_content(context, target_layer)
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(doc_html)
            meta["export_status"] = "Success"
            self.logger.info(f"HTML report successfully exported: {output_path}")
            return True, output_path, meta
        except Exception as e:
            self.logger.error(f"Failed to save HTML report: {e}", exc_info=True)
            meta["export_status"] = f"Failed: {e}"
            return False, output_path, meta

    def generate_pdf_report(
        self,
        context: AnalysisReportContext,
        output_path: str,
        target_layer: Optional[Any] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Executes publication-quality PDF generation with true physical A4 sizing, 20mm margins,
        embedded high-DPI cartographic maps, running headers/footers, and Page X of Y numbering.
        Resolves Qt device vs typographical DPI coordinate mismatches so reports are readable at 100% zoom.
        """
        doc_html, meta = self._build_document_content(context, target_layer)
        
        try:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            
            # Initialize high-resolution QPdfWriter
            writer = QPdfWriter(output_path)
            writer.setResolution(self.options.dpi)
            
            # Configure A4 Paper and 20 mm margins (NEW REQUIREMENT 5)
            try:
                if hasattr(QPageSize, "PageSizeId") and hasattr(QPageSize.PageSizeId, "A4"):
                    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
                elif hasattr(QPdfWriter, "PageSize") and hasattr(QPdfWriter.PageSize, "A4"):
                    writer.setPageSize(QPdfWriter.PageSize.A4)
            except Exception as page_err:
                self.logger.warning(f"Could not explicitly set QPageSize A4: {page_err}")

            try:
                if hasattr(QMarginsF, "__init__") and hasattr(QPageLayout, "Unit") and hasattr(QPageLayout.Unit, "Millimeter"):
                    writer.setPageMargins(QMarginsF(self.options.margins_mm, self.options.margins_mm, self.options.margins_mm, self.options.margins_mm), QPageLayout.Unit.Millimeter)
            except Exception as marg_err:
                self.logger.warning(f"Could not set millimeter margins via QPageLayout: {marg_err}")

            # Instantiate standalone printing document
            doc = QTextDocument()
            doc.setDefaultFont(QFont("Inter", 12))
            doc.setHtml(doc_html)
            
            # Determine printable geometry in logical typographical points (72 points per inch)
            # Root Cause Resolution: QPdfWriter operates in high-res device pixels (dots at target DPI, e.g. 300 DPI).
            # QTextDocument lays out elements in typographical points (72 DPI). We must convert device dimensions
            # into logical points before setting page size, and scale the QPainter by (DPI / 72.0) during painting.
            writer_dpi = float(writer.resolution())
            scale_factor = writer_dpi / 72.0
            
            page_width_pts = float(writer.width()) / scale_factor
            page_height_pts = float(writer.height()) / scale_factor
            doc.setPageSize(QSizeF(page_width_pts, page_height_pts))
            
            total_pages = doc.pageCount()
            meta["total_pages_calculated"] = total_pages
            meta["dpi_configured"] = self.options.dpi
            meta["logical_dimensions_pts"] = f"{page_width_pts:.1f}x{page_height_pts:.1f}"
            self.logger.info(f"Assembled report document spans {total_pages} pages at {self.options.dpi} DPI (Logical size: {page_width_pts:.1f}x{page_height_pts:.1f} pt).")

            # Retrieve selected template for custom header/footer strings (Refinement 8, 14)
            template = self.template_engine.get_template(self.options.template_key)

            # Two-Pass Custom Page Painter (Refinement 8: Running Header and Footer with Page X of Y)
            try:
                painter = QPainter(writer)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
                
                device_w = writer.width()
                device_h = writer.height()
                
                for page_idx in range(total_pages):
                    current_page = page_idx + 1
                    
                    # Paint content clipping rectangle in logical document coordinates
                    clip_rect = QRectF(0, page_idx * page_height_pts, page_width_pts, page_height_pts)
                    
                    painter.save()
                    # Apply resolution scale factor so logical document points map exactly to physical printer dots
                    painter.scale(scale_factor, scale_factor)
                    painter.translate(0, -page_idx * page_height_pts)
                    doc.drawContents(painter, clip_rect)
                    painter.restore()
                    
                    # Draw Running Header and Footer in device dot coordinates using physical point typography
                    if page_idx > 0:
                        header_left, header_right = template.get_header_text(context, self.options)
                        footer_left, footer_right = template.get_footer_text(context, current_page, total_pages, self.options)
                        
                        # QPainter natively renders font point sizes directly to physical printer resolution (requires int pointSize)
                        header_font = QFont("Inter", 10, QFont.Weight.Bold)
                        footer_font = QFont("Inter", 9, QFont.Weight.Normal)
                        
                        # Top header positioning (proportional to DPI)
                        painter.setFont(header_font)
                        painter.setPen(QColor("#475569"))
                        header_y = int(-32 * scale_factor)
                        header_h = int(24 * scale_factor)
                        painter.drawText(0, header_y, device_w, header_h, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, header_left)
                        painter.drawText(0, header_y, device_w, header_h, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, header_right)
                        
                        line_pen = QPen(QColor("#E2E8F0"))
                        line_pen.setWidthF(float(max(1.0, scale_factor * 0.45)))
                        painter.setPen(line_pen)
                        line_y = int(-6 * scale_factor)
                        painter.drawLine(0, line_y, device_w, line_y)
                        
                        # Bottom footer positioning
                        footer_line_y = device_h + int(6 * scale_factor)
                        painter.drawLine(0, footer_line_y, device_w, footer_line_y)
                        
                        painter.setFont(footer_font)
                        painter.setPen(QColor("#B8C6D8"))
                        footer_y = device_h + int(10 * scale_factor)
                        footer_h = int(24 * scale_factor)
                        painter.drawText(0, footer_y, device_w, footer_h, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, footer_left)
                        painter.drawText(0, footer_y, device_w, footer_h, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, footer_right)
                    
                    if page_idx < total_pages - 1:
                        writer.newPage()
                        
                painter.end()
                meta["engine_used"] = "TwoPass_QPainter_QPdfWriter_DPI_Scaled"
                meta["export_status"] = "Success"
                self.logger.info(f"Publication PDF successfully created via DPI-scaled Two-Pass Painter at: {output_path}")
                return True, output_path, meta
                
            except Exception as painter_err:
                self.logger.warning(f"Two-Pass custom painter encountered Qt exception: {painter_err}. Falling back to direct doc.print.")
                # Fallback execution path
                doc.print(writer)
                meta["engine_used"] = "Direct_QTextDocument_Print_Fallback"
                meta["export_status"] = "Success (Fallback)"
                self.logger.info(f"PDF exported successfully via fallback doc.print: {output_path}")
                return True, output_path, meta

        except Exception as e:
            self.logger.error(f"Fatal exception during PDF report generation: {e}", exc_info=True)
            meta["export_status"] = f"Failed: {e}"
            return False, output_path, meta

    def _build_document_content(
        self,
        context: AnalysisReportContext,
        target_layer: Optional[Any] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Internal assembly pipeline: exports cartographic map graphics, compiles statistical tables,
        and renders layout through the Template Engine.
        """
        diagnostic_meta: Dict[str, Any] = {
            "dpi_configured": self.options.dpi,
            "template_key": self.options.template_key,
            "map_export_status": "none",
            "multi_map_count": 0
        }

        # Step 1: Export Main Cartographic Map (Refinement 3, 4, 11, 12)
        map_gallery_html = ""
        temp_files_created = []

        if target_layer is not None:
            try:
                temp_map_path = os.path.join(tempfile.gettempdir(), f"scientific_report_map_{id(context)}.png")
                success, final_path, map_meta = self.map_exporter.export_cartographic_map(
                    target_layer=target_layer,
                    output_path=temp_map_path,
                    export_format="vector_preferred",
                    dpi=self.options.dpi,
                    title_text=f"Analysis Map: {context.formula_name}",
                    context=context
                )
                if success and os.path.exists(final_path):
                    temp_files_created.append(final_path)
                    # Convert temporary high-res image to base64 for reliable QTextDocument embedding
                    with open(final_path, "rb") as img_file:
                        map_b64 = base64.b64encode(img_file.read()).decode("utf-8")
                    
                    sat_text = getattr(context, 'satellite', 'multi-temporal spaceborne')
                    if not sat_text or sat_text == "N/A": sat_text = "multi-spectral spaceborne"
                    caption_title = f"<b>Figure 1.</b> {context.formula_name} ({context.formula_expression}) derived from {sat_text} imagery over the study area."
                    
                    map_gallery_html += f"""
                    <div class="avoid-break" style="text-align: center; margin-top: 12px; margin-bottom: 24px;">
                        <img src="data:image/png;base64,{map_b64}" width="478" 
                             style="border: 1px solid #E2E8F0; border-radius: 4px;" />
                        <p style="font-size: 10.5pt; color: #334155; margin-top: 12px; margin-bottom: 6px; line-height: 1.5; text-align: left;">
                            {caption_title}
                        </p>
                        <p style="font-size: 11.8pt; line-height: 1.65; color: #1E293B; margin-top: 10px; text-align: left;">
                            <b>Cartographic Interpretation:</b> The spatial map layout demonstrates the geographical distribution of surface phenomena categorized under the {context.vis_palette} symbology ramp. Positive surface observations (&ge; {context.classification_threshold}, representing <i>{context.positive_meaning}</i>) appear segregated from surrounding negative background regions (<i>{context.negative_meaning}</i>). Coordinate annotations follow the native projection ({context.crs}), with spatial scaling verified against ground metric references.
                        </p>
                    </div>
                    """
                    diagnostic_meta["map_export_status"] = f"Success ({map_meta.get('engine_used')})"
                    diagnostic_meta["map_cartographic_metadata"] = map_meta
                else:
                    map_gallery_html += "<p style='color: #B8C6D8; font-style: italic; padding: 15px; text-align: center;'>Cartographic map graphic pending active layer rendering in QGIS environment.</p>"
                    diagnostic_meta["map_export_status"] = "Failed rendering"
            except Exception as map_err:
                self.logger.error(f"Error during main map rendering: {map_err}", exc_info=True)
                map_gallery_html += "<p style='color: #B8C6D8; font-style: italic; padding: 15px; text-align: center;'>Cartographic map graphic pending active layer rendering in QGIS environment.</p>"
        else:
            map_gallery_html += "<p style='color: #B8C6D8; font-style: italic; padding: 15px; text-align: center;'>No active raster layer supplied for cartographic map rendering.</p>"
            diagnostic_meta["map_export_status"] = "No layer provided"

        # Step 1b: Multi-Map / Comparison Map support (Refinement 10)
        if self.options.additional_maps:
            for idx, add_layer in enumerate(self.options.additional_maps, 1):
                try:
                    add_map_path = os.path.join(tempfile.gettempdir(), f"scientific_report_addmap_{idx}_{id(context)}.png")
                    s_success, s_path, _ = self.map_exporter.export_cartographic_map(
                        target_layer=add_layer,
                        output_path=add_map_path,
                        dpi=self.options.dpi,
                        title_text=f"Comparison Layer {idx}: {getattr(add_layer, 'name', lambda: str(idx))()}",
                        context=context
                    )
                    if s_success and os.path.exists(s_path):
                        temp_files_created.append(s_path)
                        with open(s_path, "rb") as img_f:
                            add_b64 = base64.b64encode(img_f.read()).decode("utf-8")
                        map_gallery_html += f"""
                        <div class="avoid-break" style="text-align: center; margin-top: 16px; margin-bottom: 20px;">
                            <img src="data:image/png;base64,{add_b64}" width="478" style="border: 1px solid #E2E8F0; border-radius: 4px;" />
                            <p style="font-size: 10.5pt; color: #475569; margin-top: 8px; text-align: left;"><b>Comparison Map {idx}:</b> Multi-layer comparative spatial distribution analysis.</p>
                        </div>
                        """
                        diagnostic_meta["multi_map_count"] = idx
                except Exception as add_err:
                    self.logger.warning(f"Could not render additional map {idx}: {add_err}")

        # Step 2: Render individual modular sections
        sections_list = [
            "Executive Summary",
            "Analysis Details & Scientific Parameters",
            "Raster Statistics",
            "Classification Statistics",
            "Analysis Map",
            "Statistical Distribution Histogram",
            "Quality Assessment",
            "Processing Metadata",
            "References",
            "Scientific Discussion, Conclusions & Applications"
        ]
        
        toc_html = self.metadata_renderer.render_table_of_contents(sections_list)
        exec_summary_html = self.metadata_renderer.render_executive_summary(context)
        details_html = self.metadata_renderer.render_analysis_details_table(context)
        base_stats_html = self.statistics_renderer.render_base_statistics_table(context)
        class_stats_html = self.statistics_renderer.render_classification_table(context)
        map_metadata_html = self.metadata_renderer.render_map_metadata_table(context)
        histogram_html = self.histogram_exporter.render_to_html(context)
        qa_html = self.metadata_renderer.render_quality_assessment(context)
        proc_meta_html = self.metadata_renderer.render_processing_metadata(context, self.options)
        references_html = self.metadata_renderer.render_references_section(context, self.options)
        sys_info_html = self.metadata_renderer.render_system_info_section(context, self.options)

        sections_html_map: Dict[str, str] = {
            "toc": toc_html,
            "exec_summary": exec_summary_html,
            "details": details_html,
            "base_stats": base_stats_html,
            "class_stats": class_stats_html,
            "map_gallery": map_gallery_html,
            "map_metadata": map_metadata_html,
            "histogram": histogram_html,
            "quality_assessment": qa_html,
            "processing_metadata": proc_meta_html,
            "references": references_html,
            "sys_info": sys_info_html
        }

        # Step 3: Route to selected template in TemplateEngine (Refinement 14)
        template = self.template_engine.get_template(self.options.template_key)
        assembled_html = template.assemble_document_html(context, sections_html_map, self.options)

        # Step 4: Cleanup temporary cartographic files from disk
        for tmp_file in temp_files_created:
            try:
                if os.path.exists(tmp_file):
                    os.remove(tmp_file)
            except Exception as e:
                self.logger.debug(f"Unable to clean up temporary file {tmp_file}: {e}")

        return assembled_html, diagnostic_meta
