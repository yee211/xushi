"""
序时 (ClassSchedule) 自动化版本发布与打包脚本
运行方式:
    python scripts/release.py <版本号, 如 2.1.3> <版本代码, 如 5> "更新说明1" "更新说明2" ...
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

# Ensure utf-8 stdout on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# 脚本位于 server/scripts/，仓库根为上两级：frontend/、static/、data/ 均在仓库根
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT_DIR, ".env.release"), override=False)
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
ANDROID_DIR = os.path.join(FRONTEND_DIR, "android")
STATIC_DOWNLOAD_DIR = os.path.join(ROOT_DIR, "static", "downloads")
BUILT_APK = os.path.join(ANDROID_DIR, "app", "build", "outputs", "apk", "release", "app-release.apk")
FRONTEND_DIST = os.path.join(FRONTEND_DIR, "dist")
ANDROID_WEB_ASSETS = os.path.join(ANDROID_DIR, "app", "src", "main", "assets", "public")
APPLICATION_ID = "io.github.yee211.classschedule"
VERSION_FILES = [
    os.path.join(FRONTEND_DIR, "src", "utils", "version.js"),
    os.path.join(ANDROID_DIR, "app", "build.gradle"),
    os.path.join(FRONTEND_DIR, "package.json"),
    os.path.join(FRONTEND_DIR, "package-lock.json"),
    os.path.join(ROOT_DIR, "data", "app_version.json"),
    os.path.join(ROOT_DIR, "README.md"),
]

def calc_md5(filepath):
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest().upper()


def calc_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest().upper()

def update_version_files(version_name: str, version_code: int, changelog: list):
    print(f"[*] 1. 更新各处版本配置文件为 v{version_name} (code: {version_code})...")

    # 1.1 frontend/src/utils/version.js
    version_js_path = os.path.join(FRONTEND_DIR, "src", "utils", "version.js")
    with open(version_js_path, encoding="utf-8") as f:
        content = f.read()
    content = re.sub(r"export const CURRENT_VERSION_NAME = '.*?';", f"export const CURRENT_VERSION_NAME = '{version_name}';", content)
    content = re.sub(r"export const CURRENT_VERSION_CODE = \d+;", f"export const CURRENT_VERSION_CODE = {version_code};", content)
    with open(version_js_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("  -> 已更新 frontend/src/utils/version.js")

    # 1.2 frontend/android/app/build.gradle
    build_gradle_path = os.path.join(ANDROID_DIR, "app", "build.gradle")
    with open(build_gradle_path, encoding="utf-8") as f:
        content = f.read()
    content = re.sub(r"versionCode \d+", f"versionCode {version_code}", content)
    content = re.sub(r'versionName ".*?"', f'versionName "{version_name}"', content)
    with open(build_gradle_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("  -> 已更新 frontend/android/app/build.gradle")

    # 1.3 frontend/package.json
    pkg_json_path = os.path.join(FRONTEND_DIR, "package.json")
    with open(pkg_json_path, encoding="utf-8") as f:
        pkg = json.load(f)
    pkg["version"] = version_name
    with open(pkg_json_path, "w", encoding="utf-8") as f:
        json.dump(pkg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("  -> 已更新 frontend/package.json")

    # package-lock.json 的根版本必须与 package.json 保持一致，确保 npm ci 可复现。
    lock_path = os.path.join(FRONTEND_DIR, "package-lock.json")
    with open(lock_path, encoding="utf-8") as f:
        lock = json.load(f)
    lock["version"] = version_name
    if "" in lock.get("packages", {}):
        lock["packages"][""]["version"] = version_name
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("  -> 已更新 frontend/package-lock.json")

    # 1.4 data/app_version.json
    app_version_path = os.path.join(ROOT_DIR, "data", "app_version.json")
    with open(app_version_path, encoding="utf-8") as f:
        ver_info = json.load(f)
    ver_info["versionCode"] = version_code
    ver_info["versionName"] = version_name
    ver_info["title"] = f"发现新版本 v{version_name}"

    # 支持带版本号的中文命名（序时）及标准 URL 编码
    apk_filename = f"序时_v{version_name}.apk"
    quoted_apk = urllib.parse.quote(apk_filename)
    ver_info["downloadUrl"] = f"https://gh-proxy.com/https://raw.githubusercontent.com/yee211/ClassSchedule/main/static/downloads/{quoted_apk}"
    ver_info["backupDownloadUrl"] = f"https://api.tanzeng.xyz/downloads/{quoted_apk}"

    if changelog:
        ver_info["changelog"] = changelog
    with open(app_version_path, "w", encoding="utf-8") as f:
        json.dump(ver_info, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("  -> 已更新 data/app_version.json")

    # 1.5 README.md
    readme_path = os.path.join(ROOT_DIR, "README.md")
    if os.path.exists(readme_path):
        with open(readme_path, encoding="utf-8") as f:
            readme = f.read()
        readme = re.sub(r"Release-v\d+\.\d+\.\d+", f"Release-v{version_name}", readme)
        readme = re.sub(r"Android 客户端 \(v\d+\.\d+\.\d+\)", f"Android 客户端 (v{version_name})", readme)
        quoted_apk = urllib.parse.quote(f"序时_v{version_name}.apk")
        readme = re.sub(r"%E5%BA%8F%E6%97%B6_v\d+\.\d+\.\d+\.apk", quoted_apk, readme)
        readme = re.sub(r"序时_v\d+\.\d+\.\d+\.apk", f"序时_v{version_name}.apk", readme)
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(readme)
        print("  -> 已更新 README.md")

def run_cmd(cmd: list[str], cwd: str):
    print(f"[*] 执行命令: {' '.join(cmd)} (目录: {cwd})")
    subprocess.run(cmd, check=True, cwd=cwd)


def run_capture(cmd: list[str], cwd: str) -> str:
    result = subprocess.run(cmd, check=True, cwd=cwd, text=True, capture_output=True, encoding="utf-8", errors="replace")
    return result.stdout.strip()


def android_sdk_dir() -> Path:
    configured = os.getenv("ANDROID_HOME") or os.getenv("ANDROID_SDK_ROOT")
    if configured:
        candidate = Path(configured)
        if candidate.is_dir():
            return candidate
    properties = Path(ANDROID_DIR) / "local.properties"
    if properties.is_file():
        for line in properties.read_text(encoding="utf-8").splitlines():
            if line.startswith("sdk.dir="):
                value = line.split("=", 1)[1].replace(r"\:", ":").replace(r"\\", "\\")
                candidate = Path(value)
                if candidate.is_dir():
                    return candidate
    raise FileNotFoundError("未找到 Android SDK，请配置 ANDROID_HOME、ANDROID_SDK_ROOT 或 local.properties")


def find_android_tool(name: str) -> str:
    sdk = android_sdk_dir()
    suffix = ".bat" if os.name == "nt" else ""
    pattern = f"{name}{suffix}"
    roots = [sdk / "build-tools", sdk / "cmdline-tools"]
    matches = [path for root in roots if root.is_dir() for path in root.rglob(pattern)]
    if not matches:
        raise FileNotFoundError(f"Android SDK 中未找到 {pattern}")
    return str(max(matches, key=lambda path: path.stat().st_mtime))


def validate_version_files(version_name: str, version_code: int) -> None:
    version_js = Path(FRONTEND_DIR, "src", "utils", "version.js").read_text(encoding="utf-8")
    gradle = Path(ANDROID_DIR, "app", "build.gradle").read_text(encoding="utf-8")
    package = json.loads(Path(FRONTEND_DIR, "package.json").read_text(encoding="utf-8"))
    lock = json.loads(Path(FRONTEND_DIR, "package-lock.json").read_text(encoding="utf-8"))
    remote = json.loads(Path(ROOT_DIR, "data", "app_version.json").read_text(encoding="utf-8"))
    checks = {
        "version.js versionName": f"CURRENT_VERSION_NAME = '{version_name}'" in version_js,
        "version.js versionCode": f"CURRENT_VERSION_CODE = {version_code}" in version_js,
        "build.gradle versionName": f'versionName "{version_name}"' in gradle,
        "build.gradle versionCode": f"versionCode {version_code}" in gradle,
        "package.json": package.get("version") == version_name,
        "package-lock.json": lock.get("version") == version_name and lock.get("packages", {}).get("", {}).get("version") == version_name,
        "app_version.json": remote.get("versionName") == version_name and remote.get("versionCode") == version_code,
    }
    failed = [label for label, passed in checks.items() if not passed]
    if failed:
        raise RuntimeError("版本文件不一致: " + ", ".join(failed))


def verify_apk(apk_path: str, version_name: str, version_code: int) -> str:
    apksigner = find_android_tool("apksigner")
    signature = run_capture([apksigner, "verify", "--verbose", "--print-certs", apk_path], cwd=ANDROID_DIR)
    if "Verifies" not in signature or "Number of signers:" not in signature:
        raise RuntimeError("APK 签名验证没有返回有效签名者")
    analyzer = find_android_tool("apkanalyzer")
    app_id = run_capture([analyzer, "manifest", "application-id", apk_path], cwd=ANDROID_DIR)
    actual_name = run_capture([analyzer, "manifest", "version-name", apk_path], cwd=ANDROID_DIR)
    actual_code = run_capture([analyzer, "manifest", "version-code", apk_path], cwd=ANDROID_DIR)
    if (app_id, actual_name, actual_code) != (APPLICATION_ID, version_name, str(version_code)):
        raise RuntimeError(
            f"APK 内版本不符: package={app_id}, versionName={actual_name}, versionCode={actual_code}"
        )
    digest_match = re.search(r"certificate SHA-256 digest: ([0-9a-f]+)", signature, re.IGNORECASE)
    return digest_match.group(1).upper() if digest_match else "UNKNOWN"


def distribute_apk(source: str, version_name: str) -> list[Path]:
    download_dir = Path(STATIC_DOWNLOAD_DIR)
    download_dir.mkdir(parents=True, exist_ok=True)
    names = [f"序时_v{version_name}.apk", "序时.apk", "ClassSchedule.apk", f"时序_v{version_name}.apk", "时序.apk"]
    targets = [download_dir / name for name in names]
    with tempfile.TemporaryDirectory(prefix=".release-", dir=download_dir) as temp_name:
        temp_dir = Path(temp_name)
        staged = []
        backups = {}
        for target in targets:
            item = temp_dir / target.name
            shutil.copy2(source, item)
            staged.append(item)
            if target.exists():
                backup = temp_dir / f"{target.name}.previous"
                shutil.copy2(target, backup)
                backups[target] = backup
        hashes = {calc_sha256(item) for item in staged}
        sizes = {item.stat().st_size for item in staged}
        if len(hashes) != 1 or len(sizes) != 1:
            raise RuntimeError("分发 APK 的大小或 SHA-256 不一致")
        replaced = []
        try:
            for item, target in zip(staged, targets):
                os.replace(item, target)
                replaced.append(target)
        except Exception:
            for target in reversed(replaced):
                backup = backups.get(target)
                if backup and backup.exists():
                    os.replace(backup, target)
                else:
                    target.unlink(missing_ok=True)
            raise
    # 清理历史版本带版本号的旧 APK 文件，保持仓库轻量，仅保留当前版本及通用别名
    for old_file in download_dir.glob("*.apk"):
        m = re.match(r"^(序时|时序)_v(.+)\.apk$", old_file.name)
        if m and m.group(2) != version_name:
            old_file.unlink(missing_ok=True)
    return targets


def restore_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    if source.exists():
        shutil.copytree(source, target)


def validate_release(version_name: str, version_code: int) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", version_name):
        raise ValueError("版本号必须是语义化版本，例如 2.1.7")
    if version_code <= 0:
        raise ValueError("versionCode 必须是正整数")
    try:
        published_text = run_capture(
            ["git", "show", "HEAD:frontend/src/utils/version.js"],
            cwd=ROOT_DIR,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        published_text = Path(FRONTEND_DIR, "src", "utils", "version.js").read_text(encoding="utf-8")
    published_match = re.search(r"CURRENT_VERSION_CODE = (\d+)", published_text)
    if published_match and version_code <= int(published_match.group(1)):
        raise ValueError(f"versionCode 必须大于已提交版本 {published_match.group(1)}")
    required_signing = (
        "ANDROID_KEYSTORE_PATH", "ANDROID_KEYSTORE_PASSWORD",
        "ANDROID_KEY_ALIAS", "ANDROID_KEY_PASSWORD",
    )
    missing = [name for name in required_signing if not os.getenv(name)]
    if missing:
        raise ValueError("正式 APK 缺少签名环境变量: " + ", ".join(missing))
    if not Path(os.environ["ANDROID_KEYSTORE_PATH"]).is_file():
        raise ValueError("ANDROID_KEYSTORE_PATH 指向的签名文件不存在")


def get_github_token() -> str | None:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if token and token.strip():
        return token.strip()
    try:
        p = subprocess.Popen(
            ["git", "credential", "fill"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            cwd=ROOT_DIR,
        )
        out, _ = p.communicate("protocol=https\nhost=github.com\n")
        for line in out.splitlines():
            if line.startswith("password="):
                candidate = line.split("=", 1)[1].strip()
                if candidate:
                    return candidate
    except Exception:
        pass
    return None


def get_github_repo() -> tuple[str, str]:
    try:
        url = run_capture(["git", "config", "--get", "remote.origin.url"], cwd=ROOT_DIR)
        match = re.search(r"github\.com[:/]([^/]+)/([^/\.]+)", url)
        if match:
            return match.group(1), match.group(2)
    except Exception:
        pass
    return "yee211", "ClassSchedule"


def sync_git_tag(version_name: str) -> None:
    tag = f"v{version_name}"
    try:
        existing = run_capture(["git", "tag", "-l", tag], cwd=ROOT_DIR)
        if not existing:
            run_cmd(["git", "tag", "-a", tag, "-m", f"release: {tag}"], cwd=ROOT_DIR)
            print(f"  -> 已创建本地 Git Tag: {tag}")
            run_cmd(["git", "push", "origin", tag], cwd=ROOT_DIR)
            print(f"  -> 已推送 Git Tag 至远程: {tag}")
        else:
            print(f"  -> Git Tag {tag} 已存在，跳过创建")
    except Exception as e:
        print(f"  [!] Git Tag 处理提示: {e}")


def generate_release_notes(version_name: str, version_code: int, changelog: list[str], apk_info: dict) -> str:
    quoted_apk = urllib.parse.quote(f"序时_v{version_name}.apk")
    bullets = "\n".join(f"- {item}" for item in changelog) if changelog else "- 常规优化与体验提升"
    size_mb = apk_info.get("size_mb", 0.0)
    size_bytes = apk_info.get("size_bytes", 0)
    md5_val = apk_info.get("md5", "")
    sha256_val = apk_info.get("sha256", "")
    cert_sha256 = apk_info.get("cert_sha256", "")

    return f"""## 📅 序时 (ClassSchedule) v{version_name}

