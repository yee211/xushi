"""PostgreSQL snapshot tests in a disposable schema; school is mocked."""
import os
import uuid
from contextlib import contextmanager

import pytest

from app.db import connect as real_connect
from app.services import academic
from app.services import academic_directory as directory

original_search = directory.search
original_student = directory.student
original_collect = directory.collect
pytestmark = pytest.mark.skipif(os.getenv('TEST_ACADEMIC_DIRECTORY_DB') != '1', reason='Requires PostgreSQL')


def record(sid='student123', name='张同学'):
    return {'id': sid, 'name': name, 'grade': '2024', 'class_name': '计科一班',
            'major_name': '计算机', 'department_name': '学院', 'default_term': '2026-2027-1'}


@pytest.fixture
def database(monkeypatch):
    schema = 'test_directory_' + uuid.uuid4().hex
    with real_connect() as db:
        db.execute('CREATE SCHEMA ' + schema)
    @contextmanager
    def isolated():
        with real_connect() as db:
            db.execute("SELECT set_config('search_path',%s,false)", (schema,))
            db.commit()
            try:
                yield db
                db.commit()
            finally:
                db.rollback()
                db.execute('RESET search_path')
                db.commit()
    monkeypatch.setattr(directory, 'connect', isolated)
    monkeypatch.setattr(directory, 'search', original_search)
    monkeypatch.setattr(directory, 'student', original_student)
    monkeypatch.setattr(directory, 'collect', lambda progress: (['2024'], [record()]))
    try:
        directory.init_schema()
        yield isolated
    finally:
        with real_connect() as db:
            db.execute('DROP SCHEMA ' + schema + ' CASCADE')


def seed(database, rows=None):
    with database() as db:
        directory.publish(db, ['2024'], rows or [record()])


def test_initial_fallback_refresh_and_literal_search(database):
    assert directory.search(query='张') is None
    assert directory.enqueue()['state'] == 'queued'
    assert directory.enqueue()['state'] == 'queued'
    with database() as db:
        assert directory.process_one(db)
    assert directory.status()['student_count'] == 1
    assert directory.search(query='张')['students'][0]['id'] == 'student123'
    assert directory.search(query='不存在')['students'] == []
    seed(database, [record('special123', '同学%_')])
    assert directory.search(query='%_')['students'][0]['id'] == 'special123'
    assert directory.search(grade='2025')['students'] == []


def test_search_truncation_and_grade_prefix(database):
    seed(database, [record(f'student{i:04d}', '同学') for i in range(110)])
    result = directory.search(grade='2024', query='同学')
    assert len(result['students']) == 100 and result['truncated']
    assert academic.search_keyword('24级计算机')['source'] == 'directory'


def test_number_and_composite_search(database):
    student = dict(record(name='张三'), class_name='软件1班', student_number_display='2024012345')
    seed(database, [student])
    for keyword in ('2024012345', '24级软件1班张三', '软件1班 张三'):
        assert academic.search_keyword(keyword)['students'][0]['id'] == student['id']
    # Old published search_text omitted student numbers; payload fallback works.
    with database() as db:
        db.execute("UPDATE academic_directory_students SET search_text='张三 软件1班 2024'")
    assert academic.search_keyword('2024012345')['students'][0]['id'] == student['id']


def test_upstream_failure_preserves_snapshot(database, monkeypatch):
    seed(database)
    def fail(progress):
        raise academic.AcademicError('connection_expired', '学校登录过期', 409)
    monkeypatch.setattr(directory, 'collect', fail)
    directory.enqueue()
    with database() as db:
        assert directory.process_one(db)
    assert directory.status()['state'] == 'failed'
    assert directory.student('student123')['name'] == '张同学'


def test_publish_failure_rolls_back_delete(database, monkeypatch):
    seed(database)
    def fail(db, grades, students):
        db.execute('DELETE FROM academic_directory_students')
        db.execute('INSERT INTO academic_directory_students(id) VALUES(NULL)')
    monkeypatch.setattr(directory, 'publish', fail)
    directory.enqueue()
    with database() as db:
        assert directory.process_one(db)
    assert directory.status()['state'] == 'failed'
    assert directory.student('student123')['name'] == '张同学'


