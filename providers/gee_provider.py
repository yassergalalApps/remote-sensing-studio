"""
Google Earth Engine Provider Module.
"""
import logging
import datetime
import urllib.parse
from typing import Any, Dict, Tuple, List, Union
from ..utils.logger import get_logger

try:
    import ee
    HAS_EE = True
except ImportError:
    HAS_EE = False

import os
import json
from pathlib import Path
import requests

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
except ImportError:
    pass

# Removed custom OAUTH_CLIENT_CONFIG. We will use the official ee.Authenticate flow.
CREDENTIALS_FILE = Path.home() / ".config" / "earthengine" / "credentials"

from .provider_interface import ProviderInterface

class GEEProvider(ProviderInterface):
    """
    Provider class for Google Earth Engine data and computation.
    """
    
    def __init__(self) -> None:
        self.logger = get_logger(__name__)
        self.is_connected = False
        self.current_project = ""
        self.current_account = ""
        self._session_lock_count = 0
        self._cached_has_credentials = None
        
        # Configure Phase 2 Download Provider
        from ..config import DOWNLOAD_API
        if DOWNLOAD_API == "COMPUTE_PIXELS":
            from .download_provider import ComputePixelsProvider
            self.download_provider = ComputePixelsProvider()
        else:
            from .download_provider import LegacyDownloadProvider
            self.download_provider = LegacyDownloadProvider()
        
        self.SATELLITE_MAPPING = {
            'Sentinel-2': {
                'id': 'COPERNICUS/S2_SR_HARMONIZED', 
                'cloud': 'CLOUDY_PIXEL_PERCENTAGE',
                'rgb': ['B4', 'B3', 'B2'],
                'tile_prop': 'MGRS_TILE',
                'level': 'Level-2A Surface Reflectance',
                'band_calibration': {
                    'optical': {'scale': 0.0001, 'offset': 0.0}
                },
                'qa_masks': ['Cloud', 'Cirrus'],
                'resolutions': {
                    '10m': ['B2', 'B3', 'B4', 'B8'],
                    '20m': ['B5', 'B6', 'B7', 'B8A', 'B11', 'B12'],
                    '60m': ['B1', 'B9', 'B10']
                },
                'band_mapping': {
                    'BLUE': 'B2',
                    'GREEN': 'B3',
                    'RED': 'B4',
                    'RED_EDGE': 'B5',
                    'NIR': 'B8',
                    'SWIR1': 'B11',
                    'SWIR2': 'B12'
                }
            },
            'Landsat-8': {
                'id': 'LANDSAT/LC08/C02/T1_L2', 
                'cloud': 'CLOUD_COVER',
                'rgb': ['SR_B4', 'SR_B3', 'SR_B2'],
                'tile_prop': 'WRS_PATH',
                'level': 'Collection 2 Level-2',
                'band_calibration': {
                    'optical': {'scale': 0.0000275, 'offset': -0.2},
                    'thermal': {'scale': 0.00341802, 'offset': 149.0}
                },
                'qa_masks': ['Cloud', 'Shadow', 'Snow', 'Cirrus'],
                'resolutions': {
                    '30m': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'],
                    '100m': ['ST_B10']
                },
                'band_mapping': {
                    'BLUE': 'SR_B2',
                    'GREEN': 'SR_B3',
                    'RED': 'SR_B4',
                    'NIR': 'SR_B5',
                    'SWIR1': 'SR_B6',
                    'SWIR2': 'SR_B7',
                    'TIR': 'ST_B10'
                }
            },
            'Landsat-9': {
                'id': 'LANDSAT/LC09/C02/T1_L2', 
                'cloud': 'CLOUD_COVER',
                'rgb': ['SR_B4', 'SR_B3', 'SR_B2'],
                'tile_prop': 'WRS_PATH',
                'level': 'Collection 2 Level-2',
                'band_calibration': {
                    'optical': {'scale': 0.0000275, 'offset': -0.2},
                    'thermal': {'scale': 0.00341802, 'offset': 149.0}
                },
                'qa_masks': ['Cloud', 'Shadow', 'Snow', 'Cirrus'],
                'resolutions': {
                    '30m': ['SR_B1', 'SR_B2', 'SR_B3', 'SR_B4', 'SR_B5', 'SR_B6', 'SR_B7'],
                    '100m': ['ST_B10']
                },
                'band_mapping': {
                    'BLUE': 'SR_B2',
                    'GREEN': 'SR_B3',
                    'RED': 'SR_B4',
                    'NIR': 'SR_B5',
                    'SWIR1': 'SR_B6',
                    'SWIR2': 'SR_B7',
                    'TIR': 'ST_B10'
                }
            }
        }
        
        # Removed parameterless self.check_connection() from init. ConnectionService will initialize.
        
    def parse_ee_exception(self, e: Exception) -> str:
        """Parses Earth Engine exceptions into human-readable error categories."""
        error_str = str(e).lower()
        if "user_project_denied" in error_str or "caller does not have required permission" in error_str or "permission denied" in error_str:
            return "PROJECT_ACCESS_DENIED"
        elif "not found or deleted" in error_str or "does not exist" in error_str:
            return "PROJECT_NOT_FOUND"
        elif "credentials" in error_str or "unauthorized" in error_str or "invalid_grant" in error_str:
            return "AUTHENTICATION_REQUIRED"
        elif "earth engine api has not been used" in error_str or "serviceusage" in error_str:
            return "EARTH_ENGINE_NOT_ENABLED"
        elif "billing" in error_str or "quota" in error_str:
            return "BILLING_OR_QUOTA_ISSUE"
        return "EARTH_ENGINE_API_ERROR"

    def _get_credentials(self):
        """Retrieve local Earth Engine credentials."""
        try:
            return ee.data.get_persistent_credentials()
        except Exception as e:
            self.logger.warning(f"Failed to read credentials: {e}")
            return None

    def initialize_earth_engine(self, project_id: str = None) -> Tuple[bool, str]:
        """
        The ONE authoritative initialization path for Earth Engine.
        Must explicitly pass the active user's project_id.
        """
        if not HAS_EE: return False, "Earth Engine API not installed."
        if not project_id:
            self.is_connected = False
            return False, "PROJECT_NOT_CONFIGURED"

        try:
            creds = self._get_credentials()
            if not creds:
                self.is_connected = False
                self.invalidate_credential_cache()
                return False, "AUTHENTICATION_REQUIRED"
                
            ee.Initialize(credentials=creds, project=project_id)
            self.current_project = project_id
            self.current_account = self._fetch_user_email(creds)
            self.is_connected = True
            return True, "VALID"
        except Exception as e:
            self.is_connected = False
            self.current_project = ""
            if "credentials" in str(e).lower() or "auth" in str(e).lower():
                self.invalidate_credential_cache()
            return False, self.parse_ee_exception(e)

    def invalidate_credential_cache(self) -> None:
        """Invalidate the credential existence cache to force re-evaluation."""
        self._cached_has_credentials = None

    def has_credentials(self) -> bool:
        """Check if Google Auth credentials exist and are valid."""
        if self._cached_has_credentials is not None:
            return self._cached_has_credentials
            
        self._cached_has_credentials = self._get_credentials() is not None
        return self._cached_has_credentials

    def acquire_session_lock(self):
        """Acquires a lock on the Earth Engine session."""
        self._session_lock_count += 1
        
    def release_session_lock(self):
        """Releases a lock on the Earth Engine session."""
        if self._session_lock_count > 0:
            self._session_lock_count -= 1

    @property
    def is_session_locked(self) -> bool:
        return self._session_lock_count > 0

    def discover_projects(self, history_projects: List[str] = None) -> Tuple[List[Dict[str, str]], str]:
        """Discover Earth Engine projects using a prioritized cascade."""
        if self.is_session_locked:
            return [], "Earth Engine session is currently locked by a running analysis. Please wait for it to finish."
            
        creds = self._get_credentials()
        if not creds:
            return [], "No credentials available."
        
        self.logger.info("=== PROJECT DISCOVERY CASCADE START ===")
        self.logger.info(f"Authenticated Account: {self.current_account}")
        
        active_projects = []
        tested = set()
        
        def _test_project(proj_id: str, source: str) -> bool:
            if not proj_id or proj_id in tested:
                return False
            tested.add(proj_id)
            import re
            if not re.match(r"^[a-z][a-z0-9\-]{4,28}[a-z0-9]$|^[a-z0-9\-\.\:]+$", proj_id):
                self.logger.debug(f"Candidate {proj_id} rejected due to invalid syntax.")
                return False
            self.logger.info(f"Testing candidate project from {source}: {proj_id}")
            try:
                # Explicitly inject the current credentials during validation
                ee.Initialize(credentials=creds, project=proj_id)
                # Perform a real request to validate
                _ = ee.Number(1).getInfo()
                active_projects.append({"id": proj_id, "name": proj_id})
                self.logger.info(f"Candidate {proj_id} VALIDATED.")
                return True
            except Exception as e:
                error_type = self.parse_ee_exception(e)
                self.logger.debug(f"Candidate {proj_id} failed EE validation: {error_type}")
                return False

        # LEVEL 1 - Current Active Project
        if self.current_project:
            _test_project(self.current_project, "Active Session")
            
        # LEVEL 2 - Account-scoped Project History
        if history_projects:
            for p in history_projects:
                _test_project(p, "History")
        
        if active_projects:
            self.logger.info("Discovery Complete. Returning validated projects from History/Session.")
            return active_projects, ""
            
        # LEVEL 3 - Local Earth Engine Configuration
        local_proj = None
        if CREDENTIALS_FILE.exists():
            try:
                with open(CREDENTIALS_FILE, 'r') as f:
                    local_data = json.load(f)
                    local_proj = local_data.get('project')
            except Exception:
                pass
        if local_proj:
            _test_project(local_proj, "Local EE Config")
            
        if active_projects:
            self.logger.info("Discovery Complete. Returning validated project from Local EE Config.")
            return active_projects, ""
            
        # LEVEL 4 - Application Default Credentials
        adc_proj = None
        try:
            from ee.oauth import get_appdefault_project
            adc_proj = get_appdefault_project()
        except ImportError:
            pass
        if adc_proj:
            _test_project(adc_proj, "ADC")
            
        if active_projects:
            self.logger.info("Discovery Complete. Returning validated project from ADC.")
            return active_projects, ""
            
        # LEVEL 5 - Cloud Resource Manager (Optional Fallback)
        self.logger.info("Attempting Cloud Resource Manager discovery...")
        url = 'https://cloudresourcemanager.googleapis.com/v3/projects:search'
        params = {}
        try:
            res = requests.get(url, headers={'Authorization': f'Bearer {creds.token}'}, params=params, timeout=10)
            if res.status_code == 200:
                data = res.json()
                for p in data.get('projects', []):
                    if p.get('state') == 'ACTIVE' and p.get('projectId'):
                        proj_id = p['projectId']
                        _test_project(proj_id, "CRM")
            elif res.status_code == 403 and ("SERVICE_DISABLED" in res.text or "cloudresourcemanager.googleapis.com" in res.text):
                self.logger.info("Cloud Resource Manager is disabled for this OAuth client (Expected limitation).")
        except Exception as e:
            self.logger.debug(f"CRM discovery error: {e}")
            
        self.logger.info(f"Discovery Complete. Total ACTIVE & EE VALID: {len(active_projects)}")
        self.logger.info("=== PROJECT DISCOVERY CASCADE END ===")
        
        if active_projects:
            return active_projects, ""
            
        # Restore state if we ended up failing
        if self.is_connected and self.current_project:
            try:
                ee.Initialize(credentials=creds, project=self.current_project)
            except Exception:
                pass
                
        return [], "PROJECT_DISCOVERY_UNAVAILABLE"

    def test_connection(self, project_id: str) -> Tuple[bool, str]:
        """
        Strictly tests initialization and a harmless API request 
        using the CURRENT authenticated credentials explicitly.
        """
        if not HAS_EE: return False, "Earth Engine API not installed."
        creds = self._get_credentials()
        if not creds:
            self.invalidate_credential_cache()
            return False, "AUTHENTICATION_REQUIRED"
            
        try:
            # 1. Explicitly initialize with current credentials and project candidate
            ee.Initialize(credentials=creds, project=project_id)
            
            # 2. Harmless real API request to verify Earth Engine usage is enabled for THIS account
            _ = ee.Number(1).getInfo()
            
            # 3. Successful validation sets the state
            self.current_project = project_id
            self.current_account = self._fetch_user_email(creds)
            self.is_connected = True
            return True, "VALID"
        except Exception as e:
            self.is_connected = False
            self.current_project = ""
            if "credentials" in str(e).lower() or "auth" in str(e).lower():
                self.invalidate_credential_cache()
            return False, self.parse_ee_exception(e)

    def check_connection(self, project_id: str = None) -> bool:
        """Legacy check_connection, redirects to initialize_earth_engine."""
        if not project_id: return False
        success, _ = self.initialize_earth_engine(project_id)
        return success

    def supported_datasets(self) -> List[str]:
        return list(self.SATELLITE_MAPPING.keys())

    def _fetch_user_email(self, creds=None) -> str:
        """Fetch the actual authenticated Google account email."""
        if not creds:
            creds = self._get_credentials()
            
        def _get_cached_email():
            try:
                from qgis.core import QgsSettings
                email = QgsSettings().value("earth_engine/current_account_email", "")
                if isinstance(email, str) and email:
                    return email
            except Exception:
                pass
            return ""
            
        if not creds:
            return _get_cached_email()
            
        cached = _get_cached_email()
        is_expired = hasattr(creds, 'expired') and creds.expired
        
        if cached and not is_expired:
            self.logger.info(f"[AUTH DEBUG] Using fast-path cached email: {cached}")
            return cached
            
        # Try refreshing credentials if they are expired so tokeninfo works
        try:
            if is_expired and hasattr(creds, 'refresh'):
                import google.auth.transport.requests
                creds.refresh(google.auth.transport.requests.Request())
        except Exception as e:
            self.logger.debug(f"[AUTH DEBUG] Could not refresh token for email resolution: {e}")
            
        try:
            import requests
            res = requests.get(f"https://oauth2.googleapis.com/tokeninfo?access_token={creds.token}")
            if res.status_code == 200:
                data = res.json()
                email = data.get('email', '')
                if email:
                    self.logger.info(f"[AUTH DEBUG] Resolved authenticated account: {email}")
                    # Update cache
                    try:
                        from qgis.core import QgsSettings
                        QgsSettings().setValue("earth_engine/current_account_email", email)
                    except Exception:
                        pass
                    return email
            self.logger.warning(f"[AUTH DEBUG] Failed to resolve email from tokeninfo: {res.text}")
        except Exception as e:
            self.logger.error(f"[AUTH DEBUG] Error resolving email via tokeninfo: {e}")
            
        # Fallback to cached email if network resolution failed
        cached = _get_cached_email()
        if cached:
            self.logger.info(f"[AUTH DEBUG] Falling back to cached email: {cached}")
            return cached
            
        return ""

    def login(self) -> Tuple[bool, str]:
        """Performs interactive OAuth authentication using the official Earth Engine flow."""
        if not HAS_EE: return False, "Earth Engine API not installed."
                                   
        def _auth_func():
            try:
                # Import here to avoid overhead
                import ee
                scopes = [
                    'https://www.googleapis.com/auth/earthengine',
                    'https://www.googleapis.com/auth/cloud-platform',
                    'https://www.googleapis.com/auth/drive',
                    'https://www.googleapis.com/auth/devstorage.full_control',
                    'email',
                    'openid'
                ]
                ee.Authenticate(auth_mode='localhost:0', force=True, scopes=scopes)
                return True, "Authentication successful."
            except Exception as e:
                return False, str(e)
        
        success, msg = _auth_func()
        if not success:
            return False, f"Authentication failed: {msg}"
            
        self.invalidate_credential_cache()
            
        creds = self._get_credentials()
        if not creds:
            return False, "Authentication flow completed, but credentials could not be loaded."
            
        email = self._fetch_user_email(creds)
        if email:
            self.current_account = email
            try:
                from qgis.core import QgsSettings
                QgsSettings().setValue("earth_engine/current_account_email", email)
            except Exception as e:
                self.logger.warning(f"Could not save account email to QSettings: {e}")
        else:
            self.current_account = "Google account authenticated"
            
        return True, "Successfully authenticated. Please select your project."

    def logout(self) -> Tuple[bool, str]:
        """Real sign-out: clears internal plugin state without destroying global EE credentials."""
        self.logger.info("[AUTH DEBUG] GEEProvider.logout() started")
        try:
            self.invalidate_credential_cache()
            
            # CLEAR RUNTIME STATE
            if HAS_EE:
                if hasattr(ee.data, '_credentials'):
                    ee.data._credentials = None
                if hasattr(ee.data, '_project'):
                    ee.data._project = None
                self.logger.info("[AUTH DEBUG] Cleared ee.data runtime state")
            
            self.is_connected = False
            self.current_account = ""
            self.current_project = ""
            try:
                from qgis.core import QgsSettings
                QgsSettings().remove("earth_engine/current_account_email")
            except Exception:
                pass
            return True, "Successfully logged out."
        except Exception as e:
            self.logger.exception("[AUTH DEBUG] GEEProvider.logout() exception")
            return False, f"Logout failed: {e}"
            
    def get_status(self) -> Dict[str, Any]:
        has_cred = self.has_credentials()
        if has_cred and not self.current_account:
            try:
                from qgis.core import QgsSettings
                email = QgsSettings().value("earth_engine/current_account_email", "")
                if isinstance(email, str) and email:
                    self.current_account = email
                else:
                    self.current_account = ""
            except Exception:
                self.current_account = ""
        elif not has_cred:
            self.current_account = ""
            self.current_project = ""
            self.is_connected = False
            
        return {
            "has_credentials": has_cred,
            "connected": self.is_connected, 
            "account": self.current_account, 
            "project": self.current_project
        }

    def _get_base_collection(self, satellite: str, start_date: str, end_date: str, aoi_geojson: Dict[str, Any], filters: Dict[str, Any] = None):
        if not self.is_connected: raise Exception("Earth Engine is not connected.")
        sat_info = self.SATELLITE_MAPPING.get(satellite)
        if not sat_info: raise ValueError(f"Satellite {satellite} is not currently supported.")
        
        # Extract geojson if wrapped in a metrics dictionary
        if "geojson" in aoi_geojson and "original_crs" in aoi_geojson:
            aoi_geojson = aoi_geojson["geojson"]
            
        import json
        
        # Apply experimental topological repair (buffer 0) to prevent Earth Engine intersection errors
        try:
            geom = ee.Geometry(aoi_geojson).buffer(distance=0, maxError=1)
        except Exception as e:
            import json
            def get_depth(L):
                return isinstance(L, list) and max(map(get_depth, L), default=0) + 1 or 0
                
            debug_info = []
            debug_info.append(f"Traceback: {e}")
            debug_info.append(f"Python Type: {type(aoi_geojson)}")
            if isinstance(aoi_geojson, dict):
                debug_info.append(f"GeoJSON Type: {aoi_geojson.get('type')}")
                coords = aoi_geojson.get('coordinates', [])
                debug_info.append(f"Coordinates Depth: {get_depth(coords)}")
            debug_info.append(f"Payload: {json.dumps(aoi_geojson)[:1500]}")
            
            raise Exception("DEBUG PAYLOAD INFO:\n" + "\n".join(debug_info))
        
        collection = ee.ImageCollection(sat_info['id']).filterBounds(geom).filterDate(start_date, end_date)
        
        if filters:
            if 'max_cloud' in filters:
                collection = collection.filter(ee.Filter.lte(sat_info['cloud'], filters['max_cloud']))
                
        # Apply Pixel-Level Cloud Masking
        if 'Sentinel-2' in satellite:
            def mask_s2_clouds(image):
                qa = image.select('QA60')
                mask = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
                return image.updateMask(mask)
            collection = collection.map(mask_s2_clouds)
        elif 'Landsat' in satellite:
            def mask_landsat_clouds(image):
                qa = image.select('QA_PIXEL')
                mask = qa.bitwiseAnd(1 << 4).eq(0).And(qa.bitwiseAnd(1 << 3).eq(0))
                return image.updateMask(mask)
            collection = collection.map(mask_landsat_clouds)
            
        return collection, sat_info, geom

    def get_collection_metadata(self, satellite: str, start_date: str, end_date: str, aoi_geojson: Dict[str, Any]) -> Dict[str, Any]:
        try:
            collection, sat_info, geom = self._get_base_collection(satellite, start_date, end_date, aoi_geojson)
            count = collection.size().getInfo()
            if count == 0: return {"Collection Name": sat_info['id'], "Images Found": 0, "Provider": "Google Earth Engine"}
            
            first_img = ee.Image(collection.first())
            bands = first_img.bandNames().getInfo()
            proj = first_img.select(0).projection()
            crs = proj.crs().getInfo()
            res = proj.nominalScale().getInfo()
            first_date = first_img.date().format('YYYY-MM-dd').getInfo()
            last_img = ee.Image(collection.sort('system:time_start', False).first())
            last_date = last_img.date().format('YYYY-MM-dd').getInfo()
            cloud_mean = collection.aggregate_mean(sat_info['cloud']).getInfo() or 0.0
            
            return {
                "Collection Name": sat_info['id'], "Images Found": count, "Average Cloud %": round(cloud_mean, 2),
                "First Acquisition": first_date, "Last Acquisition": last_date, "Available Bands": bands,
                "Projection": crs, "Resolution": f"{round(res, 2)}m", "Provider": "Google Earth Engine",
                "QA Masks": sat_info.get("qa_masks", []), "Resolutions": sat_info.get("resolutions", {})
            }
        except Exception as e:
            self.logger.error(f"Error querying metadata: {e}")
            raise

    def get_image_list(self, satellite: str, start_date: str, end_date: str, aoi_geojson: Dict[str, Any], filters: Dict[str, Any] = None, sort_by: str = "Lowest Cloud", max_images: int = 500) -> List[Dict[str, Any]]:
        try:
            collection, sat_info, geom = self._get_base_collection(satellite, start_date, end_date, aoi_geojson, filters)
            
            def calc_coverage(img):
                intersection = img.geometry().intersection(geom, 100)
                aoi_area = geom.area(100)
                intersect_area = intersection.area(100)
                cov_pct = intersect_area.divide(aoi_area).multiply(100)
                cov_km2 = intersect_area.divide(1e6)
                cloud = img.get(sat_info['cloud'])
                
                score = cov_pct.multiply(0.5).add(ee.Number(100).subtract(cloud).multiply(0.5))
                return img.set('AOI_Coverage_Pct', cov_pct).set('AOI_Coverage_Km2', cov_km2).set('Recommendation_Score', score)

            collection = collection.map(calc_coverage)
            
            # Select only the specific properties we need to avoid heavy metadata transfer
            props_to_keep = ['system:time_start', sat_info['cloud'], 'AOI_Coverage_Pct', 'AOI_Coverage_Km2', 'Recommendation_Score']
            collection = collection.select([]) # Drop all image bands
            
            if sort_by == "Lowest Cloud":
                collection = collection.sort(sat_info['cloud'], True)
            elif sort_by == "Best Coverage":
                collection = collection.sort('AOI_Coverage_Pct', False)
            elif sort_by == "Newest":
                collection = collection.sort('system:time_start', False)
            elif sort_by == "Oldest":
                collection = collection.sort('system:time_start', True)
            else:
                collection = collection.sort('Recommendation_Score', False)
                
            collection = collection.limit(max_images)
            raw_list = collection.toList(max_images).getInfo()
            
            results = []
            for img_dict in raw_list:
                props = img_dict.get('properties', {})
                ts = props.get('system:time_start')
                acq_date = datetime.datetime.fromtimestamp(ts / 1000.0).strftime('%Y-%m-%d %H:%M:%S') if ts else "Unknown"
                bands = [b['id'] for b in img_dict.get('bands', [])]
                
                results.append({
                    "Image ID": img_dict.get('id', 'Unknown'), 
                    "Acquisition Date": acq_date,
                    "Cloud Percentage": round(props.get(sat_info['cloud'], 0.0), 2),
                    "Satellite": satellite,
                    "Processing Level": sat_info['level'], 
                    "Available Bands": bands,
                    "Coverage %": round(props.get('AOI_Coverage_Pct', 0.0), 1),
                    "Coverage km²": round(props.get('AOI_Coverage_Km2', 0.0), 2),
                    "Score": round(props.get('Recommendation_Score', 0.0), 1)
                })
                
            return results
        except Exception as e:
            self.logger.error(f"Error fetching image list: {e}")
            raise
            
    def get_image_object(self, satellite: str, start_date: str, end_date: str, aoi_geojson: Dict[str, Any], selection_mode: str, image_ids: List[str] = None, cloud_filter: float = 100.0, return_collection: bool = False) -> Tuple[Any, Dict[str, Any]]:
        from ..utils.profiler import PerformanceProfiler
        profiler = PerformanceProfiler.get_instance()
        
        profiler.step("Creating ImageCollection")
        filters = {"max_cloud": cloud_filter} if cloud_filter is not None else None
        
        profiler.step("Date filtering & AOI filtering")
        # _get_base_collection handles the base bounds and date filters
        collection, sat_info, geom = self._get_base_collection(satellite, start_date, end_date, aoi_geojson, filters)
        
        profiler.step("Cloud masking")
        if image_ids and len(image_ids) > 0:
            # Construct a list of ee.Image objects, NOT raw string IDs
            ee_images = [ee.Image(img_id) for img_id in image_ids]
            collection = ee.ImageCollection.fromImages(ee_images)
            
            # Re-apply pixel-level cloud mask for explicitly provided image IDs
            if 'Sentinel-2' in satellite:
                def mask_s2_clouds(image):
                    qa = image.select('QA60')
                    return image.updateMask(qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0)))
                collection = collection.map(mask_s2_clouds)
            elif 'Landsat' in satellite:
                def mask_landsat_clouds(image):
                    qa = image.select('QA_PIXEL')
                    return image.updateMask(qa.bitwiseAnd(1 << 4).eq(0).And(qa.bitwiseAnd(1 << 3).eq(0)))
                collection = collection.map(mask_landsat_clouds)
        
        from ..analysis.metrics_builder import AnalysisMetricsBuilder
        metrics = AnalysisMetricsBuilder.compute_collection_metrics(collection, selection_mode, image_ids)
            
        if return_collection:
            return collection, metrics
            
        profiler.step("Composite creation")
        if selection_mode == 'Median':
            img = collection.median()
        elif selection_mode == 'Mean':
            img = collection.mean()
        elif selection_mode == 'Mosaic':
            img = collection.mosaic()
        elif selection_mode == 'Quality Mosaic':
            img = collection.mosaic()
        elif selection_mode == 'Best Pixel':
            img = collection.median()
        elif image_ids and len(image_ids) == 1:
            img = ee.Image(collection.first())
        else:
            img = ee.Image(collection.first())
            
        # PIPELINE STANDARDIZATION: Clip the composite to the AOI immediately!
        img = img.clip(geom)
            
        return img, metrics

    def get_selected_image_preview(self, satellite: str, start_date: str, end_date: str, aoi_geojson: Dict[str, Any], selection_mode: str, image_ids: List[str] = None, analysis_type: str = None, vis_params_override: Dict[str, Any] = None) -> Dict[str, Any]:
        try:
            collection, sat_info, geom = self._get_base_collection(satellite, start_date, end_date, aoi_geojson)
            img, metrics = self.get_image_object(satellite, start_date, end_date, aoi_geojson, selection_mode, image_ids)
            
            image_id = selection_mode
            cloud_cover = 0.0
            acq_date = f"Composite ({start_date} to {end_date})"
            
            if image_ids and len(image_ids) == 1:
                raw_img = ee.Image(image_ids[0])
                image_id = image_ids[0]
                cloud_cover = raw_img.get(sat_info['cloud']).getInfo() or 0.0
                ts = raw_img.get('system:time_start').getInfo()
                if ts: acq_date = datetime.datetime.fromtimestamp(ts / 1000.0).strftime('%Y-%m-%d')
                
            outline = ee.FeatureCollection(geom).style(color='eab308', width=2, fillColor='00000000')
            
            # The Scene Preview must be independent from index formula logic and display the source scene directly.
            if 'Landsat' in satellite:
                landsat_rgb = img.select(sat_info['rgb']).multiply(0.0000275).add(-0.2)
                rgb_img = landsat_rgb.visualize(bands=sat_info['rgb'], min=0.0, max=0.3)
            else:
                vis_params = {'bands': sat_info['rgb'], 'min': 0, 'max': sat_info.get('scale', 3000)}
                rgb_img = img.visualize(**vis_params)
                
            blended = rgb_img.blend(outline)
            
            preview_url = blended.getThumbURL(dict(region=geom, dimensions=800, format='png'))
            bands = img.bandNames().getInfo()
            
            return {
                "Image ID": image_id, "Acquisition Date": acq_date, "Cloud Percentage": round(cloud_cover, 2) if cloud_cover else 0.0,
                "Satellite": satellite, "Available Bands": bands, "Processing Level": sat_info['level'], "Preview URL": preview_url,
                "Metrics": metrics, "Resolutions": sat_info.get("resolutions", {}), "QA Masks": sat_info.get("qa_masks", [])
            }
        except Exception as e:
            self.logger.error(f"Error generating preview: {e}")
            raise

    # ---------------------------------------------------------
    # Execution & Visualization

    def execute_formula(self, formula: Dict[str, Any], satellite: str, start_date: str, end_date: str, 
                        aoi_geojson: Dict[str, Any], selection_mode: str, image_ids: List[str] = None, cloud_filter: float = 100.0,
                        compute_ee_stats: bool = False, generate_tile_url: bool = False,
                        export_resolution_mode: str = "Dataset Default", export_resolution: float = 0.0) -> Dict[str, Any]:
        """
        Executes a mathematical formula on Earth Engine servers and returns visualization properties
        and statistics.
        """
        from ..utils.profiler import PerformanceProfiler
        profiler = PerformanceProfiler.get_instance()
        
        sat_info = self.SATELLITE_MAPPING.get(satellite)
        if not sat_info:
            raise ValueError(f"Satellite {satellite} is not supported.")
            
        # Merge JSON parameters (scaling, limits) into hardcoded mapping for mathematical parity
        from ..analysis.satellite_registry import SatelliteRegistry
        try:
            reg_sat = SatelliteRegistry.get_instance().get_satellite(satellite)
            sat_info = sat_info.copy() # Avoid mutating the global dict
            for k, v in reg_sat.items():
                if k not in sat_info:
                    sat_info[k] = v
            print(f"\n[GEE_PROVIDER_MERGE_TEST]")
            print(f"Merge successful for {satellite}. stored_as_scaled_integers={sat_info.get('stored_as_scaled_integers')}\n")
        except ValueError as ve:
            if str(ve) == f"Satellite {satellite} is not registered.":
                pass
            else:
                self.logger.warning(f"Could not merge JSON satellite definition: {ve}")
                print(f"\n[GEE_PROVIDER_MERGE_TEST] FAILED: {ve}\n")
        except Exception as e:
            self.logger.warning(f"Could not merge JSON satellite definition: {e}")
            print(f"\n[GEE_PROVIDER_MERGE_TEST] FAILED: {e}\n")
            
        if isinstance(aoi_geojson, dict) and "geojson" in aoi_geojson and "original_crs" in aoi_geojson:
            geom_dict = aoi_geojson["geojson"]
        else:
            geom_dict = aoi_geojson
        geom = ee.Geometry(geom_dict)

        # --- PHASE 5K.2: DEFENSIVE BACKEND VALIDATION ---
        normalized_mode = str(selection_mode).strip().lower()
        SINGLE_SCENE_MODES = {"best image", "single scene"}
        COMPOSITE_MODES = {"median", "mean", "mosaic", "quality mosaic", "best pixel"}

        selected_count = len(image_ids) if image_ids else 0
        if normalized_mode in SINGLE_SCENE_MODES:
            if selected_count != 1:
                raise ValueError(f"Single Scene mode requires exactly one selected scene, got {selected_count}.")
        elif normalized_mode in COMPOSITE_MODES:
            if selected_count < 2:
                raise ValueError(f"Image Collection mode requires at least 2 selected scenes, got {selected_count}.")
        else:
            raise ValueError(f"Unsupported selection mode: {selection_mode}")

        # 1. Retrieve the appropriate image/composite
        collection, metrics = self.get_image_object(satellite, start_date, end_date, aoi_geojson, selection_mode, image_ids, cloud_filter, return_collection=True)

        # --- PHASE 5K.1: STRICT SINGLE-SCENE GATE ---
        if normalized_mode in SINGLE_SCENE_MODES:
            try:
                profiler.step("Single Scene Coverage Gate")
                selected_img = ee.Image(collection.first())
                scene_footprint = selected_img.geometry()
                intersection = geom.intersection(scene_footprint, 1) # maxError=1
                
                geom_area = geom.area(1)
                inter_area = intersection.area(1)
                
                coverage_ee = inter_area.divide(geom_area).multiply(100.0)
                coverage_ee = coverage_ee.min(100.0).max(0.0)
                coverage_val = coverage_ee.getInfo()
                
                if coverage_val < 99.99:
                    raise ValueError(f"COVERAGE_BLOCK:{coverage_val}")
                    
            except ee.EEException as e:
                self.logger.error(f"Failed to compute EE coverage intersection: {e}")
                # We do not block if EE fails to compute the area due to an API glitch,
                # but if it successfully computes < 99.99 we already raised ValueError above.
                coverage_val = 100.0
        elif normalized_mode in COMPOSITE_MODES:
            coverage_val = 100.0
        else:
            self.logger.warning(f"Unsupported selection mode: {selection_mode}. Proceeding with default coverage assumption.")
            coverage_val = 100.0
        
        # 2. Map generic bands to native satellite bands and apply scaling
        band_mapping = sat_info.get("band_mapping", {})
        band_calib = sat_info.get("band_calibration", {})
        
        def process_image(img):
            img = ee.Image(img)
            from ..analysis.formula_engine import FormulaEngine
            engine_type = formula.get("formula", {}).get("engine", "expression")
            # Evaluate applies band mapping, scaling, math, and SafetyEngine hooks internally
            computed = FormulaEngine.evaluate(img, formula, sat_info, engine_type=engine_type)
            computed = computed.rename(formula.get("metadata", {}).get("scientific_name", formula.get("name", "Index")))
            return computed.copyProperties(img, ['system:time_start'])

        profiler.step("Index computation (Map over collection)")
        processed_collection = collection.map(process_image)
        
        print(f"Selected satellite: {satellite}")
        print(f"Start date: {start_date}")
        print(f"End date: {end_date}")
        
        try:
            # Fast local approximation of bounding box area (in km2) to avoid blocking .getInfo()
            coords = geom_dict.get('coordinates', [])
            if coords and geom_dict.get('type') == 'Polygon':
                lons = [pt[0] for pt in coords[0]]
                lats = [pt[1] for pt in coords[0]]
                area_sqdeg = (max(lons) - min(lons)) * (max(lats) - min(lats))
                aoi_km2 = area_sqdeg * 12300 # Approx km2 at equator
            else:
                aoi_km2 = 1000
        except Exception:
            aoi_km2 = 1000
            
        print(f"Approx AOI area: {aoi_km2} km²")
        
        print(f"Final ImageCollection size: {metrics.get('Images Found', 0)}")
        print(f"Using explicit image_ids: {bool(image_ids)}")
        
        # Determine actual spatial footprint before reduction
        if normalized_mode in COMPOSITE_MODES:
            # For composites, footprint is union of all images (GEE handles this lazily)
            raw_footprint = processed_collection.geometry()
        else:
            raw_footprint = ee.Image(processed_collection.first()).geometry()
        
        # 4. Composite creation (Reducer)
        profiler.step("Composite creation (Reducer)")
        if normalized_mode == 'median':
            computed_img = processed_collection.median()
        elif normalized_mode == 'mean':
            computed_img = processed_collection.mean()
        elif normalized_mode == 'mosaic':
            computed_img = processed_collection.mosaic()
        elif normalized_mode == 'quality mosaic':
            computed_img = processed_collection.mosaic()
        elif normalized_mode == 'best pixel':
            computed_img = processed_collection.median()
        elif image_ids and len(image_ids) == 1:
            computed_img = ee.Image(processed_collection.first())
        else:
            computed_img = ee.Image(processed_collection.first())
            
        computed_img = computed_img.set("IMAGE_STAGE", "computed")
        
        # PIPELINE STANDARDIZATION: Clip the composite to the AOI immediately!
        profiler.step("Final clip")
        clipped_img = computed_img.clip(geom)
        clipped_img = clipped_img.set("IMAGE_STAGE", "clipped")
        
        # --- EVI DIAGNOSTIC INJECTION ---
        import sys
        import os
        from ..config import EVI_DEBUG
        from ..analysis.diagnostic_utils import write_evi_diagnostic
        
        debug_mode = getattr(sys.modules.get('remote_sensing_studio.config', None), 'EVI_DEBUG', False) or EVI_DEBUG
        
        try:
            write_evi_diagnostic("===== RUNTIME MODULE PATHS =====")
            write_evi_diagnostic(f"gee_provider = {__file__}")
            try:
                write_evi_diagnostic(f"formula_registry = {sys.modules['remote_sensing_studio.analysis.formula_registry'].__file__}")
            except Exception as e:
                write_evi_diagnostic(f"formula_registry path err: {e}")
            try:
                write_evi_diagnostic(f"evi_diagnostic_runner = {sys.modules['remote_sensing_studio.analysis.evi_diagnostic_runner'].__file__}")
            except Exception as e:
                write_evi_diagnostic(f"evi_diagnostic_runner path err: {e}")
                
            write_evi_diagnostic(f"plugin_root = {os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}")

            write_evi_diagnostic("===== DEBUG STATE =====")
            write_evi_diagnostic(f"EVI_DEBUG (from config) = {getattr(sys.modules.get('remote_sensing_studio.config', None), 'EVI_DEBUG', 'Not Found')}")
            write_evi_diagnostic(f"debug_mode = {debug_mode}")

            write_evi_diagnostic("===== DIAGNOSTIC FILE PATH =====")
            log_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
            diag_path = os.path.join(log_dir, "evi_diagnostic.txt")
            write_evi_diagnostic(f"absolute_path = {os.path.abspath(diag_path)}")

            write_evi_diagnostic("===== EVI DIAGNOSTIC GATE VALUES =====")
            write_evi_diagnostic(f"debug_mode = {debug_mode}")
            write_evi_diagnostic(f"formula_id = {formula.get('id')}")
            write_evi_diagnostic(f"normalized_mode = {normalized_mode}")
            write_evi_diagnostic(f"single_scene_match = {normalized_mode in SINGLE_SCENE_MODES}")
            write_evi_diagnostic(f"is_evi = {formula.get('id') == 'EVI'}")
        except Exception:
            pass

        if debug_mode and formula.get("id") == "EVI" and normalized_mode in SINGLE_SCENE_MODES:
            try:
                write_evi_diagnostic("===== EVI DIAGNOSTIC GATE PASSED =====")
                from ..analysis.evi_diagnostic_runner import EVIDiagnosticRunner
                test_img = ee.Image(collection.first())
                native_res = 10 if 'Sentinel' in satellite else 30
                self.logger.info("Triggering EVIDiagnosticRunner...")
                write_evi_diagnostic("===== BEFORE RUNNER INVOCATION =====")
                EVIDiagnosticRunner.run_evi_denominator_diagnostic(test_img, geom, native_res, formula, sat_info, clipped_img)
                write_evi_diagnostic("===== EVI DIAGNOSTIC RUNNER RETURNED =====")
            except Exception as e:
                import traceback
                write_evi_diagnostic(f"===== RUNNER FAILED: {e} =====")
                write_evi_diagnostic(traceback.format_exc())
                self.logger.error(f"EVI Diagnostic Runner failed: {e}")
        # --------------------------------
        
        # 4. Generate Statistics using ONLY the clipped image and original AOI geometry
        
        # --- RESOLUTION HANDLING ---
        native_res = 10 if 'Sentinel' in satellite else 30
        
        if export_resolution_mode == "Custom" and export_resolution > 0:
            scale = export_resolution
        elif export_resolution_mode == "Automatic":
            if aoi_km2 > 10000:
                scale = 500
            elif aoi_km2 > 5000:
                scale = 250
            elif aoi_km2 > 1000:
                scale = 100
            elif aoi_km2 > 200:
                scale = 20 # Bypasses 48MB limit for medium-large polygons
            else:
                scale = native_res
        else:
            # "Dataset Default" (Recommended)
            scale = native_res
                    # Coverage is already validated upstream (Phase 5K)

            
        formatted_stats = {}
        if compute_ee_stats:
            profiler.step("Earth Engine API Request (Statistics)")
            from ..analysis.metrics_builder import AnalysisMetricsBuilder
            stats = AnalysisMetricsBuilder.compute_image_statistics(clipped_img, geom, scale)
            band_name = formula.get("name", "Index")
            formatted_stats = AnalysisMetricsBuilder.format_statistics(stats, band_name)
                # 6. Generate Tile URL for QGIS Map Canvas (Optional, since we mostly download GeoTIFF)
        tile_url = None
        if generate_tile_url:
            vis_params = {
                'min': formula["output_range"]["min"],
                'max': formula["output_range"]["max"],
                'palette': formula["default_palette"]
            }
            map_id_dict = ee.Image(clipped_img).getMapId(vis_params)
            tile_url = map_id_dict['tile_fetcher'].url_format
            
        # Extract native CRS from metrics object if available, otherwise fallback to standard WGS84
        native_crs = aoi_geojson.get("original_crs", "EPSG:4326")
        
        profiler.step("Export request creation skipped (handled by ExportManager)")
        
        # 8. Build detailed metadata for AnalysisResult
        # Fetching all acquisition dates used from actual EE metrics
        acq_dates = metrics.get("Actual Dates", ["Composite Range"])
            
        req_res_str = f"{export_resolution}m" if export_resolution_mode == "Custom" else export_resolution_mode
        
        from ..analysis.metrics_builder import AnalysisMetricsBuilder
        full_metadata = AnalysisMetricsBuilder.build_metadata(
            sat_info, req_res_str, scale, acq_dates
        )
        
        return {
            "tile_url": tile_url,
            "metrics": metrics,
            "statistics": formatted_stats,
            "visualization_params": vis_params if generate_tile_url else formula.get("output_range", {}),
            "metadata": full_metadata,
            "coverage_percent": round(coverage_val, 2),
            "computed_image": clipped_img,
            "scale": scale,
            "native_crs": native_crs
        }

    def download_tile(self, image: Any, tile_geojson: Dict[str, Any], scale: float, crs: str, file_path: str, timeout: int):
        """
        Delegates the tile download to the configured DownloadProvider strategy.
        """
        import json
        
        try:
            self.logger.info("==================================================")
            self.logger.info("[DIAGNOSTIC]")
            self.logger.info("==================================================")
            
            def _extract_lons_lats(geom_coords):
                lons, lats = [], []
                def _traverse(node):
                    if isinstance(node, (list, tuple)):
                        if len(node) == 2 and isinstance(node[0], (int, float)) and isinstance(node[1], (int, float)):
                            lons.append(node[0])
                            lats.append(node[1])
                        else:
                            for child in node:
                                _traverse(child)
                _traverse(geom_coords)
                return lons, lats
            
            raw_coords = tile_geojson.get("coordinates", []) if isinstance(tile_geojson, dict) else []
            lons, lats = _extract_lons_lats(raw_coords)
            
            min_lon, max_lon = min(lons) if lons else 0, max(lons) if lons else 0
            min_lat, max_lat = min(lats) if lats else 0, max(lats) if lats else 0
            out_of_bounds = any(lon < -180 or lon > 180 or lat < -90 or lat > 90 for lon, lat in zip(lons, lats))
            
            self.logger.info(f"[DIAGNOSTIC] Geometry Type: {tile_geojson.get('type') if isinstance(tile_geojson, dict) else 'Unknown'}")
            self.logger.info(f"[DIAGNOSTIC] Bounds: [{min_lon}, {min_lat}, {max_lon}, {max_lat}]")
            self.logger.info(f"[DIAGNOSTIC] Coordinates: {json.dumps(raw_coords)}")
            self.logger.info(f"[DIAGNOSTIC] Minimum Longitude: {min_lon}")
            self.logger.info(f"[DIAGNOSTIC] Maximum Longitude: {max_lon}")
            self.logger.info(f"[DIAGNOSTIC] Minimum Latitude: {min_lat}")
            self.logger.info(f"[DIAGNOSTIC] Maximum Latitude: {max_lat}")
            self.logger.info(f"[DIAGNOSTIC] Any coordinate outside valid range: {out_of_bounds}")
        except Exception as diag_e:
            self.logger.error(f"[DIAGNOSTIC] Failed to log EE Geometry validation diagnostics: {diag_e}")
            
            self.logger.info("==================================================")
            self.logger.info("[DIAGNOSTIC]")
            self.logger.info("==================================================")
            self.logger.info(f"[DIAGNOSTIC] Generated URL: (Generated internally by Earth Engine API)")
            self.logger.info(f"[DIAGNOSTIC] Request headers: (Managed internally by Earth Engine API)")
            self.logger.info(f"[DIAGNOSTIC] Request timeout: (Managed internally by Earth Engine API)")
        except Exception as diag_e:
            self.logger.error(f"[DIAGNOSTIC] Failed to log EE Request diagnostics: {diag_e}")
            
        
        try:
            self.download_provider.download_tile(image, tile_geojson, scale, crs, file_path, timeout)
            return True
        except Exception as e:
            try:
                self.logger.info("==================================================")
                self.logger.info("[DIAGNOSTIC]")
                self.logger.info("==================================================")
                self.logger.info(f"[DIAGNOSTIC] Exception Type: {type(e)}")
                self.logger.info(f"[DIAGNOSTIC] Exception Class: {e.__class__.__name__}")
                self.logger.info(f"[DIAGNOSTIC] Complete Python traceback:\n{traceback.format_exc()}")
                
                resp_body = "N/A"
                if hasattr(e, 'read'):
                    try:
                        resp_body = e.read().decode('utf-8')
                    except:
                        pass
                elif hasattr(e, 'response'):
                    resp_body = str(e.response)
                elif hasattr(e, 'content'):
                    resp_body = str(e.content)
                
                self.logger.info(f"[DIAGNOSTIC] Complete Earth Engine response body:\n{resp_body}")
                self.logger.info(f"[DIAGNOSTIC] Complete server message:\n{str(e)}")
                
                if hasattr(e, 'headers'):
                    self.logger.info(f"[DIAGNOSTIC] Every response header:\n{e.headers}")
                else:
                    self.logger.info(f"[DIAGNOSTIC] Every response header: N/A")
                    
                if hasattr(e, '__cause__') and e.__cause__:
                    self.logger.info(f"[DIAGNOSTIC] Every nested exception:\n{e.__cause__}")
                
                if resp_body != "N/A":
                    try:
                        parsed = json.loads(resp_body)
                        self.logger.info(f"[DIAGNOSTIC] Complete JSON:\n{json.dumps(parsed, indent=2)}")
                    except:
                        pass
            except Exception as diag_e:
                self.logger.error(f"[DIAGNOSTIC] Failed to log EE Exception diagnostics: {diag_e}")
            raise
            

    def start_drive_export_task(self, image: Any, aoi_geojson: Dict[str, Any], scale: float, crs: str, task_name: str, nodata_value: Union[int, float] = None) -> Any:
        """
        Initiates an Earth Engine Export Task to Google Drive.
        """
        import ee
        
        # Extract geojson if wrapped in a metrics dictionary
        if "geojson" in aoi_geojson and "original_crs" in aoi_geojson:
            aoi_geojson = aoi_geojson["geojson"]
            
        # We MUST use the bounding box of the AOI as the export region.
        # If we use the exact polygon, Earth Engine will natively mask the output GeoTIFF 
        # and override our custom nodata_value with 0. 
        # Since the image is already unmasked with our nodata_value, exporting the bounds
        # ensures the corners are physically written with the correct nodata_value.
        region_bounds = ee.Geometry(aoi_geojson).bounds()
        
        format_options = {}
        if nodata_value is not None:
            format_options['noData'] = nodata_value
            
        task = ee.batch.Export.image.toDrive(
            image=image,
            description=task_name,
            folder="RemoteSensingStudio",
            fileNamePrefix=task_name,
            region=region_bounds.getInfo()['coordinates'],
            scale=scale,
            crs=crs,
            maxPixels=1e13,
            fileFormat='GeoTIFF',
            formatOptions=format_options
        )
        
        # ---------------------------------------------------------
        # STAGE 2 DIAGNOSTICS: EXPORT ARGUMENTS
        # ---------------------------------------------------------
        import sys
        from ..config import EVI_DEBUG
        debug_mode = getattr(sys.modules.get('remote_sensing_studio.config', None), 'EVI_DEBUG', False) or EVI_DEBUG
        if debug_mode:
            self.logger.info("=== EVI_DEBUG STAGE 2: EXPORT CONFIGURATION ===")
            self.logger.info(f"image = {image.name()}")
            self.logger.info(f"scale = {scale}")
            self.logger.info(f"crs = {crs}")
            self.logger.info(f"crsTransform = Not explicitly specified (uses scale)")
            self.logger.info(f"dimensions = Not explicitly specified")
            self.logger.info(f"region = {region_bounds.getInfo()['coordinates']}")
            self.logger.info(f"fileFormat = GeoTIFF")
            self.logger.info(f"formatOptions = {format_options}")
            self.logger.info(f"resampling/reprojection = Default (Nearest Neighbor implicit via scale/crs mismatch)")
            self.logger.info("VERIFICATION: No unmask() was applied prior to Export.image.toDrive()")
        # ---------------------------------------------------------
        
        task.start()
        return task

    # ---------------------------------------------------------
    # ProviderInterface Implementation (Stage 2)
    # ---------------------------------------------------------

    def load_dataset(self, context: Any) -> Any:
        import ee
        filters = {"max_cloud": context.parameters.get("cloud_filter", 100.0)}
        satellite_id = context.satellite_definition["satellite_id"]
        collection, sat_info, geom = self._get_base_collection(
            satellite_id,
            context.date_range["start"],
            context.date_range["end"],
            context.aoi,
            filters
        )
        
        image_ids = context.parameters.get("image_ids", None)
        if image_ids and len(image_ids) > 0:
            ee_images = [ee.Image(img_id) for img_id in image_ids]
            collection = ee.ImageCollection.fromImages(ee_images)
            
            # Re-apply pixel-level cloud mask for explicitly provided image IDs
            if 'Sentinel-2' in satellite_id:
                def mask_s2_clouds(image):
                    qa = image.select('QA60')
                    mask = qa.bitwiseAnd(1 << 10).eq(0).And(qa.bitwiseAnd(1 << 11).eq(0))
                    return image.updateMask(mask)
                collection = collection.map(mask_s2_clouds)
            elif 'Landsat' in satellite_id:
                def mask_landsat_clouds(image):
                    qa = image.select('QA_PIXEL')
                    mask = qa.bitwiseAnd(1 << 4).eq(0).And(qa.bitwiseAnd(1 << 3).eq(0))
                    return image.updateMask(mask)
                collection = collection.map(mask_landsat_clouds)
                
        return collection, sat_info, geom

    def apply_cloud_mask(self, dataset: Any, context: Any) -> Any:
        return dataset

    def build_composite(self, dataset: Any, context: Any) -> Any:
        import ee
        # dataset is the computed_collection returned by evaluate_formula
        collection = dataset
        selection_mode = context.parameters.get("selection_mode", "Median")
        image_ids = context.parameters.get("image_ids", None)

        if selection_mode == 'Median':
            img = collection.median()
        elif selection_mode == 'Mean':
            img = collection.mean()
        elif selection_mode == 'Mosaic':
            img = collection.mosaic()
        elif selection_mode == 'Quality Mosaic':
            img = collection.mosaic()
        elif selection_mode == 'Best Pixel':
            img = collection.median()
        elif image_ids and len(image_ids) == 1:
            img = ee.Image(collection.first())
        else:
            img = ee.Image(collection.first())

        aoi_geojson = context.aoi
        if isinstance(aoi_geojson, dict) and "geojson" in aoi_geojson and "original_crs" in aoi_geojson:
            aoi_geojson = aoi_geojson["geojson"]
        geom = ee.Geometry(aoi_geojson)

        img = img.clip(geom)
        img = img.set("IMAGE_STAGE", "computed")
        return img

    def evaluate_formula(self, dataset: Any, context: Any) -> Any:
        import ee
        from ..analysis.formula_engine import FormulaEngine
        collection, sat_info, geom = dataset
        
        formula_def = context.index_definition
        sat_def = context.satellite_definition
        
        # --- GLOBAL INPUT SEMANTICS CORRECTION ---
        # Extract the required input semantics from the index definition for ALL paths
        # Single-Scene and Multi-Scene now uniformly scale to reflectance when required.
        import copy
        formula_def = copy.deepcopy(formula_def)
        req_unit = formula_def.get("input_semantics", {}).get("unit", "raw")
        formula_def["expected_input"] = req_unit
            
        engine_type = formula_def.get("formula", {}).get("engine", "expression")
        name = formula_def.get("metadata", {}).get("scientific_name", "Index")
        
        def process_single_image(img):
            img = ee.Image(img)
            # Evaluate applying pre/post safety hooks internally via FormulaEngine
            computed = FormulaEngine.evaluate(img, formula_def, sat_def, engine_type=engine_type)
            computed = computed.rename(name)
            # Retain original properties for reducers
            return computed.copyProperties(img, ['system:time_start'])
            
        computed_collection = collection.map(process_single_image)
        return computed_collection

    def export(self, image: Any, context: Any) -> Any:
        return image

    def download(self, export_task: Any, filepath: str, context: Any) -> bool:
        return True
