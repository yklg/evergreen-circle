# 地图 API 调用策略与等时圈算法设计

> 适用：常青圈「15 分钟生活圈智能体检」living_circle 域（M1，代码 `backend/app/living_circle/`）。
> 目标：在个人百度地图开放平台免费额度（低 QPS、低配额）下，稳定算出可信的 5/10/15/20 分钟步行等时圈，并对齐赛题评分点（批量算路、坐标转换、POI 检索）。

---

## 1. 调用策略（AK 分级与韧性）

### 1.1 AK 分级

| AK | 用途 | 权限配置 | Referer 白名单 |
|---|---|---|---|
| `BAIDU_SERVER_AK` | 服务端：批量算路 / 地点检索 / 地理编码 / 逆地理 / 坐标转换 | 对应 Web 服务 API | 无需配 |
| `BAIDU_BROWSER_AK` | 浏览器端：JS API（后续 M5 交互地图） | JS 服务 | `http://localhost:3400/*`、`http://127.0.0.1:3400/*`、生产域名 |

工程上把「服务端」与「浏览器端」拆成两个应用（应用管理 → 创建），浏览器端绝不下发服务端 AK，规避盗用。

### 1.2 接口清单

| 接口 | 用途 | 频度（单次体检·标准档） |
|---|---|---|
| `routematrix/v2/walking` | **批量距离矩阵**（等时圈主路径，R2 决策） | 标准档实测 **11 次**（1049 点 ÷ 每块 100 起源 × 1 目的地；次数随档位与预算变） |
| `place/v2/search` | 8 类 POI + 三要素检索 | ~27 次（多关键词查全） |
| `geocoding/v3` | 纯地名输入 → 中心点 | ≤1 次 |
| `directionlite/v1/walking` | 单点步行测时（**批量失败兜底**） | 0–200 次（仅降级） |
| `geoconv/v1` | GCJ-02 → BD-09 坐标转换 | 按需 |

### 1.3 限量与韧性（`request_guard.py`）

个人免费 AC 的 QPS 与配额是硬约束，采用「信号量 + 级间限速 + 指数退避 + 重试 + 批量失败降级」五层：

- **并发信号量** `max_concurrency=4`：控制同一时刻在途请求数；
- **级间最小间隔** `min_interval_s=0.25`：任意两次真实请求间隔下限，拉平瞬时 QPS 尖峰；
- **版式重试**：网络/超时（TimeoutError/ConnectionError/OSError）与配额类状态码（401/402/403/404/429）自动重试 `max_retries=4`，退避 `0.5s × 2^n` 封顶 12s + 抖动，避免惊群；
- **失败监控**：`GuardStats`（成功/失败/重试/退避计数 + 成功率）供可观测性面板；
- **批量失败降级（关键）**：`routematrix` 某一块返回行数不足（配额收紧偶发）时，该块内逐点回退到 `directionlite` 单点测时（`python`），宁可慢也不缺行，落地「批量为主、单点兜底」的 R2 决策。

```
调用链：rue: pipeline/measure
  IsochroneEngine.compute(N 采样点，规格随档位与预算 ⇒ 逐份见报告 sampling.spec)
    └─ BaiduClient.route_matrix_walking（按 capability_manifest 登记的块上限分批：步行/骑行 100、驾车 25）
          ├─ 块成功 → 解析 duration.value → 分钟
          └─ 块不足/失败 → direction_walking 逐点兜底（guard 限速）
```

### 1.4 坐标口径

统一使用 **BD-09**（百度坐标系）：中心点直接采集 BD-09；外部输入若为 GCJ-02/WGS-84 走 `geoconv` 转换。采样点与 POI 全链同口径，避免叠加漂移。

---

## 2. 等时圈算法（渔网采样 + IDW + 等值线，`isochrone.py` / `contour.py`）

### 2.1 分档采样（`build_sample_points`）

研究范围 `study_radius_m=2500`（半径 2.5km，覆盖 5/10/15/20 分钟步行带）。三档采样密度：

| 档位 | 粗网格 `coarse` | 边界带 `fine`（800–1600m 环） | 采样点数（约） |
|---|---|---|---|
| quick 速览 | 500m | 不加密 | ~90 |
| standard 标准 | 400m | 200m（极坐标） | ~500 |
| precise 精细 | 300m | 150m（极坐标） | ~800 |

生成逻辑：

