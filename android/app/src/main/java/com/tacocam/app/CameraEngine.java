package com.tacocam.app;

import android.annotation.SuppressLint;
import android.content.Context;
import android.graphics.Rect;
import android.graphics.SurfaceTexture;
import android.hardware.camera2.CameraAccessException;
import android.hardware.camera2.CameraCaptureSession;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraDevice;
import android.hardware.camera2.CameraManager;
import android.hardware.camera2.CameraMetadata;
import android.hardware.camera2.CaptureRequest;
import android.hardware.camera2.CaptureResult;
import android.hardware.camera2.TotalCaptureResult;
import android.hardware.camera2.params.MeteringRectangle;
import android.hardware.camera2.params.OutputConfiguration;
import android.hardware.camera2.params.SessionConfiguration;
import android.hardware.camera2.params.StreamConfigurationMap;
import android.media.MediaCodec;
import android.os.Handler;
import android.os.HandlerThread;
import android.util.Log;
import android.util.Range;
import android.util.Size;
import android.view.Surface;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executor;

/**
 * The phone camera (Camera2) feeding the encoder and the on-screen preview. Everything runs on one camera thread.
 * Frames go out as the sensor delivers them (landscape); the PC turns them using rotation_hint (CONTRACT section 3).
 *
 * "manual" focus / exposure / white balance mean HOLD here (as on the iPhone's combined back camera, CONTRACT
 * section 5): focus once then lock, freeze exposure, freeze colours. The caps say so (focus_lock, no *_manual).
 */
final class CameraEngine {
    interface Listener {
        void onEncoded(byte[] data, int length, long ptsUs, boolean keyframe, String codec, int width, int height);
        /** error text or null; interrupted reason ("other_app", "other") or null when the camera runs. */
        void onCameraState(String error, String interrupted);
        void onLive(JSONObject live);
    }

    static final String TAG = "TacoCam";
    static final int[][] SIZES = {{1280, 720}, {1920, 1080}, {3840, 2160}};
    static final String[] SIZE_NAMES = {"720p", "1080p", "4k"};
    static final int[] FPS = {24, 25, 30, 60};

    private final CameraManager mgr;
    private final Listener listener;
    private final HandlerThread thread = new HandlerThread("tacocam-camera");
    private final Handler handler;
    private final Executor executor;

    private final String backId, frontId;
    private final JSONObject caps;                 // {"back": {...}, "front": {...}} (CONTRACT section 5 cameras)

    private CameraDevice device;
    private String deviceId;
    private CameraCaptureSession session;
    private VideoEncoder encoder;
    private SurfaceTexture previewTexture;
    private Surface previewSurface;
    private JSONObject want;                       // settings to apply (normalised by Phone)
    private boolean running;                       // the activity is in front
    private int generation;                        // bumps on every rebuild: late callbacks of an old one are ignored
    private float zoomNow = 1f;
    private float zoomTarget = 1f;
    private MeteringRectangle[] focusRegion;
    private long focusUntil;
    private boolean triggerAf;

    CameraEngine(Context ctx, Listener listener) {
        this.mgr = (CameraManager) ctx.getSystemService(Context.CAMERA_SERVICE);
        this.listener = listener;
        thread.start();
        handler = new Handler(thread.getLooper());
        executor = handler::post;
        String[] ids = pickCameras();
        backId = ids[0];
        frontId = ids[1];
        caps = new JSONObject();
        try {
            caps.put("back", capsFor(backId, true));
            caps.put("front", capsFor(frontId, false));
        } catch (JSONException e) {
            throw new IllegalStateException(e);
        }
    }

    JSONObject caps() {
        return caps;
    }

    int sensorOrientation(String camera) {
        String id = "front".equals(camera) ? frontId : backId;
        if (id == null) return 90;
        try {
            Integer o = mgr.getCameraCharacteristics(id).get(CameraCharacteristics.SENSOR_ORIENTATION);
            return o == null ? 90 : o;
        } catch (CameraAccessException | IllegalArgumentException e) {
            return 90;
        }
    }

    // --- public, called from any thread ---------------------------------------------------------------

