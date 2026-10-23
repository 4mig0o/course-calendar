import unittest
from unittest.mock import patch
from io import BytesIO
from server import Handler, MAX_UPLOAD_BYTES, RequestError
from app.calendar_engine import parse_week_spec, parse_payload_courses, ValidationError


class RegressionTests(unittest.TestCase):
    def test_upload_limit(self):
        for size in [MAX_UPLOAD_BYTES, MAX_UPLOAD_BYTES + 1]:
            body = b'--test\r\nContent-Disposition: form-data; name="file"; filename="test.pdf"\r\n\r\n' + b'%PDF' + b'x' * (size - 4) + b'\r\n--test--\r\n'
            handler = object.__new__(Handler)
            handler.headers = {'Content-Type': 'multipart/form-data; boundary=test', 'Content-Length': str(len(body))}
            handler.rfile = BytesIO(body)
            if size == MAX_UPLOAD_BYTES:
                self.assertEqual(len(handler._multipart_pdf()[1]), size)
            else:
                with self.assertRaises(RequestError):
                    handler._multipart_pdf()

    def test_chinese_range(self):
        self.assertEqual(parse_week_spec('1至16周'), list(range(1, 17)))

    def test_mixed_parity(self):
        self.assertEqual(parse_week_spec('1-8周(单周),10-16周(双周)'), [1, 3, 5, 7, 10, 12, 14, 16])

    def test_invalid_spec(self):
        for value in ['1周乱码', '0-16周', '1-999999999周', '3-1周']:
            with self.assertRaises(ValidationError):
                parse_week_spec(value)

    def test_invalid_payload(self):
        for value in [None, {}, 'invalid']:
            with self.assertRaises(ValidationError):
                parse_payload_courses([], value)


if __name__ == '__main__':
    unittest.main()