1. **粗网格**：以中心为原点、`half=2500m` 的对称方格（奇数点数使中心恰落在格点），仅保留圆内点；
2. **边界带加密**：环带 `fine_band` **不写死，由口径派生** —— `(max(最内圈理论半径, 400m), study_radius)`（式在 `caliber.py` 的 `fine_band`）。三档实测：步行 `(400, 2500)`m、骑行 `(833, 5000)`m、驾车 `(2174, 9000)`m。对环带按极坐标（半径分级 + 角度均匀，`n_angle≥12`）加密——15min 等时圈（步行速度基准 80 m/min、绕行系数 1.3 ⇒ 理论直线半径 ≈923m）恰好落在这个环带里，加密保证等值线细节；
3. **去重**：粗/细网格重叠点按 5 位小数去重。

```python
# 粗网格：奇数对称轴（中心恰落格点）
n_coarse = ceil(half / coarse) * 2 + 1
axis = _aligned_axis(half, n_coarse)          # [-half, half] 等距
# 边界带：极坐标（半径分级 + 角度均匀），15min 圈精度所在
for r in linspace(lo, hi, n_fine):
    for k in range(max(12, int(2π·r/fine_m))):
        pts.append(center + (r·cosθ, r·sinθ))
```

### 2.2 批量测时

对全部采样点一次 `routematrix/v2/walking`（N×1：N 个采样点 → 中心），每块上限由 `capability_manifest.json` 实测登记（步行/骑行 **100** 起源/块，驾车仍是 25 —— 50 起即 401，非早期文档一律写的 25）。返回 `result` 行数组，`duration.value`（秒）→ 分钟；`restrictions_status!=0` 记不可达（None）。步行速度基准住在 `caliber.py`（现值 **80 m/min**，`R7` 由 75 上调），合成场与最坏情形估算都从这**同一份**读数（`data_source.py` 取 `caliber.speed_m_per_min`），真实测时以 API 返回为唯一口径。

### 2.3 IDW 反距离加权插值（`idw_from_local`）

把离散采样点耗时插值为连续场：

- 采样点与插值格点统一投影到**以中心为原点的局部平面**（`geo_utils.to_local_xy`，等距圆柱近似：`x=Δlng·cosφ·111320`，`y=Δlat·111320` 米）；
- 对插值网格每一点取 **k=8 近邻**（非全量）采样点，**反距离加权**：

$$\hat{t}(\mathbf{p}) = \frac{\sum_{i \in \mathcal{N}_8(\mathbf{p})} w_i\, t_i}{\sum_{i \in \mathcal{N}_8(\mathbf{p})} w_i},\quad w_i = \frac{1}{(d_i + \epsilon)^p}$$

- **为何 k-近邻而非全量**：全量加权会让稀疏粗网格中心区被远处高值样本全局平均拉高（实测 200m 处被拉到 10min，实际应 ≈4min）。k=8 近邻保证局部各向异性正确；
- 不可达采样点（None）不参与加权；全部不可达返回 `inf`（该域全为不可达）。

> 复杂度：`(G, S)` 距离矩阵一次向量化（numpy），`grid_n=80` 时 G=6400、S≈500，完全在秒级。

### 2.4 等值线提取（`contour.py`）

对插值场 `field2d ≤ minutes_th`（5/10/15/20 分钟）取连通域（**mask_connect_center**：必须与中心格连通——排除"远处快、中心不可达"的伪圈），再：

1. `trace_exterior` 追踪外环像素（Marching-squares 风格，`max_steps` 安全阀）；
2. `smooth_ring` 平滑环；
3. 反投影回 (lng, lat)，`ensure_closed` 闭合；
4. `ring_area_km2` 球面三角面积 → `area_km2`。

输出：4 层 GeoJSON Polygon 环 + 面积列表（`isochrones: [{minutes, geojson, area_km2}]`），并带 `sampling`（采样点 × 分钟、可达标记、`interpolation:'idw'`、`is_scattered`）。

```python
mask = field2d <= minutes_th
comp = mask_connect_center(mask, center_cell)      # 必须与中心连通
ring = smooth_ring(trace_exterior(comp, step))     # 等值线
zone  = {minutes, geojson: Polygon(ring_lnglat), area_km2}
```

### 2.5 与 ArcGIS 服务区法（Network Analyst Service Area）对比

