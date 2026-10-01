from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import inspect, text

from front_office.domain.schema import DType, Field, Provenance, TableContract
from front_office.domain.tables import ALL_TABLES, KEPT_TABLES, LEAGUE_TABLES, REBUILT_TABLES
from front_office.storage import Database, StorageError, Warehouse
from front_office.storage.schema import build_tables, schema_fingerprint
from front_office.storage.warehouse import records

BOS = 1610612738


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    with Database(tmp_path / "data" / "lab.sqlite") as opened:
        yield opened


def frames(normalized) -> dict[str, pd.DataFrame]:
    """Every rebuilt table: the fixture's league data plus an empty build report."""
    built = {name: frame.copy() for name, frame in normalized.frames.items()}
    for contract in REBUILT_TABLES:
        built.setdefault(contract.name, contract.empty_frame())
    return built


def table_names(database: Database) -> set[str]:
    with database.connect() as connection:
        return set(inspect(connection).get_table_names())


class TestTableGroups:
    def test_every_table_is_either_rebuilt_or_kept(self) -> None:
        rebuilt = {contract.name for contract in REBUILT_TABLES}
        kept = {contract.name for contract in KEPT_TABLES}
        assert not rebuilt & kept
        assert rebuilt | kept == {contract.name for contract in ALL_TABLES}

    def test_the_users_rosters_and_the_history_are_kept(self) -> None:
        kept = {contract.name for contract in KEPT_TABLES}
        assert kept == {"custom_rosters", "roster_players", "fetch_log", "builds"}

    def test_league_tables_are_rebuilt(self) -> None:
        rebuilt = {contract.name for contract in REBUILT_TABLES}
        assert {contract.name for contract in LEAGUE_TABLES} < rebuilt
        assert {"build_issues", "check_results", "raw_snapshots"} < rebuilt


class TestSchema:
    def test_a_new_database_has_the_kept_tables_only(self, database: Database) -> None:
        assert table_names(database) == {c.name for c in KEPT_TABLES} | {"lab_meta"}
        assert database.path.is_file()

    def test_columns_keys_and_nullability_follow_the_contracts(
        self, database: Database, normalized
    ) -> None:
        with database.begin() as connection:
            Warehouse(database).replace(connection, frames(normalized))
        with database.connect() as connection:
            inspector = inspect(connection)
            for contract in ALL_TABLES:
                columns = {
                    column["name"]: column for column in inspector.get_columns(contract.name)
                }
                assert tuple(columns) == contract.column_names, contract.name
                for field in contract.fields:
                    # SQLite reports a primary key column as nullable; skip those.
                    if field.name not in contract.primary_key:
                        assert columns[field.name]["nullable"] == field.nullable, field.name
                key = inspector.get_pk_constraint(contract.name)["constrained_columns"]
                assert tuple(key) == contract.primary_key, contract.name

    def test_declared_indexes_are_created(self, database: Database, normalized) -> None:
        with database.begin() as connection:
            Warehouse(database).replace(connection, frames(normalized))
        with database.connect() as connection:
            inspector = inspect(connection)
            for contract in ALL_TABLES:
                created = {
                    tuple(index["column_names"]) for index in inspector.get_indexes(contract.name)
                }
                assert set(contract.indexes) <= created, contract.name

    def test_logical_types_map_to_sql_types(self) -> None:
        from sqlalchemy import MetaData

        contract = TableContract(
            "every_type",
            "test",
            "One column of each logical type.",
            "One row.",
            (
                Field("id", DType.INTEGER, "Id.", nullable=False, provenance=Provenance.IDENTIFIER),
                Field("ratio", DType.FLOAT, "Ratio."),
                Field("label", DType.STRING, "Label."),
                Field("flag", DType.BOOLEAN, "Flag."),
                Field("day", DType.DATE, "Day."),
                Field("moment", DType.DATETIME, "Moment."),
            ),
            ("id",),
        )
        table = build_tables(MetaData(), [contract], enforce_references=False)["every_type"]
        kinds = {column.name: type(column.type).__name__ for column in table.columns}
        assert kinds == {
            "id": "Integer",
            "ratio": "Float",
            "label": "Text",
            "flag": "Boolean",
            "day": "Date",
            "moment": "DateTime",
        }

    def test_only_kept_tables_enforce_references(self, database: Database, normalized) -> None:
        with database.begin() as connection:
            Warehouse(database).replace(connection, frames(normalized))
        with database.connect() as connection:
            inspector = inspect(connection)
            keys = {
                contract.name: inspector.get_foreign_keys(contract.name) for contract in ALL_TABLES
            }
        with_keys = {name for name, found in keys.items() if found}
        assert with_keys == {"roster_players"}
        (reference,) = keys["roster_players"]
        assert reference["referred_table"] == "custom_rosters"
        assert reference["options"] == {"ondelete": "CASCADE"}

    def test_fingerprint_changes_with_the_shape_of_a_table(self) -> None:
        base = schema_fingerprint(REBUILT_TABLES)
        assert base == schema_fingerprint(REBUILT_TABLES)
        assert len(base) == 12
        assert schema_fingerprint(REBUILT_TABLES[:-1]) != base
        first = REBUILT_TABLES[0]
        renamed = TableContract(
            first.name,
            first.domain,
            "Different words.",
            first.grain,
            first.fields,
            first.primary_key,
        )
        # A description is documentation, not shape.
        assert schema_fingerprint((renamed, *REBUILT_TABLES[1:])) == base


