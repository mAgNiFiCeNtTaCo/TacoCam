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
