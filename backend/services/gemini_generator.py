import os
import uuid
import json
from typing import Dict, Any
from google import genai
from google.genai import types
from backend.core.config import settings

class GeminiGeneratorService:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        if not self.api_key or self.api_key == "BURAYA_API_ANAHTARINI_YAPISTIR":
            print("WARNING: GEMINI_API_KEY is not set correctly in .env!")
        
    def _get_client(self):
        return genai.Client(api_key=self.api_key)

    def generate_and_analyze(self, prompt_text: str) -> Dict[str, Any]:
        """
        Step 1: Generate image using imagen-3.0-generate-001
        Step 2: Analyze image using gemini-2.5-flash
        """
        client = self._get_client()
        generation_id = f"gemini-{uuid.uuid4()}"
        
        try:
            print(f"[Gemini] 1. Imagen modelinden görsel üretiliyor: '{prompt_text}'")
            # Step 1: Generate Image
            result = client.models.generate_images(
                model='imagen-3.0-generate-001',
                prompt=prompt_text,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="1:1"
                )
            )
            
            generated_image = result.generated_images[0]
            image_bytes = generated_image.image.image_bytes
            
            print("[Gemini] 2. Üretilen görsel analiz ediliyor (gemini-2.5-flash)...")
            # Step 2: Analyze Image
            vision_prompt = """
            Analyze the demographic features of the primary person in this image.
            Return ONLY a valid JSON object with the following exact keys:
            - detected_age_group: Must be exactly one of ["18-24", "25-34", "35-44", "45-54", "55+"]
            - detected_gender: Must be exactly one of ["Male", "Female", "Unclear"]
            - detected_person_count: Integer representing the number of people.
            
            Do not include markdown blocks like ```json or any other text.
            """
            
            image_part = types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg')
            
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[image_part, vision_prompt]
            )
            
            raw_text = response.text.strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text.replace("```json", "").replace("```", "").strip()
                
            analysis = json.loads(raw_text)
            print(f"[Gemini] 3. Analiz tamamlandı: {analysis}")
            
            return {
                "generation_id": generation_id,
                "image_reference": "gemini_generated_no_save",
                "detected_age_group": analysis.get("detected_age_group", "Unclear"),
                "detected_gender": analysis.get("detected_gender", "Unclear"),
                "detected_person_count": analysis.get("detected_person_count", 1),
                "analysis_status": "success"
            }
            
        except Exception as e:
            print(f"[Gemini] ERROR: {e}")
            return {
                "generation_id": generation_id,
                "image_reference": "error",
                "detected_age_group": "Unclear",
                "detected_gender": "Unclear",
                "detected_person_count": 0,
                "analysis_status": "failed"
            }

gemini_generator = GeminiGeneratorService()