class TestConnections:
    def test_a_failed_transaction_leaves_nothing_behind(self, database: Database) -> None:
        with pytest.raises(RuntimeError), database.begin() as connection:
            connection.execute(text("INSERT INTO lab_meta (key, value) VALUES ('a', 'b')"))
            raise RuntimeError("boom")
        with database.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM lab_meta")).scalar() == 0

    def test_table_creation_rolls_back_too(self, database: Database) -> None:
        """SQLite's driver leaves DDL outside transactions unless told otherwise."""
        with pytest.raises(RuntimeError), database.begin() as connection:
            connection.execute(text("CREATE TABLE scratch (id INTEGER)"))
            raise RuntimeError("boom")
        assert "scratch" not in table_names(database)

    def test_write_ahead_logging_and_foreign_keys_are_on(self, database: Database) -> None:
        with database.connect() as connection:
            assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"
            assert connection.execute(text("PRAGMA foreign_keys")).scalar() == 1

    def test_transaction_control_belongs_to_sqlalchemy_not_the_driver(
        self, database: Database
    ) -> None:
        with database.connect() as connection:
            assert connection.connection.dbapi_connection.isolation_level is None

    def test_reopening_keeps_what_was_stored(self, tmp_path: Path, normalized) -> None:
        path = tmp_path / "lab.sqlite"
        with Database(path) as first, first.begin() as connection:
            Warehouse(first).replace(connection, frames(normalized))
        with Database(path) as second:
            assert Warehouse(second).row_counts()["teams"] == 30
            assert second.is_current

    def test_unknown_table(self, database: Database) -> None:
        with pytest.raises(StorageError, match="no table named 'nope'"):
            database.table("nope")


