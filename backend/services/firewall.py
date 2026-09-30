"""
防火墙服务模块 — 通过 1Panel API 管理端口放行规则。

1Panel 的防火墙接口在两代版本间发生过重构，本模块自动探测并兼容：

- 新版（1Panel v2，规则清单式）：
    GET  /api/v2/hosts/firewall/settings       读取当前后端与地址族能力
    POST /api/v2/hosts/firewall/rules/search   搜索规则清单
    POST /api/v2/hosts/firewall/rules          批量创建规则（异步任务）
    POST /api/v2/hosts/firewall/rules/delete   按 uuid 批量删除（异步任务）
- 旧版（1Panel v1，端口专用）：
    POST /api/v2/hosts/firewall/search         搜索端口规则
    POST /api/v2/hosts/firewall/port           按 operation 增删端口

两代签名方式一致：Token = md5('1panel' + API-Key + 时间戳秒)。新版另支持
HMAC-SHA256（可由 1Panel-Signature-Version 头指定），但 MD5 仍被接受，
故统一使用 MD5 以获得最大兼容性。

所有操作幂等、失败不阻塞主流程。
"""
import asyncio
import hashlib
import json
import logging
import time
import urllib.error
import urllib.request

from backend.config import load_firewall_config

logger = logging.getLogger(__name__)

# 查询用：1Panel 管理的三条 iptables/nftables 链
_CHAIN_SCOPE_ORDER = ("1PANEL_BASIC_BEFORE", "1PANEL_BASIC", "1PANEL_BASIC_AFTER")
# 创建用：1Panel 新建规则固定落在该链（与官方前端一致）
_CHAIN_SCOPE_CREATE = "1PANEL_BASIC"

# 上下文（API 版本 + 防火墙后端 + 可用地址族）缓存，避免每次操作都探测
_CONTEXT_TTL = 300.0
_context_cache: dict = {"data": None, "expire_at": 0.0, "signature": ""}


def _get_api_config() -> dict:
    """读取防火墙 API 配置。"""
    config = load_firewall_config()
    return {
        "api_key": config.get("api_key", ""),
        "base_url": config.get("base_url", "http://127.0.0.1:55555"),
    }


def _get_api_base() -> str:
    """拼接 API 基地址。"""
    cfg = _get_api_config()
    return cfg["base_url"].rstrip("/")


def _make_sign_headers(api_key: str) -> dict:
    """生成 1Panel API 签名请求头（MD5 方式，两代版本均兼容）。"""
    ts = str(int(time.time()))
    token = hashlib.md5(f"1panel{api_key}{ts}".encode()).hexdigest()
    return {
        "Content-Type": "application/json",
        "1Panel-Token": token,
        "1Panel-Timestamp": ts,
    }


async def _call_api(method: str, path: str, data: dict | None = None) -> tuple[int, dict]:
    """调用 1Panel API，返回 (http_code, response_data)。

    http_code 为 0 表示网络层失败（连接被拒、超时等）；
    4xx/5xx 保留真实状态码，便于上层区分「接口不存在」与「鉴权失败」。
    """
    cfg = _get_api_config()
    if not cfg["api_key"]:
        return 0, {}

    url = f"{_get_api_base()}{path}"
    headers = _make_sign_headers(cfg["api_key"])
    body = json.dumps(data).encode("utf-8") if data is not None else None
    loop = asyncio.get_event_loop()

    def _sync_call():
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    try:
        return await loop.run_in_executor(None, _sync_call)
    except urllib.error.HTTPError as e:
        # 保留状态码：识别「新版接口不存在」需要它
        try:
            payload = json.loads(e.read().decode("utf-8"))
        except Exception:
            payload = {}
        return e.code, payload
    except Exception as e:
        logger.warning(f"[防火墙] 1Panel API 调用失败 ({path}): {e}")
        return 0, {}


# ==================== 版本与后端探测 ====================


