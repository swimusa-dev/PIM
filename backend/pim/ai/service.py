"""AI service seam (AI-01 to AI-06). Every call goes through Foundation Model APIs on Databricks, governed by
Unity Gateway. The model per task comes from config, not code. Output never writes a value directly (P4): the
caller turns it into a ValueDraft with ai_generated=True and approval_state=proposed (AI-03).

Grounding (AI-06): prompts instruct the model to use only supplied facts and answer `NEEDS_INPUT: <attribute>`
instead of inventing. A post-check rejects outputs naming materials, percentages, or certifications absent from
the inputs. Certification claims additionally require a certificate on the Fabric entity.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from pim.config import get_settings

log = logging.getLogger(__name__)

TASK_TYPES = ("generate", "adapt", "extract", "classify", "check", "restructure", "expand")

SYSTEM_RULES = (
    "You write product content for Swim USA brands. Use ONLY the facts supplied in the input attributes and "
    "images. Never invent a material, percentage, measurement, care instruction, fit claim, or sustainability or "
    "certification claim. If a required fact is missing, output exactly `NEEDS_INPUT: <attribute_code>` on its own "
    "line instead of guessing. Follow the brand voice rules exactly. Do not use the em dash character."
)

_PERCENT = re.compile(r"\b\d{1,3}\s?%")
_CERT = re.compile(r"\b(REPREVE|GOTS|OCS|RCS|GRS|OEKO[- ]?TEX|BLUESIGN)\b", re.IGNORECASE)
_MATERIAL = re.compile(r"\b(nylon|polyamide|polyester|spandex|elastane|lycra|cotton|linen|modal|tencel|silk|wool|"
                       r"viscose|rayon|econyl|repreve)\b", re.IGNORECASE)


@dataclass
class BrandVoice:
    brand_code: str
    tone: str = ""
    do_rules: list[str] = field(default_factory=list)
    dont_rules: list[str] = field(default_factory=list)
    blocked_terms: list[str] = field(default_factory=list)
    trademark_terms: dict[str, str] = field(default_factory=dict)  # "ecorib" -> "EcoRib®"
    punctuation_rules: list[str] = field(default_factory=lambda: ["Never use the em dash character."])
    examples: list[str] = field(default_factory=list)

    def as_prompt(self) -> str:
        parts = [f"Brand voice for {self.brand_code}: {self.tone}"]
        if self.do_rules:
            parts.append("Do: " + "; ".join(self.do_rules))
        if self.dont_rules:
            parts.append("Do not: " + "; ".join(self.dont_rules))
        if self.blocked_terms:
            parts.append("Blocked terms: " + ", ".join(self.blocked_terms))
        if self.trademark_terms:
            parts.append("Trademark treatments: " + ", ".join(f"{k} -> {v}" for k, v in self.trademark_terms.items()))
        parts.extend(self.punctuation_rules)
        if self.examples:
            parts.append("Approved examples:\n" + "\n---\n".join(self.examples[:10]))
        return "\n".join(parts)


@dataclass
class PromptTemplate:
    code: str
    version: str
    task_type: str
    target_attribute: str
    body: str  # uses {{attr.<code>}} placeholders
    input_attributes: list[str] = field(default_factory=list)
    input_shot_types: list[str] = field(default_factory=list)
    channel_code: str | None = None
    family_code: str | None = None
    max_length: int | None = None

    def render(self, attrs: dict[str, Any]) -> str:
        def repl(m: re.Match) -> str:
            v = attrs.get(m.group(1))
            return "" if v is None else str(v)

        return re.sub(r"\{\{attr\.([a-z0-9_]+)\}\}", repl, self.body)


@dataclass
class AIResult:
    text: str
    model: str
    template_version: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    needs_input: list[str] = field(default_factory=list)
    grounding_errors: list[str] = field(default_factory=list)
    confidence: float | None = None
    raw: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.needs_input and not self.grounding_errors


class FoundationModelClient:
    """Thin wrapper over Databricks serving endpoints (chat completions). Swappable for tests."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    def chat(self, messages: list[dict], max_tokens: int, temperature: float = 0.3) -> dict:
        """Text-only messages go through the typed SDK call; messages whose content is a list of parts (text and
        image_url, IMG-03 tier 3 vision) use the raw OpenAI-compatible invocation the endpoint also accepts."""
        from databricks.sdk import WorkspaceClient

        w = WorkspaceClient()
        if any(isinstance(m.get("content"), list) for m in messages):
            resp = w.api_client.do("POST", f"/serving-endpoints/{self.endpoint}/invocations",
                                   body={"messages": messages, "max_tokens": max_tokens, "temperature": temperature})
            choice = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content", "")
            usage = resp.get("usage") or {}
            return {"content": choice, "prompt_tokens": usage.get("prompt_tokens", 0), "completion_tokens": usage.get("completion_tokens", 0)}
        from databricks.sdk.service.serving import ChatMessage, ChatMessageRole

        resp = w.serving_endpoints.query(
            name=self.endpoint,
            messages=[ChatMessage(role=ChatMessageRole(m["role"]), content=m["content"]) for m in messages],
            max_tokens=max_tokens, temperature=temperature,
        )
        choice = resp.choices[0].message.content if resp.choices else ""
        usage = resp.usage
        return {"content": choice, "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) or 0}


class AIService:
    def __init__(self, client_factory=None, logger=None) -> None:  # noqa: ANN001
        s = get_settings()
        self.endpoints = {"copy": s.ai_endpoint_copy, "classify": s.ai_endpoint_classify}
        self.max_tokens = s.ai_max_tokens
        self._factory = client_factory or FoundationModelClient
        self._log_call = logger or (lambda rec: log.info("ai_call %s", json.dumps(rec)))

    def endpoint_for(self, task_type: str) -> str:
        return self.endpoints["classify"] if task_type in ("classify", "extract", "check") else self.endpoints["copy"]

    def run(self, template: PromptTemplate, voice: BrandVoice, attrs: dict[str, Any], *, product_id: str,
            image_urls: list[str] | None = None, has_certificate: bool = False, user_email: str = "system",
            vision: bool = False, grounded: bool = True, endpoint: str | None = None, temperature: float = 0.3) -> AIResult:
        """`vision=True` sends the images as multimodal parts (AI-05 extract from images); `grounded=False` skips the
        prose grounding check for structured JSON tasks (classify, check, extract) whose output is parsed and
        validated by the caller instead."""
        prompt = template.render(attrs)
        facts = "\n".join(f"- {k}: {v}" for k, v in attrs.items() if v not in (None, ""))
        user_text = f"Input attributes (the only allowed facts):\n{facts}\n\nTask:\n{prompt}"
        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_RULES + "\n\n" + voice.as_prompt()}]
        if image_urls and vision:
            parts: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
            parts += [{"type": "image_url", "image_url": {"url": u}} for u in image_urls[:4]]
            messages.append({"role": "user", "content": parts})
        else:
            if image_urls:
                user_text += "\n\nApproved image URLs (for visual context only):\n" + "\n".join(image_urls)
            messages.append({"role": "user", "content": user_text})
        endpoint = endpoint or self.endpoint_for(template.task_type)
        started = time.monotonic()
        out = self._factory(endpoint).chat(messages, self.max_tokens, temperature=temperature)
        text = (out.get("content") or "").strip()
        result = AIResult(text=text, model=endpoint, template_version=template.version,
                          prompt_tokens=out.get("prompt_tokens", 0), completion_tokens=out.get("completion_tokens", 0), raw=out)
        result.needs_input = re.findall(r"NEEDS_INPUT:\s*([a-z0-9_]+)", text)
        if grounded:
            result.grounding_errors = grounding_check(text, attrs, has_certificate=has_certificate)
            if template.max_length and len(text) > template.max_length:
                result.grounding_errors.append(f"output exceeds {template.max_length} characters")
            for term in voice.blocked_terms:
                if term and re.search(rf"\b{re.escape(term)}\b", text, re.IGNORECASE):
                    result.grounding_errors.append(f"blocked term: {term}")
            if "—" in text:
                result.grounding_errors.append("contains an em dash")
        latency = int((time.monotonic() - started) * 1000)
        result.raw = {**out, "latency_ms": latency}
        self._log_call({"product_id": product_id, "task_type": template.task_type, "template": template.code,
                        "template_version": template.version, "model": endpoint, "user": user_email,
                        "prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens,
                        "latency_ms": latency, "ok": result.ok})
        return result


    def describe_image(self, image_url: str, *, shot_types: list[str], user_email: str = "system") -> dict:
        """IMG-03 tier 3: read visible style or color codes and name the shot type. Returns a dict with optional
        style_number, color_code, shot_type and confidence; never writes anything (P4)."""
        prompt = ("Look at this product photo from a swimwear catalog. Answer as JSON only with keys style_number "
                  "(6 digit code visible on a tag or caption, or null), color_code (2 to 6 letter code or null), shot_type "
                  f"(one of {', '.join(shot_types)} or null), confidence (0 to 1). Do not guess codes you cannot read.")
        messages = [{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image_url}}]}]
        started = time.monotonic()
        out = self._factory(self.endpoint_for("classify")).chat(messages, 300, temperature=0.0)
        text = (out.get("content") or "").strip()
        m = re.search(r"\{.*\}", text, re.DOTALL)
        parsed: dict = {}
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                parsed = {}
        self._log_call({"product_id": None, "task_type": "vision", "template": "image_identify", "template_version": "1",
                        "model": self.endpoint_for("classify"), "user": user_email, "prompt_tokens": out.get("prompt_tokens", 0),
                        "completion_tokens": out.get("completion_tokens", 0), "latency_ms": int((time.monotonic() - started) * 1000),
                        "ok": bool(parsed)})
        return {k: parsed.get(k) for k in ("style_number", "color_code", "shot_type", "confidence")} | {"raw": text[:500]}


