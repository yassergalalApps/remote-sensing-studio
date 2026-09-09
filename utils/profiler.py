import time
from typing import List, Tuple, Optional
from PyQt6.QtCore import QObject, pyqtSignal

class PerformanceProfiler(QObject):
    """
    Measures the execution time of major workflow steps and generates a formatted report.
    Singleton pattern to allow cross-module tracking.
    """
    
    _instance = None
    
    @classmethod
    def get_instance(cls) -> 'PerformanceProfiler':
        if cls._instance is None:
            cls._instance = PerformanceProfiler()
        return cls._instance
        
    def __init__(self):
        super().__init__()
        self.steps: List[Tuple[str, float]] = []
        self.current_step_name: Optional[str] = None
        self.current_step_start: Optional[float] = None
        self.total_start: Optional[float] = None
        
    def start_workflow(self):
        """Starts a new profiling session."""
        self.steps = []
        self.current_step_name = None
        self.current_step_start = None
        self.total_start = time.time()
        
    def step(self, name: str):
        """Ends the previous step (if any) and starts a new one."""
        now = time.time()
        if self.current_step_name is not None and self.current_step_start is not None:
            duration = now - self.current_step_start
            self.steps.append((self.current_step_name, duration))
            
        self.current_step_name = name
        self.current_step_start = now
        
    def finish_step(self):
        """Ends the current step without starting a new one."""
        if self.current_step_name is not None and self.current_step_start is not None:
            now = time.time()
            duration = now - self.current_step_start
            self.steps.append((self.current_step_name, duration))
            self.current_step_name = None
            self.current_step_start = None

    def get_report(self) -> str:
        """Generates the formatted performance report."""
        self.finish_step() # Ensure the last step is recorded
        
        total_time = 0.0
        if self.total_start is not None:
            total_time = time.time() - self.total_start
            
        report = []
        report.append("\n========== Performance Report ==========\n")
        
        for name, duration in self.steps:
            duration_ms = duration * 1000
            # Format: Name .................... xxxx ms
            name_padded = (name + " ").ljust(35, ".")
            report.append(f"{name_padded} {duration_ms:.0f} ms")
            
        total_ms = total_time * 1000
        report.append("\n" + "TOTAL ".ljust(35, ".") + f" {total_ms:.0f} ms")
        report.append("\n========================================\n")
        
        return "\n".join(report)
        
    def log_report(self):
        """Logs the report to QGIS Message Log or standard logger."""
        report_str = self.get_report()
        
        # Always print to Python console for visibility
        print(report_str)
        
        try:
            from qgis.core import QgsMessageLog, Qgis
            QgsMessageLog.logMessage(report_str, 'RemoteSensingStudio', Qgis.MessageLevel.Info)
        except ImportError:
            pass
