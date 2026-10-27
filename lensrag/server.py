"""LensRAG 로컬 서버

- PC 화면:   http://localhost:8000          (main.html)
- 휴대폰:    https://<PC의 LAN IP>:8443/camera.html  (QR 코드로 접속)
- WebSocket: /ws  — 휴대폰(camera)이 보낸 프레임/인식 결과를 PC(viewer)로 전달
"""

import asyncio
import datetime
import ipaddress
import json
import logging
import socket
import ssl
from pathlib import Path

import qrcode
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from websockets.asyncio.server import broadcast, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Response

BASE_DIR = Path(__file__).resolve().parent
CERT_DIR = BASE_DIR / "certs"
HTTP_PORT = 8000
HTTPS_PORT = 8443

STATIC_FILES = {
    "/": ("main.html", "text/html; charset=utf-8"),
    "/main.html": ("main.html", "text/html; charset=utf-8"),
    "/camera.html": ("camera.html", "text/html; charset=utf-8"),
    "/connection_qr.png": ("connection_qr.png", "image/png"),
}

VIEWERS = set()
CAMERAS = set()


def get_lan_ip():
    # 실제 패킷은 보내지 않고, 외부로 나갈 때 쓰이는 로컬 IP만 확인
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def ensure_cert(ip):
    """LAN IP용 자체 서명 인증서를 만든다 (IP가 바뀌면 새로 생성)."""
    CERT_DIR.mkdir(exist_ok=True)
    cert_path = CERT_DIR / f"{ip}.crt"
    key_path = CERT_DIR / f"{ip}.key"
    if cert_path.exists() and key_path.exists():
        return cert_path, key_path

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "LensRAG Local")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.ip_address(ip)),
                x509.DNSName("localhost"),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path


def make_qr(ip):
    """휴대폰 카메라 페이지 주소로 connection_qr.png를 만들고 그 주소를 돌려준다."""
    camera_url = f"https://{ip}:{HTTPS_PORT}/camera.html"
    qrcode.make(camera_url).save(BASE_DIR / "connection_qr.png")
    return camera_url


def make_response(status, reason, body, content_type):
    headers = Headers({
        "Content-Type": content_type,
        "Content-Length": str(len(body)),
        "Cache-Control": "no-store",
    })
    return Response(status, reason, headers, body)


def make_process_request(camera_url):
    async def process_request(connection, request):
        path = request.path.split("?", 1)[0]
        if path == "/ws":
            return None  # WebSocket 핸드셰이크 진행
        if path == "/info":
            body = json.dumps({"cameraUrl": camera_url}).encode()
            return make_response(200, "OK", body, "application/json")
        if path in STATIC_FILES:
            filename, content_type = STATIC_FILES[path]
            return make_response(200, "OK", (BASE_DIR / filename).read_bytes(), content_type)
        return make_response(404, "Not Found", b"Not Found", "text/plain")

    return process_request


def camera_status():
    return json.dumps({"type": "status", "camera": bool(CAMERAS)})


async def handler(ws):
    role = None
    try:
        hello = json.loads(await ws.recv())
        role = hello.get("role")
        if role == "viewer":
            VIEWERS.add(ws)
            await ws.send(camera_status())
        elif role == "camera":
            CAMERAS.add(ws)
            broadcast(VIEWERS, camera_status())
        else:
            return

        async for message in ws:
            if role != "camera":
                continue
            if isinstance(message, bytes):
                # JPEG 프레임을 그대로 PC 화면들로 전달
                broadcast(VIEWERS, message)
            else:
                data = json.loads(message)
                if data.get("type") == "ocr":
                    broadcast(VIEWERS, json.dumps({
                        "type": "ocr",
                        "status": str(data.get("status", "")),
                        "text": str(data.get("text", "")),
                    }))
    except (ConnectionClosed, json.JSONDecodeError):
        pass
    finally:
        VIEWERS.discard(ws)
        if ws in CAMERAS:
            CAMERAS.discard(ws)
            broadcast(VIEWERS, camera_status())


async def main():
    logging.basicConfig(level=logging.WARNING)
    ip = get_lan_ip()
    camera_url = make_qr(ip)

    cert_path, key_path = ensure_cert(ip)
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(cert_path, key_path)

    process_request = make_process_request(camera_url)
    async with (
        serve(handler, "127.0.0.1", HTTP_PORT, process_request=process_request, max_size=4 * 2**20),
        serve(handler, "0.0.0.0", HTTPS_PORT, process_request=process_request, ssl=ssl_ctx, max_size=4 * 2**20),
    ):
        print(f"PC 화면:   http://localhost:{HTTP_PORT}")
        print(f"휴대폰:    {camera_url}  (QR 코드 재생성 완료)")
        print("종료: Ctrl+C")
        await asyncio.Future()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
