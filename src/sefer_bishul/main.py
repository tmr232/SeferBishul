import importlib.resources
import operator
import os
from pathlib import Path

import typer
import more_itertools
import rich
import attrs
import re

from jinja2 import Environment, PackageLoader, select_autoescape


@attrs.frozen
class Recipe:
    name: str
    description: str
    ingredients: list[str]
    steps: list[str]


def get_env() -> Environment:
    return Environment(
        loader=PackageLoader("sefer_bishul", "templates"),
        autoescape=select_autoescape(),
    )


def render_recipe(recipe: Recipe) -> str:
    env = get_env()

    recipe_template = env.get_template("recipe.html")

    return recipe_template.render(
        title=recipe.name,
        description=recipe.description,
        ingredients=recipe.ingredients,
        steps=recipe.steps,
    )


def parse_h1(line: str) -> str | None:
    if match := re.match(r"#([^#].*)", line):
        return match.group(1).strip()
    return None


def parse_recipe(source_path) -> Recipe:
    source = source_path.read_text("utf8")
    # First, we find all the titles (start with "#") and split by them.
    blocks = list(
        more_itertools.split_before(source.splitlines(), lambda s: s.startswith("#"))
    )

    # First block should be an h1 block with the recipe name

    assert parse_h1(blocks[0][0])

    name = parse_h1(blocks[0][0])
    description = "\n".join(blocks[0][1:])

    # Filter to remove empty lines
    ingredients = [block for block in blocks[1][1:] if block]

    steps = [
        "\n".join(lines)
        for lines in more_itertools.split_at(blocks[2][1:], lambda s: not s.strip())
    ]
    # Filter to remove empty steps
    steps = list(filter(bool, steps))

    recipe = Recipe(
        name=name, description=description, ingredients=ingredients, steps=steps
    )

    return recipe


def copy_static_content(output_dir: Path):
    """
    Assumes the output_dir exists.
    """
    os.makedirs(output_dir / "static", exist_ok=True)

    # Need the joinpath call as this is a namespace package, not a proper one.
    for file in importlib.resources.files("sefer_bishul").joinpath("static").iterdir():
        with importlib.resources.as_file(file) as f:
            data = f.read_bytes()

        (output_dir / "static" / file.name).write_bytes(data)


def render_index(recipes: dict[str, Recipe]) -> str:
    recipe_list = sorted(
        (
            (filename.replace(".md", ".html"), recipe.name)
            for filename, recipe in recipes.items()
        ),
        # The filename is added here for consistency in sorting.
        key=operator.itemgetter(1, 0),
    )

    env = get_env()
    index_template = env.get_template("index.html")
    return index_template.render(recipes=recipe_list)


def main(recipes_path: Path, output_dir: Path):
    recipes = {}
    for root, dirs, files in os.walk(recipes_path):
        for file in files:
            source_path = os.path.join(root, file)
            recipe = parse_recipe(Path(source_path))
            recipes[file] = recipe

    copy_static_content(output_dir)

    for filename, recipe in recipes.items():
        filename = os.path.splitext(filename)[0]
        recipe_html = render_recipe(recipe)
        (output_dir / f"{filename}.html").write_text(recipe_html)

    # Then we generate the index!
    index = render_index(recipes)
    (output_dir / "index.html").write_text(index)


if __name__ == "__main__":
    typer.run(main)
