"""Tests for chat session title generation."""

from app.services.chat_sessions import DEFAULT_SESSION_TITLE, generate_title_from_prompts


def test_generate_title_uses_prompt_context():
    title = generate_title_from_prompts(
        [
            "Help me design a rollback plan for the production deploy tonight.",
            "Also include smoke tests and alert checks.",
            "Keep it concise with clear ownership.",
            "This fourth prompt should be ignored for title seeding.",
        ]
    )
    lowered = title.lower()
    assert "rollback" in lowered
    assert "production" in lowered
    assert "smoke" in lowered


def test_generate_title_defaults_for_empty_input():
    assert generate_title_from_prompts([]) == DEFAULT_SESSION_TITLE
    assert generate_title_from_prompts(["   "]) == DEFAULT_SESSION_TITLE
