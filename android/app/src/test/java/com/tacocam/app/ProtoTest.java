package com.tacocam.app;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.io.ByteArrayInputStream;
import java.io.DataInputStream;

public class ProtoTest {
    static final String CODE = "ABCDEFGHJKLMNPQR";

    static byte[] range(int from) {
        byte[] b = new byte[16];
        for (int i = 0; i < 16; i++) b[i] = (byte) (from + i);
        return b;
    }

    /** The test numbers in CONTRACT section 2 (the PC's tests use the same ones). */
    @Test public void pairingMacsMatchTheContract() {
        assertEquals("5e8b76ad49eeca05d4fdb4ceafeb122a7b7f4c95dd1ccd8c3339f7086b47dd6c",
                Proto.hex(Proto.mac(CODE, "pc", range(0), range(16))));
        assertEquals("1bdf32c75bc42d0c329daf2dce2053f86ba92b4f90b736e3524b9698cc834330",
                Proto.hex(Proto.mac(CODE, "phone", range(0), range(16))));
    }

    @Test public void codesAreNormalisedLikeOnThePc() {
        assertEquals(CODE, Proto.normalize("abcd-efgh jklm-npqr"));
        assertEquals("ABCD-EFGH-JKLM-NPQR", Proto.pretty(CODE));
        String fresh = Proto.newCode();
        assertEquals(16, fresh.length());
        assertEquals(fresh, Proto.normalize(fresh));
        assertTrue(Proto.check(Proto.mac(CODE, "pc", range(0), range(16)), "abcd efgh jklm npqr", "pc", range(0), range(16)));
        assertFalse(Proto.check(Proto.mac(CODE, "pc", range(0), range(16)), "ABCDEFGHJKLMNPQ", "pc", range(0), range(16)));
        assertFalse(Proto.check(null, CODE, "pc", range(0), range(16)));
    }

    @Test public void hexRoundTrip() {
        assertArrayEquals(range(0), Proto.unhex(Proto.hex(range(0)), 16));
        assertNull(Proto.unhex("zz", -1));
        assertNull(Proto.unhex("abc", -1));
        assertNull(Proto.unhex(Proto.hex(range(0)), 8));
    }

    @Test public void framing() throws Exception {
        byte[] msg = Proto.encodeText(Proto.LOG, "hi");
        assertArrayEquals(new byte[] {0, 0, 0, 3, 0x30, 'h', 'i'}, msg);
        byte[] video = Proto.encodeVideo(Proto.FLAG_KEYFRAME, 0x0102030405060708L, new byte[] {9, 9, 7}, 2, 1);
        assertArrayEquals(new byte[] {0, 0, 0, 11, 0x10, 1, 1, 2, 3, 4, 5, 6, 7, 8, 7}, video);
        Object[] m = Proto.read(new DataInputStream(new ByteArrayInputStream(msg)));
        assertEquals(Proto.LOG, (int) (Integer) m[0]);
        assertArrayEquals(new byte[] {'h', 'i'}, (byte[]) m[1]);
    }

    @Test(expected = java.io.IOException.class)
    public void zeroLengthIsAnError() throws Exception {
        Proto.read(new DataInputStream(new ByteArrayInputStream(new byte[] {0, 0, 0, 0, 1})));
    }
}
