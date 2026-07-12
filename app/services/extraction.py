from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup

from app.schemas.capture import Capture, CaptureStatus, SourceType


@dataclass
class ExtractionResult:
    extracted_text: Optional[str]
    status: CaptureStatus
    extraction_error: Optional[str]


def _extract_article(capture: Capture) -> ExtractionResult:
    if not capture.url:
        return ExtractionResult(
            None, CaptureStatus.failed, "No URL available for article capture."
        )
    try:
        response = requests.get(
            capture.url, timeout=10, headers={"User-Agent": "RevisitBot/0.1"}
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        return ExtractionResult(None, CaptureStatus.failed, f"Failed to fetch URL: {exc}")

    soup = BeautifulSoup(response.text, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    if not text:
        return ExtractionResult(
            None, CaptureStatus.failed, "No readable text found at URL."
        )
    return ExtractionResult(text, CaptureStatus.extracted, None)


def _extract_with_fallback(
    capture: Capture, not_implemented_message: str
) -> ExtractionResult:
    text = capture.selected_text or capture.user_note
    if text:
        return ExtractionResult(text, CaptureStatus.extracted, None)
    return ExtractionResult(None, CaptureStatus.failed, not_implemented_message)


def extract_capture_content(capture: Capture) -> ExtractionResult:
    if capture.source_type == SourceType.passage:
        if capture.selected_text:
            return ExtractionResult(capture.selected_text, CaptureStatus.extracted, None)
        return ExtractionResult(
            None, CaptureStatus.failed, "No selected_text available for passage capture."
        )

    if capture.source_type == SourceType.note:
        if capture.user_note:
            return ExtractionResult(capture.user_note, CaptureStatus.extracted, None)
        return ExtractionResult(
            None, CaptureStatus.failed, "No user_note available for note capture."
        )

    if capture.source_type == SourceType.article:
        return _extract_article(capture)

    if capture.source_type == SourceType.video:
        return _extract_with_fallback(
            capture, "Video transcript extraction not implemented yet."
        )

    if capture.source_type == SourceType.image:
        return _extract_with_fallback(
            capture, "Image OCR extraction not implemented yet."
        )

    return ExtractionResult(
        None, CaptureStatus.failed, f"Unsupported source_type: {capture.source_type}"
    )
