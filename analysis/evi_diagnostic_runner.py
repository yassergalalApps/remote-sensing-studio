import ee
import traceback
from .diagnostic_utils import write_evi_diagnostic, normalize_scalar

class EVIDiagnosticRunner:
    @staticmethod
    def run_evi_denominator_diagnostic(image: ee.Image, aoi_geometry: ee.Geometry, scale: float, index_def: dict, satellite_def: dict, final_img: ee.Image) -> dict:
        write_evi_diagnostic("===== DIAGNOSTIC RUNNER ENTERED =====")
        try:
            # 1. Gather all info server-side, THEN write.
            # Fetch scene info
            sat_name = satellite_def.get("satellite_id", "Unknown")
            try:
                date = ee.Date(image.get('system:time_start')).format('YYYY-MM-dd').getInfo()
            except:
                date = "Unknown"
            
            # Setup bands
            band_mapping = satellite_def.get("band_mapping", {})
            nir_band = band_mapping.get("NIR", "B8")
            red_band = band_mapping.get("RED", "B4")
            blue_band = band_mapping.get("BLUE", "B2")
            
            scale_factor = satellite_def.get("scale_factor", 1.0)
            offset = satellite_def.get("additive_offset", 0.0)
            
            nir = image.select(nir_band).multiply(scale_factor).add(offset).toFloat()
            red = image.select(red_band).multiply(scale_factor).add(offset).toFloat()
            blue = image.select(blue_band).multiply(scale_factor).add(offset).toFloat()
            
            # Setup formula parameters
            formula_params = index_def.get("formula", {}).get("parameters", {})
            if not formula_params:
                formula_params = index_def.get("parameters", {})
                
            expr_args = {
                'NIR': nir, 'RED': red, 'BLUE': blue,
                'G': ee.Number(formula_params.get("G", 2.5)),
                'C1': ee.Number(formula_params.get("C1", 6.0)),
                'C2': ee.Number(formula_params.get("C2", 7.5)),
                'L': ee.Number(formula_params.get("L", 1.0))
            }
            
            # Calculate raw
            denom = image.expression("NIR + C1 * RED - C2 * BLUE + L", expr_args)
            abs_denom = denom.abs()
            num = image.expression("G * (NIR - RED)", expr_args)
            raw_evi = num.divide(denom)
            
            # Reducer helpers
            def count_pixels(img, condition=None):
                reduced = img.updateMask(condition) if condition else img
                stats = reduced.reduceRegion(
                    reducer=ee.Reducer.count(),
                    geometry=aoi_geometry,
                    scale=scale,
                    maxPixels=1e13
                ).getInfo()
                return int(normalize_scalar(stats))
                
            def get_min_max(img, condition=None):
                reduced = img.updateMask(condition) if condition else img
                stats = reduced.reduceRegion(
                    reducer=ee.Reducer.minMax(),
                    geometry=aoi_geometry,
                    scale=scale,
                    maxPixels=1e13
                ).getInfo()
                if not stats: return "N/A", "N/A"
                min_val = next((v for k, v in stats.items() if "min" in k.lower()), None)
                max_val = next((v for k, v in stats.items() if "max" in k.lower()), None)
                
                min_val = normalize_scalar(min_val, default="N/A") if min_val is not None else "N/A"
                max_val = normalize_scalar(max_val, default="N/A") if max_val is not None else "N/A"
                return min_val, max_val
            
            # Recreate masks
            eps = 0.01
            denom_mask = abs_denom.gte(eps)
            after_denom_mask = raw_evi.updateMask(denom_mask)
            
            bounds_mask = after_denom_mask.gte(-0.2).And(after_denom_mask.lte(1.0))
            finite_mask = after_denom_mask.eq(after_denom_mask).And(after_denom_mask.lt(1e38)).And(after_denom_mask.gt(-1e38))
            final_mask = bounds_mask.And(finite_mask)
            
            after_output_mask = after_denom_mask.updateMask(final_mask)

            # Build Result Object
            result_obj = {}
            
            # A. RAW INPUT IMAGE
            valid_p = count_pixels(nir)
            total_footprint = count_pixels(ee.Image.constant(1).clip(aoi_geometry))
            masked_p = total_footprint - valid_p
            result_obj["A"] = {"valid": valid_p, "masked": masked_p}
            
            # B. DENOMINATOR
            min_d, max_d = get_min_max(denom)
            min_abs_d, max_abs_d = get_min_max(abs_denom)
            result_obj["B"] = {"min_d": min_d, "max_d": max_d, "min_abs_d": min_abs_d, "max_abs_d": max_abs_d}
            
            # C. THRESHOLD TABLE
            thresholds = [1e-6, 1e-5, 1e-4, 1e-3, 2e-3, 5e-3, 1e-2, 2e-2, 5e-2, 1e-1]
            bio_invalid = raw_evi.lt(-0.2).Or(raw_evi.gt(1.0))
            math_invalid = raw_evi.lt(-1e30).Or(raw_evi.gt(1e30)).Or(raw_evi.eq(raw_evi).Not())
            
            c_results = []
            for th in thresholds:
                th_mask = abs_denom.lt(th)
                total_th = count_pixels(abs_denom, th_mask)
                invalid_in_th = count_pixels(abs_denom, th_mask.And(math_invalid))
                outbounds_in_th = count_pixels(abs_denom, th_mask.And(bio_invalid))
                c_results.append((th, total_th, invalid_in_th, outbounds_in_th))
            result_obj["C"] = c_results
            
            # D. RAW EVI BEFORE OUTPUT MASK
            def get_stats_dict(img_to_stat):
                c_finite = count_pixels(img_to_stat, img_to_stat.eq(img_to_stat).And(img_to_stat.lt(1e38)).And(img_to_stat.gt(-1e38)))
                c_nan = count_pixels(img_to_stat, img_to_stat.eq(img_to_stat).Not())
                c_inf = count_pixels(img_to_stat, img_to_stat.lt(-1e38).Or(img_to_stat.gt(1e38)))
                mi, ma = get_min_max(img_to_stat, img_to_stat.eq(img_to_stat).And(img_to_stat.lt(1e38)).And(img_to_stat.gt(-1e38)))
                c_out = count_pixels(img_to_stat, img_to_stat.lt(-0.2).Or(img_to_stat.gt(1.0)))
                return {"finite_count": c_finite, "nan_count": c_nan, "inf_count": c_inf, "min_finite": mi, "max_finite": ma, "out_bounds_count": c_out}
            
            result_obj["D"] = get_stats_dict(raw_evi)
            
            # E. FINAL EVI AFTER OUTPUT MASK
            e_stats = get_stats_dict(after_output_mask)
            masked_count = total_footprint - count_pixels(after_output_mask)
            e_stats["masked_count"] = masked_count
            result_obj["E"] = e_stats

            # 2. Serialize the complete object
            lines = []
            lines.append("===== EVI DIAGNOSTIC START =====")
            lines.append(f"\nScene:\n{sat_name} / {date}\n")
            
            lines.append("A. RAW INPUT IMAGE")
            lines.append(f"valid pixels: {result_obj['A']['valid']}")
            lines.append(f"masked pixels: {result_obj['A']['masked']}\n")
            
            lines.append("B. DENOMINATOR")
            lines.append(f"min D: {result_obj['B']['min_d']}")
            lines.append(f"max D: {result_obj['B']['max_d']}")
            lines.append(f"min |D|: {result_obj['B']['min_abs_d']}")
            lines.append(f"max |D|: {result_obj['B']['max_abs_d']}\n")
            
            lines.append("C. THRESHOLD TABLE\n")
            lines.append("threshold | total pixels |D| < threshold | math invalid | biological out-of-bounds")
            lines.append("for:")
            for row in result_obj["C"]:
                lines.append(f"{row[0]} | {row[1]} | {row[2]} | {row[3]}")
            lines.append("")
            
            lines.append("D. RAW EVI BEFORE OUTPUT MASK")
            d = result_obj["D"]
            lines.append(f"finite count: {d['finite_count']}\nNaN count: {d['nan_count']}\nInf count: {d['inf_count']}\nfinite min: {d['min_finite']}\nfinite max: {d['max_finite']}\nout-of-bounds count: {d['out_bounds_count']}\n")
            
            lines.append("E. FINAL EVI AFTER OUTPUT VALIDITY MASK")
            e = result_obj["E"]
            lines.append(f"finite count: {e['finite_count']}\nNaN count: {e['nan_count']}\nInf count: {e['inf_count']}\nfinite min: {e['min_finite']}\nfinite max: {e['max_finite']}\nout-of-bounds count: {e['out_bounds_count']}\nmasked count: {e['masked_count']}\n")
            
            # Write ONCE to file
            write_evi_diagnostic("\n".join(lines))
            return result_obj
            
        except Exception as e:
            write_evi_diagnostic(f"DIAGNOSTIC CRASHED: {e}\n{traceback.format_exc()}")
            return {}
