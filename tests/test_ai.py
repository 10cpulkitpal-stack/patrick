from backend.ai import build_system_prompt


def test_prompt_uses_user_name_and_date():
    prompt = build_system_prompt({"display_name": "Shane"}, today="2026-10-06")
    assert "The user's name is Shane" in prompt
    assert "2026-10-06 (UTC)" in prompt


def test_prompt_does_not_force_a_title_or_table():
    prompt = build_system_prompt(today="2026-10-06")
    assert "Keep simple questions and greetings brief" in prompt
    assert "do not add a title or sections by default" in prompt