> **「序时如流，亦有星辰守望」**

### 📱 多端访问与下载

| 平台 | 访问 / 下载通道 | 说明 |
| :--- | :--- | :--- |
| 🌐 **Web 网页版** | [https://api.tanzeng.xyz](https://api.tanzeng.xyz) | 浏览器免安装秒开，全端自适应，实时热更 |
| 📱 **Android 客户端 (v{version_name})** | 点击下方 Releases 附件下载 `序时_v{version_name}.apk` | 极速安装，独享开屏与桌面星轨时钟图标 |
| 🚀 **全球 CDN 直链** | [Cloudflare CDN 极速下载](https://gh-proxy.com/https://raw.githubusercontent.com/yee211/ClassSchedule/main/static/downloads/{quoted_apk}) | 国内外极速分发通道 |
| 🔗 **官方服务器直链** | [官方源站直链下载](https://api.tanzeng.xyz/downloads/{quoted_apk}) | 官方源站下载通道 |
| ⚡ **永久最新直链** | [序时.apk 永久最新版](https://api.tanzeng.xyz/downloads/%E5%BA%8F%E6%97%B6.apk) | 始终指向最新稳定构建版 |

---

### ✨ 本次更新内容 (Changelog)
{bullets}

---

### 🛡️ 安装包校验信息
- **应用包名 (Application ID)**：{APPLICATION_ID}
- **版本号 (versionName / versionCode)**：v{version_name} / {version_code}
- **文件体积**：{size_mb:.2f} MB ({size_bytes:,} 字节)
- **MD5 校验码**：{md5_val}
- **SHA-256 校验码**：{sha256_val}
- **签名证书 SHA-256**：{cert_sha256}
"""


def publish_github_release(
    version_name: str,
    version_code: int,
    changelog: list[str],
    apk_info: dict,
    apk_files: list[Path],
    token: str | None = None,
) -> str | None:
    print(f"\n[*] 7. 发布 GitHub Release v{version_name}...")
    token = token or get_github_token()
    if not token:
        print("  [!] 未找到 GitHub 认证 Token (可通过环境变量 GITHUB_TOKEN 或 Git 凭据管理器配置)，跳过 GitHub Release。")
        return None

    owner, repo = get_github_repo()
    tag_name = f"v{version_name}"
    sync_git_tag(version_name)

    notes = generate_release_notes(version_name, version_code, changelog, apk_info)
    title = f"序时 v{version_name} - 「序时如流，亦有星辰守望」"

    headers = {
        "Authorization": f"token {token}",
        "User-Agent": "ClassSchedule-Release-Script",
        "Accept": "application/vnd.github.v3+json",
    }
    tag_url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag_name}"
    existing_release = None
    req = urllib.request.Request(tag_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            existing_release = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  [!] 获取已有 Release 失败: HTTP {e.code}")
            return None

    payload = {
        "tag_name": tag_name,
        "target_commitish": "main",
        "name": title,
        "body": notes,
        "draft": False,
        "prerelease": False,
    }
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    if existing_release:
        release_id = existing_release["id"]
        patch_url = f"https://api.github.com/repos/{owner}/{repo}/releases/{release_id}"
        patch_req = urllib.request.Request(
            patch_url,
            data=payload_bytes,
            headers={**headers, "Content-Type": "application/json; charset=utf-8"},
            method="PATCH",
        )
        with urllib.request.urlopen(patch_req, timeout=30) as resp:
            release_data = json.loads(resp.read().decode("utf-8"))
        print(f"  -> 已更新已有 Release: {release_data.get('html_url')}")
    else:
        post_url = f"https://api.github.com/repos/{owner}/{repo}/releases"
        post_req = urllib.request.Request(
            post_url,
            data=payload_bytes,
            headers={**headers, "Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(post_req, timeout=30) as resp:
            release_data = json.loads(resp.read().decode("utf-8"))
        print(f"  -> 已成功创建 Release: {release_data.get('html_url')}")

    release_id = release_data["id"]
    upload_url_template = release_data.get("upload_url", "")
    base_upload_url = upload_url_template.split("{")[0]

    assets_url = f"https://api.github.com/repos/{owner}/{repo}/releases/{release_id}/assets"
    try:
        with urllib.request.urlopen(urllib.request.Request(assets_url, headers=headers), timeout=30) as resp:
            current_assets = json.loads(resp.read().decode("utf-8"))
    except Exception:
        current_assets = []

    primary_apk = apk_files[0]
    upload_targets = [
        (f"序时_v{version_name}.apk", primary_apk),
        (f"XuShi_v{version_name}.apk", primary_apk),
        ("ClassSchedule.apk", primary_apk),
    ]

    for asset_name, file_path in upload_targets:
        for existing_asset in current_assets:
            if existing_asset.get("name") == asset_name:
                del_url = f"https://api.github.com/repos/{owner}/{repo}/releases/assets/{existing_asset['id']}"
                del_req = urllib.request.Request(del_url, headers=headers, method="DELETE")
                try:
                    with urllib.request.urlopen(del_req, timeout=30):
                        print(f"  -> 已移除旧版附件: {asset_name}")
                except Exception as e:
                    print(f"  [!] 移除旧附件 {asset_name} 警告: {e}")

        quoted_name = urllib.parse.quote(asset_name)
        upload_endpoint = f"{base_upload_url}?name={quoted_name}"
        data = file_path.read_bytes()
        upload_headers = {
            "Authorization": f"token {token}",
            "User-Agent": "ClassSchedule-Release-Script",
            "Content-Type": "application/vnd.android.package-archive",
            "Content-Length": str(len(data)),
        }
        upload_req = urllib.request.Request(upload_endpoint, data=data, headers=upload_headers, method="POST")
        try:
            with urllib.request.urlopen(upload_req, timeout=180) as resp:
                if resp.status in (200, 201):
                    print(f"  -> 附件上传成功: {asset_name} ({len(data) / (1024 * 1024):.2f} MB)")
                else:
                    print(f"  [!] 附件上传异常: {asset_name} (HTTP {resp.status})")
        except Exception as e:
            print(f"  [!] 上传附件 {asset_name} 失败: {e}")

    # 清理 GitHub 历史版本 Release，仅保留当前最新发行版
    try:
        list_url = f"https://api.github.com/repos/{owner}/{repo}/releases"
        list_req = urllib.request.Request(list_url, headers=headers)
        with urllib.request.urlopen(list_req, timeout=30) as resp:
            all_releases = json.loads(resp.read().decode("utf-8"))
        for rel in all_releases:
            if rel.get("id") != release_id:
                del_rel_url = f"https://api.github.com/repos/{owner}/{repo}/releases/{rel['id']}"
                del_rel_req = urllib.request.Request(del_rel_url, headers=headers, method="DELETE")
                try:
                    with urllib.request.urlopen(del_rel_req, timeout=30):
                        print(f"  -> 已清理 GitHub 历史 Release: {rel.get('tag_name')}")
                except Exception as ex:
                    print(f"  [!] 清理历史 Release {rel.get('tag_name')} 警告: {ex}")
    except Exception as ex:
        print(f"  [!] 获取历史 Release 列表以执行清理时警告: {ex}")

    return release_data.get("html_url")


def publish_existing_github_release(version_name: str | None = None) -> None:
    app_version_path = os.path.join(ROOT_DIR, "data", "app_version.json")
    with open(app_version_path, encoding="utf-8") as f:
        ver_info = json.load(f)

    if not version_name:
        version_name = ver_info.get("versionName")
    version_code = ver_info.get("versionCode", 1)
    changelog = ver_info.get("changelog", ["常规优化与体验提升"])

    apk_path = Path(STATIC_DOWNLOAD_DIR) / f"序时_v{version_name}.apk"
    if not apk_path.is_file():
        apk_path = Path(BUILT_APK)
    if not apk_path.is_file():
        raise FileNotFoundError(f"未找到对应版本的 Release APK: {apk_path}")

    print(f"[*] 准备为已构建版本 v{version_name} (code: {version_code}) 发布 GitHub Release...")
    cert_sha256 = verify_apk(str(apk_path), version_name, version_code)
    size_bytes = apk_path.stat().st_size
    apk_info = {
        "size_bytes": size_bytes,
        "size_mb": size_bytes / (1024 * 1024),
        "md5": calc_md5(apk_path),
        "sha256": calc_sha256(apk_path),
        "cert_sha256": cert_sha256,
    }
    url = publish_github_release(
        version_name,
        version_code,
        changelog,
        apk_info,
        [apk_path],
    )
    if url:
        print(f"\n[+] GitHub Release 发布完成: {url}")


def main():
    if len(sys.argv) >= 2 and sys.argv[1] in ("--publish-github", "-p"):
        version_name = sys.argv[2] if len(sys.argv) > 2 else None
        publish_existing_github_release(version_name)
        return

    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    flags = [arg for arg in sys.argv[1:] if arg.startswith("--")]

    if len(args) < 2:
        print("用法: python scripts/release.py <version_name> <version_code> [changelog1] [changelog2] ... [--no-github]")
        print("示例: python scripts/release.py 2.1.3 5 \"修复已知问题\" \"优化界面交互\"")
        print("仅发布已有版本至 GitHub: python scripts/release.py --publish-github [version_name]")
        sys.exit(1)

    version_name = args[0]
    version_code = int(args[1])
    changelog = args[2:] if len(args) > 2 else ["常规优化与体验提升"]
    skip_github = "--no-github" in flags

    validate_release(version_name, version_code)
    snapshots = {path: Path(path).read_bytes() for path in VERSION_FILES if os.path.exists(path)}

    print("==================================================")
    print(f" 开始发布 序时 App v{version_name} (versionCode: {version_code})")
    print("==================================================")

    with tempfile.TemporaryDirectory(prefix="xushi-release-rollback-") as rollback_name:
        rollback_dir = Path(rollback_name)
        tree_snapshots = []
        for index, directory in enumerate((Path(FRONTEND_DIST), Path(ANDROID_WEB_ASSETS))):
            backup = rollback_dir / str(index)
            if directory.exists():
                shutil.copytree(directory, backup)
            tree_snapshots.append((backup, directory))
        try:
            # 版本同步后严格执行 Vite -> Capacitor -> Gradle -> 校验 -> 原子分发。
            update_version_files(version_name, version_code, changelog)
            validate_version_files(version_name, version_code)
            print("\n[*] 2. 编译前端 Vue 项目 (vite build)...")
            run_cmd(["npm.cmd" if os.name == "nt" else "npm", "run", "build"], cwd=FRONTEND_DIR)
            print("\n[*] 3. 同步前端资源到 Capacitor Android 原生目录...")
            run_cmd(["npx.cmd" if os.name == "nt" else "npx", "cap", "sync", "android"], cwd=FRONTEND_DIR)
            print("\n[*] 4. 编译并签名 Android Release APK...")
            gradle = os.path.join(ANDROID_DIR, "gradlew.bat" if os.name == "nt" else "gradlew")
            run_cmd([gradle, "assembleRelease"], cwd=ANDROID_DIR)
            if not os.path.exists(BUILT_APK):
                raise FileNotFoundError(f"未找到生成的 Release APK: {BUILT_APK}")
            print("\n[*] 5. 验证 APK 签名与内部版本...")
            certificate_sha256 = verify_apk(BUILT_APK, version_name, version_code)
            distributed = distribute_apk(BUILT_APK, version_name)
        except Exception:
            for path, content in snapshots.items():
                Path(path).write_bytes(content)
            for backup, directory in tree_snapshots:
                restore_tree(backup, directory)
            print("[!] 构建失败，已恢复版本元数据、前端构建产物和 Android Web 资源。")
            raise

    apk_versioned = distributed[0]
    size_mb = apk_versioned.stat().st_size / (1024 * 1024)
    md5_val = calc_md5(apk_versioned)
    sha256_val = calc_sha256(apk_versioned)

    print("\n[*] 6. 本地安装包构建与校验成功！")
    for item in distributed:
        print(f"  -> {item.name}: {item}")
    print(f"  -> 文件大小: {size_mb:.2f} MB")
    print(f"  -> MD5 校验: {md5_val}")
    print(f"  -> SHA-256 校验: {sha256_val}")
    print(f"  -> 签名证书 SHA-256: {certificate_sha256}")

    apk_info = {
        "size_bytes": apk_versioned.stat().st_size,
        "size_mb": size_mb,
        "md5": md5_val,
        "sha256": sha256_val,
        "cert_sha256": certificate_sha256,
    }

    if not skip_github:
        try:
            gh_url = publish_github_release(
                version_name,
                version_code,
                changelog,
                apk_info,
                distributed,
            )
            if gh_url:
                print(f"  -> GitHub Release: {gh_url}")
        except Exception as e:
            print(f"  [!] GitHub Release 发布异常 (可后续通过 --publish-github 重试): {e}")

    print("\n==================================================")
    print(" 本地构建完成；完成服务器同步与线上复核后才算发布完成。")
    print(" 1. 仅暂存本次版本文件与已验证的 APK 产物")
    print(f" 2. git commit -m \"release: v{version_name} (code: {version_code})\"")
    print(" 3. git push")
    print(" 4. 在宝塔终端执行: cd /www/wwwroot/ClassSchedule && git pull origin main")
    print("==================================================")


if __name__ == "__main__":
    main()

