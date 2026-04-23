from scrobblebox.core.discogs import normalize_text, parse_duration_seconds, track_side


def test_normalize_text_strips_noise() -> None:
    assert normalize_text("Song Title (Remastered) [Live]!") == "song title"


def test_parse_duration_seconds() -> None:
    assert parse_duration_seconds("3:45") == 225
    assert parse_duration_seconds("1:02:03") == 3723
    assert parse_duration_seconds("") is None


def test_track_side() -> None:
    assert track_side("A3") == "A"
    assert track_side("C1") == "C"
    assert track_side(None) is None
