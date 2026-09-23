"""M1 域级冒烟：合成径向耗时场 → 等时圈；fixture 数据源 → 完整体检契约。"""
import asyncio

from app.living_circle.data_source import CheckParams, FixtureDataSource
from app.living_circle.geo_utils import haversine_m
from app.living_circle.isochrone import REACH_FULL_MIN, IsochroneEngine

center = (107.9758, 26.5734)
engine = IsochroneEngine()


async def meter_fn(pts):
    out = []
    for p in pts:
        d = haversine_m(center, p)
        out.append(d / 75.0 if d < 2200 else None)  # 15min≈1125m
    return out


async def main():
    iso = await engine.compute(center, meter_fn, study_radius_m=2500, mode="quick")
    print("zones:", [(z["minutes"], z["area_km2"]) for z in iso["isochrones"]])
    print(
        "sample pts:", iso["sample_count"],
        "timed:", iso["sampling"]["timed_count"],
        "in_reach(<=%gmin):" % REACH_FULL_MIN, iso["sampling"]["in_reach_count"],
    )
    # 分档必须分离：全部已测时 ≠ 全部可达（旧版把两者混为一谈，见 isochrone.py 顶部说明）
    assert iso["sampling"]["in_reach_count"] < iso["sampling"]["timed_count"] <= iso["sample_count"]
    a15 = next(z for z in iso["isochrones"] if z["minutes"] == 15)["area_km2"]
    assert a15 > 2.5, a15
    assert iso["sampling"]["interpolation"] == "idw"

    ds = FixtureDataSource()
    r = await ds.compute(CheckParams(scene_name="凯里老街", center=center))
    print("fixture:", r["scene"]["name"], r["scores"]["total"], "blindspots", len(r["blindspots"]))
    assert r["scores"]["total"] == 65


asyncio.run(main())
print("SMOKE OK")