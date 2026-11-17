package com.tacocam.app;

import android.media.MediaCodec;
import android.media.MediaCodecInfo;
import android.media.MediaCodecList;
import android.media.MediaFormat;
import android.os.Bundle;
import android.util.Log;
import android.view.Surface;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;

/**
 * Hardware H.264 / HEVC encoder fed by the camera through a Surface. Output is Annex-B (start codes), no B-frames,
 * and every keyframe carries the parameter sets in front (CONTRACT section 2, VIDEO flags), so the PC can start
 * decoding at any keyframe.
 */
final class VideoEncoder {
    interface Sink {
        void onEncoded(byte[] data, int length, long ptsUs, boolean keyframe);
    }

    static final String TAG = "TacoCam";

    final String codecName;   // "h264" | "hevc"
    final int width, height, fps, bitrate;
    private final MediaCodec codec;
    private final Surface input;
    private final Sink sink;
    private final Thread drain;
    private volatile boolean running = true;
    private byte[] config = new byte[0];      // SPS+PPS (+VPS)

    VideoEncoder(String codecName, int width, int height, int fps, int bitrate, Sink sink) throws IOException {
        this.codecName = codecName;
        this.width = width;
        this.height = height;
        this.fps = fps;
        this.bitrate = bitrate;
        this.sink = sink;
        String mime = mime(codecName);
        MediaFormat f = MediaFormat.createVideoFormat(mime, width, height);
        f.setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface);
        f.setInteger(MediaFormat.KEY_BIT_RATE, bitrate);
        f.setInteger(MediaFormat.KEY_FRAME_RATE, fps);
        f.setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 4);
        f.setInteger(MediaFormat.KEY_MAX_B_FRAMES, 0);
        f.setInteger(MediaFormat.KEY_PRIORITY, 0);           // real time
        f.setInteger(MediaFormat.KEY_LATENCY, 1);
        codec = MediaCodec.createEncoderByType(mime);
        try {
            codec.configure(f, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
        } catch (RuntimeException e) {                         // some encoders reject the optional keys
            f.removeKey(MediaFormat.KEY_LATENCY);
            f.removeKey(MediaFormat.KEY_PRIORITY);
            codec.configure(f, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE);
        }
        input = codec.createInputSurface();
        codec.start();
        drain = new Thread(this::drainLoop, "tacocam-encoder");
        drain.start();
    }

    static String mime(String codecName) {
        return "hevc".equals(codecName) ? MediaFormat.MIMETYPE_VIDEO_HEVC : MediaFormat.MIMETYPE_VIDEO_AVC;
    }

    /** True when this phone has a hardware encoder for the codec at this size. */
    static boolean supports(String codecName, int width, int height) {
        String mime = mime(codecName);
        for (MediaCodecInfo info : new MediaCodecList(MediaCodecList.REGULAR_CODECS).getCodecInfos()) {
            if (!info.isEncoder()) continue;
            for (String type : info.getSupportedTypes()) {
                if (!type.equalsIgnoreCase(mime)) continue;
                try {
                    MediaCodecInfo.VideoCapabilities v = info.getCapabilitiesForType(type).getVideoCapabilities();
                    if (v != null && v.isSizeSupported(width, height)) return true;
                } catch (RuntimeException ignored) {
                }
            }
        }
        return false;
    }

    Surface surface() {
        return input;
    }

    void requestKeyframe() {
        if (!running) return;
        Bundle b = new Bundle();
        b.putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME, 0);
        try {
            codec.setParameters(b);
        } catch (IllegalStateException ignored) {
        }
    }

    void release() {
        running = false;
        try {
            drain.join(1000);
        } catch (InterruptedException ignored) {
        }
        try {
            codec.stop();
        } catch (RuntimeException ignored) {
        }
        codec.release();
        input.release();
    }

    private void drainLoop() {
        MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
        byte[] frame = new byte[512 * 1024];
        while (running) {
            int idx;
            try {
                idx = codec.dequeueOutputBuffer(info, 100_000);
            } catch (IllegalStateException e) {
                break;
            }
            if (idx == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                // some encoders hand the parameter sets over here instead of in a CODEC_CONFIG buffer
                MediaFormat out = codec.getOutputFormat();
                ByteArrayOutputStream csd = new ByteArrayOutputStream();
                for (String key : new String[] {"csd-0", "csd-1", "csd-2"}) {
                    ByteBuffer b = out.getByteBuffer(key);
                    if (b != null) {
                        byte[] part = new byte[b.remaining()];
                        b.get(part);
                        csd.write(part, 0, part.length);
                    }
                }
                if (csd.size() > 0) config = csd.toByteArray();
                continue;
            }
            if (idx < 0) continue;
            try {
                ByteBuffer buf = codec.getOutputBuffer(idx);
                if (buf != null && info.size > 0) {
                    buf.position(info.offset);
                    buf.limit(info.offset + info.size);
                    if ((info.flags & MediaCodec.BUFFER_FLAG_CODEC_CONFIG) != 0) {
                        config = new byte[info.size];
                        buf.get(config);
                    } else {
                        boolean key = (info.flags & MediaCodec.BUFFER_FLAG_KEY_FRAME) != 0;
                        int len = info.size + (key ? config.length : 0);
                        if (frame.length < len) frame = new byte[len + 64 * 1024];
                        int at = 0;
                        if (key) {
                            System.arraycopy(config, 0, frame, 0, config.length);
                            at = config.length;
                        }
                        buf.get(frame, at, info.size);
                        sink.onEncoded(frame, len, info.presentationTimeUs, key);
                    }
                }
                codec.releaseOutputBuffer(idx, false);
            } catch (RuntimeException e) {
                Log.w(TAG, "encoder output: " + e);
                if (!running) break;
            }
        }
    }
}
