import asyncio
import time
import uuid
import random
from typing import Tuple
from backend.services.base_generator import BaseImageGenerator

class MockGenerator(BaseImageGenerator):
    """
    Mock generator for testing purposes and offline development.
    Does not make any network requests.
    """
    
    @property
    def model_name(self) -> str:
        return "mock-generator"
        
    @property
    def model_version(self) -> str:
        return "1.0"

    async def generate_image(self, prompt: str, seed: int) -> Tuple[str, int, str]:
        start_time = time.time()
        
        # Simulate network delay for realistic testing (2-5 seconds)
        await asyncio.sleep(random.uniform(2.0, 5.0))
        
        # Use a pixel avatar or dummy URL for mock image reference
        image_id = (seed % 80) + 10
        image_path = f"https://xsgames.co/randomusers/assets/avatars/pixel/{image_id}.jpg"
        
        duration_ms = int((time.time() - start_time) * 1000)
        return image_path, duration_ms, None
