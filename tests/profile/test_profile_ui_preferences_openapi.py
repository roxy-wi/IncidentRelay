from app.api.openapi.endpoints.profile import PROFILE_SCHEMA, PROFILE_UPDATE_SCHEMA


def test_profile_openapi_documents_ui_preferences():
    profile_properties = PROFILE_SCHEMA["properties"]
    update_properties = PROFILE_UPDATE_SCHEMA["properties"]

    assert profile_properties["locale"]["enum"] == ["en", "de", "fr", "ru"]
    assert profile_properties["theme"]["enum"] == ["system", "light", "dark"]
    assert update_properties["locale"]["enum"] == ["en", "de", "fr", "ru"]
    assert update_properties["theme"]["enum"] == ["system", "light", "dark"]
