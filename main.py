import asyncio
import hashlib
from datetime import datetime
import re
import shlex
import time
from typing import Dict, List, Optional, Tuple

import httpx
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register

STEAMID64_BASE = 76561197960265728
STEAMID64_BASE_HEX = 0x110000100000000

PROFILE_ID_RE = re.compile(r"steamcommunity\.com/profiles/(\d{17})", re.I)
VANITY_ID_RE = re.compile(r"steamcommunity\.com/id/([^/]+)/?", re.I)
CSGO_FRIEND_CODE_RE = re.compile(r"^[A-Z0-9]{5}-[A-Z0-9]{4}$")
PERSONA_STATE_TEXT = {
    0: "离线",
    1: "在线",
    2: "忙碌",
    3: "离开",
    4: "打盹",
    5: "想交易",
    6: "想玩",
}


@register(
    "astrbot_plugin_steamwatch",
    "Chinachani",
    "通过astrbot视奸你的steam好友！",
    "1.1.3",
    "https://github.com/Chinachani/astrbot_plugin_steamwatch",
)
class SteamWatchPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._normalize_notify_config()
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._poll_loop())
        self._last_state: Dict[str, Tuple[bool, Optional[str]]] = {}
        self._session_start: Dict[str, float] = {}

    # ------------------------
    # Short command入口
    # ------------------------
    @filter.command("sw")
    async def short_cmd(self, event: AstrMessageEvent, args: str = ""):
        """简化指令入口（/sw）"""
        debug_log = bool(self.config.get("debug_log", False))
        raw_text = self._get_event_text(event)
        extracted = self._extract_args_from_event(event, "sw")
        if not args or (extracted and len(extracted) > len(args)):
            args = extracted
        if debug_log:
            logger.info("steamwatch sw raw: %s", raw_text or "<empty>")
            logger.info("steamwatch sw args extracted: %s", args or "<empty>")
        tokens = self._split_args(args)
        if not tokens:
            async for item in self._menu_text(event):
                yield item
            return

        action = tokens[0].lower()
        rest = tokens[1:]

        if action in {"menu", "help"}:
            async for item in self._menu_text(event):
                yield item
            return
        if action in {"add"}:
            async for item in self._cmd_add(event, rest):
                yield item
            return
        if action in {"del", "rm", "remove"}:
            async for item in self._cmd_remove(event, rest):
                yield item
            return
        if action in {"list", "ls"}:
            async for item in self._cmd_list(event):
                yield item
            return
        if action in {"interval", "int"}:
            async for item in self._cmd_interval(event, rest):
                yield item
            return
        if action in {"sub", "subscribe"}:
            async for item in self._cmd_subscribe(event):
                yield item
            return
        if action in {"subinfo", "sub_info"}:
            async for item in self._cmd_subinfo(event):
                yield item
            return
        if action in {"groupinfo", "group_info"}:
            async for item in self._cmd_groupinfo(event, rest):
                yield item
            return
        if action in {"subclean", "sub_clean"}:
            async for item in self._cmd_subclean(event):
                yield item
            return
        if action in {"unsub", "unsubscribe"}:
            async for item in self._cmd_unsubscribe(event):
                yield item
            return
        if action in {"resolve"}:
            async for item in self._cmd_resolve(event, rest):
                yield item
            return
        if action in {"query", "q"}:
            async for item in self._cmd_query(event, rest):
                yield item
            return
        if action in {"status"}:
            async for item in self._cmd_status(event, rest):
                yield item
            return
        if action in {"info", "i"}:
            async for item in self._cmd_info(event, rest):
                yield item
            return
        if action in {"test"}:
            async for item in self._cmd_test(event):
                yield item
            return
        if action in {"proxytest", "proxy"}:
            async for item in self._cmd_proxytest(event):
                yield item
            return
        if action in {"bind"}:
            async for item in self._cmd_bind(event, rest):
                yield item
            return
        if action in {"unbind"}:
            async for item in self._cmd_unbind(event, rest):
                yield item
            return
        if action in {"me"}:
            async for item in self._cmd_me(event):
                yield item
            return

        yield event.plain_result("未知子命令。输入 /sw menu 查看菜单。")

    # ------------------------
    # 原始命令（兼容）
    # ------------------------
    @filter.command("steamwatch_add")
    async def add_watch(self, event: AstrMessageEvent, target: str = ""):
        async for item in self._cmd_add(event, [target] if target else []):
            yield item

    @filter.command("steamwatch_remove")
    async def remove_watch(self, event: AstrMessageEvent, target: str = ""):
        async for item in self._cmd_remove(event, [target] if target else []):
            yield item

    @filter.command("steamwatch_list")
    async def list_watch(self, event: AstrMessageEvent):
        async for item in self._cmd_list(event):
            yield item

    @filter.command("steamwatch_interval")
    async def set_interval(self, event: AstrMessageEvent, seconds: str = ""):
        async for item in self._cmd_interval(event, [seconds] if seconds else []):
            yield item

    @filter.command("steamwatch_subscribe")
    async def subscribe(self, event: AstrMessageEvent):
        async for item in self._cmd_subscribe(event):
            yield item

    @filter.command("steamwatch_unsubscribe")
    async def unsubscribe(self, event: AstrMessageEvent):
        async for item in self._cmd_unsubscribe(event):
            yield item

    @filter.command("steamwatch_subinfo")
    async def subinfo(self, event: AstrMessageEvent):
        async for item in self._cmd_subinfo(event):
            yield item

    @filter.command("steamwatch_groupinfo")
    async def groupinfo(self, event: AstrMessageEvent, group: str = ""):
        async for item in self._cmd_groupinfo(event, [group] if group else []):
            yield item

    @filter.command("steamwatch_resolve")
    async def resolve_friend_code(self, event: AstrMessageEvent, target: str = ""):
        async for item in self._cmd_resolve(event, [target] if target else []):
            yield item

    @filter.command("steamwatch_menu")
    async def menu(self, event: AstrMessageEvent):
        async for item in self._full_menu_text(event):
            yield item

    @filter.command("steamwatch_query")
    async def query_once(self, event: AstrMessageEvent, target: str = ""):
        async for item in self._cmd_query(event, [target] if target else []):
            yield item

    @filter.command("steamwatch_info")
    async def info(self, event: AstrMessageEvent, target: str = ""):
        async for item in self._cmd_info(event, [target] if target else []):
            yield item

    @filter.command("steamwatch_test")
    async def test_access(self, event: AstrMessageEvent):
        async for item in self._cmd_test(event):
            yield item

    @filter.command("steamwatch_proxytest")
    async def proxy_test(self, event: AstrMessageEvent):
        async for item in self._cmd_proxytest(event):
            yield item

    @filter.command("steamwatch_status")
    async def push_status(self, event: AstrMessageEvent, target: str = ""):
        async for item in self._cmd_status(event, [target] if target else []):
            yield item

    @filter.command("steamwatch_bind")
    async def bind_user(self, event: AstrMessageEvent, target: str = ""):
        async for item in self._cmd_bind(event, [target] if target else []):
            yield item

    @filter.command("steamwatch_unbind")
    async def unbind_user(self, event: AstrMessageEvent, user_id: str = ""):
        async for item in self._cmd_unbind(event, [user_id] if user_id else []):
            yield item

    @filter.command("steamwatch_me")
    async def me(self, event: AstrMessageEvent):
        async for item in self._cmd_me(event):
            yield item

    # ------------------------
    # Command handlers
    # ------------------------
    def _require_admin(self, event: AstrMessageEvent) -> Optional[str]:
        admins = [str(x) for x in self.config.get("admin_user_ids", [])]
        if not admins:
            return None
        user_key = self._get_user_key(event)
        if user_key in admins:
            return None
        return "权限不足：该指令仅管理员可用。"

    async def _cmd_add(self, event: AstrMessageEvent, args: List[str]):
        deny = self._require_admin(event)
        if deny:
            yield event.plain_result(deny)
            return
        raw_text = self._get_event_text(event)
        target = args[0] if args else ""

        # 支持 /sw add @123456 或 /sw add [At:123456] 或 CQ at
        bind_user = _extract_at_user_id(target) or _extract_at_user_id_from_text(raw_text)

        # 支持 /sw add @昵称（从绑定昵称反查）
        if not bind_user and target.startswith("@") and len(target) > 1:
            name = target[1:]
            meta = self._get_binding_meta()
            matches = [uid for uid, nick in meta.items() if nick == name]
            if len(matches) == 1:
                bind_user = matches[0]

        if bind_user:
            bindings = self._get_bindings()
            steamid = bindings.get(bind_user)
            if not steamid:
                yield event.plain_result(f"未找到用户 {bind_user} 的绑定记录。")
                return
            error = None
        else:
            if not target:
                yield event.plain_result("用法：/sw add <steamid64|profile_url|vanity|friend_code|me|@qq>")
                return
            steamid, error = await self._resolve_to_steamid64(event, target)
        if not steamid:
            yield event.plain_result(error or "无法解析 SteamID。")
            return

        steamids = self._get_steamids()
        if steamid in steamids:
            yield event.plain_result(f"{steamid} 已在监控列表中。")
            return

        steamids.append(steamid)
        self._set_steamids(steamids)
        group = args[1] if len(args) > 1 else ""
        if group:
            groups = self._get_steamid_groups()
            groups[steamid] = group
            self._set_steamid_groups(groups)
            yield event.plain_result(f"已添加 {steamid} 到监控列表。分组：{group}")
        else:
            yield event.plain_result(f"已添加 {steamid} 到监控列表。")

    async def _cmd_remove(self, event: AstrMessageEvent, args: List[str]):
        deny = self._require_admin(event)
        if deny:
            yield event.plain_result(deny)
            return
        target = self._extract_target_or_at(event, args)
        if not target:
            yield event.plain_result("用法：/sw remove <steamid64|profile_url|vanity|friend_code|me>")
            return

        steamid, error = await self._resolve_to_steamid64(event, target)
        if not steamid:
            yield event.plain_result(error or "无法解析 SteamID。")
            return

        steamids = self._get_steamids()
        if steamid not in steamids:
            yield event.plain_result(f"{steamid} 不在监控列表中。")
            return

        steamids.remove(steamid)
        self._set_steamids(steamids)
        self._last_state.pop(steamid, None)
        self._session_start.pop(steamid, None)
        groups = self._get_steamid_groups()
        if steamid in groups:
            groups.pop(steamid, None)
            self._set_steamid_groups(groups)
        yield event.plain_result(f"已从监控列表移除 {steamid}。")

    async def _cmd_list(self, event: AstrMessageEvent):
        deny = self._require_admin(event)
        if deny:
            yield event.plain_result(deny)
            return
        steamids = self._get_steamids()
        if not steamids:
            yield event.plain_result("监控列表为空。")
            return
        bindings = self._get_bindings()
        meta = self._get_binding_meta()
        groups = self._get_steamid_groups()
        lines = ["监控列表："]
        for sid in steamids:
            users = [u for u, s in bindings.items() if s == sid]
            group = groups.get(sid, "")
            if users:
                # 仅展示第一个绑定用户
                uid = users[0]
                name = meta.get(uid, "").strip()
                if name:
                    suffix = f"{name}（{uid}）"
                else:
                    suffix = f"QQ: {uid}"
                if group:
                    lines.append(f"- {sid}  ({suffix}，分组：{group})")
                else:
                    lines.append(f"- {sid}  ({suffix})")
            else:
                if group:
                    lines.append(f"- {sid}  (分组：{group})")
                else:
                    lines.append(f"- {sid}")
        yield event.plain_result("\n".join(lines))

    async def _cmd_interval(self, event: AstrMessageEvent, args: List[str]):
        deny = self._require_admin(event)
        if deny:
            yield event.plain_result(deny)
            return
        if not args or not args[0].isdigit():
            yield event.plain_result("用法：/sw interval <seconds>")
            return
        value = int(args[0])
        if value < 30:
            yield event.plain_result("轮询间隔需 >= 30 秒。")
            return
        self.config["poll_interval_sec"] = value
        self.config.save_config()
        yield event.plain_result(f"轮询间隔已设置为 {value} 秒。")

    async def _cmd_subscribe(self, event: AstrMessageEvent):
        deny = self._require_admin(event)
        if deny:
            yield event.plain_result(deny)
            return
        target = event.unified_msg_origin
        if self._group_enabled():
            group = self._extract_group_arg(event, "sub")
            if group:
                groups = self._get_notify_groups()
                targets = groups.get(group, [])
                if target in targets:
                    yield event.plain_result(f"当前会话已订阅分组：{group}")
                    return
                targets.append(target)
                groups[group] = targets
                self._set_notify_groups(groups)
                yield event.plain_result(f"已订阅分组：{group}")
                return
        targets = self._get_notify_targets()
        if target in targets:
            yield event.plain_result("当前会话已订阅通知。")
            return
        targets.append(target)
        self._set_notify_targets(targets)
        yield event.plain_result("已订阅当前会话通知。")

    async def _cmd_unsubscribe(self, event: AstrMessageEvent):
        deny = self._require_admin(event)
        if deny:
            yield event.plain_result(deny)
            return
        target = event.unified_msg_origin
        if self._group_enabled():
            group = self._extract_group_arg(event, "unsub")
            if group:
                groups = self._get_notify_groups()
                targets = groups.get(group, [])
                if target not in targets:
                    yield event.plain_result(f"当前会话未订阅分组：{group}")
                    return
                targets = [t for t in targets if t != target]
                if targets:
                    groups[group] = targets
                else:
                    groups.pop(group, None)
                self._set_notify_groups(groups)
                yield event.plain_result(f"已取消订阅分组：{group}")
                return
        targets = self._get_notify_targets()
        if target not in targets:
            yield event.plain_result("当前会话未订阅通知。")
            return
        targets.remove(target)
        self._set_notify_targets(targets)
        yield event.plain_result("已取消当前会话的通知订阅。")

    async def _cmd_subinfo(self, event: AstrMessageEvent):
        deny = self._require_admin(event)
        if deny:
            yield event.plain_result(deny)
            return
        target = event.unified_msg_origin
        lines = ["当前会话订阅信息："]
        if self._group_enabled():
            groups = self._get_notify_groups()
            matched = [g for g, targets in groups.items() if target in targets]
            if matched:
                lines.append(f"- 分组订阅：{', '.join(matched)}")
            else:
                lines.append("- 分组订阅：无")
        targets = self._get_notify_targets()
        lines.append("- 全局订阅：已订阅" if target in targets else "- 全局订阅：未订阅")
        yield event.plain_result("\n".join(lines))

    async def _cmd_groupinfo(self, event: AstrMessageEvent, args: List[str]):
        deny = self._require_admin(event)
        if deny:
            yield event.plain_result(deny)
            return
        if not self._group_enabled():
            yield event.plain_result("未启用分群订阅，请先开启 notify_group_enabled。")
            return
        groups = self._get_notify_groups()
        if not args:
            if not groups:
                yield event.plain_result("暂无分组订阅记录。")
                return
            lines = ["分组订阅列表："]
            for name, targets in groups.items():
                lines.append(f"- {name}（{len(targets)} 个会话）")
            yield event.plain_result("\n".join(lines))
            return
        name = args[0]
        targets = groups.get(name, [])
        if not targets:
            yield event.plain_result("该分组没有任何订阅会话。")
            return
        lines = [f"分组 {name} 订阅会话："]
        lines.extend(f"- {t}" for t in targets)
        yield event.plain_result("\n".join(lines))

    async def _cmd_subclean(self, event: AstrMessageEvent):
        deny = self._require_admin(event)
        if deny:
            yield event.plain_result(deny)
            return
        before_targets = list(self.config.get("notify_targets", []))
        before_groups = list(self.config.get("notify_groups", []))
        self._normalize_notify_config()
        after_targets = list(self.config.get("notify_targets", []))
        after_groups = list(self.config.get("notify_groups", []))
        lines = ["已执行订阅清理："]
        lines.append(f"- notify_targets: {len(before_targets)} -> {len(after_targets)}")
        lines.append(f"- notify_groups: {len(before_groups)} -> {len(after_groups)}")
        yield event.plain_result("\n".join(lines))

    async def _cmd_resolve(self, event: AstrMessageEvent, args: List[str]):
        target = self._extract_target_or_at(event, args)
        if not target:
            yield event.plain_result("用法：/sw resolve <steamid64|profile_url|vanity|friend_code|me>")
            return
        steamid, error = await self._resolve_to_steamid64(event, target)
        if steamid:
            friend_code = _account_id_from_steamid64(int(steamid))
            lines = [f"SteamID64：{steamid}", f"好友码：{friend_code}"]
            if bool(self.config.get("show_csgo_friend_code", False)):
                lines.append(f"CS:GO 好友码：{_encode_csgo_friend_code(int(steamid))}")
            yield event.plain_result("\n".join(lines))
        else:
            yield event.plain_result(error or "无法解析 SteamID。")

    async def _cmd_query(self, event: AstrMessageEvent, args: List[str]):
        target = self._extract_target_or_at(event, args)
        if not target:
            yield event.plain_result("用法：/sw query <steamid64|profile_url|vanity|friend_code|me>")
            return
        steamid, error = await self._resolve_to_steamid64(event, target)
        if not steamid:
            yield event.plain_result(error or "无法解析 SteamID。")
            return
        api_key = self.config.get("steam_web_api_key", "")
        if not api_key:
            yield event.plain_result("未配置 Steam Web API Key。")
            return
        summaries = await self._fetch_player_summaries(api_key, [steamid])
        if not summaries:
            yield event.plain_result("未获取到该 SteamID 信息。")
            return
        player = summaries.get(steamid)
        if not player:
            yield event.plain_result("未获取到该 SteamID 信息。")
            return
        name = player.get("personaname", steamid)
        playing = "gameid" in player or "gameextrainfo" in player
        game_name = player.get("gameextrainfo")
        if playing:
            yield event.plain_result(f"{name} 正在玩 {game_name or '某个游戏'}！")
        else:
            yield event.plain_result(f"{name} 当前未在游戏中。")

    async def _cmd_info(self, event: AstrMessageEvent, args: List[str]):
        target = self._extract_target_or_at(event, args)
        if not target:
            yield event.plain_result("用法：/sw info <steamid64|profile_url|vanity|friend_code|me>")
            return
        steamid, error = await self._resolve_to_steamid64(event, target)
        if not steamid:
            yield event.plain_result(error or "无法解析 SteamID。")
            return
        api_key = self.config.get("steam_web_api_key", "")
        if not api_key:
            yield event.plain_result("未配置 Steam Web API Key。")
            return
        summaries = await self._fetch_player_summaries(api_key, [steamid])
        if not summaries:
            yield event.plain_result("未获取到该 SteamID 信息。")
            return
        player = summaries.get(steamid)
        if not player:
            yield event.plain_result("未获取到该 SteamID 信息。")
            return
        name = player.get("personaname", steamid)
        playing = "gameid" in player or "gameextrainfo" in player
        game_name = player.get("gameextrainfo")
        appid = player.get("gameid")
        friend_code = _account_id_from_steamid64(int(steamid))
        lines = [f"昵称：{name}", f"好友码：{friend_code}", f"SteamID64：{steamid}"]
        persona_state = PERSONA_STATE_TEXT.get(player.get("personastate"))
        if persona_state:
            lines.append(f"状态：{persona_state}")
        realname = player.get("realname")
        if realname:
            lines.append(f"实名：{realname}")
        profile_url = player.get("profileurl")
        if profile_url:
            lines.append(f"主页：{profile_url}")
        last_logoff = _format_ts(player.get("lastlogoff"))
        if last_logoff:
            lines.append(f"上次离线：{last_logoff}")
        created = _format_ts(player.get("timecreated"))
        if created:
            lines.append(f"注册时间：{created}")
        country = player.get("loccountrycode")
        state = player.get("locstatecode")
        city = player.get("loccityid")
        if country or state or city:
            parts = [str(x) for x in (country, state, city) if x]
            lines.append(f"地区：{'-'.join(parts)}")
        if playing:
            lines.append(f"正在玩：{game_name or '某个游戏'} (appid: {appid})！")
        else:
            lines.append("当前未在游戏中。")
        if appid:
            playtime = await self._fetch_game_playtime(api_key, steamid, int(appid))
            if playtime is not None:
                lines.append(f"游戏总时长：{playtime} 小时")
            achv = await self._fetch_achievements(api_key, steamid, int(appid))
            if achv:
                lines.append(f"成就进度：{achv}")
        yield event.plain_result("\n".join(lines))

    async def _cmd_status(self, event: AstrMessageEvent, args: List[str]):
        target = self._extract_target_or_at(event, args)
        if not target:
            yield event.plain_result("用法：/sw status <steamid64|profile_url|vanity|friend_code|me>")
            return
        steamid, error = await self._resolve_to_steamid64(event, target)
        if not steamid:
            yield event.plain_result(error or "无法解析 SteamID。")
            return
        api_key = self.config.get("steam_web_api_key", "")
        if not api_key:
            yield event.plain_result("未配置 Steam Web API Key。")
            return
        summaries = await self._fetch_player_summaries(api_key, [steamid])
        if not summaries:
            yield event.plain_result("未获取到该 SteamID 信息。")
            return
        player = summaries.get(steamid)
        if not player:
            yield event.plain_result("未获取到该 SteamID 信息。")
            return
        name = player.get("personaname", steamid)
        playing = "gameid" in player or "gameextrainfo" in player
        game_name = player.get("gameextrainfo")
        if playing:
            await self._notify_by_steamid(steamid, f"{name} 正在玩 {game_name or '某个游戏'}！")
        else:
            await self._notify_by_steamid(steamid, f"{name} 当前未在游戏中。")
        yield event.plain_result("已推送当前状态。")

    async def _cmd_test(self, event: AstrMessageEvent):
        timeout_sec = int(self.config.get("request_timeout_sec", 10))
        results = []
        proxy_url = self._get_proxy_url()
        async with self._create_http_client(timeout_sec, follow_redirects=True) as client:
            try:
                resp = await client.get("https://steamcommunity.com")
                results.append(f"steamcommunity.com: {resp.status_code}")
            except Exception as exc:
                results.append(f"steamcommunity.com: 失败 ({type(exc).__name__})")
            try:
                resp = await client.get("https://api.steampowered.com/ISteamWebAPIUtil/GetSupportedAPIList/v1/")
                results.append(f"api.steampowered.com: {resp.status_code}")
            except Exception as exc:
                results.append(f"api.steampowered.com: 失败 ({type(exc).__name__})")
        results.append(f"代理：{proxy_url or '未配置'}")
        yield event.plain_result("连通性测试结果：\n" + "\n".join(results))

    async def _cmd_proxytest(self, event: AstrMessageEvent):
        proxy_url = self._get_proxy_url()
        if not proxy_url:
            yield event.plain_result("未配置代理（proxy_url）。")
            return
        timeout_sec = int(self.config.get("request_timeout_sec", 10))
        results = []
        try:
            async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
                resp = await client.get("https://api.ipify.org?format=json")
                results.append(f"直连IP：{resp.json().get('ip', '未知')}")
        except Exception as exc:
            results.append(f"直连IP：失败 ({type(exc).__name__})")
        try:
            async with self._create_http_client(timeout_sec, follow_redirects=True) as client:
                resp = await client.get("https://api.ipify.org?format=json")
                results.append(f"代理IP：{resp.json().get('ip', '未知')}")
        except Exception as exc:
            results.append(f"代理IP：失败 ({type(exc).__name__})")
        results.append(f"代理地址：{proxy_url}")
        yield event.plain_result("代理测试结果：\n" + "\n".join(results))

    async def _cmd_bind(self, event: AstrMessageEvent, args: List[str]):
        if not args:
            yield event.plain_result("用法：/sw bind <steamid64|profile_url|vanity|friend_code>")
            return
        steamid, error = await self._resolve_to_steamid64(event, args[0])
        if not steamid:
            yield event.plain_result(error or "无法解析 SteamID。")
            return
        user_key = self._get_user_key(event)
        bindings = self._get_bindings()
        # 防止重复绑定：同一用户或同一SteamID
        if user_key in bindings:
            yield event.plain_result("你已绑定过 SteamID，如需更换请先 /sw unbind。")
            return
        if steamid in bindings.values():
            yield event.plain_result("该 SteamID 已被其他用户绑定。")
            return
        bindings[user_key] = steamid
        self._set_bindings(bindings)
        meta = self._get_binding_meta()
        try:
            nickname = event.get_sender_name()
        except Exception:
            nickname = ""
        if nickname:
            meta[user_key] = nickname
            self._set_binding_meta(meta)
        friend_code = _account_id_from_steamid64(int(steamid))
        csgo_code = _encode_csgo_friend_code(int(steamid))
        extra = ""
        if bool(self.config.get("show_csgo_friend_code", False)):
            extra = f"（CS:GO 好友码：{csgo_code}）"
        yield event.plain_result(f"已绑定：{user_key} -> {friend_code}（64ID：{steamid}）{extra}")

    async def _cmd_unbind(self, event: AstrMessageEvent, args: List[str]):
        user_key = self._get_user_key(event)
        target_user = user_key
        if args:
            deny = self._require_admin(event)
            if deny:
                yield event.plain_result(deny)
                return
            target_user = args[0]
        bindings = self._get_bindings()
        if target_user not in bindings:
            yield event.plain_result("未找到绑定记录。")
            return
        bindings.pop(target_user, None)
        self._set_bindings(bindings)
        yield event.plain_result("已解除绑定。")

    async def _cmd_me(self, event: AstrMessageEvent):
        user_key = self._get_user_key(event)
        bindings = self._get_bindings()
        steamid = bindings.get(user_key)
        if not steamid:
            yield event.plain_result("你还未绑定 SteamID。使用 /sw bind 进行绑定。")
            return
        friend_code = _account_id_from_steamid64(int(steamid))
        csgo_code = _encode_csgo_friend_code(int(steamid))
        extra = ""
        if bool(self.config.get("show_csgo_friend_code", False)):
            extra = f"（CS:GO 好友码：{csgo_code}）"
        yield event.plain_result(f"当前绑定：{friend_code}（64ID：{steamid}）{extra}")

    async def _menu_text(self, event: AstrMessageEvent):
        lines = [
            "========== SteamWatch 菜单 ==========",
            "简化指令：/sw <子命令>",
            "",
            "管理：/sw add|remove|list|interval",
            "通知：/sw sub|unsub [group] | subinfo | groupinfo | subclean",
            "查询：/sw query|status|info|resolve",
            "网络：/sw test|proxytest",
            "绑定：/sw bind|unbind|me",
            "",
            "示例：/sw add 7656119xxxxxxxxxx",
            "完整命令：/steamwatch_menu",
        ]
        yield event.plain_result("\n".join(lines))

    async def _full_menu_text(self, event: AstrMessageEvent):
        lines = [
            "========== SteamWatch 完整菜单 ==========",
            "简化入口：/sw",
            "",
            "管理（管理员）：",
            "/steamwatch_add <steamid64|profile_url|vanity|friend_code|me>",
            "/steamwatch_remove <steamid64|profile_url|vanity|friend_code|me>",
            "/steamwatch_list",
            "/steamwatch_interval <seconds>",
            "/steamwatch_subscribe [group]",
            "/steamwatch_unsubscribe [group]",
            "/steamwatch_subinfo",
            "/steamwatch_groupinfo [group]",
            "/steamwatch_subclean",
            "",
            "查询：",
            "/steamwatch_query <steamid64|profile_url|vanity|friend_code|me>",
            "/steamwatch_info <steamid64|profile_url|vanity|friend_code|me>",
            "/steamwatch_status <steamid64|profile_url|vanity|friend_code|me>",
            "/steamwatch_resolve <steamid64|profile_url|vanity|friend_code|me>",
            "",
            "绑定：",
            "/steamwatch_bind <steamid64|profile_url|vanity|friend_code>",
            "/steamwatch_unbind [user_id]",
            "/steamwatch_me",
            "",
            "网络：",
            "/steamwatch_test",
            "/steamwatch_proxytest",
            "",
            "菜单：",
            "/steamwatch_menu",
        ]
        yield event.plain_result("\n".join(lines))

    # ------------------------
    # Core logic
    # ------------------------
    async def terminate(self):
        self._stop_event.set()
        if self._task:
            self._task.cancel()

    async def _poll_loop(self):
        while not self._stop_event.is_set():
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("steamwatch poll loop error")
            interval = int(self.config.get("poll_interval_sec", 60))
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue

    async def _poll_once(self):
        steamids = self._get_steamids()
        if not steamids:
            return
        api_key = self.config.get("steam_web_api_key", "")
        if not api_key:
            logger.warning("steam_web_api_key not configured")
            return
        summaries = await self._fetch_player_summaries(api_key, steamids)
        if summaries is None:
            return
        notify_on_stop = bool(self.config.get("notify_on_stop", False))
        for steamid in steamids:
            player = summaries.get(steamid)
            if not player:
                continue
            playing = "gameid" in player or "gameextrainfo" in player
            game_name = player.get("gameextrainfo")
            if steamid not in self._last_state:
                self._last_state[steamid] = (playing, game_name)
                if playing:
                    self._session_start[steamid] = time.time()
                continue
            last_playing, last_game = self._last_state[steamid]
            if playing and not last_playing:
                self._session_start[steamid] = time.time()
                await self._notify_by_steamid(
                    steamid,
                    f"{player.get('personaname', steamid)} 正在玩 {game_name or '某个游戏'}！",
                )
            elif notify_on_stop and last_playing and not playing:
                duration_min = self._consume_session_minutes(steamid)
                taunt = _playtime_taunt(duration_min)
                await self._notify_by_steamid(
                    steamid,
                    f"{player.get('personaname', steamid)} 已停止游戏 {last_game or '某个游戏'}。本次游玩 {duration_min} 分钟，评价：{taunt}",
                )
            self._last_state[steamid] = (playing, game_name)

    async def _fetch_player_summaries(self, api_key: str, steamids: List[str]):
        url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v0002/"
        summaries: Dict[str, dict] = {}
        timeout_sec = int(self.config.get("request_timeout_sec", 10))
        retries = int(self.config.get("request_retries", 2))
        retry_delay = float(self.config.get("request_retry_delay_sec", 2.0))
        debug_log = bool(self.config.get("debug_log", False))
        async with self._create_http_client(timeout_sec) as client:
            for chunk in _chunk_list(steamids, 100):
                params = {
                    "key": api_key,
                    "steamids": ",".join(chunk),
                }
                if debug_log:
                    logger.info(
                        "steamwatch request: url=%s steamids=%s timeout=%s retries=%s proxy=%s",
                        url,
                        params["steamids"],
                        timeout_sec,
                        retries,
                        self._get_proxy_url() or "none",
                    )
                resp = None
                for attempt in range(retries + 1):
                    try:
                        resp = await client.get(url, params=params)
                        resp.raise_for_status()
                        break
                    except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                        if attempt >= retries:
                            logger.warning("steamwatch request failed after %s retries: %s", retries, exc)
                            resp = None
                            break
                        if debug_log:
                            logger.info("steamwatch retry %s/%s after error: %s", attempt + 1, retries, exc)
                        await asyncio.sleep(retry_delay)
                if resp is None:
                    continue
                if debug_log:
                    logger.info("steamwatch response status=%s", resp.status_code)
                data = resp.json()
                players = data.get("response", {}).get("players", [])
                if debug_log:
                    logger.info("steamwatch players=%s", len(players))
                for player in players:
                    sid = player.get("steamid")
                    if sid:
                        summaries[sid] = player
        return summaries

    async def _fetch_game_playtime(self, api_key: str, steamid: str, appid: int) -> Optional[int]:
        url = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
        params = {
            "key": api_key,
            "steamid": steamid,
            "include_appinfo": 0,
            "include_played_free_games": 1,
            "appids_filter[0]": appid,
        }
        try:
            async with self._create_http_client(10) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return None
        games = data.get("response", {}).get("games", [])
        if not games:
            return None
        minutes = games[0].get("playtime_forever", 0)
        return max(0, int(minutes // 60))

    async def _fetch_achievements(self, api_key: str, steamid: str, appid: int) -> Optional[str]:
        url = "https://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/"
        params = {"key": api_key, "steamid": steamid, "appid": appid}
        try:
            async with self._create_http_client(10) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return None
        playerstats = data.get("playerstats", {})
        achievements = playerstats.get("achievements", [])
        if not achievements:
            return None
        total = len(achievements)
        achieved = sum(1 for a in achievements if a.get("achieved") == 1)
        return f"{achieved}/{total}"

    async def _notify(self, text: str):
        targets = self._get_notify_targets()
        if not targets:
            logger.info("No notify targets configured")
            return
        await self._notify_to_targets(text, targets)

    async def _notify_by_steamid(self, steamid: str, text: str):
        if self._group_enabled():
            groups = self._get_notify_groups()
            steamid_groups = self._get_steamid_groups()
            group = steamid_groups.get(steamid, "")
            if group and group in groups and groups[group]:
                await self._notify_to_targets(text, groups[group])
                return
        await self._notify(text)

    async def _notify_to_targets(self, text: str, targets: List[str]):
        message = MessageChain().message(text)
        for target in targets:
            try:
                await self.context.send_message(target, message)
            except Exception:
                logger.exception("Failed to send steamwatch notification")

    # ------------------------
    # Helpers: config/bindings
    # ------------------------
    def _normalize_message_type(self, value: str) -> str:
        text = (value or "").strip()
        lowered = text.lower()
        if lowered in {"group", "groupmessage", "group_message"}:
            return "GroupMessage"
        if lowered in {"friend", "private", "privatemessage", "friendmessage"}:
            return "FriendMessage"
        if lowered in {"other", "othermessage"}:
            return "OtherMessage"
        return text

    def _normalize_target(self, target: str) -> Optional[str]:
        if not target:
            return None
        default_platform = str(self.config.get("default_platform_id", "aiocqhttp")).strip()
        default_msg_type = self._normalize_message_type(
            str(self.config.get("default_message_type", "GroupMessage")).strip()
        )
        parts = target.split(":", 2)
        if len(parts) == 1:
            return f"{default_platform}:{default_msg_type}:{parts[0]}"
        if len(parts) == 2:
            msg_type = self._normalize_message_type(parts[0])
            return f"{default_platform}:{msg_type}:{parts[1]}"
        if len(parts) == 3:
            parts[1] = self._normalize_message_type(parts[1])
            return ":".join(parts)
        return None

    def _normalize_notify_config(self) -> None:
        changed = False
        targets = self._get_notify_targets()
        norm_targets: List[str] = []
        for t in targets:
            normalized = self._normalize_target(str(t).strip())
            if normalized and normalized not in norm_targets:
                norm_targets.append(normalized)
        if norm_targets != targets:
            self.config["notify_targets"] = norm_targets
            changed = True

        groups = self._get_notify_groups()
        norm_groups: Dict[str, List[str]] = {}
        for group, targets in groups.items():
            cleaned: List[str] = []
            for t in targets:
                normalized = self._normalize_target(str(t).strip())
                if normalized and normalized not in cleaned:
                    cleaned.append(normalized)
            if cleaned:
                norm_groups[group] = cleaned
        if norm_groups != groups:
            self._set_notify_groups(norm_groups)
            changed = True

        if changed:
            self.config.save_config()

    def _get_user_key(self, event: AstrMessageEvent) -> str:
        for name in ("get_sender_id", "get_user_id", "get_sender_uid"):
            attr = getattr(event, name, None)
            if callable(attr):
                try:
                    val = attr()
                except TypeError:
                    val = attr
                if val:
                    return str(val)
        for name in ("sender_id", "user_id", "sender"):
            val = getattr(event, name, None)
            if val:
                return str(val)
        try:
            return str(event.get_sender_name())
        except Exception:
            return "unknown"

    def _get_steamids(self) -> List[str]:
        return list(self.config.get("steamids", []))

    def _set_steamids(self, steamids: List[str]):
        self.config["steamids"] = steamids
        self.config.save_config()

    def _get_notify_targets(self) -> List[str]:
        targets = list(self.config.get("notify_targets", []))
        cleaned: List[str] = []
        for t in targets:
            normalized = self._normalize_target(str(t).strip())
            if normalized and normalized not in cleaned:
                cleaned.append(normalized)
        if cleaned != targets:
            self.config["notify_targets"] = cleaned
            self.config.save_config()
        return cleaned

    def _set_notify_targets(self, targets: List[str]):
        cleaned: List[str] = []
        for t in targets:
            normalized = self._normalize_target(str(t).strip())
            if normalized and normalized not in cleaned:
                cleaned.append(normalized)
        self.config["notify_targets"] = cleaned
        self.config.save_config()

    def _get_bindings(self) -> Dict[str, str]:
        raw = list(self.config.get("bindings", []))
        bindings: Dict[str, str] = {}
        for item in raw:
            if not isinstance(item, str) or ":" not in item:
                continue
            user_id, steamid = item.split(":", 1)
            if user_id and steamid:
                bindings[user_id] = steamid
        return bindings

    def _set_bindings(self, bindings: Dict[str, str]):
        items = [f"{user_id}:{steamid}" for user_id, steamid in bindings.items()]
        self.config["bindings"] = items
        self.config.save_config()

    def _get_binding_meta(self) -> Dict[str, str]:
        raw = list(self.config.get("binding_meta", []))
        meta: Dict[str, str] = {}
        for item in raw:
            if not isinstance(item, str) or ":" not in item:
                continue
            user_id, name = item.split(":", 1)
            if user_id and name:
                meta[user_id] = name
        return meta

    def _set_binding_meta(self, meta: Dict[str, str]):
        items = [f"{user_id}:{name}" for user_id, name in meta.items()]
        self.config["binding_meta"] = items
        self.config.save_config()

    def _group_enabled(self) -> bool:
        return bool(self.config.get("notify_group_enabled", False))

    def _get_notify_groups(self) -> Dict[str, List[str]]:
        raw = list(self.config.get("notify_groups", []))
        groups: Dict[str, List[str]] = {}
        for item in raw:
            if not isinstance(item, str) or ":" not in item:
                continue
            group, target = item.split(":", 1)
            if not group or not target:
                continue
            normalized = self._normalize_target(target)
            if not normalized:
                continue
            groups.setdefault(group, [])
            if normalized not in groups[group]:
                groups[group].append(normalized)
        return groups

    def _set_notify_groups(self, groups: Dict[str, List[str]]):
        items: List[str] = []
        for group, targets in groups.items():
            for target in targets:
                normalized = self._normalize_target(str(target).strip())
                if normalized:
                    items.append(f"{group}:{normalized}")
        self.config["notify_groups"] = items
        self.config.save_config()

    def _get_steamid_groups(self) -> Dict[str, str]:
        raw = list(self.config.get("steamid_groups", []))
        groups: Dict[str, str] = {}
        for item in raw:
            if not isinstance(item, str) or ":" not in item:
                continue
            sid, group = item.split(":", 1)
            if sid and group:
                groups[sid] = group
        return groups

    def _set_steamid_groups(self, groups: Dict[str, str]):
        items = [f"{sid}:{group}" for sid, group in groups.items()]
        self.config["steamid_groups"] = items
        self.config.save_config()

    def _split_args(self, text: str) -> List[str]:
        if not text:
            return []
        try:
            return shlex.split(text)
        except ValueError:
            return text.split()

    def _get_event_text(self, event: AstrMessageEvent) -> str:
        """Best-effort plain text extraction."""
        candidates = [
            "message_str",
            "plain_text",
            "raw_message",
            "message",
            "text",
            "message_chain",
        ]
        for name in candidates:
            val = getattr(event, name, None)
            if val is None:
                continue
            if callable(val):
                try:
                    val = val()
                except Exception:
                    continue
            # Try common methods on message-like objects
            for meth in ("get_plain_text", "to_plain_text"):
                func = getattr(val, meth, None)
                if callable(func):
                    try:
                        text = func()
                    except Exception:
                        text = ""
                    if isinstance(text, str) and text.strip():
                        return text.strip()
            if isinstance(val, str) and val.strip():
                return val.strip()
            try:
                val_str = str(val).strip()
            except Exception:
                val_str = ""
            if val_str:
                return val_str
        return ""

    def _extract_args_from_event(self, event: AstrMessageEvent, cmd_name: str) -> str:
        """Try to extract raw args from event text when framework doesn't pass args."""
        text = self._get_event_text(event)
        if not text:
            return ""
        match = re.search(rf"(?:^|\s)/?{re.escape(cmd_name)}(?:@[\w\-]+)?\b(.*)$", text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return ""

    def _extract_group_arg(self, event: AstrMessageEvent, action: str) -> str:
        text = self._get_event_text(event)
        parts = self._split_args(text)
        if not parts:
            return ""
        cmd0 = parts[0].lstrip("/").lower()
        action = action.lower()
        # /sw sub <group>
        if cmd0 == "sw":
            if len(parts) >= 3 and parts[1].lower() in {"sub", "subscribe", "unsub", "unsubscribe"}:
                return parts[2]
            return ""
        # /steamwatch_subscribe <group>
        if cmd0 in {"steamwatch_subscribe", "steamwatch_unsubscribe"}:
            return parts[1] if len(parts) >= 2 else ""
        # fallback: search for action token and return next
        for idx, token in enumerate(parts):
            if token.lstrip("/").lower() in {"sub", "subscribe", "unsub", "unsubscribe"}:
                return parts[idx + 1] if idx + 1 < len(parts) else ""
        return ""

    def _extract_target_or_at(self, event: AstrMessageEvent, args: List[str]) -> str:
        if args:
            return args[0]
        raw_text = self._get_event_text(event)
        at_uid = _extract_at_user_id_from_text(raw_text)
        if at_uid:
            return f"@{at_uid}"
        return ""

    def _consume_session_minutes(self, steamid: str) -> int:
        start = self._session_start.pop(steamid, None)
        if not start:
            return 0
        return max(1, int((time.time() - start) // 60))

    # ------------------------
    # Helpers: resolve/HTTP
    # ------------------------
    async def _resolve_to_steamid64(self, event: AstrMessageEvent, raw: str) -> Tuple[Optional[str], Optional[str]]:
        raw = raw.strip()
        at_uid = _extract_at_user_id(raw) or _extract_at_user_id_from_text(raw)
        if at_uid:
            bindings = self._get_bindings()
            steamid = bindings.get(at_uid)
            if steamid:
                return steamid, None
            return None, f"未找到用户 {at_uid} 的绑定记录。"
        if raw.startswith("@") and len(raw) > 1:
            name = raw[1:]
            meta = self._get_binding_meta()
            matches = [uid for uid, nick in meta.items() if nick == name]
            if len(matches) == 1:
                bindings = self._get_bindings()
                steamid = bindings.get(matches[0])
                if steamid:
                    return steamid, None
            return None, f"未找到昵称 {name} 的绑定记录。"
        if raw.lower() in {"me", "self", "我", "自己"}:
            bindings = self._get_bindings()
            user_key = self._get_user_key(event)
            steamid = bindings.get(user_key)
            if steamid:
                return steamid, None
            return None, "你还未绑定 SteamID。使用 /sw bind 进行绑定。"

        if raw.isdigit() and len(raw) == 17:
            return raw, None

        profile_match = PROFILE_ID_RE.search(raw)
        if profile_match:
            return profile_match.group(1), None

        if CSGO_FRIEND_CODE_RE.match(raw):
            try:
                return str(_decode_csgo_friend_code(raw)), None
            except ValueError:
                return None, "CS:GO 好友码无效。"

        if raw.isdigit() and len(raw) <= 10:
            return str(int(raw) + STEAMID64_BASE), None

        vanity_match = VANITY_ID_RE.search(raw)
        if vanity_match:
            vanity = vanity_match.group(1)
            return await self._resolve_vanity(vanity)

        if "/" in raw:
            raw = raw.rstrip("/")
            if raw.startswith("http"):
                return await self._resolve_short_url(raw)

        return await self._resolve_vanity(raw)

    async def _resolve_vanity(self, vanity: str) -> Tuple[Optional[str], Optional[str]]:
        api_key = self.config.get("steam_web_api_key", "")
        if not api_key:
            return None, "解析自定义链接需要 Steam Web API Key。"
        url = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v0001/"
        async with self._create_http_client(10) as client:
            resp = await client.get(url, params={"key": api_key, "vanityurl": vanity})
            resp.raise_for_status()
            data = resp.json().get("response", {})
            if data.get("success") == 1:
                return data.get("steamid"), None
        return None, "无法解析自定义链接。"

    async def _resolve_short_url(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        try:
            async with self._create_http_client(10, follow_redirects=True) as client:
                resp = await client.get(url)
                final_url = str(resp.url)
        except Exception:
            return None, "短链接解析失败。"
        profile_match = PROFILE_ID_RE.search(final_url)
        if profile_match:
            return profile_match.group(1), None
        vanity_match = VANITY_ID_RE.search(final_url)
        if vanity_match:
            return await self._resolve_vanity(vanity_match.group(1))
        return None, "短链接未解析到 Steam 个人主页。"

    def _get_proxy_url(self) -> str:
        return str(self.config.get("proxy_url", "")).strip()

    def _create_http_client(self, timeout_sec: int, follow_redirects: bool = False) -> httpx.AsyncClient:
        proxy_url = self._get_proxy_url()
        verify_ssl = bool(self.config.get("verify_ssl", True))
        kwargs = {
            "timeout": timeout_sec,
            "follow_redirects": follow_redirects,
            "verify": verify_ssl,
        }
        if proxy_url:
            try:
                return httpx.AsyncClient(proxy=proxy_url, **kwargs)
            except TypeError:
                return httpx.AsyncClient(proxies=proxy_url, **kwargs)
        return httpx.AsyncClient(**kwargs)


def _chunk_list(items: List[str], size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _extract_at_user_id(text: str) -> Optional[str]:
    if text.startswith("@") and text[1:].isdigit():
        return text[1:]
    m = re.fullmatch(r"@.*\((\d+)\)", text)
    if m:
        return m.group(1)
    m = re.fullmatch(r"\[At:(\d+)\]", text)
    if m:
        return m.group(1)
    # CQ 码格式
    m = re.fullmatch(r"\[CQ:at,qq=(\d+)\]", text)
    if m:
        return m.group(1)
    return None


def _extract_at_user_id_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    # 支持 @昵称(123)
    m = re.search(r"@.*\((\d+)\)", text)
    if m:
        return m.group(1)
    # 支持 [At:123] 或 [CQ:at,qq=123]
    m = re.search(r"\[At:(\d+)\]", text)
    if m:
        return m.group(1)
    m = re.search(r"\[CQ:at,qq=(\d+)\]", text)
    if m:
        return m.group(1)
    return None


def _encode_csgo_friend_code(steamid64: int) -> str:
    alphabet = "ABCDEFGHJKLMNOPQRSTUVWXYZ23456789"
    steamid = steamid64 - STEAMID64_BASE_HEX
    checksum = _friend_code_checksum(steamid)
    steamid ^= checksum
    chars = []
    for i in range(9):
        chars.append(alphabet[(steamid >> (i * 5)) & 31])
    code = "".join(chars)[::-1]
    return f"{code[:5]}-{code[5:]}"


def _decode_csgo_friend_code(code: str) -> int:
    code = code.replace("-", "").upper()
    if len(code) != 9:
        raise ValueError("Invalid code length")
    alphabet = "ABCDEFGHJKLMNOPQRSTUVWXYZ23456789"
    code = code[::-1]
    steamid = 0
    for idx, ch in enumerate(code):
        try:
            digit = alphabet.index(ch)
        except ValueError:
            raise ValueError("Invalid character") from None
        steamid += digit << (idx * 5)
    checksum = _friend_code_checksum(steamid)
    steamid ^= checksum
    return steamid + STEAMID64_BASE_HEX


def _friend_code_checksum(steamid: int) -> int:
    data = steamid.to_bytes(8, byteorder="little", signed=False)
    digest = hashlib.md5(data).digest()
    return int.from_bytes(digest[:4], byteorder="little", signed=False)


def _account_id_from_steamid64(steamid64: int) -> int:
    return int(steamid64 - STEAMID64_BASE_HEX)


def _format_ts(ts: Optional[int]) -> str:
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _playtime_taunt(minutes: int) -> str:
    if minutes <= 5:
        return "杂鱼，这就不行了？"
    if minutes <= 15:
        return "才这么点？要不要我给你计时器？"
    if minutes <= 30:
        return "勉强及格，下次再坚持点。"
    if minutes <= 60:
        return "还行吧，但离强还差点。"
    if minutes <= 120:
        return "不错，继续保持。"
    return "今天挺猛的，给你点个赞。"
