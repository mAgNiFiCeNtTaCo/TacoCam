package com.tacocam.app;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.json.JSONObject;
import org.junit.Test;

import java.util.List;

public class PhoneTest {
    static JSONObject caps() throws Exception {
        return new JSONObject("{\"back\":{\"available\":true,\"name\":\"Back camera\",\"min_zoom\":0.5,\"max_zoom\":8,"
                + "\"lens_zooms\":[0.5,1,2],\"has_torch\":true,\"resolutions\":[\"720p\",\"1080p\"],"
                + "\"fps\":{\"720p\":[24,30,60],\"1080p\":[24,30]},\"codecs\":[\"h264\"],"
                + "\"stabilization\":[\"off\",\"standard\"]},"
                + "\"front\":{\"available\":true,\"name\":\"Front camera\",\"min_zoom\":1,\"max_zoom\":4,"
                + "\"lens_zooms\":[1],\"has_torch\":false,\"resolutions\":[\"1080p\"],\"fps\":{\"1080p\":[30]},"
                + "\"codecs\":[\"h264\",\"hevc\"],\"stabilization\":[\"off\"]}}");
    }

    @Test public void defaultsFitThePhone() throws Exception {
        Phone p = new Phone(caps(), null);
        JSONObject s = p.settings();
        assertEquals("back", s.getString("camera"));
        assertEquals("1080p", s.getString("resolution"));
        assertEquals(30, s.getInt("fps"));
        assertEquals("h264", s.getString("codec"));
    }

    @Test public void setIsClampedToWhatTheCameraCanDo() throws Exception {
        Phone p = new Phone(caps(), null);
        List<String> notes = p.apply(new JSONObject("{\"zoom\":0.3,\"fps\":60,\"codec\":\"hevc\",\"torch\":0.004,"
                + "\"bogus\":1,\"focus\":{\"mode\":\"manual\",\"nope\":2},\"exposure\":{\"iso\":400,\"bias\":5},"
                + "\"screen\":\"dim\",\"zoom_glide_s\":9}"));
        JSONObject s = p.settings();
        assertEquals(0.5, s.getDouble("zoom"), 1e-9);
        assertEquals(30, s.getInt("fps"));                 // 1080p has no 60 here: the next lower rate
        assertEquals("h264", s.getString("codec"));        // no HEVC encoder on the back camera
        assertEquals(0.01, s.getDouble("torch"), 1e-9);
        assertEquals("manual", s.getJSONObject("focus").getString("mode"));
        assertEquals(3.0, s.getJSONObject("exposure").getDouble("bias"), 1e-9);
        assertTrue(s.getJSONObject("exposure").isNull("iso"));   // ISO can't be set: manual = hold
        assertEquals("dim", s.getString("screen"));
        assertEquals(3.0, s.getDouble("zoom_glide_s"), 1e-9);
        assertTrue(notes.contains("unknown setting bogus"));
        assertTrue(notes.contains("unknown setting focus.nope"));
        assertTrue(notes.stream().anyMatch(n -> n.startsWith("codec")));
    }

    @Test public void lowerResolutionAllowsSixty() throws Exception {
        Phone p = new Phone(caps(), null);
        p.apply(new JSONObject("{\"resolution\":\"720p\",\"fps\":60}"));
        assertEquals(60, p.settings().getInt("fps"));
        p.apply(new JSONObject("{\"resolution\":\"4k\"}"));
        assertEquals("720p", p.settings().getString("resolution"));
    }

    @Test public void frontCameraHasNoTorchOrUltraWide() throws Exception {
        Phone p = new Phone(caps(), null);
        p.apply(new JSONObject("{\"camera\":\"front\",\"zoom\":0.5,\"torch\":1}"));
        JSONObject s = p.settings();
        assertEquals("front", s.getString("camera"));
        assertEquals(1.0, s.getDouble("zoom"), 1e-9);
        assertEquals(0.0, s.getDouble("torch"), 1e-9);
    }

    @Test public void stateHasTheContractKeys() throws Exception {
        Phone p = new Phone(caps(), null);
        p.setRotation(90, "portrait");
        p.setBattery(0.5, true);
        JSONObject st = p.state();
        for (String k : new String[] {"settings", "stream", "cameras", "rotation_hint", "orientation", "battery",
                "charging", "thermal", "app_active", "interrupted", "error", "live", "app_expires"}) {
            assertTrue(k, st.has(k));
        }
        assertEquals(1920, st.getJSONObject("stream").getInt("width"));
        assertEquals(90, st.getInt("rotation_hint"));
        assertTrue(st.isNull("app_expires"));
        p.setCamera(null, "other_app");
        assertFalse(p.sending());
    }

    @Test public void savedSettingsComeBack() throws Exception {
        Phone p = new Phone(caps(), new JSONObject("{\"zoom\":2,\"screen\":\"dim\",\"focus\":{\"mode\":\"manual\"}}"));
        assertEquals(2.0, p.settings().getDouble("zoom"), 1e-9);
        assertEquals("manual", p.settings().getJSONObject("focus").getString("mode"));
    }
}
