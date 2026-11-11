import XCTest
import Network

/// Framing (CONTRACT section 2) and Annex-B conversion. Protocol.swift and AnnexB.swift are compiled
/// straight into this test bundle, so no app host or camera is needed.
final class ProtocolTests: XCTestCase {

    // MARK: framing

    func testHeaderIsBigEndianLengthIncludingTypeByte() {
        let d = Framing.encode(.ping, payload: Data([1, 2, 3]))
        XCTAssertEqual([UInt8](d), [0, 0, 0, 4, 0x20, 1, 2, 3])
    }

    func testEmptyPayload() {
        XCTAssertEqual([UInt8](Framing.encode(.keyframe)), [0, 0, 0, 1, 0x04])
    }

    func testTypeNumbers() {
        XCTAssertEqual(MsgType.hello.rawValue, 0x01)
        XCTAssertEqual(MsgType.set.rawValue, 0x02)
        XCTAssertEqual(MsgType.state.rawValue, 0x03)
        XCTAssertEqual(MsgType.keyframe.rawValue, 0x04)
        XCTAssertEqual(MsgType.focusPoint.rawValue, 0x05)
        XCTAssertEqual(MsgType.video.rawValue, 0x10)
        XCTAssertEqual(MsgType.ping.rawValue, 0x20)
        XCTAssertEqual(MsgType.pong.rawValue, 0x21)
        XCTAssertEqual(MsgType.log.rawValue, 0x30)
    }

    func testVideoMessage() {
        let d = Framing.encodeVideo(flags: 0x03, ptsUs: 0x0102_0304_0506_0708,
                                    annexB: Data([0, 0, 0, 1, 0x65]))
        XCTAssertEqual([UInt8](d), [0, 0, 0, 15, 0x10, 0x03,
                                    1, 2, 3, 4, 5, 6, 7, 8,
                                    0, 0, 0, 1, 0x65])
    }

    func testLargeLength() {
        let payload = Data(repeating: 7, count: 70_000)
        let d = Framing.encode(.log, payload: payload)
        XCTAssertEqual([UInt8](d.prefix(5)), [0x00, 0x01, 0x11, 0x71, 0x30])  // 70_001 = 0x011171
        XCTAssertEqual(d.count, 70_005)
    }

    func testJSONMessageRoundTrip() throws {
        let d = try XCTUnwrap(Framing.encodeJSON(.hello, ["proto": 1, "app": "TacoCam"]))
        var p = FrameParser()
        let msgs = try p.feed(d)
        XCTAssertEqual(msgs.count, 1)
        XCTAssertEqual(msgs[0].type, 0x01)
        let obj = try XCTUnwrap(FrameParser.jsonObject(msgs[0].payload))
        XCTAssertEqual(obj["proto"] as? Int, 1)
        XCTAssertEqual(obj["app"] as? String, "TacoCam")
    }

    func testParserHandlesSplitAndJoinedMessages() throws {
        let a = Framing.encode(.hello, payload: Data("{\"proto\":1}".utf8))
        let b = Framing.encode(.ping, payload: Data([9, 8]))
        let c = Framing.encode(.keyframe)
        var all = Data()
        all.append(a)
        all.append(b)
        all.append(c)
        var p = FrameParser()
        var got: [(type: UInt8, payload: Data)] = []
        // Feed one byte at a time.
        for i in 0..<all.count {
            got += try p.feed(all.subdata(in: i..<(i + 1)))
        }
        XCTAssertEqual(got.map { $0.type }, [0x01, 0x20, 0x04])
        XCTAssertEqual([UInt8](got[1].payload), [9, 8])
        XCTAssertEqual(got[2].payload.count, 0)
        XCTAssertEqual(p.bufferedCount, 0)

        // All at once, from a slice with a non-zero start index.
        var q = FrameParser()
        let padded = Data([0xEE]) + all
        let msgs = try q.feed(padded.dropFirst())
        XCTAssertEqual(msgs.map { $0.type }, [0x01, 0x20, 0x04])
    }

    func testUnknownTypeIsStillFramed() throws {
        var p = FrameParser()
        let msgs = try p.feed(Data([0, 0, 0, 2, 0x99, 0x01]))
        XCTAssertEqual(msgs.count, 1)
        XCTAssertEqual(msgs[0].type, 0x99)
    }

    func testBadLengthsThrow() {
        var p = FrameParser()
        XCTAssertThrowsError(try p.feed(Data([0, 0, 0, 0])))
        var q = FrameParser()
        XCTAssertThrowsError(try q.feed(Data([0x01, 0x00, 0x00, 0x01])))  // 16_777_217
        var r = FrameParser()
        XCTAssertNoThrow(try r.feed(Data([0x01, 0x00, 0x00, 0x00])))      // 16_777_216 is allowed
        XCTAssertEqual(r.bufferedCount, 4)
    }

    // MARK: pairing (CONTRACT section 2). The same numbers are in pc/tests/test_engine_protocol.py.

