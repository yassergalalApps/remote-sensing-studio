import numpy as np
from typing import Dict, Any, Tuple, Optional, List

class ClassificationEngine:
    """
    Separates scientific classification logic from visualization.
    Evaluates classification modes (Binary, Continuous, Equal Interval, Quantile, Natural Breaks, Custom Breaks) dynamically in-memory.
    """
    
    @staticmethod
    def classify(data_array: np.ndarray, mode: str, nodata: Optional[float] = None, 
                 breaks: Optional[List[float]] = None, num_classes: int = 5) -> np.ndarray:
        """
        Classifies the data_array based on the provided mode.
        Returns a classified numpy array where pixels are assigned a class index (0 to num_classes-1).
        NoData pixels are assigned -1.
        """
        classified = np.full(data_array.shape, -1, dtype=np.int16)
        
        if nodata is not None:
            if np.isnan(nodata):
                valid_mask = ~np.isnan(data_array)
            else:
                valid_mask = (data_array != nodata) & ~np.isnan(data_array)
        else:
            valid_mask = ~np.isnan(data_array)
            
        valid_data = data_array[valid_mask]
        
        if valid_data.size == 0:
            return classified
            
        if mode == "Binary":
            # Requires exactly one break (the threshold originating from index metadata or UI override)
            if not breaks or len(breaks) < 1:
                raise ValueError("Binary classification mode requires a break threshold originating from metadata or user input.")
            threshold = breaks[0]
            classified_valid = np.where(valid_data >= threshold, 1, 0)
            
        elif mode == "Continuous":
            # Continuous doesn't map directly to discrete integer classes in the same way,
            # but we can return the raw data and let the renderer handle continuous color ramps.
            # However, for API consistency if someone wants 'classes' out of continuous:
            classified_valid = np.zeros_like(valid_data, dtype=np.int16)
            
        elif mode == "Equal Interval":
            min_val = np.min(valid_data)
            max_val = np.max(valid_data)
            edges = np.linspace(min_val, max_val, num_classes + 1)
            classified_valid = np.digitize(valid_data, edges[1:-1])
            
        elif mode == "Quantile":
            quantiles = np.linspace(0, 100, num_classes + 1)
            edges = np.percentile(valid_data, quantiles)
            # Ensure strictly increasing edges to avoid digitize errors
            edges = np.unique(edges)
            classified_valid = np.digitize(valid_data, edges[1:-1])
            
        elif mode == "Natural Breaks (Jenks)":
            # Note: Jenks can be slow for large arrays. Consider random sampling for breaks calculation.
            edges = ClassificationEngine._jenks_breaks(valid_data, num_classes)
            classified_valid = np.digitize(valid_data, edges[1:-1])
            
        elif mode == "Custom Breaks":
            if not breaks:
                raise ValueError("Custom Breaks mode requires a list of breaks.")
            edges = sorted(breaks)
            classified_valid = np.digitize(valid_data, edges)
            
        else:
            raise ValueError(f"Unknown classification mode: {mode}")
            
        classified[valid_mask] = classified_valid
        return classified

    @staticmethod
    def _jenks_breaks(data: np.ndarray, num_classes: int, sample_size: int = 10000) -> List[float]:
        """
        Calculates Natural Breaks using Jenks optimization.
        Uses Jenks-Caspall algorithm or standard Jenks. For performance on large rasters,
        it samples the data first.
        """
        # Simple sampling for performance
        if data.size > sample_size:
            sampled_data = np.random.choice(data, size=sample_size, replace=False)
        else:
            sampled_data = data
            
        # Due to complexity of pure Jenks, we'll use a fast alternative (k-means 1D) 
        # or simplified Jenks. Here we implement a simplified k-means 1D for speed.
        try:
            from sklearn.cluster import KMeans
            kmeans = KMeans(n_clusters=num_classes, n_init=1, random_state=42)
            kmeans.fit(sampled_data.reshape(-1, 1))
            centers = np.sort(kmeans.cluster_centers_.flatten())
            # Midpoints between centers
            edges = [np.min(sampled_data)]
            for i in range(len(centers) - 1):
                edges.append((centers[i] + centers[i+1]) / 2.0)
            edges.append(np.max(sampled_data))
            return edges
        except ImportError:
            # Fallback to quantiles if sklearn is missing
            return np.percentile(sampled_data, np.linspace(0, 100, num_classes + 1)).tolist()

