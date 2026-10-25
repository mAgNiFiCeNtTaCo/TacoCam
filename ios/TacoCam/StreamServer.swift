import Foundation
import Network
import CoreGraphics

/// TCP 47777 server, one PC at a time (CONTRACT sections 1-2). All state lives on `queue`;
/// callbacks marked "main" are delivered on the main queue.
final class StreamServer {
    static let port: UInt16 = 47777
    static let maxQueuedFrames = 3
    static let maxQueuedBytes = 2 * 1024 * 1024
    static let deadAfter: TimeInterval = 10

    let queue = DispatchQueue(label: "tacocam.net")

    // main
    var onConnected: (() -> Void)?
    var onDisconnected: (() -> Void)?
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
    private var useBonjour = true
    private var connection: NWConnection?
    private var connId = 0
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
        if useBonjour {
            l.service = NWListener.Service(name: "Taco Cam", type: "_tacocam._tcp")
        }
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
                // Bonjour can fail on its own (local network permission); listen without it next time.
                self.useBonjour = false
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
        if connection != nil {
            close(reason: "a new PC connection replaced it")
        }
        connId += 1
        let id = connId
        connection = c
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
                DispatchQueue.main.async { self.onConnected?() }
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

    private func handle(type: UInt8, payload: Data) {
        guard let t = MsgType(rawValue: type) else { return }  // unknown types are ignored
        switch t {
        case .hello:
            let obj = FrameParser.jsonObject(payload) ?? [:]
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
        case .state, .video, .pong, .log:
            break  // phone -> PC types; ignore if echoed
        }
    }

    private func close(reason: String?) {
        guard let c = connection else { return }
        connection = nil
        connId += 1
        videoStarted = false
        gotHello = false
        pendingFrames = 0
        pendingBytes = 0
        if let r = reason {
            c.send(content: Framing.encodeLog("Closing: \(r)"), completion: .contentProcessed { _ in c.cancel() })
        } else {
            c.cancel()
        }
        DispatchQueue.main.async { self.onDisconnected?() }
    }

    private func sendRaw(_ data: Data, video: Bool) {
        guard let c = connection else { return }
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
        guard connection != nil, !videoStarted else { return }
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
        guard connection != nil, videoStarted else { return }
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
        let connected = connection != nil
        DispatchQueue.main.async { self.onStats?(connected ? fps : 0, connected ? mbps : 0, d) }
    }
}
