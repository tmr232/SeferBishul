from markdown_it import MarkdownIt
from markdown_it.token import Token
from markdown_it.renderer import RendererHTML
from markdown_it.utils import OptionsDict, EnvType
from itertools import takewhile
from glob import iglob
from pathlib import Path
from typing import Iterator, Sequence
from typer import Typer
from jinja2 import Environment, PackageLoader, select_autoescape
import attrs


def get_title(tokens: list[Token]) -> str:
    for token in tokens:
        print(token)
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


class RecipeRenderer(RendererHTML):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.__current_heading = ""

    def __close_divs(self) -> str:
        if self.__current_heading:
            return "</div>" * int(self.__current_heading[1:])
        return ""

    def render(
        self, tokens: Sequence[Token], options: OptionsDict, env: EnvType
    ) -> str:
        return super().render(tokens, options, env) + self.__close_divs()

    def heading_open(
        self, tokens: Sequence[Token], idx: int, options: OptionsDict, env: EnvType
    ) -> str:
        result = ""
        token = tokens[idx]
        if self.__current_heading >= token.tag:
            result += "</div>"
        self.__current_heading = token.tag
        result += "<div>"
        return result + self.renderToken(tokens, idx, options, env)


def main():
    source = Path("../../recipes")
    output = Path("../../html")

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


if __name__ == "__main__":
    main()
