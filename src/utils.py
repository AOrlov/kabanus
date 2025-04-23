def strip_markdown_to_json(text: str) -> str:
    text = text.strip()
    #remove markdown code block markers if present
    if text.startswith('```json'):
        text = text[7:]
    if text.endswith('```'):
        text = text[:-3]
    return text.strip()
