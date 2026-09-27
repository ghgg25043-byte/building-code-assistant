"""Check local Markdown links and images before publishing the repository."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


class LocalHtmlLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.targets: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"a", "img"}:
            return
        wanted = "href" if tag == "a" else "src"
        self.targets.extend(value for name, value in attrs if name == wanted and value)


def main() -> int:
    broken = []
    checked = 0
    for doc in [*ROOT.rglob("*.md"), *ROOT.joinpath("docs").rglob("*.html")]:
        if any(part in {"private", "exports", "node_modules", ".git", ".venv"} for part in doc.parts):
            continue
        contents = doc.read_text(encoding="utf-8")
        if doc.suffix == ".html":
            parser = LocalHtmlLinks()
            parser.feed(contents)
            targets = parser.targets
        else:
            targets = LINK.findall(contents)
        for target in targets:
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            local = unquote(target.split("#", 1)[0].strip("<>"))
            if not local:
                continue
            checked += 1
            if not (doc.parent / local).exists():
                broken.append(f"{doc.relative_to(ROOT)} -> {target}")
    if broken:
        print("失效的本地文档链接：")
        print("\n".join(broken))
        return 1
    print(f"本地 Markdown / 导览 HTML 链接：{checked} 处路径均存在。外部网页和锚点未检查。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