class TestReplace:
    def test_loads_every_rebuilt_table(self, database: Database, normalized) -> None:
        warehouse = Warehouse(database)
        assert not warehouse.is_built()
        assert warehouse.row_counts() == {}
        built = frames(normalized)
        with database.begin() as connection:
            written = warehouse.replace(connection, built)
        assert warehouse.is_built()
        counts = warehouse.row_counts()
        assert counts == {contract.name: len(built[contract.name]) for contract in REBUILT_TABLES}
        assert written == sum(counts.values())
        assert database.is_current

    def test_what_is_read_back_equals_what_was_written(
        self, database: Database, normalized
    ) -> None:
        built = frames(normalized)
        warehouse = Warehouse(database)
        with database.begin() as connection:
            warehouse.replace(connection, built)
        for contract in LEAGUE_TABLES:
            stored = warehouse.read(contract.name, order_by=contract.primary_key)
            expected = (
                built[contract.name].sort_values(list(contract.primary_key)).reset_index(drop=True)
            )
            pd.testing.assert_frame_equal(stored, expected, check_exact=False, obj=contract.name)

    def test_a_second_build_replaces_the_first(self, database: Database, normalized) -> None:
        warehouse = Warehouse(database)
        built = frames(normalized)
        with database.begin() as connection:
            warehouse.replace(connection, built)
        smaller = dict(built)
        smaller["team_games"] = built["team_games"].head(10)
        with database.begin() as connection:
            warehouse.replace(connection, smaller)
        assert warehouse.row_counts()["team_games"] == 10
        assert warehouse.row_counts()["teams"] == 30

    def test_a_failed_build_leaves_the_previous_one_intact(
        self, database: Database, normalized
    ) -> None:
        warehouse = Warehouse(database)
        built = frames(normalized)
        with database.begin() as connection:
            warehouse.replace(connection, built)
        before = warehouse.row_counts()
        with pytest.raises(RuntimeError), database.begin() as connection:
            warehouse.replace(connection, {**built, "teams": built["teams"].head(1)})
            raise RuntimeError("the build failed after writing")
        assert warehouse.row_counts() == before
        assert len(warehouse.read("teams")) == 30

    def test_a_frame_that_breaks_its_contract_is_refused_before_anything_changes(
        self, database: Database, normalized
    ) -> None:
        from front_office.domain.schema import ContractViolationError

        warehouse = Warehouse(database)
        built = frames(normalized)
        with database.begin() as connection:
            warehouse.replace(connection, built)
        broken = dict(built)
        broken["teams"] = built["teams"].assign(conference="North")
        with pytest.raises(ContractViolationError), database.begin() as connection:
            warehouse.replace(connection, broken)
        assert set(warehouse.read("teams")["conference"]) == {"East", "West"}

    def test_every_rebuilt_table_must_be_supplied(self, database: Database, normalized) -> None:
        built = frames(normalized)
        del built["teams"]
        built["surprise"] = built["players"]
        with pytest.raises(StorageError, match=r"missing \['teams'\], extra \['surprise'\]"):
            with database.begin() as connection:
                Warehouse(database).replace(connection, built)

    def test_a_rebuild_does_not_touch_kept_tables(self, database: Database, normalized) -> None:
        from front_office.storage import RosterRepository

        rosters = RosterRepository(database)
        roster_id = rosters.create("Keep me", stats_season="2025-26", payroll_season="2026-27")
        rosters.set_player(roster_id, 1628369, slot="SF")
        for _ in range(2):
            with database.begin() as connection:
                Warehouse(database).replace(connection, frames(normalized))
        assert rosters.get(roster_id)["name"] == "Keep me"
        assert rosters.players(roster_id)["player_id"].tolist() == [1628369]

    def test_a_reader_sees_the_old_build_until_the_new_one_commits(
        self, tmp_path: Path, normalized
    ) -> None:
        path = tmp_path / "lab.sqlite"
        built = frames(normalized)
        with Database(path) as writer, Database(path) as reader:
            with writer.begin() as connection:
                Warehouse(writer).replace(connection, built)
            with reader.connect() as reading:
                reading.begin()
                count = text("SELECT count(*) FROM team_games")
                before = reading.execute(count).scalar()
                with writer.begin() as connection:
                    Warehouse(writer).replace(
                        connection, {**built, "team_games": built["team_games"].head(4)}
                    )
                assert reading.execute(count).scalar() == before
                reading.rollback()
                assert reading.execute(count).scalar() == 4


