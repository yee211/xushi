from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_get_app_version():
    response = client.get("/api/app/version")
    assert response.status_code == 200
    data = response.json()
    assert "versionCode" in data
    assert "versionName" in data
    assert "downloadUrl" in data
    assert isinstance(data["versionCode"], int)
    assert isinstance(data["versionName"], str)
    assert isinstance(data["changelog"], list)


def test_downloads_directory_mounted():
    # 验证 /downloads 静态路由是否正常工作（404 表示路由已挂载但文件不存在，非 405/500）
    response = client.get("/downloads/non_existent_file.apk")
    assert response.status_code == 404
