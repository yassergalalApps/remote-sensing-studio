from typing import Any

def run_savi_diagnostics(base_img: Any, computed_img: Any, context: Any, scale: float, geom: Any, collection_metrics: dict, sat_info: dict):
    """
    Temporary diagnostic logger for SAVI scientific verification.
    """
    if context.index_definition["id"] != "SAVI":
        return
        
    try:
        import ee
        
        print("\n========== SAVI MATHEMATICAL VERIFICATION START ==========")
        print("="*70)
        
        formula = context.index_definition.get("formula", {})
        expression = formula.get("expression", "")
        params = formula.get("parameters", {})
        band_mapping = context.satellite_definition.get("band_mapping", {})
        
        red_band = band_mapping.get('RED')
        nir_band = band_mapping.get('NIR')
        savi_name = context.index_definition["metadata"]["scientific_name"]
        
        print("\n[Sampling Pixel Data]")
        centroid = geom.centroid()
        
        savi_only = computed_img.select([savi_name])
        red_only = base_img.select([red_band]).rename(['RED_RAW'])
        nir_only = base_img.select([nir_band]).rename(['NIR_RAW'])
        
        combined_img = savi_only.addBands(red_only).addBands(nir_only)
        
        sample = combined_img.sample(
            region=centroid, scale=scale, numPixels=1, geometries=False
        ).getInfo()
        
        features = sample.get('features', [])
        if not features:
            sample = combined_img.sample(
                region=geom, scale=scale, numPixels=1, geometries=False
            ).getInfo()
            features = sample.get('features', [])
            
        if not features:
            print("ERROR: Could not sample any valid pixels in the AOI.")
            return
            
        feat = features[0]
        props = feat.get('properties', {})
        
        raw_red = props.get('RED_RAW', 0)
        raw_nir = props.get('NIR_RAW', 0)
        ee_savi = props.get(savi_name, 0)
        
        print("\n[Input Data Verification - FIRST SAMPLED PIXEL]")
        print(f"Raw dataset {red_band} value: {raw_red}")
        print(f"Raw dataset {nir_band} value: {raw_nir}")
        
        print("\n[Scaling Analysis]")
        expected_input = context.index_definition.get("expected_input", "raw")
        bands_are_scaled = context.satellite_definition.get("stored_as_scaled_integers", False)
        scale_factor = context.satellite_definition.get("scale_factor", 1.0)
        
        print(f"Dataset stored_as_scaled_integers: {bands_are_scaled}")
        print(f"Dataset scale_factor: {scale_factor}")
        print(f"Index expected_input: {expected_input}")
        
        val_red_entering = raw_red
        val_nir_entering = raw_nir
        
        if bands_are_scaled and expected_input == "reflectance":
            print(f"Scaling performed: YES (Multiplied by {scale_factor})")
            val_red_entering = raw_red * scale_factor
            val_nir_entering = raw_nir * scale_factor
        else:
            print("Scaling performed: NO")
            
        print(f"Values after preprocessing (entering image.expression()):")
        print(f"  RED: {val_red_entering}")
        print(f"  NIR: {val_nir_entering}")
        
        print("\n[Mathematical Verification]")
        L = params.get('L', 0.5)
        print(f"Python calculation using exact values entering image.expression():")
        print(f"(({val_nir_entering} - {val_red_entering}) / ({val_nir_entering} + {val_red_entering} + {L})) * (1.0 + {L})")
        
        manual_savi = ((val_nir_entering - val_red_entering) / (val_nir_entering + val_red_entering + L)) * (1.0 + L)
        diff = abs(ee_savi - manual_savi)
        
        print(f"\nEarth Engine result: {ee_savi}")
        print(f"Python calculation result: {manual_savi}")
        print(f"Absolute difference: {diff}")
        if diff > 1e-6:
            print(f"WARNING: Difference exceeds 1e-6!")
            
        print("========== SAVI MATHEMATICAL VERIFICATION END ==========\n")
        
    except Exception as e:
        print(f"\n========== SAVI DIAGNOSTICS FAILED ==========\n{e}\n==============================================\n")
