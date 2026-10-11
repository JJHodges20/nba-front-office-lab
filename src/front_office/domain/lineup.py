"""Where a saved roster puts each player: who starts, and at which position.

One rule for every save - the Roster Optimizer's, a proposal's and the Scenario
Simulator's. The starters come from the :data:`ROTATION` who play the most, chosen and
placed so that as many as can play a position they are listed at - a guard at point or
shooting guard, a forward at either forward spot, a center at center - and, of the lineups
that manage that equally, the one that plays the most minutes. Everyone else is on the
bench. The Team Builder can move anyone. At the A5 review the user asked that players keep
their own positions as far as possible: the rule before had started the five with the most
minutes, and five guards had started, one of them at center.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations, permutations

from front_office.domain.tables.rosters import ROSTER_SLOTS, STARTING_SLOTS

BENCH = ROSTER_SLOTS[-1]
ROTATION = 9
"""The players the starters are chosen from: the nine who play the most, a rotation's worth."""
SLOT_POSITION = {"PG": "G", "SG": "G", "SF": "F", "PF": "F", "C": "C"}
"""The listed position - guard, forward, center - each starting slot is for."""
GROUP_POSITION = {"Guard": "G", "Forward": "F", "Center": "C"}


@dataclass(frozen=True, slots=True)
class LineupPlayer:
    player_id: int
    positions: str
    """The positions the player is listed at, as the league writes them: G, F-C, C..."""
    share: float
    """The player's projected share of the season's minutes."""


def starting_slots(players: Sequence[LineupPlayer]) -> dict[int, str]:
    """Every player's slot: a starting position, or the bench."""
    ordered = sorted(players, key=lambda player: -player.share)
    rotation = ordered[:ROTATION]
    size = min(len(STARTING_SLOTS), len(rotation))
    best: tuple[tuple[int, float], dict[int, str]] | None = None
    # Every choice of starters from the rotation, in every arrangement over the five
    # positions: 15,120 at most, and the first of equals wins, so the result is fixed.
    for group in combinations(rotation, size):
        played = round(sum(player.share for player in group), 9)
        for placement in permutations(STARTING_SLOTS, size):
            fitting = sum(
                SLOT_POSITION[slot] in player.positions.upper()
                for slot, player in zip(placement, group, strict=True)
            )
            if best is None or (fitting, played) > best[0]:
                best = (
                    (fitting, played),
                    {player.player_id: slot for slot, player in zip(placement, group, strict=True)},
                )
    starters = {} if best is None else best[1]
    return {player.player_id: starters.get(player.player_id, BENCH) for player in ordered}
