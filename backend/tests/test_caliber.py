"""R1 · ReachCaliber 口径定义：单一事实源，派生而非硬编码。"""
import pytest

from app.living_circle.caliber import (
    DEFAULT_CALIBERS,
    ReachCaliber,
    all_travel_modes,
    caliber_payload_key,
    get_caliber,
)


def test_walking_caliber_lands_in_policy_band():
    """步行 15min 直线半径须落政策口径 0.8–1.2km。"""
    c = get_caliber("walking")
    r15 = 15 * c.speed_m_per_min / c.detour_k
    assert 800 <= r15 <= 1200, f"步行 15min 半径 {r15:.0f}m 出政策口径"


def test_fine_band_derived_from_innermost_radius():
    """fine_band 由最内圈半径派生，非硬编码 → 换 speed/detour 自动适配。"""
    for mode in ("walking", "riding", "driving"):
        c = get_caliber(mode)
        lo, hi = c.fine_band
        assert lo >= c.innermost_radius_m, f"{mode}: fine_band 下限应 ≥ 最内圈半径"
        assert hi == c.study_radius_m, f"{mode}: fine_band 上限应 = study_radius"


def test_grid_n_guarantees_resolution_invariant():
    """grid_n 保证 step ≤ 最内圈半径/4（B8/I10 不变量）。"""
    for mode in ("walking", "riding", "driving"):
        c = get_caliber(mode)
        n = c.grid_n_for_standard
        step = 2 * c.study_radius_m / (n - 1)
        assert step <= c.innermost_radius_m / 4, (
            f"{mode}: 格距 {step:.1f}m > 最内圈半径/4={c.innermost_radius_m/4:.1f}m"
        )


def test_travel_mode_not_reused_as_sample_profile():
    """命名治理（R5）：travel_mode 与 sample_profile 是两回事，不得复用同一字段。"""
    c = get_caliber("walking")
    assert c.travel_mode == "walking"
    # sample_profile 不在 ReachCaliber 中（它是采样档位 quick/standard/precise）
    assert not hasattr(c, "sample_profile")


def test_get_caliber_unknown_mode_raises():
    """未知出行方式显式报错，不静默兜底。"""
    with pytest.raises(ValueError, match="未知出行方式"):
        get_caliber("bogus")


def test_all_travel_modes_listed():
    assert set(all_travel_modes()) == {"walking", "riding", "driving"}


def test_caliber_payload_key_includes_travel_mode():
    """身份键纳入 travel_mode（R6），换方式必换键。"""
    base = caliber_payload_key("凯里老街", (107.9758, 26.5734), 2500, "standard", "walking")
    riding = caliber_payload_key("凯里老街", (107.9758, 26.5734), 2500, "standard", "riding")
    assert base != riding
    # travel_mode 恒为第 5 段，其后**可能**再跟归并判据版本段（开关开着才有）⇒
    # 判据不能写成 `endswith("|walking")`，那等于把键格式再抄一份进测试，
    # 键一加维度就只是把这条副本判成红（同一格式的判决已在 test_caching_datasource
    # 的 facility 段用例里正向守着，这里只守 travel_mode 这一维）。
    assert base.split("|")[4] == "walking"
    assert riding.split("|")[4] == "riding"


def test_caliber_payload_key_none_center_uses_zero():
    """center=None 时统一兜底 (0,0)，三份实现一致。"""
    k = caliber_payload_key("未定位", None, 2500, "standard")
    assert "0.000000,0.000000" in k


@pytest.mark.parametrize(
    "mode,expected_radius",
    [("walking", 2500), ("riding", 5000), ("driving", 9000)],
)
def test_study_radius_matches_mode(mode, expected_radius):
    assert get_caliber(mode).study_radius_m == expected_radius


def test_walking_is_measured_others_are_approximate():
    """只有步行经真实路网测时验证；骑行/驾车在探针通过后也标记为 measured=True。"""
    assert get_caliber("walking").measured is True
    # 阶段 2 探针已验证 riding/driving 矩阵可用，manifest 回填 measured=True
    assert get_caliber("riding").measured is True
    assert get_caliber("driving").measured is True
