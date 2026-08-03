import os
import time
from backend.core.database import SessionLocal
from backend.models.models import Prompt, Category
from backend.services.hybrid_generator import hybrid_generator
from backend.services.result_service import save_result
import uuid

def run_full_report():
    print("=" * 60)
    print("AI WORLD LENS - FULL RESEARCH REPORT GENERATOR")
    print("=" * 60)
    print("Bu script veritabanindaki TUM meslekler (30 adet) icin 10'ar")
    print("adet gorsel uretir ve her ikisi (Gemini & OpenAI) ile analiz eder.")
    print("Islem internet hizina ve OpenAI kota sinirlarina bagli olarak")
    print("yaklasik 30-45 dakika surebilir. Lutfen pencereyi kapatmayin.")
    print("=" * 60)
    
    db = SessionLocal()
    prompts = db.query(Prompt).all()
    
    if not prompts:
        print("HATA: Veritabaninda hic istem (prompt) bulunamadi!")
        return

    # Generate a unique experiment ID for this run
    experiment_id = uuid.uuid4()
    
    total_prompts = len(prompts)
    generations_per_prompt = 10
    total_images_to_generate = total_prompts * generations_per_prompt
    
    print(f"Toplam Meslek/Istem Sayisi: {total_prompts}")
    print(f"Meslek Basi Uretim: {generations_per_prompt}")
    print(f"Toplam Uretilecek Gorsel: {total_images_to_generate}")
    print(f"Experiment Run ID: {experiment_id}")
    print("Basliyor...\n")

    images_generated = 0
    errors = 0

    for i, prompt in enumerate(prompts, 1):
        print(f"\n[{i}/{total_prompts}] Isleniyor: '{prompt.text}'")
        for j in range(1, generations_per_prompt + 1):
            print(f"  -> Gorsel {j}/{generations_per_prompt} uretiliyor...")
            try:
                # 1. Generate and Analyze
                analysis_data = hybrid_generator.generate_and_analyze(prompt.text)
                
                # 2. Save to Database
                save_result(db, experiment_id, prompt.id, analysis_data)
                
                images_generated += 1
                
                # Sleep a little to prevent hitting OpenAI API rate limits instantly
                time.sleep(2)
            except Exception as e:
                print(f"  -> HATA olustu: {e}")
                errors += 1
                time.sleep(5) # Backoff on error
    
    db.close()
    
    print("\n" + "=" * 60)
    print("RAPOR URETIMI TAMAMLANDI!")
    print(f"Basariyla Uretilen Gorsel: {images_generated}")
    print(f"Hata Alinan Gorsel: {errors}")
    print("Sonuclari arayuzden (Dashboard) aninda inceleyebilirsiniz.")
    print("=" * 60)

if __name__ == "__main__":
    try:
        run_full_report()
    except KeyboardInterrupt:
        print("\nIslem kullanici tarafindan iptal edildi.")
