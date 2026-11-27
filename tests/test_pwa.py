import hashlib
import json
import struct
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

import pytest
from PIL import IcoImagePlugin, Image

from sefer_bishul.ng import build_book


class HeadLinks(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links = {}
        self.anchors = []
        self.meta_names = set()
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link":
            self.links[attrs["rel"]] = attrs["href"]
        elif tag == "a":
            self.anchors.append(attrs["href"])
        elif tag == "meta":
            self.meta_names.add(attrs.get("name", "").lower())


@pytest.mark.parametrize("prefix", ["/", "/SeferBishul/"])
def test_installation_paths_and_icons(tmp_path, prefix):
    source, output = tmp_path / "recipes", tmp_path / "public"
    nested = source / "חגים" / "עוד תיקיה"
    nested.mkdir(parents=True)
    text = "# לחם\n\n## חומרים\n\n- קמח\n\n## הכנה\n\nלערבב\n"
    (source / "לחם.md").write_text(text, encoding="utf-8")
    (nested / "לחם.md").write_text(text, encoding="utf-8")
    build_book(source, tmp_path, output, site_url="https://example.com" + prefix)

    origin = "https://example.com"
    manifest_url = origin + prefix + "static/manifest.webmanifest"
    manifest = json.loads((output / "static/manifest.webmanifest").read_text())
    assert manifest["lang"] == "he" and manifest["dir"] == "rtl"
    assert manifest["name"] == "ספר המתכונים של נמיר"
    assert manifest["display"] == "standalone"
    assert "theme_color" not in manifest
    assert manifest["background_color"] == "#ffffff"
    # Omit id so identity defaults to start_url, not a path at the origin root.
    assert "id" not in manifest
    assert urljoin(manifest_url, manifest["scope"]) == origin + prefix
    assert (
        urljoin(manifest_url, manifest["start_url"]) == origin + prefix + "index.html"
    )
    assert (output / "index.html").is_file()

    for page in output.rglob("*.html"):
        page_url = origin + prefix + page.relative_to(output).as_posix()
        head = HeadLinks(page.read_text())
        assert "theme-color" not in head.meta_names
        links = head.links
        assert urljoin(page_url, links["manifest"]) == manifest_url
        assert urljoin(page_url, links["apple-touch-icon"]) == (
            origin + prefix + "static/icons/apple-touch-icon.png"
        )
        favicon_url = urljoin(page_url, links["icon"])
        assert favicon_url == origin + prefix + "static/favicon.ico"
        assert (output / urlsplit(favicon_url).path.removeprefix(prefix)).is_file()

    error_text = (output / "404.html").read_text()
    assert "אופס! כנראה הזזנו את המתכון. תשאלו את טמיר או נעם איפה הוא" in error_text
    assert 'lang="he" dir="rtl"' in error_text
    assert "share-link" not in error_text
    error = HeadLinks(error_text)
    assert error.anchors == [
        prefix + name for name in ("index.html", "tags.html", "search.html")
    ]
    # Pages serves the same 404 HTML at the missing URL, not at /404.html.
    for missing in ("deleted.html", "חגים/עוד/מתכון-חסר.html"):
        missing_url = origin + prefix + missing
        for link in error.anchors + list(error.links.values()):
            target_url = urljoin(missing_url, link)
            assert target_url.startswith(origin + prefix)
            assert (output / urlsplit(target_url).path.removeprefix(prefix)).is_file()

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

    favicon = output / "static/favicon.ico"
    with Image.open(favicon) as image:
        assert isinstance(image, IcoImagePlugin.IcoImageFile)
        assert image.format == "ICO"
        assert image.ico.sizes() == {(16, 16), (32, 32), (48, 48)}

    # SHA-256 of the owner's original PNG exports: each payload stays byte-for-byte
    # intact, rather than deriving the smaller frames by resizing the largest one.
    original_hashes = {
        16: "8fb2a90fa83a4d48c193a8069cdfc11c65e60363650202a4c7bb14219f53bf20",
        32: "dc58c5dbeb76913dbdc9e2c0a2017156b385e5b6740799617098f5dfa5bb8461",
        48: "cdf3216b2f13dbdbc69de7dc3f71dab1b7046a7ce97f5ad3bc92db28e43701a1",
    }
    data = favicon.read_bytes()
    assert struct.unpack_from("<HHH", data) == (0, 1, 3)
    for index, size in enumerate((16, 32, 48)):
        width, height, _, _, _, depth, length, offset = struct.unpack_from(
            "<BBBBHHII", data, 6 + 16 * index
        )
        assert (width, height, depth) == (size, size, 32)
        assert (
            hashlib.sha256(data[offset : offset + length]).hexdigest()
            == (original_hashes[size])
        )
