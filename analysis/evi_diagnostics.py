import logging

class EVIDiagnostics:
    """
    Dedicated diagnostic module for EVI.
    Provides detailed logging of the computation parameters and optionally
    runs expensive Earth Engine checks if EVI_DEBUG is enabled.
    """
    
    @staticmethod
    def log_pre_computation(satellite_id: str, expression: str, scaling: dict, safety_def: dict):
        logger = logging.getLogger("RemoteSensingStudio")
        logger.info("=== EVI DIAGNOSTICS: PRE-COMPUTATION ===")
        logger.info(f"Satellite: {satellite_id}")
        logger.info(f"Expression: {expression}")
        logger.info(f"Scaling parameters: {scaling}")
        logger.info(f"Safety definition: {safety_def}")
        logger.info("========================================")
