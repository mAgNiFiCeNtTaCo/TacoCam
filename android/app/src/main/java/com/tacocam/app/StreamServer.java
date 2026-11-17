package com.tacocam.app;

import android.util.Log;

import org.json.JSONException;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.util.ArrayDeque;
import java.util.List;

/**
 * Listens on the phone's own loopback address, port 47777: the PC reaches it through the USB cable
 * (`adb forward`), nothing on a network can. Other apps on this phone could reach loopback too, so every
 * connection must prove the pairing code first (CONTRACT section 2, Pairing). The PC reads the code over the
 * cable (the app's files folder, which other apps can't read since Android 11).
 *
 * One PC at a time; a connected PC is never pushed out by a newcomer unless it went quiet for 3 s.
 */
final class StreamServer {
    interface Handler {
        JSONObject hello();
        JSONObject state();
        List<String> applySet(JSONObject patch);
        void focus(double x, double y);
        void keyframe();
        void status(String text);
        String code();
    }

    static final String TAG = "TacoCam";
    static final int MAX_QUEUED_FRAMES = 3;
    static final int MAX_QUEUED_BYTES = 2 * 1024 * 1024;
    static final long PAIR_TIMEOUT_MS = 3000;
    static final long QUIET_AFTER_MS = 3000;
    static final long SILENT_CLOSE_MS = 10_000;

    private final Handler handler;
    private ServerSocket server;
    private volatile boolean running;
    private Session session;
    private int wrongCodes;
    private long lockedUntil;

    private final int wantPort;
    private volatile int boundPort = -1;

    StreamServer(Handler handler) {
        this(handler, Proto.PORT);
    }

    /** port 0 = any free port (tests); port() says which one once it listens. */
    StreamServer(Handler handler, int port) {
        this.handler = handler;
        this.wantPort = port;
    }

    int port() {
        return boundPort;
    }

    void start() {
        running = true;
        Thread t = new Thread(this::acceptLoop, "tacocam-accept");
        t.setDaemon(true);
        t.start();
        Thread w = new Thread(this::watchdog, "tacocam-watchdog");
        w.setDaemon(true);
        w.start();
    }

    void stop() {
        running = false;
        try {
            if (server != null) server.close();
        } catch (IOException ignored) {
        }
        Session s;
        synchronized (this) {
            s = session;
            session = null;
        }
        if (s != null) s.close();
    }

    synchronized boolean connected() {
        return session != null && session.authed && session.gotHello && !session.closed;
    }

    /** True while a PC wants video. */
    synchronized boolean streaming() {
        return session != null && session.streaming && !session.closed;
    }

    void sendState() {
        Session s;
        synchronized (this) {
            s = session;
        }
        if (s != null && s.gotHello) s.send(Proto.encodeJson(Proto.STATE, handler.state()));
    }

    void sendLog(String text) {
        Session s;
        synchronized (this) {
            s = session;
        }
        if (s != null && s.gotHello) s.send(Proto.encodeText(Proto.LOG, text));
    }

    static final int SENT = 0, DROPPED = 1, DROPPED_WANT_KEY = 2;

    /** One encoded frame -> SENT, DROPPED, or DROPPED_WANT_KEY (ask the encoder for a keyframe now). */
    int sendVideo(int flags, long ptsUs, byte[] data, int len, boolean key) {
        Session s;
        synchronized (this) {
            s = session;
        }
        if (s == null || !s.streaming) return DROPPED;
        return s.sendVideo(flags, ptsUs, data, len, key);
    }

