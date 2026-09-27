"""Create a reviewed preview ZIP from an explicit public-file allowlist."""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    ".gitignore", ".gitattributes", "LICENSE", "README.md", "CHANGELOG.md", "CONTRIBUTING.md",
    "COMPLIANCE_STATUS.md", "SECURITY.md",
    "PILOT_PLAN.md", "start.bat", "app.py", "search_engine.py", "quality.py",
    "evaluate.py", "expert_eval.py", "source_review.py",
}
DATA_FILES = {
    "clauses.json", "demo-source.md", "eval_cases.json", "expert_reviews.csv",
    "field_reviews_blank.csv", "source_review_blank.csv",
}
OTHER_EXTENSIONS = {
    "static": {".html", ".css", ".js"},
    "tests": {".py", ".js"},
    "docs": {".md", ".html", ".css", ".js", ".json"},
    ".github": {".yml", ".yaml", ".md"},
    "scripts": {".py"},
}


def public_file(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    relative = path.relative_to(ROOT)
    if len(relative.parts) == 1:
        return relative.name in ROOT_FILES
    category = relative.parts[0]
    if category == "data":
        return len(relative.parts) == 2 and relative.name in DATA_FILES
    return category in OTHER_EXTENSIONS and path.suffix in OTHER_EXTENSIONS[category]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT.parent / "building-code-assistant-0.2.0-fictional.zip")
    args = parser.parse_args()
    destination = args.out.resolve()
    if destination.exists():
        parser.error(f"输出文件已存在，请换一个 --out 路径：{destination}")
    files = sorted(path for path in ROOT.rglob("*") if public_file(path))
    required = [ROOT / name for name in ROOT_FILES]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.is_file()]
    if missing:
        parser.error("缺少发布必需文件：" + ", ".join(sorted(missing)))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as bundle:
        for path in files:
            bundle.write(path, f"{ROOT.name}/{path.relative_to(ROOT).as_posix()}")
    with ZipFile(destination, "r") as bundle:
        damaged = bundle.testzip()
        if damaged:
            raise RuntimeError(f"ZIP 检查失败：{damaged}")
    print(f"发布包：{destination}\n公开文件：{len(files)} 个\nZIP 完整性：通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
