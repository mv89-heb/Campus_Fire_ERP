import os
import uuid

def validate_and_save_pdf(file_obj, destination_dir: str) -> str:
    if not file_obj.filename.lower().endswith('.pdf'):
        raise Exception("Only PDF files are allowed.")
    
    # התיקון: שימוש ב-UUID לשם הקובץ הפיזי כדי למנוע מחיקת עברית
    safe_filename = f"{uuid.uuid4().hex}.pdf"
    
    os.makedirs(destination_dir, exist_ok=True)
    safe_path = os.path.join(destination_dir, safe_filename)
    file_obj.save(safe_path)
    
    return safe_path
