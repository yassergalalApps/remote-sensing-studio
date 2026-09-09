"""
Formula Registry for Remote Sensing Indices.
Acts as a completely decoupled repository of analysis algorithms.
"""

from typing import Dict, Any

class FormulaRegistry:
    """
    Central catalogue for remote sensing indices and formulas.
    """
    
    @classmethod
    def get_formula(cls, index_name: str) -> Dict[str, Any]:
        """Returns the full formula definition exclusively from the JSON registry."""
        from .index_registry import IndexRegistry
        
        try:
            registry = IndexRegistry.get_instance()
            index_def = registry.get_index(index_name)
        except ValueError:
            raise ValueError(f"Index '{index_name}' could not be loaded because its JSON definition was not found in the indices directory.")
            
        if "formula" not in index_def:
            raise ValueError(f"Index '{index_name}' exists but does not contain a valid 'formula' block in its JSON definition.")
            
        availability = index_def.get("availability", {"supported": True})
        if not availability.get("supported", True):
            reason = availability.get("reason", "Formula/unit incompatibility.")
            raise ValueError(f"Index '{index_name}' is currently unsupported in this pipeline: {reason}")
            
        metadata = index_def.get("metadata", {})
        formula_data = index_def.get("formula", {})
        
        return {
            "name": metadata.get("display_name", index_name),
            "id": index_def.get("id", index_name),
            "description": metadata.get("description", ""),
            "expression": formula_data.get("expression", ""),
            "required_bands": formula_data.get("required_bands", []),
            "parameters": formula_data.get("parameters", {}),
            "output_range": {
                "min": formula_data.get("expected_output_range", [-1.0])[0], 
                "max": formula_data.get("expected_output_range", [1.0])[-1]
            },
            "references": [formula_data.get("reference", "")],
            "availability": availability,
            "safety": index_def.get("safety", {}),
            "input_semantics": index_def.get("input_semantics", {}),
            "formula": formula_data
        }

    @classmethod
    def get_available_indices(cls) -> list:
        """Returns a list of supported index acronyms from JSON files."""
        from .index_registry import IndexRegistry
        registry = IndexRegistry.get_instance()
        supported_indices = []
        for idx in registry.get_all_indices():
            if "formula" in idx:
                availability = idx.get("availability", {"supported": True})
                if availability.get("supported", True):
                    supported_indices.append(idx.get("id"))
        return supported_indices