    void setPreview(SurfaceTexture texture) {
        handler.post(() -> {
            previewTexture = texture;
            if (running) rebuild();
        });
    }

    void start(JSONObject settings) {
        handler.post(() -> {
            running = true;
            want = settings;
            rebuild();
        });
    }

    void stop() {
        handler.post(() -> {
            running = false;
            closeAll();
        });
    }

    /** New settings: rebuilds what must change, otherwise only updates the running request. */
    void apply(JSONObject settings) {
        handler.post(() -> {
            JSONObject old = want;
            want = settings;
            if (!running) return;
            if (old == null || session == null || encoder == null || needsRebuild(old, settings)) {
                rebuild();
            } else {
                startZoomGlide();
                updateRequest();
            }
        });
    }

    void focus(double x, double y) {
        handler.post(() -> {
            CameraCharacteristics ch = chars(deviceId);
            if (ch == null) return;
            Rect array = ch.get(CameraCharacteristics.SENSOR_INFO_ACTIVE_ARRAY_SIZE);
            if (array == null) return;
            // the visible picture: the zoomed centre of the active array, cropped to the stream's 16:9
            float z = Math.max(zoomNow, 1f);
            float cw = array.width() / z, chh = array.height() / z;
            float sh = Math.min(chh, cw * 9f / 16f);
            float left = array.left + (array.width() - cw) / 2f, top = array.top + (array.height() - sh) / 2f;
            int px = Math.round(left + (float) x * cw), py = Math.round(top + (float) y * sh);
            int r = Math.max(50, Math.round(Math.min(cw, sh) / 10f));
            Rect area = new Rect(px - r, py - r, px + r, py + r);
            area.intersect(array);
            focusRegion = new MeteringRectangle[] {new MeteringRectangle(area, MeteringRectangle.METERING_WEIGHT_MAX - 1)};
            focusUntil = System.currentTimeMillis() + 10_000;
            triggerAf = true;
            updateRequest();
        });
    }

    void requestKeyframe() {
        VideoEncoder e = encoder;
        if (e != null) e.requestKeyframe();
    }

    // --- camera thread -------------------------------------------------------------------------------

    private static boolean needsRebuild(JSONObject a, JSONObject b) {
        for (String k : new String[] {"camera", "resolution", "fps", "codec", "bitrate_mbps", "stabilization"}) {
            if (!String.valueOf(a.opt(k)).equals(String.valueOf(b.opt(k)))) return true;
        }
        return false;
    }

    private void closeAll() {
        generation++;
        if (session != null) {
            try {
                session.close();
            } catch (RuntimeException ignored) {
            }
            session = null;
        }
        if (device != null) {
            device.close();
            device = null;
            deviceId = null;
        }
        if (encoder != null) {
            encoder.release();
            encoder = null;
        }
        if (previewSurface != null) {
            previewSurface.release();
            previewSurface = null;
        }
    }

    private void rebuild() {
        if (want == null) return;
        String id = "front".equals(want.optString("camera")) ? frontId : backId;
        if (id == null) id = backId != null ? backId : frontId;
        if (id == null) {
            listener.onCameraState("This phone has no camera Taco Cam can use", null);
            return;
        }
        if (session != null) {
            try {
                session.close();
            } catch (RuntimeException ignored) {
            }
            session = null;
        }
        if (encoder != null) {
            encoder.release();
            encoder = null;
        }
        if (previewSurface != null) {
            previewSurface.release();
            previewSurface = null;
        }
        generation++;
        if (device != null && id.equals(deviceId)) {
            makeSession();
            return;
        }
        if (device != null) {
            device.close();
            device = null;
        }
        open(id);
    }