def test_single_worker_and_crash_recovery(database, monkeypatch):
    directory.enqueue()
    calls = []
    monkeypatch.setattr(directory, 'collect', lambda progress: calls.append(1) or (['2024'], [record()]))
    with database() as leader, database() as follower:
        leader.execute('SELECT pg_advisory_lock(%s)', (directory.LOCK_KEY,))
        leader.commit()
        try:
            assert not directory.process_one(follower)
            assert not calls
        finally:
            leader.execute('SELECT pg_advisory_unlock(%s)', (directory.LOCK_KEY,))
            leader.commit()
        follower.execute("UPDATE academic_directory_control SET state='running'")
        follower.commit()
        assert directory.process_one(follower)
    assert calls == [1] and directory.status()['state'] == 'succeeded'


def test_new_snapshot_invisible_until_commit(database):
    seed(database)
    with database() as writer:
        directory.publish(writer, ['2024'], [record('newstudent', '新同学')])
        assert directory.student('student123') is not None
        assert directory.student('newstudent') is None
        writer.commit()
    assert directory.student('student123') is None
    assert directory.student('newstudent')['name'] == '新同学'


def test_exact_name_priority_and_pinyin_fuzzy_fallback(database):
    exact = dict(record('exact1', '李欣'), student_number_display='2026****0105')
    homophone = dict(record('homo1', '李鑫'), student_number_display='2026****0106')
    ying = dict(record('ying1', '李欣莹'), student_number_display='2026****0108')
    pqk = dict(record('pqk1', '潘桥康', ), student_number_display='2024****0706')
    seed(database, [homophone, ying, exact, pqk])
    # 子串命中时精确同名排最前（“李欣”也命中“李欣莹”）
    assert directory.search(query='李欣')['students'][0]['id'] == 'exact1'
    # 子串零命中 → 读音兜底，标注 fuzzy
    fuzzy = directory.search(query='李昕')
    # 全拼前缀也算读音相近（李欣莹 lixinying 含 lixin）；候选需用户确认，宁多勿漏
    assert fuzzy['fuzzy'] is True and {s['id'] for s in fuzzy['students']} == {'exact1', 'homo1', 'ying1'}
    # 纯拼音（全拼/缩写）同样走兜底
    assert {s['id'] for s in directory.search(query='panqiaokang')['students']} == {'pqk1'}
    assert {s['id'] for s in directory.search(query='pqk')['students']} == {'pqk1'}
    # 无匹配时仍是普通空结果（不带 fuzzy 标记）
    empty = directory.search(query='不存在')
    assert empty['students'] == [] and 'fuzzy' not in empty


def test_by_number_pattern_resolves_masked_number(database):
    masked = dict(record('m1', '潘桥康'), student_number_display='2024****0706')
    other = dict(record('m2', '王五'), student_number_display='2024****0707')
    seed(database, [masked, other])
    assert directory.by_number_pattern('202412340706')['id'] == 'm1'
    assert directory.by_number_pattern('2024') is None  # 太短不猜
    twin = dict(record('m3', '赵六'), student_number_display='2024****0706')
    seed(database, [masked, other, twin])
    assert directory.by_number_pattern('202412340706') is None  # 掩码撞车时不选定


def test_ambiguous_empty_class_preserves_old_class_and_refreshes_others(database, monkeypatch):
    seed(database, [dict(record('old-student'), class_id='a')])
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def grades(self): return ['2024']
        def json(self, *args, **kwargs):
            return [{'id': 'dept', 'zyxxList': [{'id': 'major', 'bjxxList': [{'id': 'a'}, {'id': 'b'}]}]}]
        def request(self, *args, **kwargs):
            if kwargs['params']['bjid'] == 'a':
                return '<div>暂无数据</div>'
            return '<a class="xskb-link" data-id="newstudent123" data-name="新同学" data-xnxq="2026-2027-1"></a>'
    monkeypatch.setattr(academic, 'CcsutClient', Client)
    directory._stop.clear()
    grades, students = original_collect(lambda *args: None)
    by_id = {row['id']: row for row in students}
    assert by_id['old-student']['directory_stale']
    assert 'newstudent123' in by_id
    with database() as db:
        directory.publish(db, grades, students)
    assert directory.student('old-student')['directory_stale']
