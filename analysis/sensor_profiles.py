from typing import Dict, Optional, List

class SensorBandRegistry:
    """
    Provides a source of truth for standard satellite sensor spectral band mappings,
    intended specifically as recommendations for the Local Raster workflow.
    """
    
    _PROFILES = {
        "Auto Detect / Unknown": {},
        "Sentinel-2 MSI": {
            "RED": "Band 4",
            "NIR": "Band 8",
            "BLUE": "Band 2",
            "GREEN": "Band 3",
            "RED_EDGE": "Band 5",
            "SWIR1": "Band 11",
            "SWIR2": "Band 12"
        },
        "Landsat 8/9 OLI": {
            "RED": "Band 4",
            "NIR": "Band 5",
            "BLUE": "Band 2",
            "GREEN": "Band 3",
            "SWIR1": "Band 6",
            "SWIR2": "Band 7"
        },
        "Landsat 7 ETM+": {
            "BLUE": "Band 1",
            "GREEN": "Band 2",
            "RED": "Band 3",
            "NIR": "Band 4",
            "SWIR1": "Band 5",
            "SWIR2": "Band 7"
        }
    }
    
    @classmethod
    def get_available_sensors(cls) -> List[str]:
        return list(cls._PROFILES.keys())
        
    @classmethod
    def get_band_recommendation(cls, sensor_id: str, requirement: str) -> Optional[str]:
        """
        Returns the expected band name (e.g. 'Band 8') for a given abstract requirement ('NIR')
        based on the sensor profile.
        """
        if sensor_id not in cls._PROFILES:
            return None
        return cls._PROFILES[sensor_id].get(requirement.upper(), None)
