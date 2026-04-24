"""
DMX output manager — Art-Net and sACN sender.
Packet formats are spec-exact, ported from Titan Engine v3.
Never modify the packet byte layouts without checking the spec.
"""
import socket
import threading
import queue
import logging

from models.project import OutputConfig

logger = logging.getLogger(__name__)

ARTNET_PORT = 6454
SACN_PORT = 5568


def _build_artnet_packet(universe: int, payload: bytes,
                          art_net: int = 0, art_sub: int = 0) -> bytes:
    port_addr = (art_net << 8) | (art_sub << 4) | (universe & 0x0F)
    header = bytearray(b'Art-Net\x00\x00\x50\x00\x0e\x00\x00')
    header.append(port_addr & 0xFF)
    header.append((port_addr >> 8) & 0x7F)
    header.append((len(payload) >> 8) & 0xFF)
    header.append(len(payload) & 0xFF)
    return bytes(header) + bytes(payload)


def _build_sacn_packet(universe: int, payload: bytes, sequence: int,
                        priority: int = 100, source_name: str = "Titan Engine",
                        preview: bool = False) -> bytes:
    # ANSI E1.31 (sACN) — root, framing, and DMP layer
    flags_length = 0x7000 | (110 + len(payload))
    pdu_flags_length = 0x7000 | (88 + len(payload))
    dmp_flags_length = 0x7000 | (10 + len(payload))

    name_bytes = source_name.encode('utf-8')[:63]
    name_padded = name_bytes + b'\x00' * (64 - len(name_bytes))
    opts = 0x80 if preview else 0x00

    header = bytearray([
        0x00, 0x10, 0x00, 0x00, 0x41, 0x53, 0x43, 0x2d,
        0x45, 0x31, 0x2e, 0x31, 0x37, 0x00, 0x00, 0x00,
        (flags_length >> 8) & 0xFF, flags_length & 0xFF,
        0x00, 0x00, 0x00, 0x04,
        0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88,
        0x99, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff, 0x00,
        (pdu_flags_length >> 8) & 0xFF, pdu_flags_length & 0xFF,
        0x00, 0x00, 0x00, 0x02,
    ])
    header += name_padded
    header += bytearray([
        priority & 0xFF, 0x00, 0x00, sequence & 0xFF, opts,
        (universe >> 8) & 0xFF, universe & 0xFF,
        (dmp_flags_length >> 8) & 0xFF, dmp_flags_length & 0xFF,
        0x02, 0xa1, 0x00, 0x00, 0x00, 0x01,
        ((len(payload) + 1) >> 8) & 0xFF, (len(payload) + 1) & 0xFF, 0x00,
    ])
    return bytes(header) + bytes(payload)


def _dest_ip(universe: int, net_mode: str, protocol: str, base_ip: str) -> str:
    if net_mode == "Broadcast" and protocol == "Art-Net":
        return "255.255.255.255"
    if net_mode == "Multicast" and protocol == "sACN":
        return f"239.255.{(universe >> 8) & 0xFF}.{universe & 0xFF}"
    return base_ip


class OutputManager:
    """
    Queue-based UDP sender. Accepts {universe: bytearray} dicts from the
    compositor thread and ships them on a dedicated background thread.
    Drops the oldest frame when the queue is full so the render thread
    never blocks on a slow network.
    """

    def __init__(self, config: OutputConfig):
        self.config = config
        self._queue: queue.Queue = queue.Queue(maxsize=4)
        self._sacn_seq: dict = {}
        self.packets_sent: int = 0
        self.last_error: str | None = None

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 4)
        except Exception:
            pass

        self._running = True
        self._thread = threading.Thread(target=self._send_loop, daemon=True)
        self._thread.start()

    def send(self, universes: dict):
        """
        Non-blocking. Called from the render thread.
        Drops the oldest queued frame if the sender thread is behind.
        """
        if not self.config.active:
            return
        try:
            self._queue.put_nowait(universes)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(universes)
            except queue.Empty:
                pass

    def _send_loop(self):
        while self._running:
            try:
                universes = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue

            cfg = self.config
            is_sacn = cfg.protocol == "sACN"
            port = SACN_PORT if is_sacn else ARTNET_PORT
            offset = cfg.artnet_offset

            for u, payload in universes.items():
                # QLC+ compatibility: universe numbers below offset would collide
                # on wire-universe 0 — skip and warn once.
                if offset and u < offset:
                    logger.warning(
                        f"Universe {u} skipped: below artnet_offset={offset}. "
                        f"Re-patch fixture to U{offset}+ or set artnet_offset=0."
                    )
                    continue

                wire_u = u - offset
                dest = _dest_ip(wire_u, cfg.net_mode, cfg.protocol, cfg.target_ip)

                if is_sacn:
                    seq = self._sacn_seq.get(u, 0)
                    self._sacn_seq[u] = (seq + 1) % 256
                    packet = _build_sacn_packet(
                        wire_u, payload, seq,
                        cfg.sacn_priority, cfg.sacn_source_name, cfg.sacn_preview,
                    )
                else:
                    packet = _build_artnet_packet(
                        wire_u, payload, cfg.art_net, cfg.art_sub,
                    )

                try:
                    self._sock.sendto(packet, (dest, port))
                    self.packets_sent += 1
                    self.last_error = None
                except Exception as e:
                    self.last_error = str(e)
                    logger.warning(f"DMX send error U{u} → {dest}:{port}: {e}")

    def close(self):
        self._running = False
        self._sock.close()
