from open_transcribe.settings import SecuritySettings, Settings


def test_default_configuration_is_available_from_source_checkout() -> None:
    settings = Settings(
        environment="test",
        security=SecuritySettings(auth_mode="none"),
    )

    assert (settings.config_dir / "pricing.yaml").is_file()
    assert (settings.config_dir / "routing.yaml").is_file()
