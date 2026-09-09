import json
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("RemoteSensingStudio")

class SymbologyManager:
    """
    Extends the Preset Manager into a full Symbology Template system.
    Serializes and deserializes user visualization states to local JSON files.
    """
    def __init__(self, templates_dir: str):
        self.templates_dir = templates_dir
        if not os.path.exists(self.templates_dir):
            os.makedirs(self.templates_dir)

    def save_template(self, name: str, symbology_data: Dict[str, Any]):
        """
        Saves a Symbology Template.
        Symbology Template should include: Renderer Type, Classification Method, Palette, Display Range, Threshold, Transparency, Labels, Legend Settings.
        """
        file_path = os.path.join(self.templates_dir, f"{name.replace(' ', '_')}.json")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(symbology_data, f, indent=4)
        logger.info(f"Saved Symbology Template: {name}")

    def load_template(self, name: str) -> Optional[Dict[str, Any]]:
        """Loads a Symbology Template by name."""
        file_path = os.path.join(self.templates_dir, f"{name.replace(' ', '_')}.json")
        if not os.path.exists(file_path):
            return None
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load Symbology Template {name}: {e}")
            return None

    def save_session_state(self, session_data: Dict[str, Any]):
        """Saves the current visualization state for persistence between sessions."""
        self.save_template("_last_session", session_data)

    def load_session_state(self) -> Optional[Dict[str, Any]]:
        """Restores the visualization state from the last session."""
        return self.load_template("_last_session")
