from __future__ import annotations

import enum
import importlib.resources
import itertools
import operator
import os
from pathlib import Path
from typing import Iterable, Callable

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


@attrs.frozen
class Heading:
    text: str
    level: int


Line = str | Heading


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
    return _HEADING_TO_RENDER_MAPPING.get(heading)


@attrs.frozen
class Section:
    heading: Heading
    content: list[str]
    children: list[Section] = attrs.field(factory=list)

    @staticmethod
    def from_lines(lines: Iterable[Line]) -> Section:
        heading, *content = lines
        assert isinstance(heading, Heading)
        return Section(
            heading=heading,
            content=content,
        )


def parse_heading(line: str) -> Heading | None:
    if match := re.match(r"(#+)(.*)", line):
        level = len(match.group(1))
        text = match.group(2).strip()
        return Heading(text=text, level=level)
    return None


def parse_line(line: str) -> str | Heading:
    if heading := parse_heading(line):
        return heading
    return line


def parse_sections(recipe: str) -> list[Section]:
    parsed_lines = map(parse_line, recipe.splitlines())

    section_lines = more_itertools.split_before(
        parsed_lines, lambda s: isinstance(s, Heading)
    )

    return list(map(Section.from_lines, section_lines))


def nest_sections(sections: list[Section]) -> Section:
    # Assume sections is non-empty
    assert sections
    # Assume the toplevel exists, and it's the only one
    assert sections[0].heading.level == 1

    # We use copy to avoid modifying the input sections.
    def copy(section: Section) -> Section:
        return attrs.evolve(section)

    toplevel = copy(sections[0])

    stack = [toplevel]
    for section in sections[1:]:
        while stack and section.heading.level <= stack[-1].heading.level:
            stack.pop()
        stack[-1].children.append(copy(section))
        stack.append(section)

    return toplevel


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

        for child in section.children:
            stack.append((child, renderer))

    return "\n".join(rendered_sections)


def render_recipe_from_nested(toplevel: Section) -> str:
    recipe = render_nested_sections(toplevel)

    env = get_env()
    template = env.get_template("recipe.container.html")
    return template.render(recipe=recipe)


def parse_recipe_text(recipe: str) -> Recipe:
    parsed_lines = map(parse_line, recipe.splitlines())

    section_lines = more_itertools.split_before(
        parsed_lines, lambda s: isinstance(s, Heading)
    )

    sections = map(Section.from_lines, section_lines)

    # Now that we have the sections, let's generate the recipe!
    sections = list(sections)

    name = sections[0].heading.text
    description = "\n".join(filter(bool, sections[0].content))

    ingredients = list(filter(bool, sections[1].content))

    steps = [
        "\n".join(lines)
        for lines in more_itertools.split_at(sections[2].content, lambda s: not s)
    ]
    rich.print(steps)

    return Recipe(
        name=name, description=description, ingredients=ingredients, steps=steps
    )


def parse_recipe(source_path) -> Recipe:
    source = source_path.read_text("utf8")
    return parse_recipe_text(source)


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
