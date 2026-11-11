import Foundation
import Network
import CoreGraphics

/// TCP 47777 server, one PC at a time (CONTRACT sections 1-2). All state lives on `queue`;
/// callbacks marked "main" are delivered on the main queue.
///
/// Who gets in: the USB cable always (it arrives on the phone's own loopback address). Anything else only
/// while "Allow Wi-Fi connections" is on, and it gets no picture, no settings and no log lines until it has
/// proved the pairing code. A connected PC is never pushed out by a newcomer.
final class StreamServer {
    static let port: UInt16 = 47777
    static let maxQueuedFrames = 3
    static let maxQueuedBytes = 2 * 1024 * 1024
    static let deadAfter: TimeInterval = 10

    let queue = DispatchQueue(label: "tacocam.net")

    // main
    /// A PC that may use the camera is connected: "USB" or "Wi-Fi 192.168.1.5".
    var onConnected: ((String) -> Void)?
    var onDisconnected: (() -> Void)?
    /// A connection was turned away (text for the phone screen).
    var onRefused: ((String) -> Void)?
    var onHello: (([String: Any]) -> Void)?
    var onSet: (([String: Any]) -> Void)?
    var onFocusPoint: ((CGPoint) -> Void)?
    var onVideoStart: (() -> Void)?
    var onStats: ((_ fps: Double, _ mbps: Double, _ dropped: Int) -> Void)?
    var onListening: ((Bool) -> Void)?
    // net queue
    var onKeyframeRequest: (() -> Void)?

    private var listener: NWListener?
    private var listenerReady = false
    private var connection: NWConnection?
    private var connId = 0
    // who may connect
    private var wifiAllowed = false
    private var wifiCode = ""
    private var wrongCodes = WrongCodeLog()
    private var peerHost = ""
    private var peerLocal = false
    /// USB, or Wi-Fi after the pairing code was proved. Nothing is sent or obeyed before.
    private var authed = false
    /// onConnected was delivered for this connection.
    private var announced = false
    private var challenge: Data?
    private var pendingHello: [String: Any]?
    private var acceptedAt = Date()
    private var parser = FrameParser()
    private var gotHello = false
    private var videoStarted = false
    private var pendingFrames = 0
    private var pendingBytes = 0
    private var congested = false
    private var waitingForKey = false
    private var lastFormat: String?
    private var lastRx = Date()
    private var timer: DispatchSourceTimer?
    private var framesSent = 0
    private var bytesSent = 0
    private var dropped = 0
    private var lastTick = Date()

    // MARK: public (any thread)

    func start() {
        queue.async {
            self.startListener()
            if self.timer == nil {
                let t = DispatchSource.makeTimerSource(queue: self.queue)
                t.schedule(deadline: .now() + 1, repeating: 1)
                t.setEventHandler { [weak self] in self?.tick() }
                t.resume()
                self.timer = t
            }
        }
    }

    /// After the app comes back to the foreground: iOS may have torn the listener down.
    func restartIfNeeded() {
        queue.async {
            if self.listener == nil || !self.listenerReady {
                self.listener?.cancel()
                self.listener = nil
                self.listenerReady = false
                self.startListener()
            }
        }
    }

    /// The phone's "Allow Wi-Fi connections" switch and pairing code. A Wi-Fi PC that connected under the
    /// old values is dropped; the USB connection is left alone.
    func setWifi(allowed: Bool, code: String) {
        queue.async {
            let c = Pairing.normalize(code)
            guard allowed != self.wifiAllowed || c != self.wifiCode else { return }
            self.wifiAllowed = allowed
            self.wifiCode = c
            if self.connection != nil && !self.peerLocal {
                self.close(reason: "Wi-Fi was switched off or the pairing code changed on the iPhone")
            }
        }
    }

    func send(_ type: MsgType, json: [String: Any]) {
        guard let data = Framing.encodeJSON(type, json) else { return }
        queue.async { self.sendRaw(data, video: false) }
    }

    func sendLog(_ line: String) {
        let data = Framing.encodeLog(line)
        queue.async { self.sendRaw(data, video: false) }
    }

