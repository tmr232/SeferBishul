import nox
from nox import Session

SOURCE_LOCATIONS = ("src", "tests", "noxfile.py")

nox.options.sessions = ["format", "lint", "test"]


@nox.session(python=False)
def format(session: Session) -> None:
    session.run("ruff", "check", "--fix-only", "--exit-zero", *SOURCE_LOCATIONS)
    session.run("ruff", "format", *SOURCE_LOCATIONS)
    session.run("bun", "run", "--bun", "format")


@nox.session(python=False)
def lint(session: Session) -> None:
    session.run("ruff", "check", *SOURCE_LOCATIONS)
    session.run("ruff", "format", "--check", *SOURCE_LOCATIONS)
    session.run("mypy", *SOURCE_LOCATIONS)
    session.run("bun", "run", "--bun", "format:check")
    session.run("bun", "run", "--bun", "lint")


@nox.session(python=False)
def test(session: Session) -> None:
    session.run("pytest", *session.posargs)
    session.run("bun", "run", "--bun", "test")


@nox.session(python=False)
def build(session: Session) -> None:
    session.run("build-book", "recipes", "images", "public")
