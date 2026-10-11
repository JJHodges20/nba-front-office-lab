"""Who starts on a saved roster, and where: players keep their own positions as far as the
roster allows (the user's wish at the A5 review), and of the lineups that manage that, the
one with the most projected impact starts (at the A6 review)."""

from __future__ import annotations

from front_office.domain.lineup import ROTATION, LineupPlayer, starting_slots


def player(
    player_id: int, positions: str, share: float, impact: float | None = None
) -> LineupPlayer:
    return LineupPlayer(player_id, positions, share, impact)


def test_five_guards_with_the_most_minutes_no_longer_start_at_every_position() -> None:
    """The case the user saw: the five with the most minutes were guards, and one started
    at center."""
    roster = [
        player(1, "G", 0.64),
        player(2, "G", 0.58),
        player(3, "G", 0.56),
        player(4, "G", 0.55),
        player(5, "G", 0.51),
        player(6, "C", 0.48),
        player(7, "F", 0.30),
        player(8, "F-C", 0.20),
        player(9, "G", 0.10),
        player(10, "F", 0.05),
    ]
    slots = starting_slots(roster)
    starters = {player_id: slot for player_id, slot in slots.items() if slot != "BENCH"}
    assert (starters[1], starters[2], starters[6]) == ("PG", "SG", "C")
    assert {starters[7], starters[8]} == {"SF", "PF"}
    assert all(slots[player_id] == "BENCH" for player_id in (3, 4, 5, 9, 10))


def test_two_stars_who_play_a_little_less_now_start() -> None:
    """The case the user saw at A6, Option B of the browser pass: a guard and a forward-center
    with the roster's best projections came off the bench for players projected to play
    more. Now the lineup that fits with the most projected impact starts."""
    roster = [
        player(1, "G-F", 0.64, 2.6),
        player(2, "G-F", 0.58, 2.5),
        player(3, "G", 0.56, 3.0),
        player(4, "G", 0.55, 2.2),
        player(5, "G", 0.51, 7.4),
        player(6, "C", 0.48, 2.7),
        player(7, "F-C", 0.46, 7.8),
        player(8, "F", 0.39, 2.2),
        player(9, "C", 0.39, 3.5),
        player(10, "G", 0.29, 2.6),
    ]
    slots = starting_slots(roster)
    starters = {player_id: slot for player_id, slot in slots.items() if slot != "BENCH"}
    assert set(starters) == {1, 3, 5, 7, 9}
    assert {starters[3], starters[5]} == {"PG", "SG"}, "the guards with the most impact"
    assert (starters[1], starters[7], starters[9]) == ("SF", "PF", "C")


def test_a_player_without_a_projection_starts_only_where_no_one_else_can() -> None:
    roster = [
        player(1, "G", 0.60, -1.0),
        player(2, "G", 0.58, -2.0),
        player(3, "F", 0.55, -1.5),
        player(4, "F", 0.50, -0.5),
        player(5, "C", 0.45, -3.0),
        player(6, "C", 0.44),
    ]
    slots = starting_slots(roster)
    assert slots[5] == "C" and slots[6] == "BENCH", "a known center below average still starts"


def test_of_lineups_that_fit_and_project_alike_the_one_that_plays_most_starts() -> None:
    roster = [
        player(1, "G", 0.60),
        player(2, "G-F", 0.59),
        player(3, "F", 0.58),
        player(4, "F-C", 0.57),
        player(5, "C", 0.30),
        player(6, "F", 0.20),
        player(7, "G", 0.10),
    ]
    slots = starting_slots(roster)
    assert {pid for pid, slot in slots.items() if slot != "BENCH"} == {1, 2, 3, 4, 5}
    assert slots[5] == "C", "the only center is at center"
    assert slots[1] in ("PG", "SG") and slots[2] in ("PG", "SG", "SF", "PF")


def test_a_roster_with_no_center_still_fills_center() -> None:
    roster = [player(n, "G" if n < 4 else "F", 0.6 - n / 100) for n in range(1, 9)]
    slots = starting_slots(roster)
    assert sorted(slot for slot in slots.values() if slot != "BENCH") == [
        "C",
        "PF",
        "PG",
        "SF",
        "SG",
    ]


def test_starters_come_from_the_rotation() -> None:
    """A center who barely plays does not start ahead of the rotation."""
    rotation = [player(n, "G" if n % 2 else "F", 0.7 - n / 100) for n in range(1, ROTATION + 1)]
    seldom = player(99, "C", 0.01)
    slots = starting_slots([*rotation, seldom])
    assert slots[99] == "BENCH"


def test_a_short_roster_starts_everyone_it_has() -> None:
    assert starting_slots([player(1, "C", 0.5), player(2, "G", 0.4)]) == {1: "C", 2: "PG"}
    assert starting_slots([]) == {}