    private void acceptLoop() {
        while (running) {
            try {
                server = new ServerSocket();
                server.setReuseAddress(true);
                server.bind(new InetSocketAddress(InetAddress.getLoopbackAddress(), wantPort), 4);
                boundPort = server.getLocalPort();
                break;
            } catch (IOException e) {
                handler.status("Can't listen on port " + wantPort + ": " + e.getMessage());
                sleep(2000);
            }
        }
        while (running) {
            Socket sock;
            try {
                sock = server.accept();
            } catch (IOException e) {
                if (running) Log.w(TAG, "accept: " + e);
                continue;
            }
            boolean keep;
            synchronized (this) {
                Session old = session;
                long now = System.currentTimeMillis();
                if (now < lockedUntil) {
                    keep = true;
                } else {
                    keep = old != null && !old.closed && old.authed && now - old.lastRx < QUIET_AFTER_MS;
                }
                if (!keep) {
                    Session s = new Session(sock);
                    session = s;
                    if (old != null) old.close();
                    s.start();
                }
            }
            if (keep) {
                try {
                    sock.close();
                } catch (IOException ignored) {
                }
                handler.status(System.currentTimeMillis() < lockedUntil
                        ? "Turned a connection away: too many wrong codes, wait a minute"
                        : "Turned a second PC away: one is already connected");
            }
        }
    }