def _build_scopes(provider: str, families: list[str]) -> list[dict]:
    """构造【查询】用的 scope 列表。

    查询需要覆盖 1Panel 管理的三条链（BEFORE/BASIC/AFTER），
    否则看漏已存在的规则、导致重复放行。
    注意：这个多链列表只用于读，创建规则时必须用 _build_create_scope。
    """
    if provider in ("iptables", "nftables"):
        return [
            {
                "provider": provider,
                "family": family,
                "table": "filter",
                "chain": chain,
                "direction": "input",
            }
            for family in families
            for chain in _CHAIN_SCOPE_ORDER
        ]
    if provider == "firewalld":
        return [{"provider": "firewalld", "family": "inet", "zone": "public", "direction": "input"}]
    if provider == "ufw":
        return [{"provider": "ufw", "family": "inet", "chain": "incoming", "direction": "input"}]
    return []


def _build_create_scope(provider: str, family: str = "ipv4") -> dict | None:
    """构造【创建】用的单个 scope。

    1Panel 官方前端在新建规则时把 chain 固定为 '1PANEL_BASIC'（单条链），
    family 取源地址所属族、无源地址时默认 ipv4。一个端口因此只产生一条规则。
    早期实现按三条链 × 两个地址族创建，会在防火墙上堆出 6 条重复规则。
    """
    if provider in ("iptables", "nftables"):
        return {
            "provider": provider,
            "family": family,
            "table": "filter",
            "chain": _CHAIN_SCOPE_CREATE,
            "direction": "input",
        }
    if provider == "firewalld":
        return {"provider": "firewalld", "family": "inet", "zone": "public", "direction": "input"}
    if provider == "ufw":
        return {"provider": "ufw", "family": "inet", "chain": "incoming", "direction": "input"}
    return None


def _parse_backend(payload: dict) -> dict:
    """从 /hosts/firewall/settings 响应中解析后端与可用地址族。"""
    system = ((payload or {}).get("data") or {}).get("system") or {}
    provider = system.get("current") or system.get("selected") or ""
    families: list[str] = []
    for option in system.get("options") or []:
        if option.get("name") != provider:
            continue
        for family in ("ipv4", "ipv6"):
            if (option.get(family) or {}).get("available"):
                families.append(family)
        break
    if not families:
        families = ["ipv4"]
    return {"provider": provider, "families": families}


async def _load_context(force: bool = False) -> dict:
    """探测 1Panel API 版本与防火墙后端，结果缓存 5 分钟。

    配置（地址或 API Key）发生变化时自动重新探测。
    返回 {"flavor": "v2"|"v1", "provider": str, "families": [...]}
    """
    cfg = _get_api_config()
    signature = f"{cfg['base_url']}|{cfg['api_key']}"
    now = time.time()

    if (not force
            and _context_cache["data"]
            and _context_cache["signature"] == signature
            and _context_cache["expire_at"] > now):
        return _context_cache["data"]

    context = {"flavor": "v1", "provider": "", "families": ["ipv4"]}

    # 新版独有 settings 接口，是判断版本最直接的依据
    code, payload = await _call_api("GET", "/api/v2/hosts/firewall/settings")
    if code == 200 and isinstance(payload, dict) and payload.get("code") == 200:
        context["flavor"] = "v2"
        context.update(_parse_backend(payload))
    else:
        # 旧版没有 settings，用端口查询确认连通性
        code, payload = await _call_api("POST", "/api/v2/hosts/firewall/search", {
            "page": 1, "pageSize": 1, "type": "port",
        })
        if code == 200 and isinstance(payload, dict) and payload.get("code") == 200:
            context["flavor"] = "v1"
        else:
            logger.warning("[防火墙] 无法识别 1Panel API 版本，按旧版接口尝试")

    _context_cache.update(data=context, expire_at=now + _CONTEXT_TTL, signature=signature)
    logger.info(f"[防火墙] 1Panel 接口版本={context['flavor']}，后端={context['provider'] or '未知'}")
    return context


