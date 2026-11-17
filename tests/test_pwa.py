import json
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

import pytest
from PIL import Image

from sefer_bishul.ng import build_book


class HeadLinks(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links = {}
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link":
            self.links[attrs["rel"]] = attrs["href"]


@pytest.mark.parametrize("prefix", ["/", "/SeferBishul/"])
def test_installation_paths_and_icons(tmp_path, prefix):
    source, output = tmp_path / "recipes", tmp_path / "public"
    nested = source / "חגים" / "עוד תיקיה"
    nested.mkdir(parents=True)
    text = "# לחם\n\n## חומרים\n\n- קמח\n\n## הכנה\n\nלערבב\n"
    (source / "לחם.md").write_text(text, encoding="utf-8")
    (nested / "לחם.md").write_text(text, encoding="utf-8")
    build_book(source, tmp_path, output)

    origin = "https://example.com"
    manifest_url = origin + prefix + "static/manifest.webmanifest"
    manifest = json.loads((output / "static/manifest.webmanifest").read_text())
    assert manifest["lang"] == "he" and manifest["dir"] == "rtl"
    assert manifest["name"] == "ספר המתכונים של נמיר"
    assert manifest["display"] == "standalone"
    # Omit id so identity defaults to start_url, not a path at the origin root.
    assert "id" not in manifest
    assert urljoin(manifest_url, manifest["scope"]) == origin + prefix
    assert (
        urljoin(manifest_url, manifest["start_url"]) == origin + prefix + "index.html"
    )
    assert (output / "index.html").is_file()

    for page in output.rglob("*.html"):
        page_url = origin + prefix + page.relative_to(output).as_posix()
        links = HeadLinks(page.read_text()).links
        assert urljoin(page_url, links["manifest"]) == manifest_url
        assert urljoin(page_url, links["apple-touch-icon"]) == (
            origin + prefix + "static/icons/apple-touch-icon.png"
        )

    assert {(icon["sizes"], icon["purpose"]) for icon in manifest["icons"]} >= {
        ("192x192", "any"),
        ("512x512", "any"),
        ("512x512", "maskable"),
    }
    for icon in manifest["icons"]:
        path = unquote(urlsplit(urljoin(manifest_url, icon["src"])).path)
        with Image.open(output / path.removeprefix(prefix)) as image:
            assert image.format == "PNG"
            assert image.size == tuple(map(int, icon["sizes"].split("x")))
            assert image.mode == "RGB"
    with Image.open(output / "static/icons/apple-touch-icon.png") as image:
        assert image.size == (180, 180)
