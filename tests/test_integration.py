import copy
from datetime import date
from http.client import HTTPConnection
from io import BytesIO
import json
import threading
import unittest
from unittest.mock import patch

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

from app.calendar_engine import parse_week_spec, ValidationError
from server import Handler, ThreadingHTTPServer, MAX_UPLOAD_BYTES


def fixture_pdf(note=''):
    """Synthetic, anonymous text-layer PDF; exercise the actual PDF reader."""
    out = BytesIO()
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    page = canvas.Canvas(out, pagesize=(900, 600))
    page.setFont('STSong-Light', 10)
    for index, day in enumerate('一二三四五六日'):
        page.drawString(110 + index * 105, 550, '星期' + day)
    for y, text in [(480, '测试课程'), (460, '(1-2节)1-2周'),
                    (440, '/场地:测试教室/教师:测试教师/课堂')]:
        page.setFont('STSong-Light', 4)
        page.drawString(110, y, text)
    if note:
        page.drawString(100, 100, '其他课程:' + note)
    page.save()
    return out.getvalue()


def multipart(data, filename='测试课表.pdf'):
    prefix = '--boundary\r\nContent-Disposition: form-data; name="note"\r\n\r\ntest\r\n--boundary\r\nContent-Disposition: form-data; name="file"; filename="' + filename + '"\r\nContent-Type: application/pdf\r\n\r\n'
    return prefix.encode() + data + b'\r\n--boundary--\r\n'


COURSE = dict(name='测试课程', weekday=0, start_period=1, end_period=2, weeks='1-2周', location='测试教室', teacher='测试教师')


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class QuietHandler(Handler):
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, path, body, content_type='application/json'):
        connection = HTTPConnection(*self.server.server_address, timeout=10)
        try:
            connection.request('POST', path, body, {'Content-Type': content_type})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def generate(self, **changes):
        payload = dict(courses=[copy.deepcopy(COURSE)], reminders=[], week1_start='2026-08-31', timezone='Asia/Shanghai')
        payload.update(changes)
        return self.request('/api/generate', json.dumps(payload).encode())

    def upload(self, data, filename='测试课表.pdf'):
        return self.request('/api/parse', multipart(data, filename), 'multipart/form-data; boundary=boundary')

    def test_pdf_to_ics(self):
        status, result = self.upload(fixture_pdf())
        self.assertEqual(status, 200, result)
        self.assertEqual(result['pages'], 1)
        self.assertFalse(result['used_ocr'])
        self.assertEqual(len(result['courses']), 1)
        for key, expected in COURSE.items():
            self.assertEqual(result['courses'][0][key], expected)
        status, result = self.generate(courses=result['courses'])
        self.assertEqual(status, 200, result)
        self.assertEqual(result['summary']['event_count'], 2)
        self.assertEqual(result['summary']['date_start'], '2026-08-31')
        self.assertEqual(result['summary']['date_end'], '2026-09-07')
        ics = result['ics']
        self.assertEqual(ics.count('BEGIN:VEVENT'), 2)
        for day in ['20260831', '20260907']:
            self.assertIn('DTSTART;TZID=Asia/Shanghai:' + day + 'T080000', ics)
            self.assertIn('DTEND;TZID=Asia/Shanghai:' + day + 'T092500', ics)
        self.assertIn('SUMMARY:测试课程', ics)
        self.assertIn('LOCATION:测试教室', ics)

    def test_other_courses_warning(self):
        cases = [('', 0, False), ('情绪管理测试老师/1-2周', 1, True),
                 ('情绪管理测试老师/1-2周;未知课程测试老师/1-2周', 1, True),
                 ('未知课程测试老师/1-2周', 0, True)]
        for note, count, warned in cases:
            with self.subTest(note=note):
                status, result = self.upload(fixture_pdf(note))
                self.assertEqual(status, 200, result)
                self.assertEqual(len(result['reminders']), count)
                self.assertEqual(bool(result['warnings']), warned)

    def test_invalid_lists_return_400(self):
        for field in ['courses', 'reminders']:
            for value in [None, {}, 'invalid', [None], [42], ['invalid']]:
                with self.subTest(field=field, value=value):
                    status, result = self.generate(**{field: value})
                    self.assertEqual(status, 400, result)
                    self.assertTrue(result['error'])
        self.assertEqual(self.generate()[0], 200)

    def test_invalid_json(self):
        for body in [b'{', b'null', b'[]', b'\xff', b'']:
            with self.subTest(body=body):
                self.assertEqual(self.request('/api/generate', body)[0], 400)

    def test_dates_timezone_and_conflicts(self):
        for changes in [dict(week1_start='2026-09-01'), dict(week1_start='bad'),
                        dict(timezone='unknown'), dict(courses=[COURSE, COURSE])]:
            with self.subTest(changes=changes):
                self.assertEqual(self.generate(**changes)[0], 400)
        self.assertEqual(self.generate(timezone='UTC')[0], 200)

    def test_upload_size_over_http(self):
        pdf = fixture_pdf()
        for size in [MAX_UPLOAD_BYTES-1, MAX_UPLOAD_BYTES, MAX_UPLOAD_BYTES+1]:
            with self.subTest(size=size):
                status, result = self.upload(pdf + b' ' * (size - len(pdf)))
                self.assertEqual(status, 200 if size <= MAX_UPLOAD_BYTES else 400, result)

    def test_invalid_upload_then_recovery(self):
        for data, name in [(b'', 'a.pdf'), (b'not pdf', 'a.pdf'),
                           (b'%PDF broken', 'a.pdf'), (fixture_pdf(), 'a.txt')]:
            with self.subTest(name=name, data=data[:12]):
                self.assertEqual(self.upload(data, name)[0], 400)
        self.assertEqual(self.request('/api/parse', b'bad', 'multipart/form-data')[0], 400)
        self.assertEqual(self.upload(fixture_pdf())[0], 200)

    def test_ics_unicode_folding_and_all_day(self):
        course = dict(COURSE, name='中文课程' * 40 + ',;\\\n结束')
        status, result = self.generate(courses=[course], reminders=[dict(name='整周事项', start_week=1, end_week=1)])
        self.assertEqual(status, 200, result)
        ics = result['ics']
        self.assertEqual(result['summary']['event_count'], 3)
        self.assertIn('DTSTART;VALUE=DATE:20260831', ics)
        self.assertIn('DTEND;VALUE=DATE:20260907', ics)
        self.assertTrue(all(len(line.encode()) <= 75 for line in ics.split('\r\n')))
        self.assertNotIn('\n', ics.replace('\r\n', ''))
        unfolded = ics.replace('\r\n ', '')
        self.assertIn('\\,\\;\\\\\\n', unfolded)


class WeekTests(unittest.TestCase):
    def test_compatible_formats(self):
        for spec in ['1至3周', '1到3周', '1～3周', '1—3周', '1–3周', '1-2周，3周', '1、2、3', '1 - 3 周', '1-3周,2周']:
            with self.subTest(spec=spec):
                self.assertEqual(parse_week_spec(spec), [1, 2, 3])
        self.assertEqual(parse_week_spec('1-6周（偶数周）'), [2, 4, 6])
        self.assertEqual(parse_week_spec('1-6周奇数周'), [1, 3, 5])
        self.assertEqual(parse_week_spec('53周'), [53])

    def test_invalid_and_empty(self):
        for spec in ['', '54周', '0周', '2-1周', '1周乱码', '1-999999999周', '2周单周', '1周双周']:
            with self.subTest(spec=spec), self.assertRaises(ValidationError):
                parse_week_spec(spec)
