"""usbmux client against a small fake usbmuxd (and once against the real one, when it runs)."""
import os
import plistlib
import socket
import struct
import sys
import threading
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from tacocam import usbmux  # noqa: E402


class FakeUsbmuxd:
    """Speaks the usbmuxd plist protocol on 127.0.0.1:<random>.

    devices: {device_id: {"serial": str, "connection": "USB"|"Network", "ports": {phone_port: (host, tcp_port)}}}
    A Connect to a port that is not in "ports" (or whose target refuses) answers Result 3 (refused);
    otherwise the socket becomes a byte pipe to the target, like the real usbmuxd does."""

    def __init__(self, devices=None):
        self.devices = devices if devices is not None else {}
        self.requests = []
        self.listeners = []
        self._srv = socket.socket()
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(16)
        self._srv.settimeout(0.2)
        self.address = self._srv.getsockname()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._socks = []
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def close(self):
        self._stop.set()
        self._srv.close()
        with self._lock:
            socks = list(self._socks)
        for s in socks:
            try:
                s.close()
            except OSError:
                pass
        self._thread.join(2)

    def _accept(self):
        while not self._stop.is_set():
            try:
                c, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self._lock:
                self._socks.append(c)
            threading.Thread(target=self._client, args=(c,), daemon=True).start()

    @staticmethod
    def _send(c, obj, tag):
        body = plistlib.dumps(obj)
        c.sendall(struct.pack("<IIII", 16 + len(body), 1, 8, tag) + body)

    def _entry(self, did, d):
        return {"DeviceID": did, "MessageType": "Attached",
                "Properties": {"ConnectionType": d["connection"], "DeviceID": did, "SerialNumber": d["serial"],
                               "ProductID": 4776}}

    def attach(self, did, serial, connection="USB", ports=None):
        with self._lock:
            self.devices[did] = {"serial": serial, "connection": connection, "ports": ports or {}}
            listeners = list(self.listeners)
        for c in listeners:
            try:
                self._send(c, self._entry(did, self.devices[did]), 0)
            except OSError:
                pass

    def detach(self, did):
        with self._lock:
            self.devices.pop(did, None)
            listeners = list(self.listeners)
        for c in listeners:
            try:
                self._send(c, {"MessageType": "Detached", "DeviceID": did}, 0)
            except OSError:
                pass

    def _client(self, c):
        try:
            hdr = usbmux._recv_exact(c, 16)
            length, version, message, tag = struct.unpack("<IIII", hdr)
            req = plistlib.loads(usbmux._recv_exact(c, length - 16))
            self.requests.append((version, message, tag, req))
            kind = req.get("MessageType")
            if kind == "ListDevices":
                with self._lock:
                    lst = [self._entry(did, d) for did, d in self.devices.items()]
                self._send(c, {"DeviceList": lst}, tag)
                c.close()
            elif kind == "Listen":
                self._send(c, {"MessageType": "Result", "Number": 0}, tag)
                with self._lock:
                    self.listeners.append(c)
            elif kind == "Connect":
                did = req.get("DeviceID")
                port = usbmux.htons(req.get("PortNumber"))  # htons is its own inverse
                with self._lock:
                    dev = self.devices.get(did)
                if dev is None:
                    self._send(c, {"MessageType": "Result", "Number": 2}, tag)
                    c.close()
                    return
                target = dev["ports"].get(port)
                try:
                    if target is None:
                        raise ConnectionRefusedError
                    up = socket.create_connection(target, timeout=0.4)
                    up.settimeout(None)
                except OSError:
                    self._send(c, {"MessageType": "Result", "Number": 3}, tag)
                    c.close()
                    return
                self._send(c, {"MessageType": "Result", "Number": 0}, tag)
                with self._lock:
                    self._socks.append(up)
                threading.Thread(target=self._pipe, args=(c, up), daemon=True).start()
                threading.Thread(target=self._pipe, args=(up, c), daemon=True).start()
            else:
                self._send(c, {"MessageType": "Result", "Number": 1}, tag)
                c.close()
        except (OSError, usbmux.UsbmuxError):
            try:
                c.close()
            except OSError:
                pass

    @staticmethod
    def _pipe(a, b):
        try:
            while True:
                data = a.recv(1 << 16)
                if not data:
                    break
                b.sendall(data)
        except OSError:
            pass
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


