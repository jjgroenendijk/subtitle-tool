"""Tests for the library page: rendering, pagination, sorting, and the gaps filter."""

from __future__ import annotations

from typing import TYPE_CHECKING

from subtitle_tool.config import save_config
from tests.helpers import build_library, media_config, wait_idle

if TYPE_CHECKING:
    from pathlib import Path

    from fastapi.testclient import TestClient


def configure_media(config_dir: Path, media: Path) -> None:
    save_config(media_config(media), config_dir / "config.toml")


def test_library_gaps_toggle_is_an_alpine_component(
    client: TestClient, config_dir: Path, tmp_path: Path
) -> None:
    media = tmp_path / "media"
    build_library(media)
    save_config(
        media_config(
            media, language={"filter": {"enabled": True, "wanted_languages": ["en", "nl"]}}
        ),
        config_dir / "config.toml",
    )
    client.post("/api/jobs", json={"mode": "real"})
    wait_idle(client)

    page = client.get("/library")
    assert page.status_code == 200
    # Keeps its id (the server-side filter param) plus an Alpine change handler.
    assert 'x-data="libraryGaps"' in page.text
    assert 'id="gaps-only" x-on:change="toggle"' in page.text


def test_library_page_renders_indexed_videos(
    client: TestClient, config_dir: Path, tmp_path: Path
) -> None:
    media = tmp_path / "media"
    build_library(media)
    save_config(
        media_config(
            media, language={"filter": {"enabled": True, "wanted_languages": ["en", "nl"]}}
        ),
        config_dir / "config.toml",
    )

    # Empty before any scan populates the index.
    empty = client.get("/library")
    assert empty.status_code == 200
    assert "No indexed videos yet" in empty.text

    client.post("/api/jobs", json={"mode": "real"})
    wait_idle(client)

    page = client.get("/library")
    assert page.status_code == 200
    assert "Movie (2020).mkv" in page.text
    # Coverage summary and the gaps filter help focus on incomplete videos.
    assert "missing wanted" in page.text
    assert 'id="gaps-only"' in page.text
    # Extra columns are rendered server-side; the picker hides them client-side.
    assert "col-size" in page.text
    assert "col-modified" in page.text
    # The full path is rendered even though the filename shows by default.
    assert str(media / "Movie (2020).mkv") in page.text

    # The missing filter is a server-side query param so it spans every page.
    filtered = client.get("/library?missing=1")
    assert filtered.status_code == 200
    assert "Movie (2020).mkv" in filtered.text

    library = client.get("/api/library").json()
    assert len(library) == 1
    entry = library[0]
    assert entry["path"].endswith("Movie (2020).mkv")
    # The French subtitle is indexed; the wanted en and nl are both missing.
    assert "fr" in entry["languages"]
    assert entry["missing_languages"] == ["en", "nl"]


def test_library_view_is_an_alpine_component(
    client: TestClient, config_dir: Path, tmp_path: Path
) -> None:
    media = tmp_path / "media"
    media.mkdir(parents=True, exist_ok=True)
    (media / "Movie.mkv").write_text("video", encoding="utf-8")
    configure_media(config_dir, media)
    client.post("/api/jobs", json={"mode": "real"})
    wait_idle(client)

    page = client.get("/library")
    assert page.status_code == 200
    # View preferences, path toggle, and quick filter are the libraryView component.
    assert 'x-data="libraryView"' in page.text
    assert 'x-bind:class="tableClass"' in page.text
    assert 'class="quick-filter"' in page.text
    assert 'x-model="filter"' in page.text
    # Column and path toggles delegate to component methods (CSP-safe refs).
    assert 'class="col-toggle" value="size" x-on:change="setColumn"' in page.text
    assert 'class="path-toggle" x-on:change="setPaths"' in page.text
    assert 'x-on:click="reset"' in page.text
    # Rows carry a lowercased name the quick filter matches against client-side.
    assert 'data-name="' in page.text
    assert str(media / "Movie.mkv").lower() in page.text


