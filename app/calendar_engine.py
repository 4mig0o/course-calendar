from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import json
import re
from pathlib import Path
from typing import Any, Iterable
from uuid import NAMESPACE_URL, uuid5


DEFAULT_PERIOD_TIMES: dict[int, tuple[str, str]] = {
    1: ("08:00", "08:40"),
    2: ("08:45", "09:25"),
    3: ("09:55", "10:35"),
    4: ("10:40", "11:20"),
    5: ("11:25", "12:05"),
    6: ("12:40", "13:20"),
    7: ("13:25", "14:05"),
    8: ("14:30", "15:10"),
    9: ("15:15", "15:55"),
    10: ("16:25", "17:05"),
    11: ("17:10", "17:50"),
    12: ("17:55", "18:35"),
    13: ("19:30", "20:10"),
    14: ("20:15", "20:55"),
    15: ("21:00", "21:40"),
}


def _load_period_times() -> dict[int, tuple[str, str]]:
    """Load school-specific period times, falling back to the common table."""
    config_path = Path(__file__).resolve().parent.parent / "period_times.json"
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        parsed = {int(key): (str(value[0]), str(value[1])) for key, value in raw.items()}
        if set(parsed) == set(DEFAULT_PERIOD_TIMES) and all(re.fullmatch(r"\d{2}:\d{2}", value) for pair in parsed.values() for value in pair):
            return parsed
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        pass
    return dict(DEFAULT_PERIOD_TIMES)


PERIOD_TIMES = _load_period_times()

WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
SUPPORTED_TIMEZONES = {
    "Asia/Shanghai": ("+0800", "CST"),
    "UTC": ("+0000", "UTC"),
}


class ValidationError(ValueError):
    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or [message]


@dataclass
class Course:
    name: str
    weekday: int
    start_period: int
    end_period: int
    weeks: list[int]
    location: str = ""
    teacher: str = ""
    course_type: str = "理论"
    source: str = "PDF"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["weeks"] = format_week_spec(self.weeks)
        return value


@dataclass
class Reminder:
    name: str
    start_week: int
    end_week: int
    teacher: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_week_spec(value: str | Iterable[int]) -> list[int]:
    if not isinstance(value, str):
        weeks = sorted({int(item) for item in value})
        if not weeks:
            raise ValidationError("周次不能为空")
        return weeks
    text = value.strip().replace("，", ",").replace("、", ",").replace("～", "-").replace("—", "-")
    text = re.sub(r"\s+", "", text).replace("至", "-").replace("到", "-").replace("–", "-")
    pattern = r"(\d+)(?:-(\d+))?周?(?:[（(]?(单周|双周|奇数周|偶数周)[）)]?)?"
    parts = text.split(",")
    matches = [re.fullmatch(pattern, part) for part in parts]
    if not all(matches):
        raise ValidationError(f"无法识别周次：{value}，请使用 1-16周或1-8周(单周),10-16周(双周)")
    matches = [match.groups() for match in matches]
    if not matches:
        raise ValidationError(f"无法识别周次：{value}")
    result: set[int] = set()
    for first, last, parity in matches:
        start, end = int(first), int(last or first)
        if end < start:
            raise ValidationError(f"周次范围无效：{value}")
        if not 1 <= start <= end <= 53:
            raise ValidationError("周次必须在 1-53 范围内")
        result.update(week for week in range(start, end + 1) if not parity or week % 2 == (1 if parity in ("单周", "奇数周") else 0))
    if not result or min(result) < 1 or max(result) > 53:
        raise ValidationError(f"周次必须在 1-53 范围内：{value}")
    if not result:
        raise ValidationError(f"周次筛选后为空：{value}")
    return sorted(result)


def format_week_spec(weeks: Iterable[int]) -> str:
    values = sorted({int(week) for week in weeks})
    if not values:
        return ""
    ranges: list[str] = []
    start = previous = values[0]
    for current in values[1:]:
        if current == previous + 1:
            previous = current
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = current
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(f"{item}周" for item in ranges)


