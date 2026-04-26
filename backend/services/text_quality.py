import re


PLACEHOLDER_PATTERN = re.compile(r"^\s*\{\{[^{}]+\}\}\s*$")


def is_placeholder_text(value: str | None) -> bool:
    if not value:
        return False

    stripped = value.strip()
    return bool(PLACEHOLDER_PATTERN.fullmatch(stripped))


def clean_ad_text(value: str | None) -> str:
    if not value:
        return ""

    stripped = value.strip()
    if is_placeholder_text(stripped):
        return ""

    return stripped
