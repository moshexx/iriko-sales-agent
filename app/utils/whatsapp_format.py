"""
WhatsApp message formatting utilities.

LLMs tend to produce Markdown output. WhatsApp uses a different (limited)
formatting syntax, so we normalise LLM output before sending.

WhatsApp formatting reference:
  *bold*        — single asterisk
  _italic_      — single underscore
  ~strikethrough~
  ```monospace```

What we fix here:
  **bold**  →  bold text (strip double asterisks — WA shows them literally)
"""

import re


def normalise_for_whatsapp(text: str) -> str:
    """Convert LLM Markdown output to WhatsApp-compatible plain text."""
    # **bold** → bold (strip double asterisks)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.DOTALL)
    return text
