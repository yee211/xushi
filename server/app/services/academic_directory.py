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
SCHEMA = (
    """CREATE TABLE IF NOT EXISTS academic_directory_students (
        id TEXT PRIMARY KEY,grade TEXT NOT NULL,payload JSONB NOT NULL,search_text TEXT NOT NULL)""",
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
                             ('search_text', query)):
            if value:
                # strpos treats %, _ and backslash as literal user input.
                clauses.append(f"{field}=%s" if field == 'grade' else f"strpos({field},%s)>0")
                params.append(value)
        where = ' AND '.join(clauses) or 'TRUE'
        rows = db.execute(f"SELECT payload FROM academic_directory_students WHERE {where} "
                          "ORDER BY grade DESC,payload->>'class_name',payload->>'name',id LIMIT 101", params).fetchall()
    return {'students': [r['payload'] for r in rows[:100]], 'truncated': len(rows) > 100,
            'classes': [], 'fetched_at': metadata['synced_at'].isoformat(), 'stale': False, 'source': 'directory'}


def grades():
    with connect() as db:
        row = db.execute('SELECT grades,synced_at FROM academic_directory_control WHERE id=1').fetchone()
    return {'grades': row['grades'], 'stale': False, 'source': 'directory'} if row and row['synced_at'] else None


def student(sid):
    with connect() as db:
        row = db.execute("SELECT payload FROM academic_directory_students WHERE id=%s", (sid,)).fetchone()
    return row['payload'] if row else None


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
        cursor.executemany("INSERT INTO academic_directory_students(id,grade,payload,search_text) VALUES(%s,%s,%s::jsonb,%s)",
            [(s['id'], s['grade'], json.dumps(s, ensure_ascii=False),
              ' '.join(str(s.get(k, '')) for k in ('name','major_name','class_name','grade','department_name')))
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
