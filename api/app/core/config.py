"""全局配置：从环境变量 / .env 读取，不硬编码密钥（第 16.4 章）。"""
import os
from functools import lru_cache

from dotenv import dotenv_values
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 用绝对路径定位 backend/.env，避免因启动工作目录不同而读不到密钥。
# config.py 位于 backend/app/core/，向上三级即 backend/。
_BACKEND_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
_ENV_FILE = os.path.join(_BACKEND_DIR, ".env")

# ── 旧名（ZHIPU_*）兼容层 ────────────────────────────────
# 键名已在「模型配置键名泛化」中从 zhipu_* 泛化为 llm_*（厂商无关的 OpenAI 兼容连接）。
# 为不破坏既有部署：新名 LLM_* 由 pydantic-settings 正常读取；缺失时经下面的
# default_factory 兜底读旧名 ZHIPU_*（os.environ 注入优先，其次 .env 文件）。
_LEGACY_ENV = dotenv_values(_ENV_FILE)  # .env 文件旧名一次读入（模块级）


def _legacy(name: str) -> str:
    """读旧名 env：os.environ 注入优先，其次 backend/.env 文件。"""
    v = os.environ.get(name)
    if v is None:
        v = _LEGACY_ENV.get(name)
    return v or ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    # LLM 连接（OpenAI 兼容，厂商无关——切厂商只需改 base_url/key/model，见「模型配置」页）
    # 字段用 default_factory 兜底旧名 ZHIPU_*（见 _legacy），故 .env 里旧键名无需迁移。
    llm_api_key: str = Field(default_factory=lambda: _legacy("ZHIPU_API_KEY"))
    # 默认/杂务模型：glm-5.1（10 并发，质量高、速度快）。
    # 报告章节按 SECTION_MODEL_MAP 用 glm-5.2(核心)/glm-5.1(辅助)；
    # intake/澄清/情感分类等杂务用 llm_model_fast（高并发极速）。
    llm_model: str = Field(default_factory=lambda: _legacy("ZHIPU_MODEL") or "glm-5.1")
    # 核心章模型（质量最高，10 并发）
    llm_model_core: str = Field(
        default_factory=lambda: _legacy("ZHIPU_MODEL_CORE") or "glm-5.2"
    )
    # 辅助章模型（质量高，10 并发）
    llm_model_aux: str = Field(
        default_factory=lambda: _legacy("ZHIPU_MODEL_AUX") or "glm-5.1"
    )
    # 杂务/快速模型（30 并发，极速，用于澄清/情感分类/单条重写等轻任务）
    llm_model_fast: str = Field(
        default_factory=lambda: _legacy("ZHIPU_MODEL_FAST") or "glm-z1-air"
    )
    llm_base_url: str = Field(
        default_factory=lambda: _legacy("ZHIPU_BASE_URL")
        or "https://open.bigmodel.cn/api/paas/v4"
    )
    # 单次 LLM 调用超时（秒）与自动重试次数，避免请求卡死拖垮整个服务。
    # analyze 等重型 JSON 调用（claims+对比+定价+五力+趋势一次产出）在大 max_tokens
    # 下耗时较长，180s 给足余量；max_retries 设 1，避免超时后再叠加 2 次重试（最坏 3×timeout）。
    llm_timeout: float = 180.0
    llm_max_retries: int = 1

    # 搜索 API（博查 Bocha Web Search：https://open.bocha.cn 获取 key）
    bocha_api_key: str = ""
    bocha_base_url: str = "https://api.bocha.cn/v1"
    # 单次搜索超时（秒）
    search_timeout: float = 30.0
    # 兼容旧字段（已弃用，不再使用）
    serpapi_key: str = ""
    bing_search_key: str = ""

    # 平台采集
    douyin_cookie: str = ""
    xhs_cookie: str = ""
    bilibili_cookie: str = ""

    # 百度地图**服务端 AK**（与浏览器端 AK 是不同申请类型）：
    # 供 services/baidu.py 的地点检索 / 地理编码 / 路线规划调用。
    # 缺失不炸任务——spots 实体阶段整体走降级链，地图/路线出占位（《目的地实体政策》）。
    baidu_server_ak: str = ""
    # 单次百度调用超时（秒）：批量 fan-out 时配合阶段级 deadline，慢接口不拖垮管线
    baidu_timeout: float = 8.0

    # 服务
    # 安全默认值：仅监听本机回环。
    # 本项目接口无鉴权（localhost 单用户假设），若绑定 0.0.0.0 会让同局域网
    # 任意主机读取配置、覆盖密钥。确需远程访问时请显式设 APP_HOST 并自行加防火墙/口令门禁。
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    frontend_origin: str = "http://localhost:5173"

    # 澄清问卷：候选目的地发现超时（秒）与发现结果缓存 TTL（天）。
    # 发现走 LLM（_discover_scope），设短超时 + 正则兜底，确保基础题不被阻塞（P0-①/②）。
    clarify_discover_timeout_s: float = 4.0
    discovery_cache_ttl_d: int = 7

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
