"""Complete school directory: atomic PostgreSQL snapshots and a durable refresh request."""
import json
import logging
import os
import re
import threading
import time

from bs4 import BeautifulSoup

from ..db import connect
from . import academic

logger = logging.getLogger(__name__)
LOCK_KEY = 719802602
PINYIN_LOCK_KEY = 719802603
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS academic_directory_students (
        id TEXT PRIMARY KEY,grade TEXT NOT NULL,payload JSONB NOT NULL,search_text TEXT NOT NULL,
        pinyin_text TEXT NOT NULL DEFAULT '')""",
    "ALTER TABLE academic_directory_students ADD COLUMN IF NOT EXISTS pinyin_text TEXT NOT NULL DEFAULT ''",
    "CREATE INDEX IF NOT EXISTS idx_academic_directory_grade ON academic_directory_students(grade)",
    """CREATE TABLE IF NOT EXISTS academic_directory_control (
        id INTEGER PRIMARY KEY CHECK(id=1),state TEXT NOT NULL DEFAULT 'idle',
        grades JSONB NOT NULL DEFAULT '[]',synced_at TIMESTAMPTZ,
        student_count INTEGER NOT NULL DEFAULT 0,classes_done INTEGER NOT NULL DEFAULT 0,
        classes_total INTEGER NOT NULL DEFAULT 0,error TEXT,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    "INSERT INTO academic_directory_control(id) VALUES(1) ON CONFLICT DO NOTHING",
)
_stop = threading.Event()
_thread = None

_HAN = re.compile(r'[\u4e00-\u9fff]+')


def pinyin_keys(text) -> tuple[str, str]:
    """取汉字部分的 (全拼, 首字母缩写)；无汉字或 pypinyin 缺失时返回空串（模糊检索自动停用）。"""
    han = ''.join(_HAN.findall(str(text or '')))
    if not han:
        return '', ''
    try:
        from pypinyin import lazy_pinyin
    except ImportError:
        return '', ''
    syllables = lazy_pinyin(han)
    return ''.join(syllables), ''.join(part[:1] for part in syllables if part)


def pinyin_column(name) -> str:
    full, initials = pinyin_keys(name)
    return ' '.join(filter(None, (full, initials)))


def backfill_pinyin():
    """为存量名录行补拼音（幂等；advisory lock 防止并发重复计算）。"""
    with connect() as db:
        if not db.execute('SELECT pg_try_advisory_lock(%s) AS acquired', (PINYIN_LOCK_KEY,)).fetchone()['acquired']:
            return
        try:
            rows = db.execute("SELECT id,payload->>'name' AS name FROM academic_directory_students "
                              "WHERE pinyin_text=''").fetchall()
            updates = [(pinyin_column(row['name']), row['id']) for row in rows]
            if updates:
                with db.cursor() as cursor:
                    cursor.executemany(
                        "UPDATE academic_directory_students SET pinyin_text=%s WHERE id=%s AND pinyin_text=''",
                        updates)
                logger.info('School directory pinyin backfilled: %d rows', len(updates))
        finally:
            db.execute('SELECT pg_advisory_unlock(%s)', (PINYIN_LOCK_KEY,))


def init_schema():
    with connect() as db:
        for sql in SCHEMA:
            db.execute(sql)


def status():
    with connect() as db:
        return db.execute("SELECT * FROM academic_directory_control WHERE id=1").fetchone()


def enqueue():
    with connect() as db:
        # Locking the row makes simultaneous refresh clicks idempotent.
        row = db.execute("SELECT * FROM academic_directory_control WHERE id=1 FOR UPDATE").fetchone()
        if row['state'] not in ('queued', 'running'):
            row = db.execute("""UPDATE academic_directory_control SET state='queued',error=NULL,
                classes_done=0,classes_total=0,updated_at=CURRENT_TIMESTAMP WHERE id=1 RETURNING *""").fetchone()
    return row


def ensure_initial_refresh():
    """Warm an empty directory once a school connection is available."""
    academic.connection_headers()
    current = status()
    if current and not current['synced_at'] and current['state'] in ('idle', 'failed'):
        return enqueue()
    return current


def _search_tokens(query):
    text = str(query or '').strip()
    composite = re.fullmatch(r'(.+?班)([\u4e00-\u9fff]{2,4})', text) or re.fullmatch(
        r'(.+?\d)([\u4e00-\u9fff]{2,4})', text)
    return list(composite.groups()) if composite else text.split()


