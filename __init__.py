"""
Initialization file for the Remote Sensing Studio Plugin.
"""
import sys
import os

# Vendorized dependencies: ensure the ext_libs directory is in the Python path
# so that google-auth-oauthlib and requests can be imported without manual pip install.
ext_libs_path = os.path.join(os.path.dirname(__file__), 'ext_libs')
if ext_libs_path not in sys.path:
    sys.path.insert(0, ext_libs_path)

def classFactory(iface):
    """
    Load the plugin class.
    """
    from .remote_sensing_studio import RemoteSensingStudioPlugin
    return RemoteSensingStudioPlugin(iface)
