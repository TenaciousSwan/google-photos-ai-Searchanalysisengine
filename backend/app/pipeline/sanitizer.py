import re
import hashlib
from typing import Tuple, Optional

# Regular expressions for PII detection
EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
PHONE_REGEX = re.compile(r'\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b')
SSN_REGEX = re.compile(r'\b\d{3}-\d{2}-\d{4}\b')
URL_REGEX = re.compile(r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)')
EMOJI_REGEX = re.compile(r'[\U00010000-\U0010ffff]', flags=re.UNICODE)

class DataSanitizer:
    """
    Sanitizes raw text:
      - Strips PII (SSNs, emails, phone numbers) per Edge Case 3.4
      - Filters out pure emojis, spam length floods, and 0-char reviews per Edge Case 1.2
      - Generates pseudonymized author hashes (e.g. usr_a3f81e)
    """

    @staticmethod
    def pseudonymize_author(author_name: Optional[str]) -> str:
        if not author_name or author_name.strip() in ("", "Google user", "Anonymous", "A Google user"):
            return "usr_anonymous"
        # Deterministic 8-char hex hash
        author_hash = hashlib.sha256(author_name.strip().encode("utf-8")).hexdigest()[:8]
        return f"usr_{author_hash}"

    @staticmethod
    def scrub_pii(text: str) -> str:
        """Replaces sensitive information with redaction tokens."""
        scrubbed = SSN_REGEX.sub("[REDACTED_SSN]", text)
        scrubbed = EMAIL_REGEX.sub("[REDACTED_EMAIL]", scrubbed)
        scrubbed = PHONE_REGEX.sub("[REDACTED_PHONE]", scrubbed)
        return scrubbed

    @staticmethod
    def validate_content_quality(text: str) -> Tuple[bool, str]:
        """
        Validates whether text is meaningful:
          - Length between 20 and 3500 chars
          - Emoji density < 50%
        Returns (is_valid, reason).
        """
        if not text or len(text.strip()) == 0:
            return False, "Empty content"

        clean = text.strip()
        if len(clean) < 20:
            return False, f"Too short ({len(clean)} chars; minimum 20 required)"

        if len(clean) > 3500:
            return False, f"Too long ({len(clean)} chars; maximum 3500 allowed)"

        # Check emoji density
        emojis = EMOJI_REGEX.findall(clean)
        emoji_count = len(emojis)
        if emoji_count > 0 and (emoji_count / len(clean)) > 0.4:
            return False, "Excessive emoji density (>40%)"

        return True, "Valid"

    @classmethod
    def sanitize(cls, raw_text: str, author_name: Optional[str] = None) -> Tuple[Optional[str], str, bool, str]:
        """
        Runs full sanitation pipeline.
        Returns (scrubbed_text, pseudonymized_author, is_valid, reason).
        """
        author = cls.pseudonymize_author(author_name)
        is_valid, reason = cls.validate_content_quality(raw_text)
        if not is_valid:
            return None, author, False, reason

        scrubbed = cls.scrub_pii(raw_text)
        return scrubbed, author, True, "OK"

sanitizer = DataSanitizer()
