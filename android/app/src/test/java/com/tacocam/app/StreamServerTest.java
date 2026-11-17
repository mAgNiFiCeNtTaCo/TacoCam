package com.tacocam.app;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import org.json.JSONObject;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;

import java.io.DataInputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** The phone's server against a client that follows CONTRACT section 2 like the PC does. */
public class StreamServerTest {
    static final String CODE = "ABCDEFGHJKLMNPQR";

    final List<JSONObject> sets = Collections.synchronizedList(new ArrayList<>());
    final List<String> statuses = Collections.synchronizedList(new ArrayList<>());
    int keyframes;
    StreamServer server;

    @Before public void start() throws Exception {
        server = new StreamServer(new StreamServer.Handler() {
            @Override public JSONObject hello() {
                try {
                    return new JSONObject().put("proto", 1).put("app", "TacoCam").put("platform", "android");
                } catch (Exception e) {
                    throw new RuntimeException(e);
                }
            }

            @Override public JSONObject state() {
                try {
                    return new JSONObject().put("rotation_hint", 90);
                } catch (Exception e) {
                    throw new RuntimeException(e);
                }
            }

            @Override public List<String> applySet(JSONObject patch) {
                sets.add(patch);
                return Collections.singletonList("demo note");
            }

            @Override public void focus(double x, double y) {}

            @Override public void keyframe() {
                keyframes++;
            }

            @Override public void status(String text) {
                statuses.add(String.valueOf(text));
            }

            @Override public String code() {
                return CODE;
            }
        }, 0);
        server.start();
        for (int i = 0; i < 100 && server.port() < 0; i++) Thread.sleep(20);
    }

    @After public void stop() {
        server.stop();
    }

    static class Client {
        final Socket s;
        final DataInputStream in;
        final OutputStream out;

        Client(int port) throws IOException {
            s = new Socket(InetAddress.getLoopbackAddress(), port);
            s.setSoTimeout(3000);
            in = new DataInputStream(s.getInputStream());
            out = s.getOutputStream();
        }

        void send(int type, byte[] payload) throws IOException {
            out.write(Proto.encode(type, payload));
        }

        void sendJson(int type, String json) throws IOException {
            send(type, json.getBytes("UTF-8"));
        }

        Object[] next() throws IOException {
            return Proto.read(in);
        }

        Object[] next(int type) throws IOException {
            for (int i = 0; i < 50; i++) {
                Object[] m = next();
                if ((Integer) m[0] == type) return m;
            }
            throw new AssertionError("no message of type " + type);
        }

        /** HELLO + pairing as the PC does it. Returns the phone's HELLO. */
        JSONObject pair(String code) throws Exception {
            sendJson(Proto.HELLO, "{\"proto\":1,\"client\":\"TacoCam PC\",\"version\":\"1.0\"}");
            Object[] m = next();
            assertEquals(Proto.AUTH, (int) (Integer) m[0]);
            byte[] phoneNonce = Proto.unhex(Proto.json((byte[]) m[1]).getString("nonce"), 16);
            byte[] pcNonce = Proto.nonce();
            sendJson(Proto.AUTH, new JSONObject().put("nonce", Proto.hex(pcNonce))
                    .put("mac", Proto.hex(Proto.mac(code, "pc", phoneNonce, pcNonce))).toString());
            m = next();
            if ((Integer) m[0] != Proto.AUTH) return null;
            byte[] mac = Proto.unhex(Proto.json((byte[]) m[1]).getString("mac"), 32);
            assertTrue("the phone proves the code back", Proto.check(mac, CODE, "phone", phoneNonce, pcNonce));
            m = next();
            assertEquals(Proto.HELLO, (int) (Integer) m[0]);
            return Proto.json((byte[]) m[1]);
        }

        boolean closedSoon() throws IOException {
            try {
                while (true) next();
            } catch (EOFException e) {
                return true;
            } catch (SocketTimeoutException e) {
                return false;
            } catch (IOException e) {
                return true;
            }
        }
    }

    @Test public void fullHandshakeSetPingAndVideo() throws Exception {
        Client c = new Client(server.port());
        JSONObject hello = c.pair(CODE);
        assertEquals("android", hello.getString("platform"));
        Object[] st = c.next(Proto.STATE);
        assertEquals(90, Proto.json((byte[]) st[1]).getInt("rotation_hint"));
        c.sendJson(Proto.SET, "{\"zoom\":2}");
        Object[] log = c.next(Proto.LOG);
        assertEquals("SET ignored: demo note", new String((byte[]) log[1], "UTF-8"));
        c.next(Proto.STATE);
        assertEquals(2, sets.get(0).getInt("zoom"));
        c.send(Proto.PING, new byte[] {1, 2, 3});
        assertArrayEquals(new byte[] {1, 2, 3}, (byte[]) c.next(Proto.PONG)[1]);

        assertEquals(StreamServer.DROPPED_WANT_KEY, server.sendVideo(0, 5, new byte[] {1}, 1, false));   // must start with a key
        assertEquals(StreamServer.SENT, server.sendVideo(Proto.FLAG_KEYFRAME, 7, new byte[] {0, 0, 0, 1, 0x65}, 5, true));
        Object[] v = c.next(Proto.VIDEO);
        byte[] p = (byte[]) v[1];
        assertEquals(Proto.FLAG_KEYFRAME, p[0]);
        assertEquals(7, p[8]);
        assertEquals(0x65, p[13]);
        assertTrue(server.connected());
    }

    @Test public void wrongCodeGetsNothing() throws Exception {
        Client c = new Client(server.port());
        assertEquals(null, c.pair("ZZZZZZZZZZZZZZZZ"));
        assertTrue(c.closedSoon());
        assertTrue(sets.isEmpty());
    }

    @Test public void nothingIsTakenBeforePairing() throws Exception {
        Client c = new Client(server.port());
        c.sendJson(Proto.SET, "{\"zoom\":3}");
        c.send(Proto.PING, new byte[] {1});
        Thread.sleep(300);
        assertTrue(sets.isEmpty());
        assertTrue("closed after 3 s without the code", c.closedSoon() || c.closedSoon());
    }

    @Test public void aSecondPcIsTurnedAway() throws Exception {
        Client a = new Client(server.port());
        a.pair(CODE);
        a.next(Proto.STATE);
        Client b = new Client(server.port());
        assertTrue(b.closedSoon());
        a.send(Proto.PING, new byte[] {4});
        assertArrayEquals(new byte[] {4}, (byte[]) a.next(Proto.PONG)[1]);
    }

    @Test public void fiveWrongCodesLockForAMinute() throws Exception {
        for (int i = 0; i < 5; i++) {
            Client c = new Client(server.port());
            c.pair("ZZZZZZZZZZZZZZZZ");
            c.closedSoon();
        }
        Client c = new Client(server.port());
        try {
            c.sendJson(Proto.HELLO, "{\"proto\":1}");
            Object[] m = c.next();
            fail("a locked phone answered: " + m[0]);
        } catch (IOException expected) {
            // closed at once
        }
    }
}
