from __future__ import annotations

import argparse
import asyncio
import base64
import logging
import os
import socket as _socket
import ssl
import struct
import sys
import time
import threading
import json
import random
from typing import Dict, List, Optional, Set, Tuple
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from http.server import HTTPServer, BaseHTTPRequestHandler
import shutil
from datetime import datetime
import eel
import io

if sys.platform == 'win32':
    try:
        if sys.stdout is not None and hasattr(sys.stdout, 'buffer'):
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except (AttributeError, io.UnsupportedOperation, ValueError):
        pass

eel.init('web')

class Colors:
    BLACK = '\033[90m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    RESET = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    BLINK = '\033[5m'
    REVERSE = '\033[7m'
    
    BG_BLACK = '\033[40m'
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'
    BG_MAGENTA = '\033[45m'
    BG_CYAN = '\033[46m'
    BG_WHITE = '\033[47m'
    
    @staticmethod
    def rgb(r, g, b):
        return f'\033[38;2;{r};{g};{b}m'
    
    @staticmethod
    def bg_rgb(r, g, b):
        return f'\033[48;2;{r};{g};{b}m'

class ColoredFormatter(logging.Formatter):
    COLORS = {
        'INFO': Colors.GREEN,
        'WARNING': Colors.YELLOW + Colors.BOLD,
        'ERROR': Colors.RED + Colors.BOLD,
        'DEBUG': Colors.CYAN,
        'CRITICAL': Colors.RED + Colors.BG_WHITE + Colors.BOLD,
    }
    
    def format(self, record):
        levelname = record.levelname
        if levelname in self.COLORS:
            timestamp = self.formatTime(record, '%H:%M:%S')
            colored_timestamp = f"{Colors.MAGENTA}{timestamp}{Colors.RESET}"
            colored_level = f"{self.COLORS[levelname]}{levelname}{Colors.RESET}"
            
            if hasattr(record, 'colored_msg'):
                msg = record.colored_msg
            else:
                msg = record.getMessage()
                
            return f"{colored_timestamp}  {colored_level}  {msg}"
        return super().format(record)

DEFAULT_PORT = 1080

log = logging.getLogger('tg-ws-proxy')
_TG_RANGES = [
    (struct.unpack('!I', _socket.inet_aton('185.76.151.0'))[0],
     struct.unpack('!I', _socket.inet_aton('185.76.151.255'))[0]),
    (struct.unpack('!I', _socket.inet_aton('149.154.160.0'))[0],
     struct.unpack('!I', _socket.inet_aton('149.154.175.255'))[0]),
    (struct.unpack('!I', _socket.inet_aton('91.105.192.0'))[0],
     struct.unpack('!I', _socket.inet_aton('91.105.193.255'))[0]),
    (struct.unpack('!I', _socket.inet_aton('91.108.0.0'))[0],
     struct.unpack('!I', _socket.inet_aton('91.108.255.255'))[0]),
]

_IP_TO_DC: Dict[str, int] = {
    '149.154.175.50': 1, '149.154.175.51': 1, '149.154.175.54': 1,
    '149.154.167.41': 2,
    '149.154.167.50': 2, '149.154.167.51': 2, '149.154.167.220': 2,
    '149.154.175.100': 3, '149.154.175.101': 3,
    '149.154.167.91': 4, '149.154.167.92': 4,
    '91.108.56.100': 5, 
    '91.108.56.126': 5, '91.108.56.101': 5, '91.108.56.116': 5, 
    '91.105.192.100': 203,
    '149.154.167.151': 2, '149.154.167.223': 2, 
    '149.154.166.120': 4, '149.154.166.121': 4,
}

_dc_opt: Dict[int, Optional[str]] = {}
_ws_blacklist: Set[Tuple[int, bool]] = set()
_dc_fail_until: Dict[Tuple[int, bool], float] = {}
_DC_FAIL_COOLDOWN = 60.0
start_time = time.time()

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

def gradient_text(text, colors=None):
    if not colors:
        colors = [Colors.CYAN, Colors.BLUE, Colors.MAGENTA, Colors.GREEN]
    result = ""
    for i, char in enumerate(text):
        color = colors[i % len(colors)]
        result += f"{color}{char}{Colors.RESET}"
    return result

def rainbow_text(text):
    colors = [Colors.RED, Colors.YELLOW, Colors.GREEN, Colors.CYAN, Colors.BLUE, Colors.MAGENTA]
    return gradient_text(text, colors)

def generate_art():
    arts = [
        f"""
{Colors.CYAN}    ╔══════════════════════════════════════════════════════════╗
    ║{Colors.YELLOW}                      🚀 TG PROXY NEO 🚀                      {Colors.CYAN}║
    ║{Colors.GREEN}              The Most Overkill Telegram Proxy                {Colors.CYAN}║
    ║{Colors.MAGENTA}                    [{datetime.now().strftime('%H:%M:%S')}]                      {Colors.CYAN}║
    ╚══════════════════════════════════════════════════════════╝{Colors.RESET}
""",
        f"""
{Colors.BLUE}    ╭━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╮
    ┃{Colors.CYAN}            ⚡ TELEGRAM WEBSOCKET BRIDGE ⚡            {Colors.BLUE}┃
    ┃{Colors.GREEN}                 Proudly Overengineered                 {Colors.BLUE}┃
    ┃{Colors.YELLOW}                    Version 9000+                      {Colors.BLUE}┃
    ╰━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╯{Colors.RESET}
""",
        f"""
{Colors.MAGENTA}    ┌──────────────────────────────────────────────────┐
    │{Colors.CYAN}    ████████╗ ██████╗     ██████╗  ██████╗     {Colors.MAGENTA}│
    │{Colors.CYAN}    ╚══██╔══╝██╔════╝     ██╔══██╗██╔════╝     {Colors.MAGENTA}│
    │{Colors.CYAN}       ██║   ██║  ███╗    ██████╔╝██║  ███╗    {Colors.MAGENTA}│
    │{Colors.CYAN}       ██║   ██║   ██║    ██╔══██╗██║   ██║    {Colors.MAGENTA}│
    │{Colors.CYAN}       ██║   ╚██████╔╝    ██████╔╝╚██████╔╝    {Colors.MAGENTA}│
    │{Colors.CYAN}       ╚═╝    ╚═════╝     ╚═════╝  ╚═════╝     {Colors.MAGENTA}│
    └──────────────────────────────────────────────────┘{Colors.RESET}
"""
    ]
    return random.choice(arts)

BANNER = generate_art()

class WsHandshakeError(Exception):
    def __init__(self, status_code: int, status_line: str,
                 headers: dict = None, location: str = None):
        self.status_code = status_code
        self.status_line = status_line
        self.headers = headers or {}
        self.location = location
        super().__init__(f"HTTP {status_code}: {status_line}")

    @property
    def is_redirect(self) -> bool:
        return self.status_code in (301, 302, 303, 307, 308)

def _xor_mask(data: bytes, mask: bytes) -> bytes:
    if not data:
        return data
    a = bytearray(data)
    for i in range(len(a)):
        a[i] ^= mask[i & 3]
    return bytes(a)

class RawWebSocket:
    OP_CONTINUATION = 0x0
    OP_TEXT = 0x1
    OP_BINARY = 0x2
    OP_CLOSE = 0x8
    OP_PING = 0x9
    OP_PONG = 0xA

    def __init__(self, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self._closed = False

    @staticmethod
    async def connect(ip: str, domain: str, path: str = '/apiws',
                      timeout: float = 10.0) -> 'RawWebSocket':
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, 443, ssl=_ssl_ctx,
                                    server_hostname=domain),
            timeout=min(timeout, 10))

        ws_key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f'GET {path} HTTP/1.1\r\n'
            f'Host: {domain}\r\n'
            f'Upgrade: websocket\r\n'
            f'Connection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {ws_key}\r\n'
            f'Sec-WebSocket-Version: 13\r\n'
            f'Sec-WebSocket-Protocol: binary\r\n'
            f'Origin: https://web.telegram.org\r\n'
            f'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            f'AppleWebKit/537.36 (KHTML, like Gecko) '
            f'Chrome/131.0.0.0 Safari/537.36\r\n'
            f'\r\n'
        )
        writer.write(req.encode())
        await writer.drain()

        response_lines: list[str] = []
        try:
            while True:
                line = await asyncio.wait_for(reader.readline(),
                                              timeout=timeout)
                if line in (b'\r\n', b'\n', b''):
                    break
                response_lines.append(
                    line.decode('utf-8', errors='replace').strip())
        except asyncio.TimeoutError:
            writer.close()
            raise

        if not response_lines:
            writer.close()
            raise WsHandshakeError(0, 'empty response')

        first_line = response_lines[0]
        parts = first_line.split(' ', 2)
        try:
            status_code = int(parts[1]) if len(parts) >= 2 else 0
        except ValueError:
            status_code = 0

        if status_code == 101:
            return RawWebSocket(reader, writer)

        headers: dict[str, str] = {}
        for hl in response_lines[1:]:
            if ':' in hl:
                k, v = hl.split(':', 1)
                headers[k.strip().lower()] = v.strip()

        writer.close()
        raise WsHandshakeError(status_code, first_line, headers,
                                location=headers.get('location'))

    async def send(self, data: bytes):
        if self._closed:
            raise ConnectionError("WebSocket closed")
        frame = self._build_frame(self.OP_BINARY, data, mask=True)
        self.writer.write(frame)
        await self.writer.drain()

    async def recv(self) -> Optional[bytes]:
        while not self._closed:
            opcode, payload = await self._read_frame()

            if opcode == self.OP_CLOSE:
                self._closed = True
                try:
                    reply = self._build_frame(
                        self.OP_CLOSE,
                        payload[:2] if payload else b'',
                        mask=True)
                    self.writer.write(reply)
                    await self.writer.drain()
                except Exception:
                    pass
                return None

            if opcode == self.OP_PING:
                try:
                    pong = self._build_frame(self.OP_PONG, payload,
                                             mask=True)
                    self.writer.write(pong)
                    await self.writer.drain()
                except Exception:
                    pass
                continue

            if opcode == self.OP_PONG:
                continue

            if opcode in (self.OP_TEXT, self.OP_BINARY):
                return payload

            continue

        return None

    async def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.writer.write(
                self._build_frame(self.OP_CLOSE, b'', mask=True))
            await self.writer.drain()
        except Exception:
            pass
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass

    @staticmethod
    def _build_frame(opcode: int, data: bytes,
                     mask: bool = False) -> bytes:
        header = bytearray()
        header.append(0x80 | opcode)
        length = len(data)
        mask_bit = 0x80 if mask else 0x00

        if length < 126:
            header.append(mask_bit | length)
        elif length < 65536:
            header.append(mask_bit | 126)
            header.extend(struct.pack('>H', length))
        else:
            header.append(mask_bit | 127)
            header.extend(struct.pack('>Q', length))

        if mask:
            mask_key = os.urandom(4)
            header.extend(mask_key)
            return bytes(header) + _xor_mask(data, mask_key)
        return bytes(header) + data

    async def _read_frame(self) -> Tuple[int, bytes]:
        hdr = await self.reader.readexactly(2)
        opcode = hdr[0] & 0x0F
        is_masked = bool(hdr[1] & 0x80)
        length = hdr[1] & 0x7F

        if length == 126:
            length = struct.unpack('>H',
                                   await self.reader.readexactly(2))[0]
        elif length == 127:
            length = struct.unpack('>Q',
                                   await self.reader.readexactly(8))[0]

        if is_masked:
            mask_key = await self.reader.readexactly(4)
            payload = await self.reader.readexactly(length)
            return opcode, _xor_mask(payload, mask_key)

        payload = await self.reader.readexactly(length)
        return opcode, payload

