"""只读配液方案：app.planning 纯函数求解器单元测试 + API 集成测试。"""

from __future__ import annotations

import importlib

import pytest


# ---------------- 求解器纯函数单元测试 ----------------


from app.planning import PlanSource, solve as solve_plan


def _sources(concs, caps=None, ids=None):
    if caps is None:
        caps = [30] * len(concs)
    if ids is None:
        ids = [f"s{i}" for i in range(len(concs))]
    return [
        PlanSource(i, ids[i], concs[i], caps[i])
        for i in range(len(concs))
    ]


def test_single_source_exact() -> None:
    sol = solve_plan(_sources([20]), 10, 20)
    assert sol is not None
    assert sol.volumes == (10,)
    assert sol.used_count == 1


def test_concentration_out_of_range_no_solution() -> None:
    # 目标浓度高于所有来源浓度
    assert solve_plan(_sources([10, 20]), 10, 50) is None
    # 目标浓度低于所有来源浓度
    assert solve_plan(_sources([10, 20]), 10, 5) is None


def test_available_cap_constrains_volume() -> None:
    # 浓度恰好 10 的样本只能给 5 μL，其余须用 0 浓度样本补足
    sol = solve_plan(_sources([10, 0], caps=[5, 30]), 10, 5)
    assert sol is not None
    assert sol.volumes == (5, 5)
    assert sol.used_count == 2
    # 0 浓度样本无可用量 → 无法补足
    assert solve_plan(_sources([10, 0], caps=[5, 0]), 10, 5) is None


def test_no_integer_mix_without_rounding() -> None:
    # V=3, C=50：40/60 混合需要 20*y = 30，无整数解，绝不四舍五入
    assert solve_plan(_sources([40, 60]), 3, 50) is None
    # 但 V 为偶数时精确可解
    sol = solve_plan(_sources([40, 60]), 4, 50)
    assert sol is not None
    assert sol.volumes == (2, 2)


def test_min_used_sources_beats_lexicographic() -> None:
    # 单来源（下标 3，浓度 50）方案 (0,0,0,10,0) 用量为 1；
    # 两来源方案 (0,0,5,0,5)（40/60）虽字典序更小，但来源数多 → 必须选单来源
    sol = solve_plan(_sources([20, 80, 60, 50, 40]), 10, 50)
    assert sol is not None
    assert sol.volumes == (0, 0, 0, 10, 0)
    assert sol.used_count == 1


def test_lexicographically_smallest_among_equal_used() -> None:
    # 同为 2 个来源：(5,5,0,0)（20/80）与 (0,0,5,5)（40/60）→ 后者字典序更小
    sol = solve_plan(_sources([20, 80, 40, 60]), 10, 50)
    assert sol is not None
    assert sol.volumes == (0, 0, 5, 5)
    assert sol.used_count == 2


def test_zero_concentration_target() -> None:
    sol = solve_plan(_sources([0, 20], caps=[30, 30]), 10, 0)
    assert sol is not None
    assert sol.volumes == (10, 0)
    # 没有 0 浓度来源则无法精确配出 0 浓度
    assert solve_plan(_sources([5, 10]), 10, 0) is None


def test_zero_cap_sources_kept_in_vector() -> None:
    sol = solve_plan(_sources([50, 100, 0], caps=[0, 30, 30]), 6, 50)
    assert sol is not None
    # 浓度 50 的来源可用体积为 0；只能用 100 与 0 浓度来源配出 50：
    # 100*y = 300 → y=3，z=3；零用量来源仍保留在向量中
    assert sol.volumes == (0, 3, 3)
    assert sol.used_count == 2


def test_target_volume_one_microliter() -> None:
    # 1 μL 只能整体取自某个浓度恰为目标浓度的来源
    assert solve_plan(_sources([49, 51]), 1, 50) is None
    sol = solve_plan(_sources([49, 50, 51]), 1, 50)
    assert sol is not None
    assert sol.volumes == (0, 1, 0)


# ---------------- API 集成测试 ----------------


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_file))

    import app.database as database
    import app.services as services
    import app.main as main

    importlib.reload(database)
    importlib.reload(services)
    importlib.reload(main)

    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        yield c


def _make_sample(client, sid, name=None):
    payload = {
        "id": sid,
        "name": name or f"样本-{sid}",
        "freeze_threshold_c": -20,
        "thaw_threshold_c": 0,
    }
    r = client.post("/samples", json=payload)
    assert r.status_code == 201, r.text


def _plan(client, sources, target_volume_ul=10, target_concentration_ng_ul=50):
    return client.post(
        "/preparation-plans",
        json={
            "sources": sources,
            "target_volume_ul": target_volume_ul,
            "target_concentration_ng_ul": target_concentration_ng_ul,
        },
    )


def _src(sid, c, v):
    return {"sample_id": sid, "concentration_ng_ul": c, "available_volume_ul": v}


