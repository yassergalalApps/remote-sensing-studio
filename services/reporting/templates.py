"""
Report Template Engine Module.
Defines abstract ReportTemplate interface, DefaultTemplate production implementation,
and extensible architectures for MSc, PhD, Journal Paper, and Organization templates.
"""
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Tuple, Optional
from ...utils.logger import get_logger
from ...models.analysis_report_context import AnalysisReportContext


class ReportTemplate(ABC):
    """
    Abstract Base Class representing a customizable publication report template.
    """
    @abstractmethod
    def get_template_name(self) -> str:
        """Return the unique human-readable name of the template."""
        pass

    @abstractmethod
    def render_cover_page(self, context: AnalysisReportContext, options: Optional[Any] = None) -> str:
        """Render the front cover page HTML string."""
        pass

    @abstractmethod
    def get_header_text(self, context: AnalysisReportContext, options: Optional[Any] = None) -> Tuple[str, str]:
        """Return (left_text, right_text) to be rendered on running page headers."""
        pass

    @abstractmethod
    def get_footer_text(self, context: AnalysisReportContext, page_num: int, total_pages: int, options: Optional[Any] = None) -> Tuple[str, str]:
        """Return (left_text, right_text) to be rendered on running page footers."""
        pass

    @abstractmethod
    def assemble_document_html(
        self,
        context: AnalysisReportContext,
        sections_html: Dict[str, str],
        options: Optional[Any] = None
    ) -> str:
        """
        Assemble the complete document HTML styling and section order.
        """
        pass


