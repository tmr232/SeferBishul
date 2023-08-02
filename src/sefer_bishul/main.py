from __future__ import annotations

import importlib.resources
import operator
import os
from pathlib import Path
from typing import Callable

import attrs
import more_itertools
import rich
import typer
from jinja2 import Environment, PackageLoader, select_autoescape

from sefer_bishul.parser import Heading, Recipe, Section, parse_recipe


def get_env() -> Environment:
    return Environment(
        loader=PackageLoader("sefer_bishul", "templates"),
        autoescape=select_autoescape(),
    )


def render_toplevel(section: Section) -> str:
    env = get_env()
    template = env.get_template("toplevel.partial.html")
    return template.render(
        heading=section.heading,
        # Remove empty lines
        description="\n".join(filter(bool, section.content)),
    )


def render_ingredients(section: Section) -> str:
    env = get_env()
    template = env.get_template("ingredients.partial.html")
    return template.render(
        heading=section.heading,
        # Remove empty lines
        ingredients=list(filter(bool, section.content)),
    )


def render_prep(section: Section) -> str:
    env = get_env()
    template = env.get_template("prep.partial.html")
    return template.render(
        heading=section.heading,
        # Merge blocks
        steps=[
            "\n".join(lines)
            for lines in more_itertools.split_at(section.content, lambda s: not s)
        ],
    )


_RENDER_MAPPING = {
    render_ingredients: ("חומרים",),
    render_prep: (
        "הוראות",
        "הוראות הכנה",
    ),
}

_HEADING_TO_RENDER_MAPPING = {
    value: key for key, values in _RENDER_MAPPING.items() for value in values
}


def heading_to_renderer(heading: Heading) -> Callable[[Section], str] | None:
    if heading.level != 2:
        # Only the second level of heading is interesting here.
        return None
    return _HEADING_TO_RENDER_MAPPING.get(heading.text)


def render_nested_sections(toplevel: Section) -> str:
    """
    The idea is that as we traverse the section tree,
    special sections (with their name & level in the heading mapping)
    get relevant CSS classes added to their elements, for formatting!

    And possible additional rendering features.
    """
    rendered_sections = []

    stack = [(toplevel, render_toplevel)]
    while stack:
        section, renderer = stack.pop()
        renderer = heading_to_renderer(section.heading) or renderer

        # TODO: Maybe extract to generator?
        rendered_sections.append(renderer(section))

        # Reverse insertion order as pop-order is reversed.
        for child in reversed(section.children):
            stack.append((child, renderer))

    return "\n".join(rendered_sections)


def render_recipe_from_nested(toplevel: Section) -> str:
    recipe = render_nested_sections(toplevel)

    env = get_env()
    template = env.get_template("recipe.container.html")
    return template.render(recipe=recipe)


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


@attrs.frozen
class Category:
    name: str | None
    children: list[Category]
    recipes: dict[Path, Recipe]

    def __iter__(self):
        yield 1, self
        for child in self.children:
            for level, category in child:
                yield level + 1, category


def load_category(root: Path) -> tuple[Category, dict[Path, Recipe]]:
    recipes: dict[Path, Recipe] = {}
    children = []
    index = {}
    for entry in os.listdir(root):
        path = root / entry
        if os.path.isfile(path):
            recipe = parse_recipe(path)
            recipes[path.relative_to(root).with_suffix("")] = recipe
            index[path] = recipe
        elif os.path.isdir(path):
            category, cat_index = load_category(path)
            children.append(category)
            index.update(cat_index)
        else:
            raise RuntimeError(f"Unexpected entry: {path}")

    return Category(name=root.name, children=children, recipes=recipes), index


def load_recipes(recipes_path: Path) -> tuple[Category, dict[Path, Recipe]]:
    root, index = load_category(recipes_path)
    return attrs.evolve(root, name=None), index


def render_categories(root_category: Category) -> str:
    env = get_env()
    index_template = env.get_template("index.html")
    return index_template.render(categories=root_category)


def main(recipes_path: Path, output_dir: Path):
    copy_static_content(output_dir)

    root_category, recipe_index = load_recipes(recipes_path)

    for path, recipe in recipe_index.items():
        new_path = output_dir / path.relative_to(recipes_path)
        new_path = new_path.with_suffix(".html")
        os.makedirs(new_path.parent, exist_ok=True)

        recipe_html = render_recipe_from_nested(recipe.toplevel)
        new_path.write_text(recipe_html)

    # Then we generate the index!
    index = render_categories(root_category)
    (output_dir / "index.html").write_text(index)


if __name__ == "__main__":
    typer.run(main)
