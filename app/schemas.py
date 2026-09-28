"""请求 / 响应 Pydantic 模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator


def _freeze_lt_thaw(data: dict) -> dict:
    freeze = data.get("freeze_threshold_c")
    thaw = data.get("thaw_threshold_c")
    if freeze is not None and thaw is not None and freeze >= thaw:
        raise ValueError("freeze_threshold_c 必须严格小于 thaw_threshold_c")
    return data


def _validate_dose_fields(data: dict) -> dict:
    """暴露剂量相关字段的跨字段校验。"""

    for name in (
        "cold_dose_budget_c_min",
        "heat_dose_budget_c_min",
        "max_integration_interval_minutes",
    ):
        value = data.get(name)
        if value is not None and value <= 0:
            raise ValueError(f"{name} 必须为正数")

    if data.get("cold_dose_budget_c_min") is not None and data.get("min_allowed_c") is None:
        raise ValueError("配置 cold_dose_budget_c_min 时必须同时提供 min_allowed_c")
    if data.get("heat_dose_budget_c_min") is not None and data.get("max_allowed_c") is None:
        raise ValueError("配置 heat_dose_budget_c_min 时必须同时提供 max_allowed_c")
    return data


# ---------------- 请求模型 ----------------


class SampleCreate(BaseModel):
    id: Optional[str] = Field(None, max_length=128, description="不填则自动生成 UUID")
    name: str = Field(..., max_length=256)
    freeze_threshold_c: float = Field(..., description="温度 <= 该值判定为冻结（默认建议 -20）")
    thaw_threshold_c: float = Field(..., description="温度 >= 该值判定为解冻（默认建议 0）")
    min_allowed_c: Optional[float] = Field(None, description="允许的最低温度，低于即告警")
    max_allowed_c: Optional[float] = Field(None, description="允许的最高温度，高于即告警")
    max_freeze_thaw_cycles: Optional[int] = Field(None, ge=0, description="允许的最大冻融循环次数")
    cold_dose_budget_c_min: Optional[float] = Field(
        None,
        gt=0,
        description="低温累计暴露剂量预算（°C·min），首次跨越产生 exposure_budget_exceeded 告警",
    )
    heat_dose_budget_c_min: Optional[float] = Field(
        None, gt=0, description="高温累计暴露剂量预算（°C·min）"
    )
    max_integration_interval_minutes: Optional[float] = Field(
        None,
        gt=0,
        description="相邻读数最大可积分间隔（分钟）；超过则跳过该区间并计入缺口时长",
    )

    @model_validator(mode="after")
    def _validate(self):
        if self.freeze_threshold_c >= self.thaw_threshold_c:
            raise ValueError("freeze_threshold_c 必须严格小于 thaw_threshold_c")
        _validate_dose_fields(self.model_dump())
        return self


class SampleUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=256)
    freeze_threshold_c: Optional[float] = None
    thaw_threshold_c: Optional[float] = None
    min_allowed_c: Optional[float] = None
    max_allowed_c: Optional[float] = None
    max_freeze_thaw_cycles: Optional[int] = Field(None, ge=0)
    cold_dose_budget_c_min: Optional[float] = Field(None, gt=0)
    heat_dose_budget_c_min: Optional[float] = Field(None, gt=0)
    max_integration_interval_minutes: Optional[float] = Field(None, gt=0)

    @model_validator(mode="after")
    def _validate(self):
        data = self.model_dump(exclude_unset=True)
        _freeze_lt_thaw(data)
        # 是否同时提供允许区间边界的跨字段检查由路由层合并现有配置后完成
        for name in (
            "cold_dose_budget_c_min",
            "heat_dose_budget_c_min",
            "max_integration_interval_minutes",
        ):
            if data.get(name) is not None and data[name] <= 0:
                raise ValueError(f"{name} 必须为正数")
        return self


class ReadingIn(BaseModel):
    temperature_c: float = Field(..., description="摄氏温度读数")
    event_time: datetime = Field(..., description="读数发生时间（ISO 8601，无时区按 UTC 处理）")
    event_id: Optional[str] = Field(
        None,
        max_length=128,
        description="客户端幂等键；不填则以 (event_time, temperature_c) 去重",
    )


class ReadingsBatch(BaseModel):
    readings: list[ReadingIn] = Field(..., min_length=1, max_length=10_000)


# ---------------- 共享记录仪 ----------------


class LoggerCreate(BaseModel):
    id: Optional[str] = Field(None, max_length=128, description="不填则自动生成 UUID")
    name: str = Field(..., max_length=256)


class LoggerUpdate(BaseModel):
    name: str = Field(..., max_length=256)


class LoggerBindingIn(BaseModel):
    start_time: datetime = Field(..., description="绑定时段起点（含，左闭；ISO 8601，无时区按 UTC 处理）")
    end_time: datetime = Field(..., description="绑定时段终点（不含，右开）")

    @model_validator(mode="after")
    def _validate(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time 必须严格晚于 start_time（左闭右开时段）")
        return self


class LoggerBindingUpdate(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    @model_validator(mode="after")
    def _validate(self):
        start = self.start_time
        end = self.end_time
        if start is not None and end is not None and end <= start:
            raise ValueError("end_time 必须严格晚于 start_time（左闭右开时段）")
        return self


class LoggerInvalidPeriodIn(BaseModel):
    start_time: datetime = Field(..., description="校准无效时段起点（含，左闭；ISO 8601，无时区按 UTC 处理）")
    end_time: datetime = Field(..., description="校准无效时段终点（不含，右开）")

    @model_validator(mode="after")
    def _validate(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time 必须严格晚于 start_time（左闭右开时段）")
        return self


class LoggerInvalidPeriodUpdate(BaseModel):
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    @model_validator(mode="after")
    def _validate(self):
        start = self.start_time
        end = self.end_time
        if start is not None and end is not None and end <= start:
            raise ValueError("end_time 必须严格晚于 start_time（左闭右开时段）")
        return self


class AckRequest(BaseModel):
    acknowledged: bool = True


# ---------------- 保管人交接与告警归责 ----------------


class CustodyHandoverIn(BaseModel):
    custodian: str = Field(..., min_length=1, max_length=128, description="接任保管人姓名/标识")
    effective_time: datetime = Field(
        ...,
        description="交接生效时间（ISO 8601，无时区按 UTC 处理）；允许补录较早时刻",
    )
    note: Optional[str] = Field(None, max_length=512, description="备注（可选）")


class CustodyHandoverOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    sample_id: str
    custodian: str
    effective_time: datetime
    note: Optional[str]
    created_at: datetime


class AlertCustodyItem(BaseModel):
    """一条当前告警的归责结果：按事件时间匹配左闭右开责任区间。"""

    alert_id: int = Field(..., description="告警 ID（alerts.id）")
    event_time: datetime = Field(..., description="告警事件时间")
    custodian: Optional[str] = Field(
        ..., description="责任保管人；首条交接之前为 null（责任人为空）"
    )
    handover_id: Optional[int] = Field(
        ..., description="匹配到的交接记录 ID；首条交接之前为 null"
    )


# ---------------- 只读配液方案 ----------------


class PreparationSourceIn(BaseModel):
    """配液候选来源：关联已有样本，并给出该样本当前浓度与可用体积。

    体积/浓度仅用于本次方案计算，接口只读，不扣减、不持久化任何库存。
    """

    sample_id: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="已有样本 ID（samples.id）；请求内不得重复",
    )
    concentration_ng_ul: int = Field(
        ...,
        strict=True,
        ge=0,
        le=100,
        description="来源样本浓度（整数纳克/微升，0~100）",
    )
    available_volume_ul: int = Field(
        ...,
        strict=True,
        ge=0,
        le=30,
        description="来源样本可用体积（整数微升，0~30）",
    )


class PreparationPlanRequest(BaseModel):
    sources: list[PreparationSourceIn] = Field(
        ...,
        min_length=1,
        max_length=6,
        description="1~6 个不同来源样本（按请求顺序决定字典序）",
    )
    target_volume_ul: int = Field(
        ...,
        strict=True,
        ge=1,
        le=30,
        description="目标混合液体积（整数微升，1~30）",
    )
    target_concentration_ng_ul: int = Field(
        ...,
        strict=True,
        ge=0,
        le=100,
        description="目标浓度（整数纳克/微升，0~100）",
    )

    @model_validator(mode="after")
    def _validate_unique_ids(self):
        ids = [s.sample_id for s in self.sources]
        if len(set(ids)) != len(ids):
            raise ValueError("sources 中的 sample_id 不得重复")
        return self


class PreparationPlanItemOut(BaseModel):
    """单个来源的逐项配方（未使用的来源同样返回，volume_ul 为 0）。"""

    sample_id: str
    sample_name: str
    order_index: int = Field(..., description="该来源在请求中的序号（0 起）")
    concentration_ng_ul: int
    available_volume_ul: int
    volume_ul: int = Field(..., description="取用体积（整数微升，0 表示不使用该来源）")
    used: bool = Field(..., description="volume_ul 是否大于 0")


class PreparationPlanOut(BaseModel):
    target_volume_ul: int
    target_concentration_ng_ul: int
    target_mass_ng: int = Field(..., description="目标总质量 = 目标体积 × 目标浓度（纳克）")
    used_sample_count: int = Field(..., description="非零用量的来源样本数")
    items: list[PreparationPlanItemOut] = Field(
        ...,
        description="逐项配方，与请求 sources 等长、同序，含零用量来源",
    )


# ---------------- 响应模型 ----------------


class SampleOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    freeze_threshold_c: float
    thaw_threshold_c: float
    min_allowed_c: Optional[float]
    max_allowed_c: Optional[float]
    max_freeze_thaw_cycles: Optional[int]
    cold_dose_budget_c_min: Optional[float]
    heat_dose_budget_c_min: Optional[float]
    max_integration_interval_minutes: Optional[float]
    current_state: str
    active_freeze_event_time: Optional[datetime]
    active_freeze_min_c: Optional[float]
    active_freeze_max_c: Optional[float]
    cycle_count: int
    cold_dose_c_min: float
    heat_dose_c_min: float
    exposure_gap_minutes: float
    created_at: datetime
    updated_at: datetime


class ReadingOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    sample_id: Optional[str] = None
    event_id: Optional[str]
    event_time: datetime
    received_at: datetime
    temperature_c: float
    # 读数来源：direct=样本直接读数；logger=记录仪读数经绑定时段归入
    source: str = "direct"
    logger_id: Optional[str] = None
    logger_reading_id: Optional[int] = None


class LoggerOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    created_at: datetime
    updated_at: datetime


class LoggerReadingOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    logger_id: str
    event_id: Optional[str]
    event_time: datetime
    received_at: datetime
    temperature_c: float


class LoggerBindingOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    sample_id: str
    logger_id: str
    start_time: datetime
    end_time: datetime
    created_at: datetime
    updated_at: datetime
    # 联表查询时附带名称，便于直接展示
    sample_name: Optional[str] = None
    logger_name: Optional[str] = None
    # 该时段当前归入的记录仪读数条数
    reading_count: Optional[int] = None


class LoggerInvalidPeriodOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    logger_id: str
    start_time: datetime
    end_time: datetime
    created_at: datetime
    updated_at: datetime
    # 联表查询时附带名称，便于直接展示
    logger_name: Optional[str] = None
    # 落在该时段内、被排除归属的记录仪原始读数条数
    reading_count: Optional[int] = None


class CycleOut(BaseModel):
    model_config = {"from_attributes": True}

    cycle_index: int
    freeze_event_time: datetime
    freeze_temperature_c: float
    thaw_event_time: datetime
    thaw_temperature_c: float
    min_temperature_c: float
    max_temperature_c: float


class AlertOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    sample_id: str
    alert_type: str
    severity: str
    event_time: datetime
    temperature_c: Optional[float]
    cycle_index: Optional[int]
    reading_id: Optional[int]
    logger_reading_id: Optional[int] = None
    direction: Optional[str]
    dose_c_min: Optional[float]
    budget_c_min: Optional[float]
    message: str
    acknowledged: bool
    created_at: datetime


class SampleStateOut(BaseModel):
    sample_id: str
    name: str
    current_state: str
    cycle_count: int
    active_freeze_event_time: Optional[datetime]
    active_freeze_min_c: Optional[float]
    active_freeze_max_c: Optional[float]
    # 双向累计暴露剂量（°C·min）、缺口总时长（分钟）与预算使用率（0~∞，>=1 即超限）
    cold_dose_c_min: float
    heat_dose_c_min: float
    exposure_gap_minutes: float
    cold_dose_budget_c_min: Optional[float]
    heat_dose_budget_c_min: Optional[float]
    max_integration_interval_minutes: Optional[float]
    cold_budget_usage: Optional[float]
    heat_budget_usage: Optional[float]
    last_event_time: Optional[datetime]
    last_temperature_c: Optional[float]
    unacknowledged_alert_count: int


class BatchReadingsResponse(BaseModel):
    sample_id: str
    accepted: int
    duplicates: int
    current_state: str
    cycle_count: int
    new_alerts: list[AlertOut]


class RecomputeResponse(BaseModel):
    sample_id: str
    cycle_count: int
    current_state: str
    alert_count: int
    new_alert_count: int


class LoggerReadingsResponse(BaseModel):
    logger_id: str
    accepted: int
    duplicates: int
    # 受迟到读数影响、已撤销旧归属并重建重算的样本
    affected_samples: list[str]
    # 这些样本重算后新产生的告警（跨样本）
    new_alerts: list[AlertOut]


# ---------------- 样本 × 记录仪温度一致性核查 ----------------


class ConsistencyPairOut(BaseModel):
    """一对配对读数中温差超限的明细（两侧读数 ID、时间、温度与时间差/温差）。"""

    reading_id: int = Field(..., description="样本直接读数 ID（readings.id）")
    logger_reading_id: int = Field(..., description="记录仪读数 ID（logger_readings.id）")
    sample_event_time: datetime
    logger_event_time: datetime
    sample_temperature_c: float
    logger_temperature_c: float
    time_diff_seconds: float = Field(..., description="两侧事件时间差的绝对值（秒）")
    temperature_diff_c: float = Field(..., description="两侧温差的绝对值（°C）")


class LoggerConsistencyResponse(BaseModel):
    sample_id: str
    logger_id: str
    max_time_diff_seconds: float
    temp_diff_threshold_c: float
    paired_count: int = Field(..., description="成功配对的读数对数（含温差正常的配对）")
    unmatched_sample_count: int = Field(..., description="未配对的样本直接读数条数")
    unmatched_logger_count: int = Field(..., description="未配对的记录仪归属读数条数")
    anomaly_count: int = Field(..., description="温差严格大于阈值的配对数")
    anomalies: list[ConsistencyPairOut]
