from app.config import load_settings


def test_defaults_point_to_gemini():
    s = load_settings({})
    assert s.base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"
    assert s.model == "gemini-2.5-flash"
    assert s.api_key is None


def test_repr_hides_key():
    s = load_settings({"LLM_API_KEY": "secret123"})
    assert "secret123" not in repr(s)
    assert "api_key='***'" in repr(s)


def test_repr_unset_key_is_none():
    assert "api_key=None" in repr(load_settings({}))


def test_empty_google_creds_is_none():
    assert load_settings({"GOOGLE_CREDENTIALS_FILE": ""}).google_credentials_file is None


def test_google_calendar_id_defaults_to_primary():
    assert load_settings({}).google_calendar_id == "primary"
    s = load_settings({"GOOGLE_CALENDAR_ID": "owner@gmail.com"})
    assert s.google_calendar_id == "owner@gmail.com"
