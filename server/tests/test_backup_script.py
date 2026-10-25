"""Exercise success/failure paths using dummy pg tools, never a live database."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "backup.sh"


def shell():
    if os.name == "nt":
        git = shutil.which("git")
        candidate = Path(git).parents[1] / "bin" / "bash.exe" if git else None
        if candidate and candidate.exists():
            return str(candidate)
    value = shutil.which("sh")
    if not value:
        pytest.skip("POSIX shell unavailable")
    return value


def posix_path(path):
    value = path.as_posix()
    if os.name == "nt":
        value = "/" + value[0].lower() + value[2:]
    return value


def run_backup(tmp_path, fail=False, empty=False):
    binary = tmp_path / "bin"
    binary.mkdir()
    destination = tmp_path / "backups"
    data = tmp_path / "data"
    data.mkdir()
    (data / "credential.key").write_text("test-key")
    (data / "connection.enc").write_text("encrypted-test")
    (data / ".env").write_text("do-not-back-up")
    (data / "managed-browser-profile").mkdir()
    (data / "managed-browser-profile" / "volatile").write_text("ignore")
    if empty:
        for item in data.rglob("*"):
            if item.is_file():
                item.unlink()
    dump = "exit 1" if fail else 'for arg; do file="$arg"; done; printf dummy > "$file"'
    for name, content in (("pg_dump", dump), ("pg_restore", "exit 0")):
        path = binary / name
        path.write_text("#!/bin/sh\n" + content + "\n", newline="\n")
        path.chmod(0o755)
    # Replace only the fixed test roots; execute exactly the production shell logic.
    script = tmp_path / "backup.sh"
    text = SCRIPT.read_text().replace("root=/backups", 'root="' + posix_path(destination) + '"')
    text = text.replace("source_data=/source-data", 'source_data="' + posix_path(data) + '"')
    script.write_text(text, newline="\n")
    executable = shell()
    # Git Bash uses POSIX PATH separators, including when launched from Windows.
    env = dict(os.environ, BACKUP_ONCE="1", PATH=posix_path(binary) + ":/usr/bin:/bin")
    result = subprocess.run([executable, str(script)], env=env, capture_output=True, text=True, timeout=15)
    return result, destination


def test_backup_publishes_verified_bundle_and_excludes_private_runtime(tmp_path):
    import tarfile
    result, destination = run_backup(tmp_path)
    assert result.returncode == 0, result.stderr
    bundles = list(destination.glob("xushi_bundle_*Z"))
    assert len(bundles) == 1
    bundle = bundles[0]
    assert (bundle / "database.dump").exists()
    assert (bundle / "SHA256SUMS").exists()
    with tarfile.open(bundle / "data.tar.gz") as archive:
        names = archive.getnames()
    assert "./credential.key" in names
    assert "./connection.enc" in names
    assert not any(".env" in name or "managed-browser-profile" in name for name in names)


def test_failed_dump_never_publishes_success_and_cleans_pending(tmp_path):
    result, destination = run_backup(tmp_path, fail=True)
    assert result.returncode == 1
    assert "backup failed" in result.stderr
    assert not list(destination.iterdir())


def test_empty_source_preserves_database_backup_with_warning(tmp_path):
    result, destination = run_backup(tmp_path, empty=True)
    assert result.returncode == 0, result.stderr
    assert "database backup retained" in result.stderr
    bundle, = destination.glob("xushi_bundle_*Z")
    assert (bundle / "database.dump").exists()
    assert (bundle / "data-unavailable.txt").exists()


@pytest.mark.parametrize("failure", [None, "restore", "tables", "checksum"])
def test_restore_verification_cleans_scratch_on_all_paths(tmp_path, failure):
    import hashlib
    import tarfile

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "database.dump").write_bytes(b"test-dump")
    with tarfile.open(bundle / "data.tar.gz", "w:gz") as archive:
        archive.add(bundle / "database.dump", arcname="credential.key")
    manifest = "".join(hashlib.sha256((bundle / name).read_bytes()).hexdigest() + "  " + name + "\n"
                       for name in ("database.dump", "data.tar.gz"))
    (bundle / "SHA256SUMS").write_text(manifest, newline="\n")
    if failure == "checksum":
        (bundle / "database.dump").write_bytes(b"corrupted")
    binary = tmp_path / "bin"
    binary.mkdir()
    log = tmp_path / "commands"
    tools = {"createdb": "exit 0", "dropdb": "exit 0",
             "pg_restore": "exit 1" if failure == "restore" else "exit 0",
             "psql": "echo 2" if failure == "tables" else "echo 3"}
    for name, command in tools.items():
        path = binary / name
        path.write_text('#!/bin/sh\nprintf "%s\n" "' + name + ' $*" >> "' + posix_path(log) + '"\n' + command + '\n', newline="\n")
        path.chmod(0o755)
    script = tmp_path / "verify.sh"
    script.write_text(SCRIPT.with_name("verify-backup.sh").read_text(), newline="\n")
    env = dict(os.environ, PATH=posix_path(binary) + ":/usr/bin:/bin")
    result = subprocess.run([shell(), str(script), posix_path(bundle)], env=env,
                            capture_output=True, text=True, timeout=15)
    assert (result.returncode == 0) == (failure is None), result.stderr
    if failure == "checksum":
        assert not log.exists()
    else:
        calls = log.read_text()
        assert "createdb" in calls and "dropdb" in calls
        assert " -d xushi_restore_check_" in calls