# ==================== 新版（规则清单式） ====================


def _rule_uuid(item: dict) -> str:
    """从清单条目中取规则 uuid。

    1Panel 的 uuid 只存在于 desired.uuid（filter.DesiredRule），
    item.rule 与 item.observed.rule 上都没有该字段；
    但 observed.locator.nativeId 可作为原生规则标识兜底。
    """
    desired = (item or {}).get("desired") or {}
    uuid = desired.get("uuid")
    if uuid:
        return str(uuid)
    locator = ((item or {}).get("observed") or {}).get("locator") or {}
    native = locator.get("nativeId")
    return str(native) if native else ""


def _matches_accept_port(item: dict, target: str) -> bool:
    """判断清单条目是否为「目标端口的 accept 规则」。

    item.rule 与 item.observed.rule 都可能承载规则信息，任一命中即算匹配，
    避免因响应字段摆放差异而漏判（这正是面板误报未放行的成因之一）。
    """
    candidates = [
        (item or {}).get("rule") or {},
        ((item or {}).get("observed") or {}).get("rule") or {},
        ((item or {}).get("desired") or {}).get("rule") or {},
    ]
    for rule in candidates:
        if not rule:
            continue
        raw = str(rule.get("destinationPort") or "").strip()
        if not raw:
            continue
        if _port_matches(raw, target) and rule.get("action") == "accept":
            return True
    return False


def _find_accept_rules(items: list[dict], port: int) -> list[dict]:
    """挑出目标端口的所有 accept 规则条目。"""
    target = str(port)
    return [it for it in (items or []) if _matches_accept_port(it, target)]


def _extract_accept_uuids(items: list[dict], port: int) -> list[str]:
    """挑出目标端口的 accept 规则 uuid（去重）。

    收集全部匹配项而非只取第一条，是为了能一次清理掉历史遗留的冗余规则
    （早期版本按三链两族创建，同一端口会有多条）。
    """
    uuids: list[str] = []
    seen: set[str] = set()
    for item in _find_accept_rules(items, port):
        uuid = _rule_uuid(item)
        if uuid and uuid not in seen:
            seen.add(uuid)
            uuids.append(uuid)
    return uuids


def _port_matches(rule_port: str, target: str) -> bool:
    """判断规则里的端口表达是否覆盖目标端口。

    支持单端口（8080）、端口段（8000-8100）、逗号分隔（80,443）。
    """
    if not rule_port:
        return False
    try:
        want = int(target)
    except ValueError:
        return rule_port == target

    for chunk in rule_port.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk:
            lo_s, _, hi_s = chunk.partition("-")
            try:
                if int(lo_s.strip()) <= want <= int(hi_s.strip()):
                    return True
            except ValueError:
                continue
        else:
            try:
                if int(chunk) == want:
                    return True
            except ValueError:
                continue
    return False


async def _search_rules_v2(context: dict, port: int) -> list[dict] | None:
    """搜索规则清单。查询失败返回 None（与「确实没有规则」区分开）。"""
    scopes = _build_scopes(context["provider"], context["families"])
    if not scopes:
        logger.warning(f"[防火墙] 未识别的防火墙后端: {context['provider'] or '空'}")
        return None

    code, payload = await _call_api("POST", "/api/v2/hosts/firewall/rules/search", {
        "page": 1, "pageSize": 200, "scopes": scopes, "info": str(port),
    })
    if code != 200 or not isinstance(payload, dict) or payload.get("code") != 200:
        logger.warning(f"[防火墙] 规则查询失败: HTTP {code} {str(payload)[:200]}")
        return None
    return (payload.get("data") or {}).get("items") or []


