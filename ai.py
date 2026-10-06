"""Prompt construction for Patrick's language-model adapters."""

import base64
import datetime
import re

from google import genai
from google.genai import types as genai_types


def build_system_prompt(user=None, today=None):
    """Build a brief, user-aware prompt without forcing structure on answers."""
    name = (user or {}).get("display_name") or ""
    date = today or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    personalization = f"The user's name is {name}. Use it naturally when useful, but do not overuse it.\n" if name else ""
    return (
        "You are Patrick, a helpful and accurate AI assistant.\n"
        f"Today's date is {date} (UTC).\n"
        f"{personalization}"
        "Answer the user's actual question directly and naturally. Keep simple questions and greetings brief. "
        "Use headings, lists, tables, or code blocks only when they make the answer clearer; do not add a title or sections by default. "
        "Use Markdown when helpful, never raw HTML, and never wrap an entire answer in a code block. "
        "Be transparent about uncertainty and do not invent facts."
    )


class AIService:
    """Provider adapter for Groq and Gemini text/vision generation."""

    def __init__(self, groq_client, gemini_client, logger, *, text_model,
                 text_fallback, vision_model, vision_fallback, gemini_default,
                 max_output_tokens):
        self.groq_client = groq_client
        self.gemini_client = gemini_client
        self.logger = logger
        self.text_model = text_model
        self.text_fallback = text_fallback
        self.vision_model = vision_model
        self.vision_fallback = vision_fallback
        self.gemini_default = gemini_default
        self.max_output_tokens = max_output_tokens

    @staticmethod
    def _gemini_contents(messages):
        contents = []
        for message in messages:
            role = "model" if message["role"] == "assistant" else "user"
            value = message["content"]
            parts = []
            if isinstance(value, str):
                if value:
                    parts.append(genai_types.Part.from_text(text=value))
            else:
                for item in value:
                    if item.get("type") == "text" and item.get("text"):
                        parts.append(genai_types.Part.from_text(text=item["text"]))
                    elif item.get("type") == "image_url":
                        image_url = item.get("image_url", {}).get("url", "")
                        match = re.fullmatch(r"data:(image/(?:jpeg|png|webp|gif));base64,([A-Za-z0-9+/]+={0,2})", image_url)
                        if match:
                            image_bytes = base64.b64decode(match.group(2), validate=True)
                            parts.append(genai_types.Part.from_bytes(data=image_bytes, mime_type=match.group(1)))
            if parts:
                contents.append(genai_types.Content(role=role, parts=parts))
        return contents

    def generate_reply(self, messages, vision=False, provider="groq", selected_model=None, user=None):
        system_prompt = build_system_prompt(user)
        if provider == "gemini":
            if not self.gemini_client:
                raise RuntimeError("Gemini is not configured. Set GEMINI_API_KEY on the server.")
            model = selected_model or self.gemini_default
            response = self.gemini_client.models.generate_content(
                model=model,
                contents=self._gemini_contents(messages),
                config=genai_types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    max_output_tokens=self.max_output_tokens,
                ),
            )
            reply = (response.text or "").strip()
            if not reply:
                raise RuntimeError(f"Gemini model {model} returned an empty answer")
            candidates = getattr(response, "candidates", None) or []
            if candidates and "MAX_TOKENS" in str(getattr(candidates[0], "finish_reason", "")):
                reply += "\n\n_(This answer reached the output limit and may be incomplete.)_"
            return reply

        primary = selected_model or (self.vision_model if vision else self.text_model)
        fallback = self.vision_fallback if vision and primary == self.vision_model else self.text_fallback if not vision and primary == self.text_model else ""
        candidates = list(dict.fromkeys(model for model in (primary, fallback) if model))
        last_error = None
        for index, model in enumerate(candidates):
            try:
                response = self.groq_client.chat.completions.create(
                    model=model,
                    max_tokens=self.max_output_tokens,
                    messages=[{"role": "system", "content": system_prompt}] + messages,
                )
                choice = response.choices[0] if response.choices else None
                reply = (choice.message.content or "").strip() if choice else ""
                if not reply:
                    last_error = RuntimeError(f"Groq model {model} returned an empty answer")
                    continue
                if choice.finish_reason == "length":
                    reply += "\n\n_(This answer reached the output limit and may be incomplete.)_"
                return reply
            except Exception as error:
                last_error = error
                status_code = getattr(error, "status_code", None)
                if index + 1 >= len(candidates) or status_code not in {400, 404, 410, 422}:
                    raise
                self.logger.warning("Groq model %s unavailable; retrying with configured fallback %s", model, candidates[index + 1])
        if last_error:
            raise last_error
        raise RuntimeError("No Groq model is configured")
