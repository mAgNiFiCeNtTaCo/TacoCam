package com.tacocam.app;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

/**
 * The phone's settings and state (CONTRACT sections 4 and 5). SET patches are merged and clamped to what this phone's
 * cameras can do (the same rules as pc/tools/fake_phone.py), and STATE is built here. Thread-safe.
 */
final class Phone {
    static final String[] NESTED = {"focus", "exposure", "white_balance"};

    private final JSONObject caps;
    private JSONObject settings;
    // state (set by the activity)
    private int rotationHint = 90;
    private String orientation = "portrait";
    private double battery = -1;
    private boolean charging;
    private String thermal = "nominal";
    private boolean appActive = true;
    private String interrupted;
    private String error;
    private JSONObject live;

    Phone(JSONObject caps, JSONObject saved) {
        this.caps = caps;
        List<String> notes = new ArrayList<>();
        this.settings = normalize(merge(defaults(), saved), defaultsFor(caps), caps, notes);
    }

    static JSONObject defaults() {
        try {
            return new JSONObject("{\"camera\":\"back\",\"zoom\":1.0,\"zoom_glide_s\":0.0,\"resolution\":\"1080p\","
                    + "\"fps\":30,\"codec\":\"h264\",\"bitrate_mbps\":16,"
                    + "\"focus\":{\"mode\":\"auto\",\"position\":0.5},"
                    + "\"exposure\":{\"mode\":\"auto\",\"bias\":0.0,\"iso\":null,\"shutter_s\":null},"
                    + "\"white_balance\":{\"mode\":\"auto\",\"temperature\":5000,\"tint\":0},"
                    + "\"torch\":0.0,\"stabilization\":\"off\",\"hdr\":false,\"screen\":\"normal\",\"anti_flicker\":\"off\"}");
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
    }

    /** Defaults already fitted to this phone (the starting point every clamp falls back to). */
    private static JSONObject defaultsFor(JSONObject caps) {
        JSONObject d = defaults();
        JSONObject back = caps.optJSONObject("back");
        if (back == null || !back.optBoolean("available")) {
            try {
                d.put("camera", "front");
            } catch (JSONException ignored) {
            }
        }
        return d;
    }

    synchronized JSONObject settings() {
        return copy(settings);
    }

    /** Applies a SET patch. Returns notes about values that were ignored or clamped. */
    synchronized List<String> apply(JSONObject patch) {
        List<String> notes = new ArrayList<>();
        JSONObject merged = copy(settings);
        Iterator<String> keys = patch.keys();
        while (keys.hasNext()) {
            String k = keys.next();
            Object v = patch.opt(k);
            try {
                if (isNested(k)) {
                    if (!(v instanceof JSONObject)) {
                        notes.add(k + " must be an object");
                        continue;
                    }
                    JSONObject into = merged.getJSONObject(k);
                    Iterator<String> subs = ((JSONObject) v).keys();
                    while (subs.hasNext()) {
                        String s = subs.next();
                        if (into.has(s)) into.put(s, ((JSONObject) v).opt(s));
                        else notes.add("unknown setting " + k + "." + s);
                    }
                } else if (merged.has(k)) {
                    merged.put(k, v);
                } else {
                    notes.add("unknown setting " + k);
                }
            } catch (JSONException e) {
                notes.add(k + ": " + e.getMessage());
            }
        }
        settings = normalize(merged, settings, caps, notes);
        return notes;
    }

    // --- state --------------------------------------------------------------------------------------

    synchronized void setRotation(int hint, String orientation) {
        this.rotationHint = hint;
        this.orientation = orientation;
    }

    synchronized void setBattery(double level, boolean charging) {
        this.battery = level;
        this.charging = charging;
    }

    synchronized void setThermal(String t) {
        thermal = t;
    }

    synchronized void setActive(boolean active) {
        appActive = active;
    }

    synchronized void setCamera(String error, String interrupted) {
        this.error = error;
        this.interrupted = interrupted;
    }

    synchronized void setLive(JSONObject live) {
        this.live = live;
    }

    synchronized boolean sending() {
        return appActive && interrupted == null;
    }

    synchronized String interrupted() {
        return interrupted;
    }

    synchronized JSONObject state() {
        JSONObject s = new JSONObject();
        try {
            s.put("settings", copy(settings));
            int[] wh = CameraEngine.sizeOf(settings.optString("resolution"));
            s.put("stream", new JSONObject().put("codec", settings.optString("codec")).put("width", wh[0])
                    .put("height", wh[1]).put("fps", settings.optInt("fps")));
            s.put("cameras", caps);
            s.put("rotation_hint", rotationHint);
            s.put("orientation", orientation);
            s.put("battery", battery < 0 ? JSONObject.NULL : Math.round(battery * 1000) / 1000.0);
            s.put("charging", charging);
            s.put("thermal", thermal);
            s.put("app_active", appActive);
            s.put("interrupted", interrupted == null ? JSONObject.NULL : interrupted);
            s.put("error", error == null ? JSONObject.NULL : error);
            s.put("live", live == null ? JSONObject.NULL : live);
            s.put("app_expires", JSONObject.NULL);      // installed for good, unlike a free-Apple-ID iPhone copy
        } catch (JSONException ignored) {
        }
        return s;
    }

    // --- clamping (same rules as fake_phone.normalize) --------------------------------------------------

    private static boolean isNested(String k) {
        for (String n : NESTED) if (n.equals(k)) return true;
        return false;
    }

    static JSONObject copy(JSONObject o) {
        try {
            return new JSONObject(o.toString());
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
    }

    private static JSONObject merge(JSONObject base, JSONObject over) {
        JSONObject out = copy(base);
        if (over == null) return out;
        Iterator<String> keys = over.keys();
        while (keys.hasNext()) {
            String k = keys.next();
            try {
                if (isNested(k) && over.opt(k) instanceof JSONObject) {
                    JSONObject into = out.getJSONObject(k);
                    JSONObject src = over.getJSONObject(k);
                    Iterator<String> subs = src.keys();
                    while (subs.hasNext()) {
                        String s = subs.next();
                        if (into.has(s)) into.put(s, src.opt(s));
                    }
                } else if (out.has(k)) {
                    out.put(k, over.opt(k));
                }
            } catch (JSONException ignored) {
            }
        }
        return out;
    }

    private static boolean isNumber(Object v) {
        return v instanceof Number && !Double.isNaN(((Number) v).doubleValue())
                && !Double.isInfinite(((Number) v).doubleValue());
    }

    private static double clamp(double v, double lo, double hi) {
        return Math.min(Math.max(v, lo), hi);
    }

    private static boolean contains(JSONArray a, Object v) {
        if (a == null) return false;
        for (int i = 0; i < a.length(); i++) if (String.valueOf(a.opt(i)).equals(String.valueOf(v))) return true;
        return false;
    }

    private static double round(double v, int places) {
        double p = Math.pow(10, places);
        return Math.round(v * p) / p;
    }

    /** s = merged wish, prev = settings in effect: every value that can't be used keeps prev's value (and a note). */
    static JSONObject normalize(JSONObject s, JSONObject prev, JSONObject caps, List<String> notes) {
        JSONObject out = copy(prev);
        try {
            String camera = s.optString("camera");
            JSONObject cam = caps.optJSONObject(camera);
            if (cam != null && cam.optBoolean("available")) out.put("camera", camera);
            else notes.add("camera: " + camera + " is not available");
            cam = caps.optJSONObject(out.optString("camera"));
            if (cam == null) cam = new JSONObject();
            double minZ = cam.optDouble("min_zoom", 1), maxZ = cam.optDouble("max_zoom", 1);

            if (isNumber(s.opt("zoom"))) out.put("zoom", round(clamp(s.optDouble("zoom"), minZ, maxZ), 3));
            else notes.add("zoom: not a number");
            out.put("zoom", clamp(out.optDouble("zoom", 1), minZ, maxZ));
            if (isNumber(s.opt("zoom_glide_s"))) out.put("zoom_glide_s", round(clamp(s.optDouble("zoom_glide_s"), 0, 3), 3));

            JSONArray res = cam.optJSONArray("resolutions");
            if (contains(res, s.opt("resolution"))) out.put("resolution", s.optString("resolution"));
            else notes.add("resolution: " + s.opt("resolution") + " is not available");
            if (!contains(res, out.opt("resolution")) && res != null && res.length() > 0) {
                out.put("resolution", contains(res, "1080p") ? "1080p" : res.optString(0));
            }
            JSONArray fpsList = cam.optJSONObject("fps") == null ? null
                    : cam.optJSONObject("fps").optJSONArray(out.optString("resolution"));
            if (fpsList != null && fpsList.length() > 0) {
                int want = isNumber(s.opt("fps")) ? (int) s.optDouble("fps") : out.optInt("fps", 30);
                int best = -1, lowest = Integer.MAX_VALUE;
                for (int i = 0; i < fpsList.length(); i++) {
                    int f = fpsList.optInt(i);
                    lowest = Math.min(lowest, f);
                    if (f <= want && f > best) best = f;
                }
                out.put("fps", best > 0 ? best : lowest);
            }
            if (contains(cam.optJSONArray("codecs"), s.opt("codec"))) out.put("codec", s.optString("codec"));
            else {
                notes.add("codec: " + s.opt("codec") + " is not available on this phone");
                if (!contains(cam.optJSONArray("codecs"), out.opt("codec"))) out.put("codec", "h264");
            }
            if (isNumber(s.opt("bitrate_mbps"))) out.put("bitrate_mbps", round(clamp(s.optDouble("bitrate_mbps"), 2, 80), 2));

            JSONObject focus = s.optJSONObject("focus"), ofocus = out.getJSONObject("focus");
            if (focus != null) {
                String mode = focus.optString("mode");
                if ("auto".equals(mode) || "manual".equals(mode)) ofocus.put("mode", mode);
                if (isNumber(focus.opt("position"))) ofocus.put("position", round(clamp(focus.optDouble("position"), 0, 1), 4));
            }
            JSONObject exp = s.optJSONObject("exposure"), oexp = out.getJSONObject("exposure");
            if (exp != null) {
                String mode = exp.optString("mode");
                if ("auto".equals(mode) || "manual".equals(mode)) oexp.put("mode", mode);
                if (isNumber(exp.opt("bias"))) oexp.put("bias", round(clamp(exp.optDouble("bias"), -3, 3), 3));
                // ISO / shutter can't be set on this phone's camera: "manual" holds the exposure in use
                oexp.put("iso", JSONObject.NULL);
                oexp.put("shutter_s", JSONObject.NULL);
            }
            JSONObject wb = s.optJSONObject("white_balance"), owb = out.getJSONObject("white_balance");
            if (wb != null) {
                String mode = wb.optString("mode");
                if ("auto".equals(mode) || "manual".equals(mode)) owb.put("mode", mode);
                if (isNumber(wb.opt("temperature"))) owb.put("temperature", (int) Math.round(clamp(wb.optDouble("temperature"), 2500, 8000)));
                if (isNumber(wb.opt("tint"))) owb.put("tint", (int) Math.round(clamp(wb.optDouble("tint"), -150, 150)));
            }
            if (isNumber(s.opt("torch"))) {
                double t = clamp(s.optDouble("torch"), 0, 1);
                out.put("torch", !cam.optBoolean("has_torch") || t <= 0 ? 0.0 : round(Math.max(t, 0.01), 3));
            }
            if (!cam.optBoolean("has_torch")) out.put("torch", 0.0);
            JSONArray stab = cam.optJSONArray("stabilization");
            if (contains(stab, s.opt("stabilization"))) out.put("stabilization", s.optString("stabilization"));
            if (!contains(stab, out.opt("stabilization"))) out.put("stabilization", "off");
            out.put("hdr", false);
            String screen = s.optString("screen");
            if ("normal".equals(screen) || "dim".equals(screen)) out.put("screen", screen);
            String flick = s.optString("anti_flicker");
            if ("off".equals(flick) || "60hz".equals(flick) || "50hz".equals(flick)) out.put("anti_flicker", flick);
        } catch (JSONException e) {
            notes.add("settings: " + e.getMessage());
        }
        return out;
    }
}
