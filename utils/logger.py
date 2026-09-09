"""
Logging Utility Module.
"""
import logging
try:
    from qgis.core import QgsMessageLog, Qgis
except ImportError:
    QgsMessageLog = None
    Qgis = None

class QgsLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            if QgsMessageLog and Qgis:
                level = getattr(Qgis, "Info", getattr(Qgis.MessageLevel, "Info", 0))
                if record.levelno >= logging.ERROR:
                    level = getattr(Qgis, "Critical", getattr(Qgis.MessageLevel, "Critical", 2))
                elif record.levelno >= logging.WARNING:
                    level = getattr(Qgis, "Warning", getattr(Qgis.MessageLevel, "Warning", 1))
                QgsMessageLog.logMessage(msg, "RemoteSensingStudio", level)
            else:
                print(msg)
        except Exception:
            pass

def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger instance that outputs to both console and QgsMessageLog.
    
    Args:
        name (str): The name for the logger, typically __name__.
        
    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger(name)
    if not any(isinstance(h, (logging.StreamHandler, QgsLogHandler)) for h in logger.handlers):
        logger.setLevel(logging.DEBUG)
        
        # Create console handler
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        
        # Create QGIS message log handler
        qgs_handler = QgsLogHandler()
        qgs_handler.setLevel(logging.DEBUG)
        
        # Create formatter and add it to the handlers
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        qgs_handler.setFormatter(formatter)
        
        logger.addHandler(ch)
        logger.addHandler(qgs_handler)
        
    return logger
