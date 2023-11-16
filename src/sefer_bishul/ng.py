import enum
from collections import defaultdict
from markdown_it import MarkdownIt
from markdown_it.token import Token
from markdown_it.renderer import RendererHTML
from markdown_it.utils import OptionsDict, EnvType
from itertools import takewhile
from glob import iglob
from pathlib import Path
from typing import Iterator, Sequence, NamedTuple
from typer import Typer
from jinja2 import Environment, PackageLoader, select_autoescape
import attrs


def get_title(tokens: list[Token]) -> str:
    tokens = iter(tokens)
    for token in tokens:
        if token.tag == "h1":
            break
    return next(tokens).content


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
        # return super().render(tokens, options, env) + self.__close_divs()
        return super().render(tokens, options, env) + "</div>" * 2

    def heading_open(
        self, tokens: Sequence[Token], idx: int, options: OptionsDict, env: EnvType
    ) -> str:
        result = ""
        token = tokens[idx]
        prefix = self.__sm.process(token)
        # if self.__current_heading >= token.tag:
        #     result += "</div>"
        # self.__current_heading = token.tag
        # result += "<div>"
        # return result + self.renderToken(tokens, idx, options, env)
        return prefix + self.renderToken(tokens, idx, options, env)


class RecipeInfo(NamedTuple):
    name: str
    link: str


class RecipeGroup(NamedTuple):
    name: str
    recipes: list[RecipeInfo]
    is_group: bool = True


def generate_toc(recipes: list[RecipeInfo]) -> list[RecipeInfo | RecipeGroup]:
    groups = defaultdict(list)
    for recipe in recipes:
        group, _, _ = recipe.link.rpartition("/")
        groups[group].append(recipe)

    result = sorted(groups.pop("", []))
    for name, recipes in sorted(groups.items()):
        result.append(RecipeGroup(name=name, recipes=sorted(recipes)))

    return result


def main():
    source = Path("../../recipes")
    output = Path("../../html")

    recipe_info: list[RecipeInfo] = []

    for path in get_recipes(source):
        md = MarkdownIt(renderer_cls=RecipeRenderer)
        recipe_text = path.read_text()
        title = get_title(md.parse(recipe_text))
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
            )
        )

    toc_info = generate_toc(recipe_info)
    toc = get_env().get_template("toc.html.j2").render(toc=toc_info)
    (output / "index.html").write_text(toc)


if __name__ == "__main__":
    main()
