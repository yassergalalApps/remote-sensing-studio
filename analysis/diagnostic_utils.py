import os
from pathlib import Path
import logging

def write_evi_diagnostic(message: str):
    """
    1. always attempt direct file writing,
    2. optionally also call logger.info(),
    3. never allow logging failure to interrupt EVI computation.
    """
    try:
        log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(exist_ok=True)
        diag_path = log_dir / "evi_diagnostic.txt"
        with open(diag_path, "a", encoding="utf-8") as f:
            f.write(message + "\n")
    except Exception:
        pass
        
    try:
        logger = logging.getLogger("RemoteSensingStudio")
        logger.info(message)
    except Exception:
        pass

def normalize_scalar(val, default=0):
    if val is None:
        return default
    if isinstance(val, dict):
        if not val:
            return default
        val = list(val.values())[0]
    if isinstance(val, (list, tuple)):
        if not val:
            return default
        val = val[0]
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default
