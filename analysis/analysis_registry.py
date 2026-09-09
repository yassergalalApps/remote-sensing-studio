"""
Analysis Registry Module.
"""
import logging
from typing import Dict, Any
from ..utils.logger import get_logger

class AnalysisRegistry:
    """
    Registry for discovering and managing remote sensing analysis modules.
    """
    _registry: Dict[str, Any] = {}
    _discovered: bool = False
    
    @classmethod
    def register(cls, name: str, module_class: Any) -> None:
        """Register a new analysis module."""
        cls._registry[name.upper()] = module_class
        logger = get_logger(__name__)
        logger.debug(f"Registered analysis module: {name.upper()}")
        
    @classmethod
    def get_module(cls, name: str) -> Any:
        """Retrieve a registered module by name."""
        return cls._registry.get(name.upper())
        
    @classmethod
    def discover_modules(cls) -> None:
        """Dynamically auto-discover and load all modules in the modules package."""
        if cls._discovered:
            return
            
        import importlib
        import pkgutil
        from . import modules
        
        logger = get_logger(__name__)
        logger.debug("Discovering analysis modules...")
        
        package = modules
        prefix = package.__name__ + "."
        for _, modname, _ in pkgutil.iter_modules(package.__path__, prefix):
            try:
                module = importlib.import_module(modname)
                if hasattr(module, 'register'):
                    module.register(cls)
            except Exception as e:
                logger.error(f"Failed to load module {modname}: {e}")
                
        cls._discovered = True