    @SuppressLint("MissingPermission")
    private void open(String id) {
        final int gen = ++generation;
        try {
            mgr.openCamera(id, executor, new CameraDevice.StateCallback() {
                @Override public void onOpened(CameraDevice d) {
                    if (gen != generation || !running) {
                        d.close();
                        return;
                    }
                    device = d;
                    deviceId = id;
                    makeSession();
                }

                @Override public void onDisconnected(CameraDevice d) {
                    d.close();
                    if (device == d) {
                        device = null;
                        deviceId = null;
                    }
                    listener.onCameraState(null, "other_app");
                    retryLater();
                }

                @Override public void onError(CameraDevice d, int error) {
                    d.close();
                    if (device == d) {
                        device = null;
                        deviceId = null;
                    }
                    boolean busy = error == ERROR_CAMERA_IN_USE || error == ERROR_MAX_CAMERAS_IN_USE;
                    listener.onCameraState(busy ? null : "The camera stopped (error " + error + ")",
                            busy ? "other_app" : "other");
                    retryLater();
                }
            });
        } catch (CameraAccessException | SecurityException | IllegalArgumentException e) {
            listener.onCameraState("Can't open the camera: " + e.getMessage(), "other");
            retryLater();
        }
    }

    private void retryLater() {
        handler.postDelayed(() -> {
            if (running && device == null) rebuild();
        }, 2000);
    }

    private void makeSession() {
        final int gen = generation;
        int[] wh = sizeOf(want.optString("resolution", "1080p"));
        int fps = want.optInt("fps", 30);
        String codec = want.optString("codec", "h264");
        int bitrate = (int) Math.round(want.optDouble("bitrate_mbps", 16) * 1_000_000);
        try {
            encoder = new VideoEncoder(codec, wh[0], wh[1], fps, bitrate,
                    (data, len, pts, key) -> listener.onEncoded(data, len, pts, key, codec, wh[0], wh[1]));
        } catch (Exception e) {
            listener.onCameraState("The video encoder would not start: " + e.getMessage(), "other");
            return;
        }
        List<OutputConfiguration> outs = new ArrayList<>();
        outs.add(new OutputConfiguration(encoder.surface()));
        if (previewTexture != null) {
            previewTexture.setDefaultBufferSize(wh[0], wh[1]);
            previewSurface = new Surface(previewTexture);
            outs.add(new OutputConfiguration(previewSurface));
        }
        try {
            device.createCaptureSession(new SessionConfiguration(SessionConfiguration.SESSION_REGULAR, outs, executor,
                    new CameraCaptureSession.StateCallback() {
                        @Override public void onConfigured(CameraCaptureSession s) {
                            if (gen != generation) {
                                s.close();
                                return;
                            }
                            session = s;
                            zoomNow = zoomTarget = (float) want.optDouble("zoom", 1.0);
                            updateRequest();
                            listener.onCameraState(null, null);
                            encoder.requestKeyframe();
                        }

                        @Override public void onConfigureFailed(CameraCaptureSession s) {
                            listener.onCameraState("The camera refused " + wh[0] + "x" + wh[1] + " at " + fps
                                    + " fps", "other");
                        }
                    }));
        } catch (CameraAccessException | IllegalArgumentException | IllegalStateException e) {
            listener.onCameraState("Camera session failed: " + e.getMessage(), "other");
        }
    }

    private long glideStart;
    private float glideFrom;
    private double glideSeconds;

    private void startZoomGlide() {
        float target = (float) want.optDouble("zoom", 1.0);
        if (Math.abs(target - zoomTarget) < 1e-4) return;
        zoomTarget = target;
        glideSeconds = want.optDouble("zoom_glide_s", 0.0);
        if (glideSeconds <= 0.01) {
            zoomNow = target;
            return;
        }
        glideFrom = zoomNow;
        glideStart = System.nanoTime();
        handler.removeCallbacks(glideStep);
        handler.post(glideStep);
    }

    private final Runnable glideStep = new Runnable() {
        @Override public void run() {
            double t = (System.nanoTime() - glideStart) / 1e9 / glideSeconds;
            if (t >= 1) {
                zoomNow = zoomTarget;
            } else {   // even steps on a log scale, like the iPhone's ramp
                zoomNow = (float) Math.exp(Math.log(glideFrom) + (Math.log(zoomTarget) - Math.log(glideFrom)) * t);
                handler.postDelayed(this, 33);
            }
            updateRequest();
        }
    };

