import os
import uuid

from werkzeug.utils import secure_filename


PDF_SIGNATURE = b'%PDF-'


def _validate_pdf_bytes(data: bytes, original_name: str, max_bytes: int) -> None:
    if not original_name or not secure_filename(original_name).lower().endswith('.pdf'):
        raise ValueError('Only PDF files are allowed.')
    if not data:
        raise ValueError('The uploaded file is empty.')
    if len(data) > max_bytes:
        raise ValueError(f'The PDF exceeds the maximum allowed size of {max_bytes} bytes.')
    if not data.startswith(PDF_SIGNATURE):
        raise ValueError('The uploaded file is not a valid PDF.')

    # Basic structural validation using PyMuPDF when available. This catches
    # renamed/non-PDF payloads while keeping the function usable in minimal tests.
    try:
        import fitz
        document = fitz.open(stream=data, filetype='pdf')
        try:
            if document.page_count < 1:
                raise ValueError('The PDF contains no pages.')
        finally:
            document.close()
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('The uploaded file could not be parsed as a PDF.') from exc


def validate_pdf_bytes(data: bytes, original_name: str, max_bytes: int) -> None:
    """Validate PDF filename, size and content before persistence."""
    _validate_pdf_bytes(data, original_name, max_bytes)


def validate_and_save_pdf(file_obj, destination_dir: str, max_bytes: int = 100 * 1024 * 1024) -> str:
    """Validate an uploaded PDF and persist it under an unpredictable filename."""
    original_name = file_obj.filename or ''
    current_pos = file_obj.tell() if hasattr(file_obj, 'tell') else 0
    try:
        file_obj.seek(0)
        data = file_obj.read(max_bytes + 1)
    finally:
        try:
            file_obj.seek(current_pos)
        except Exception:
            pass

    _validate_pdf_bytes(data, original_name, max_bytes)

    os.makedirs(destination_dir, exist_ok=True)
    safe_filename = f"{uuid.uuid4().hex}.pdf"
    safe_path = os.path.abspath(os.path.join(destination_dir, safe_filename))
    destination_root = os.path.abspath(destination_dir)
    if os.path.commonpath([safe_path, destination_root]) != destination_root:
        raise ValueError('Invalid storage path.')

    with open(safe_path, 'wb') as output:
        output.write(data)

    return safe_path
