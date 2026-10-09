"""Retired product workflows must not remain exposed as API routes."""
from app.main import app


def test_retired_routes_are_not_registered():
    registered = {(method.upper(), path) for path, operations in app.openapi()['paths'].items()
                  for method in operations}
    retired = {
        ('POST', '/api/schedules/{schedule_id}/adjusted'),
        ('POST', '/api/schedules/demo'),
        ('POST', '/api/schedules/{schedule_id}/share'),
        ('GET', '/api/schedules/share/{code}'),
        ('POST', '/api/schedules/share/{code}/import'),
        ('GET', '/api/config'),
        ('GET', '/api/academic/grades'),
        ('GET', '/api/academic/students/{student_id}/schedule'),
        ('POST', '/api/academic/binding/sync'),
    }
    assert not registered.intersection(retired)
    assert ('POST', '/api/academic/binding/sync/tasks') in registered
    assert ('POST', '/api/import') in registered
    assert ('PUT', '/api/courses/{course_id}') in registered


def test_retired_get_does_not_fall_through_to_spa():
    from fastapi.testclient import TestClient
    response = TestClient(app).get('/api/academic/grades')
    assert response.status_code == 404
