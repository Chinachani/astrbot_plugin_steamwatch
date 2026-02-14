# astrbot_plugin_steamwatch

监控 SteamID 是否在进行游戏，并推送通知。支持绑定与 @用户查询、分群订阅、代理与连通性测试，以及游戏时长/成就等信息展示。

## 前置要求
- Steam Web API Key（用于 `GetPlayerSummaries` 与 `ResolveVanityURL`）
  - 申请地址：https://steamcommunity.com/dev/apikey
- Python 依赖：`httpx`

## 配置说明
插件启动后会根据 `_conf_schema.json` 生成配置项：
- `steam_web_api_key`：Steam Web API Key
- `poll_interval_sec`：轮询间隔（秒，>= 30）
- `steamids`：需要监控的 SteamID64 列表
- `bindings`：用户绑定（由指令维护，格式 user_id:steamid64）
- `binding_meta`：绑定昵称（由指令维护，格式 user_id:nickname）
- `admin_user_ids`：管理员用户ID列表（为空则不限制敏感指令）
- `auto_add_on_bind_when_no_admin`：管理员列表为空时，绑定自动加入监控
- `notify_targets`：接收通知的会话目标
- `default_platform_id`：订阅会话默认平台ID（兼容旧订阅）
- `default_message_type`：订阅会话默认消息类型（GroupMessage/FriendMessage/OtherMessage）
- `notify_group_enabled`：是否启用分群订阅
- `notify_groups`：分群订阅（格式 group:target）
- `steamid_groups`：SteamID 分组（格式 steamid:group）
- `notify_on_stop`：是否在停止游戏时提醒
- `request_timeout_sec`：请求超时（秒）
- `request_retries`：请求重试次数
- `request_retry_delay_sec`：重试间隔（秒）
- `proxy_url`：代理地址（可选，例如 http://127.0.0.1:7890）
- `debug_log`：是否开启调试日志
- `verify_ssl`：是否校验证书（关闭可绕过 CERTIFICATE_VERIFY_FAILED）
- `show_csgo_friend_code`：是否在绑定/解析中额外显示 CS:GO 好友码
- `use_localized_game_name`：是否尝试获取游戏中文名（Steam 商店 API）
- `game_name_language`：游戏名语言（默认 schinese）
- `game_name_cache_ttl_sec`：游戏名缓存有效期（秒）

## 指令
### 简化入口
- `/sw` 查看菜单
- `/sw manage` 管理模块菜单
- `/sw notify` 通知模块菜单
- `/sw query` 查询模块菜单
- `/sw bind`  绑定模块菜单
- `/sw net`   网络模块菜单
- `/sw add|remove|list|interval`
- `/sw sub|unsub [group]`
- `/sw subclean` 清理无效订阅（管理员）
- `/sw subinfo` 查看当前会话订阅信息
- `/sw groupinfo [group]` 查看分组订阅详情
- `/sw grouplist` 查看分组订阅列表
- `/sw resolve|query|status|info`
- `/sw test|proxytest`
- `/sw bind|unbind|me`

说明：当 `admin_user_ids` 配置不为空时，以下指令仅管理员可用：添加/移除监控、查看列表、设置轮询、订阅/取消订阅通知。

说明：插件内“好友码”指 Steam 账号 ID（SteamID32 / AccountID，例如 1058658524）。
如需同时显示 CS:GO 好友码，可启用 `show_csgo_friend_code`。

### 分群订阅
启用 `notify_group_enabled` 后：
- `/sw sub <group>` 创建分组并且订阅
- `/sw unsub <group>` 删除分组并取消订阅
- `/sw add <steamid|me|@qq> <group>` 为指定分组添加监控对象
- `/sw subinfo` 查看当前会话订阅
- `/sw groupinfo [group]` 查看分组订阅详情
- `/sw grouplist` 查看分组订阅列表
- `/sw subclean` 清理无效订阅（管理员）
说明：启用分群订阅后，仅推送已分组目标，不再回退到全局订阅。

