from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import re
from typing import Any

from .calendar_engine import Course, Reminder, ValidationError, parse_week_spec


class PDFParseError(ValidationError):
    """An uploaded PDF could not be converted into a reliable course table."""


@dataclass
class _Line:
    page: int
    x0: float
    x1: float
    y0: float
    text: str


@dataclass
class ParseResult:
    courses: list[Course]
    reminders: list[Reminder]
    warnings: list[str]
    pages: int
    used_ocr: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "courses": [course.to_dict() for course in self.courses],
            "reminders": [reminder.to_dict() for reminder in self.reminders],
            "warnings": self.warnings,
            "pages": self.pages,
            "used_ocr": self.used_ocr,
            "course_count": len(self.courses),
            "reminder_count": len(self.reminders),
        }


def _normalise(text: str) -> str:
    return re.sub(r"\s+", "", text.replace("：", ":").replace("，", ",").replace("、", ",").replace("～", "-"))


def _course_type(name: str) -> str:
    if "课程设计" in name or "体质测试" in name:
        return "实践"
    if "实验" in name:
        return "实验"
    return "理论"


def _weekday_from_x(x0: float, x1: float, header_centers: dict[int, float], fallback_centers: list[float]) -> int:
    # Header labels are centred in their columns, while cell text can be
    # long and therefore has a shifted right edge. When no reliable headers
    # exist, compare left edges instead.
    center = (x0 + x1) / 2 if header_centers else x0
    centers = header_centers or {index: value for index, value in enumerate(fallback_centers)}
    return min(centers, key=lambda index: abs(centers[index] - center))


