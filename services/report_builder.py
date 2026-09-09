"""
Report Builder Service Module.
Transform AnalysisResult and AnalysisReportContext models into production Scientific Reports.
"""
import logging
from typing import Optional, Any
from ..models.analysis_result import AnalysisResult
from ..models.analysis_report_context import AnalysisReportContext
from ..utils.logger import get_logger


class ReportBuilder:
    """
    Service responsible for transforming analysis outputs into Scientific Reports
    (HTML, PDF, Markdown) utilizing the universal Scientific PDF Report Engine.
    """
    
    @staticmethod
    def generate_html(result: AnalysisResult) -> str:
        """
        Generate default basic HTML overview for an AnalysisResult model.
        """
        logger = get_logger(__name__)
        logger.info(f"Generating HTML report overview for {result.formula_name}")
        return f"""
        <html><body>
            <h1>Scientific Analysis Report: {result.formula_name}</h1>
            <p><b>Expression:</b> {result.formula_expression}</p>
            <p><b>Dataset:</b> {result.dataset} ({result.satellite} via {result.provider})</p>
            <p><b>Scenes Used:</b> {result.number_of_scenes} ({result.composite_method})</p>
            <p><b>Execution Time:</b> {result.execution_time_sec} s ({result.processing_timestamp})</p>
        </body></html>
        """

    @staticmethod
    def export_pdf(html_content: str, output_path: str, context: Optional[AnalysisReportContext] = None, target_layer: Optional[Any] = None) -> bool:
        """
        Export scientific report to publication-quality PDF.
        If an AnalysisReportContext is supplied, invokes the full ScientificPdfEngine cartographic workflow.
        Otherwise falls back to standard document rendering.
        """
        logger = get_logger(__name__)
        try:
            if context is not None:
                from .reporting.pdf_engine import ScientificPdfEngine
                engine = ScientificPdfEngine()
                success, path, meta = engine.export_report(
                    context=context,
                    output_path=output_path,
                    target_layer=target_layer,
                    export_format="pdf"
                )
                logger.info(f"Scientific PDF Engine export finished: status={success}, metadata={meta}")
                return success
            else:
                # Basic direct HTML printing if only string supplied
                try:
                    from PyQt6.QtGui import QPdfWriter, QTextDocument
                except ImportError:
                    from PyQt5.QtGui import QPdfWriter, QTextDocument
                    
                writer = QPdfWriter(output_path)
                writer.setResolution(300)
                doc = QTextDocument()
                doc.setHtml(html_content)
                doc.print(writer)
                logger.info(f"Basic HTML content exported to PDF: {output_path}")
                return True
        except Exception as e:
            logger.error(f"Failed to export PDF in ReportBuilder: {e}", exc_info=True)
            return False
        
    @staticmethod
    def export_markdown(result: AnalysisResult, output_path: str) -> bool:
        """
        Export simple Markdown representation of the analysis result.
        """
        logger = get_logger(__name__)
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"# Scientific Analysis Report: {result.formula_name}\n\n")
                f.write(f"- **Expression:** `{result.formula_expression}`\n")
                f.write(f"- **Dataset & Satellite:** {result.dataset} ({result.satellite})\n")
                f.write(f"- **Provider:** {result.provider}\n")
                f.write(f"- **Scenes Used:** {result.number_of_scenes} ({result.composite_method})\n")
                f.write(f"- **Execution Duration:** {result.execution_time_sec} s\n")
                f.write(f"- **Timestamp:** {result.processing_timestamp}\n")
            logger.info(f"Markdown report exported: {output_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to export Markdown: {e}", exc_info=True)
            return False