class DefaultTemplate(ReportTemplate):
    """
    Production default scientific report template suitable for peer-reviewed journal papers,
    environmental assessments, MSc/PhD dissertations, and governmental technical reporting.
    """
    def __init__(self) -> None:
        self.logger = get_logger(__name__)

    def get_template_name(self) -> str:
        return "Default Scientific Publication Template"

    def render_cover_page(self, context: AnalysisReportContext, options: Optional[Any] = None) -> str:
        """
        Renders an authoritative, professionally typeset scientific publication cover page.
        Employs strong visual hierarchy with 30pt title, 16pt subtitle, balanced padding,
        and clean typography blocks without analysis tables.
        """
        org_name = getattr(options, 'organization_name', None) or "Remote Sensing Studio"
        proj_title = getattr(options, 'project_title', None) or "Earth Observation & Spectral Analysis"
        author_name = getattr(options, 'author_name', None) or "Research Intelligence Division"

        return f"""
        <div style="padding: 40px 20px; text-align: center; font-family: 'Inter', 'Segoe UI', 'Roboto', 'Helvetica', sans-serif;">
            <h3 style="color: #B8C6D8; font-size: 14pt; font-weight: 700; letter-spacing: 3px; text-transform: uppercase; margin-bottom: 10px;">
                {org_name}
            </h3>
            <div style="height: 4px; width: 100px; background-color: #2563EB; margin: 0 auto 50px auto;"></div>
            
            <h1 style="color: #FFFFFF; font-size: 30pt; font-weight: 800; margin-bottom: 16px; line-height: 1.25; text-transform: uppercase; letter-spacing: 0.5px;">
                SCIENTIFIC ANALYSIS REPORT
            </h1>
            
            <p style="color: #2563EB; font-size: 16pt; font-weight: 600; margin-top: 0; margin-bottom: 50px;">
                Quantitative Remote Sensing &amp; Bio-Geophysical Surface Evaluation
            </p>
            
            <div style="margin: 35px auto 60px auto; padding: 28px 36px; border-left: 5px solid #2563EB; background-color: #12243B; text-align: left; max-width: 92%; border-top: 1px solid #334155; border-right: 1px solid #334155; border-bottom: 1px solid #334155; border-radius: 4px;">
                <h2 style="color: #FFFFFF; font-size: 19pt; font-weight: 700; margin-top: 0; margin-bottom: 8px; border: none; padding: 0;">
                    {context.formula_name}
                </h2>
                <p style="font-family: monospace; font-size: 12.5pt; color: #FFFFFF; font-weight: 600; margin-top: 0; margin-bottom: 24px;">
                    Mathematical Formulation: {context.formula_expression}
                </p>
                
                <div style="font-size: 12pt; line-height: 1.85; color: #D7E3F4;">
                    <p style="margin: 6px 0; color: #F8FAFC;"><b style="color: #FFFFFF;">Workspace Domain:</b> {proj_title}</p>
                    <p style="margin: 6px 0; color: #F8FAFC;"><b style="color: #FFFFFF;">Dataset Archive:</b> {context.dataset}</p>
                    <p style="margin: 6px 0; color: #F8FAFC;"><b style="color: #FFFFFF;">Satellite Platform &amp; Sensor:</b> {context.satellite} (via {context.provider})</p>
                    <p style="margin: 6px 0; color: #F8FAFC;"><b style="color: #FFFFFF;">Processing Timestamp:</b> {context.processing_timestamp}</p>
                    <p style="margin: 6px 0; color: #F8FAFC;"><b style="color: #FFFFFF;">Lead Organization &amp; Laboratory:</b> {org_name}</p>
                </div>
            </div>
            
            <div style="margin-top: 70px;">
                <p style="font-size: 11.5pt; font-weight: 700; color: #FFFFFF; margin-bottom: 6px;">
                    Prepared by: {author_name}
                </p>
                <p style="font-size: 10pt; color: #B8C6D8; margin-top: 0;">
                    Universal Scientific PDF Report Engine &bull; Automated Publication Provenance Architecture
                </p>
            </div>
        </div>
        """

    def get_header_text(self, context: AnalysisReportContext, options: Optional[Any] = None) -> Tuple[str, str]:
        """Return running Header strings."""
        left = getattr(options, 'organization_name', None) or "Remote Sensing Studio"
        right = f"Scientific Analysis Report: {context.formula_name}"
        return (left, right)

    def get_footer_text(self, context: AnalysisReportContext, page_num: int, total_pages: int, options: Optional[Any] = None) -> Tuple[str, str]:
        """Return running Footer strings with Page X of Y."""
        left = f"Automated Scientific Engine | {context.processing_timestamp}"
        right = f"Page {page_num} of {total_pages}"
        return (left, right)

    def assemble_document_html(
        self,
        context: AnalysisReportContext,
        sections_html: Dict[str, str],
        options: Optional[Any] = None
    ) -> str:
        """
        Assembles sections into a continuous, true-to-physical-size publication layout flow:
        1. Cover Page (Followed by forced page break to push summary to Page 2)
        2. Executive Summary (Page 2, spanning multiple paragraphs naturally)
        3. Analysis Details & Scientific Parameters
        4. Raster Statistics
        5. Classification Statistics
        6. Analysis Map (Starts on fresh page, map occupies upper body, spatial metadata below)
        7. Statistical Distribution Histogram & Scientific Interpretation
        8. Quality Assessment
        9. Processing Metadata
        10. References
        11. System Information
        """
        cover_page_html = self.render_cover_page(context, options)
        
        exec_summary = sections_html.get("exec_summary", "")
        details_table = sections_html.get("details", "")
        base_stats = sections_html.get("base_stats", "")
        class_stats = sections_html.get("class_stats", "")
        map_gallery = sections_html.get("map_gallery", "")
        map_metadata = sections_html.get("map_metadata", "")
        histogram = sections_html.get("histogram", "")
        qa_section = sections_html.get("quality_assessment", "")
        proc_metadata = sections_html.get("processing_metadata", "")
        references_section = sections_html.get("references", "")
        sys_info = sections_html.get("sys_info", "")
        
        return f"""
        <html>
        <head>
            <style>
                body, p, div, span, td, li, ul {{
                    font-family: 'Inter', 'Segoe UI', 'Roboto', 'Helvetica', 'Arial', sans-serif;
                    color: #2D3748;
                    line-height: 1.65;
                    font-size: 11.8pt;
                    margin: 0;
                    padding: 0;
                }}
                h1, h2, h3, h4, th, b, strong {{
                    color: #111827;
                    font-weight: 700;
                    page-break-after: avoid;
                    margin-top: 0;
                }}
                h2 {{
                    font-size: 19pt;
                    color: #111827;
                    border-bottom: 2px solid #2563EB;
                    padding-bottom: 6px;
                    margin-top: 28px;
                    margin-bottom: 14px;
                    page-break-after: avoid;
                }}
                h3 {{
                    font-size: 15.5pt;
                    color: #111827;
                    margin-top: 22px;
                    margin-bottom: 10px;
                    page-break-after: avoid;
                }}
                h4 {{
                    font-size: 13.5pt;
                    color: #111827;
                    margin-top: 16px;
                    margin-bottom: 8px;
                    page-break-after: avoid;
                }}
                p {{
                    font-size: 11.8pt;
                    line-height: 1.65;
                    margin-bottom: 14px;
                    color: #374151;
                }}
                table {{
                    font-size: 11pt;
                    width: 100%;
                    border-collapse: collapse;
                }}
                td, th {{
                    font-size: 11pt;
                    color: #374151;
                }}
                th {{
                    color: #111827;
                }}
                a {{
                    color: #2563EB;
                    text-decoration: none;
                }}
                figure, table, .avoid-break {{
                    page-break-inside: avoid;
                }}
                .page-break {{
                    page-break-before: always;
                }}
            </style>
        </head>
        <body>
            {cover_page_html}
            
            <div class="page-break"></div>
            
            <h2>1. Executive Summary</h2>
            {exec_summary}
            
            <h2>2. Analysis Details &amp; Scientific Parameters</h2>
            {details_table}
            
            <h2>3. Raster Statistics</h2>
            {base_stats}
            
            <h2>4. Classification Statistics</h2>
            {class_stats}
            
            <div class="page-break"></div>
            
            <h2>5. Analysis Map</h2>
            {map_gallery}
            {map_metadata}
            
            <h2>6. Statistical Distribution Histogram</h2>
            {histogram}
            
            <h2>7. Quality Assessment</h2>
            {qa_section}
            
            <h2>8. Processing Metadata</h2>
            {proc_metadata}
            
            <h2>9. References</h2>
            {references_section}
            
            <h2>10. Scientific Discussion, Conclusions &amp; Applications</h2>
            {sys_info}
        </body>
        </html>
        """


