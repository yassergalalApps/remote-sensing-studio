import os
from pathlib import Path
import logging

def write_evi_diagnostic(message: str):
    """
    1. Only use standard python logging in production.
    2. Never allow logging failure to interrupt EVI computation.
    """
    try:
        logger = logging.getLogger("RemoteSensingStudio")
        logger.debug(message)
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
