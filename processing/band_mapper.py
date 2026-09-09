"""
Band Mapper Module.
Centralizes mapping between logical band names and provider-specific bands.
"""
from typing import Dict, Optional

class BandMapper:
    """Resolves abstract band names (RED, NIR) to satellite-specific bands."""
    
    _MAPPING: Dict[str, Dict[str, str]] = {
        'Sentinel-2': {
            'BLUE': 'B2',
            'GREEN': 'B3',
            'RED': 'B4',
            'NIR': 'B8',
            'SWIR1': 'B11',
            'SWIR2': 'B12'
        },
        'Landsat-8': {
            'BLUE': 'SR_B2',
            'GREEN': 'SR_B3',
            'RED': 'SR_B4',
            'NIR': 'SR_B5',
            'SWIR1': 'SR_B6',
            'SWIR2': 'SR_B7'
        },
        'Landsat-9': {
            'BLUE': 'SR_B2',
            'GREEN': 'SR_B3',
            'RED': 'SR_B4',
            'NIR': 'SR_B5',
            'SWIR1': 'SR_B6',
            'SWIR2': 'SR_B7'
        }
    }
    
    @classmethod
    def get_band(cls, satellite: str, logical_band: str) -> Optional[str]:
        """Get the specific band name for a given satellite and logical band."""
        sat_map = cls._MAPPING.get(satellite)
        if not sat_map:
            return None
        return sat_map.get(logical_band.upper())
        
    @classmethod
    def get_mapping(cls, satellite: str) -> Dict[str, str]:
        """Get all band mappings for a given satellite."""
        return cls._MAPPING.get(satellite, {})
