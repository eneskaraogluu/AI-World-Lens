from abc import ABC, abstractmethod
import time
from typing import Dict, Any, Tuple

class BaseImageGenerator(ABC):
    """
    Abstract base class for all image generators.
    Enforces a strict contract for generating images.
    """
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the name of the model (e.g., 'pollinations-flux')"""
        pass
        
    @property
    @abstractmethod
    def model_version(self) -> str:
        """Return the version of the model (e.g., '1.0')"""
        pass

    @abstractmethod
    async def generate_image(self, prompt: str, seed: int | None) -> Tuple[str, int, str]:
        """
        Generate an image for a given prompt and seed.
        
        Args:
            prompt (str): The prompt to generate an image for.
            seed (int | None): Provider seed; None when the provider has no seed support.
            
        Returns:
            Tuple[str, int, str]: (image_reference_url_or_path, generation_duration_ms, error_message)
            If error_message is not empty, image_reference should be None.
        """
        pass
