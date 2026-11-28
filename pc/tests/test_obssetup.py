"""One-click OBS setup (obssetup.py) on a made-up OBS folder: never the real %APPDATA%\\obs-studio."""
import json

import pytest

from tacocam import obssetup as O


@pytest.fixture
def obs(tmp_path):
    d = tmp_path / "obs-studio"
    (d / "basic" / "profiles" / "Untitled").mkdir(parents=True)
    (d / "basic" / "scenes").mkdir(parents=True)
    (d / "user.ini").write_text("[General]\nInfo=1\n\n[Basic]\nProfile=Untitled\nProfileDir=Untitled\n"
                                "SceneCollection=Untitled\nSceneCollectionFile=Untitled.json\n", encoding="utf-8")
    return d


def test_writes_profile_collection_and_switches(obs):
    res = O.setup(obs, check_running=False)
    prof = obs / "basic" / "profiles" / "Taco_Cam_Whatnot"
    ini = (prof / "basic.ini").read_text(encoding="utf-8")
    for line in ("Name=Taco Cam Whatnot", "BaseCX=1080", "BaseCY=1920", "OutputCX=1080", "OutputCY=1920",
                 "FPSCommon=30", "Encoder=obs_x264", "AudioEncoder=ffmpeg_opus", "Mode=Advanced"):
        assert line in ini
    assert json.loads((prof / "streamEncoder.json").read_text()) == O.STREAM_ENCODER
    assert json.loads((prof / "service.json").read_text()) == {"type": "whip_custom", "settings": {}}
    col = json.loads((obs / "basic" / "scenes" / "Taco_Cam_Whatnot.json").read_text(encoding="utf-8"))
    cam = next(s for s in col["sources"] if s["name"] == "Taco Cam")
    assert cam["id"] == "dshow_input" and cam["settings"]["video_device_id"] == "Taco Cam:foo#3Abar"
    live = next(s for s in col["sources"] if s["name"] == "Live")
    item = next(i for i in live["settings"]["items"] if i["name"] == "Taco Cam")
    assert item["rot"] == 90.0 and item["pos"] == {"x": 1080.0, "y": 0.0} and item["scale"] == {"x": 1.0, "y": 1.0}
    assert item["pos_rel"] == {"x": 0.5625, "y": -1.0} and item["source_uuid"] == cam["uuid"]
    user = (obs / "user.ini").read_text(encoding="utf-8")
    assert "Profile=Taco Cam Whatnot" in user and "SceneCollectionFile=Taco_Cam_Whatnot.json" in user
    assert "[General]\nInfo=1" in user                              # the rest of the file is kept
    assert (obs / "user.ini.bak-tacocam").exists()
    assert res["websocket_new"] and len(res["websocket_password"]) == 16 and res["websocket_port"] == 4455
    ws = json.loads((obs / "plugin_config" / "obs-websocket" / "config.json").read_text())
    assert ws["server_enabled"] and ws["auth_required"] and ws["server_password"] == res["websocket_password"]


def test_existing_websocket_and_service_are_kept(obs):
    ws = obs / "plugin_config" / "obs-websocket"
    ws.mkdir(parents=True)
    (ws / "config.json").write_text(json.dumps({"server_enabled": True, "server_port": 4466, "auth_required": True,
                                                "server_password": "theirs"}))
    prof = obs / "basic" / "profiles" / "Taco_Cam_Whatnot"
    prof.mkdir(parents=True)
    (prof / "service.json").write_text('{"type":"whip_custom","settings":{"server":"kept"}}')
    res = O.setup(obs, check_running=False)
    assert res["websocket_new"] is False and res["websocket_password"] == "theirs" and res["websocket_port"] == 4466
    assert "kept" in (prof / "service.json").read_text()
    O.setup(obs, check_running=False)                               # running it twice is fine
    assert (obs / "basic" / "scenes" / "Taco_Cam_Whatnot.json.bak-tacocam").exists()


def test_obs_never_opened(tmp_path):
    with pytest.raises(O.SetupProblem, match="open OBS once"):
        O.setup(tmp_path / "nothing", check_running=False)


def test_obs_open_is_refused(obs, monkeypatch):
    monkeypatch.setattr(O, "obs_running", lambda: True)
    with pytest.raises(O.SetupProblem, match="close OBS first"):
        O.setup(obs)


