"""Minimal usbmuxd client (CONTRACT section 1): list iPhones, open a TCP pipe to a port on one, watch plug/unplug.

On Windows the Apple Mobile Device Service listens on 127.0.0.1:27015. Each request: 16-byte little-endian
header (u32 total length incl. header, u32 version=1, u32 message=8 (plist), u32 tag) + XML plist.
"""
import plistlib
import socket
import struct
import threading

ADDRESS = ("127.0.0.1", 27015)
_HEADER = struct.Struct("<IIII")
_VERSION = 1
_MSG_PLIST = 8
_MAX_REPLY = 4 * 1024 * 1024

RESULT_OK = 0
RESULT_BADDEV = 2
RESULT_REFUSED = 3
RESULT_BADVERSION = 6

_CLIENT = {"ClientVersionString": "TacoCam", "ProgName": "TacoCam", "kLibUSBMuxVersion": 3}


class UsbmuxError(Exception):
    """usbmuxd is not reachable or answered something unexpected."""


class ConnectRefused(UsbmuxError):
    """The iPhone is there but nothing listens on that port (Taco Cam app not open)."""


def htons(port):
    return ((port & 0xFF) << 8) | ((port >> 8) & 0xFF)


def pack(obj, tag):
    body = plistlib.dumps(obj, fmt=plistlib.FMT_XML)
    return _HEADER.pack(_HEADER.size + len(body), _VERSION, _MSG_PLIST, tag) + body


def _recv_exact(sock, n):
    chunks = []
    while n:
        chunk = sock.recv(n)
        if not chunk:
            raise UsbmuxError("usbmuxd closed the connection")
        chunks.append(chunk)
        n -= len(chunk)
    return b"".join(chunks)


def read_message(sock):
    """-> (tag, plist dict)"""
    length, _version, _message, tag = _HEADER.unpack(_recv_exact(sock, _HEADER.size))
    if length < _HEADER.size or length > _MAX_REPLY:
        raise UsbmuxError(f"bad usbmuxd reply length {length}")
    body = _recv_exact(sock, length - _HEADER.size)
    try:
        obj = plistlib.loads(body)
    except Exception as e:
        raise UsbmuxError(f"bad usbmuxd plist: {e}") from None
    if not isinstance(obj, dict):
        raise UsbmuxError("usbmuxd reply is not a dictionary")
    return tag, obj


def device_info(entry):
    """Normalise one DeviceList / Attached entry."""
    props = entry.get("Properties") or {}
    return {
        "id": entry.get("DeviceID", props.get("DeviceID")),
        "serial": props.get("SerialNumber") or "",
        "connection": props.get("ConnectionType") or "",
        "properties": props,
    }


def short_serial(serial):
    serial = str(serial or "")
    return serial if len(serial) <= 12 else f"{serial[:4]}...{serial[-4:]}"


class _Session:
    def __init__(self, address, timeout):
        self.address = tuple(address or ADDRESS)
        try:
            self.sock = socket.create_connection(self.address, timeout=timeout)
        except OSError as e:
            raise UsbmuxError(f"cannot reach usbmuxd at {self.address[0]}:{self.address[1]} ({e})") from None
        self.sock.settimeout(timeout)
        self.tag = 0

    def request(self, message_type, **fields):
        self.tag += 1
        obj = {"MessageType": message_type, **_CLIENT, **fields}
        try:
            self.sock.sendall(pack(obj, self.tag))
            while True:
                tag, reply = read_message(self.sock)
                if tag == self.tag or reply.get("MessageType") not in ("Attached", "Detached", "Paired"):
                    return reply
        except OSError as e:
            raise UsbmuxError(f"usbmuxd {message_type} failed ({e})") from None

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def list_devices(address=None, timeout=3.0):
    """All devices usbmuxd knows: [{"id", "serial", "connection" ("USB"/"Network"), "properties"}]."""
    s = _Session(address, timeout)
    try:
        reply = s.request("ListDevices")
    finally:
        s.close()
    if "DeviceList" not in reply:
        raise UsbmuxError(f"unexpected ListDevices reply: {reply.get('MessageType')}")
    return [device_info(d) for d in reply.get("DeviceList") or []]


def usb_devices(address=None, timeout=3.0):
    return [d for d in list_devices(address, timeout) if d["connection"] == "USB"]


def connect(device_id, port, address=None, timeout=3.0):
    """Open a raw TCP pipe to port on the device. Returns a connected socket (blocking, no timeout).

    Raises ConnectRefused when nothing listens on the phone, UsbmuxError for other failures."""
    s = _Session(address, timeout)
    try:
        reply = s.request("Connect", DeviceID=int(device_id), PortNumber=htons(int(port)))
    except Exception:
        s.close()
        raise
    number = reply.get("Number")
    if reply.get("MessageType") != "Result" or number != RESULT_OK:
        s.close()
        if number == RESULT_REFUSED:
            raise ConnectRefused(f"port {port} refused on device {device_id}")
        raise UsbmuxError(f"usbmuxd Connect failed (result {number})")
    s.sock.settimeout(None)
    return s.sock


class Listener:
    """Background thread that calls on_event("Attached"|"Detached", info) as phones come and go."""

    def __init__(self, on_event, address=None, timeout=3.0):
        self.on_event = on_event
        self.address = address
        self.timeout = timeout
        self._stop = threading.Event()
        self._sock = None
        self._thread = None
        self.error = None
        self.ready = threading.Event()

    def start(self):
        self._thread = threading.Thread(target=self._run, name="usbmux-listen", daemon=True)
        self._thread.start()
        return self

    def _run(self):
        try:
            s = _Session(self.address, self.timeout)
            self._sock = s.sock
            reply = s.request("Listen")
            if reply.get("MessageType") != "Result" or reply.get("Number") != RESULT_OK:
                raise UsbmuxError(f"usbmuxd Listen failed (result {reply.get('Number')})")
            s.sock.settimeout(None)
            self.ready.set()
            while not self._stop.is_set():
                _tag, msg = read_message(s.sock)
                kind = msg.get("MessageType")
                if kind == "Attached":
                    self.on_event(kind, device_info(msg))
                elif kind == "Detached":
                    self.on_event(kind, {"id": msg.get("DeviceID"), "serial": "", "connection": "",
                                         "properties": {}})
        except (UsbmuxError, OSError) as e:
            if not self._stop.is_set():
                self.error = e
        finally:
            self.ready.set()

    def stop(self):
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(1.0)
