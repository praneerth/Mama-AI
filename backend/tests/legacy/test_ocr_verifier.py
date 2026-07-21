from app.verifier.ocr_verifier import verify_ocr

success = verify_ocr([
    "chatgpt",
    "google",
    "youtube",
])

print("\nResult:", success)