    /// Starts VIDEO (after the PC's SET); the first frame sent is a keyframe.
    func startVideo() {
        queue.async { self.startVideoNow() }
    }

    func sendVideo(_ f: EncodedFrame) {
        queue.async { self.handleFrame(f) }
    }

    // MARK: listener

    private func startListener() {
        guard listener == nil else { return }
        let tcp = NWProtocolTCP.Options()
        tcp.noDelay = true
        let params = NWParameters(tls: nil, tcp: tcp)
        params.allowLocalEndpointReuse = true
        guard let port = NWEndpoint.Port(rawValue: StreamServer.port) else { return }
        let l: NWListener
        do {
            l = try NWListener(using: params, on: port)
        } catch {
            NSLog("%@", "TacoCam: listener failed: \(error)")
            queue.asyncAfter(deadline: .now() + 2) { self.startListener() }
            return
        }
        // No Bonjour advertisement: the PC never looked for it, it only told the network where the camera is.
        l.stateUpdateHandler = { [weak self, weak l] st in
            guard let self = self, let l = l, l === self.listener else { return }
            switch st {
            case .ready:
                self.listenerReady = true
                DispatchQueue.main.async { self.onListening?(true) }
            case .failed(let err):
                NSLog("%@", "TacoCam: listener failed: \(err)")
                self.listenerReady = false
                l.cancel()
                self.listener = nil
                DispatchQueue.main.async { self.onListening?(false) }
                self.queue.asyncAfter(deadline: .now() + 2) { self.startListener() }
            case .cancelled:
                self.listenerReady = false
            default:
                break
            }
        }
        l.newConnectionHandler = { [weak self] c in
            self?.accept(c)
        }
        listener = l
        l.start(queue: queue)
    }

    // MARK: connection

    private func accept(_ c: NWConnection) {
        let peer = Pairing.peer(c.endpoint)
        let now = Date()
        let decision = Pairing.decide(
            local: peer.local,
            wifiAllowed: wifiAllowed,
            codeSet: wifiCode.count == Pairing.codeLength,
            locked: wrongCodes.isLocked(peer.host, now: now),
            busy: connection != nil && authed,
            quiet: now.timeIntervalSince(lastRx) >= Pairing.quietAfter)
        if decision != .accept {
            c.cancel()
            let why: String
            switch decision {
            case .refuseWifiOff:
                why = "Wi-Fi connections are off (Settings > Wi-Fi)"
            case .refuseLocked:
                why = "too many wrong pairing codes, it has to wait a minute"
            default:
                why = "a PC is already connected"
            }
            let text = "Refused a connection from \(peer.host): \(why)"
            DispatchQueue.main.async { self.onRefused?(text) }
            return
        }
        if connection != nil {
            close(reason: "a new PC connection replaced it")
        }
        connId += 1
        let id = connId
        connection = c
        peerHost = peer.host
        peerLocal = peer.local
        authed = peer.local
        announced = false
        challenge = nil
        pendingHello = nil
        acceptedAt = now
        parser = FrameParser()
        gotHello = false
        videoStarted = false
        pendingFrames = 0
        pendingBytes = 0
        congested = false
        waitingForKey = false
        lastFormat = nil
        lastRx = Date()
        framesSent = 0
        bytesSent = 0
        dropped = 0
        c.stateUpdateHandler = { [weak self] st in
            guard let self = self, id == self.connId else { return }
            switch st {
            case .ready:
                if self.authed { self.announce() }   // Wi-Fi: announced once the pairing code is proved
            case .failed, .cancelled:
                self.close(reason: nil)
            default:
                break
            }
        }
        c.start(queue: queue)
        receive(c, id: id)
    }

