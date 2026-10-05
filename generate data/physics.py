"""WGS84 geometry and an identical, direction-independent FSPL radio budget."""
from dataclasses import dataclass
import numpy as np

C_MPS = 299792458.0
K_B = 1.380649e-23


def ground_ecef(ground):
    lat, lon = np.deg2rad([ground.lat_deg, ground.lon_deg])
    e2 = 6.6943799901413165e-3
    n = 6378137.0 / np.sqrt(1 - e2 * np.sin(lat)**2)
    return np.array([(n + ground.height_m) * np.cos(lat) * np.cos(lon),
                     (n + ground.height_m) * np.cos(lat) * np.sin(lon),
                     (n * (1 - e2) + ground.height_m) * np.sin(lat)])


def enu_rotation(ground):
    p, l = np.deg2rad([ground.lat_deg, ground.lon_deg])
    return np.array([[-np.sin(l), np.cos(l), 0],
                     [-np.sin(p)*np.cos(l), -np.sin(p)*np.sin(l), np.cos(p)],
                     [np.cos(p)*np.cos(l), np.cos(p)*np.sin(l), np.sin(p)]])


def fspl_db(range_m, frequency_hz):
    distances = np.asarray(range_m, dtype=float)
    if frequency_hz <= 0 or np.any(distances <= 0):
        raise ValueError("FSPL requires positive distance and frequency.")
    return 20 * np.log10(4 * np.pi * distances * frequency_hz / C_MPS)


def noise_power_w(radio):
    return K_B * radio.temperature_k * radio.bandwidth_hz * 10 ** (radio.noise_figure_db / 10)


def power_w(range_m, radio):
    budget_dbw = 10*np.log10(radio.tx_power_w) + radio.tx_gain_dbi + radio.rx_gain_dbi
    return 10 ** ((budget_dbw - fspl_db(range_m, radio.frequency_hz)) / 10)


def ratios_db(signal_w, interference_w, noise_w):
    """Zero signal/interference has undefined dB; return NaN with explicit masks upstream."""
    s, i = np.broadcast_arrays(np.asarray(signal_w, float), np.asarray(interference_w, float))
    if noise_w <= 0 or np.any(s < 0) or np.any(i < 0):
        raise ValueError("Noise must be positive; signal/interference nonnegative.")
    with np.errstate(divide="ignore", invalid="ignore"):
        snr = np.where(s > 0, 10*np.log10(s/noise_w), np.nan)
        inr = np.where(i > 0, 10*np.log10(i/noise_w), np.nan)
        sinr = np.where(s > 0, 10*np.log10(s/(i+noise_w)), np.nan)
    return sinr, snr, inr


@dataclass
class LinkGeometry:
    range_m: np.ndarray
    azimuth_deg: np.ndarray
    elevation_deg: np.ndarray
    los_enu: np.ndarray
    power_w: np.ndarray
    snr_db: np.ndarray
    above_horizon: np.ndarray


def link_geometry(positions, valid, ground, radio):
    relative = np.asarray(positions, float) - ground_ecef(ground)
    enu = relative @ enu_rotation(ground).T
    distances = np.linalg.norm(enu, axis=-1)
    valid = valid & np.isfinite(distances) & (distances > 0)
    safe_distance = np.where(valid, distances, np.nan)
    unit = enu / safe_distance[..., None]
    elevation = np.rad2deg(np.arctan2(enu[..., 2], np.hypot(enu[..., 0], enu[..., 1])))
    azimuth = np.rad2deg(np.arctan2(enu[..., 0], enu[..., 1])) % 360
    received = np.where(valid, power_w(safe_distance, radio), 0.0)
    with np.errstate(divide="ignore"):
        snr = np.where(received > 0, 10*np.log10(received/noise_power_w(radio)), np.nan)
    return LinkGeometry(safe_distance, azimuth, elevation, unit, received, snr,
                        valid & (elevation > 0))