async def _open_port_v2(context: dict, port: int, project_name: str) -> bool:
    """新版：创建一条放行规则（异步任务）。

    刻意只创建单条规则：1Panel 的新建接口固定把规则落在 1PANEL_BASIC 链、
    单个地址族上。早期实现按「三链 × 两族」批量创建，会在防火墙上留下
    6 条重复规则（用户在面板上看到一屏冗余条目）。
    """
    scope = _build_create_scope(context["provider"])
    if not scope:
        logger.warning(f"[防火墙] 未识别的防火墙后端: {context['provider'] or '空'}")
        return False

    items = [{
        "rule": {
            "scope": scope,
            "protocol": "tcp",
            "destinationPort": str(port),
            "action": "accept",
            "description": project_name,
        },
        "sourceKind": "user",
    }]

    code, payload = await _call_api("POST", "/api/v2/hosts/firewall/rules", {"items": items})
    if code != 200 or not isinstance(payload, dict) or payload.get("code") != 200:
        logger.warning(f"[防火墙] 放行端口 {port} 失败: HTTP {code} {str(payload)[:200]}")
        return False

    data = payload.get("data") or {}
    succeeded = data.get("succeeded") or 0
    failed = data.get("failed") or 0
    task_id = data.get("taskID") or ""

    # 异步执行时 succeeded 可能为 0 且 queued=true，只要没有明确失败即视为已提交
    if failed and not succeeded:
        logger.warning(f"[防火墙] 放行端口 {port} 被拒绝: {str(data.get('errors'))[:200]}")
        return False

    logger.info(
        f"[防火墙] 端口 {port} 已提交放行 (后端={context['provider']}, "
        f"task={task_id or '无'}, 成功={succeeded}, 失败={failed})"
    )
    return True


async def _close_port_v2(context: dict, port: int) -> bool:
    """新版：按 uuid 批量删除规则（异步任务）。"""
    items = await _search_rules_v2(context, port)
    if items is None:
        return False

    uuids = _extract_accept_uuids(items, port)
    if not uuids:
        return False

    code, payload = await _call_api("POST", "/api/v2/hosts/firewall/rules/delete", {"uuids": uuids})
    if code != 200 or not isinstance(payload, dict) or payload.get("code") != 200:
        logger.warning(f"[防火墙] 移除端口 {port} 失败: HTTP {code} {str(payload)[:200]}")
        return False

    data = payload.get("data") or {}
    failed = data.get("failed") or 0
    if failed and not (data.get("succeeded") or 0):
        logger.warning(f"[防火墙] 移除端口 {port} 被拒绝: {str(data.get('errors'))[:200]}")
        return False

    logger.info(f"[防火墙] 端口 {port} 规则已提交移除 (共 {len(uuids)} 条)")
    return True


# ==================== 旧版（端口专用接口） ====================


async def _check_port_v1(port: int) -> bool:
    code, resp = await _call_api("POST", "/api/v2/hosts/firewall/search", {
        "page": 1, "pageSize": 100, "type": "port", "info": str(port),
    })
    if code != 200 or not isinstance(resp, dict) or resp.get("code") != 200:
        return False
    items = ((resp.get("data") or {}).get("items")) or []
    for item in items:
        if item.get("port") == str(port) and item.get("strategy") == "accept":
            return True
    return False


async def _open_port_v1(port: int, project_name: str) -> bool:
    code, resp = await _call_api("POST", "/api/v2/hosts/firewall/port", {
        "operation": "add",
        "port": str(port),
        "protocol": "tcp",
        "strategy": "accept",
        "description": project_name,
    })
    if code == 200 and isinstance(resp, dict) and resp.get("code") == 200:
        logger.info(f"[防火墙] 端口 {port} 已通过 1Panel 开放 (项目: {project_name})")
        return True
    logger.warning(f"[防火墙] 开放端口 {port} 失败: HTTP {code} {str(resp)[:200]}")
    return False