    private func receive(_ c: NWConnection, id: Int) {
        c.receive(minimumIncompleteLength: 1, maximumLength: 65536) { [weak self] data, _, isComplete, error in
            guard let self = self, id == self.connId else { return }
            if let data = data, !data.isEmpty {
                self.lastRx = Date()
                let msgs: [(type: UInt8, payload: Data)]
                do {
                    msgs = try self.parser.feed(data)
                } catch {
                    self.sendLog("Protocol error (bad message length), closing the connection")
                    self.close(reason: nil)
                    return
                }
                for m in msgs {
                    self.handle(type: m.type, payload: m.payload)
                    if id != self.connId { return }
                }
            }
            if isComplete || error != nil {
                self.close(reason: nil)
                return
            }
            self.receive(c, id: id)
        }
    }

    private func announce() {
        guard connection != nil, !announced else { return }
        announced = true
        let label = peerLocal ? "USB" : "Wi-Fi \(peerHost)"
        DispatchQueue.main.async { self.onConnected?(label) }
    }

    /// A Wi-Fi connection before the pairing code is proved: HELLO gets a challenge, AUTH is checked,
    /// everything else is dropped (CONTRACT section 2, "Pairing").
    private func handleBeforePairing(_ t: MsgType, payload: Data) {
        switch t {
        case .hello:
            pendingHello = FrameParser.jsonObject(payload) ?? [:]
            if challenge == nil {
                let nonce = Pairing.newNonce()
                challenge = nonce
                if let msg = Framing.encodeJSON(.auth, ["nonce": Pairing.hex(nonce)]) {
                    sendRaw(msg, video: false, beforePairing: true)
                }
            }
        case .auth:
            guard let phoneNonce = challenge else { return }
            let obj = FrameParser.jsonObject(payload) ?? [:]
            let pcNonce = (obj["nonce"] as? String).flatMap { Pairing.unhex($0) } ?? Data()
            let mac = (obj["mac"] as? String).flatMap { Pairing.unhex($0) } ?? Data()
            guard Pairing.check(mac, code: wifiCode, role: "pc", phoneNonce: phoneNonce, pcNonce: pcNonce) else {
                wrongCodes.wrong(peerHost, now: Date())
                let text = "Refused \(peerHost): wrong pairing code"
                DispatchQueue.main.async { self.onRefused?(text) }
                close(reason: "wrong pairing code")
                return
            }
            wrongCodes.right(peerHost)
            authed = true
            // Prove the code back, so the PC knows this is the phone and not something else at its address.
            let proof = Pairing.proof(code: wifiCode, role: "phone", phoneNonce: phoneNonce, pcNonce: pcNonce)
            if let msg = Framing.encodeJSON(.auth, ["mac": Pairing.hex(proof)]) {
                sendRaw(msg, video: false)
            }
            announce()
            acceptHello(pendingHello ?? [:])
            pendingHello = nil
        default:
            break
        }
    }

    private func acceptHello(_ obj: [String: Any]) {
        if let proto = obj["proto"] as? Int, proto != 1 {
            sendLog("PC speaks protocol \(proto), this app speaks 1")
        }
        gotHello = true
        let id = connId
        DispatchQueue.main.async { self.onHello?(obj) }
        // Video starts after the PC's SET; if it never comes, start anyway after 3 s.
        queue.asyncAfter(deadline: .now() + 3) {
            if id == self.connId && !self.videoStarted { self.startVideoNow() }
        }
    }

    private func handle(type: UInt8, payload: Data) {
        guard let t = MsgType(rawValue: type) else { return }  // unknown types are ignored
        if !authed {
            handleBeforePairing(t, payload: payload)
            return
        }
        switch t {
        case .hello:
            acceptHello(FrameParser.jsonObject(payload) ?? [:])
        case .set:
            guard let obj = FrameParser.jsonObject(payload) else {
                sendLog("SET ignored: not a JSON object")
                return
            }
            DispatchQueue.main.async { self.onSet?(obj) }
        case .keyframe:
            onKeyframeRequest?()
        case .focusPoint:
            guard let obj = FrameParser.jsonObject(payload),
                  let x = (obj["x"] as? NSNumber)?.doubleValue,
                  let y = (obj["y"] as? NSNumber)?.doubleValue else {
                sendLog("FOCUS_POINT ignored: needs {\"x\":0..1,\"y\":0..1}")
                return
            }
            let p = CGPoint(x: min(max(x, 0), 1), y: min(max(y, 0), 1))
            DispatchQueue.main.async { self.onFocusPoint?(p) }
        case .ping:
            sendRaw(Framing.encode(.pong, payload: payload), video: false)
        case .state, .video, .pong, .log, .auth:
            break  // phone -> PC types (and AUTH once paired); ignore
        }
    }

