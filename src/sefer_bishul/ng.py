import enum
import hashlib
import json
import os
import re
import shutil
import unicodedata
import urllib.parse
from collections import defaultdict
from collections.abc import Iterator, Sequence
from glob import iglob
from pathlib import Path
from typing import NamedTuple, Self, cast

import attrs
import typer
import yaml
from jinja2 import Environment, PackageLoader, select_autoescape
from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict
from more_itertools import split_at
from PIL import Image
from slugify import slugify

TAGS_FIELD = "תגיות"
SLUG_FIELD = "מזהה"
SITE_URL = "https://tmr232.github.io/SeferBishul/"


@attrs.frozen
class ParsedFrontmatter:
    text: str
    frontmatter: dict[str, object]


def parse_frontmatter(text: str) -> ParsedFrontmatter:
    """Separate optional YAML frontmatter from the recipe's Markdown text."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return ParsedFrontmatter(text=text, frontmatter={})

    sections = split_at(lines[1:], lambda line: line.strip() == "---", maxsplit=1)
    metadata_lines = next(sections)
    body = next(sections, None)
    if body is None:
        raise ValueError("Missing closing frontmatter delimiter (---)")

    metadata = yaml.safe_load("".join(metadata_lines))
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        # Invalid recipe data keeps the same ValueError contract as other metadata.
        raise ValueError("Recipe frontmatter must be a YAML mapping")  # noqa: TRY004

    return ParsedFrontmatter(text="".join(body), frontmatter=metadata)


def parse_tags(frontmatter: dict[str, object]) -> tuple[str, ...]:
    """Validate and normalize tag names from parsed frontmatter."""
    tags = frontmatter.get(TAGS_FIELD, [])
    if not isinstance(tags, list) or any(
        not isinstance(tag, str) or not tag.strip() for tag in tags
    ):
        raise ValueError(f"{TAGS_FIELD!r} must be a list of non-empty strings")

    return tuple(
        dict.fromkeys(unicodedata.normalize("NFC", tag.strip()) for tag in tags)
    )


def get_tags_from_path(path: Path) -> tuple[str, ...]:
    """Get the directory category from a recipe path relative to the source root."""
    category = path.parent.as_posix()
    if category == ".":
        return ()

    return (unicodedata.normalize("NFC", category),)


def validate_slug(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[a-z0-9]+(?:-[a-z0-9]+)*", value
    ):
        raise ValueError(
            f"Invalid slug {value!r}: use lowercase ASCII letters, digits and single hyphens"
        )
    return value


def validate_unique_slugs(slugs: dict[str, str]) -> None:
    owners: dict[str, str] = {}
    for name, slug in slugs.items():
        if slug in owners:
            raise ValueError(f"Duplicate slug {slug!r}: {owners[slug]!r} and {name!r}")
        owners[slug] = name


def get_tag_slugs(source: Path, path: Path) -> dict[str, str]:
    """Keep saved tag URLs, including retired tags, and default only new names."""
    saved = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(saved, dict):
        # Invalid input data uses the same ValueError contract as frontmatter.
        raise ValueError(f"{path}: tag slugs must be a YAML mapping")  # noqa: TRY004
    slugs: dict[str, str] = {}
    for name, slug in saved.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{path}: tag names must be non-empty strings")
        normalized = unicodedata.normalize("NFC", name.strip())
        if normalized in slugs:
            raise ValueError(f"{path}: duplicate tag name {normalized!r}")
        try:
            slugs[normalized] = validate_slug(slug)
        except ValueError as error:
            raise ValueError(f"{path}: tag {name!r}: {error}") from error
    for recipe in sorted(get_recipes(source)):
        try:
            parsed = parse_frontmatter(recipe.read_text(encoding="utf-8"))
            tags = (
                *parse_tags(parsed.frontmatter),
                *get_tags_from_path(recipe.relative_to(source)),
            )
            for name in tags:
                if name not in slugs:
                    try:
                        slugs[name] = validate_slug(slugify(name))
                    except ValueError as error:
                        raise ValueError(
                            f"Tag {name!r}: {error}; set its slug in {path}"
                        ) from error
        except (ValueError, yaml.YAMLError) as error:
            raise ValueError(f"{recipe}: {error}") from error
    validate_unique_slugs(slugs)
    return slugs


def update_tag_slugs(source: Path, tag_slugs: Path | None = None) -> None:
    """Create/update the editable tag slug mapping without replacing saved values."""
    path = tag_slugs if tag_slugs is not None else source.parent / "tag-slugs.yaml"
    slugs = get_tag_slugs(source, path)
    path.write_text(
        yaml.safe_dump(slugs, allow_unicode=True, sort_keys=True), encoding="utf-8"
    )
    typer.echo(f"Updated {path} ({len(slugs)} tags)")


@attrs.frozen
class TagInfo:
    name: str
    link: str
    color: str

    @classmethod
    def from_name(cls, name: str, slug: str) -> Self:
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
        # Name-based colors do not shift when a URL changes or another tag is added.
        hue = int(digest[:8], 16) / 0xFFFFFFFF * 360
        return cls(name, f"tags/{slug}.html", f"hsl({hue:.4f} 65% 84%)")


def get_title(tokens: list[Token]) -> str:
    token_iterator: Iterator[Token] = iter(tokens)
    for token in token_iterator:
        if token.tag == "h1":
            break
    return next(token_iterator).content


def get_hero(tokens: list[Token]) -> str | None:
    def _iter():
        for token in tokens:
            if token.type == "inline":
                if token.children is not None:
                    yield from token.children
            else:
                yield token

    tokens = list(_iter())
    for token in tokens:
        if token.type == "image":
            break
    else:
        return None
    return urllib.parse.unquote(cast(str, token.attrs.get("src")))


def get_recipes(root: Path | str) -> Iterator[Path]:
    root = Path(root)
    for path in iglob("**/*.md", root_dir=root, recursive=True):
        yield root / path


def get_env() -> Environment:
    return Environment(
        loader=PackageLoader("sefer_bishul", "templates"),
        autoescape=select_autoescape(),
    )


class State(enum.Enum):
    Start = enum.auto()
    TitleFound = enum.auto()
    IngredientsFound = enum.auto()
    PrepFound = enum.auto()


@attrs.define
class RecipeMachine:
    state: State = State.Start

    def process(self, token: Token) -> str:
        match self.state, token:
            case State.Start, Token(type="heading_open", tag="h1"):
                self.state = State.TitleFound
            case State.TitleFound, Token(type="heading_open", tag="h2"):
                self.state = State.IngredientsFound
                return '<div class="recipe-body"><div class="ingredients">'
            case State.IngredientsFound, Token(type="heading_open", tag="h2"):
                self.state = State.PrepFound
                return '</div><div class="prep">'
        return ""


class RecipeRenderer(RendererHTML):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.__current_heading = ""
        self.__sm = RecipeMachine()

    def __close_divs(self) -> str:
        if self.__current_heading:
            return "</div>" * int(self.__current_heading[1:])
        return ""

    def render(
        self, tokens: Sequence[Token], options: OptionsDict, env: EnvType
    ) -> str:
        return super().render(tokens, options, env) + "</div>" * 2

    def heading_open(
        self, tokens: Sequence[Token], idx: int, options: OptionsDict, env: EnvType
    ) -> str:
        token = tokens[idx]
        prefix = self.__sm.process(token)
        return prefix + self.renderToken(tokens, idx, options, env)

    def image(
        self, tokens: Sequence[Token], idx: int, options: OptionsDict, env: EnvType
    ) -> str:
        return ""

    def link_open(
        self, tokens: Sequence[Token], idx: int, options: OptionsDict, env: EnvType
    ) -> str:
        token = tokens[idx]
        url = urllib.parse.urlsplit(
            urllib.parse.urljoin(env["page_url"], token.attrGet("href") or "")
        )
        site = urllib.parse.urlsplit(env["site_url"])
        if url.scheme in {"https", "http"} and (
            (url.scheme, url.netloc) != (site.scheme, site.netloc)
            or not url.path.startswith(site.path)
        ):
            token.attrSet("target", "_blank")
            token.attrSet("rel", "noopener noreferrer")
            token.attrSet("title", "קישור חיצוני")
        return self.renderToken(tokens, idx, options, env)


class RecipeInfo(NamedTuple):
    name: str
    link: str
    hero: str | None
    tags: tuple[str, ...] = ()
    category: str = ""


def search_entry(tokens: list[Token], recipe: RecipeInfo) -> dict[str, str]:
    """Index visible text using the same section boundaries as the recipe renderer."""
    machine = RecipeMachine()
    sections: dict[State, list[str]] = defaultdict(list)
    full_text: list[str] = []
    for token in tokens:
        machine.process(token)
        if token.type in {"fence", "code_block"}:
            text = token.content.strip()
        elif token.type == "inline":
            parts = []
            for child in token.children or []:
                if child.type in {"text", "code_inline"}:
                    parts.append(child.content)
                elif child.type in {"softbreak", "hardbreak"}:
                    parts.append(" ")
            text = "".join(parts)
        else:
            continue
        full_text.append(text)
        sections[machine.state].append(text)
    return {
        "title": recipe.name,
        "url": recipe.link,
        "ingredients": " ".join(sections[State.IngredientsFound]),
        "instructions": " ".join(sections[State.PrepFound]),
        "text": " ".join(full_text),
    }


@attrs.frozen
class TagGroup:
    tag: TagInfo
    recipes: list[RecipeInfo]


class RecipeGroup(NamedTuple):
    name: str
    recipes: list[RecipeInfo]
    is_group: bool = True


def generate_toc(recipes: list[RecipeInfo]) -> list[RecipeInfo | RecipeGroup]:
    groups = defaultdict(list)
    for recipe in recipes:
        groups[recipe.category].append(recipe)

    result: list[RecipeInfo | RecipeGroup] = sorted(groups.pop("", []))
    for name, group_recipes in sorted(groups.items()):
        result.append(RecipeGroup(name=name, recipes=sorted(group_recipes)))

    return result


@attrs.define
class ImageManager:
    in_dir: Path
    in_url: str
    out_dir: Path

    def add_image(self, url: str):
        relative_path = Path(url).relative_to(self.in_url)
        in_path = self.in_dir / relative_path
        out_path = self.out_dir / relative_path

        self._process(in_path, out_path)

    def _process(self, in_path: Path, out_path: Path):
        im = Image.open(in_path)
        im.thumbnail((512, 512))
        im.save(out_path)


def copy_static_files(output: Path) -> None:
    shutil.copytree(
        Path(__file__).parent / "static", output / "static", dirs_exist_ok=True
    )


def build_book(
    source: Path,
    images: Path,
    output: Path,
    site_url: str = SITE_URL,
    tag_slugs: Path | None = None,
):
    site_url = site_url.rstrip("/") + "/"
    site = urllib.parse.urlsplit(site_url)
    if (
        site.scheme not in {"https", "http"}
        or not site.netloc
        or site.query
        or site.fragment
    ):
        raise ValueError("site_url must be an absolute HTTP(S) base URL")
    recipe_info: list[RecipeInfo] = []
    search_index: list[dict[str, str]] = []
    tag_urls = get_tag_slugs(
        source, tag_slugs if tag_slugs is not None else source.parent / "tag-slugs.yaml"
    )
    recipe_slugs: dict[str, str] = {}
    os.makedirs(output / "images", exist_ok=True)
    image_manager = ImageManager(
        in_dir=images, in_url="/images", out_dir=output / "images"
    )
    for path in sorted(get_recipes(source)):
        md = MarkdownIt(renderer_cls=RecipeRenderer)
        try:
            parsed = parse_frontmatter(path.read_text(encoding="utf-8"))
            tags = parse_tags(parsed.frontmatter)
        except (ValueError, yaml.YAMLError) as error:
            raise ValueError(f"{path}: {error}") from error

        tags = tuple(
            dict.fromkeys((*tags, *get_tags_from_path(path.relative_to(source))))
        )
        recipe_text = parsed.text
        tokens = md.parse(recipe_text)
        title = get_title(tokens)
        try:
            slug = validate_slug(parsed.frontmatter.get(SLUG_FIELD, slugify(title)))
        except ValueError as error:
            raise ValueError(f"{path}: {error}") from error
        recipe_slugs[str(path)] = slug
        validate_unique_slugs(recipe_slugs)
        hero = get_hero(tokens)
        if hero:
            image_manager.add_image(hero)
        link = f"r/{slug}.html"
        page_url = site_url + urllib.parse.quote(link)
        category = path.relative_to(source).parent.as_posix()
        recipe = RecipeInfo(
            title,
            link,
            hero.lstrip("/") if hero else None,
            tags,
            "" if category == "." else category,
        )
        entry = search_entry(tokens, recipe)
        description = entry["text"].removeprefix(title).strip()
        description = description[:197] + "…" if len(description) > 200 else description
        description = description or f"מתכון ל{title} מתוך ספר המתכונים של נמיר"
        image_url = site_url + urllib.parse.quote(
            recipe.hero or "static/icons/icon-512.png"
        )
        rendered = md.render(recipe_text, {"page_url": page_url, "site_url": site_url})

        target = output / link
        target.parent.mkdir(parents=True, exist_ok=True)
        # Links must reach the book root from this recipe's directory, not the domain root.
        root_prefix = output.relative_to(target.parent, walk_up=True).as_posix()

        wakelock_script = (
            (output / "static" / "wakelock.js")
            .relative_to(target.parent, walk_up=True)
            .as_posix()
        )
        html = (
            get_env()
            .get_template("recipe.html")
            .render(
                title=title,
                content=rendered,
                wakelock_script=wakelock_script,
                root_prefix=root_prefix,
                tags=[TagInfo.from_name(tag, tag_urls[tag]) for tag in tags],
                page_url=page_url,
                description=description,
                image_url=image_url,
                image_alt=title if hero else "ספר המתכונים של נמיר",
            )
        )

        target.write_text(html)

        recipe_info.append(recipe)
        search_index.append(entry)

    (output / "search-index.json").write_text(
        json.dumps(
            sorted(search_index, key=lambda entry: entry["title"]), ensure_ascii=False
        ),
        encoding="utf-8",
    )
    (output / "search.html").write_text(
        get_env().get_template("search.html").render(), encoding="utf-8"
    )
    (output / "404.html").write_text(
        get_env().get_template("404.html").render(root_prefix=site.path.rstrip("/")),
        encoding="utf-8",
    )

    tagged_recipes: dict[str, list[RecipeInfo]] = defaultdict(list)
    for recipe in recipe_info:
        for name in recipe.tags:
            tagged_recipes[name].append(recipe)

    tag_menu = [
        TagGroup(TagInfo.from_name(name, tag_urls[name]), sorted(items))
        for name, items in sorted(tagged_recipes.items())
    ]
    template = get_env().get_template("tags.html")
    (output / "tags.html").write_text(template.render(tags=tag_menu), encoding="utf-8")

    for group in tag_menu:
        target = output / group.tag.link
        target.parent.mkdir(exist_ok=True)
        target.write_text(
            template.render(tag=group.tag, recipes=group.recipes), encoding="utf-8"
        )

    toc_info = generate_toc(recipe_info)
    toc = get_env().get_template("toc.html.j2").render(toc=toc_info)
    (output / "index.html").write_text(toc)

    toc = get_env().get_template("pics.html.j2").render(recipes=recipe_info)
    (output / "picture-menu.html").write_text(toc)

    copy_static_files(output)


def main():
    typer.run(build_book)


def tag_slugs_main():
    typer.run(update_tag_slugs)


if __name__ == "__main__":
    main()
