import json
from pathlib import Path

from sefer_bishul.ng import build_book


def test_build_search_index_from_recipe_sections(tmp_path: Path):
    source, output = tmp_path / "recipes", tmp_path / "public"
    nested = source / "תיקייה" / "עוד תיקייה"
    nested.mkdir(parents=True)
    (nested / "לחם & זיתים.md").write_text(
        "---\nתגיות: [סודמטא]\n---\n"
        "# לחם & זיתים\n\nהערת פתיחה\n\n"
        "## מרכיבים\n\n- **קמח**\n- [זיתים](https://example.com/secret)\n"
        "### תוספות\n\n- `מלח`\n\n"
        "## הוראות הכנה\n\nללוש\nהיטב\n\n### אפייה\n\nלאפות\n\n```\nחום נמוך\n```\n",
        encoding="utf-8",
    )
    (source / "קצר.md").write_text("# קצר\n\nבלי סעיפים\n", encoding="utf-8")
    build_book(source, tmp_path, output)
    entries = json.loads((output / "search-index.json").read_text())
    assert entries == [
        {
            "title": "לחם & זיתים",
            "url": "תיקייה/עוד תיקייה/לחם & זיתים.html",
            "ingredients": "מרכיבים קמח זיתים תוספות מלח",
            "instructions": "הוראות הכנה ללוש היטב אפייה לאפות חום נמוך",
            "text": "לחם & זיתים הערת פתיחה מרכיבים קמח זיתים תוספות מלח הוראות הכנה ללוש היטב אפייה לאפות חום נמוך",
        },
        {
            "title": "קצר",
            "url": "קצר.html",
            "ingredients": "",
            "instructions": "",
            "text": "קצר בלי סעיפים",
        },
    ]
    assert (output / entries[0]["url"]).is_file()
    assert 'lang="he" dir="rtl"' in (output / "search.html").read_text()
    for asset in ("search.js", "search-engine.mjs", "search.css"):
        assert (output / "static" / asset).is_file()
    for page in output.rglob("*.html"):
        if page.name != "search.html":
            assert 'search.html"' in page.read_text()
