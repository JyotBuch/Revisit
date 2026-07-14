import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger("revisit.llm")

DEFAULT_MODEL = "gpt-4o-mini"
PROMPT_VERSION = "v3"  # v3: research_notes-aware; research_notes is primary source when present

_REQUIRED_FIELDS = ("title", "why_saved", "original_context", "next_action")
_MAX_NEXT_ACTION_LENGTH = 300

_SYSTEM_PROMPT = (
    'You write short "Revisit Cards" that help a user resume a saved topic '
    "later. You are given capture/cluster context as JSON. "
    "Using ONLY that context, return a JSON object with exactly these string "
    "fields: title, why_saved, original_context, next_action. "
    "Do not invent URLs, sources, or facts that are not in the provided context. "
    "\n\n"
    "If a 'research_notes' object is present in the context: it was produced "
    "by a deep research pass and is the PRIMARY basis for original_context and "
    "next_action. Use research_notes.summary as the core of original_context — "
    "synthesize it into 2-4 sentences. Draw next_action from "
    "research_notes.questions_remaining (if any) or research_notes.key_findings. "
    "Reference specific findings; never contradict them. "
    "\n\n"
    "If only a 'resources' list is present (no research_notes): treat it as "
    "supporting context. Mention a resource only if genuinely relevant; never "
    "invent details beyond its title/snippet/url. If resources are weak or "
    "loosely related, say so rather than overstating their relevance. "
    "\n\n"
    "If context is thin, be explicit rather than inventing — say so plainly in "
    "original_context. Keep next_action concise: one actionable sentence."
)


def _log_event(event: str, **fields: Any) -> None:
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info("%s %s", event, details)


def get_active_model_name() -> str:
    return os.environ.get("OPENAI_REVISIT_CARD_MODEL", DEFAULT_MODEL)


def _validate_card_content(data: Any) -> Optional[Dict[str, str]]:
    if not isinstance(data, dict):
        return None
    result: Dict[str, str] = {}
    for field in _REQUIRED_FIELDS:
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            return None
        result[field] = value.strip()
    if len(result["next_action"]) > _MAX_NEXT_ACTION_LENGTH:
        return None
    return result


def generate_revisit_card_content(
    input_context: Dict[str, Any],
    *,
    owner_type: str,
    owner_id: str,
    db: Optional["Session"] = None,
    job_id: Optional[str] = None,
) -> Optional[Dict[str, str]]:
    """Generate Revisit Card fields via an LLM, or None if unavailable/failed.

    Callers must treat None as "fall back to rule-based generation" — this
    never raises for expected failure modes (missing key, API error,
    malformed response); it only returns None and logs why. Never logs the
    actual capture/cluster text, only ids, method, model, and failure type.

    When db is supplied, records a telemetry row with token counts and latency.
    """
    if not os.environ.get("OPENAI_API_KEY"):
        return None

    model = get_active_model_name()
    _log_event(
        "llm_card_generation_started",
        owner_type=owner_type,
        owner_id=owner_id,
        model=model,
    )

    from app.services.langfuse_client import get_langfuse

    lf = get_langfuse()
    lf_trace = None
    lf_gen = None
    _messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(input_context)},
    ]
    if lf is not None:
        try:
            # v4 SDK: use start_observation(as_type=...) — no .trace() or .generation()
            lf_trace = lf.start_observation(
                name="revisit-card-generation",
                as_type="agent",
                input=_messages,
                metadata={
                    "owner_type": owner_type,
                    "owner_id": owner_id,
                    "prompt_version": PROMPT_VERSION,
                    "job_id": job_id,
                },
            )
            lf_gen = lf_trace.start_observation(
                name="card-llm-call",
                as_type="generation",
                model=model,
                model_parameters={"response_format": "json_object"},
                input=_messages,
            )
        except Exception:
            lf_trace = None
            lf_gen = None

    latency_ms: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens_: Optional[int] = None

    start = time.monotonic()
    try:
        from openai import OpenAI

        client = OpenAI()
        response = client.chat.completions.create(
            model=model,
            response_format={"type": "json_object"},
            messages=_messages,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        usage = response.usage
        if usage is not None:
            input_tokens = usage.prompt_tokens
            output_tokens = usage.completion_tokens
            total_tokens_ = usage.total_tokens

        data = json.loads(response.choices[0].message.content)

    except Exception as exc:
        latency_ms = int((time.monotonic() - start) * 1000)
        failure_type = type(exc).__name__
        _log_event(
            "llm_card_generation_failed",
            owner_type=owner_type,
            owner_id=owner_id,
            model=model,
            failure_type=failure_type,
        )
        if lf_gen is not None:
            try:
                lf_gen.update(level="ERROR", status_message=str(exc))
                lf_gen.end()
                lf_trace.end()  # type: ignore[union-attr]
                lf.flush()  # type: ignore[union-attr]
            except Exception:
                pass
        if db is not None:
            _record(
                db,
                job_id=job_id,
                owner_type=owner_type,
                owner_id=owner_id,
                model=model,
                latency_ms=latency_ms,
                status="failed",
                failure_type=failure_type,
            )
        return None

    validated = _validate_card_content(data)
    if validated is None:
        _log_event(
            "llm_card_generation_failed",
            owner_type=owner_type,
            owner_id=owner_id,
            model=model,
            failure_type="ValidationError",
        )
        if lf_gen is not None:
            try:
                lf_gen.update(
                    output=response.choices[0].message.content,
                    level="WARNING",
                    status_message="ValidationError",
                    usage_details={"input": input_tokens, "output": output_tokens, "total": total_tokens_} if input_tokens else None,
                )
                lf_gen.end()
                lf_trace.end()  # type: ignore[union-attr]
                lf.flush()  # type: ignore[union-attr]
            except Exception:
                pass
        if db is not None:
            _record(
                db,
                job_id=job_id,
                owner_type=owner_type,
                owner_id=owner_id,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens_,
                latency_ms=latency_ms,
                status="failed",
                failure_type="ValidationError",
            )
        return None

    _log_event(
        "llm_card_generation_succeeded",
        owner_type=owner_type,
        owner_id=owner_id,
        model=model,
    )
    if lf_gen is not None:
        try:
            lf_gen.update(
                output=response.choices[0].message.content,
                usage_details={"input": input_tokens, "output": output_tokens, "total": total_tokens_} if input_tokens else None,
            )
            lf_gen.end()
            lf_trace.end()  # type: ignore[union-attr]
            lf.flush()  # type: ignore[union-attr]
        except Exception:
            pass
    if db is not None:
        _record(
            db,
            job_id=job_id,
            owner_type=owner_type,
            owner_id=owner_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens_,
            latency_ms=latency_ms,
            status="succeeded",
        )
    return validated


def _record(
    db: "Session",
    *,
    job_id: Optional[str],
    owner_type: str,
    owner_id: str,
    model: str,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    latency_ms: Optional[int],
    status: str,
    failure_type: Optional[str] = None,
) -> None:
    from app.services import telemetry

    try:
        telemetry.record_llm_call(
            db,
            job_id=job_id,
            owner_type=owner_type,
            owner_id=owner_id,
            purpose="revisit_card_generation",
            model_name=model,
            prompt_version=PROMPT_VERSION,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
            status=status,
            failure_type=failure_type,
        )
        db.commit()
    except Exception:
        logger.warning("telemetry_record_failed", exc_info=True)
        db.rollback()
