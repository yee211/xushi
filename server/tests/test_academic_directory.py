"""Directory harvesting and local-search routing, with no real school requests."""
import time

import httpx
import pytest

from app.services import academic, academic_directory as directory


def school_response(count=145, broken=False):
    if broken:
        return '<h1>服务异常</h1>'
    return ''.join(f'<a class="xskb-link" data-id="student{i:04d}" data-name="同学{i}" '
        'data-xnxq="2026-2027-1"><span class="text-class">2024****</span></a>' for i in range(count))


def test_full_class_collection_exceeds_search_limit():
    with academic.CcsutClient({'Cookie': 'test'}, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=school_response()))) as client:
        client.deadline = time.monotonic() - 1
        rows = directory.class_students(client, '2024', {'id': 'dept', 'yxmc': '学院'},
            {'id': 'major', 'zymc': '专业'}, {'id': 'class', 'bjmc': '一班'})
    assert len(rows) == 145
    assert rows[-1]['student_number_display'] == '2024****'
    assert rows[-1]['class_id'] == 'class'


@pytest.mark.parametrize('html', [school_response(broken=True), '<a class="xskb-link" data-id="bad">同学</a>'])
def test_invalid_class_page_never_becomes_empty_directory(html):
    with academic.CcsutClient({'Cookie': 'test'}, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=html))) as client:
        with pytest.raises(academic.AcademicError):
            directory.class_students(client, '2024', {'id': 'd'}, {'id': 'm'}, {'id': 'c'})


def test_local_search_does_not_call_school_even_for_no_matches(monkeypatch):
    monkeypatch.setattr(directory, 'search', lambda **kwargs: {'students': [], 'source': 'directory'})
    monkeypatch.setattr(academic, 'CcsutClient', lambda: pytest.fail('local search must not contact school'))
    assert academic.search_keyword('24级不存在')['students'] == []
    assert academic.search_students('2024', '不存在', '')['students'] == []


def test_keyword_grade_and_search_are_preserved(monkeypatch):
    calls = []
    monkeypatch.setattr(directory, 'search', lambda **kwargs: calls.append(kwargs) or {'students': []})
    academic.search_keyword('24级计科')
    assert calls == [{'query': '计科', 'grade': '2024'}]


def test_directory_student_can_bind_without_process_cache(monkeypatch):
    monkeypatch.setattr(academic, '_students', {})
    monkeypatch.setattr(directory, 'student', lambda sid: {'id': sid, 'name': '同学'})
    assert academic.student_context('student123')['name'] == '同学'


def test_collection_visits_every_grade_and_class(monkeypatch):
    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def grades(self): return ['2024', '2025']
        def json(self, *args, **kwargs):
            return [{'id': 'dept', 'zyxxList': [{'id': 'major', 'bjxxList': [
                {'id': 'a'}, {'id': 'b'}]}]}]
    calls, progress = [], []
    monkeypatch.setattr(academic, 'CcsutClient', Client)
    monkeypatch.setattr(directory, 'class_students', lambda client, grade, dept, major, cls:
        calls.append((grade, cls['id'])) or [{'id': grade + cls['id'], 'grade': grade}])
    directory._stop.clear()
    grades, students = directory.collect(lambda done, total: progress.append((done, total)))
    assert len(students) == 4 and grades == ['2024', '2025']
    assert calls == [('2024', 'a'), ('2024', 'b'), ('2025', 'a'), ('2025', 'b')]
    assert progress[-1] == (4, 4)


def test_fresh_directory_overrides_old_process_context(monkeypatch):
    monkeypatch.setattr(academic, '_students', {'student123': {'id': 'student123', 'name': '旧名字'}})
    monkeypatch.setattr(directory, 'student', lambda sid: {'id': sid, 'name': '新名字'})
    assert academic.student_context('student123')['name'] == '新名字'
