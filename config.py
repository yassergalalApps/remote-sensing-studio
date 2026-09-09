# remote_sensing_studio/config.py

# Internal constants and configurations for the Remote Sensing Studio plugin

# The maximum number of concurrent downloads to run during an Earth Engine export.
# 2 is the recommended default to balance performance and avoid Earth Engine rate limits.
CONCURRENT_DOWNLOADS = 3

# --- Export Pipeline Optimization (Phase 1) ---
WEB_DEMO_URL = "https://yassergalalapps.github.io/remote-sensing-studio-website/"
WORK_QUEUE_ENABLED = True
OVER_PARTITION_FACTOR = 4
TARGET_PIXELS_PER_TILE = 10_000_000
SLOW_TILE_TIMEOUT = 120
MAX_TILE_RECURSION = 3
MIN_TILE_PIXEL_COUNT = 100_000
MAX_RETRIES_BEFORE_SPLIT = 2
MAX_PENDING_TILES = 100

# --- Phase 2 Configuration (Adaptive Download Engine) ---
# Options: "LEGACY" (getDownloadURL), "COMPUTE_PIXELS" (High-Volume API)
DOWNLOAD_API = "LEGACY"

# Options: "PHASE1", "GREEDY_x2", "GREEDY_x4", "MAXIMUM", "AUTO_PROGRESSIVE"
TILE_SIZING_STRATEGY = "PHASE1"

# Dynamically evaluates success/failure and adjusts the target tile size
AUTO_TUNE_TILE_SIZE = True

# Path to the structured JSON history for benchmarks
import os
import tempfile
BENCHMARK_HISTORY_FILE = os.path.join(tempfile.gettempdir(), "rss_benchmark_history.json")

# --- Debugging Toggles ---
EVI_DEBUG = True