    private func close(reason: String?) {
        guard let c = connection else { return }
        let wasAnnounced = announced
        connection = nil
        connId += 1
        videoStarted = false
        gotHello = false
        authed = false
        announced = false
        challenge = nil
        pendingHello = nil
        pendingFrames = 0
        pendingBytes = 0
        if let r = reason {
            c.send(content: Framing.encodeLog("Closing: \(r)"), completion: .contentProcessed { _ in c.cancel() })
        } else {
            c.cancel()
        }
        if wasAnnounced {
            DispatchQueue.main.async { self.onDisconnected?() }
        }
    }

    /// Nothing goes to a connection that has not proved the pairing code, except the pairing question itself.
    private func sendRaw(_ data: Data, video: Bool, beforePairing: Bool = false) {
        guard let c = connection, authed || beforePairing else { return }
        let id = connId
        let n = data.count
        if video {
            pendingFrames += 1
            pendingBytes += n
        }
        c.send(content: data, completion: .contentProcessed { [weak self] err in
            guard let self = self, id == self.connId else { return }
            if video {
                self.pendingFrames = max(0, self.pendingFrames - 1)
                self.pendingBytes = max(0, self.pendingBytes - n)
            }
            if err != nil { self.close(reason: nil) }
        })
    }

    private func startVideoNow() {
        guard connection != nil, authed, !videoStarted else { return }
        videoStarted = true
        waitingForKey = true
        congested = false
        lastFormat = nil
        onKeyframeRequest?()
        DispatchQueue.main.async { self.onVideoStart?() }
    }

    /// Back-pressure: with more than 3 frames or 2 MB unsent, drop non-key frames until the queue
    /// drains, then the next frame sent is a keyframe.
    private func handleFrame(_ f: EncodedFrame) {
        guard connection != nil, authed, videoStarted else { return }
        if waitingForKey {
            if !f.isKeyframe {
                dropped += 1
                return
            }
            waitingForKey = false
        }
        if congested {
            if f.isKeyframe {
                congested = false
            } else if pendingFrames == 0 {
                congested = false
                waitingForKey = true
                onKeyframeRequest?()
                dropped += 1
                return
            } else {
                dropped += 1
                return
            }
        } else if (pendingFrames > StreamServer.maxQueuedFrames || pendingBytes > StreamServer.maxQueuedBytes)
                    && !f.isKeyframe {
            congested = true
            dropped += 1
            return
        }
        var flags: UInt8 = f.isKeyframe ? Framing.flagKeyframe : 0
        let fmt = "\(f.codec) \(f.width)x\(f.height)"
        if fmt != lastFormat {
            flags |= Framing.flagFormatChanged
            lastFormat = fmt
        }
        let msg = Framing.encodeVideo(flags: flags, ptsUs: f.ptsUs, annexB: f.data)
        sendRaw(msg, video: true)
        framesSent += 1
        bytesSent += msg.count
    }

    private func tick() {
        let now = Date()
        let dt = max(0.001, now.timeIntervalSince(lastTick))
        lastTick = now
        let fps = Double(framesSent) / dt
        let mbps = Double(bytesSent) * 8 / 1_000_000 / dt
        framesSent = 0
        bytesSent = 0
        let d = dropped
        if connection != nil && now.timeIntervalSince(lastRx) > StreamServer.deadAfter {
            close(reason: "nothing heard from the PC for \(Int(StreamServer.deadAfter)) s")
        }
        if connection != nil && !authed && now.timeIntervalSince(acceptedAt) > Pairing.proveWithin {
            close(reason: "no pairing code received")
        }
        let connected = connection != nil && authed
        DispatchQueue.main.async { self.onStats?(connected ? fps : 0, connected ? mbps : 0, d) }
    }
}
