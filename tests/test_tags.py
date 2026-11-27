from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote

import pytest

from sefer_bishul.ng import build_book


class Links(HTMLParser):
    def __init__(self, text: str):
        super().__init__()
        self.links: list[dict[str, str | None]] = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs))


def write_recipe(source: Path, name: str, frontmatter: str = ""):
    target = source / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        f"{frontmatter}# {target.stem}\n\n## חומרים\n\n- קמח\n\n## הכנה\n\nלערבב\n"
    )


def test_build_multi_tag_navigation_and_stable_colors(tmp_path):
    source, output = tmp_path / "recipes", tmp_path / "public"
    write_recipe(
        source,
        "חגים/עוד תיקיה/סופגניות.md",
        "---\nתגיות:\n  - חנוכה\n  - ' טיגון עמוק '\n  - חנוכה\n---\n",
    )
    write_recipe(source, "חנוכה/לביבות.md", "---\nתגיות: [חנוכה]\n---\n")
    write_recipe(source, "חגים/עוד תיקיה/לביבות קישואים.md")
    write_recipe(source, "לחם.md")
    write_recipe(source, "מיוחד.md", "---\nתגיות: ['<תגית & מיוחדת>']\n---\n")
    build_book(source, tmp_path, output)

    menu = (output / "tags.html").read_text()
    tiles = [link for link in Links(menu).links if link.get("class") == "tag-tile"]
    assert len(tiles) == 4
    assert len({link["style"] for link in tiles}) == 4
    assert "&lt;תגית &amp; מיוחדת&gt;" in menu
    assert 'lang="he" dir="rtl"' in menu
    pages = [(output / str(link["href"])).read_text() for link in tiles]
    holiday = next(page for page in pages if "<h1>חנוכה</h1>" in page)
    fried = next(page for page in pages if "<h1>טיגון עמוק</h1>" in page)
    category = next(page for page in pages if "<h1>חגים/עוד תיקיה</h1>" in page)
    assert "סופגניות" in holiday and "לביבות" in holiday and "לחם" not in holiday
    assert "סופגניות" in fried and "לביבות" not in fried
    assert "סופגניות" in category and "לביבות קישואים" in category
    assert "לחם" not in category
    assert (
        sum(link["href"] == "../חנוכה/לביבות.html" for link in Links(holiday).links)
        == 1
    )
    assert "מתכונים בתגית" not in holiday
    recipe = (output / "חגים/עוד תיקיה/סופגניות.html").read_text()
    assert recipe.count('class="recipe-tag"') == 3
    category_recipe = (output / "חגים/עוד תיקיה/לביבות קישואים.html").read_text()
    assert category_recipe.count('class="recipe-tag"') == 1
    assert (output / "חנוכה/לביבות.html").read_text().count('class="recipe-tag"') == 1
    assert "תגיות:" not in recipe and "<h1>סופגניות</h1>" in recipe
    assert "לחם" in (output / "index.html").read_text()
    index_links = {
        link["href"]: link for link in Links((output / "index.html").read_text()).links
    }
    assert index_links["tags.html"]["aria-label"] == "מתכונים לפי תגיות"
    assert index_links["picture-menu.html"]["aria-label"] == "מתכונים בתמונות"
    # Every navigation link, including nested recipe return links, resolves.
    for page in output.rglob("*.html"):
        for link in Links(page.read_text()).links:
            if link.get("id") == "share-link":
                assert link["href"] == "https://tmr232.github.io/SeferBishul/" + quote(
                    page.relative_to(output).as_posix()
                )
            else:
                assert (page.parent / unquote(str(link["href"]))).is_file()

    write_recipe(source, "חדש.md", "---\nתגיות: [אפייה]\n---\n")
    build_book(source, tmp_path, output)
    new_tiles = Links((output / "tags.html").read_text()).links
    for tile in tiles:
        assert tile in new_tiles


def test_build_without_tags(tmp_path):
    source, output = tmp_path / "recipes", tmp_path / "public"
    write_recipe(source, "לחם.md", "---\nnotes: הערה\n---\n")
    build_book(source, tmp_path, output)
    assert "עדיין אין תגיות" in (output / "tags.html").read_text()
    assert "<h1>לחם</h1>" in (output / "לחם.html").read_text()


@pytest.mark.parametrize(
    "metadata",
    [
        "תגיות: חנוכה",
        "תגיות: [חנוכה, 7]",
        "תגיות: [' ']",
        "תגיות: null",
        "- חנוכה",
        "תגיות: [",
    ],
)
def test_invalid_frontmatter_identifies_recipe(tmp_path, metadata):
    source = tmp_path / "recipes"
    write_recipe(source, "לא תקין.md", f"---\n{metadata}\n---\n")
    with pytest.raises(ValueError, match="לא תקין.md"):
        build_book(source, tmp_path, tmp_path / "public")


def test_unclosed_frontmatter(tmp_path):
    source = tmp_path / "recipes"
    write_recipe(source, "לא סגור.md", "---\nתגיות: [חנוכה]\n")
    with pytest.raises(ValueError, match="לא סגור.md"):
        build_book(source, tmp_path, tmp_path / "public")
