from __future__ import annotations

import re
from typing import Iterable

import attrs
import more_itertools


@attrs.frozen
class Recipe:
    name: str
    toplevel: Section


@attrs.frozen
class Heading:
    text: str
    level: int


Line = str | Heading


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


def parse_recipe_text(recipe: str) -> Recipe:
    parsed_lines = map(parse_line, recipe.splitlines())

    section_lines = more_itertools.split_before(
        parsed_lines, lambda s: isinstance(s, Heading)
    )

    sections = map(Section.from_lines, section_lines)

    # Now that we have the sections, let's generate the recipe!
    sections = list(sections)

    toplevel = nest_sections(sections)
    return Recipe(toplevel=toplevel, name=toplevel.heading.text)


def parse_recipe(source_path) -> Recipe:
    source = source_path.read_text("utf8")
    return parse_recipe_text(source)