@pytest.fixture
def mux():
    m = FakeUsbmuxd()
    yield m
    m.close()


def test_htons():
    assert usbmux.htons(47777) == 0xA1BA
    assert usbmux.htons(usbmux.htons(47777)) == 47777


def test_pack_header():
    msg = usbmux.pack({"MessageType": "ListDevices"}, 7)
    length, version, message, tag = struct.unpack("<IIII", msg[:16])
    assert (length, version, message, tag) == (len(msg), 1, 8, 7)
    assert plistlib.loads(msg[16:])["MessageType"] == "ListDevices"


def test_list_devices(mux):
    assert usbmux.list_devices(mux.address) == []
    mux.attach(5, "00008030-001A2B3C4D5E6F70", "USB")
    mux.attach(9, "WIFI-PHONE", "Network")
    devs = usbmux.list_devices(mux.address)
    assert {(d["id"], d["serial"], d["connection"]) for d in devs} == {
        (5, "00008030-001A2B3C4D5E6F70", "USB"), (9, "WIFI-PHONE", "Network")}
    assert [d["id"] for d in usbmux.usb_devices(mux.address)] == [5]
    version, message, tag, req = mux.requests[-1]
    assert (version, message) == (1, 8)
    assert req["MessageType"] == "ListDevices" and req["ProgName"] == "TacoCam"
    assert req["ClientVersionString"] == "TacoCam"


def test_connect_pipes_bytes(mux):
    echo = socket.socket()
    echo.bind(("127.0.0.1", 0))
    echo.listen(1)

    def serve():
        c, _ = echo.accept()
        data = c.recv(100)
        c.sendall(b"echo:" + data)
        c.close()
    threading.Thread(target=serve, daemon=True).start()
    mux.attach(3, "SERIAL3", "USB", ports={47777: echo.getsockname()})
    s = usbmux.connect(3, 47777, mux.address)
    s.sendall(b"hello")
    s.settimeout(2)
    assert s.recv(100) == b"echo:hello"
    s.close()
    req = mux.requests[-1][3]
    assert req["MessageType"] == "Connect" and req["DeviceID"] == 3 and req["PortNumber"] == 0xA1BA
    echo.close()


def test_connect_refused(mux):
    mux.attach(3, "SERIAL3", "USB")
    with pytest.raises(usbmux.ConnectRefused):
        usbmux.connect(3, 47777, mux.address)


def test_connect_bad_device(mux):
    with pytest.raises(usbmux.UsbmuxError) as e:
        usbmux.connect(42, 47777, mux.address)
    assert not isinstance(e.value, usbmux.ConnectRefused)


def test_unreachable_usbmuxd():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    addr = s.getsockname()
    s.close()  # nothing listens there now
    with pytest.raises(usbmux.UsbmuxError):
        usbmux.list_devices(addr, timeout=1)


def test_listen_attach_detach(mux):
    events = []
    got = threading.Event()

    def on_event(kind, info):
        events.append((kind, info["id"], info["serial"]))
        got.set()
    listener = usbmux.Listener(on_event, mux.address).start()
    assert listener.ready.wait(2) and listener.error is None
    for _ in range(50):
        if mux.listeners:
            break
        time.sleep(0.02)
    mux.attach(7, "SERIAL7", "USB")
    assert got.wait(2)
    got.clear()
    mux.detach(7)
    assert got.wait(2)
    listener.stop()
    assert events == [("Attached", 7, "SERIAL7"), ("Detached", 7, "")]


def test_short_serial():
    assert usbmux.short_serial("00008030-001A2B3C4D5E6F70") == "0000...6F70"
    assert usbmux.short_serial("ABC") == "ABC"


def _real_usbmuxd_up():
    try:
        socket.create_connection(usbmux.ADDRESS, timeout=0.5).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _real_usbmuxd_up(), reason="Apple Mobile Device Service not running")
def test_real_usbmuxd_lists_devices():
    devs = usbmux.list_devices()
    assert isinstance(devs, list)
    for d in devs:
        assert d["connection"] in ("USB", "Network") and d["id"] is not None