def search(*, query='', grade=None, name='', class_name='', major_name=''):
    with connect() as db:
        # Metadata and students must refer to the same complete snapshot.
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        metadata = db.execute("SELECT synced_at FROM academic_directory_control WHERE id=1").fetchone()
        if not metadata or not metadata['synced_at']:
            return None
        clauses, params = [], []
        for field, value in (('grade', grade), ("payload->>'name'", name),
                             ("payload->>'class_name'", class_name), ("payload->>'major_name'", major_name),
                             ):
            if value:
                # strpos treats %, _ and backslash as literal user input.
                clauses.append(f"{field}=%s" if field == 'grade' else f"strpos({field},%s)>0")
                params.append(value)
        # Include payload fields so existing snapshots support student-number
        # searches immediately, without waiting for the next directory rebuild.
        tokens = _search_tokens(query)
        for token in tokens:
            clauses.append("strpos(concat_ws(' ', search_text, payload->>'student_number_display', id),%s)>0")
            params.append(token)
        where = ' AND '.join(clauses) or 'TRUE'
        # 重名候选精确名优先：搜索是子串匹配（“李欣”也命中李欣莹），名单里把与关键词完全同名的排最前。
        exact_names = list(dict.fromkeys(tokens + ([name] if name else [])))
        rows = db.execute(
            f"SELECT payload FROM academic_directory_students WHERE {where} "
            "ORDER BY (payload->>'name' = ANY(%s)) DESC,grade DESC,payload->>'class_name',payload->>'name',id "
            "LIMIT 101", params + [exact_names]).fetchall()
        if not rows and tokens:
            # 子串完全零命中才按读音兜底（同音字/纯拼音查询），结果由上层标注 fuzzy。
            fuzzy_rows = _pinyin_search(db, tokens, grade)
            result_extra = {'fuzzy': True} if fuzzy_rows else {}
            rows = fuzzy_rows or []
        else:
            result_extra = {}
    payload = {'students': [r['payload'] for r in rows[:100]], 'truncated': len(rows) > 100,
               'classes': [], 'fetched_at': metadata['synced_at'].isoformat(), 'stale': False, 'source': 'directory'}
    payload.update(result_extra)
    return payload


def _pinyin_search(db, tokens, grade):
    """按读音兜底匹配（同音字/纯拼音查询）。命中返回行列表，无可行条件（无汉字）返回 None。"""
    text = ''.join(tokens).strip().lower()
    full, initials = pinyin_keys(text)
    if not full and re.fullmatch(r'[a-z]{2,30}', text):
        # 纯拼音输入（全拼或首字母缩写）本身就是匹配词
        full = initials = text
    if not full:
        return None
    clauses, params = [], []
    if grade:
        clauses.append('grade=%s')
        params.append(grade)
    match = 'strpos(pinyin_text,%s)>0'
    match_params = [full]
    if len(initials) >= 2:
        # pinyin_text 形如“liqin lq”：结尾等值即首字母缩写命中
        match += f' OR right(pinyin_text,{len(initials)})=%s'
        match_params.append(initials)
    clauses.append(f'({match})')
    params += match_params
    return db.execute(f"SELECT payload FROM academic_directory_students WHERE {' AND '.join(clauses)} "
                      "ORDER BY grade DESC,payload->>'class_name',payload->>'name',id LIMIT 101", params).fetchall()


def grades():
    with connect() as db:
        row = db.execute('SELECT grades,synced_at FROM academic_directory_control WHERE id=1').fetchone()
    return {'grades': row['grades'], 'stale': False, 'source': 'directory'} if row and row['synced_at'] else None


def student(sid):
    with connect() as db:
        row = db.execute("SELECT payload FROM academic_directory_students WHERE id=%s", (sid,)).fetchone()
    return row['payload'] if row else None


def by_number_pattern(number):
    """按完整学号在脱敏名录内定位：仅存“前4+****+后4”，故按长度+前缀+后缀匹配，唯一命中才返回。"""
    number = re.sub(r'\D', '', str(number or ''))
    if len(number) < 6:
        return None
    with connect() as db:
        rows = db.execute("""SELECT payload FROM academic_directory_students
            WHERE char_length(payload->>'student_number_display') = %s
              AND left(payload->>'student_number_display', 4) = left(%s, 4)
              AND right(payload->>'student_number_display', 4) = right(%s, 4)
            LIMIT 2""", (len(number), number, number)).fetchall()
    return rows[0]['payload'] if len(rows) == 1 else None


def class_students(client, grade, dept, major, cls):
    client.deadline = time.monotonic() + 25
    html = client.request('GET', '/admin/jwxtgld/kbcx/xsxxlist', params={
        'sznj': grade, 'yxid': dept['id'], 'zyid': major['id'], 'bjid': cls['id']})
    soup = BeautifulSoup(html, 'html.parser')
    links = soup.select('.xskb-link')
    if not links and not re.search(r'暂无学生|暂无数据|没有学生|无学生', soup.get_text()):
        raise academic.AcademicError('directory_invalid', '学生列表为空且无法确认完整性，保留原目录')
    result = []
    for link in links:
        sid, name, term = (link.get(k, '') for k in ('data-id', 'data-name', 'data-xnxq'))
        if not academic.ID_RE.fullmatch(sid) or not name or not academic.TERM_RE.fullmatch(term):
            raise academic.AcademicError('directory_invalid', '学生目录字段不完整')
        fields = link.select('.text-class')
        result.append({'id': sid, 'name': name, 'default_term': term, 'grade': grade,
            'student_number_display': fields[0].get_text(strip=True) if fields else '',
            'department_name': dept.get('yxmc', ''), 'major_name': major.get('zymc', ''),
            'class_name': cls.get('bjmc', ''), 'class_id': cls['id']})
    return result


