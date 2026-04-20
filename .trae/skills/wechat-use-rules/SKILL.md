---
name: wechatuserules
description: 微信聊天数据拉取规范，群聊/联系人经验库建设与使用规范。涉及到以下动作必须先读取这个SKILL：微信聊天记录拉取、群聊/联系人读取、联系人经验库建设与读取、联系人画像读取与建设、群聊画像读取与建设、总结/归纳联系人特征、更新经验库、写入经验库。
---

# 微信数据拉取规范

## 路由索引

| 路由文件 | 适用场景 |
|---------|---------|
| [sources/chat-history.md](sources/chat-history.md) | 总结聊天记录、查看消息、拉取聊天内容、分析话题人物事件 |
| [sources/profile-builder.md](sources/profile-builder.md) | 针对特定私聊联系人建设/更新个人画像 |
| [sources/group-builder.md](sources/group-builder.md) | 群维度任务：找活跃成员、批量建群成员画像、建群整体画像 |

## ⛔ 最高级别约束

**所有涉及聊天记录的操作，必须先读取 [sources/chat-history.md](sources/chat-history.md) 获取拉取规范。**

> 聊天记录只能通过 `get_messages` 工具获取，严禁直接读取本地文件作为聊天数据来源。
> 唯一允许读取的本地文件是：`data/` 目录下由 `get_messages` 工具写入的 JSON 产物。
> **无论任务是查看消息、总结聊天、还是建设经验库，只要涉及拉取聊天记录，此约束均适用。**

## 通用原则

1. **wxid 优先原则**：所有操作必须基于 wxid，用户名/昵称仅用于搜索获取 wxid
2. **静默执行原则**：搜索结果唯一时静默执行，多个结果时主动询问
3. **经验库优先原则**：建设前先读取已有经验库文件，了解已有认知后再操作

## 经验库目录结构

```
experience/
  contacts/         # 私聊好友画像（双边关系为主）
    {wxid}.md
  members/          # 群成员画像（跨群，一人一文件）
    {wxid}.md
  groups/           # 群整体画像
    {group_wxid}.md
```

> 同一个 wxid 可同时存在于 `contacts/` 和 `members/`，两份文件服务不同目的，互不干扰。

## 错误处理

- 搜索无结果 → 询问用户提供更多信息
- 技术错误 → 转化为人类友好描述，不暴露内部细节