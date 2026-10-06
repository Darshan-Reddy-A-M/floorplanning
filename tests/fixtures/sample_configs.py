"""Configuration matrix used to measure layout quality.

Pure data (no solver imports). ``mode='auto'`` mirrors what the app does after
"Accept Recommendation" using the current rule-based program; ``'default_custom'``
uses ``testfit.defaults.DEFAULT_ROOMS``. Plot sizes are placeholders until the
real demo plot sizes are confirmed.
"""

from __future__ import annotations

from dataclasses import dataclass

SINGLE = "Single-Family House"
DUPLEX = "Duplex"
RENTAL = "Rental / Multi-Unit Building"


@dataclass(frozen=True)
class SampleConfig:
    id: str
    description: str
    building_type: str = SINGLE
    floors: int = 1
    units_per_floor: int = 1
    site_ft: tuple[float, float] = (40.0, 60.0)  # width, length
    road_access: str = "South"
    entrance_side: str | None = None  # None -> same as road_access (app default)
    parking: str = "No parking"
    setbacks_ft: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # front, rear, left, right
    mode: str = "auto"


SAMPLE_CONFIGS: tuple[SampleConfig, ...] = (
    SampleConfig("custom_default_1f", "App default 7-room custom program, legacy single-floor path",
                 site_ft=(60, 50), mode="default_custom"),
    SampleConfig("sf_1f_30x50_south_nopark", "Small narrow plot, one floor", site_ft=(30, 50)),
    SampleConfig("sf_1f_40x60_south_1car", "One floor, one car, road south", parking="1 car"),
    SampleConfig("sf_1f_40x60_north_1car", "Road north (entrance-selection check)",
                 road_access="North", parking="1 car"),
    SampleConfig("sf_1f_40x60_east_1car", "Road east (entrance-selection check)",
                 road_access="East", parking="1 car"),
    SampleConfig("sf_1f_40x60_west_1car", "Road west", road_access="West", parking="1 car"),
    SampleConfig("sf_2f_40x60_south_1car", "Two floors, one car", floors=2, parking="1 car"),
    SampleConfig("sf_2f_30x50_east_1car", "Two floors, narrow plot, road east",
                 floors=2, site_ft=(30, 50), road_access="East", parking="1 car"),
    SampleConfig("sf_2f_40x60_setbacks_south_1car", "Two floors with setbacks",
                 floors=2, parking="1 car", setbacks_ft=(10, 5, 5, 5)),
    SampleConfig("sf_3f_40x60_south_2car", "Three floors, two cars", floors=3, parking="2 cars"),
    SampleConfig("sf_5f_50x80_south_2car", "Five floors, two cars",
                 floors=5, site_ft=(50, 80), parking="2 cars"),
    SampleConfig("duplex_2f_40x60_south_1car", "Duplex, two floors", building_type=DUPLEX,
                 floors=2, parking="1 car"),
    SampleConfig("duplex_3f_50x80_west_2car", "Duplex, three floors, road west",
                 building_type=DUPLEX, floors=3, site_ft=(50, 80), road_access="West",
                 parking="2 cars"),
    SampleConfig("rental_3f_50x80_2units_south_1car", "Rental, 2 units/floor, 3 floors",
                 building_type=RENTAL, floors=3, units_per_floor=2, site_ft=(50, 80), parking="1 car"),
    SampleConfig("rental_4f_60x80_2units_north_2car", "Rental, 2 units/floor, 4 floors, road north",
                 building_type=RENTAL, floors=4, units_per_floor=2, site_ft=(60, 80),
                 road_access="North", parking="2 cars"),
    SampleConfig("rental_3f_60x80_4units_south_2car", "Rental, 4 units/floor, 3 floors",
                 building_type=RENTAL, floors=3, units_per_floor=4, site_ft=(60, 80), parking="2 cars"),
)
