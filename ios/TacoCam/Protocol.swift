import Foundation
import CryptoKit
import Network

/// Message types, CONTRACT section 2.
enum MsgType: UInt8 {
    case hello = 0x01
    case set = 0x02
    case state = 0x03
    case keyframe = 0x04
    case focusPoint = 0x05
    case auth = 0x06
    case video = 0x10
    case ping = 0x20
    case pong = 0x21
    case log = 0x30
}

enum FramingError: Error, Equatable {
    case badLength(UInt32)
}

/// Framing: u32 big-endian N (type byte + payload) + u8 type + N-1 bytes payload.
enum Framing {
    static let maxLength: UInt32 = 16_777_216

    static func appendU32BE(_ v: UInt32, to d: inout Data) {
        d.append(UInt8((v >> 24) & 0xff))
        d.append(UInt8((v >> 16) & 0xff))
        d.append(UInt8((v >> 8) & 0xff))
        d.append(UInt8(v & 0xff))
    }

    static func appendU64BE(_ v: UInt64, to d: inout Data) {
        for shift in stride(from: 56, through: 0, by: -8) {
            d.append(UInt8((v >> UInt64(shift)) & 0xff))
        }
    }

    static func encode(type: UInt8, payload: Data) -> Data {
        var d = Data()
        d.reserveCapacity(5 + payload.count)
        appendU32BE(UInt32(payload.count + 1), to: &d)
        d.append(type)
        d.append(payload)
        return d
    }

    static func encode(_ type: MsgType, payload: Data = Data()) -> Data {
        return encode(type: type.rawValue, payload: payload)
    }

    /// JSON objects only (CONTRACT section 2).
    static func encodeJSON(_ type: MsgType, _ object: [String: Any]) -> Data? {
        guard JSONSerialization.isValidJSONObject(object),
              let body = try? JSONSerialization.data(withJSONObject: object, options: []) else { return nil }
        return encode(type, payload: body)
    }

    static func encodeLog(_ line: String) -> Data {
        return encode(.log, payload: Data(line.utf8))
    }

    /// VIDEO message: u8 flags + u64 BE pts_us + Annex-B bitstream, all framed.
    static func encodeVideo(flags: UInt8, ptsUs: UInt64, annexB: Data) -> Data {
        var d = Data()
        d.reserveCapacity(5 + 9 + annexB.count)
        appendU32BE(UInt32(1 + 9 + annexB.count), to: &d)
        d.append(MsgType.video.rawValue)
        d.append(flags)
        appendU64BE(ptsUs, to: &d)
        d.append(annexB)
        return d
    }

    static let flagKeyframe: UInt8 = 0x01
    static let flagFormatChanged: UInt8 = 0x02
}