def _human_bytes(n: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if abs(n) < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"

def _is_telegram_ip(ip: str) -> bool:
    try:
        n = struct.unpack('!I', _socket.inet_aton(ip))[0]
        return any(lo <= n <= hi for lo, hi in _TG_RANGES)
    except OSError:
        return False

def _is_http_transport(data: bytes) -> bool:
    return (data[:5] == b'POST ' or data[:4] == b'GET ' or
            data[:5] == b'HEAD ' or data[:8] == b'OPTIONS ')

def _dc_from_init(data: bytes) -> Tuple[Optional[int], bool]:
    try:
        key = bytes(data[8:40])
        iv = bytes(data[40:56])
        cipher = Cipher(algorithms.AES(key), modes.CTR(iv))
        encryptor = cipher.encryptor()
        keystream = encryptor.update(b'\x00' * 64) + encryptor.finalize()
        plain = bytes(a ^ b for a, b in zip(data[56:64], keystream[56:64]))
        proto = struct.unpack('<I', plain[0:4])[0]
        dc_raw = struct.unpack('<h', plain[4:6])[0]
        if proto in (0xEFEFEFEF, 0xEEEEEEEE, 0xDDDDDDDD):
            dc = abs(dc_raw)
            if 1 <= dc <= 1000:
                return dc, (dc_raw < 0)
    except Exception:
        pass
    return None, False

def _ws_domains(dc: int, is_media) -> List[str]:
    base = 'telegram.org' if dc > 5 else 'web.telegram.org'
    if is_media is None:
        return [f'kws{dc}-1.{base}', f'kws{dc}.{base}']
    if is_media:
        return [f'kws{dc}-1.{base}', f'kws{dc}.{base}']
    return [f'kws{dc}.{base}', f'kws{dc}-1.{base}']

class Stats:
    def __init__(self):
        self.connections_total = 0
        self.connections_ws = 0
        self.connections_tcp_fallback = 0
        self.connections_http_rejected = 0
        self.connections_passthrough = 0
        self.ws_errors = 0
        self.bytes_up = 0
        self.bytes_down = 0

    def summary(self) -> str:
        return (f"total={self.connections_total} ws={self.connections_ws} "
                f"tcp_fb={self.connections_tcp_fallback} "
                f"http_skip={self.connections_http_rejected} "
                f"pass={self.connections_passthrough} "
                f"err={self.ws_errors} "
                f"up={_human_bytes(self.bytes_up)} "
                f"down={_human_bytes(self.bytes_down)}")

_stats = Stats()

async def _bridge_ws(reader, writer, ws: RawWebSocket, label,
                     dc=None, dst=None, port=None, is_media=False):
    dc_tag = f"DC{dc}{'m' if is_media else ''}" if dc else "DC?"
    dst_tag = f"{dst}:{port}" if dst else "?"

    up_bytes = 0
    down_bytes = 0
    up_packets = 0
    down_packets = 0
    start_time = asyncio.get_event_loop().time()

    async def tcp_to_ws():
        nonlocal up_bytes, up_packets
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                _stats.bytes_up += len(chunk)
                up_bytes += len(chunk)
                up_packets += 1
                await ws.send(chunk)
        except (asyncio.CancelledError, ConnectionError, OSError):
            return
        except Exception:
            return

    async def ws_to_tcp():
        nonlocal down_bytes, down_packets
        try:
            while True:
                data = await ws.recv()
                if data is None:
                    break
                _stats.bytes_down += len(data)
                down_bytes += len(data)
                down_packets += 1
                writer.write(data)
                await writer.drain()
        except (asyncio.CancelledError, ConnectionError, OSError):
            return
        except Exception:
            return

    tasks = [asyncio.create_task(tcp_to_ws()),
             asyncio.create_task(ws_to_tcp())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except BaseException:
                pass
        elapsed = asyncio.get_event_loop().time() - start_time
        
        color = random.choice([Colors.CYAN, Colors.GREEN, Colors.MAGENTA, Colors.BLUE])
        log.info(f"{color}[{label}]{Colors.RESET} {dc_tag} ({dst_tag}) ⚡ "
                 f"⬆️ {Colors.GREEN}{_human_bytes(up_bytes)}{Colors.RESET} ({up_packets} pkts) "
                 f"⬇️ {Colors.BLUE}{_human_bytes(down_bytes)}{Colors.RESET} ({down_packets} pkts) "
                 f"{Colors.MAGENTA}in {elapsed:.1f}s{Colors.RESET}")
        try:
            await ws.close()
        except BaseException:
            pass
        try:
            writer.close()
            await writer.wait_closed()
        except BaseException:
            pass

async def _bridge_tcp(reader, writer, remote_reader, remote_writer,
                      label, dc=None, dst=None, port=None,
                      is_media=False):
    async def forward(src, dst_w, tag):
        try:
            while True:
                data = await src.read(65536)
                if not data:
                    break
                if 'up' in tag:
                    _stats.bytes_up += len(data)
                else:
                    _stats.bytes_down += len(data)
                dst_w.write(data)
                await dst_w.drain()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    tasks = [
        asyncio.create_task(forward(reader, remote_writer, 'up')),
        asyncio.create_task(forward(remote_reader, writer, 'down')),
    ]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except BaseException:
                pass
        for w in (writer, remote_writer):
            try:
                w.close()
                await w.wait_closed()
            except BaseException:
                pass

async def _pipe(r, w):
    try:
        while True:
            data = await r.read(65536)
            if not data:
                break
            w.write(data)
            await w.drain()
    except asyncio.CancelledError:
        return
    except Exception:
        return
    finally:
        try:
            w.close()
            await w.wait_closed()
        except Exception:
            pass

def _socks5_reply(status):
    return bytes([0x05, status, 0x00, 0x01]) + b'\x00' * 6

async def _tcp_fallback(reader, writer, dst, port, init, label,
                        dc=None, is_media=False):
    try:
        rr, rw = await asyncio.wait_for(
            asyncio.open_connection(dst, port), timeout=10)
    except Exception as exc:
        log.warning(f"{Colors.YELLOW}[{label}]{Colors.RESET} 🐢 TCP fallback connect to {dst}:{port} failed: {exc}")
        return False

    _stats.connections_tcp_fallback += 1
    rw.write(init)
    await rw.drain()
    await _bridge_tcp(reader, writer, rr, rw, label,
                      dc=dc, dst=dst, port=port, is_media=is_media)
    return True

async def _handle_client(reader, writer):
    _stats.connections_total += 1
    peer = writer.get_extra_info('peername')
    label = f"{peer[0]}:{peer[1]}" if peer else "?"
    
    client_color = random.choice([Colors.CYAN, Colors.GREEN, Colors.MAGENTA, Colors.BLUE, Colors.YELLOW])

    try:
        hdr = await asyncio.wait_for(reader.readexactly(2), timeout=10)
        if hdr[0] != 5:
            log.debug(f"{client_color}[{label}]{Colors.RESET} not SOCKS5")
            writer.close()
            return
        nmethods = hdr[1]
        await reader.readexactly(nmethods)
        writer.write(b'\x05\x00')
        await writer.drain()

        req = await asyncio.wait_for(reader.readexactly(4), timeout=10)
        _ver, cmd, _rsv, atyp = req
        if cmd != 1:
            writer.write(_socks5_reply(0x07))
            await writer.drain()
            writer.close()
            return

        if atyp == 1:
            raw = await reader.readexactly(4)
            dst = _socket.inet_ntoa(raw)
        elif atyp == 3:
            dlen = (await reader.readexactly(1))[0]
            dst = (await reader.readexactly(dlen)).decode()
        elif atyp == 4:
            raw = await reader.readexactly(16)
            dst = _socket.inet_ntop(_socket.AF_INET6, raw)
        else:
            writer.write(_socks5_reply(0x08))
            await writer.drain()
            writer.close()
            return

        port = struct.unpack('!H', await reader.readexactly(2))[0]

        if not _is_telegram_ip(dst):
            _stats.connections_passthrough += 1
            log.debug(f"{client_color}[{label}]{Colors.RESET} ⚡ passthrough -> {dst}:{port}")
            try:
                rr, rw = await asyncio.wait_for(
                    asyncio.open_connection(dst, port), timeout=10)
            except Exception as exc:
                log.warning(f"{client_color}[{label}]{Colors.RESET} passthrough failed to {dst}: {exc}")
                writer.write(_socks5_reply(0x05))
                await writer.drain()
                writer.close()
                return

            writer.write(_socks5_reply(0x00))
            await writer.drain()

            tasks = [asyncio.create_task(_pipe(reader, rw)),
                     asyncio.create_task(_pipe(rr, writer))]
            await asyncio.wait(tasks,
                               return_when=asyncio.FIRST_COMPLETED)
            for t in tasks:
                t.cancel()
            for t in tasks:
                try:
                    await t
                except BaseException:
                    pass
            return

        writer.write(_socks5_reply(0x00))
        await writer.drain()

        try:
            init = await asyncio.wait_for(
                reader.readexactly(64), timeout=15)
        except asyncio.IncompleteReadError:
            log.debug(f"{client_color}[{label}]{Colors.RESET} client disconnected")
            return

        if _is_http_transport(init):
            _stats.connections_http_rejected += 1
            log.debug(f"{client_color}[{label}]{Colors.RESET} HTTP transport rejected")
            writer.close()
            return

        dc, is_media = _dc_from_init(init)
        if dc is None and dst in _IP_TO_DC:
            dc = _IP_TO_DC.get(dst)

        if dc is None or dc not in _dc_opt:
            log.warning(f"{client_color}[{label}]{Colors.RESET} unknown DC{dc} for {dst}:{port} -> TCP passthrough")
            await _tcp_fallback(reader, writer, dst, port, init, label)
            return

        dc_key = (dc, is_media if is_media is not None else True)
        now = time.monotonic()
        media_tag = " media" if is_media else (" media?" if is_media is None else "")

        if dc_key in _ws_blacklist:
            log.debug(f"{client_color}[{label}]{Colors.RESET} DC{dc}{media_tag} WS blacklisted -> TCP")
            ok = await _tcp_fallback(reader, writer, dst, port, init,
                                     label, dc=dc, is_media=is_media)
            if ok:
                log.info(f"{client_color}[{label}]{Colors.RESET} DC{dc}{media_tag} TCP fallback closed")
            return

        fail_until = _dc_fail_until.get(dc_key, 0)
        if now < fail_until:
            remaining = fail_until - now
            log.debug(f"{client_color}[{label}]{Colors.RESET} DC{dc}{media_tag} WS cooldown ({remaining:.0f}s) -> TCP")
            ok = await _tcp_fallback(reader, writer, dst, port, init,
                                     label, dc=dc, is_media=is_media)
            if ok:
                log.info(f"{client_color}[{label}]{Colors.RESET} DC{dc}{media_tag} TCP fallback closed")
            return

        domains = _ws_domains(dc, is_media)
        target = _dc_opt[dc]
        ws = None
        ws_failed_redirect = False
        all_redirects = True

        for domain in domains:
            url = f'wss://{domain}/apiws'
            log.info(f"{client_color}[{label}]{Colors.RESET} 📡 DC{dc}{media_tag} ({dst}:{port}) -> {Colors.CYAN}{url}{Colors.RESET} via {Colors.YELLOW}{target}{Colors.RESET}")
            try:
                ws = await RawWebSocket.connect(target, domain,
                                                timeout=10)
                all_redirects = False
                break
            except WsHandshakeError as exc:
                _stats.ws_errors += 1
                if exc.is_redirect:
                    ws_failed_redirect = True
                    log.warning(f"{client_color}[{label}]{Colors.RESET} DC{dc}{media_tag} got {exc.status_code} from {domain}")
                    continue
                else:
                    all_redirects = False
                    log.warning(f"{client_color}[{label}]{Colors.RESET} DC{dc}{media_tag} WS handshake: {exc.status_line}")
            except Exception as exc:
                _stats.ws_errors += 1
                all_redirects = False
                if ('CERTIFICATE_VERIFY_FAILED' in str(exc) or
                        'Hostname mismatch' in str(exc)):
                    log.warning(f"{client_color}[{label}]{Colors.RESET} DC{dc}{media_tag} SSL error: {exc}")
                else:
                    log.warning(f"{client_color}[{label}]{Colors.RESET} DC{dc}{media_tag} WS connect failed: {exc}")

        if ws is None:
            if ws_failed_redirect and all_redirects:
                _ws_blacklist.add(dc_key)
                log.warning(f"{client_color}[{label}]{Colors.RESET} DC{dc}{media_tag} blacklisted for WS")
            elif ws_failed_redirect:
                _dc_fail_until[dc_key] = now + _DC_FAIL_COOLDOWN
            else:
                _dc_fail_until[dc_key] = now + _DC_FAIL_COOLDOWN
                log.info(f"{client_color}[{label}]{Colors.RESET} DC{dc}{media_tag} WS cooldown for {int(_DC_FAIL_COOLDOWN)}s")

            log.info(f"{client_color}[{label}]{Colors.RESET} 🐢 DC{dc}{media_tag} -> TCP fallback to {dst}:{port}")
            ok = await _tcp_fallback(reader, writer, dst, port, init,
                                     label, dc=dc, is_media=is_media)
            if ok:
                log.info(f"{client_color}[{label}]{Colors.RESET} DC{dc}{media_tag} TCP fallback closed")
            return

        _dc_fail_until.pop(dc_key, None)
        _stats.connections_ws += 1

        await ws.send(init)
        await _bridge_ws(reader, writer, ws, label,
                         dc=dc, dst=dst, port=port, is_media=is_media)

    except asyncio.TimeoutError:
        log.warning(f"{client_color}[{label}]{Colors.RESET} timeout during SOCKS5 handshake")
    except asyncio.IncompleteReadError:
        log.debug(f"{client_color}[{label}]{Colors.RESET} client disconnected")
    except asyncio.CancelledError:
        log.debug(f"{client_color}[{label}]{Colors.RESET} cancelled")
    except ConnectionResetError:
        log.debug(f"{client_color}[{label}]{Colors.RESET} connection reset")
    except Exception as exc:
        log.error(f"{client_color}[{label}]{Colors.RESET} unexpected: {exc}")
    finally:
        try:
            writer.close()
        except BaseException:
            pass

_server_instance = None
_server_stop_event = None

async def _run(port: int, dc_opt: Dict[int, Optional[str]],
               stop_event: Optional[asyncio.Event] = None):
    global _dc_opt, _server_instance, _server_stop_event, start_time
    _dc_opt = dc_opt
    _server_stop_event = stop_event
    start_time = time.time()

    try:
        print(BANNER)
        
        print(f"{Colors.CYAN}{'='*60}{Colors.RESET}")
        print(f"{Colors.GREEN}  Telegram WS Bridge Proxy - {Colors.YELLOW}OVERKILL EDITION{Colors.RESET}")
        print(f"{Colors.GREEN}  Listening on   {Colors.CYAN}127.0.0.1:{port}{Colors.RESET}")
        print(f"{Colors.GREEN}  Target DC IPs:{Colors.RESET}")
        for dc in dc_opt.keys():
            ip = dc_opt.get(dc)
            color = random.choice([Colors.MAGENTA, Colors.CYAN, Colors.YELLOW, Colors.GREEN])
            print(f"{color}    DC{dc}: {ip}{Colors.RESET}")
        print(f"{Colors.CYAN}{'='*60}{Colors.RESET}")
        print(f"{Colors.GREEN}  Configure Telegram Desktop:{Colors.RESET}")
        print(f"{Colors.YELLOW}    SOCKS5 proxy -> 127.0.0.1:{port}  (no user/pass){Colors.RESET}")
        print(f"{Colors.CYAN}{'='*60}{Colors.RESET}")
        print(f"{Colors.GREEN}  Web Interface: {Colors.BLUE}http://localhost:8080{Colors.RESET}")
        print(f"{Colors.CYAN}{'='*60}{Colors.RESET}")
    except:
        pass
    
    server = await asyncio.start_server(
        _handle_client, '127.0.0.1', port)
    _server_instance = server

    async def log_stats():
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        i = 0
        while True:
            await asyncio.sleep(2)
            try:
                terminal_width = shutil.get_terminal_size().columns
                uptime = time.time() - start_time
                uptime_str = f"{int(uptime // 3600):02d}:{int((uptime % 3600) // 60):02d}:{int(uptime % 60):02d}"
                
                status = (f"{frames[i % len(frames)]} "
                         f"⬆️ {Colors.GREEN}{_human_bytes(_stats.bytes_up)}{Colors.RESET} "
                         f"⬇️ {Colors.BLUE}{_human_bytes(_stats.bytes_down)}{Colors.RESET} "
                         f"| 🔌 {Colors.CYAN}{_stats.connections_ws}{Colors.RESET} "
                         f"| 🐢 {Colors.YELLOW}{_stats.connections_tcp_fallback}{Colors.RESET} "
                         f"| ❌ {Colors.RED}{_stats.ws_errors}{Colors.RESET} "
                         f"| ⏱️ {Colors.MAGENTA}{uptime_str}{Colors.RESET}")
                
                padding = terminal_width - len(status) + 20
                print(f"\r{status}{' ' * padding}", end='', flush=True)
            except:
                pass
            i += 1

    asyncio.create_task(log_stats())

    if stop_event:
        async def wait_stop():
            await stop_event.wait()
            server.close()
            me = asyncio.current_task()
            for task in list(asyncio.all_tasks()):
                if task is not me:
                    task.cancel()
            try:
                await server.wait_closed()
            except asyncio.CancelledError:
                pass
        asyncio.create_task(wait_stop())

    async with server:
        try:
            await server.serve_forever()
        except asyncio.CancelledError:
            pass
    _server_instance = None

def parse_dc_ip_list(dc_ip_list: List[str]) -> Dict[int, str]:
    dc_opt: Dict[int, str] = {}
    for entry in dc_ip_list:
        if ':' not in entry:
            raise ValueError(f"Invalid --dc-ip format {entry!r}, expected DC:IP")
        dc_s, ip_s = entry.split(':', 1)
        try:
            dc_n = int(dc_s)
            _socket.inet_aton(ip_s)
        except (ValueError, OSError):
            raise ValueError(f"Invalid --dc-ip {entry!r}")
        dc_opt[dc_n] = ip_s
    return dc_opt

def run_proxy(port: int, dc_opt: Dict[int, str],
              stop_event: Optional[asyncio.Event] = None):
    asyncio.run(_run(port, dc_opt, stop_event))

def run_proxy_thread():
    dc_opt = parse_dc_ip_list(['2:149.154.167.220', '4:149.154.167.220'])
    asyncio.run(_run(DEFAULT_PORT, dc_opt))

@eel.expose
def get_stats_py():
    return {
        'bytes_up': _stats.bytes_up,
        'bytes_down': _stats.bytes_down,
        'connections_ws': _stats.connections_ws,
        'connections_tcp': _stats.connections_tcp_fallback,
        'errors': _stats.ws_errors,
        'total': _stats.connections_total,
        'uptime': time.time() - start_time,
        'dcs': list(_dc_opt.keys())
    }

def start_gui():
    try:
        handler = logging.StreamHandler()
        handler.setFormatter(ColoredFormatter(
            '%(asctime)s  %(levelname)-5s  %(message)s',
            datefmt='%H:%M:%S'
        ))
        logging.basicConfig(
            level=logging.INFO,
            handlers=[handler]
        )
    except:
        logging.basicConfig(level=logging.INFO)
    
    proxy_thread = threading.Thread(target=run_proxy_thread, daemon=True)
    proxy_thread.start()
    
    time.sleep(1)
    
    eel.start('index.html', 
              size=(1200, 800),
              position=(300, 150),
              mode='chrome',
              port=0)

if __name__ == '__main__':
    start_gui()