def test_set_ini_adds_and_replaces(tmp_path):
    p = tmp_path / "a.ini"
    p.write_text("[A]\nx=1\r\n", encoding="utf-8")
    O.set_ini(p, "A", {"x": 2, "y": 3})
    O.set_ini(p, "B", {"z": 4})
    text = p.read_text(encoding="utf-8")
    assert "x=2" in text and "y=3" in text and "[B]" in text and "z=4" in text and "x=1" not in text


X264 = {"rate_control": "CBR", "bitrate": 3500, "keyint_sec": 2, "preset": "veryfast", "tune": "zerolatency",
        "x264opts": "bframes=0"}
NVENC = {"rate_control": "CBR", "bitrate": 3500, "keyint_sec": 2, "preset2": "p5", "tune": "hq", "multipass": "qres",
         "profile": "main", "bf": 0, "lookahead": False, "psycho_aq": True}


def _prof(obs):
    return obs / "basic" / "profiles" / "Taco_Cam_Whatnot"


def test_x264_choice_writes_the_whatnot_setup(obs):
    res = O.setup(obs, check_running=False, encoder="x264")
    assert res["encoder"] == "x264"
    assert json.loads((_prof(obs) / "streamEncoder.json").read_text()) == X264
    assert O.get_ini(_prof(obs) / "basic.ini", "AdvOut", "Encoder") == "obs_x264"


def test_nvenc_choice_writes_the_nvidia_setup(obs, monkeypatch):
    monkeypatch.setattr(O, "has_nvidia", lambda: True)
    res = O.setup(obs, check_running=False, encoder="nvenc")
    assert res["encoder"] == "nvenc"
    assert json.loads((_prof(obs) / "streamEncoder.json").read_text()) == NVENC
    ini = _prof(obs) / "basic.ini"
    assert O.get_ini(ini, "AdvOut", "Encoder") == "obs_nvenc_h264_tex"
    assert O.get_ini(ini, "AdvOut", "AudioEncoder") == "ffmpeg_opus" and O.get_ini(ini, "Output", "Mode") == "Advanced"


def test_nvenc_needs_an_nvidia_card(obs):
    with pytest.raises(O.SetupProblem, match="NVIDIA graphics card"):
        O.setup(obs, check_running=False, encoder="nvenc")
    assert not _prof(obs).exists()                              # nothing written
    with pytest.raises(ValueError):
        O.setup(obs, check_running=False, encoder="av1")


def _whatnot_profile(obs, mode="Advanced"):
    """A profile like the one Whatnot's "Update Profile" makes, made the active one."""
    prof = obs / "basic" / "profiles" / "Whatnot_Live__Recommended_"
    prof.mkdir(parents=True)
    (prof / "basic.ini").write_text("[General]\nName=Whatnot Live (Recommended)\n\n[Output]\nMode=%s\n\n"
                                    "[AdvOut]\nEncoder=obs_x264\nAudioEncoder=ffmpeg_opus\n" % mode, encoding="utf-8")
    (prof / "streamEncoder.json").write_text(json.dumps(X264), encoding="utf-8")
    (prof / "service.json").write_text('{"type":"whip_custom","settings":{"bearer_token":"SECRET"}}', encoding="utf-8")
    O.set_ini(obs / "user.ini", "Basic", {"Profile": "Whatnot Live (Recommended)",
                                          "ProfileDir": "Whatnot_Live__Recommended_"})
    return prof


def test_reapply_nvenc_on_whatnots_profile(obs, monkeypatch):
    monkeypatch.setattr(O, "has_nvidia", lambda: True)
    prof = _whatnot_profile(obs)
    service_before = (prof / "service.json").read_bytes()
    assert O.apply_encoder("nvenc", obs, check_running=False) == ("Whatnot Live (Recommended)", 3500)
    assert json.loads((prof / "streamEncoder.json").read_text()) == NVENC
    assert O.get_ini(prof / "basic.ini", "AdvOut", "Encoder") == "obs_nvenc_h264_tex"
    assert O.get_ini(prof / "basic.ini", "AdvOut", "AudioEncoder") == "ffmpeg_opus"     # the rest is kept
    assert json.loads((prof / "streamEncoder.json.bak-tacocam").read_text()) == X264    # backups
    assert "Encoder=obs_x264" in (prof / "basic.ini.bak-tacocam").read_text(encoding="utf-8")
    assert (prof / "service.json").read_bytes() == service_before                       # stream key untouched
    assert not (prof / "service.json.bak-tacocam").exists()