/// Who may connect, and the Wi-Fi pairing code (CONTRACT sections 1 and 2). Pure functions, unit-tested.
enum Pairing {
    /// No 0, 1, I or O: they are easy to mix up when typing the code on the PC.
    static let alphabet: [Character] = Array("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
    static let codeLength = 16
    static let nonceLength = 16
    static let maxWrongCodes = 5
    static let lockoutSeconds: TimeInterval = 60
    /// A Wi-Fi connection that has not proved the code after this many seconds is closed.
    static let proveWithin: TimeInterval = 3
    /// A connected PC not heard from for this long may be replaced by a new USB connection.
    static let quietAfter: TimeInterval = 3

    static func newCode() -> String {
        var g = SystemRandomNumberGenerator()
        return String((0..<codeLength).map { _ in alphabet[Int.random(in: 0..<alphabet.count, using: &g)] })
    }

    /// The code as both sides use it: capitals, only characters a code can hold (no dashes or spaces).
    static func normalize(_ text: String) -> String {
        return String(text.uppercased().filter { alphabet.contains($0) })
    }

    /// "ABCD-EFGH-JKLM-NPQR" for the screen.
    static func display(_ code: String) -> String {
        var out = ""
        for (i, ch) in code.enumerated() {
            if i > 0 && i % 4 == 0 { out.append("-") }
            out.append(ch)
        }
        return out
    }

    static func newNonce() -> Data {
        var g = SystemRandomNumberGenerator()
        return Data((0..<nonceLength).map { _ in UInt8.random(in: 0...255, using: &g) })
    }

    static func hex(_ d: Data) -> String {
        return d.map { String(format: "%02x", $0) }.joined()
    }

    static func unhex(_ s: String) -> Data? {
        let chars = Array(s.utf8)
        guard chars.count % 2 == 0 else { return nil }
        var out = Data()
        var i = 0
        while i < chars.count {
            guard let hi = nibble(chars[i]), let lo = nibble(chars[i + 1]) else { return nil }
            out.append((hi << 4) | lo)
            i += 2
        }
        return out
    }

    private static func nibble(_ c: UInt8) -> UInt8? {
        switch c {
        case 48...57: return c - 48     // 0-9
        case 97...102: return c - 87    // a-f
        case 65...70: return c - 55     // A-F
        default: return nil
        }
    }

    private static func message(role: String, phoneNonce: Data, pcNonce: Data) -> Data {
        var msg = Data("tacocam-pair-v1 \(role) ".utf8)
        msg.append(phoneNonce)
        msg.append(pcNonce)
        return msg
    }

    /// HMAC-SHA256 keyed with the code over "tacocam-pair-v1 <role> " + phone nonce + PC nonce. role: "pc" | "phone".
    static func proof(code: String, role: String, phoneNonce: Data, pcNonce: Data) -> Data {
        let key = SymmetricKey(data: Data(normalize(code).utf8))
        let mac = HMAC<SHA256>.authenticationCode(for: message(role: role, phoneNonce: phoneNonce, pcNonce: pcNonce),
                                                  using: key)
        return Data(mac)
    }

    /// True when `mac` is the right proof. Compared in constant time; a code or nonce of the wrong length never passes.
    static func check(_ mac: Data, code: String, role: String, phoneNonce: Data, pcNonce: Data) -> Bool {
        let c = normalize(code)
        guard c.count == codeLength, phoneNonce.count == nonceLength, pcNonce.count == nonceLength else { return false }
        let key = SymmetricKey(data: Data(c.utf8))
        return HMAC<SHA256>.isValidAuthenticationCode(
            mac, authenticating: message(role: role, phoneNonce: phoneNonce, pcNonce: pcNonce), using: key)
    }

    /// The other end's address for the screen, and whether it came through the USB cable: usbmuxd hands USB
    /// connections to the app on the phone's own loopback address, which nothing on a network can use.
    static func peer(_ endpoint: NWEndpoint) -> (host: String, local: Bool) {
        guard case .hostPort(let host, _) = endpoint else { return ("unknown", false) }
        switch host {
        case .ipv4(let a):
            return ("\(a)", a.isLoopback)
        case .ipv6(let a):
            if a.isLoopback { return ("\(a)", true) }
            if a.isIPv4Mapped, let v4 = a.asIPv4 { return ("\(v4)", v4.isLoopback) }
            return ("\(a)", false)
        default:
            return ("\(host)", false)
        }
    }

    enum Decision: Equatable {
        case accept, refuseWifiOff, refuseLocked, refuseBusy
    }

    /// What to do with a new connection.
    /// - local: it came through the USB cable. codeSet: a full pairing code exists.
    /// - locked: this address sent too many wrong codes. busy: a PC that was let in is connected now.
    /// - quiet: nothing was heard from that PC for `quietAfter` seconds.
    static func decide(local: Bool, wifiAllowed: Bool, codeSet: Bool, locked: Bool, busy: Bool, quiet: Bool) -> Decision {
        if !local {
            if !wifiAllowed || !codeSet { return .refuseWifiOff }
            if locked { return .refuseLocked }
        }
        // A connected PC is never pushed out by a newcomer that has proved nothing. Only the USB cable may
        // take over, and only once the old connection went quiet (a PC that crashed or lost its cable).
        if busy && !(local && quiet) { return .refuseBusy }
        return .accept
    }
}

/// Wrong pairing codes per address: after `Pairing.maxWrongCodes` in a row the address waits `lockoutSeconds`.
struct WrongCodeLog {
    private var entries: [String: (count: Int, until: Date)] = [:]

    func isLocked(_ host: String, now: Date) -> Bool {
        guard let e = entries[host] else { return false }
        return e.count >= Pairing.maxWrongCodes && now < e.until
    }

    mutating func wrong(_ host: String, now: Date) {
        var e = entries[host] ?? (count: 0, until: now)
        if now >= e.until { e.count = 0 }   // old tries are forgotten
        e.count += 1
        e.until = now.addingTimeInterval(Pairing.lockoutSeconds)
        entries[host] = e
        if entries.count > 64 {
            entries = entries.filter { now < $0.value.until }
            if entries.count > 64 { entries.removeAll() }
        }
    }

    mutating func right(_ host: String) {
        entries[host] = nil
    }
}

/// Incremental parser for the byte stream from the PC.
struct FrameParser {
    private var buffer: [UInt8] = []

    var bufferedCount: Int { return buffer.count }

    /// Returns every complete message in the buffer. Throws on a length outside 1...16_777_216
    /// (the caller then drops the connection).
    mutating func feed(_ data: Data) throws -> [(type: UInt8, payload: Data)] {
        buffer.append(contentsOf: data)
        var out: [(type: UInt8, payload: Data)] = []
        var offset = 0
        while buffer.count - offset >= 4 {
            let n = (UInt32(buffer[offset]) << 24) | (UInt32(buffer[offset + 1]) << 16)
                | (UInt32(buffer[offset + 2]) << 8) | UInt32(buffer[offset + 3])
            if n < 1 || n > Framing.maxLength {
                buffer.removeAll()
                throw FramingError.badLength(n)
            }
            let total = 4 + Int(n)
            if buffer.count - offset < total { break }
            let type = buffer[offset + 4]
            let payload = Data(buffer[(offset + 5)..<(offset + total)])
            out.append((type: type, payload: payload))
            offset += total
        }
        if offset > 0 {
            buffer.removeFirst(offset)
        }
        return out
    }

    static func jsonObject(_ payload: Data) -> [String: Any]? {
        guard let obj = try? JSONSerialization.jsonObject(with: payload, options: []) else { return nil }
        return obj as? [String: Any]
    }
}
