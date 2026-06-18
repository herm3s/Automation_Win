"""
socks5_helper.py — Minimal SOCKS5 proxy support using Python standard library only.
No external dependencies required. Works with socks5://host:port proxy URLs.
"""
import os
import ssl
import socket
import struct
from urllib.parse import urlparse


def _parse_proxy(proxy_url: str):
    """Parse proxy URL into (scheme, host, port)."""
    parsed = urlparse(proxy_url)
    scheme = parsed.scheme.lower()
    host = parsed.hostname
    port = parsed.port
    return scheme, host, port


def _socks5_connect(proxy_host: str, proxy_port: int, dest_host: str, dest_port: int, timeout: int = 15):
    """
    Open a raw socket connection through a SOCKS5 proxy.
    Implements RFC 1928 (SOCKS5, no-auth).
    Returns the connected socket.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((proxy_host, proxy_port))

    # --- Step 1: Greeting ---
    # \x05 = SOCKS version 5, \x01 = 1 auth method, \x00 = no auth
    sock.sendall(b'\x05\x01\x00')
    resp = sock.recv(2)
    if len(resp) < 2 or resp[0] != 0x05 or resp[1] != 0x00:
        sock.close()
        raise ConnectionError(f"SOCKS5 auth handshake failed: {resp!r}")

    # --- Step 2: Connect request ---
    host_bytes = dest_host.encode('utf-8')
    req = (
        b'\x05'                     # version 5
        b'\x01'                     # command: CONNECT
        b'\x00'                     # reserved
        b'\x03'                     # addr type: domain name
        + bytes([len(host_bytes)])  # hostname length (1 byte)
        + host_bytes                # hostname
        + struct.pack('>H', dest_port)  # port (2 bytes, big-endian)
    )
    sock.sendall(req)

    # --- Step 3: Read response ---
    resp = sock.recv(4)
    if len(resp) < 4 or resp[0] != 0x05:
        sock.close()
        raise ConnectionError(f"SOCKS5 connect response invalid: {resp!r}")
    if resp[1] != 0x00:
        error_codes = {
            0x01: "general SOCKS failure",
            0x02: "connection not allowed by ruleset",
            0x03: "network unreachable",
            0x04: "host unreachable",
            0x05: "connection refused",
            0x06: "TTL expired",
            0x07: "command not supported",
            0x08: "address type not supported",
        }
        err = error_codes.get(resp[1], f"unknown error code {resp[1]}")
        sock.close()
        raise ConnectionError(f"SOCKS5 connect failed: {err}")

    # Skip the bound address in response (variable length)
    atyp = resp[3]
    if atyp == 0x01:    # IPv4
        sock.recv(4 + 2)
    elif atyp == 0x03:  # domain
        length = sock.recv(1)[0]
        sock.recv(length + 2)
    elif atyp == 0x04:  # IPv6
        sock.recv(16 + 2)

    return sock


def make_https_request(url: str, method: str = "POST", headers: dict = None,
                       body: bytes = None, proxy_url: str = None, timeout: int = 15):
    """
    Make an HTTPS request, optionally through a SOCKS5 or HTTP proxy.
    Returns (status_code: int, body: str).
    Only uses Python standard library.
    """
    parsed = urlparse(url)
    dest_host = parsed.hostname
    dest_port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    path = parsed.path or '/'
    if parsed.query:
        path += '?' + parsed.query

    # --- Create socket (direct or via proxy) ---
    if proxy_url:
        scheme, proxy_host, proxy_port = _parse_proxy(proxy_url)
        if scheme in ('socks5', 'socks5h'):
            raw_sock = _socks5_connect(proxy_host, proxy_port, dest_host, dest_port, timeout)
        elif scheme in ('http', 'https'):
            # HTTP CONNECT tunnel
            raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            raw_sock.settimeout(timeout)
            raw_sock.connect((proxy_host, proxy_port))
            connect_req = (
                f"CONNECT {dest_host}:{dest_port} HTTP/1.1\r\n"
                f"Host: {dest_host}:{dest_port}\r\n\r\n"
            ).encode()
            raw_sock.sendall(connect_req)
            resp_line = raw_sock.recv(512).decode('utf-8', errors='replace')
            if '200' not in resp_line.split('\r\n')[0]:
                raw_sock.close()
                raise ConnectionError(f"HTTP CONNECT failed: {resp_line[:80]}")
        else:
            raise ValueError(f"Unsupported proxy scheme: {scheme}")
    else:
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.settimeout(timeout)
        raw_sock.connect((dest_host, dest_port))

    # --- Wrap with TLS if HTTPS ---
    if parsed.scheme == 'https':
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        sock = ctx.wrap_socket(raw_sock, server_hostname=dest_host)
    else:
        sock = raw_sock

    # --- Build & send HTTP request ---
    if headers is None:
        headers = {}
    headers.setdefault('Host', dest_host)
    headers.setdefault('Connection', 'close')
    if body:
        headers.setdefault('Content-Length', str(len(body)))

    header_str = ''.join(f'{k}: {v}\r\n' for k, v in headers.items())
    request_line = f"{method} {path} HTTP/1.1\r\n{header_str}\r\n"
    sock.sendall(request_line.encode('utf-8'))
    if body:
        sock.sendall(body)

    # --- Read full response ---
    raw_response = b''
    while True:
        try:
            chunk = sock.recv(8192)
            if not chunk:
                break
            raw_response += chunk
        except socket.timeout:
            break
    sock.close()

    # --- Parse HTTP response ---
    sep = raw_response.find(b'\r\n\r\n')
    if sep == -1:
        raise ValueError("Malformed HTTP response (no header/body separator)")

    raw_headers = raw_response[:sep].decode('utf-8', errors='replace')
    response_body = raw_response[sep + 4:]
    status_line = raw_headers.split('\r\n')[0]
    status_code = int(status_line.split(' ')[1])

    # Decode chunked transfer encoding if needed
    if 'transfer-encoding: chunked' in raw_headers.lower():
        decoded = b''
        i = 0
        while i < len(response_body):
            end = response_body.find(b'\r\n', i)
            if end == -1:
                break
            chunk_size = int(response_body[i:end], 16)
            if chunk_size == 0:
                break
            decoded += response_body[end + 2: end + 2 + chunk_size]
            i = end + 2 + chunk_size + 2
        response_body = decoded

    return status_code, response_body.decode('utf-8', errors='replace')
