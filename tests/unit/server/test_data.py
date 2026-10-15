"""The lab's data through the API (C4): read from the services, formatted, never computed.

Each figure the API sends is compared with what the service returns for it, as the page
tests compare what a page shows.
"""

from __future__ import annotations

import math
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from front_office.config import Settings
from front_office.server.app import create_app
from front_office.services import Lab
from tests.helpers import BOS, NYK, TATUM
from tests.unit.server.conftest import FAST, SECRET, sign_in


@pytest.fixture
def lab_client(built_lab: Settings) -> Iterator[tuple[TestClient, dict, Settings]]:
    """The API on a private copy of the fixture build, and a signed-in user."""
    with TestClient(create_app(built_lab, api=FAST, secret=SECRET)) as client:
        yield client, sign_in(client), built_lab


def _same(sent: float | None, computed: object) -> bool:
    """A figure as sent against the service's: missing is null, never 0."""
    if computed is None or (isinstance(computed, float) and math.isnan(computed)):
        return sent is None
    return sent is not None and math.isclose(sent, float(computed))  # type: ignore[arg-type]


def test_what_the_lab_holds(lab_client) -> None:
    client, headers, settings = lab_client
    body = client.get("/lab", headers=headers).json()
    with Lab(settings) as lab:
        held = lab.status()
    assert body["built"] is True and body["current"] is True
    assert body["build"]["build_id"] == held.build_id
    assert body["team_seasons"] == list(held.team_seasons)
    assert body["player_seasons"] == list(held.player_seasons)
    assert body["cap_seasons"] == list(held.cap_seasons)


def test_a_lab_never_built_says_so_and_makes_nothing(
    client: TestClient, settings: Settings
) -> None:
    headers = sign_in(client)
    body = client.get("/lab", headers=headers).json()
    assert body["built"] is False and body["team_seasons"] == []
    assert body["cap_seasons"]  # the season rules are configuration, there without a build
    for path in ("/seasons/2025-26/teams", "/teams/1", "/seasons/2025-26/players", "/players/1"):
        response = client.get(path, headers=headers)
        assert response.status_code == 503, path
        assert response.json() == {"detail": "No data has been built yet. Run: fol refresh"}
    assert not settings.database_path.exists()


class TestTeams:
    def test_a_seasons_teams_as_the_service_computes_them(self, lab_client) -> None:
        client, headers, settings = lab_client
        with Lab(settings) as lab:
            season = lab.status().team_seasons[0]
            table = lab.teams.table(season)
        body = client.get(f"/seasons/{season}/teams", headers=headers).json()
        assert body["season"] == season
        assert [team["team_id"] for team in body["teams"]] == [int(i) for i in table.teams.index]
        sent = next(team for team in body["teams"] if team["team_id"] == BOS)
        for key in table.metrics.keys:
            assert _same(sent["figures"][key], table.teams.at[BOS, key]), key
            assert _same(body["league_average"][key], table.league[key]), key
        assert sent["ranks"]["net_rating"] == int(table.ranks.at[BOS, "net_rating"])

    def test_every_figure_says_what_it_is(self, lab_client) -> None:
        client, headers, settings = lab_client
        with Lab(settings) as lab:
            season = lab.status().team_seasons[0]
        metrics = client.get(f"/seasons/{season}/teams", headers=headers).json()["metrics"]
        assert {metric["provenance"] for metric in metrics} <= {"measured", "derived"}
        net = next(metric for metric in metrics if metric["key"] == "net_rating")
        # A whole regular season carries the league's published ratings, not estimates.
        assert net["estimated"] is False
        assert net["higher_is_better"] is True

    def test_a_season_the_lab_does_not_hold(self, lab_client) -> None:
        client, headers, _ = lab_client
        response = client.get("/seasons/1950-51/teams", headers=headers)
        assert response.status_code == 404
        assert "no team statistics for 1950-51" in response.json()["detail"]

    @pytest.mark.parametrize("season", ["2025", "2025-2026", "26-27", "2025-27"])
    def test_a_season_written_wrongly(self, lab_client, season: str) -> None:
        client, headers, _ = lab_client
        assert client.get(f"/seasons/{season}/teams", headers=headers).status_code == 422

    def test_a_franchise_and_its_seasons(self, lab_client) -> None:
        client, headers, settings = lab_client
        with Lab(settings) as lab:
            profile = lab.teams.profile(NYK)
        body = client.get(f"/teams/{NYK}", headers=headers).json()
        assert body["full_name"] == profile.team["full_name"]
        assert [row["season"] for row in body["seasons"]] == list(profile.seasons["season"])
        first, computed = body["seasons"][0], profile.seasons.iloc[0]
        assert _same(first["figures"]["net_rating"], computed["net_rating"])
        assert first["rating_ranks"]["net_rating"] == int(computed["net_rating_rank"])

    def test_a_team_the_lab_does_not_hold(self, lab_client) -> None:
        client, headers, _ = lab_client
        assert client.get("/teams/99", headers=headers).status_code == 404


