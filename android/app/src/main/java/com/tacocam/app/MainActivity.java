package com.tacocam.app;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.SurfaceTexture;
import android.os.BatteryManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.OrientationEventListener;
import android.view.TextureView;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * Taco Cam for Android: the phone's camera as a webcam for the Taco Cam PC program, over the USB cable.
 * Keep this screen open while streaming (Android stops the camera of apps in the background).
 */
public class MainActivity extends Activity implements CameraEngine.Listener, StreamServer.Handler {
    private static final int ASK_CAMERA = 1;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private SharedPreferences prefs;
    private String code;
    private Phone phone;
    private CameraEngine camera;
    private StreamServer server;
    private OrientationEventListener orientation;
    private boolean resumed;
    private String connection;            // null = waiting, "connected", or a short note
    private String lastFormat;

    private TextureView preview;
    private TextView status, codeText, dimText;
    private LinearLayout zoomRow;
    private View dim;

    @Override protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        setShowWhenLocked(true);           // the PC can bring Taco Cam up while the phone sits locked on its stand
        setTurnScreenOn(true);
        prefs = getSharedPreferences("tacocam", MODE_PRIVATE);
        code = prefs.getString("pair_code", null);
        if (code == null || Proto.normalize(code).length() != Proto.PAIR_CODE_LEN) {
            code = Proto.newCode();
            prefs.edit().putString("pair_code", code).apply();
        }
        writeCodeFile();

        camera = new CameraEngine(this, this);
        JSONObject savedSettings = null;
        try {
            String s = prefs.getString("settings", null);
            if (s != null) savedSettings = new JSONObject(s);
        } catch (JSONException ignored) {
        }
        phone = new Phone(camera.caps(), savedSettings);
        buildUi();
        server = new StreamServer(this);
        server.start();