def course_from_dict(raw: dict[str, Any]) -> Course:
    required = ("name", "weekday", "start_period", "end_period", "weeks")
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValidationError("课程字段不完整", [f"缺少字段：{', '.join(missing)}"])
    try:
        course = Course(
            name=str(raw["name"]).strip(),
            weekday=int(raw["weekday"]),
            start_period=int(raw["start_period"]),
            end_period=int(raw["end_period"]),
            weeks=parse_week_spec(raw["weeks"]),
            location=str(raw.get("location", "") or "").strip(),
            teacher=str(raw.get("teacher", "") or "").strip(),
            course_type=str(raw.get("course_type", raw.get("type", "理论")) or "理论").strip(),
            source=str(raw.get("source", "PDF") or "PDF").strip(),
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError("课程字段格式错误") from exc
    validate_course(course)
    return course


def reminder_from_dict(raw: dict[str, Any]) -> Reminder:
    try:
        reminder = Reminder(
            name=str(raw["name"]).strip(),
            start_week=int(raw["start_week"]),
            end_week=int(raw["end_week"]),
            teacher=str(raw.get("teacher", "") or "").strip(),
            note=str(raw.get("note", "") or "").strip(),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("全天提醒字段格式错误") from exc
    if not reminder.name:
        raise ValidationError("全天提醒名称不能为空")
    if not 1 <= reminder.start_week <= reminder.end_week <= 53:
        raise ValidationError("全天提醒周次范围必须在 1-53 内")
    return reminder


def validate_course(course: Course) -> None:
    errors: list[str] = []
    if not course.name:
        errors.append("课程名称不能为空")
    if course.weekday not in range(7):
        errors.append(f"星期无效：{course.weekday}")
    if course.start_period not in PERIOD_TIMES or course.end_period not in PERIOD_TIMES:
        errors.append("节次必须在 1-15 范围内")
    elif course.end_period < course.start_period:
        errors.append("结束节次不能早于开始节次")
    if not course.weeks or min(course.weeks) < 1 or max(course.weeks) > 53:
        errors.append("周次必须在 1-53 范围内")
    if errors:
        raise ValidationError(f"课程“{course.name or '未命名'}”校验失败", errors)


def _start_end_for(course: Course, day: date) -> tuple[datetime, datetime]:
    start_text = PERIOD_TIMES[course.start_period][0]
    end_text = PERIOD_TIMES[course.end_period][1]
    start = datetime.combine(day, datetime.strptime(start_text, "%H:%M").time())
    end = datetime.combine(day, datetime.strptime(end_text, "%H:%M").time())
    return start, end


def expand_courses(courses: list[Course], week1_start: date) -> list[dict[str, Any]]:
    occurrences: list[dict[str, Any]] = []
    for index, course in enumerate(courses):
        for week in course.weeks:
            day = week1_start + timedelta(weeks=week - 1, days=course.weekday)
            start, end = _start_end_for(course, day)
            occurrences.append({
                "index": index,
                "course": course,
                "week": week,
                "day": day,
                "start": start,
                "end": end,
            })
    return occurrences


def find_conflicts(courses: list[Course], week1_start: date) -> list[dict[str, Any]]:
    by_day: dict[date, list[dict[str, Any]]] = {}
    for occurrence in expand_courses(courses, week1_start):
        by_day.setdefault(occurrence["day"], []).append(occurrence)
    conflicts: list[dict[str, Any]] = []
    for day, items in by_day.items():
        items.sort(key=lambda item: item["start"])
        for previous, current in zip(items, items[1:]):
            if previous["end"] > current["start"]:
                conflicts.append({
                    "date": day.isoformat(),
                    "first": previous["course"].name,
                    "second": current["course"].name,
                    "first_time": f"{previous['start']:%H:%M}-{previous['end']:%H:%M}",
                    "second_time": f"{current['start']:%H:%M}-{current['end']:%H:%M}",
                })
    return conflicts


def validate_timezone(tzid: str) -> None:
    if tzid not in SUPPORTED_TIMEZONES:
        raise ValidationError(f"暂不支持时区“{tzid}”，请选择 Asia/Shanghai 或 UTC")


def ical_escape(value: str) -> str:
    return (str(value).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n"))


def fold_ical_line(line: str) -> list[str]:
    """Fold at 75 UTF-8 octets without splitting UTF-8 characters."""
    result: list[str] = []
    current = ""
    limit = 75
    for char in line:
        candidate = current + char
        if current and len(candidate.encode("utf-8")) > limit:
            result.append(current)
            current = " " + char
            limit = 74
        else:
            current = candidate
    result.append(current)
    return result


def _uid(kind: str, summary: str, day: date, start: str, end: str, index: int) -> str:
    seed = f"{kind}|{summary}|{day.isoformat()}|{start}|{end}|{index}"
    return f"{uuid5(NAMESPACE_URL, seed)}@course-calendar.local"


def _add_vevent(lines: list[str], *, uid: str, summary: str, description: str, location: str = "", start: str, end: str, all_day: bool, tzid: str) -> None:
    lines.extend(("BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}", f"SUMMARY:{ical_escape(summary)}"))
    if all_day:
        lines.extend((f"DTSTART;VALUE=DATE:{start}", f"DTEND;VALUE=DATE:{end}"))
    else:
        lines.extend((f"DTSTART;TZID={tzid}:{start}", f"DTEND;TZID={tzid}:{end}"))
    if location:
        lines.append(f"LOCATION:{ical_escape(location)}")
    lines.extend((f"DESCRIPTION:{ical_escape(description)}", "CATEGORIES:课程", "STATUS:CONFIRMED", "TRANSP:OPAQUE", "SEQUENCE:0", "END:VEVENT"))


def generate_ics(courses: list[Course], reminders: list[Reminder], week1_start: date, tzid: str = "Asia/Shanghai") -> tuple[str, dict[str, Any]]:
    validate_timezone(tzid)
    for course in courses:
        validate_course(course)
    conflicts = find_conflicts(courses, week1_start)
    if conflicts:
        raise ValidationError("发现课程时间冲突，请返回预览表修改后再导出", [f"{item['date']}：{item['first']} 与 {item['second']} 重叠" for item in conflicts])

    offset, tzname = SUPPORTED_TIMEZONES[tzid]
    lines = [
        "BEGIN:VCALENDAR",
        "PRODID:-//Course Calendar//PDF to ICS//CN",
        "VERSION:2.0",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:大学课表日历",
        f"X-WR-TIMEZONE:{tzid}",
        f"X-WR-CALDESC:第1周从{week1_start.isoformat()}（周一）开始；由课表 PDF 生成。",
        "BEGIN:VTIMEZONE",
        f"TZID:{tzid}",
        f"X-LIC-LOCATION:{tzid}",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        f"TZOFFSETFROM:{offset}",
        f"TZOFFSETTO:{offset}",
        f"TZNAME:{tzname}",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]
    event_count = 0
    timed_occurrences = expand_courses(courses, week1_start)
    for occurrence in timed_occurrences:
        course: Course = occurrence["course"]
        day: date = occurrence["day"]
        event_count += 1
        description = f"第{occurrence['week']}周；{course.start_period}-{course.end_period}节；教师：{course.teacher or '未提供'}；课程类型：{course.course_type}；来源：课表 PDF"
        _add_vevent(
            lines,
            uid=_uid("timed", course.name, day, f"{occurrence['start']:%H:%M}", f"{occurrence['end']:%H:%M}", event_count),
            summary=course.name,
            description=description,
            location=course.location,
            start=f"{day:%Y%m%d}T{occurrence['start']:%H%M}00",
            end=f"{day:%Y%m%d}T{occurrence['end']:%H%M}00",
            all_day=False,
            tzid=tzid,
        )

    for reminder_index, reminder in enumerate(reminders):
        for week in range(reminder.start_week, reminder.end_week + 1):
            event_count += 1
            start_day = week1_start + timedelta(weeks=week - 1)
            end_day = start_day + timedelta(days=7)
            note = f"第{week}周；教师：{reminder.teacher or '未提供'}；课表未提供具体星期、时间和地点。"
            if reminder.note:
                note += f" {reminder.note}"
            _add_vevent(
                lines,
                uid=_uid("all-day", reminder.name, start_day, "全天", "全天", reminder_index * 100 + week),
                summary=reminder.name,
                description=note,
                start=f"{start_day:%Y%m%d}",
                end=f"{end_day:%Y%m%d}",
                all_day=True,
                tzid=tzid,
            )
    lines.append("END:VCALENDAR")
    content = "\r\n".join(part for line in lines for part in fold_ical_line(line)) + "\r\n"
    starts = [item["start"].date() for item in timed_occurrences]
    ends = [item["end"].date() for item in timed_occurrences]
    for reminder in reminders:
        starts.append(week1_start + timedelta(weeks=reminder.start_week - 1))
        # DTEND is exclusive for all-day events; report the last visible day.
        ends.append(week1_start + timedelta(weeks=reminder.end_week) - timedelta(days=1))
    summary = {
        "event_count": event_count,
        "timed_event_count": len(timed_occurrences),
        "all_day_event_count": event_count - len(timed_occurrences),
        "date_start": min(starts).isoformat() if starts else week1_start.isoformat(),
        "date_end": max(ends).isoformat() if ends else (week1_start + timedelta(days=6)).isoformat(),
        "timezone": tzid,
        "week1_start": week1_start.isoformat(),
    }
    return content, summary


def parse_iso_date(value: str) -> date:
    try:
        result = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("第 1 周周一日期格式应为 YYYY-MM-DD") from exc
    if result.weekday() != 0:
        raise ValidationError("第 1 周日期必须是星期一")
    return result


def parse_payload_courses(raw_courses: list[dict[str, Any]], raw_reminders: list[dict[str, Any]]) -> tuple[list[Course], list[Reminder]]:
    if not isinstance(raw_reminders, list):
        raise ValidationError("全天事项必须是列表")
    if isinstance(raw_courses, list) and any(not isinstance(item, dict) for item in raw_courses):
        raise ValidationError("每门课程必须是对象")
    if any(not isinstance(item, dict) for item in raw_reminders):
        raise ValidationError("每项全天事项必须是对象")
    if not isinstance(raw_courses, list) or not raw_courses:
        raise ValidationError("至少需要一门课程")
    courses = [course_from_dict(item) for item in raw_courses if isinstance(item, dict)]
    reminders = [reminder_from_dict(item) for item in raw_reminders if isinstance(item, dict)]
    if not courses:
        raise ValidationError("没有可导出的课程")
    return courses, reminders
