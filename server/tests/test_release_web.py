from pathlib import Path

from scripts import release


def test_distribute_apk_creates_identical_aliases(tmp_path, monkeypatch):
    source = tmp_path / "signed.apk"
    source.write_bytes(b"signed-apk-fixture")
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(release, "STATIC_DOWNLOAD_DIR", str(downloads))

    targets = release.distribute_apk(str(source), "9.8.7")

    assert [path.name for path in targets] == [
        "序时_v9.8.7.apk",
        "序时.apk",
        "ClassSchedule.apk",
        "时序_v9.8.7.apk",
        "时序.apk",
    ]
    assert {Path(path).read_bytes() for path in targets} == {source.read_bytes()}
    assert len({release.calc_sha256(path) for path in targets}) == 1


def test_distribute_apk_cleans_historical_versions(tmp_path, monkeypatch):
    source = tmp_path / "signed.apk"
    source.write_bytes(b"signed-apk-fixture")
    downloads = tmp_path / "downloads"
    downloads.mkdir(parents=True)
    old_file1 = downloads / "序时_v1.0.0.apk"
    old_file1.write_bytes(b"old-apk")
    old_file2 = downloads / "时序_v1.0.0.apk"
    old_file2.write_bytes(b"old-apk")
    monkeypatch.setattr(release, "STATIC_DOWNLOAD_DIR", str(downloads))

    release.distribute_apk(str(source), "2.0.0")

    assert not old_file1.exists()
    assert not old_file2.exists()
    assert (downloads / "序时_v2.0.0.apk").exists()


def test_generate_release_notes():
    notes = release.generate_release_notes(
        "1.2.3",
        4,
        ["特性 1", "修复 2"],
        {
            "size_mb": 5.2,
            "size_bytes": 5452595,
            "md5": "TESTMD5",
            "sha256": "TESTSHA256",
            "cert_sha256": "TESTCERTSHA256",
        },
    )
    assert "序时 (ClassSchedule) v1.2.3" in notes
    assert "- 特性 1" in notes
    assert "- 修复 2" in notes
    assert "TESTMD5" in notes
    assert "TESTSHA256" in notes
    assert "TESTCERTSHA256" in notes
    assert "序时_v1.2.3.apk" in notes


def test_get_github_repo(monkeypatch):
    monkeypatch.setattr(release, "run_capture", lambda *args, **kwargs: "https://github.com/testowner/testrepo.git")
    assert release.get_github_repo() == ("testowner", "testrepo")