def collect(progress):
    students, classes = {}, []
    with academic.CcsutClient() as client:
        grades = client.grades()
        for grade in grades:
            if _stop.is_set():
                raise academic.AcademicError('directory_stopped', '目录同步已中止，可重新刷新', 503)
            client.deadline = time.monotonic() + 25
            tree = client.json('POST', '/admin/jwxtgld/xscx/getXssjYxxx', data={'sznj': grade, 'xm': ''})
            if not isinstance(tree, list) or not tree:
                raise academic.AcademicError('directory_invalid', '年级目录为空或格式异常，保留原目录')
            grade_classes = []
            for dept in tree:
                for major in dept['zyxxList']:
                    # The school omits bjxxList for majors with no classes.
                    class_list = major.get('bjxxList', [])
                    if not isinstance(class_list, list):
                        raise academic.AcademicError('directory_invalid', 'Invalid class directory')
                    for cls in class_list:
                        if not all(str(item.get('id', '')).strip() for item in (dept, major, cls)):
                            raise academic.AcademicError('directory_invalid', '班级目录缺少标识')
                        grade_classes.append((grade, dept, major, cls))
            if not grade_classes:
                raise academic.AcademicError('directory_invalid', '年级未返回班级，保留原目录')
            classes.extend(grade_classes)
        progress(0, len(classes))
        for index, (grade, dept, major, cls) in enumerate(classes, 1):
            if _stop.is_set():
                raise academic.AcademicError('directory_stopped', '目录同步已中止，可重新刷新', 503)
            for item in class_students(client, grade, dept, major, cls):
                if item['id'] in students and students[item['id']] != item:
                    raise academic.AcademicError('directory_invalid', '目录中学生标识冲突，保留原目录')
                students[item['id']] = item
            progress(index, len(classes))
    if not students:
        raise academic.AcademicError('directory_invalid', '完整目录为空，保留原目录')
    return grades, list(students.values())


def publish(db, grades, students):
    # Deleting old rows and inserting the new snapshot share one transaction.
    db.execute('DELETE FROM academic_directory_students')
    with db.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO academic_directory_students(id,grade,payload,search_text,pinyin_text) VALUES(%s,%s,%s::jsonb,%s,%s)",
            [(s['id'], s['grade'], json.dumps(s, ensure_ascii=False),
              ' '.join(str(s.get(k, '')) for k in ('name','major_name','class_name','grade','department_name','student_number_display','id')),
              pinyin_column(s['name']))
             for s in students])
    db.execute("""UPDATE academic_directory_control SET state='succeeded',grades=%s::jsonb,
        synced_at=CURRENT_TIMESTAMP,student_count=%s,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=1""",
        (json.dumps(grades), len(students)))


def process_one(db):
    if not db.execute('SELECT pg_try_advisory_lock(%s) AS acquired', (LOCK_KEY,)).fetchone()['acquired']:
        db.commit()
        return False
    try:
        row = db.execute('SELECT state FROM academic_directory_control WHERE id=1 FOR UPDATE').fetchone()
        if row['state'] not in ('queued', 'running'):
            db.commit()
            return False
        # A previous running request is restarted after a crashed worker releases its lock.
        db.execute("UPDATE academic_directory_control SET state='running',classes_done=0,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=1")
        db.commit()
        def progress(done, total):
            db.execute("""UPDATE academic_directory_control SET classes_done=%s,classes_total=%s,
                updated_at=CURRENT_TIMESTAMP WHERE id=1""", (done, total))
            db.commit()
        try:
            grades, students = collect(progress)
            publish(db, grades, students)
            db.commit()
        except Exception as error:
            db.rollback()
            logger.exception('School directory refresh failed')
            message = error.message if isinstance(error, academic.AcademicError) else '目录同步失败，保留原名单，请查看服务日志'
            db.execute("UPDATE academic_directory_control SET state='failed',error=%s,updated_at=CURRENT_TIMESTAMP WHERE id=1", (message,))
            db.commit()
        return True
    finally:
        db.execute('SELECT pg_advisory_unlock(%s)', (LOCK_KEY,))
        db.commit()


def run():
    try:
        ensure_initial_refresh()
    except academic.AcademicError:
        # Saving a valid connection later will submit the initial refresh.
        pass
    except Exception:
        logger.exception('School directory initial refresh unavailable')
    try:
        # 存量名录补拼音列（全新安装为空操作；刷新流程此后会自带拼音）
        backfill_pinyin()
    except Exception:
        logger.exception('School directory pinyin backfill unavailable')
    while not _stop.is_set():
        try:
            # Do not hold a pooled connection while idle.
            with connect() as db:
                process_one(db)
        except Exception:
            logger.exception('School directory worker unavailable')
        _stop.wait(2)


def start():
    global _thread
    if os.getenv('ACADEMIC_DIRECTORY_WORKER_ENABLED', 'true').lower() not in ('1', 'true', 'yes'):
        return
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=run, name='school-directory', daemon=True)
    _thread.start()


def stop():
    _stop.set()
    if _thread:
        _thread.join(timeout=30)