        orientation = new OrientationEventListener(this) {
            @Override public void onOrientationChanged(int deg) {
                updateRotation(deg);
            }
        };
        updateRotation(0);
        ui.post(ticker);
        if (Build.VERSION.SDK_INT >= 29) {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            pm.addThermalStatusListener(getMainExecutor(), s -> {
                phone.setThermal(thermalName(s));
                server.sendState();
            });
            phone.setThermal(thermalName(pm.getCurrentThermalStatus()));
        }
    }

    /**
     * The PC reads the pairing code over the USB cable from the app's own files folder
     * (/sdcard/Android/data/com.tacocam.app/files): adb can read it, other apps on the phone can't (Android 11+).
     */
    private void writeCodeFile() {
        File dir = getExternalFilesDir(null);
        if (dir == null) return;
        try (FileOutputStream f = new FileOutputStream(new File(dir, "pairing.txt"))) {
            f.write(code.getBytes(StandardCharsets.US_ASCII));
        } catch (Exception ignored) {
        }
    }

    @Override protected void onResume() {
        super.onResume();
        resumed = true;
        phone.setActive(true);
        orientation.enable();
        if (checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            camera.start(phone.settings());
        } else {
            requestPermissions(new String[] {Manifest.permission.CAMERA}, ASK_CAMERA);
        }
        server.sendState();
        refreshUi();
    }

    @Override protected void onPause() {
        super.onPause();
        resumed = false;
        phone.setActive(false);
        orientation.disable();
        server.sendState();
        camera.stop();
    }

    @Override protected void onDestroy() {
        super.onDestroy();
        ui.removeCallbacksAndMessages(null);
        server.stop();
    }

    @Override public void onRequestPermissionsResult(int req, String[] perms, int[] results) {
        if (req == ASK_CAMERA && results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED) {
            if (resumed) camera.start(phone.settings());
        } else {
            phone.setCamera("Taco Cam needs the camera: allow it in Settings > Apps > Taco Cam > Permissions", "other");
            refreshUi();
        }
    }

    // --- state ---------------------------------------------------------------------------------------

    private final Runnable ticker = new Runnable() {
        @Override public void run() {
            Intent b = registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            if (b != null) {
                int level = b.getIntExtra(BatteryManager.EXTRA_LEVEL, -1), scale = b.getIntExtra(BatteryManager.EXTRA_SCALE, 100);
                int plugged = b.getIntExtra(BatteryManager.EXTRA_STATUS, -1);
                phone.setBattery(level >= 0 && scale > 0 ? level / (double) scale : -1,
                        plugged == BatteryManager.BATTERY_STATUS_CHARGING || plugged == BatteryManager.BATTERY_STATUS_FULL);
            }
            server.sendState();
            refreshUi();
            ui.postDelayed(this, 2000);
        }
    };

    private static String thermalName(int s) {
        switch (s) {
            case PowerManager.THERMAL_STATUS_NONE:
            case PowerManager.THERMAL_STATUS_LIGHT:
                return "nominal";
            case PowerManager.THERMAL_STATUS_MODERATE:
                return "fair";
            case PowerManager.THERMAL_STATUS_SEVERE:
                return "serious";
            default:
                return "critical";
        }
    }

    private int lastDevice = -1;

    /** rotation_hint = clockwise turn the PC must give the frame (Android's JPEG-orientation rule). */
    private void updateRotation(int deg) {
        String name;
        int dev;
        if (deg == OrientationEventListener.ORIENTATION_UNKNOWN) {
            if (lastDevice < 0) dev = 0;
            else dev = lastDevice;
            name = "flat";
        } else {
            dev = ((deg + 45) / 90 * 90) % 360;
            name = dev == 0 ? "portrait" : dev == 90 ? "landscape_port_left" : dev == 180 ? "portrait_upside_down"
                    : "landscape_port_right";
        }
        boolean changed = dev != lastDevice;
        lastDevice = dev;
        boolean front = "front".equals(phone.settings().optString("camera"));
        int sensor = camera.sensorOrientation(front ? "front" : "back");
        int hint = ((sensor + (front ? -dev : dev)) % 360 + 360) % 360;
        phone.setRotation(hint, name);
        if (changed) server.sendState();
    }

    // --- CameraEngine.Listener ------------------------------------------------------------------------

    @Override public void onEncoded(byte[] data, int length, long ptsUs, boolean keyframe, String codec, int w, int h) {
        if (!server.streaming() || !phone.sending()) return;
        String fmt = codec + w + "x" + h;
        int flags = keyframe ? Proto.FLAG_KEYFRAME : 0;
        if (lastFormat != null && !lastFormat.equals(fmt)) flags |= Proto.FLAG_FORMAT_CHANGED;
        int r = server.sendVideo(flags, ptsUs, data, length, keyframe);
        if (r == StreamServer.SENT) lastFormat = fmt;
        else if (r == StreamServer.DROPPED_WANT_KEY) camera.requestKeyframe();
    }

    @Override public void onCameraState(String error, String interrupted) {
        phone.setCamera(error, interrupted);
        server.sendState();
        if (error != null) server.sendLog(error);
        ui.post(this::refreshUi);
    }

    @Override public void onLive(JSONObject live) {
        phone.setLive(live);
    }

    // --- StreamServer.Handler -------------------------------------------------------------------------

    @Override public JSONObject hello() {
        JSONObject h = new JSONObject();
        try {
            h.put("proto", 1).put("app", "TacoCam").put("version", versionName()).put("platform", "android")
                    .put("device", deviceName()).put("android", Build.VERSION.RELEASE);
        } catch (JSONException ignored) {
        }
        return h;
    }

    @Override public JSONObject state() {
        return phone.state();
    }

    @Override public List<String> applySet(JSONObject patch) {
        List<String> notes = phone.apply(patch);
        settingsChanged();
        return notes;
    }

    @Override public void focus(double x, double y) {
        camera.focus(x, y);
    }

    @Override public void keyframe() {
        camera.requestKeyframe();
    }

    @Override public void status(String text) {
        ui.post(() -> {
            if ("connected".equals(text)) lastFormat = null;
            connection = text;
            refreshUi();
        });
    }

    @Override public String code() {
        return code;
    }

    private void settingsChanged() {
        JSONObject s = phone.settings();
        prefs.edit().putString("settings", s.toString()).apply();
        if (resumed) camera.apply(s);
        updateRotation(lastDevice < 0 ? 0 : lastDevice);
        ui.post(this::refreshUi);
    }

    private void changeFromScreen(JSONObject patch) {
        phone.apply(patch);
        settingsChanged();
        server.sendState();
    }

    // --- screen ---------------------------------------------------------------------------------------

    private String versionName() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (PackageManager.NameNotFoundException e) {
            return "?";
        }
    }

    private static String deviceName() {
        String maker = Build.MANUFACTURER == null ? "" : Build.MANUFACTURER;
        String model = Build.MODEL == null ? "Android phone" : Build.MODEL;
        if (!maker.isEmpty() && !model.toLowerCase().startsWith(maker.toLowerCase())) {
            model = Character.toUpperCase(maker.charAt(0)) + maker.substring(1) + " " + model;
        }
        return model;
    }

    private int dp(float v) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics()));
    }

    private TextView text(float sp, int color) {
        TextView t = new TextView(this);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        t.setPadding(dp(16), dp(6), dp(16), dp(6));
        return t;
    }

    private void buildUi() {
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);

        preview = new TextureView(this);
        int w = getResources().getDisplayMetrics().widthPixels;
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(w, w * 16 / 9, Gravity.CENTER);
        root.addView(preview, lp);
        preview.setSurfaceTextureListener(new TextureView.SurfaceTextureListener() {
            @Override public void onSurfaceTextureAvailable(SurfaceTexture st, int width, int height) {
                camera.setPreview(st);
            }

            @Override public void onSurfaceTextureSizeChanged(SurfaceTexture st, int width, int height) {}

            @Override public boolean onSurfaceTextureDestroyed(SurfaceTexture st) {
                camera.setPreview(null);
                return true;
            }

            @Override public void onSurfaceTextureUpdated(SurfaceTexture st) {}
        });

        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.VERTICAL);
        top.setBackgroundColor(0x99000000);
        TextView title = text(20, 0xFFFFB238);
        title.setText("Taco Cam");
        status = text(15, Color.WHITE);
        codeText = text(12, 0xFFAAAAAA);
        top.addView(title);
        top.addView(status);
        top.addView(codeText);
        root.addView(top, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.TOP));

        LinearLayout bottom = new LinearLayout(this);
        bottom.setOrientation(LinearLayout.HORIZONTAL);
        bottom.setGravity(Gravity.CENTER);
        bottom.setPadding(dp(8), dp(8), dp(8), dp(24));
        zoomRow = new LinearLayout(this);
        zoomRow.setOrientation(LinearLayout.HORIZONTAL);
        bottom.addView(zoomRow);
        Button dimBtn = new Button(this);
        dimBtn.setText("Dim");
        dimBtn.setOnClickListener(v -> changeFromScreen(json("screen", "dim")));
        bottom.addView(dimBtn);
        root.addView(bottom, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM));

        dim = new FrameLayout(this);
        dim.setBackgroundColor(Color.BLACK);
        dimText = text(14, 0xFF777777);
        dimText.setGravity(Gravity.CENTER);
        ((FrameLayout) dim).addView(dimText, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.CENTER));
        dim.setOnClickListener(v -> changeFromScreen(json("screen", "normal")));
        dim.setVisibility(View.GONE);
        root.addView(dim, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));
        setContentView(root);
    }

    private static JSONObject json(String k, Object v) {
        try {
            return new JSONObject().put(k, v);
        } catch (JSONException e) {
            return new JSONObject();
        }
    }

    private String shownZooms;

    private void refreshUi() {
        if (status == null) return;
        JSONObject st = phone.state();
        JSONObject s = st.optJSONObject("settings");
        String line;
        if (!st.isNull("error")) {
            line = "Problem: " + st.optString("error");
        } else if ("connected".equals(connection) && server.connected()) {
            JSONObject stream = st.optJSONObject("stream");
            line = "Connected to the PC (USB cable)\n" + stream.optInt("width") + "x" + stream.optInt("height") + ", "
                    + stream.optInt("fps") + " fps, " + s.optString("codec").toUpperCase() + ", zoom "
                    + String.format(java.util.Locale.US, "%.1fx", s.optDouble("zoom"));
        } else if (connection != null && !"connected".equals(connection)) {
            line = connection + "\nWaiting for the PC: plug in the USB cable and start Taco Cam on the PC.";
        } else {
            line = "Waiting for the PC: plug in the USB cable and start Taco Cam on the PC.";
        }
        status.setText(line);
        codeText.setText("Keep this screen open while you stream.  Code: " + Proto.pretty(code));

        boolean dimmed = "dim".equals(s.optString("screen"));
        dim.setVisibility(dimmed ? View.VISIBLE : View.GONE);
        dimText.setText("Taco Cam is " + (server.connected() ? "streaming" : "waiting for the PC")
                + "\nThe screen is dimmed to save battery. Tap to light it up.");
        WindowManager.LayoutParams wl = getWindow().getAttributes();
        float want = dimmed ? 0.01f : WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE;
        if (wl.screenBrightness != want) {
            wl.screenBrightness = want;
            getWindow().setAttributes(wl);
        }

        JSONObject cam = camera.caps().optJSONObject(s.optString("camera"));
        JSONArray zooms = cam == null ? null : cam.optJSONArray("lens_zooms");
        String key = String.valueOf(zooms) + s.optDouble("zoom");
        if (zooms != null && !key.equals(shownZooms)) {
            shownZooms = key;
            zoomRow.removeAllViews();
            for (int i = 0; i < zooms.length(); i++) {
                double z = zooms.optDouble(i);
                Button b = new Button(this);
                b.setText((z < 1 ? String.format(java.util.Locale.US, "%.1f", z) : String.valueOf((int) z)) + "x");
                b.setAlpha(Math.abs(z - s.optDouble("zoom")) < 0.05 ? 1f : 0.6f);
                b.setOnClickListener(v -> changeFromScreen(json("zoom", z)));
                zoomRow.addView(b);
            }
        }
    }
}
