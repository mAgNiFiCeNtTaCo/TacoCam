import json

from tacocam import settings as S


def test_defaults_match_contract():
    d = S.default_settings()
    assert d["phone"]["zoom"] == 1.0 and d["phone"]["camera"] == "back"
    assert d["pc"]["output"] == "1920x1080" and d["pc"]["connect"] == "usb"
    assert d["pc"]["vcam_name"] == "Taco Cam" and d["pc"]["when_disconnected"] == "card"
    assert S.default_settings() is not S.DEFAULTS and S.default_settings() == S.DEFAULTS


def test_missing_file_gives_defaults(tmp_path):
    s, note = S.load(tmp_path / "settings.json")
    assert s == S.DEFAULTS and note is None


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "settings.json"
    s = S.default_settings()
    S.deep_update(s, {"phone": {"zoom": 0.5, "focus": {"mode": "manual"}}, "pc": {"output": "1080x1920", "rotate": 90}})
    assert S.save(s, p)
    again, note = S.load(p)
    assert note is None and again == s
    assert not (tmp_path / "settings.json.tmp").exists()


def test_partial_file_is_filled_with_defaults(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"phone": {"zoom": 3.0, "focus": {"position": 0.9}}}), encoding="utf-8")
    s, note = S.load(p)
    assert s["phone"]["zoom"] == 3.0 and s["phone"]["focus"] == {"mode": "auto", "position": 0.9}
    assert s["pc"] == S.DEFAULTS["pc"]


def test_corrupt_file_kept_as_bad(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{ this is not json", encoding="utf-8")
    s, note = S.load(p)
    assert s == S.DEFAULTS
    assert note and "settings.bad.json" in note
    assert not p.exists()
    assert (tmp_path / "settings.bad.json").read_text(encoding="utf-8") == "{ this is not json"


def test_not_an_object_counts_as_corrupt(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    s, note = S.load(p)
    assert s == S.DEFAULTS and (tmp_path / "settings.bad.json").exists()


def test_bom_file_is_read(tmp_path):
    p = tmp_path / "settings.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"pc": {"fit": "fit"}}).encode())
    s, note = S.load(p)
    assert note is None and s["pc"]["fit"] == "fit"


def test_bad_values_replaced_one_by_one(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "phone": {"zoom": "big", "fps": True, "bitrate_mbps": 500, "codec": "hevc", "hdr": "yes",
                  "exposure": {"mode": "weird", "iso": -5, "shutter_s": 0.01}},
        "pc": {"rotate": 45, "output": "800x600", "mirror": True, "vcam_name": "  "},
    }), encoding="utf-8")
    s, _ = S.load(p)
    d = S.DEFAULTS
    assert s["phone"]["zoom"] == d["phone"]["zoom"]
    assert s["phone"]["fps"] == 30
    assert s["phone"]["bitrate_mbps"] == d["phone"]["bitrate_mbps"]
    assert s["phone"]["codec"] == "hevc"            # the good value survives
    assert s["phone"]["hdr"] is False
    assert s["phone"]["exposure"]["mode"] == "auto" and s["phone"]["exposure"]["iso"] is None
    assert s["phone"]["exposure"]["shutter_s"] == 0.01
    assert s["pc"]["rotate"] == "auto" and s["pc"]["output"] == "1920x1080"
    assert s["pc"]["mirror"] is True and s["pc"]["vcam_name"] == "Taco Cam"


def test_rotate_accepts_auto_and_degrees():
    for v in ("auto", 0, 90, 180, 270):
        assert S.sanitize({"pc": {"rotate": v}})["pc"]["rotate"] == v


def test_nest_and_get_path():
    n = S.nest("phone.focus.mode", "manual")
    assert n == {"phone": {"focus": {"mode": "manual"}}}
    assert S.get_path(n, "phone.focus.mode") == "manual"
    assert S.get_path(n, "phone.zoom", "x") == "x"