class TestRead:
    @pytest.fixture
    def warehouse(self, database: Database, normalized) -> Warehouse:
        warehouse = Warehouse(database)
        with database.begin() as connection:
            warehouse.replace(connection, frames(normalized))
        return warehouse

    def test_frames_come_back_with_canonical_types(self, warehouse: Warehouse) -> None:
        games = warehouse.read("team_games", {"season": "2025-26", "season_type": "playin"})
        assert len(games) == 12
        assert str(games["game_date"].dtype) == "datetime64[ns]"
        assert str(games["is_home"].dtype) == "bool"
        assert str(games["won"].dtype) == "boolean"
        assert str(games["team_id"].dtype) == "int64"
        assert games["game_id"].str.startswith("005").all()

    def test_equality_and_membership_filters(self, warehouse: Warehouse) -> None:
        one = warehouse.read("team_seasons", {"season": "2025-26", "team_id": BOS})
        assert len(one) == 1 and one.iloc[0]["team_name"] == "Boston Celtics"
        two = warehouse.read("team_seasons", {"season": ["1996-97", "2025-26"], "team_id": BOS})
        assert sorted(two["season"]) == ["1996-97", "2025-26"]
        none = warehouse.read("team_seasons", {"season": []})
        assert len(none) == 0

    def test_null_filter_matches_nulls(self, warehouse: Warehouse) -> None:
        retired = warehouse.read("players", {"current_team_id": None})
        assert len(retired) > 0
        assert retired["current_team_id"].isna().all()
        assert not retired["is_active"].any()

    def test_numpy_values_are_accepted_as_filters(self, warehouse: Warehouse) -> None:
        team_id = warehouse.read("teams")["team_id"].iloc[0]
        assert len(warehouse.read("team_seasons", {"team_id": team_id})) == 3
        ids = warehouse.read("teams")["team_id"].head(2)
        assert len(warehouse.read("teams", {"team_id": list(ids)})) == 2

    def test_ordering(self, warehouse: Warehouse) -> None:
        ordered = warehouse.read(
            "team_seasons", {"season": "2025-26"}, order_by=["wins", "team_id"]
        )
        assert ordered["wins"].is_monotonic_increasing

    def test_an_empty_result_keeps_the_contract_columns(self, warehouse: Warehouse) -> None:
        empty = warehouse.read("team_seasons", {"season": "1950-51"})
        assert len(empty) == 0
        assert str(empty["wins"].dtype) == "int64"

    def test_an_unknown_column_is_an_error(self, warehouse: Warehouse) -> None:
        with pytest.raises(StorageError, match="has no column 'sesaon'"):
            warehouse.read("team_seasons", {"sesaon": "2025-26"})

    def test_an_unknown_table_is_an_error(self, warehouse: Warehouse) -> None:
        with pytest.raises(KeyError, match="no table contract named"):
            warehouse.read("nope")

    def test_reading_before_any_build_explains_what_to_do(self, database: Database) -> None:
        with pytest.raises(StorageError, match="has not been built; run: fol build"):
            Warehouse(database).read("teams")

    def test_accented_names_round_trip(self, warehouse: Warehouse) -> None:
        names = set(warehouse.read("player_seasons", {"season": "2025-26"})["player_name"])
        assert "Nikola Vučević" in names


class TestRecords:
    def test_values_become_plain_python_and_missing_becomes_none(self) -> None:
        frame = pd.DataFrame(
            {
                "whole": pd.array([7, None], dtype="Int64"),
                "required": [1, 2],
                "ratio": [1.5, float("nan")],
                "label": pd.Series(["a", None], dtype="str"),
                "flag": pd.array([True, None], dtype="boolean"),
                "day": pd.to_datetime(["2025-10-21", None]).astype("datetime64[ns]"),
            }
        )
        first, second = records(frame)
        assert {key: type(value).__name__ for key, value in first.items()} == {
            "whole": "int",
            "required": "int",
            "ratio": "float",
            "label": "str",
            "flag": "bool",
            "day": "Timestamp",
        }
        assert [second[key] for key in ("whole", "ratio", "label", "flag", "day")] == [None] * 5
        assert second["required"] == 2

    def test_an_empty_frame_gives_no_records(self) -> None:
        assert records(pd.DataFrame({"a": pd.Series(dtype="int64")})) == []
