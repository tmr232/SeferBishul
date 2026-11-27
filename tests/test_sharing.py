from html.parser import HTMLParser
from urllib.parse import quote, unquote, urlsplit

import pytest
from PIL import Image

from sefer_bishul.ng import SITE_URL, build_book


class SharingPage(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.meta = {}
        self.links = []
        self.canonical = None
        self.share_url = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            self.meta[attrs.get("property", attrs.get("name"))] = attrs.get("content")
        elif tag == "a":
            self.links.append(attrs)
            if attrs.get("id") == "share-link":
                self.share_url = attrs["href"]
        elif tag == "link" and attrs.get("rel") == "canonical":
            self.canonical = attrs["href"]


@pytest.mark.parametrize(
    "base", [SITE_URL, "https://tmr232.github.io/SeferBishul/", "https://example.com/"]
)
def test_recipe_sharing_and_external_navigation(tmp_path, base):
    source, output, images = (
        tmp_path / name for name in ("recipes", "public", "images")
    )
    nested = source / "חגים" / "עוד תיקייה"
    nested.mkdir(parents=True)
    images.mkdir()
    Image.new("RGB", (600, 400)).save(images / "לחם & זיתים.jpg")
    links = [
        "https://external.example/recipe",
        "//external.example/recipe",
        base + "r/lkhm.html",
        "../r/lkhm.html",
        "#הכנה",
        "mailto:cook@example.com",
    ]
    if "/SeferBishul/" in base:
        links += ["https://tmr232.github.io/other/", "/SeferBishul-other/recipe"]
    text = '# לחם & "זיתים"\n\nפתיחה עם **טעם** & שמן.\n\n'
    text += "![לחם](/images/לחם%20%26%20זיתים.jpg)\n\n"
    text += "\n\n".join(f"[קישור {i}]({link})" for i, link in enumerate(links))
    text += "\n\n## חומרים\n\n- קמח\n\n## הכנה\n\nללוש\n"
    recipe_path = nested / "לחם & זיתים.md"
    recipe_path.write_text(text, encoding="utf-8")
    (source / "קצר.md").write_text("# קצר\n", encoding="utf-8")
    (source / "ארוך.md").write_text("# ארוך\n\n" + "א" * 205, encoding="utf-8")
    build_book(source, images, output, site_url=base)

    page = SharingPage((output / "r/lkhm-zytym.html").read_text())
    expected_url = base + "r/lkhm-zytym.html"
    assert page.canonical == page.meta["og:url"] == page.share_url == expected_url
    assert page.meta["og:title"] == 'לחם & "זיתים"'
    assert page.meta["og:description"].startswith("פתיחה עם טעם & שמן.")
    assert page.meta["og:description"] == page.meta["description"]
    assert len(page.meta["description"]) <= 200
    assert page.meta["og:type"] == "article"
    assert page.meta["og:locale"] == "he_IL"
    assert page.meta["og:image"] == base + quote("images/לחם & זיתים.jpg")
    assert page.meta["og:image:alt"] == 'לחם & "זיתים"'
    image_path = unquote(
        urlsplit(page.meta["og:image"]).path.removeprefix(urlsplit(base).path)
    )
    assert (output / image_path).is_file()

    # The first links are cookbook navigation; the recipe links follow them.
    recipe_links = page.links[5:]
    assert len(recipe_links) == len(links)
    for i, link in enumerate(recipe_links):
        external = i in {0, 1, 6, 7}
        assert (link.get("target") == "_blank") is external
        if external:
            assert set(link["rel"].split()) == {"noopener", "noreferrer"}
    assert all("target" not in link for link in page.links[:5])

    short = SharingPage((output / "r/qtsr.html").read_text())
    assert short.meta["og:image"] == base + "static/icons/icon-512.png"
    assert short.meta["description"] == "מתכון לקצר מתוך ספר המתכונים של נמיר"
    long = SharingPage((output / "r/rvk.html").read_text())
    assert long.meta["og:description"] == "א" * 197 + "…"
    assert (output / "static/share.js").is_file()
