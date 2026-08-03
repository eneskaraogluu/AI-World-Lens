import os
import uuid
import json
import base64
import requests
from typing import Dict, Any
from google import genai
from google.genai import types
from openai import OpenAI
from backend.core.config import settings

class HybridGeneratorService:
    def __init__(self):
        self.gemini_api_key = settings.GEMINI_API_KEY
        self.openai_api_key = settings.OPENAI_API_KEY
        
        if not self.gemini_api_key or not self.openai_api_key or "BURAYA" in self.gemini_api_key or "BURAYA" in self.openai_api_key:
            print("WARNING: API keys are not set correctly in .env!")
            
    def _get_gemini_client(self):
        return genai.Client(api_key=self.gemini_api_key)
        
    def _get_openai_client(self):
        return OpenAI(api_key=self.openai_api_key)

    def generate_and_analyze(self, prompt_text: str) -> Dict[str, Any]:
        """
        Step 1: Generate image using OpenAI DALL-E 3
        Step 2: Download image bytes
        Step 3: Analyze image using Gemini 2.5 Flash
        """
        generation_id = f"hybrid-{uuid.uuid4()}"
        
        try:
            print(f"[Hybrid] 1. OpenAI (DALL-E 2) ile görsel üretiliyor: '{prompt_text}'")
            openai_client = self._get_openai_client()
            
            # Step 1: Generate Image
            response = openai_client.images.generate(
                model="dall-e-3",
                prompt=prompt_text,
                size="1024x1024",
                n=1,
            )
            image_url = response.data[0].url
            print(f"[Hybrid] 1.1. Görsel üretildi. İndiriliyor...")
            
            # Step 2: Download Image Bytes
            img_response = requests.get(image_url, timeout=15)
            img_response.raise_for_status()
            image_bytes = img_response.content
            
            # Step 2.5: Save image locally to frontend/assets/generations
            filename = f"{generation_id}.jpg"
            save_dir = os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "assets", "generations")
            os.makedirs(save_dir, exist_ok=True)
            file_path = os.path.join(save_dir, filename)
            with open(file_path, "wb") as f:
                f.write(image_bytes)
            
            print("[Hybrid] 2. Üretilen görsel analiz ediliyor (gemini-2.5-flash)...")
            gemini_client = self._get_gemini_client()
            
            # Step 3: Analyze Image (Coder 1 - Gemini)
            vision_prompt = """
            Analyze the demographic features of the primary person in this image.
            Return ONLY a valid JSON object with the following exact keys:
            - detected_age_group: Must be exactly one of ["18-24", "25-34", "35-44", "45-54", "55+"]
            - detected_gender: Must be exactly one of ["Male", "Female", "Unclear"]
            - detected_person_count: Integer representing the number of people.
            - detected_location: Must be exactly one of ["Urban", "Rural", "Indoors", "Outdoors", "Unclear"]
            - detected_socioeconomic_status: Must be exactly one of ["Low", "Middle", "High", "Unclear"]
            
            Do not include markdown blocks like ```json or any other text.
            """
            
            image_part = types.Part.from_bytes(data=image_bytes, mime_type='image/jpeg')
            
            vision_response = gemini_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[image_part, vision_prompt]
            )
            
            raw_text = vision_response.text.strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text.replace("```json", "").replace("```", "").strip()
                
            analysis = json.loads(raw_text)
            print(f"[Hybrid] 3. 1. Kodlayıcı (Gemini) Analizi: {analysis}")
            
            # Step 4: Analyze Image (Coder 2 - OpenAI)
            print("[Hybrid] 4. 2. Bağımsız Kodlayıcı çalışıyor (OpenAI gpt-4o-mini)...")
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
            
            openai_response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": vision_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=300
            )
            raw_text_2 = openai_response.choices[0].message.content.strip()
            if raw_text_2.startswith("```json"):
                raw_text_2 = raw_text_2.replace("```json", "").replace("```", "").strip()
            
            analysis_2 = json.loads(raw_text_2)
            print(f"[Hybrid] 5. 2. Kodlayıcı (OpenAI) Analizi: {analysis_2}")
            
            # Calculate Inter-Coder Reliability
            matches = 0
            keys_to_compare = ["detected_age_group", "detected_gender", "detected_location", "detected_socioeconomic_status"]
            for key in keys_to_compare:
                if analysis.get(key) == analysis_2.get(key):
                    matches += 1
            
            agreement_score = int((matches / 4.0) * 100)
            
            # We use Coder 1 (Gemini) as primary, but store both
            return {
                "generation_id": generation_id,
                "image_reference": filename,
                "detected_age_group": analysis.get("detected_age_group", "Unclear"),
                "detected_gender": analysis.get("detected_gender", "Unclear"),
                "detected_person_count": analysis.get("detected_person_count", 1),
                "detected_location": analysis.get("detected_location", "Unclear"),
                "detected_socioeconomic_status": analysis.get("detected_socioeconomic_status", "Unclear"),
                "coder1_data": json.dumps(analysis),
                "coder2_data": json.dumps(analysis_2),
                "coder_agreement_score": agreement_score,
                "analysis_status": "success"
            }
            
        except Exception as e:
            print(f"[Hybrid] ERROR: {e}")
            return {
                "generation_id": generation_id,
                "image_reference": "error",
                "detected_age_group": "Unclear",
                "detected_gender": "Unclear",
                "detected_person_count": 0,
                "detected_location": "Unclear",
                "detected_socioeconomic_status": "Unclear",
                "coder1_data": None,
                "coder2_data": None,
                "coder_agreement_score": 0,
                "analysis_status": "failed"
            }

hybrid_generator = HybridGeneratorService()
