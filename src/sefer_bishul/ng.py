import enum
import hashlib
import os
import shutil
import unicodedata
import urllib.parse
from collections import defaultdict
from glob import iglob
from pathlib import Path
from typing import Iterator, NamedTuple, Sequence, cast

import attrs
import typer
import yaml
from jinja2 import Environment, PackageLoader, select_autoescape
from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict
from PIL import Image


def parse_recipe(text: str) -> tuple[str, tuple[str, ...]]:
    """Remove optional YAML frontmatter and validate its tags."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return text, ()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        raise ValueError("חסרה שורת סיום (---) לחזית המתכון")
    metadata = yaml.safe_load("".join(lines[1:end]))
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise ValueError("חזית המתכון חייבת להיות מיפוי YAML")
    tags = metadata.get("תגיות", [])
    if not isinstance(tags, list) or any(
        not isinstance(tag, str) or not tag.strip() for tag in tags
    ):
        raise ValueError("תגיות חייבות להיות רשימה של שמות לא ריקים")
    return "".join(lines[end + 1 :]), tuple(
        dict.fromkeys(unicodedata.normalize("NFC", tag.strip()) for tag in tags)
    )


class TagInfo(NamedTuple):
    name: str
    link: str
    color: str


def tag_info(name: str) -> TagInfo:
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    # Name-based colors and URLs do not shift when another tag is added.
    hue = int(digest[:8], 16) / 0xFFFFFFFF * 360
    return TagInfo(name, f"tags/{digest}.html", f"hsl({hue:.4f} 65% 84%)")


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
    os.makedirs(output / "images", exist_ok=True)
    image_manager = ImageManager(
        in_dir=images, in_url="/images", out_dir=output / "images"
    )
    for path in get_recipes(source):
        md = MarkdownIt(renderer_cls=RecipeRenderer)
        try:
            recipe_text, tags = parse_recipe(path.read_text(encoding="utf-8"))
        except (ValueError, yaml.YAMLError) as error:
            raise ValueError(f"{path}: {error}") from error
        category = path.relative_to(source).parent.as_posix()
        if category != ".":
            tags = tuple(dict.fromkeys((*tags, unicodedata.normalize("NFC", category))))
        tokens = md.parse(recipe_text)
        title = get_title(tokens)
        hero = get_hero(tokens)
        if hero:
            image_manager.add_image(hero)
        rendered = md.render(recipe_text)

        target = (output / path.relative_to(source)).with_suffix(".html")
        target.parent.mkdir(parents=True, exist_ok=True)
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
                tags=[tag_info(tag) for tag in tags],
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

    tagged_recipes: dict[str, list[RecipeInfo]] = defaultdict(list)
    for recipe in recipe_info:
        for name in recipe.tags:
            tagged_recipes[name].append(recipe)
    tag_menu = [
        (tag_info(name), sorted(items))
        for name, items in sorted(tagged_recipes.items())
    ]
    template = get_env().get_template("tags.html")
    (output / "tags.html").write_text(template.render(tags=tag_menu), encoding="utf-8")
    for tag, items in tag_menu:
        target = output / tag.link
        target.parent.mkdir(exist_ok=True)
        target.write_text(template.render(tag=tag, recipes=items), encoding="utf-8")

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