def test_api_exact_plan_with_zero_items(client) -> None:
    for sid in ("a", "b", "c", "d"):
        _make_sample(client, sid)
    r = _plan(
        client,
        [_src("a", 20, 30), _src("b", 80, 30), _src("c", 40, 30), _src("d", 60, 30)],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["target_volume_ul"] == 10
    assert body["target_concentration_ng_ul"] == 50
    assert body["target_mass_ng"] == 500
    assert body["used_sample_count"] == 2
    assert [it["volume_ul"] for it in body["items"]] == [0, 0, 5, 5]
    # 逐项返回全部来源（含零用量），顺序与请求一致
    assert len(body["items"]) == 4
    assert [it["sample_id"] for it in body["items"]] == ["a", "b", "c", "d"]
    assert [it["order_index"] for it in body["items"]] == [0, 1, 2, 3]
    assert [it["used"] for it in body["items"]] == [False, False, True, True]
    assert body["items"][0]["sample_name"] == "样本-a"
    # 精确性自检：体积之和与质量之和恰好达标
    assert sum(it["volume_ul"] for it in body["items"]) == 10
    assert sum(
        it["volume_ul"] * it["concentration_ng_ul"] for it in body["items"]
    ) == 500


def test_api_single_source_plan(client) -> None:
    _make_sample(client, "s1")
    r = _plan(client, [_src("s1", 50, 10)])
    assert r.status_code == 200
    body = r.json()
    assert body["used_sample_count"] == 1
    assert body["items"][0]["volume_ul"] == 10
    assert body["items"][0]["used"] is True


def test_api_no_exact_solution_returns_409(client) -> None:
    _make_sample(client, "a")
    _make_sample(client, "b")
    # 3 μL、目标 50 ng/μL，40 与 60 混合无整数解
    r = _plan(client, [_src("a", 40, 30), _src("b", 60, 30)], target_volume_ul=3)
    assert r.status_code == 409
    # 目标浓度超出所有来源浓度范围
    r = _plan(client, [_src("a", 10, 30), _src("b", 20, 30)], target_concentration_ng_ul=50)
    assert r.status_code == 409


def test_api_missing_sample_returns_422(client) -> None:
    _make_sample(client, "a")
    r = _plan(client, [_src("a", 50, 10), _src("ghost", 50, 10)])
    assert r.status_code == 422
    assert "ghost" in r.json()["detail"]


def test_api_duplicate_sample_ids_returns_422(client) -> None:
    _make_sample(client, "a")
    r = _plan(client, [_src("a", 50, 10), _src("a", 60, 10)])
    assert r.status_code == 422


@pytest.mark.parametrize(
    "payload",
    [
        # 空来源列表 / 超过 6 个来源
        {"sources": [], "target_volume_ul": 1, "target_concentration_ng_ul": 1},
        {
            "sources": [_src(f"s{i}", 10, 10) for i in range(7)],
            "target_volume_ul": 1,
            "target_concentration_ng_ul": 1,
        },
        # 目标体积越界（1~30）
        {"sources": [_src("s0", 10, 10)], "target_volume_ul": 0, "target_concentration_ng_ul": 1},
        {"sources": [_src("s0", 10, 10)], "target_volume_ul": 31, "target_concentration_ng_ul": 1},
        # 浓度越界（0~100）
        {"sources": [_src("s0", 10, 10)], "target_volume_ul": 1, "target_concentration_ng_ul": -1},
        {"sources": [_src("s0", 10, 10)], "target_volume_ul": 1, "target_concentration_ng_ul": 101},
        # 来源可用体积越界（0~30）
        {"sources": [_src("s0", 10, -1)], "target_volume_ul": 1, "target_concentration_ng_ul": 1},
        {"sources": [_src("s0", 10, 31)], "target_volume_ul": 1, "target_concentration_ng_ul": 1},
        # 来源浓度越界
        {"sources": [_src("s0", -1, 10)], "target_volume_ul": 1, "target_concentration_ng_ul": 1},
        {"sources": [_src("s0", 101, 10)], "target_volume_ul": 1, "target_concentration_ng_ul": 1},
        # 非整数（严格拒绝，不做隐式转换）
        {"sources": [_src("s0", 10, 10)], "target_volume_ul": 1.5, "target_concentration_ng_ul": 1},
        {"sources": [_src("s0", 10.5, 10)], "target_volume_ul": 1, "target_concentration_ng_ul": 1},
        # 布尔值不得充当整数
        {"sources": [_src("s0", 10, 10)], "target_volume_ul": True, "target_concentration_ng_ul": 1},
        # 空 sample_id
        {"sources": [_src("", 10, 10)], "target_volume_ul": 1, "target_concentration_ng_ul": 1},
    ],
)
def test_api_invalid_params_422(client, payload) -> None:
    r = client.post("/preparation-plans", json=payload)
    assert r.status_code == 422, r.text


def test_api_plan_is_read_only(client) -> None:
    _make_sample(client, "a")
    _make_sample(client, "b")
    before = client.get("/samples/a").json()
    for _ in range(2):
        r = _plan(client, [_src("a", 40, 30), _src("b", 60, 30)], target_volume_ul=3)
        assert r.status_code == 409
    # 样本数据不被修改（无库存扣减、无任何写入）
    after = client.get("/samples/a").json()
    assert after == before
    # 可行方案重复查询结果一致
    r1 = _plan(client, [_src("a", 40, 30), _src("b", 60, 30)], target_volume_ul=4)
    r2 = _plan(client, [_src("a", 40, 30), _src("b", 60, 30)], target_volume_ul=4)
    assert r1.json() == r2.json()


def test_api_cap_zero_source_only_zeros(client) -> None:
    _make_sample(client, "a")
    _make_sample(client, "b")
    # a 可用体积为 0 但浓度恰好匹配，不能取用；需 b 也能精确配出
    r = _plan(client, [_src("a", 50, 0), _src("b", 50, 10)])
    assert r.status_code == 200
    assert [it["volume_ul"] for it in r.json()["items"]] == [0, 10]
    # 仅有的浓度匹配来源可用体积为 0，且目标体积 > 0 → 409
    r = _plan(client, [_src("a", 50, 0), _src("b", 0, 10)])
    assert r.status_code == 409
