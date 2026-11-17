import enum
import hashlib
import json
import os
import shutil
import unicodedata
import urllib.parse
from collections import defaultdict
from glob import iglob
from pathlib import Path
from typing import Iterator, NamedTuple, Self, Sequence, cast

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


TAGS_FIELD = "תגיות"


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
        raise ValueError("Recipe frontmatter must be a YAML mapping")

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


@attrs.frozen
class TagInfo:
    name: str
    link: str
    color: str

    @classmethod
    def from_name(cls, name: str) -> Self:
        digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
        # Name-based colors and URLs do not shift when another tag is added.
        hue = int(digest[:8], 16) / 0xFFFFFFFF * 360
        return cls(name, f"tags/{digest}.html", f"hsl({hue:.4f} 65% 84%)")


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


class RecipeInfo(NamedTuple):
    name: str
    link: str
    hero: str | None
    tags: tuple[str, ...] = ()


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
        group, _, _ = recipe.link.rpartition("/")
        groups[group].append(recipe)

    result: list[RecipeInfo | RecipeGroup] = sorted(groups.pop("", []))
    for name, recipes in sorted(groups.items()):
        result.append(RecipeGroup(name=name, recipes=sorted(recipes)))

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


def build_book(source: Path, images: Path, output: Path):
    recipe_info: list[RecipeInfo] = []
    search_index: list[dict[str, str]] = []
    os.makedirs(output / "images", exist_ok=True)
    image_manager = ImageManager(
        in_dir=images, in_url="/images", out_dir=output / "images"
    )
    for path in get_recipes(source):
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
        hero = get_hero(tokens)
        if hero:
            image_manager.add_image(hero)
        rendered = md.render(recipe_text)

        target = (output / path.relative_to(source)).with_suffix(".html")
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
                tags=[TagInfo.from_name(tag) for tag in tags],
            )
        )

        target.write_text(html)

        recipe_info.append(
            RecipeInfo(
                name=title,
                link=path.relative_to(source).with_suffix(".html").as_posix(),
                # Temporary hack, because we don't take the website address
                hero=hero.lstrip("/") if hero else None,
                tags=tags,
            )
        )
        search_index.append(search_entry(tokens, recipe_info[-1]))

    (output / "search-index.json").write_text(
        json.dumps(
            sorted(search_index, key=lambda entry: entry["title"]), ensure_ascii=False
        ),
        encoding="utf-8",
    )
    (output / "search.html").write_text(
        get_env().get_template("search.html").render(), encoding="utf-8"
    )

    tagged_recipes: dict[str, list[RecipeInfo]] = defaultdict(list)
    for recipe in recipe_info:
        for name in recipe.tags:
            tagged_recipes[name].append(recipe)

    tag_menu = [
        TagGroup(TagInfo.from_name(name), sorted(items))
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


if __name__ == "__main__":
    main()
