"""对照 AI 解析与本地确定性解析在同一批 Excel 课表上的差异。

用法：
    python scripts/compare_parse.py            # 扫描 data/uploads
    python scripts/compare_parse.py 某个目录    # 扫描指定目录

只读脚本：不写数据库、不修改任何文件。未配置 AI_API_KEY 时 AI 侧会统一返回
ai-not-configured，此时可用来单独确认本地兜底链路对全部历史样本仍然正常。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# Windows 控制台默认 GBK，中文课表名会乱码，这里强制 UTF-8 输出
sys.stdout.reconfigure(encoding="utf-8")

from app.ai import AI_API_KEY, AI_BASE_URL, AI_MODEL, parse_with_ai  # noqa: E402
from app.parser import parse_xlsx_schedule  # noqa: E402


def describe(parsed):
    """把解析结果压缩成一行可读摘要。"""
    if not parsed:
        return "无结果"
    courses = parsed["courses"]
    empty_weeks = sum(1 for course in courses if not course["weeks"])
    merged = sum(1 for course in courses if course["end_section"] > course["start_section"])
    return (f"{len(courses)} 条，空周次 {empty_weeks}，连堂 {merged}，"
            f"学期「{parsed['term']}」，名称「{parsed['name']}」")


def run(path: Path) -> tuple[str, dict | None, dict | None, str]:
    ai_parsed, engine = parse_with_ai(path)
    try:
        local_parsed = parse_xlsx_schedule(path)
    except Exception as error:
        return engine, ai_parsed, None, f"{type(error).__name__}: {error}"
    return engine, ai_parsed, local_parsed, ""


def main():
    folder = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "data" / "uploads"
    files = sorted([*folder.glob("*.xlsx"), *folder.glob("*.xlsm"), *folder.glob("*.xls")])
    if not files:
        print(f"{folder} 下没有 xlsx / xlsm / xls 样本")
        return


    backend = f"{AI_MODEL} @ {AI_BASE_URL}" if AI_API_KEY else "未配置 AI_API_KEY（AI 侧将全部返回 ai-not-configured）"
    print(f"AI 后端：{backend}")
    print(f"样本目录：{folder}（{len(files)} 个文件）\n")

    matched, drifted, failed = [], [], []
    for index, path in enumerate(files, 1):
        engine, ai_parsed, local_parsed, error = run(path)
        ai_count = len(ai_parsed["courses"]) if ai_parsed else 0
        local_count = len(local_parsed["courses"]) if local_parsed else 0
        print(f"[{index}/{len(files)}] {path.name}")
        print(f"  引擎：{engine}")
        print(f"  AI  ：{describe(ai_parsed)}")
        print(f"  本地：{describe(local_parsed)}")
        if error:
            print(f"  错误：{error}")
        if ai_parsed and local_parsed and ai_count == local_count:
            ai_names = sorted(course["name"] for course in ai_parsed["courses"])
            local_names = sorted(course["name"] for course in local_parsed["courses"])
            if ai_names == local_names:
                print("  差异：无（课程名与条数完全一致）")
                matched.append(path.name)
            else:
                only_ai = sorted(set(ai_names) - set(local_names))
                only_local = sorted(set(local_names) - set(ai_names))
                print(f"  差异：条数相同但课程名不一致；仅 AI 有 {only_ai[:5]}，仅本地有 {only_local[:5]}")
                drifted.append(path.name)
        elif ai_parsed or local_parsed:
            print(f"  差异：条数不一致（AI {ai_count} / 本地 {local_count}）")
            drifted.append(path.name)
        else:
            print("  差异：两条链路都没有解析出课程")
            failed.append(path.name)
        print()

    print("=" * 60)
    print(f"一致 {len(matched)} 个，存在差异 {len(drifted)} 个，双双失败 {len(failed)} 个")
    if drifted:
        print("需人工复核：" + "、".join(drifted))
    if failed:
        print("两条链路均失败：" + "、".join(failed))


if __name__ == "__main__":
    main()
