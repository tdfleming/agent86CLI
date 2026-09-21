"""The release helper scripts in `scripts/`.

Deliberately *not* marked `packaging`: these are fast, pure-function tests and they guard the
one thing a release cannot recover from — shipping a tag whose version disagrees with the
package, or a GitHub Release whose body is the wrong changelog section. They run in the default
suite.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"_scripts_{name}", SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def check_release() -> ModuleType:
    return _load("check_release")


SAMPLE_CHANGELOG = """\
# Changelog

Preamble prose that belongs to no section.

## [Unreleased]

## [1.0.0] - 2026-09-21

The release everyone waited for.

### Added

- A thing.

## [0.9.0] - 2026-09-01

### Fixed

- Another thing.
"""


class TestChangelogSections:
    def test_splits_headings_from_bodies(self, check_release: ModuleType) -> None:
        sections = check_release.changelog_sections(SAMPLE_CHANGELOG)
        assert set(sections) == {"Unreleased", "1.0.0", "0.9.0"}
        assert sections["Unreleased"] == ""
        assert sections["1.0.0"].startswith("The release everyone waited for.")
        assert "Another thing" not in sections["1.0.0"]
        assert sections["0.9.0"].endswith("- Another thing.")

    def test_a_populated_unreleased_section_is_not_empty(self, check_release: ModuleType) -> None:
        text = SAMPLE_CHANGELOG.replace(
            "## [Unreleased]\n", "## [Unreleased]\n\n### Added\n\n- Forgotten work.\n"
        )
        assert check_release.changelog_sections(text)["Unreleased"] != ""


class TestVersionAgreement:
    def test_the_real_tree_agrees_with_itself(self, check_release: ModuleType) -> None:
        assert check_release.package_version() == check_release.pyproject_version()

    def test_normalise_tag_strips_the_v(self, check_release: ModuleType) -> None:
        assert check_release.normalise_tag("v1.0.0") == "1.0.0"
        assert check_release.normalise_tag("1.0.0") == "1.0.0"


class TestMain:
    def test_passes_against_the_current_tree(
        self, check_release: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        version = check_release.pyproject_version()
        assert check_release.main(["--tag", f"v{version}"]) == 0
        assert "ready to publish" in capsys.readouterr().out

    def test_rejects_a_tag_that_does_not_match_pyproject(
        self, check_release: ModuleType, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert check_release.main(["--tag", "v99.99.99"]) == 1
        assert "git tag matches pyproject" in capsys.readouterr().out

    def test_skips_the_tag_check_when_not_a_tag_build(
        self,
        check_release: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.delenv("GITHUB_REF_NAME", raising=False)
        monkeypatch.delenv("GITHUB_REF_TYPE", raising=False)
        assert check_release.main([]) == 0
        assert "skip  tag comparison" in capsys.readouterr().out

    def test_takes_the_tag_from_the_github_environment(
        self, check_release: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_REF_NAME", "v99.99.99")
        monkeypatch.setenv("GITHUB_REF_TYPE", "tag")
        assert check_release.main([]) == 1
