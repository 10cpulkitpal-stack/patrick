from backend.ai import build_system_prompt
from backend.ai import AIService
from types import SimpleNamespace
from unittest.mock import Mock


def test_prompt_uses_user_name_and_date():
    prompt = build_system_prompt({"display_name": "Shane"}, today="2026-10-06")
    assert "The user's name is Shane" in prompt
    assert "2026-10-06 (UTC)" in prompt


def test_prompt_does_not_force_a_title_or_table():
    prompt = build_system_prompt(today="2026-10-06")
    assert "Keep simple questions and greetings brief" in prompt
    assert "do not add a title or sections by default" in prompt


def test_groq_stream_uses_low_gpt_oss_reasoning_effort():
    groq_client = Mock()
    groq_client.chat.completions.create.return_value = iter([
        SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content="Fast answer."), finish_reason=None,
        )]),
        SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content=None), finish_reason="stop",
        )]),
    ])
    service = AIService(
        groq_client, None, Mock(), text_model="openai/gpt-oss-120b",
        text_fallback="openai/gpt-oss-20b", vision_model="vision-model",
        vision_fallback="", gemini_default="gemini-3.8-flash", max_output_tokens=4096,
    )

    assert "".join(service.generate_reply_stream(
        [{"role": "user", "content": "hi"}], selected_model="openai/gpt-oss-120b",
    )) == "Fast answer."
    options = groq_client.chat.completions.create.call_args.kwargs
    assert options["stream"] is True
    assert options["reasoning_effort"] == "low"
    assert options["include_reasoning"] is False


def test_gemini_stream_falls_back_to_groq_when_the_client_is_unavailable():
    groq_client = Mock()
    groq_client.chat.completions.create.return_value = iter([
        SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content="Groq fallback."), finish_reason="stop",
        )]),
    ])
    service = AIService(
        groq_client, None, Mock(), text_model="openai/gpt-oss-120b",
        text_fallback="openai/gpt-oss-20b", vision_model="vision-model",
        vision_fallback="", gemini_default="gemini-3.8-flash", max_output_tokens=4096,
    )

    assert "".join(service.generate_reply_stream(
        [{"role": "user", "content": "hi"}], provider="gemini",
        selected_model="gemini-3.8-flash",
    )) == "Groq fallback."
    groq_client.chat.completions.create.assert_called_once()
    assert groq_client.chat.completions.create.call_args.kwargs["model"] == "openai/gpt-oss-120b"


def test_gemini_stream_yields_incremental_text():
    gemini_client = Mock()
    gemini_client.models.generate_content_stream.return_value = iter([
        SimpleNamespace(text="First "),
        SimpleNamespace(text="reply."),
    ])
    service = AIService(
        Mock(), gemini_client, Mock(), text_model="openai/gpt-oss-120b",
        text_fallback="openai/gpt-oss-20b", vision_model="vision-model",
        vision_fallback="", gemini_default="gemini-3.8-flash", max_output_tokens=4096,
    )

    assert list(service.generate_reply_stream(
        [{"role": "user", "content": "hi"}], provider="gemini",
        selected_model="gemini-3.8-flash",
    )) == ["First ", "reply."]
    gemini_client.models.generate_content_stream.assert_called_once()