| 维度 | 本实现（百度批量算路 + IDW） | ArcGIS Network Analyst 服务区 |
|---|---|---|
| 路网数据 | 百度路网（云端，实时配额驱动） | 本地路网数据集（需自有数据+授权） |
| 耗时场 | N 采样点 × 1 中心（一次矩阵），IDW 插值 | 网络阻抗求解，精确可达域 |
| 精度 | 采样+插值近似（边缘带加密缓解） | 精确（网络拓扑） |
| 成本 | 免费额度内（~20 次矩阵调用/社区） | 高（商业许可/数据维护） |
| 输出 | 5/10/15/20 分钟等值线 + 面积，可直接出图 | 服务区面要素 |

**选用理由**：赛题限定「地图开放能力」，个人 AK 免费额度内用批量算路 + IDW 逼近网络服务区效果；通过边界带加密、k-近邻 IDW、中心连通约束三类手段把插值误差控制在演示可接受范围，并全流程披露（报告 `sampling.interpolation='idw'` + 界面横幅标注）。

---

## 3. 实测结果（真实 AK · M5）

> 下表在 `backend/` 下运行 `python scripts/snapshot_live.py` 生成（真实 `data_mode=live`，串行限流），快照覆写 `backend/app/living_circle/fixtures/` 与 `frontend/src/mocks/fixtures/livingCircle/`。数据可离线一键复现。

<!-- M5 实测回填 -->
| 社区 | 5min/km² | 10min/km² | 15min/km² | 20min/km² | POI 采集 | 圈内 POI | 盲区 | 综合评分 | 采样可达 |
|---|---|---|---|---|---|---|---|---|---|
| 凯里老街 | 0.06 | 0.42 | 1.36 | 2.74 | 339 | 49 | 3 | 58.5 | 498/498 |
| 北京劲松 | 0.06 | 0.33 | 1.26 | 3.23 | 356 | 38 | 1 | 56.6 | 498/498 |

复现步骤：

```bash
cd backend
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env   # 填入 BAIDU_SERVER_AK
.venv/bin/python scripts/snapshot_live.py
```

---

## 4. 可观测性

- 每次真实调用经 `GuardStats` 计数（成功/失败/重试/退避），可用于「调用策略」评分点的量化证据；
- `probe_baidu.py`：单接口探针（分组跑，打印各接口状态码与耗时），M0 已全组通过（9/9，含 4×1 批量矩阵）；
- 失败降级在全链可观测（日志 `routematrix 块行数不足…降级单点兜底`）。

---

## 5. 渲染层（真实地图 · 评审对齐）

前端地图页/对比页以 **BMapGL v3.0** 渲染真实百度瓦片底图，覆盖层全部来自本算法产出：

| 图层 | 数据来源 | 评审口径 |
|---|---|---|
| 采样点耗时热力 | `sampling.points`（渔网采样 + 批量算路测时，逐点按 0→20min 渐变着色） | 40%「等时圈热力图」 |
| 等时圈族 5/10/15/20min | `isochrones`（IDW 耗时场 + marching-squares 等值线） | 40%「15 分钟步行等时圈」 |
| POI 真实坐标 Marker | `poi.points`（多关键词检索 + 清洗 + IDW 耗时回填） | 40%「POI 检索」 |
| 盲区灰区 | `blindspots`（1km 网格硬判 + 连通聚合） | 40%「服务盲区识别」 |
| 中心标记（可拖拽）+「定位到我」 | BMapGL Geolocation（WGS84→BD-09）+ 逆地理 | 15%「交互/自定义中心点」 |

**关键澄清（对应 30%「不取底层路网」）**：底图瓦片（路网/水系/标注）仅作**地理参照**，其拓扑不参与任何计算——等时圈与耗时场完全由「分散点位 API 测时 + IDW 插值」推导。评审材料中明确区分「参照底图」与「计算数据」，杜绝被误读为调用了底层路网。

**底图风格调适（C7）**：应用「个性化地图」浅色样式（`BAIDU_MAP_STYLE_ID` 优先，空则内置低饱和 styleJson 模板），弱化底图与覆盖层争色。

**降级链**：无 AK / 脚本加载失败 / 离线 → 自动回退静态 SVG 投影画布 + 降级横幅（评审无网演示能力不退化）；`poi.points` 为空时跳过 Marker 不报错。

**快照点位**：权威快照（评分/等时圈/盲区/聚合统计）保持 M5 冻结；`poi.points` 由 `scripts/make_fixture_points.py` **增量附加**（只补点位，不改冻结字段），避免整包重跑导致真实数据漂移。