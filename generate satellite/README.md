# Satellite CSV generation

按原 `8Sat8Gd/starlink_tracker.ipynb`、`oneweb_tracker_no_generation.ipynb` 的观测点、ENU 坐标和速度定义实现；借鉴 `dtc_d2d_ntn_all_constellations` 的本地 GP 缓存和来源记录。原文件没有修改。

## 文件与运行顺序

| Notebook | 用途 |
|---|---|
| `download_tle.ipynb` | 抓取三个星座，按 UTC 时间保存 TLE、OMM JSON 和来源 manifest；固定公共时间轴 |
| `starlink_real_tracker.ipynb` | 真实 Starlink，排除 DTC 与低轨样本 |
| `kuiper_real_tracker.ipynb` | 真实 Amazon Kuiper / Amazon Leo |
| `oneweb_real_tracker.ipynb` | 真实 OneWeb |
| `kuiper_approved_missing.ipynb` | 按 FCC 批准的 Gen1 壳层参数补全估算数量缺口 |
| `oneweb_approved_missing.ipynb` | 按 FCC 批准的 Phase1 壳层参数补全估算数量缺口 |
| `kuiper_custom.ipynb` | 自定义 Kuiper 虚拟轨道和额外卫星 |
| `oneweb_custom.ipynb` | 自定义 OneWeb 虚拟轨道和额外卫星 |

先运行 `download_tle.ipynb`，再按需求运行其余文件。`*_approved_missing.ipynb` 只依赖 `download_tle.ipynb` 的完整轨道目录，不需要先生成真实可见 CSV。`*_custom.ipynb` 是独立实验分支，不是 `*_approved_missing.ipynb` 的下一批卫星；同一星座合并时选一种虚拟场景。

Python 3.10+，在项目目录安装依赖：

```bash
cd "/home/shizhen/my_project/WorldNTN/generate satellite"
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

在 IDE 中选择 `.venv/bin/python` 为 notebook 内核。测试命令：`.venv/bin/python -m pytest -q tests`。

## 目录

```text
generate satellite/
  download_tle.ipynb / *_real_tracker.ipynb / *_approved_missing.ipynb / *_custom.ipynb
  satellite_pipeline.py         # 统一抓取、坐标、真实传播、CSV、合并
  synthetic_orbits.py           # 两个独立虚拟建模分支
  scenario.json                 # 公共观测点、时间轴、筛选条件、输入快照
  tle/                          # 真实输入，不覆盖历史快照
    starlink/ kuiper/ oneweb/
    snapshot_<UTC>.json
  orbit_info/                   # 与 tle 并列
    approved_shells.csv         # 官方参数，逐行引用
    custom_shells.json          # 用户自定义参数
    SOURCES.md / sources.json
    official_documents/         # FCC 原始 PDF 与校验哈希
    generated/                  # 每次模拟的平均轨道根数、相位假设、数量统计
  outputs/
    real_gp/<constellation>/<UTC>/
    approved_shell_synthetic/<constellation>/<UTC>/
    custom_synthetic/<constellation>/<UTC>/
