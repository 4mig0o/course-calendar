from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import json
import re
from urllib.parse import unquote

from app.calendar_engine import ValidationError, generate_ics, parse_iso_date, parse_payload_courses
from app.parser import PDFParseError, parse_pdf


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_JSON_BYTES = 3 * 1024 * 1024


class RequestError(ValidationError):
    pass


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        # Avoid logging filenames, student numbers, course names, or request
        # payloads. A minimal path/status log is sufficient for local use.
        print(f"{self.command} {self.path.split('?', 1)[0]} - {fmt % args}")

    def _send(self, status: int, body: bytes, content_type: str = "text/plain; charset=utf-8", *, download: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:")
        if download:
            self.send_header("Content-Disposition", 'attachment; filename="course-calendar.ics"')
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, value: object) -> None:
        self._send(status, _json_bytes(value), "application/json; charset=utf-8")

    def _read_body(self, max_bytes: int) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise RequestError("请求长度无效") from exc
        if length <= 0:
            raise RequestError("请求内容为空")
        if length > max_bytes:
            raise RequestError(f"请求过大，限制为 {max_bytes // (1024 * 1024)} MB")
        return self.rfile.read(length)

    def _multipart_pdf(self) -> tuple[str, bytes]:
        content_type = self.headers.get("Content-Type", "")
        match = re.search(r"boundary=(?:\"([^\"]+)\"|([^;]+))", content_type)
        if not match:
            raise RequestError("请使用 multipart/form-data 上传 PDF")
        boundary = (match.group(1) or match.group(2)).encode("utf-8")
        body = self._read_body(MAX_UPLOAD_BYTES + 64 * 1024)
        marker = b"--" + boundary
        for part in body.split(marker)[1:]:
            if part.startswith(b"--"):
                break
            if part.startswith(b"\r\n"):
                part = part[2:]
            if part.endswith(b"\r\n"):
                part = part[:-2]
            if not part or b"\r\n\r\n" not in part:
                continue
            raw_headers, content = part.split(b"\r\n\r\n", 1)
            headers = raw_headers.decode("utf-8", "replace")
            disposition = re.search(r"name=\"([^\"]+)\"(?:;\s*filename=\"([^\"]*)\")?", headers, re.I)
            if disposition and disposition.group(2) is not None:
                filename = unquote(disposition.group(2)).strip()
                if len(content) > MAX_UPLOAD_BYTES:
                    raise RequestError("PDF 文件超过 10 MB 限制")
                if not filename.lower().endswith(".pdf"):
                    raise RequestError("只支持 .pdf 文件")
                if not content.startswith(b"%PDF"):
                    raise RequestError("上传文件不是有效 PDF")
                return filename, content
        raise RequestError("未找到 PDF 文件字段")

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._serve_static("index.html", "text/html; charset=utf-8")
        elif path == "/static/app.js":
            self._serve_static("app.js", "text/javascript; charset=utf-8")
        elif path == "/static/styles.css":
            self._serve_static("styles.css", "text/css; charset=utf-8")
        elif path == "/static/sw.js":
            self._serve_static("sw.js", "text/javascript; charset=utf-8")
        elif path == "/manifest.webmanifest":
            self._serve_static("manifest.webmanifest", "application/manifest+json; charset=utf-8")
        elif path == "/healthz":
            self._send_json(HTTPStatus.OK, {"ok": True})
        else:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "页面不存在"})

    def _serve_static(self, filename: str, content_type: str) -> None:
        target = (STATIC / filename).resolve()
        if STATIC.resolve() not in target.parents or not target.is_file():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "资源不存在"})
            return
        self._send(HTTPStatus.OK, target.read_bytes(), content_type)

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/parse":
                _, data = self._multipart_pdf()
                result = parse_pdf(data)
                self._send_json(HTTPStatus.OK, result.to_dict())
            elif path == "/api/generate":
                try:
                    payload = json.loads(self._read_body(MAX_JSON_BYTES).decode("utf-8"))
                except UnicodeDecodeError as exc:
                    raise RequestError("请求 JSON 必须使用 UTF-8 编码") from exc
                if not isinstance(payload, dict):
                    raise RequestError("请求 JSON 必须是对象")
                courses, reminders = parse_payload_courses(payload.get("courses"), payload.get("reminders", []))
                week1_start = parse_iso_date(payload.get("week1_start"))
                timezone = str(payload.get("timezone", "Asia/Shanghai"))
                ics, summary = generate_ics(courses, reminders, week1_start, timezone)
                self._send_json(HTTPStatus.OK, {"ics": ics, "summary": summary, "filename": "course-calendar.ics"})
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
        except (ValidationError, PDFParseError, json.JSONDecodeError) as exc:
            errors = getattr(exc, "errors", [str(exc)])
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc), "details": errors})
        except Exception:
            # Never expose parser internals or uploaded content to clients.
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "服务器处理失败，请稍后重试"})


def main() -> None:
    parser = argparse.ArgumentParser(description="大学课表 PDF 转 ICS 本地服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Course Calendar running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