def test_reapply_refuses_while_obs_runs_and_writes_nothing(obs, monkeypatch):
    monkeypatch.setattr(O, "has_nvidia", lambda: True)
    monkeypatch.setattr(O, "obs_running", lambda: True)
    prof = _whatnot_profile(obs)
    with pytest.raises(O.SetupProblem, match="close OBS first"):
        O.apply_encoder("nvenc", obs)
    with pytest.raises(O.SetupProblem, match="close OBS first"):
        O.setup(obs, encoder="nvenc")
    assert json.loads((prof / "streamEncoder.json").read_text()) == X264
    assert not (prof / "basic.ini.bak-tacocam").exists() and not _prof(obs).exists()


# What Whatnot's "Update Profile" writes (checked on the user's PC, 2026-11-28): Simple output mode, x264.
WHATNOT_SIMPLE = """[General]
Name=Whatnot Live (Recommended)

[Output]
Mode=Simple
Reconnect=true

[SimpleOutput]
VBitrate=3000
ABitrate=128
UseAdvanced=true
Preset=veryfast
NVENCPreset2=p5
StreamAudioEncoder=opus
StreamEncoder=x264
x264Settings=keyint=60 tune=zerolatency profile=main scenecut=0

[AdvOut]
ApplyServiceSettings=true
TrackIndex=1
Encoder=obs_x264
RecEncoder=none
Track1Bitrate=160
"""


def test_reapply_moves_a_simple_profile_to_advanced(obs, monkeypatch):
    prof = _whatnot_profile(obs, mode="Simple")
    (prof / "basic.ini").write_text(WHATNOT_SIMPLE, encoding="utf-8")
    service_before = (prof / "service.json").read_bytes()
    with pytest.raises(O.SetupProblem, match="NVIDIA graphics card"):
        O.apply_encoder("nvenc", obs, check_running=False)
    monkeypatch.setattr(O, "has_nvidia", lambda: True)
    assert O.apply_encoder("nvenc", obs, check_running=False) == ("Whatnot Live (Recommended)", 3000)
    ini = prof / "basic.ini"
    assert O.get_ini(ini, "Output", "Mode") == "Advanced"
    assert O.get_ini(ini, "AdvOut", "Encoder") == "obs_nvenc_h264_tex"
    assert O.get_ini(ini, "AdvOut", "AudioEncoder") == "ffmpeg_opus"                   # WHIP needs Opus
    assert O.get_ini(ini, "AdvOut", "Track1Bitrate") == "128" and O.get_ini(ini, "AdvOut", "TrackIndex") == "1"
    assert O.get_ini(ini, "AdvOut", "ApplyServiceSettings") == "true"
    assert O.get_ini(ini, "AdvOut", "RecEncoder") == "none"                             # the rest is kept
    assert O.get_ini(ini, "SimpleOutput", "VBitrate") == "3000"
    assert json.loads((prof / "streamEncoder.json").read_text()) == dict(NVENC, bitrate=3000)   # Whatnot's bitrate
    assert "Mode=Simple" in (prof / "basic.ini.bak-tacocam").read_text(encoding="utf-8")
    assert (prof / "service.json").read_bytes() == service_before


def test_reapply_keeps_bitrate_within_whatnots_limit(obs, monkeypatch):
    monkeypatch.setattr(O, "has_nvidia", lambda: True)
    prof = _whatnot_profile(obs, mode="Simple")
    (prof / "basic.ini").write_text(WHATNOT_SIMPLE.replace("VBitrate=3000", "VBitrate=20000"), encoding="utf-8")
    assert O.apply_encoder("nvenc", obs, check_running=False)[1] == 3500
    assert json.loads((prof / "streamEncoder.json").read_text())["bitrate"] == 3500


def test_has_nvidia_needs_the_card_and_its_encoder(monkeypatch, tmp_path):
    monkeypatch.undo()                                          # the real function, with made-up inputs
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    (tmp_path / "System32").mkdir()
    monkeypatch.setattr(O, "gpu_names", lambda: ["AMD Radeon RX 7800 XT"])
    assert O.has_nvidia() is False
    monkeypatch.setattr(O, "gpu_names", lambda: ["NVIDIA GeForce RTX 3080 Ti"])
    assert O.has_nvidia() is False                              # driver's encoder library missing
    (tmp_path / "System32" / "nvEncodeAPI64.dll").write_bytes(b"")
    assert O.has_nvidia() is True
