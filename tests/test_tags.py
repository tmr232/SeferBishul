import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urljoin

import pytest
import yaml

from sefer_bishul.ng import build_book, update_tag_slugs


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
    assert sum(link["href"] == "../r/lbybvt.html" for link in Links(holiday).links) == 1
    assert "מתכונים בתגית" not in holiday
    recipe = (output / "r/svpgnyvt.html").read_text()
    assert recipe.count('class="recipe-tag"') == 3
    category_recipe = (output / "r/lbybvt-qyshvym.html").read_text()
    assert category_recipe.count('class="recipe-tag"') == 1
    assert (output / "r/lbybvt.html").read_text().count('class="recipe-tag"') == 1
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
            base = "https://tmr232.github.io/SeferBishul/"
            page_url = base + quote(page.relative_to(output).as_posix())
            url = urljoin(page_url, str(link["href"]))
            assert url.startswith(base)
            assert (output / unquote(url.removeprefix(base))).is_file()

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
    assert "<h1>לחם</h1>" in (output / "r/lkhm.html").read_text()


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


def test_recipe_and_tag_slug_overrides_and_updates(tmp_path):
    source, output = tmp_path / "recipes", tmp_path / "public"
    write_recipe(source, "ארוחות/ערב/מרק.md", "---\nמזהה: soup\nתגיות: [לחם]\n---\n")
    (source / "שם קובץ.md").write_text("# לחם\n")
    mapping = tmp_path / "tag-slugs.yaml"
    update_tag_slugs(source)
    generated = yaml.safe_load(mapping.read_text())
    assert set(generated) == {"ארוחות/ערב", "לחם"}
    assert generated["לחם"] == "lkhm"

    generated.update({"ארוחות/ערב": "dinner", "לחם": "bread", "תגית ישנה": "retired"})
    mapping.write_text(yaml.safe_dump(generated, allow_unicode=True))
    write_recipe(source, "חדש.md", "---\nתגיות: [אפייה]\n---\n")
    update_tag_slugs(source)
    updated = yaml.safe_load(mapping.read_text())
    assert {name: updated[name] for name in generated} == generated
    assert set(updated) == {*generated, "אפייה"}
    before = mapping.read_bytes()
    update_tag_slugs(source)
    assert mapping.read_bytes() == before

    build_book(source, tmp_path, output)
    assert mapping.read_bytes() == before  # Builds do not rewrite the editable file.
    assert (output / "r/lkhm.html").is_file()
    recipe = (output / "r/soup.html").read_text()
    assert 'href="https://tmr232.github.io/SeferBishul/r/soup.html"' in recipe
    assert 'content="https://tmr232.github.io/SeferBishul/r/soup.html"' in recipe
    assert 'href="../tags/dinner.html"' in recipe
    assert 'href="../tags/bread.html"' in recipe
    assert 'href="../r/soup.html"' in (output / "tags/dinner.html").read_text()
    assert not (output / "tags/retired.html").exists()
    index = (output / "index.html").read_text()
    assert '<h2 class="category">ארוחות/ערב</h2>' in index
    assert 'href="r/soup.html"' in index
    assert any(
        entry["url"] == "r/soup.html"
        for entry in json.loads((output / "search-index.json").read_text())
    )

    # A pinned URL survives both a filename/category move and a title edit.
    (source / "ארוחות/ערב/מרק.md").unlink()
    (source / "שם חדש.md").write_text("---\nמזהה: soup\n---\n# כותרת חדשה\n")
    build_book(source, tmp_path, output)
    assert "<h1>כותרת חדשה</h1>" in (output / "r/soup.html").read_text()


@pytest.mark.parametrize(
    "first,first_metadata,second,second_metadata",
    [
        ("café", "", "cafe", ""),
        ("ראשון", "---\nמזהה: duplicate\n---\n", "שני", "---\nמזהה: duplicate\n---\n"),
        ("ראשון", "---\nמזהה: lkhm\n---\n", "לחם", ""),
    ],
)
def test_duplicate_recipe_slugs_fail_build(
    tmp_path, first, first_metadata, second, second_metadata
):
    source = tmp_path / "recipes"
    write_recipe(source, f"one/{first}.md", first_metadata)
    write_recipe(source, f"two/{second}.md", second_metadata)
    with pytest.raises(ValueError, match="Duplicate slug") as error:
        build_book(source, tmp_path, tmp_path / "public")
    assert f"one/{first}.md" in str(error.value)
    assert f"two/{second}.md" in str(error.value)


@pytest.mark.parametrize(
    "value", ["''", "null", "123", "../escape", "two/slugs", "עברית"]
)
def test_invalid_recipe_slug_fails_build(tmp_path, value):
    source = tmp_path / "recipes"
    write_recipe(source, "לחם.md", f"---\nמזהה: {value}\n---\n")
    with pytest.raises(ValueError, match="לחם.md: Invalid slug"):
        build_book(source, tmp_path, tmp_path / "public")


@pytest.mark.parametrize(
    "saved,tags",
    [
        ({"א": "same", "ב": "same"}, []),
        ({}, ["café", "cafe"]),
        ({"א": "cafe"}, ["cafe"]),
    ],
)
def test_duplicate_tag_slugs_fail_build_and_update(tmp_path, saved, tags):
    source = tmp_path / "recipes"
    write_recipe(
        source,
        "לחם.md",
        "---\n" + yaml.safe_dump({"תגיות": tags}, allow_unicode=True) + "---\n",
    )
    mapping = tmp_path / "tag-slugs.yaml"
    mapping.write_text(yaml.safe_dump(saved, allow_unicode=True))
    before = mapping.read_bytes()
    with pytest.raises(ValueError, match="Duplicate slug"):
        update_tag_slugs(source)
    assert mapping.read_bytes() == before
    with pytest.raises(ValueError, match="Duplicate slug"):
        build_book(source, tmp_path, tmp_path / "public")
