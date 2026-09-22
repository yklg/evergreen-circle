"""外部服务客户端层（百度地图等）。

依赖方向：orchestrator(core) → services → httpx/config。
services 不 import core 业务模块，防反向耦合。
"""