def _complete_header_centers(centers: dict[int, float]) -> dict[int, float]:
    """Fill a missing weekday header (some PDFs merge it with the title)."""
    if len(centers) < 2:
        # One isolated heading is not enough to infer column pitch; use the
        # standard-layout fallback instead of assigning every course to it.
        return {}
    result = dict(centers)
    known = sorted(result)
    # Estimate the horizontal pitch from all known header labels.
    pitches = [(result[right] - result[left]) / (right - left) for left, right in zip(known, known[1:]) if right > left]
    pitch = sorted(pitches)[len(pitches) // 2] if pitches else 104.0
    for index in range(7):
        if index in result:
            continue
        previous = max((item for item in known if item < index), default=None)
        following = min((item for item in known if item > index), default=None)
        if previous is not None and following is not None:
            result[index] = result[previous] + (result[following] - result[previous]) * (index - previous) / (following - previous)
        elif previous is not None:
            result[index] = result[previous] + pitch * (index - previous)
        elif following is not None:
            result[index] = result[following] - pitch * (following - index)
    return result


def _infer_column_positions(lines: list[_Line]) -> list[float]:
    positions = sorted(line.x0 for line in lines if re.search(r"\(\d+\s*-\s*\d+节\)", _normalise(line.text)))
    if not positions:
        return [104 + 104 * index for index in range(7)]
    clusters: list[list[float]] = []
    for position in positions:
        if not clusters or position - clusters[-1][-1] > 8:
            clusters.append([position])
        else:
            clusters[-1].append(position)
    centers = [sum(cluster) / len(cluster) for cluster in clusters]
    if len(centers) >= 7:
        return centers[:7]
    if len(centers) >= 2:
        pitch = sorted([(right - left) / (j - i) for i, left in enumerate(centers) for j, right in enumerate(centers[i + 1:], i + 1) if j > i])[0]
        first = centers[0]
        return [first + pitch * index for index in range(7)]
    return [104 + 104 * index for index in range(7)]


def _parse_block(lines: list[_Line], weekday: int) -> Course | None:
    raw = " ".join(line.text.strip() for line in lines if line.text.strip())
    text = _normalise(raw)
    period_match = re.search(r"\((\d+)\s*-\s*(\d+)节\)", text)
    if not period_match:
        return None
    name = raw[: raw.find("(")].strip(" /:：")
    # Line wrapping inside a table cell can split a Chinese title (e.g.
    # "Java...设计" + "实验"); remove layout whitespace from the title.
    name = re.sub(r"\s+", "", name).strip()
    if not name or name in {"时间段", "节次"}:
        return None
    after = text[period_match.end() :]
    location_marker = re.search(r"/?场地:?", after)
    # A few school templates omit the location label altogether. The week
    # range is still safe to parse up to the teacher field in that case.
    if location_marker:
        week_text = after[: location_marker.start()]
        location_and_rest = after[location_marker.end() :]
    else:
        teacher_before_location = re.search(r"/?教师:?", after)
        week_text = after[: teacher_before_location.start()] if teacher_before_location else after
        location_and_rest = after[teacher_before_location.start() :] if teacher_before_location else ""
    try:
        weeks = parse_week_spec(week_text)
    except ValidationError as exc:
        raise PDFParseError(f"课程“{name}”的周次无法识别", exc.errors) from exc
    teacher_marker = re.search(r"/?教师:?", location_and_rest)
    if teacher_marker:
        location = location_and_rest[: teacher_marker.start()].strip(" /")
        teacher_and_rest = location_and_rest[teacher_marker.end() :]
    else:
        location = location_and_rest.split("/课堂", 1)[0].strip(" /")
        teacher_and_rest = ""
    teacher_end = re.search(r"/?课堂|/?选课人数|/?授课方式", teacher_and_rest)
    teacher = (teacher_and_rest[: teacher_end.start()] if teacher_end else teacher_and_rest).strip(" /")
    return Course(
        name=name,
        weekday=weekday,
        start_period=int(period_match.group(1)),
        end_period=int(period_match.group(2)),
        weeks=weeks,
        location=location,
        teacher=teacher,
        course_type=_course_type(name),
    )


def _group_courses(lines: list[_Line], header_centers: dict[int, float], fallback_centers: list[float], *, ocr: bool = False) -> list[Course]:
    by_column: dict[int, list[_Line]] = {index: [] for index in range(7)}
    for line in lines:
        text = line.text.strip()
        if not text or "打印时间" in text or "其他课程" in text:
            continue
        if re.fullmatch(r"星期[一二三四五六日]", text) or text in {"刘睿轩课表", "时间段", "节次"}:
            continue
        # In the normal PDF, the first ~12% of the page is the time/period
        # column. OCR uses the same relative cut-off.
        if line.x0 < (90 if not ocr else (fallback_centers[0] * 0.55)):
            continue
        weekday = _weekday_from_x(line.x0, line.x1, header_centers, fallback_centers)
        by_column[weekday].append(line)

    blocks: list[Course] = []
    for weekday, column_lines in by_column.items():
        column_lines.sort(key=lambda item: (item.page, -item.y0))
        pending: list[_Line] = []
        current: list[_Line] | None = None
        for line in column_lines:
            if re.search(r"\(\d+\s*-\s*\d+节\)", _normalise(line.text)):
                if current:
                    course = _parse_block(current, weekday)
                    if course:
                        blocks.append(course)
                current = [*pending, line]
                pending = []
            elif current is not None:
                current.append(line)
            elif line.page == 0 and line.y0 < 510:
                # Course title lines precede the line containing the section
                # and week range. Keep them until that marker is encountered.
                pending.append(line)
        if current:
            course = _parse_block(current, weekday)
            if course:
                blocks.append(course)
    return blocks


def _parse_reminders(note_text: str) -> list[Reminder]:
    reminders: list[Reminder] = []
    patterns = [
        ("情绪管理", r"情绪管理\s*([^(/（;；]+).*?/\s*(\d+)\s*-\s*(\d+)\s*周", "超星网络通识选修课"),
        ("管理技能通识训练", r"管理技能通识训练\s*([^(/（;；]+).*?/\s*(\d+)\s*-\s*(\d+)\s*周", ""),
        ("数据库原理与方法B课程设计", r"数据库原理与方法B课程设计\s*([^(/（;；]+).*?/\s*(\d+)\s*-\s*(\d+)\s*周", ""),
        ("Java与面向对象程序设计课程设计", r"Java与面向对象程序设计课程设计\s*([^(/（;；]+).*?/\s*(\d+)\s*-\s*(\d+)\s*周", ""),
    ]
    for name, pattern, default_note in patterns:
        match = re.search(pattern, note_text)
        if not match:
            continue
        teacher = re.sub(r"[（(].*?[）)]", "", match.group(1)).strip(" ：:")
        reminders.append(Reminder(name=name, start_week=int(match.group(2)), end_week=int(match.group(3)), teacher=teacher, note=default_note))
    return reminders


def _pdfminer_lines(data: bytes) -> tuple[list[_Line], dict[int, float], list[str], int]:
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextContainer
    except ImportError as exc:
        raise PDFParseError("缺少 PDF 解析依赖，请安装 requirements.txt", ["缺少 pdfminer.six"])
    try:
        pages = list(extract_pages(BytesIO(data)))
    except Exception as exc:
        raise PDFParseError("PDF 无法读取或已损坏", ["PDF 解析失败，请重新下载后再试"]) from exc
    lines: list[_Line] = []
    header_centers: dict[int, float] = {}
    page_texts: list[str] = []
    weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6}
    for page_number, layout in enumerate(pages):
        text_parts: list[str] = []
        for element in layout:
            if not isinstance(element, LTTextContainer):
                continue
            text = element.get_text().strip()
            if not text:
                continue
            text_parts.append(text)
            one_line = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
            lines.append(_Line(page_number, float(element.x0), float(element.x1), float(element.y0), one_line))
            match = re.fullmatch(r"星期([一二三四五六日])", one_line)
            if match:
                header_centers[weekday_map[match.group(1)]] = (float(element.x0) + float(element.x1)) / 2
        page_texts.append("\n".join(text_parts))
    return lines, _complete_header_centers(header_centers), page_texts, len(pages)