    private void watchdog() {
        while (running) {
            sleep(500);
            Session s;
            synchronized (this) {
                s = session;
            }
            if (s == null || s.closed) continue;
            long now = System.currentTimeMillis();
            if (!s.authed && now - s.started > PAIR_TIMEOUT_MS) {
                s.close();
            } else if (now - s.lastRx > SILENT_CLOSE_MS) {
                s.close();
            } else if (s.gotHello && !s.streaming && now - s.helloAt > 2000) {
                s.streaming = true;
            }
        }
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ignored) {
        }
    }

    private final class Session {
        final Socket sock;
        final long started = System.currentTimeMillis();
        volatile long lastRx = started;
        volatile boolean closed, authed, gotHello, streaming;
        volatile long helloAt;
        boolean needKey = true;
        long lastKeyAsk;
        byte[] challenge;
        byte[] pendingHello;
        private final ArrayDeque<byte[]> out = new ArrayDeque<>();
        private final ArrayDeque<Boolean> outIsVideo = new ArrayDeque<>();
        private int queuedVideo, queuedBytes;

        Session(Socket sock) {
            this.sock = sock;
        }

        void start() {
            try {
                sock.setTcpNoDelay(true);
                sock.setSendBufferSize(1 << 20);
            } catch (IOException ignored) {
            }
            new Thread(this::readLoop, "tacocam-session-read").start();
            new Thread(this::writeLoop, "tacocam-session-write").start();
        }

        void close() {
            synchronized (this) {
                if (closed) return;
                closed = true;
                notifyAll();
            }
            try {
                sock.close();
            } catch (IOException ignored) {
            }
        }

        synchronized boolean send(byte[] msg) {
            if (closed) return false;
            out.add(msg);
            outIsVideo.add(false);
            queuedBytes += msg.length;
            notifyAll();
            return true;
        }

        /** Back-pressure (CONTRACT section 2): with 3 frames or 2 MB waiting, drop non-key frames. */
        synchronized int sendVideo(int flags, long pts, byte[] data, int len, boolean key) {
            if (closed) return DROPPED;
            if (!key && (needKey || queuedVideo >= MAX_QUEUED_FRAMES || queuedBytes > MAX_QUEUED_BYTES)) {
                needKey = true;
                long now = System.currentTimeMillis();
                if (now - lastKeyAsk > 500) {        // ask the encoder for a keyframe, at most twice a second
                    lastKeyAsk = now;
                    return DROPPED_WANT_KEY;
                }
                return DROPPED;
            }
            if (key) needKey = false;
            byte[] msg = Proto.encodeVideo(flags, pts, data, 0, len);
            out.add(msg);
            outIsVideo.add(true);
            queuedVideo++;
            queuedBytes += msg.length;
            notifyAll();
            return SENT;
        }

        private void writeLoop() {
            try {
                OutputStream os = sock.getOutputStream();
                while (true) {
                    byte[] msg;
                    boolean video;
                    synchronized (this) {
                        while (out.isEmpty() && !closed) wait(500);
                        if (closed) return;
                        msg = out.poll();
                        video = outIsVideo.poll();
                    }
                    os.write(msg);
                    synchronized (this) {
                        queuedBytes -= msg.length;
                        if (video) queuedVideo--;
                    }
                }
            } catch (IOException | InterruptedException e) {
                // closed
            } finally {
                close();
            }
        }

        private void readLoop() {
            handler.status("PC connecting...");
            try {
                DataInputStream in = new DataInputStream(new BufferedInputStream(sock.getInputStream(), 65536));
                while (!closed) {
                    Object[] m = Proto.read(in);
                    lastRx = System.currentTimeMillis();
                    int type = (Integer) m[0];
                    byte[] payload = (byte[]) m[1];
                    if (!authed) pair(type, payload);
                    else handle(type, payload);
                }
            } catch (IOException e) {
                // closed or broken
            } finally {
                close();
                synchronized (StreamServer.this) {
                    if (session == this) session = null;
                }
                handler.status(null);
            }
        }

        private void pair(int type, byte[] payload) throws IOException {
            if (type == Proto.HELLO) {
                pendingHello = payload;
                if (challenge == null) {
                    challenge = Proto.nonce();
                    try {
                        send(Proto.encodeJson(Proto.AUTH, new JSONObject().put("nonce", Proto.hex(challenge))));
                    } catch (JSONException ignored) {
                    }
                }
            } else if (type == Proto.AUTH && challenge != null) {
                JSONObject auth = Proto.json(payload);
                byte[] pcNonce = Proto.unhex(auth.optString("nonce", null), Proto.PAIR_NONCE_LEN);
                byte[] mac = Proto.unhex(auth.optString("mac", null), -1);
                String code = handler.code();
                if (pcNonce == null || !Proto.check(mac, code, "pc", challenge, pcNonce)) {
                    synchronized (StreamServer.this) {
                        if (++wrongCodes >= 5) {
                            lockedUntil = System.currentTimeMillis() + 60_000;
                            wrongCodes = 0;
                        }
                    }
                    send(Proto.encodeText(Proto.LOG, "Closing: wrong pairing code"));
                    handler.status("Turned a connection away: wrong pairing code");
                    sleep(100);
                    close();
                    return;
                }
                synchronized (StreamServer.this) {
                    wrongCodes = 0;
                }
                authed = true;
                try {
                    send(Proto.encodeJson(Proto.AUTH, new JSONObject().put("mac",
                            Proto.hex(Proto.mac(code, "phone", challenge, pcNonce)))));
                } catch (JSONException ignored) {
                }
                if (pendingHello != null) handle(Proto.HELLO, pendingHello);
            }
            // anything else before the code is proved: ignored
        }

        private void handle(int type, byte[] payload) throws IOException {
            switch (type) {
                case Proto.HELLO:
                    send(Proto.encodeJson(Proto.HELLO, handler.hello()));
                    gotHello = true;
                    helloAt = System.currentTimeMillis();
                    send(Proto.encodeJson(Proto.STATE, handler.state()));
                    handler.status("connected");
                    handler.keyframe();
                    break;
                case Proto.SET:
                    for (String note : handler.applySet(Proto.json(payload))) {
                        send(Proto.encodeText(Proto.LOG, "SET ignored: " + note));
                    }
                    streaming = true;
                    send(Proto.encodeJson(Proto.STATE, handler.state()));
                    break;
                case Proto.KEYFRAME:
                    handler.keyframe();
                    break;
                case Proto.FOCUS_POINT: {
                    JSONObject p = Proto.json(payload);
                    double x = p.optDouble("x", Double.NaN), y = p.optDouble("y", Double.NaN);
                    if (Double.isNaN(x) || Double.isNaN(y)) send(Proto.encodeText(Proto.LOG, "FOCUS_POINT needs x and y 0..1"));
                    else handler.focus(Math.min(Math.max(x, 0), 1), Math.min(Math.max(y, 0), 1));
                    break;
                }
                case Proto.PING:
                    send(Proto.encode(Proto.PONG, payload));
                    break;
                default:
                    break;   // unknown types are ignored (forward compatibility)
            }
        }
    }
}
