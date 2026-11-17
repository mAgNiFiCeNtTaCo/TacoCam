package com.tacocam.app;

import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

import org.json.JSONObject;

/** The Taco Cam wire protocol (CONTRACT section 2): u32 big-endian N + u8 type + N-1 payload bytes. */
final class Proto {
    static final int PORT = 47777;

    static final int HELLO = 0x01;
    static final int SET = 0x02;
    static final int STATE = 0x03;
    static final int KEYFRAME = 0x04;
    static final int FOCUS_POINT = 0x05;
    static final int AUTH = 0x06;
    static final int VIDEO = 0x10;
    static final int PING = 0x20;
    static final int PONG = 0x21;
    static final int LOG = 0x30;

    static final int MAX_LEN = 16_777_216;
    static final int FLAG_KEYFRAME = 0x01;
    static final int FLAG_FORMAT_CHANGED = 0x02;

    static final String PAIR_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    static final int PAIR_CODE_LEN = 16;
    static final int PAIR_NONCE_LEN = 16;

    private static final SecureRandom RANDOM = new SecureRandom();

    private Proto() {}

    static byte[] encode(int type, byte[] payload) {
        int n = payload.length + 1;
        ByteBuffer b = ByteBuffer.allocate(4 + n);
        b.putInt(n);
        b.put((byte) type);
        b.put(payload);
        return b.array();
    }

    static byte[] encodeJson(int type, JSONObject obj) {
        return encode(type, obj.toString().getBytes(StandardCharsets.UTF_8));
    }

    static byte[] encodeText(int type, String text) {
        return encode(type, text.getBytes(StandardCharsets.UTF_8));
    }

    static byte[] encodeVideo(int flags, long ptsUs, byte[] data, int offset, int length) {
        int n = 1 + 9 + length;
        ByteBuffer b = ByteBuffer.allocate(4 + n);
        b.putInt(n);
        b.put((byte) VIDEO);
        b.put((byte) flags);
        b.putLong(ptsUs);
        b.put(data, offset, length);
        return b.array();
    }

    /** One message: {type, payload}. Throws IOException on a closed stream or a bad length. */
    static Object[] read(DataInputStream in) throws IOException {
        int n = in.readInt();
        if (n < 1 || n > MAX_LEN) throw new IOException("bad message length " + n);
        int type = in.readUnsignedByte();
        byte[] payload = new byte[n - 1];
        in.readFully(payload);
        return new Object[] {type, payload};
    }

    static JSONObject json(byte[] payload) throws IOException {
        try {
            return new JSONObject(new String(payload, StandardCharsets.UTF_8));
        } catch (Exception e) {
            throw new IOException("bad JSON: " + e.getMessage());
        }
    }

    // --- pairing (CONTRACT section 2, "Pairing") ---------------------------------------------------

    static String newCode() {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < PAIR_CODE_LEN; i++) sb.append(PAIR_ALPHABET.charAt(RANDOM.nextInt(PAIR_ALPHABET.length())));
        return sb.toString();
    }

    static String normalize(String text) {
        StringBuilder sb = new StringBuilder();
        if (text == null) return "";
        for (char ch : text.toUpperCase().toCharArray()) if (PAIR_ALPHABET.indexOf(ch) >= 0) sb.append(ch);
        return sb.toString();
    }

    static String pretty(String code) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < code.length(); i++) {
            if (i > 0 && i % 4 == 0) sb.append('-');
            sb.append(code.charAt(i));
        }
        return sb.toString();
    }

    static byte[] nonce() {
        byte[] b = new byte[PAIR_NONCE_LEN];
        RANDOM.nextBytes(b);
        return b;
    }

    /** HMAC-SHA256(key = code, "tacocam-pair-v1 " + role + " " + phone nonce + PC nonce). */
    static byte[] mac(String code, String role, byte[] phoneNonce, byte[] pcNonce) {
        try {
            Mac m = Mac.getInstance("HmacSHA256");
            m.init(new SecretKeySpec(normalize(code).getBytes(StandardCharsets.US_ASCII), "HmacSHA256"));
            ByteArrayOutputStream msg = new ByteArrayOutputStream();
            msg.write(("tacocam-pair-v1 " + role + " ").getBytes(StandardCharsets.US_ASCII));
            msg.write(phoneNonce);
            msg.write(pcNonce);
            return m.doFinal(msg.toByteArray());
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    static boolean check(byte[] mac, String code, String role, byte[] phoneNonce, byte[] pcNonce) {
        if (mac == null || normalize(code).length() != PAIR_CODE_LEN) return false;
        return MessageDigest.isEqual(mac, mac(code, role, phoneNonce, pcNonce));
    }

    static String hex(byte[] b) {
        StringBuilder sb = new StringBuilder();
        for (byte x : b) sb.append(String.format("%02x", x & 0xff));
        return sb.toString();
    }

    /** Hex text -> bytes, or null when it isn't hex (or isn't `length` bytes; length < 0 = any). */
    static byte[] unhex(String text, int length) {
        if (text == null || text.length() % 2 != 0) return null;
        byte[] out = new byte[text.length() / 2];
        for (int i = 0; i < out.length; i++) {
            int hi = Character.digit(text.charAt(2 * i), 16), lo = Character.digit(text.charAt(2 * i + 1), 16);
            if (hi < 0 || lo < 0) return null;
            out[i] = (byte) ((hi << 4) | lo);
        }
        return (length >= 0 && out.length != length) ? null : out;
    }
}