    private let pairCode = "ABCDEFGHJKLMNPQR"
    private let phoneNonce = Data((0..<16).map { UInt8($0) })
    private let pcNonce = Data((16..<32).map { UInt8($0) })
    private let pcProof = "5e8b76ad49eeca05d4fdb4ceafeb122a7b7f4c95dd1ccd8c3339f7086b47dd6c"
    private let phoneProof = "1bdf32c75bc42d0c329daf2dce2053f86ba92b4f90b736e3524b9698cc834330"

    func testAuthTypeNumber() {
        XCTAssertEqual(MsgType.auth.rawValue, 0x06)
    }

    func testCodeShape() {
        XCTAssertEqual(Pairing.alphabet.count, 32)
        XCTAssertEqual(Set(Pairing.alphabet).count, 32)
        XCTAssertEqual(Pairing.normalize("abcd-efgh jklm_npqr 01io"), pairCode)
        XCTAssertEqual(Pairing.display(pairCode), "ABCD-EFGH-JKLM-NPQR")
        let a = Pairing.newCode(), b = Pairing.newCode()
        XCTAssertEqual(a.count, 16)
        XCTAssertEqual(Pairing.normalize(a), a)
        XCTAssertNotEqual(a, b)
        XCTAssertEqual(Pairing.newNonce().count, 16)
    }

    func testHex() {
        XCTAssertEqual(Pairing.hex(Data([0x00, 0xff, 0x10])), "00ff10")
        XCTAssertEqual(Pairing.unhex("00fF10"), Data([0x00, 0xff, 0x10]))
        XCTAssertNil(Pairing.unhex("0"))
        XCTAssertNil(Pairing.unhex("zz"))
    }

    func testProofsMatchThePC() {
        XCTAssertEqual(Pairing.hex(Pairing.proof(code: pairCode, role: "pc", phoneNonce: phoneNonce, pcNonce: pcNonce)),
                       pcProof)
        XCTAssertEqual(Pairing.hex(Pairing.proof(code: "abcd-efgh-jklm-npqr", role: "phone",
                                                 phoneNonce: phoneNonce, pcNonce: pcNonce)), phoneProof)
    }

    func testOnlyTheRightProofPasses() {
        let ok = Pairing.unhex(pcProof)!
        XCTAssertTrue(Pairing.check(ok, code: pairCode, role: "pc", phoneNonce: phoneNonce, pcNonce: pcNonce))
        XCTAssertFalse(Pairing.check(ok, code: pairCode, role: "phone", phoneNonce: phoneNonce, pcNonce: pcNonce))
        XCTAssertFalse(Pairing.check(ok, code: pairCode, role: "pc", phoneNonce: pcNonce, pcNonce: phoneNonce))
        XCTAssertFalse(Pairing.check(ok, code: "ABCDEFGHJKLMNPQS", role: "pc", phoneNonce: phoneNonce, pcNonce: pcNonce))
        XCTAssertFalse(Pairing.check(Data(ok.dropLast()), code: pairCode, role: "pc",
                                     phoneNonce: phoneNonce, pcNonce: pcNonce))
        XCTAssertFalse(Pairing.check(Data(), code: pairCode, role: "pc", phoneNonce: phoneNonce, pcNonce: pcNonce))
        // an empty or short code never passes, even with the proof that matches it
        let empty = Pairing.proof(code: "", role: "pc", phoneNonce: phoneNonce, pcNonce: pcNonce)
        XCTAssertFalse(Pairing.check(empty, code: "", role: "pc", phoneNonce: phoneNonce, pcNonce: pcNonce))
        // a PC nonce of the wrong length never passes
        XCTAssertFalse(Pairing.check(ok, code: pairCode, role: "pc", phoneNonce: phoneNonce, pcNonce: Data([1, 2])))
    }

    // MARK: who may connect (CONTRACT section 1)

    func testUSBIsLoopbackAndNothingElseIs() {
        XCTAssertTrue(Pairing.peer(.hostPort(host: .ipv4(IPv4Address("127.0.0.1")!), port: 50000)).local)
        XCTAssertTrue(Pairing.peer(.hostPort(host: .ipv6(IPv6Address("::1")!), port: 50000)).local)
        XCTAssertTrue(Pairing.peer(.hostPort(host: .ipv6(IPv6Address("::ffff:127.0.0.1")!), port: 50000)).local)
        XCTAssertFalse(Pairing.peer(.hostPort(host: .ipv4(IPv4Address("192.168.1.23")!), port: 50000)).local)
        XCTAssertFalse(Pairing.peer(.hostPort(host: .ipv4(IPv4Address("100.101.102.103")!), port: 50000)).local)
        XCTAssertFalse(Pairing.peer(.hostPort(host: .ipv6(IPv6Address("::ffff:192.168.1.23")!), port: 50000)).local)
        XCTAssertFalse(Pairing.peer(.hostPort(host: .ipv6(IPv6Address("fe80::1")!), port: 50000)).local)
        XCTAssertFalse(Pairing.peer(.hostPort(host: .name("localhost", nil), port: 50000)).local)
        XCTAssertEqual(Pairing.peer(.hostPort(host: .ipv4(IPv4Address("192.168.1.23")!), port: 50000)).host,
                       "192.168.1.23")
    }

