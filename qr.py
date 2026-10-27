import qrcode

# 웹서버와 연동할 URL 또는 데이터
data = "http://127.0.0.1:8000"

# QR 코드 생성
img = qrcode.make(data)
img.save("connection_qr.png")