def grounding_check(text: str, attrs: dict[str, Any], *, has_certificate: bool) -> list[str]:
    """AI-06 post-generation check: every material, percentage, and certification in the output must exist in
    the inputs; certification claims also need a certificate record."""
    errors: list[str] = []
    inputs = " ".join(str(v) for v in attrs.values() if v is not None).lower()
    for pct in _PERCENT.findall(text):
        if pct.replace(" ", "") not in inputs.replace(" ", ""):
            errors.append(f"percentage not in inputs: {pct}")
    for mat in {m.lower() for m in _MATERIAL.findall(text)}:
        if mat not in inputs:
            errors.append(f"material not in inputs: {mat}")
    for cert in {c.upper() for c in _CERT.findall(text)}:
        if cert.lower() not in inputs:
            errors.append(f"certification not in inputs: {cert}")
        elif not has_certificate:
            errors.append(f"certification {cert} has no certificate record on the Fabric")
    return errors


DEFAULT_VITAMIN_A_VOICE = BrandVoice(
    brand_code="vitamin_a",
    tone="Warm, confident, sun-soaked, and specific. Short sentences. Sensory but never gushing.",
    do_rules=["Name the fabric and its feel", "State fit and coverage plainly", "Use American English"],
    dont_rules=["No superlatives like best or perfect", "No invented sustainability claims", "No exclamation points"],
    blocked_terms=["cheap", "perfect", "guaranteed"],
    trademark_terms={"ecorib": "EcoRib®", "repreve": "REPREVE®", "ecolux": "EcoLux®"},
)
