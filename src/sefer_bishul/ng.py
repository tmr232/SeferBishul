import enum
import os
import urllib.parse
from collections import defaultdict
from glob import iglob
from pathlib import Path
from typing import Iterator, NamedTuple, Sequence

import attrs
import rich
import typer
from jinja2 import Environment, PackageLoader, select_autoescape
from markdown_it import MarkdownIt
from markdown_it.renderer import RendererHTML
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict
from PIL import Image


def get_title(tokens: list[Token]) -> str:
    tokens: Iterator[Token] = iter(tokens)  # type:ignore[no-redef]
    for token in tokens:
        if token.tag == "h1":
            break
    return next(tokens).content  # type:ignore[call-overload]


def get_hero(tokens: list[Token]) -> str:
    def _iter():
        for token in tokens:
            if token.type == "inline":
                yield from token.children
            else:
                yield token

    tokens = list(_iter())
    for token in tokens:
        if token.type == "image":
            rich.print(token)
            break
    else:
        return None
    return urllib.parse.unquote(token.attrs.get("src"))  # type:ignore[call-overload]


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

    # def image(self, tokens: Sequence[Token], idx: int, options: OptionsDict, env: EnvType) -> str:
    #     return ""


class RecipeInfo(NamedTuple):
    name: str
    link: str
    hero: str


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


def build_book(source: Path, images: Path, output: Path):
    recipe_info: list[RecipeInfo] = []
    os.makedirs(output / "images", exist_ok=True)
    image_manager = ImageManager(
        in_dir=images, in_url="/images", out_dir=output / "images"
    )
    for path in get_recipes(source):
        md = MarkdownIt(renderer_cls=RecipeRenderer)
        recipe_text = path.read_text()
        tokens = md.parse(recipe_text)
        title = get_title(tokens)
        hero = get_hero(tokens)
        if hero:
            image_manager.add_image(hero)
        rendered = md.render(recipe_text)

        html = (
            get_env().get_template("recipe.html").render(title=title, content=rendered)
        )

        target = (output / path.relative_to(source)).with_suffix(".html")
        target.parent.mkdir(exist_ok=True)

        target.write_text(html)

        recipe_info.append(
            RecipeInfo(
                name=title,
                link=str(path.relative_to(source).with_suffix(".html")).replace(
                    "\\", "/"
                ),
                hero=hero,
            )
        )

    toc_info = generate_toc(recipe_info)
    toc = get_env().get_template("toc.html.j2").render(toc=toc_info)
    (output / "index.html").write_text(toc)


    toc = get_env().get_template("pics.html.j2").render(recipes=recipe_info)
    (output / "pics.html").write_text(toc)


def main():
    typer.run(build_book)


if __name__ == "__main__":
    main()
