# 聊天记录获取

> ⛔ **最高级别约束：聊天记录必须通过工具获取**
> 必须调用 `get_messages` 工具拉取数据，严禁直接读取本地文件作为聊天记录来源。
> 唯一允许读取的本地文件是：`data/` 目录下由 `get_messages` 写入的 JSON 产物。
> **在任何情况下，本地不存在"可以直接读的原始聊天记录"，不要尝试搜索或读取。**

## 触发条件

用户请求涉及以下行为时使用本路由：
- 总结聊天记录
- 查看特定时间段的消息
- 拉取某人/某群的聊天内容
- 分析聊天记录中的话题、人物、事件

## 核心流程

```
用户请求
    ↓
识别联系人/群聊 → 获取 wxid
    ↓
获取聊天记录（写入 JSON 文件）
    ↓
读取 JSON 文件分析内容
```

## 1. 联系人识别

```
用户提到联系人/群聊名称
    ↓
使用 search_contacts 搜索关键词
    ↓
├─ 0 个结果 → 询问用户或拉取最近会话列表辅助回忆
├─ 1 个结果 → 静默使用 wxid 继续
└─ 多个结果 → 列出选项，询问用户确认
```

## 2. 时间范围计算

| 用户输入 | 计算规则 |
|---------|---------|
| "最近"、"这几天" | 最近 3 天 |
| "N 天" | 第1天00:00 到 第N天23:59 |
| "N 周" | 第一周周一00:00 到 第N周周日23:59 |
| "N 月" | 第一月1日00:00 到 第N月最后一天23:59 |
| "昨天" | 前一天00:00 到 23:59 |
| "今天" | 当天00:00 到 当前时刻 |
| 具体日期 | 按用户指定范围 |

## 4. 聊天记录获取

**策略**：一次性获取全量数据，写入 JSON 文件，不分页。工具层保证数据完整性，无需多次调用。

**output_path 规范**：必须写入 SKILL 数据目录，格式为：
```
data/{wxid}/{YYYYMMDD_HHMMSS}.json
```
例：`data/wxid_abc123/20260419_143052.json`

> 精确到秒，同一天多次拉取不会覆盖

```
调用 get_messages(wxid, start_time, end_time, output_path)
    ↓
工具写入 JSON 文件，返回 {path, count, wxid, start_time, end_time}
    ↓
读取 JSON 文件处理消息
```

### 消息结构（每条）

```json
{
  "local_id": 12345,
  "server_id": "...",
  "sender": "wxid_abc",
  "create_time": "2026-04-19 10:30:00",
  "select_wxid": "xxx@chatroom",
  "at_user_list": ["wxid_xxx"],
  "type": "文本消息",
  "content": "今天吃什么"
}
```

- `sender` 为 wxid，需要显示名时调用 `get_contact_name(wxid)`
- `type` 枚举值：文本消息、图片消息、语音消息、视频消息、表情消息、位置消息、名片消息、链接、文件、音频、小程序、引用消息、拍一拍、红包、视频号、聊天记录、群公告、通话消息、系统通知、系统消息

### 引用消息溯源

引用消息的 `content` 字段格式为：
```
回复内容
  > 引用: 发送者wxid: 被引用文字
```

如需获取被引用消息的完整内容，使用 `get_message_by_server_id`：
```
从 refer_svrid 字段获取 server_id
    ↓
调用 get_message_by_server_id(server_id, wxid)
    ↓
返回被引用消息的完整 format_message
```

## 5. 图片处理

```
读取 JSON 文件
    ↓
找到 type="图片消息" 的条目，取 local_id
    ↓
使用 decode_image 解密
    ↓
结合上下文理解内容，生成图片描述
```
- 跨群事件发生时

**回写内容**：
- Mnemosyne：实体更新、关系创建、事件记录
- MD画像：泛化总结更新

## 工具使用规范

### search_contacts
- 输入：用户提供的关键词（匹配备注名、昵称、wxid、alias）
- 输出：JSON 数组，每项含 `wxid / remark / nick_name / alias`
- 用途：联系人识别，关键词 → wxid

### get_contact_name
- 输入：wxid
- 输出：JSON 对象，含 `wxid / remark / nick_name / display_name`
- 用途：wxid → 显示名，解析消息 sender 字段时使用

### get_messages
- 必填：wxid、start_time、end_time、output_path
- 时间格式：`YYYY-MM-DD` 或 `YYYY-MM-DD HH:MM:SS`
- output_path：必须使用 `data/{wxid}/{YYYYMMDD_HHMMSS}.json`
- 返回：`{path, count, wxid, start_time, end_time}`
- **不分页**，一次返回时间段内全量消息

### get_message_by_server_id
- 必填：server_id、wxid（消息所在会话）
- 输出：单条消息的完整 format_message
- 用途：引用消息溯源

### decode_image
- 必填：chat_name（wxid 或名称）、local_id
- 用途：解密图片消息

## 输出格式

### 聊天记录输出
- 按 `create_time` 正序排列（工具已保证）
- sender 为 wxid，如需展示名称统一调用 `get_contact_name`
- 图片消息附带图片描述
- 保持对话连贯性

### 图片描述格式
```
[时间] 发送者: [图片描述] - 结合聊天上下文的理解
```