```

下载文件、生成轨道和输出已在此目录的 `.gitignore` 中忽略；本地仍会保留。分享复现实验时要同时复制 `scenario.json`、对应 `tle` 快照、`orbit_info/generated` 和输出 metadata。文件名时间表示抓取/生成时间，不等于轨道历元；原始历元另有记录。

## 抓取与完整性

[CelesTrak GP 格式说明](https://celestrak.org/NORAD/documentation/gp-data-formats.php)说明传统 TLE 的五位编号限制。`download_tle.ipynb` 同时请求 TLE 和完整 OMM JSON，传播优先读取 JSON，支持六位 NORAD 编号。TLE 校验行长度、编号和 checksum；JSON 校验参数；按 NORAD ID 去重并保留最新历元。manifest 记录 URL、UTC、SHA256、数量、历元范围和 OMM 中未出现在 TLE 的编号。

`auto` 复用两小时内快照，`local` 离线读取，`refresh` 请求新数据。HTTP 错误不会写成 TLE；单种格式失败会写明原因。三组 JSON 都成功才可作为完整传播输入，TLE 失败不丢弃已成功的 JSON。此时将可用五位编号的 OMM 记录转换成 `*_derived_from_omm.tle`，manifest 中单独标注转换来源与遗漏六位编号；它不是原始 TLE 下载结果。默认不做无限重试或静默使用旧数据。传播和虚拟生成 notebook 不联网。Skyfield 使用内置时间尺度，不隐式下载星历。

## 共享设置与过滤

`scenario.json` 默认沿用参考观测点 `(39.95697°, -105.16033°, 1660 m)`；采样区间为 `[start, start+24h)`，间隔 120 秒，共 720 个时间点；仰角至少 25°、全方位、不截断 top-N。首次运行 `download_tle.ipynb` 写入当前 UTC，以后保留。需要新实验时修改时间或在 `download_tle.ipynb` 设置 `RESET_START_TIME=True`。不同星座必须使用同一设置才能直接合并。

| 星座 | 最低 WGS84 高度 | DTC 处理 |
|---|---:|---|
| Starlink | 450 km | 沿用原 `[DTC]` 排除规则，兼容其他明确 DTC 名称标记 |
| Kuiper | 550 km | 有明确 DTC 标记才排除，不按未核实的编号段推断 |
| OneWeb | 1100 km | 同上 |

Starlink 门限来自原 notebook；另外两项是可调整的工程筛选值，不是官方业务状态判定。**低高度可能表示升轨、降轨或其他状态；高于门限也不能保证正在提供宽带服务。** DTC 识别依赖输入名称，可能不完整；`excluded_norad_ids` 可以补充已确认排除名单。高度按每个采样时刻过滤。修改这些规则应重跑所有待合并输出。

真实轨道数据默认限制 `abs(采样时间−轨道历元) <= 14 days`，逐样本记录过期情况；整个缺口估算目录过期则拒绝补全。应尽量使用靠近实验日期的归档数据，不能用今天的 TLE 可靠重建很久以前的轨迹。[Skyfield 的历元说明](https://rhodesmill.org/skyfield/earth-satellites.html#checking-an-element-set-s-epoch)

## CSV 内容与坐标

前 12 列保留参考格式：`Time, Name, Azimuth (°), Elevation (°), Orbit Altitude (km), Slant km, x_East (m), y_North (m), z_Up (m), vx_East (m/s), vy_North (m/s), vz_Up (m/s)`。

新增从 1 开始的 `TimeIndex`、全球唯一 `Satellite ID`、真实 `NORAD ID`、星座、来源类型、synthetic/DTC 标记、壳层、经纬度、ECEF 位置/速度、ECEF/GCRS 速率、距离变化率、轨道历元与输入哈希。虚拟 NORAD 留空，不伪造官方编号或 TLE。`Time` 使用带 `Z` 的 ISO UTC，可通过 `pd.to_datetime(..., utc=True)` 读取。

ECEF 使用 ITRS；ENU 是固定地面站的局部东、北、天坐标，位置减去地面站位置，速度通过旋转参考系变换后再减去地面站速度。包含地球自转项，不能用惯性速度直接旋转代替。[Skyfield 参考系 API](https://rhodesmill.org/skyfield/api-position.html#skyfield.positionlib.ICRF.frame_xyz_and_velocity)

默认 `*_visible.csv` 只含满足所有门限的可见样本，按时间、斜距排序；设置 `write_all_states=true` 可额外输出过滤后的全球状态，文件按卫星分块。每次还输出：

- `counts.csv`：包含零可见时间点；平均值以完整时间轴为分母。
- `filter_audit.csv`：逐星 DTC/手动排除、传播无效、过期、低轨、保留和可见样本数量。
- `metadata.json`：设置、输入、传播方式和完成状态。中途失败标为 `failed`，不可合并。

## 两种虚拟场景的边界

`*_approved_missing.ipynb` 使用已核对的批准参数。先对**完整目录**按倾角（默认 ±1°）与平均高度分配壳层；允许 200 km 至壳层高度+150 km，将升轨星、备份星也计入已有数量。每壳层生成 `max(批准数量 − 目录归属数量, 0)` 颗，输出 `population.csv` 与逐星 `real_assignments.csv`。过量备份星不会挪去抵消另一倾角壳层的缺口。

**这是基于目录的缺口估算，不是已经核实的未发射卫星名单。** 缺失目录、退役、跨系统归属和在轨备份会影响估计。官方没有提供逐星未来 RAAN 和相位，本实现只在批准壳层中构造可复现的模板：近极轨 RAAN 跨度默认 180°，其他 360°；每面均匀相位、Walker F 默认为 1（单面为 0），RAAN 起点/相位和缺口模板抽样由 seed 确定。所有这些都是假设。模板没有与真实卫星做逐个轨位配准，不可解读为真实空位或用于碰撞判断。

`*_custom.ipynb` 完全由 `custom_shells.json` 决定，不依赖批准参数；默认数量是示例额外星数。两类模拟都用零阻力的 SGP4 平均圆轨道，名义高度指 `a−R_WGS72`，与 CSV 中随位置变化的 WGS84 椭球高度略有差异。每颗模拟星的初始根数和假设均存档，`load_virtual_elements()` 可离线重放。

每个虚拟 notebook 的最后一格提供显式合并示例。`merge_exports()` 检查共同场景、输入哈希、完成状态与重复 ID，并阻止同一星座同时合并两种虚拟方案。合并不会自动解决模板与真实轨位的空间重合。

## 验证范围

`tests/test_pipeline.py` 覆盖旋转参考系速度与位置中心差分、Skyfield 地面几何对照、DTC/低轨/过期过滤、零可见时间统计、六位编号、缓存完整性、逐壳层缺口和可复现模拟、合并检查、notebook 结构与语法。

完成 `download_tle.ipynb` 的下载后，还可运行 `.venv/bin/python tests/smoke_notebooks.py`。它把输入复制到临时目录，离线执行八个 notebook；只传播两个时刻、每星座最多八颗卫星，但批准缺口使用完整目录统计。不会修改正式 `scenario.json` 或生成完整 24 小时仿真结果。