class TestPlayers:
    def test_qualified_players_by_default_as_the_service_computes_them(self, lab_client) -> None:
        client, headers, settings = lab_client
        with Lab(settings) as lab:
            season = lab.status().player_seasons[0]
            table = lab.players.table(season)
        body = client.get(f"/seasons/{season}/players?limit=500", headers=headers).json()
        qualified = table.players[table.players["is_qualified"]]
        assert body["matched"] == len(qualified)
        assert [row["player_id"] for row in body["players"]] == [int(i) for i in qualified.index]
        assert body["qualification"]["described"] == table.qualification.describe()
        chosen = int(qualified.index[0])
        sent = next(row for row in body["players"] if row["player_id"] == chosen)
        for key in table.metrics.keys:
            assert _same(sent["figures"][key], table.players.at[chosen, key]), key

    def test_no_salary_is_served(self, lab_client) -> None:
        client, headers, settings = lab_client
        with Lab(settings) as lab:
            season = lab.status().player_seasons[0]
        response = client.get(f"/seasons/{season}/players?qualified_only=false", headers=headers)
        assert "salary" not in response.text
        assert "salary" not in client.get(f"/players/{TATUM}", headers=headers).text

    def test_one_team_sorted_by_a_figure(self, lab_client) -> None:
        client, headers, settings = lab_client
        with Lab(settings) as lab:
            season = lab.status().player_seasons[0]
        query = f"team_id={BOS}&qualified_only=false&sort=pts_per_game"
        rows = client.get(f"/seasons/{season}/players?{query}", headers=headers).json()["players"]
        assert rows and all(row["team_id"] == BOS for row in rows)
        points = [row["figures"]["pts_per_game"] for row in rows]
        assert points == sorted(points, reverse=True)

    def test_paging(self, lab_client) -> None:
        client, headers, settings = lab_client
        with Lab(settings) as lab:
            season = lab.status().player_seasons[0]
        path = f"/seasons/{season}/players?qualified_only=false"
        everyone = client.get(f"{path}&limit=500", headers=headers).json()["players"]
        second = client.get(f"{path}&limit=2&offset=2", headers=headers).json()
        assert second["players"] == everyone[2:4]
        assert second["matched"] == len(everyone)

    @pytest.mark.parametrize(
        "query", ["sort=salary", "limit=0", "limit=501", "offset=-1", "team_id=0"]
    )
    def test_a_query_out_of_bounds(self, lab_client, query: str) -> None:
        client, headers, settings = lab_client
        with Lab(settings) as lab:
            season = lab.status().player_seasons[0]
        response = client.get(f"/seasons/{season}/players?{query}", headers=headers)
        assert response.status_code == 422

    def test_a_player_with_the_value_models_estimates_marked_modeled(self, lab_client) -> None:
        client, headers, settings = lab_client
        with Lab(settings) as lab:
            profile = lab.players.profile(TATUM)
            model = lab.value.model()
        body = client.get(f"/players/{TATUM}", headers=headers).json()
        assert body["full_name"] == profile.player["full_name"]
        assert len(body["seasons"]) == len(profile.seasons)
        assert len(body["value"]) == len(profile.value)
        provenance = {metric["key"]: metric["provenance"] for metric in body["metrics"]}
        assert provenance["impact"] == "modeled"
        assert provenance["projected_impact"] == "modeled"
        assert provenance["pts_per_game"] in ("measured", "derived")
        if model is None:
            assert body["value_model"] is None
        else:
            assert body["value_model"]["revision"] == model.revision
            assert body["value_model"]["rmse_minutes_played"] == round(model.validation.net.rmse, 2)
            assert "no tested interval" in body["value_model"]["note"]

    def test_a_player_the_lab_does_not_hold(self, lab_client) -> None:
        client, headers, _ = lab_client
        assert client.get("/players/1", headers=headers).status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/lab",
        "/seasons/2025-26/teams",
        f"/teams/{BOS}",
        "/seasons/2025-26/players",
        f"/players/{TATUM}",
    ],
)
def test_every_data_endpoint_needs_a_token(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 401
