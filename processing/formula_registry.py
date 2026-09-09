"""
Formula Registry Module.
Registers mathematical expressions and dependencies for remote sensing indices.
"""
from typing import Dict, Any, List
from dataclasses import dataclass

@dataclass
class FormulaDef:
    name: str
    expression: str
    required_bands: List[str]

class FormulaRegistry:
    """Registry containing all supported analysis formulas."""
    
    _formulas: Dict[str, FormulaDef] = {}
    
    @classmethod
    def initialize(cls) -> None:
        """Register all default remote sensing formulas without executing them."""
        cls.register(FormulaDef("NDVI", "(NIR - RED) / (NIR + RED)", ["NIR", "RED"]))
        cls.register(FormulaDef("SAVI", "((NIR - RED) / (NIR + RED + L)) * (1 + L)", ["NIR", "RED"]))
        cls.register(FormulaDef("MSAVI", "(2 * NIR + 1 - sqrt((2 * NIR + 1)**2 - 8 * (NIR - RED))) / 2", ["NIR", "RED"]))
        cls.register(FormulaDef("EVI", "2.5 * ((NIR - RED) / (NIR + 6 * RED - 7.5 * BLUE + 1))", ["NIR", "RED", "BLUE"]))
        cls.register(FormulaDef("NDWI", "(GREEN - NIR) / (GREEN + NIR)", ["GREEN", "NIR"]))
        cls.register(FormulaDef("NDMI", "(NIR - SWIR1) / (NIR + SWIR1)", ["NIR", "SWIR1"]))
        cls.register(FormulaDef("NDBI", "(SWIR1 - NIR) / (SWIR1 + NIR)", ["SWIR1", "NIR"]))
        cls.register(FormulaDef("BSI", "((SWIR1 + RED) - (NIR + BLUE)) / ((SWIR1 + RED) + (NIR + BLUE))", ["SWIR1", "RED", "NIR", "BLUE"]))
        cls.register(FormulaDef("AVI", "(NIR * (1 - RED) * (NIR - RED))**(1/3)", ["NIR", "RED"]))

    @classmethod
    def register(cls, formula: FormulaDef) -> None:
        """Add a new formula to the registry."""
        cls._formulas[formula.name.upper()] = formula
        
    @classmethod
    def get_formula(cls, name: str) -> FormulaDef:
        """Retrieve a formula by name."""
        return cls._formulas.get(name.upper())

# Auto-initialize on import
FormulaRegistry.initialize()
