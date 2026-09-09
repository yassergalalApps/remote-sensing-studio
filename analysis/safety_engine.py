import ee

class SafetyEngine:
    """
    Generic safety engine for evaluating JSON-driven safety rules on Earth Engine images.
    Strictly decoupled from index-specific logic.
    """

    @classmethod
    def apply_pre_formula_safety(cls, img: ee.Image, expr_args: dict, safety_def: dict) -> ee.Image:
        """
        Applies mathematical safety masks before the formula executes.
        Updates expr_args in place if derived terms are calculated.
        
        Args:
            img: The base ee.Image.
            expr_args: Dictionary of bands and constants.
            safety_def: The "safety" dictionary from the index JSON.
        Returns:
            The masked ee.Image.
        """
        
        # 1. Base Denominators
        for denom in safety_def.get("base_denominators", []):
            denom_img = img.expression(denom["expression"], expr_args)
            eps = denom.get("epsilon", 1e-6)
            denom_mask = denom_img.abs().gte(eps)
            img = img.updateMask(denom_mask)
            
            # Apply mask to all input images so the expression respects it mathematically
            for k, v in list(expr_args.items()):
                if isinstance(v, ee.Image):
                    expr_args[k] = v.updateMask(denom_mask)
                    
        # 2. Input Validity
        opt_min = safety_def.get("input_validity", {}).get("optical_min", 0.0)
        if opt_min is not None:
            for generic_band, b_img in expr_args.items():
                if generic_band != "TIR" and isinstance(b_img, ee.Image):
                    img = img.updateMask(b_img.gte(opt_min))
                    
        # 3. Derived Terms
        for dt in safety_def.get("derived_terms", []):
            dt_img = img.expression(dt["expression"], expr_args)
            expr_args[dt["id"]] = dt_img
            
        # 4. Complex Denominators
        for cdenom in safety_def.get("complex_denominators", []):
            cdenom_img = img.expression(cdenom["expression"], expr_args)
            eps = cdenom.get("epsilon", 1e-6)
            img = img.updateMask(cdenom_img.abs().gte(eps))
            
        # 5. SQRT Domains
        for sq in safety_def.get("sqrt_domains", []):
            sq_img = img.expression(sq["expression"], expr_args)
            min_v = sq.get("min_valid", 0.0)
            img = img.updateMask(sq_img.gte(min_v))
            
        return img

    @classmethod
    def apply_post_formula_safety(cls, computed_img: ee.Image, safety_def: dict) -> ee.Image:
        """
        Applies mathematical safety masks after the formula executes.
        
        Args:
            computed_img: The resulting ee.Image from FormulaEngine.
            safety_def: The "safety" dictionary from the index JSON.
        Returns:
            The masked ee.Image.
        """
        out_val = safety_def.get("output_validity", {})
        
        import logging
        import sys
        from ..config import EVI_DEBUG
        logger = logging.getLogger(__name__)
        debug_mode = getattr(sys.modules.get('remote_sensing_studio.config', None), 'EVI_DEBUG', False) or EVI_DEBUG
        
        # ---------------------------------------------------------
        EVI_RUNTIME_FIX_VERSION = "FINITE_MASK_FIX_2026_08_18"
        # ---------------------------------------------------------
        
        if debug_mode:
            logger.info("=== SAFETY ENGINE DIAGNOSTICS ===")
            logger.info(f"EVI_RUNTIME_FIX_VERSION = {EVI_RUNTIME_FIX_VERSION}")
            logger.info(f"output_validity.enabled: {out_val.get('enabled', False)}")
            logger.info(f"output_validity.min: {out_val.get('min')}")
            logger.info(f"output_validity.max: {out_val.get('max')}")
            
        if out_val.get("enabled", False):
            if "min" not in out_val or "max" not in out_val:
                raise ValueError(
                    f"SafetyEngine: output_validity is enabled but min/max are missing. "
                    f"Got: {out_val}. Refusing to proceed with silent defaults."
                )
            v_min = out_val["min"]
            v_max = out_val["max"]
            if not isinstance(v_min, (int, float)) or not isinstance(v_max, (int, float)):
                raise ValueError(
                    f"SafetyEngine: output_validity min/max must be numeric. "
                    f"Got min={v_min!r}, max={v_max!r}"
                )
                
            # Create the valid bounds mask
            bounds_mask = computed_img.gte(v_min).And(computed_img.lte(v_max))
            
            # Explicitly create a finite mask to handle NaN/Inf (Investigation #3)
            # In Earth Engine, comparisons with NaN might evaluate to false, masking them, 
            # but to be scientifically robust and mathematically explicit, we mask non-finite values.
            # EE doesn't have isNaN() natively, but we can do: img.eq(img) which is false for NaN,
            # and img.lt(1e38).And(img.gt(-1e38)) which masks Inf.
            finite_mask = computed_img.eq(computed_img).And(computed_img.lt(1e38)).And(computed_img.gt(-1e38))
            
            final_mask = bounds_mask.And(finite_mask)
            computed_img = computed_img.updateMask(final_mask)
            
            # ---------------------------------------------------------
            # STAGE 1: EVI_DEBUG DIAGNOSTICS (Immediately after SafetyEngine)
            # ---------------------------------------------------------
            if debug_mode:
                logger.info("=== EVI_DEBUG STAGE 1: AFTER SAFETY ENGINE ===")
                # Note: At this stage we don't have the AOI bounds explicitly passed to SafetyEngine
                # So we rely on a global reduction if this is a small test, or skip intensive global reducers.
                # However, the user specifically requested diagnostic counts.
                # We will return the image as is, the counts will be logged accurately in Stage 2 with the geometry.
                logger.info("Mask successfully applied to the image object.")
                logger.info("Detailed pixel counts will be executed at Stage 2 with the exact export AOI geometry.")
            # ---------------------------------------------------------
            
            if debug_mode:
                logger.info("apply_post_formula_safety() was actually called.")
                logger.info("The returned image is the masked image.")
            
        return computed_img
