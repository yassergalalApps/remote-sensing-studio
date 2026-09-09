from dataclasses import dataclass
from ..models.analysis_result import AnalysisResult

@dataclass(frozen=True)
class DashboardViewModel:
    analysis_name: str
    dataset: str
    provider: str
    execution_time: str
    scenes_used: str
    status_color: str
    
    @classmethod
    def from_result(cls, result: AnalysisResult) -> 'DashboardViewModel':
        status_col = "#DC2626" if result.errors else "#10B981"
        return cls(
            analysis_name=result.formula_name,
            dataset=result.dataset,
            provider=result.provider,
            execution_time=f"{result.execution_time_sec} s",
            scenes_used=str(result.number_of_scenes),
            status_color=status_col
        )
