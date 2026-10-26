"""Connection to the phone (CONTRACT sections 1 and 2): finds it, connects, keeps it alive, reconnects forever.

usb:  first USB iPhone that usbmuxd lists, its port 47777 (refused = status "no_app", retry every 1 s).
wifi: TCP to host:47777 ("host:port" also accepted, used by tests and the fake phone on another port).
Handshake: PC HELLO -> phone HELLO + STATE -> PC sends one SET with all phone settings -> VIDEO.
PING every 1 s; nothing from the phone for 5 s = dead, reconnect.

Callbacks (all called on the link's reader thread, keep them quick):
  on_hello(dict), on_state(dict), on_video(flags, pts_us, data, nbytes), on_log(str),
  on_connected(), on_disconnected(), get_phone_settings() -> dict (full phone settings for the first SET)
"""
import queue
import select
import socket
import struct
import threading
import time

from . import protocol, usbmux

PING_INTERVAL = 1.0
DEAD_AFTER = 5.0
RETRY = 1.0


def split_host(text, default_port=protocol.PORT):
    text = (text or "").strip()
    if not text:
        return "", default_port
    if text.startswith("["):                       # [ipv6]:port
        host, _, rest = text[1:].partition("]")
        port = rest[1:] if rest.startswith(":") else ""
    elif text.count(":") == 1:
        host, port = text.split(":")
    else:
        host, port = text, ""
    try:
        port = int(port) if port else default_port
    except ValueError:
        port = default_port
    return host.strip(), port


