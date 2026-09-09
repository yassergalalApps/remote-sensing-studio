from dataclasses import dataclass
from ..models.analysis_result import AnalysisResult

@dataclass(frozen=True)
class ResultsViewModel:
    layer_name: str
    crs: str
    resolution: str
    
    @classmethod
    def from_result(cls, result: AnalysisResult) -> 'ResultsViewModel':
        return cls(
            layer_name=result.output_layer_name,
            crs=result.crs,
            resolution=result.resolution
        )

@dataclass(frozen=True)
class QAViewModel:
    cloud_percent: str
    coverage_percent: str
    
    @classmethod
    def from_result(cls, result: AnalysisResult) -> 'QAViewModel':
        return cls(
            cloud_percent=f"{result.cloud_threshold}%", # Using threshold as placeholder for actual cloud
            coverage_percent=f"{result.coverage_percent}%"
        )

@dataclass(frozen=True)
class ReportViewModel:
    html_content: str
    
    @classmethod
    def from_result(cls, result: AnalysisResult) -> 'ReportViewModel':
        # Will integrate with ReportBuilder
        return cls(html_content="<p>Skeleton Report</p>")