    private void updateRequest() {
        if (session == null || device == null || encoder == null || want == null) return;
        try {
            CaptureRequest.Builder b = device.createCaptureRequest(CameraDevice.TEMPLATE_RECORD);
            b.addTarget(encoder.surface());
            if (previewSurface != null) b.addTarget(previewSurface);
            CameraCharacteristics ch = chars(deviceId);
            int fps = want.optInt("fps", 30);
            Range<Integer> range = bestFpsRange(ch, fps);
            if (range != null) b.set(CaptureRequest.CONTROL_AE_TARGET_FPS_RANGE, range);
            b.set(CaptureRequest.CONTROL_MODE, CameraMetadata.CONTROL_MODE_AUTO);
            b.set(CaptureRequest.CONTROL_ZOOM_RATIO, zoomNow);

            JSONObject focus = want.optJSONObject("focus");
            boolean holdFocus = focus != null && "manual".equals(focus.optString("mode"));
            boolean regions = focusRegion != null && System.currentTimeMillis() < focusUntil;
            if (holdFocus) {
                b.set(CaptureRequest.CONTROL_AF_MODE, CameraMetadata.CONTROL_AF_MODE_AUTO);
            } else if (has(ch, CameraCharacteristics.CONTROL_AF_AVAILABLE_MODES,
                    CameraMetadata.CONTROL_AF_MODE_CONTINUOUS_VIDEO)) {
                b.set(CaptureRequest.CONTROL_AF_MODE, CameraMetadata.CONTROL_AF_MODE_CONTINUOUS_VIDEO);
            }
            if (regions) {
                b.set(CaptureRequest.CONTROL_AF_REGIONS, focusRegion);
                b.set(CaptureRequest.CONTROL_AE_REGIONS, focusRegion);
            }

            JSONObject exp = want.optJSONObject("exposure");
            boolean holdExposure = exp != null && "manual".equals(exp.optString("mode"));
            b.set(CaptureRequest.CONTROL_AE_LOCK, holdExposure);
            Range<Integer> comp = ch.get(CameraCharacteristics.CONTROL_AE_COMPENSATION_RANGE);
            android.util.Rational step = ch.get(CameraCharacteristics.CONTROL_AE_COMPENSATION_STEP);
            if (comp != null && step != null && step.floatValue() > 0 && exp != null) {
                int steps = Math.round((float) exp.optDouble("bias", 0) / step.floatValue());
                b.set(CaptureRequest.CONTROL_AE_EXPOSURE_COMPENSATION, comp.clamp(steps));
            }
            String flicker = want.optString("anti_flicker", "off");
            b.set(CaptureRequest.CONTROL_AE_ANTIBANDING_MODE, "60hz".equals(flicker)
                    ? CameraMetadata.CONTROL_AE_ANTIBANDING_MODE_60HZ : "50hz".equals(flicker)
                    ? CameraMetadata.CONTROL_AE_ANTIBANDING_MODE_50HZ : CameraMetadata.CONTROL_AE_ANTIBANDING_MODE_AUTO);

            JSONObject wb = want.optJSONObject("white_balance");
            b.set(CaptureRequest.CONTROL_AWB_LOCK, wb != null && "manual".equals(wb.optString("mode")));

            boolean torch = want.optDouble("torch", 0) > 0;
            b.set(CaptureRequest.FLASH_MODE, torch ? CameraMetadata.FLASH_MODE_TORCH : CameraMetadata.FLASH_MODE_OFF);
            b.set(CaptureRequest.CONTROL_VIDEO_STABILIZATION_MODE, "off".equals(want.optString("stabilization", "off"))
                    ? CameraMetadata.CONTROL_VIDEO_STABILIZATION_MODE_OFF
                    : CameraMetadata.CONTROL_VIDEO_STABILIZATION_MODE_ON);

            session.setRepeatingRequest(b.build(), liveCallback, handler);
            if (triggerAf || (holdFocus && !heldFocus)) {
                b.set(CaptureRequest.CONTROL_AF_TRIGGER, CameraMetadata.CONTROL_AF_TRIGGER_START);
                session.capture(b.build(), null, handler);
                triggerAf = false;
            }
            heldFocus = holdFocus;
        } catch (CameraAccessException | IllegalStateException | IllegalArgumentException e) {
            Log.w(TAG, "request: " + e);
        }
    }