class Link:
    def __init__(self, connect="usb", wifi_host="", port=protocol.PORT, usbmux_address=None,
                 log=None, **callbacks):
        self._lock = threading.Lock()
        self._connect = connect
        self._wifi_host = wifi_host
        self.port = port
        self.usbmux_address = usbmux_address
        self.log = log or (lambda s: None)
        self.cb = callbacks
        self._stop = threading.Event()
        self._retarget = threading.Event()
        self._thread = None
        self._sock = None
        self._out = None                 # queue of bytes for the writer thread, per session
        # status (read by the engine)
        self.state = "searching"
        self.transport = None
        self.device_name = None
        self.error = None
        self.rtt_ms = None
        self.hello = None
        self._last_logged = None

    # -- public ----------------------------------------------------------------------------------
    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="tacocam-link", daemon=True)
        self._thread.start()
        return self

    def signal_stop(self):
        """Ask the thread to end (closes the socket) without waiting for it."""
        self._stop.set()
        self._retarget.set()
        self._close_sock()

    def stop(self, timeout=1.5):
        self.signal_stop()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def set_target(self, connect=None, wifi_host=None):
        """Change usb/wifi or the phone address: drops the current connection and reconnects."""
        with self._lock:
            changed = False
            if connect is not None and connect != self._connect:
                self._connect, changed = connect, True
            if wifi_host is not None and wifi_host != self._wifi_host:
                self._wifi_host = wifi_host
                changed = changed or self._connect == "wifi"
        if changed:
            self._retarget.set()
            self._close_sock()

    def send(self, mtype, payload=b""):
        """Queue one message for the phone. Returns False when not connected (nothing sent)."""
        out = self._out
        if out is None or self.state != "connected":
            return False
        out.put(protocol.encode(mtype, payload))
        return True

    def send_json(self, mtype, obj):
        out = self._out
        if out is None or self.state != "connected":
            return False
        out.put(protocol.encode_json(mtype, obj))
        return True

    def send_set(self, phone_settings):
        return self.send_json(protocol.SET, phone_settings)

    def send_keyframe(self):
        return self.send(protocol.KEYFRAME)

    def send_focus(self, x, y):
        return self.send_json(protocol.FOCUS_POINT, {"x": round(float(x), 5), "y": round(float(y), 5)})

    # -- internals -------------------------------------------------------------------------------
    def _call(self, name, *args):
        fn = self.cb.get(name)
        if fn is not None:
            try:
                return fn(*args)
            except Exception as e:  # a callback bug must not kill the link
                self.log(f"Internal error in {name}: {e!r}")
        return None

    def _set_state(self, state, transport=None, device_name=None, error=None, say=None):
        self.state = state
        self.transport = transport
        self.device_name = device_name
        self.error = error
        if say and say != self._last_logged:
            self._last_logged = say
            self.log(say)

    def _close_sock(self):
        s = self._sock
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass

    def _wait(self, seconds):
        """Sleep, but wake at once for stop() or a target change. True = keep going."""
        self._retarget.wait(seconds)
        self._retarget.clear()
        return not self._stop.is_set()

    def _run(self):
        while not self._stop.is_set():
            with self._lock:
                mode, host_text = self._connect, self._wifi_host
            sock, transport, name = None, None, None
            if mode == "wifi":
                host, port = split_host(host_text, self.port)
                if not host:
                    self._set_state("error", "wifi", None, "Wi-Fi mode needs the iPhone's IP address",
                                    say="Wi-Fi mode: type the iPhone's IP address (shown in the Taco Cam app)")
                    if not self._wait(RETRY):
                        break
                    continue
                self._set_state("searching", "wifi", None, None, say=f"Looking for the iPhone at {host}:{port}")
                try:
                    sock = socket.create_connection((host, port), timeout=1.0)
                    transport, name = "wifi", host
                except ConnectionRefusedError:
                    self._set_state("no_app", "wifi", host, None,
                                    say=f"{host} answers but Taco Cam is not open there")
                except OSError:
                    self._set_state("searching", "wifi", None, None)
            else:
                try:
                    devices = usbmux.usb_devices(self.usbmux_address, timeout=1.0)
                except usbmux.UsbmuxError as e:
                    self._set_state("error", "usb", None,
                                    "Apple Mobile Device Service is not running (install Apple Devices or iTunes)",
                                    say=f"Cannot reach Apple's USB service: {e}")
                    devices = None
                if devices == []:
                    self._set_state("searching", "usb", None, None,
                                    say="Waiting for an iPhone on USB")
                for dev in devices or []:
                    short = usbmux.short_serial(dev["serial"]) or f"device {dev['id']}"
                    try:
                        sock = usbmux.connect(dev["id"], self.port, self.usbmux_address, timeout=1.5)
                        transport, name = "usb", short
                        break
                    except usbmux.ConnectRefused:
                        self._set_state("no_app", "usb", short, None,
                                        say=f"iPhone {short} found; open the Taco Cam app on it")
                    except usbmux.UsbmuxError as e:
                        self._set_state("error", "usb", short, str(e), say=f"USB connect failed: {e}")
            if sock is None:
                if not self._wait(RETRY):
                    break
                continue
            self._session(sock, transport, name)
            if self._stop.is_set():
                break
            self._wait(0.2)
        self._set_state("searching", None, None, None)

    def _session(self, sock, transport, name):
        self._sock = sock
        out = queue.Queue()
        self._set_state("connecting", transport, name, None, say=f"Connecting to the iPhone ({transport})")
        writer = threading.Thread(target=self._writer, args=(sock, out), name="tacocam-link-writer", daemon=True)
        writer.start()
        self._out = out
        reader = protocol.FrameReader()
        connected = False
        sent_set = False
        hello_at = None
        last_rx = time.monotonic()
        last_ping = 0.0
        reason = "connection closed"
        try:
            sock.settimeout(None)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
            out.put(protocol.encode_json(protocol.HELLO, protocol.PC_HELLO))
            while not self._stop.is_set() and not self._retarget.is_set():
                now = time.monotonic()
                if connected and now - last_ping >= PING_INTERVAL:
                    last_ping = now
                    out.put(protocol.encode(protocol.PING, struct.pack(">Q", time.monotonic_ns())))
                if now - last_rx > DEAD_AFTER:
                    reason = "no answer from the iPhone for 5 s"
                    break
                if connected and not sent_set and hello_at is not None and now - hello_at > 2.0:
                    sent_set = self._send_all_settings(out)  # phone sent HELLO but no STATE: send anyway
                readable, _, _ = select.select([sock], [], [], 0.2)
                if not readable:
                    continue
                data = sock.recv(1 << 20)
                if not data:
                    break
                last_rx = time.monotonic()
                for mtype, payload in reader.feed(data):
                    if mtype == protocol.VIDEO:
                        flags, pts, bitstream = protocol.decode_video(payload)
                        self._call("on_video", flags, pts, bitstream, len(payload) + 5)
                    elif mtype == protocol.STATE:
                        state = protocol.decode_json(payload)
                        self._call("on_state", state)
                        if connected and not sent_set:
                            sent_set = self._send_all_settings(out)
                    elif mtype == protocol.PONG:
                        if len(payload) == 8:
                            (t0,) = struct.unpack(">Q", payload)
                            rtt = (time.monotonic_ns() - t0) / 1e6
                            if 0 <= rtt < 60000:
                                self.rtt_ms = rtt if self.rtt_ms is None else self.rtt_ms * 0.7 + rtt * 0.3
                    elif mtype == protocol.HELLO:
                        hello = protocol.decode_json(payload)
                        self.hello = hello
                        if hello.get("proto") != 1:
                            self.log(f"The iPhone app speaks protocol {hello.get('proto')}, this PC 1: "
                                     "update the app or the PC program")
                        dev = hello.get("device") or name
                        connected, hello_at = True, time.monotonic()
                        self._set_state("connected", transport, str(dev), None,
                                        say=f"Connected to {dev} ({transport}, Taco Cam {hello.get('version', '?')}"
                                            f", iOS {hello.get('ios', '?')})")
                        self._call("on_hello", hello)
                        self._call("on_connected")
                    elif mtype == protocol.LOG:
                        text = bytes(payload).decode("utf-8", "replace").strip()
                        self._call("on_log", text)
                    # other types: ignored (forward compatibility)
        except protocol.ProtocolError as e:
            reason = f"protocol error: {e}"
        except (OSError, ValueError) as e:  # ValueError: select() on a socket closed by stop()
            if not self._stop.is_set():
                reason = f"connection lost ({e})"
        finally:
            self._out = None
            out.put(None)
            self._close_sock()
            self._sock = None
            writer.join(1.0)
            self.rtt_ms = None
            self.hello = None
            if connected:
                self._call("on_disconnected")
            if not self._stop.is_set():
                self.log(f"iPhone disconnected: {reason}")
                self._last_logged = None
                self._set_state("searching", transport, None, None)

    def _send_all_settings(self, out):
        settings = self._call("get_phone_settings")
        if isinstance(settings, dict):
            out.put(protocol.encode_json(protocol.SET, settings))
        return True

    @staticmethod
    def _writer(sock, out):
        while True:
            data = out.get()
            if data is None:
                return
            try:
                sock.sendall(data)
            except OSError:
                try:
                    sock.close()  # wakes the reader, which ends the session
                except OSError:
                    pass
                return