async def _close_port_v1(port: int) -> bool:
    code, resp = await _call_api("POST", "/api/v2/hosts/firewall/port", {
        "operation": "remove",
        "port": str(port),
        "protocol": "tcp",
        "strategy": "accept",
    })
    if code == 200 and isinstance(resp, dict) and resp.get("code") == 200:
        logger.info(f"[防火墙] 端口 {port} 已通过 1Panel 移除")
        return True
    logger.warning(f"[防火墙] 移除端口 {port} 失败: HTTP {code} {str(resp)[:200]}")
    return False


# ==================== 对外接口 ====================


async def test_connection(config: dict) -> tuple[bool, str]:
    """测试 1Panel API 连接。使用传入的临时配置。"""
    api_key = config.get("api_key", "")
    if not api_key:
        return False, "API Key 不能为空"

    base = config.get("base_url", "http://127.0.0.1:55555").rstrip("/")
    headers = _make_sign_headers(api_key)
    loop = asyncio.get_event_loop()

    async def _probe(method: str, path: str, data: dict | None = None) -> tuple[int, dict]:
        url = f"{base}{path}"
        body = json.dumps(data).encode("utf-8") if data is not None else None

        def _sync():
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))

        try:
            return await loop.run_in_executor(None, _sync)
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8"))
            except Exception:
                return e.code, {}
        except Exception as e:
            return 0, {"message": str(e)[:200]}

    # 新版：settings 可同时确认连通性与防火墙后端
    code, payload = await _probe("GET", "/api/v2/hosts/firewall/settings")
    if code == 200 and isinstance(payload, dict) and payload.get("code") == 200:
        info = _parse_backend(payload)
        return True, f"连接成功（新版规则接口，后端 {info['provider'] or '未知'}）"

    # 旧版：用端口规则查询确认
    code, payload = await _probe("POST", "/api/v2/hosts/firewall/search", {
        "page": 1, "pageSize": 1, "type": "port",
    })
    if code == 200 and isinstance(payload, dict) and payload.get("code") == 200:
        return True, "连接成功（旧版端口接口）"

    if code == 0:
        return False, (payload or {}).get("message", "无法连接 1Panel API")
    message = (payload or {}).get("message") or str(payload)[:100]
    return False, f"HTTP {code}: {message}"


async def check_port(port: int) -> bool:
    """检查指定端口是否已有 ACCEPT 规则。

    判定依据是「清单里存在匹配的 accept 条目」，而不是「条目带 uuid」——
    uuid 只出现在 desired 上，观测到的规则可能没有，用 uuid 判定会误报未放行。
    """
    try:
        context = await _load_context()
        if context["flavor"] == "v2":
            items = await _search_rules_v2(context, port)
            if items is None:
                return False
            return bool(_find_accept_rules(items, port))
        return await _check_port_v1(port)
    except Exception as e:
        logger.warning(f"[防火墙] check_port 异常: {e}")
        return False


async def open_port(port: int, project_name: str) -> bool:
    """开放端口（幂等）。"""
    try:
        context = await _load_context()
        if context["flavor"] == "v2":
            items = await _search_rules_v2(context, port)
            if items is not None and _find_accept_rules(items, port):
                logger.info(f"[防火墙] 端口 {port} 已开放，跳过 (项目: {project_name})")
                return True
            return await _open_port_v2(context, port, project_name)

        if await _check_port_v1(port):
            logger.info(f"[防火墙] 端口 {port} 已开放，跳过 (项目: {project_name})")
            return True
        return await _open_port_v1(port, project_name)
    except Exception as e:
        logger.warning(f"[防火墙] 开放端口 {port} 异常: {e}")
        return False


async def close_port(port: int) -> bool:
    """关闭端口规则（幂等）。"""
    try:
        context = await _load_context()
        if context["flavor"] == "v2":
            return await _close_port_v2(context, port)
        return await _close_port_v1(port)
    except Exception as e:
        logger.warning(f"[防火墙] 移除端口 {port} 异常: {e}")
        return False