    private boolean heldFocus;
    private long lastLive;

    private final CameraCaptureSession.CaptureCallback liveCallback = new CameraCaptureSession.CaptureCallback() {
        @Override public void onCaptureCompleted(CameraCaptureSession s, CaptureRequest r, TotalCaptureResult res) {
            long now = System.currentTimeMillis();
            if (now - lastLive < 1000) return;
            lastLive = now;
            try {
                JSONObject live = new JSONObject();
                Float dist = res.get(CaptureResult.LENS_FOCUS_DISTANCE);
                Float min = chars(deviceId) == null ? null
                        : chars(deviceId).get(CameraCharacteristics.LENS_INFO_MINIMUM_FOCUS_DISTANCE);
                // lens_position 0..1 like the iPhone: 0 = closest, 1 = far (diopters 0 = infinity)
                if (dist != null && min != null && min > 0) live.put("lens_position", 1.0 - Math.min(1.0, dist / min));
                Integer iso = res.get(CaptureResult.SENSOR_SENSITIVITY);
                if (iso != null) live.put("iso", (double) iso);
                Long exposure = res.get(CaptureResult.SENSOR_EXPOSURE_TIME);
                if (exposure != null) live.put("shutter_s", exposure / 1e9);
                live.put("temperature", 5000);
                live.put("tint", 0);
                listener.onLive(live);
            } catch (JSONException ignored) {
            }
        }
    };

    // --- capabilities ---------------------------------------------------------------------------------

    private CameraCharacteristics chars(String id) {
        if (id == null) return null;
        try {
            return mgr.getCameraCharacteristics(id);
        } catch (CameraAccessException | IllegalArgumentException e) {
            return null;
        }
    }

    private static boolean has(CameraCharacteristics ch, CameraCharacteristics.Key<int[]> key, int value) {
        int[] all = ch == null ? null : ch.get(key);
        if (all == null) return false;
        for (int v : all) if (v == value) return true;
        return false;
    }

    /** [back id, front id]: per side the camera that zooms out furthest (the one holding the ultra-wide). */
    private String[] pickCameras() {
        String back = null, front = null;
        float backMin = Float.MAX_VALUE, frontMin = Float.MAX_VALUE;
        try {
            for (String id : mgr.getCameraIdList()) {
                CameraCharacteristics ch = mgr.getCameraCharacteristics(id);
                Integer facing = ch.get(CameraCharacteristics.LENS_FACING);
                if (!has(ch, CameraCharacteristics.REQUEST_AVAILABLE_CAPABILITIES,
                        CameraMetadata.REQUEST_AVAILABLE_CAPABILITIES_BACKWARD_COMPATIBLE)) continue;
                Range<Float> z = ch.get(CameraCharacteristics.CONTROL_ZOOM_RATIO_RANGE);
                float min = z == null ? 1f : z.getLower();
                if (facing != null && facing == CameraMetadata.LENS_FACING_BACK && min < backMin) {
                    back = id;
                    backMin = min;
                } else if (facing != null && facing == CameraMetadata.LENS_FACING_FRONT && min < frontMin) {
                    front = id;
                    frontMin = min;
                }
            }
        } catch (CameraAccessException e) {
            Log.w(TAG, "camera list: " + e);
        }
        return new String[] {back, front};
    }

    static int[] sizeOf(String name) {
        for (int i = 0; i < SIZE_NAMES.length; i++) if (SIZE_NAMES[i].equals(name)) return SIZES[i];
        return SIZES[1];
    }