def _ocr_lines(data: bytes) -> tuple[list[_Line], dict[int, float], int]:
    try:
        import pypdfium2
        import pytesseract
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        raise PDFParseError("该 PDF 没有文本层，当前环境未安装 OCR 依赖。", ["扫描型 PDF 需要安装 pytesseract、pypdfium2、Pillow，并安装 Tesseract OCR（含 chi_sim 语言包）。"]) from exc
    try:
        pdf = pypdfium2.PdfDocument(data)
        lines: list[_Line] = []
        header_centers: dict[int, float] = {}
        weekday_map = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6}
        for page_number in range(len(pdf)):
            page = pdf[page_number]
            bitmap = page.render(scale=2.0)
            image = bitmap.to_pil()
            ocr = pytesseract.image_to_data(image, lang="chi_sim+eng", output_type=pytesseract.Output.DICT)
            grouped: dict[tuple[int, int, int], list[tuple[int, int, int, int, str]]] = {}
            for index, value in enumerate(ocr["text"]):
                value = value.strip()
                if not value:
                    continue
                try:
                    confidence = float(ocr["conf"][index])
                except (TypeError, ValueError):
                    confidence = 0
                if confidence < 15:
                    continue
                key = (int(ocr["block_num"][index]), int(ocr["par_num"][index]), int(ocr["line_num"][index]))
                grouped.setdefault(key, []).append((int(ocr["left"][index]), int(ocr["top"][index]), int(ocr["width"][index]), int(ocr["height"][index]), value))
            for words in grouped.values():
                words.sort()
                text = " ".join(word[4] for word in words)
                x0 = min(word[0] for word in words)
                x1 = max(word[0] + word[2] for word in words)
                top = min(word[1] for word in words)
                lines.append(_Line(page_number, x0, x1, -float(top), text))
                match = re.search(r"星期([一二三四五六日])", text)
                if match:
                    header_centers[weekday_map[match.group(1)]] = (x0 + x1) / 2
        return lines, _complete_header_centers(header_centers), len(pdf)
    except Exception as exc:
        raise PDFParseError("OCR 处理失败，请确认 Tesseract 和 chi_sim 语言包已安装。", [str(exc)]) from exc


def parse_pdf(data: bytes) -> ParseResult:
    if not data.startswith(b"%PDF"):
        raise PDFParseError("上传的文件不是有效 PDF", ["请上传 .pdf 文件"])
    lines, headers, page_texts, pages = _pdfminer_lines(data)
    fallback_centers = _infer_column_positions(lines)
    courses = _group_courses(lines, headers, fallback_centers)
    note_text = "\n".join(page_texts)
    # The notes row frequently wraps “课程设计” across a PDF line break.
    reminders = _parse_reminders(re.sub(r"\s+", "", note_text))
    warnings: list[str] = []
    if courses:
        if not reminders and "其他课程" in note_text:
            warnings.append("检测到“其他课程”说明，但未能自动识别其中的全天提醒，请在预览中确认。")
        return ParseResult(courses=courses, reminders=reminders, warnings=warnings, pages=pages)

    # No text-layer timetable was found. Try OCR when available; otherwise the
    # raised error explicitly tells the user what to install or upload.
    ocr_lines, ocr_headers, ocr_pages = _ocr_lines(data)
    ocr_fallback_centers = [0.19 * 1600 + index * (0.81 * 1600 / 7) for index in range(7)]
    courses = _group_courses(ocr_lines, ocr_headers, ocr_fallback_centers, ocr=True)
    if not courses:
        raise PDFParseError("OCR 未能可靠识别课程表", ["请上传带文本层的教务系统 PDF，或手动录入课程；OCR 结果无法安全生成日历。"])
    warnings.append("此文件通过 OCR 解析，课程、星期、周次和时间请逐项人工核对后再导出。")
    return ParseResult(courses=courses, reminders=[], warnings=warnings, pages=ocr_pages, used_ocr=True)
