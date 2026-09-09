"""
Reporting package for Remote Sensing Studio.
Provides modular renderers, template engines, and publication-quality export engines.
"""
from .pdf_engine import ScientificPdfEngine, ReportExtensionOptions
from .templates import TemplateEngine, ReportTemplate, DefaultTemplate
from .renderers import HistogramExporter, StatisticsRenderer, MetadataRenderer

__all__ = [
    "ScientificPdfEngine",
    "ReportExtensionOptions",
    "TemplateEngine",
    "ReportTemplate",
    "DefaultTemplate",
    "HistogramExporter",
    "StatisticsRenderer",
    "MetadataRenderer",
]