    private static Range<Integer> bestFpsRange(CameraCharacteristics ch, int fps) {
        Range<Integer>[] ranges = ch == null ? null : ch.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES);
        if (ranges == null) return null;
        Range<Integer> best = null;
        for (Range<Integer> r : ranges) {
            if (r.getUpper() != fps) continue;
            if (best == null || r.getLower() > best.getLower()) best = r;   // steadiest: [fps, fps] first
        }
        return best;
    }

    private JSONObject capsFor(String id, boolean back) throws JSONException {
        JSONObject c = new JSONObject();
        CameraCharacteristics ch = chars(id);
        c.put("available", ch != null);
        c.put("name", back ? "Back camera" : "Front camera");
        Range<Float> z = ch == null ? null : ch.get(CameraCharacteristics.CONTROL_ZOOM_RATIO_RANGE);
        float min = z == null ? 1f : z.getLower(), max = z == null ? 1f : z.getUpper();
        c.put("min_zoom", round(min));
        c.put("max_zoom", round(max));
        JSONArray lenses = new JSONArray();
        if (min < 0.95f) lenses.put(round(min));
        lenses.put(1.0);
        if (max >= 2f && back) lenses.put(2.0);
        c.put("lens_zooms", lenses);
        Boolean flash = ch == null ? null : ch.get(CameraCharacteristics.FLASH_INFO_AVAILABLE);
        c.put("has_torch", flash != null && flash);

        JSONArray resolutions = new JSONArray();
        JSONObject fpsBy = new JSONObject();
        StreamConfigurationMap map = ch == null ? null : ch.get(CameraCharacteristics.SCALER_STREAM_CONFIGURATION_MAP);
        Range<Integer>[] ranges = ch == null ? null : ch.get(CameraCharacteristics.CONTROL_AE_AVAILABLE_TARGET_FPS_RANGES);
        if (map != null) {
            Size[] sizes = map.getOutputSizes(MediaCodec.class);
            for (int i = 0; i < SIZES.length; i++) {
                Size want = new Size(SIZES[i][0], SIZES[i][1]);
                boolean ok = false;
                if (sizes != null) for (Size s : sizes) if (s.equals(want)) ok = true;
                if (!ok || !VideoEncoder.supports("h264", want.getWidth(), want.getHeight())) continue;
                long minFrame = map.getOutputMinFrameDuration(MediaCodec.class, want);
                JSONArray list = new JSONArray();
                for (int f : FPS) {
                    boolean range = false;
                    if (ranges != null) for (Range<Integer> r : ranges) if (r.getUpper() == f) range = true;
                    if (range && (minFrame <= 0 || minFrame <= 1_000_000_000L / f + 1000)) list.put(f);
                }
                if (list.length() == 0) continue;
                resolutions.put(SIZE_NAMES[i]);
                fpsBy.put(SIZE_NAMES[i], list);
            }
        }
        c.put("resolutions", resolutions);
        c.put("fps", fpsBy);
        JSONArray codecs = new JSONArray().put("h264");
        if (VideoEncoder.supports("hevc", 1920, 1080)) codecs.put("hevc");
        c.put("codecs", codecs);

        Range<Integer> iso = ch == null ? null : ch.get(CameraCharacteristics.SENSOR_INFO_SENSITIVITY_RANGE);
        c.put("iso_range", new JSONArray().put(iso == null ? 50 : iso.getLower()).put(iso == null ? 3200 : iso.getUpper()));
        Range<Long> exp = ch == null ? null : ch.get(CameraCharacteristics.SENSOR_INFO_EXPOSURE_TIME_RANGE);
        c.put("shutter_range_s", new JSONArray().put(exp == null ? 0.0001 : exp.getLower() / 1e9)
                .put(exp == null ? 0.5 : exp.getUpper() / 1e9));
        c.put("focus_manual", false);
        c.put("focus_lock", true);
        c.put("exposure_manual", false);
        c.put("wb_manual", false);
        c.put("anti_flicker", true);
        c.put("hdr", false);
        JSONArray stab = new JSONArray().put("off");
        if (has(ch, CameraCharacteristics.CONTROL_AVAILABLE_VIDEO_STABILIZATION_MODES,
                CameraMetadata.CONTROL_VIDEO_STABILIZATION_MODE_ON)) stab.put("standard");
        c.put("stabilization", stab);
        return c;
    }

    private static double round(float v) {
        return Math.round(v * 100) / 100.0;
    }
}