def test_library_page_paginates(client: TestClient, config_dir: Path, tmp_path: Path) -> None:
    media = tmp_path / "media"
    media.mkdir(parents=True, exist_ok=True)
    for name in ("Alpha", "Bravo", "Charlie"):
        (media / f"{name}.mkv").write_text("video", encoding="utf-8")
    configure_media(config_dir, media)

    client.post("/api/jobs", json={"mode": "real"})
    wait_idle(client)

    # One video per page: page 1 shows Alpha (sorted by path) and links to page 2.
    first = client.get("/library?per_page=1&page=1")
    assert first.status_code == 200
    assert "Page 1 of 3" in first.text
    assert "Alpha.mkv" in first.text
    assert "Charlie.mkv" not in first.text

    last = client.get("/library?per_page=1&page=3")
    assert "Page 3 of 3" in last.text
    assert "Charlie.mkv" in last.text
    assert "Alpha.mkv" not in last.text

    # Out-of-range pages clamp to the valid range rather than erroring.
    clamped = client.get("/library?per_page=1&page=99")
    assert clamped.status_code == 200
    assert "Page 3 of 3" in clamped.text

    # The default single page hides the pagination controls.
    single = client.get("/library")
    assert "Page 1 of 1" not in single.text


def test_library_headers_are_sortable_and_default_to_name(
    client: TestClient, config_dir: Path, tmp_path: Path
) -> None:
    media = tmp_path / "media"
    build_library(media)
    configure_media(config_dir, media)
    client.post("/api/jobs", json={"mode": "real"})
    wait_idle(client)

    page = client.get("/library")
    assert page.status_code == 200
    # Sortable columns are interactive links carrying the sort param.
    assert 'class="col-name sortable"' in page.text
    assert "sort=size" in page.text
    # The default name sort exposes its direction accessibly.
    assert 'class="col-name sortable" aria-sort="ascending"' in page.text


def test_library_sorts_by_query_params(
    client: TestClient, config_dir: Path, tmp_path: Path
) -> None:
    media = tmp_path / "media"
    media.mkdir(parents=True, exist_ok=True)
    # Distinct sizes so a size sort has an unambiguous order, independent of name.
    (media / "Alpha.mkv").write_text("a", encoding="utf-8")
    (media / "Bravo.mkv").write_text("bb" * 50, encoding="utf-8")
    (media / "Charlie.mkv").write_text("c" * 500, encoding="utf-8")
    configure_media(config_dir, media)
    client.post("/api/jobs", json={"mode": "real"})
    wait_idle(client)

    page = client.get("/library?sort=size&dir=desc")
    assert page.status_code == 200
    assert 'aria-sort="descending"' in page.text
    # Largest first: Charlie, then Bravo, then Alpha.
    order = [page.text.index(name) for name in ("Charlie.mkv", "Bravo.mkv", "Alpha.mkv")]
    assert order == sorted(order)


def test_library_missing_filter_stays_clearable(
    client: TestClient, config_dir: Path, tmp_path: Path
) -> None:
    media = tmp_path / "media"
    build_library(media)
    # Wanted matches the only indexed subtitle, so nothing is missing.
    save_config(
        media_config(media, language={"filter": {"enabled": True, "wanted_languages": ["fr"]}}),
        config_dir / "config.toml",
    )

    client.post("/api/jobs", json={"mode": "real"})
    wait_idle(client)

    # No gaps, so the toggle is absent on the default view.
    default = client.get("/library")
    assert default.status_code == 200
    assert 'id="gaps-only"' not in default.text

    # On the active missing filter the toggle still renders (checked) so the user
    # can clear it, even though the filter leaves no rows to show.
    filtered = client.get("/library?missing=1")
    assert filtered.status_code == 200
    assert 'id="gaps-only"' in filtered.text
    assert "Movie (2020).mkv" not in filtered.text


def test_library_missing_filter_clearable_without_wanted(
    client: TestClient, config_dir: Path, tmp_path: Path
) -> None:
    # No wanted languages: the missing filter empties the list, but an active
    # ?missing=1 must still render the toggle so the user can clear it.
    media = tmp_path / "media"
    build_library(media)
    configure_media(config_dir, media)

    client.post("/api/jobs", json={"mode": "real"})
    wait_idle(client)

    # Without wanted languages the toggle is absent on the default view.
    default = client.get("/library")
    assert default.status_code == 200
    assert 'id="gaps-only"' not in default.text

    filtered = client.get("/library?missing=1")
    assert filtered.status_code == 200
    assert 'id="gaps-only"' in filtered.text
    assert "Movie (2020).mkv" not in filtered.text
