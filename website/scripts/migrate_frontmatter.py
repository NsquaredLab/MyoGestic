"""Move collection-page H1 headings into Starlight title frontmatter once."""

import json
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[2] / "docs"
SLUGS = {"images/README.md": "images", "reference/otb/README.md": "reference/otb"}


def migrate(path: Path, relative: str) -> bool:
    """Migrate a page without changing its body, existing metadata or code blocks."""
    source = path.read_text()
    frontmatter = ""
    body = source
    if source.startswith("---\n"):
        frontmatter, body = source[4:].split("---\n", 1)
    if re.search(r"^title\s*:", frontmatter, re.M):
        return False
    heading = re.search(r"^# ([^\n]+)\n(?:\n)?", body, re.M)
    if heading is None:
        raise ValueError(f"No title heading found in {path}")
    title = json.dumps(heading[1], ensure_ascii=False)
    metadata = f"title: {title}\n" + frontmatter
    if relative in SLUGS:
        metadata += f"slug: {SLUGS[relative]}\n"
    path.write_text(f"---\n{metadata}---\n" + body[: heading.start()] + body[heading.end() :])
    return True


def main() -> None:
    """Apply the same inclusion rules as the Astro docs collection."""
    count = 0
    for path in sorted(DOCS.rglob("*.md")):
        relative = path.relative_to(DOCS)
        if relative.as_posix() == "index.md" or relative.parts[0] in {"superpowers", "playground"}:
            continue
        count += migrate(path, relative.as_posix())
    print(f"Migrated {count} documentation pages.")


if __name__ == "__main__":
    main()
