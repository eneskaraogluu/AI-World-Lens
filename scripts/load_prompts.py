import os
import sys
import json

# Proje ana dizinini Python yoluna ekle ki 'backend' paketini bulabilsin
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root)

from backend.core.database import SessionLocal
from backend.models.models import Category, Prompt

def load_prompts(json_path):
    print(f"Loading prompts from {json_path}...")
    
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    db = SessionLocal()
    categories_added = 0
    prompts_added = 0
    
    try:
        for cat_data in data.get("categories", []):
            cat_name = cat_data.get("name")
            
            # Kategori veritabanında var mı kontrol et
            category = db.query(Category).filter(Category.name == cat_name).first()
            if not category:
                # Yoksa yeni kategori oluştur
                category = Category(name=cat_name)
                db.add(category)
                db.commit()
                db.refresh(category)
                categories_added += 1
                
            for prompt_text in cat_data.get("prompts", []):
                # Bu kategori altında bu prompt var mı kontrol et
                prompt = db.query(Prompt).filter(
                    Prompt.category_id == category.id,
                    Prompt.text == prompt_text
                ).first()
                
                if not prompt:
                    # Yoksa ekle
                    prompt = Prompt(category_id=category.id, text=prompt_text)
                    db.add(prompt)
                    prompts_added += 1
            
            # Her kategori bittikten sonra o kategorinin promptlarını kaydet
            db.commit()
            
        print(f"SUCCESS: {categories_added} categories and {prompts_added} prompts were added.")
    except Exception as e:
        db.rollback()
        print(f"ERROR: Failed to load prompts. {e}")
    finally:
        db.close()

if __name__ == "__main__":
    json_file_path = os.path.join(project_root, "data", "prompts.json")
    load_prompts(json_file_path)
