import time
import os

class TimingProfiler:
    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = TimingProfiler()
        return cls._instance
        
    def __init__(self):
        self.log_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'timing.log')
        # Clear log on startup
        with open(self.log_path, 'w', encoding='utf-8') as f:
            f.write('--- NEW STARTUP SESSION ---\n')
            
    def record(self, tag: str, message: str = ''):
        t = time.perf_counter()
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(f'{t:.6f} | {tag:5s} | {message}\n')