### 完整菜单示例（模块化）
```
========== SteamWatch 菜单 ==========
简化入口：/sw <模块>
模块列表：manage / notify / query / bind / net
--------------------------------------
【管理】/sw manage  - 监控列表与轮询
【通知】/sw notify  - 订阅/分组/清理
【查询】/sw query   - 查询/解析/状态
【绑定】/sw bind    - 绑定/解绑/我的
【网络】/sw net     - 连通性测试
--------------------------------------
示例：/sw notify
完整命令：/steamwatch_menu
```

### 完整命令（兼容）
- `/steamwatch_add <steamid64|profile_url|vanity|friend_code|me>` 添加监控
- `/steamwatch_remove <steamid64|profile_url|vanity|friend_code|me>` 移除监控
- `/steamwatch_list` 查看监控列表
- `/steamwatch_interval <seconds>` 设置轮询间隔
- `/steamwatch_subscribe` 订阅当前会话通知（管理员）
- `/steamwatch_unsubscribe` 取消订阅（管理员）
- `/steamwatch_subinfo` 查看当前会话订阅信息
- `/steamwatch_groupinfo [group]` 查看分组订阅详情
- `/steamwatch_grouplist` 查看分组订阅列表
- `/steamwatch_subclean` 清理无效订阅（管理员）
- `/steamwatch_resolve <steamid64|profile_url|vanity|friend_code|me>` 解析为 SteamID64
- `/steamwatch_menu` 查看菜单
- `/steamwatch_query <steamid64|profile_url|vanity|friend_code|me>` 立即查询一次
- `/steamwatch_info <steamid64|profile_url|vanity|friend_code|me>` 查询更多信息（成就/时长等）
- `/steamwatch_test` 测试 Steam/Steam Web API 访问
- `/steamwatch_proxytest` 测试代理是否生效
- `/steamwatch_status <steamid64|profile_url|vanity|friend_code|me>` 推送当前状态
- `/steamwatch_bind <steamid64|profile_url|vanity|friend_code>` 绑定自己的 SteamID
- `/steamwatch_unbind [user_id]` 解除绑定（可选参数仅管理员）
- `/steamwatch_me` 查看自己的绑定

## 好友码说明
支持：
- CS:GO 好友码（如 `ABCDE-1234`）
- 数字账号 ID（视为 SteamID32，自动转换为 SteamID64）

若提供 `steamcommunity.com/id/<vanity>` 或短链接（如 `s.team/p/...`），插件会使用 Steam Web API 解析。

## 网络问题说明
如果在中国大陆网络下访问 Steam/Steam Web API 经常失败，可使用独立的 Hosts 优化工具进行网络优化与加速。
仓库地址：https://github.com/Chinachani/steam-hosts-tools

## 更新日志
### v1.1.0
- 新增 `/sw info`：展示更丰富的 Steam 信息（时长/成就/状态等）
- 绑定与查询支持 @用户，且输出好友码为账号 ID（可选显示 CS:GO 好友码）
- 新增分群订阅与通知路由
- 轮询记录本次游玩时长并生成评价

### v1.1.2
- 分群订阅会话格式自动归一化，兼容旧订阅数据
- 新增订阅查询指令：/sw subinfo 与 /sw groupinfo

### v1.1.3
- 新增订阅清理指令：/sw subclean

### v1.1.4
- 菜单改为模块化+分隔线版本，子模块补充中文提示

### v1.1.5
- /sw bind 兼容模块菜单与实际绑定
- 停止游戏评价改为换行展示

### v1.1.6
- /sw query 在有参数时正确执行查询（不再被模块菜单拦截）

### v1.1.7
- 分群订阅启用时不再回退到全局通知
- 订阅清理会过滤无效会话格式

### v1.1.8
- 新增分组订阅列表指令：/sw grouplist

### v1.1.9
- 分群订阅启用且当前群已订阅时，/sw add 自动加入当前分组
- 已在监控列表中的 SteamID 可更新分组

### v1.1.10
- 增加可选“中文游戏名”开关（走的 Steam 商店 ，不是第三方翻译，可以保准）
- 提示：自己决定开不开，游戏名会缓存，但是每次第一次获取的时候可能会很慢

### v1.1.11
- 管理员列表为空时可选“绑定即加入监控”
