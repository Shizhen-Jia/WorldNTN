"""Explicit research assumptions for the first FSPL-only dataset."""
from dataclasses import asdict, dataclass, field
import math
import warnings


def constellation_name(name):
    aliases = {"amazon": "kuiper", "amazon leo": "kuiper", "amazon_kuiper": "kuiper"}
    name = str(name).strip().lower()
    name = aliases.get(name, name)
    if name not in {"starlink", "kuiper", "oneweb"}:
        raise ValueError(f"Unsupported constellation: {name}")
    return name


@dataclass(frozen=True)
class GroundStation:
    lat_deg: float = 39.95697
    lon_deg: float = -105.16033
    height_m: float = 1660.0


def ground_east_of(ground, distance_m=1000.0):
    """Short eastward displacement on WGS84, intended for nearby research UEs."""
    lat = math.radians(ground.lat_deg)
    radius = 6378137.0 / math.sqrt(1 - 6.6943799901413165e-3 * math.sin(lat)**2)
    if abs(math.cos(lat)) < 1e-6:
        raise ValueError("Specify B explicitly near the poles.")
    lon = ground.lon_deg + math.degrees(distance_m / (radius * math.cos(lat)))
    return GroundStation(ground.lat_deg, (lon + 180) % 360 - 180, ground.height_m)


@dataclass(frozen=True)
class RadioConfig:
    frequency_hz: float = 20e9
    bandwidth_hz: float = 250e6
    tx_power_w: float = 10.0
    tx_gain_dbi: float = 30.0
    rx_gain_dbi: float = 30.0
    temperature_k: float = 290.0
    noise_figure_db: float = 6.0
    interference_enabled: bool = True


@dataclass(frozen=True)
class TriggerConfig:
    sinr_min_db: float = 0.0
    middle_start_db: float = 3.0
    highest_start_db: float = 6.0
    window_samples: int = 5
    trigger_points: int = 10
    # Order: below minimum, low, middle, high.
    bin_points: tuple = (5, 3, 2, 1)
    force_on_geometry_loss: bool = False


@dataclass(frozen=True)
class RewardConfig:
    time_scale_s: float = 60.0
    dwell_weight: float = 1.0
    quality_weight: float = 1.0
    outage_weight: float = 2.0
    handover_cost: float = 0.05
    success_score_threshold: float = 2.0


@dataclass(frozen=True)
class SimulationConfig:
    victim: str = "starlink"
    aggressor: str = "amazon"
    ground_a: GroundStation = field(default_factory=GroundStation)
    ground_b: GroundStation = field(default_factory=lambda: ground_east_of(GroundStation()))
    radio: RadioConfig = field(default_factory=RadioConfig)
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    reward: RewardConfig = field(default_factory=RewardConfig)
    min_snr_db: float = 0.0
    min_elevation_deg: float = 25.0
    aggressor_policy: str = "longest_remaining"
    victim_initial_policy: str = "longest_remaining"
    victim_handover_policy: str = "random"
    random_seed: int = 20261005
    # Keep the native CSV grid; never pretend that interpolation is new data.
    start_time_utc: str | None = None
    max_steps: int | None = 600
    allow_partial_catalog: bool = False
    allow_unverified_csv: bool = False
    assume_naive_utc: bool = False
    history_samples: int = 10
    prediction_samples: int = 1
    window_stride: int = 1
    split: str = "train"
    scenario_group_id: str | None = None

    def validate(self):
        if constellation_name(self.victim) == constellation_name(self.aggressor):
            raise ValueError("A and B must use different constellations in this version.")
        for g in (self.ground_a, self.ground_b):
            if not (-90 <= g.lat_deg <= 90 and -180 <= g.lon_deg <= 180 and math.isfinite(g.height_m)):
                raise ValueError("Invalid ground station coordinates.")
        for key, value in asdict(self.radio).items():
            if key == "interference_enabled":
                continue
            if not math.isfinite(value):
                raise ValueError(f"Nonfinite radio setting: {key}")
            if key in {"frequency_hz", "bandwidth_hz", "tx_power_w", "temperature_k"} and value <= 0:
                raise ValueError(f"{key} must be positive.")
        if self.radio.noise_figure_db < 0:
            raise ValueError("Noise figure must be >= 0 dB.")
        t = self.trigger
        if not t.sinr_min_db < t.middle_start_db < t.highest_start_db:
            raise ValueError("SINR bin boundaries must be strictly increasing.")
        for name, value in [("window_samples", t.window_samples), ("trigger_points", t.trigger_points),
                            ("history_samples", self.history_samples), ("prediction_samples", self.prediction_samples),
                            ("window_stride", self.window_stride), *[("bin_points", x) for x in t.bin_points]]:
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer.")
        if len(t.bin_points) != 4 or list(t.bin_points) != sorted(t.bin_points, reverse=True):
            raise ValueError("Four descending bin scores are required.")
        if t.window_samples * t.bin_points[-1] >= t.trigger_points:
            warnings.warn("Even an always-high SINR fills this window enough to trigger handover.")
        if self.min_snr_db != t.sinr_min_db:
            warnings.warn("SNR admission and SINR outage minima differ; no-interference trigger boundary is SINR minimum.")
        if not math.isfinite(self.min_snr_db) or not 0 <= self.min_elevation_deg <= 90:
            raise ValueError("Invalid link admission thresholds.")
        if self.aggressor_policy != "longest_remaining":
            raise ValueError("Only longest_remaining is implemented for B.")
        for policy in (self.victim_initial_policy, self.victim_handover_policy):
            if policy not in {"longest_remaining", "random", "max_snr"}:
                raise ValueError(f"Unknown A policy: {policy}")
        if self.max_steps is not None and (not isinstance(self.max_steps, int) or self.max_steps < 2):
            raise ValueError("max_steps must be None or an integer >= 2.")
        if self.split not in {"train", "val", "test"}:
            raise ValueError("split must be train, val, or test.")
        for value in asdict(self.reward).values():
            if not math.isfinite(value):
                raise ValueError("Nonfinite reward setting.")
        r = self.reward
        if r.time_scale_s <= 0 or min(r.dwell_weight, r.quality_weight, r.outage_weight, r.handover_cost) < 0:
            raise ValueError("Reward scale must be positive and weights/cost nonnegative.")
        if r.outage_weight < r.dwell_weight:
            warnings.warn("Outage penalty is smaller than dwell reward: staying disconnected can earn score.")
        return self