# -------------------------------------------------------------------------
# Future Template Extensibility Skeletons
# -------------------------------------------------------------------------

class MscThesisTemplate(DefaultTemplate):
    """Template specialized for MSc Thesis chapter attachments."""
    def get_template_name(self) -> str:
        return "MSc Thesis Chapter Template"


class PhdThesisTemplate(DefaultTemplate):
    """Template specialized for PhD Dissertations and extensive appendices."""
    def get_template_name(self) -> str:
        return "PhD Dissertation Comprehensive Template"


class JournalPaperTemplate(DefaultTemplate):
    """Template formatted for peer-reviewed journal manuscript standards."""
    def get_template_name(self) -> str:
        return "Peer-Reviewed Journal Paper Template"


class OrganizationTemplate(DefaultTemplate):
    """Template supporting corporate branding and governmental reporting standards."""
    def get_template_name(self) -> str:
        return "Organization / Governmental Technical Report Template"


class TemplateEngine:
    """
    Factory and registry for report templates.
    Enables zero-redesign addition of specialized academic and professional formatting styles.
    """
    def __init__(self) -> None:
        self.logger = get_logger(__name__)
        self._templates: Dict[str, ReportTemplate] = {
            "default": DefaultTemplate(),
            "msc_thesis": MscThesisTemplate(),
            "phd_thesis": PhdThesisTemplate(),
            "journal_paper": JournalPaperTemplate(),
            "organization": OrganizationTemplate()
        }

    def register_template(self, key: str, template: ReportTemplate) -> None:
        """Register a new template at runtime."""
        self._templates[key.lower()] = template
        self.logger.info(f"Registered new ReportTemplate: {key} ({template.get_template_name()})")

    def get_template(self, key: str = "default") -> ReportTemplate:
        """Retrieve a registered template by key, defaulting to DefaultTemplate."""
        temp = self._templates.get(key.lower())
        if not temp:
            self.logger.warning(f"Template key '{key}' not found. Defaulting to DefaultTemplate.")
            return self._templates["default"]
        return temp