    func testWifiIsRefusedUnlessSwitchedOnWithACode() {
        func d(local: Bool, wifi: Bool = false, code: Bool = false, locked: Bool = false,
               busy: Bool = false, quiet: Bool = false) -> Pairing.Decision {
            return Pairing.decide(local: local, wifiAllowed: wifi, codeSet: code, locked: locked, busy: busy, quiet: quiet)
        }
        XCTAssertEqual(d(local: true), .accept)                                  // USB always
        XCTAssertEqual(d(local: false), .refuseWifiOff)                          // the default
        XCTAssertEqual(d(local: false, wifi: true), .refuseWifiOff)              // on but no code yet
        XCTAssertEqual(d(local: false, wifi: true, code: true), .accept)         // may now try to prove the code
        XCTAssertEqual(d(local: false, wifi: true, code: true, locked: true), .refuseLocked)
        // a connected PC is never pushed out by a newcomer
        XCTAssertEqual(d(local: false, wifi: true, code: true, busy: true), .refuseBusy)
        XCTAssertEqual(d(local: false, wifi: true, code: true, busy: true, quiet: true), .refuseBusy)
        XCTAssertEqual(d(local: true, busy: true), .refuseBusy)
        XCTAssertEqual(d(local: true, busy: true, quiet: true), .accept)         // USB replug after a dead connection
    }

    func testLockoutAfterWrongCodes() {
        var log = WrongCodeLog()
        let t0 = Date(timeIntervalSince1970: 1_000_000)
        for i in 0..<(Pairing.maxWrongCodes - 1) {
            log.wrong("192.168.1.9", now: t0.addingTimeInterval(Double(i)))
            XCTAssertFalse(log.isLocked("192.168.1.9", now: t0.addingTimeInterval(Double(i))))
        }
        log.wrong("192.168.1.9", now: t0.addingTimeInterval(10))
        XCTAssertTrue(log.isLocked("192.168.1.9", now: t0.addingTimeInterval(11)))
        XCTAssertFalse(log.isLocked("192.168.1.8", now: t0.addingTimeInterval(11)))   // other addresses are not held up
        XCTAssertFalse(log.isLocked("192.168.1.9", now: t0.addingTimeInterval(10 + Pairing.lockoutSeconds + 1)))
        log.wrong("192.168.1.9", now: t0.addingTimeInterval(200))                      // old tries were forgotten
        XCTAssertFalse(log.isLocked("192.168.1.9", now: t0.addingTimeInterval(201)))
        log.right("192.168.1.9")
        XCTAssertFalse(log.isLocked("192.168.1.9", now: t0.addingTimeInterval(202)))
    }

    // MARK: Annex-B

    func testLengthPrefixedToAnnexB() {
        let avcc = Data([0, 0, 0, 2, 0x67, 0x42,
                         0, 0, 0, 3, 0x68, 0xCE, 0x38,
                         0, 0, 0, 1, 0x65])
        let out = AnnexB.fromLengthPrefixed(avcc)
        XCTAssertEqual(out.map { [UInt8]($0) }, [0, 0, 0, 1, 0x67, 0x42,
                                                 0, 0, 0, 1, 0x68, 0xCE, 0x38,
                                                 0, 0, 0, 1, 0x65])
    }

    func testTwoByteLengthPrefix() {
        let avcc = Data([0, 2, 0x41, 0x9A, 0, 1, 0x06])
        let out = AnnexB.fromLengthPrefixed(avcc, lengthSize: 2)
        XCTAssertEqual(out.map { [UInt8]($0) }, [0, 0, 0, 1, 0x41, 0x9A, 0, 0, 0, 1, 0x06])
    }

    func testTruncatedNALIsRejected() {
        XCTAssertNil(AnnexB.fromLengthPrefixed(Data([0, 0, 0, 5, 0x65, 0x88])))
        XCTAssertNil(AnnexB.fromLengthPrefixed(Data([0, 0, 1])))
        XCTAssertNil(AnnexB.fromLengthPrefixed(Data([0, 1, 0x65]), lengthSize: 3))
    }

    func testEmptyInput() {
        XCTAssertEqual(AnnexB.fromLengthPrefixed(Data()), Data())
    }

    func testParameterSetsGoInFrontOfKeyframe() {
        let vps = Data([0x40, 0x01]), sps = Data([0x42, 0x01]), pps = Data([0x44, 0x01])
        let frame = AnnexB.fromLengthPrefixed(Data([0, 0, 0, 2, 0x26, 0x01]))!
        let out = AnnexB.withParameterSets([vps, sps, pps], frame: frame)
        XCTAssertEqual([UInt8](out), [0, 0, 0, 1, 0x40, 0x01,
                                      0, 0, 0, 1, 0x42, 0x01,
                                      0, 0, 0, 1, 0x44, 0x01,
                                      0, 0, 0, 1, 0x26, 0x01])
    }
}
