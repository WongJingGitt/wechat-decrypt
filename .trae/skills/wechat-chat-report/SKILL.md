---
name: "wechat-chat-report"
description: "生成群聊周期性报告（娱乐向）。仅在用户明确要求生成/输出群聊报告时调用。不适用于：拉取聊天记录、维护联系人画像、建设经验库、读取经验库。使用前应该先阅读WechaUseRules技能获取聊天记录数据拉取规范。"
---

# 群聊报告生成

## ⛔ 硬性禁止（最高优先级，先于一切规划执行）

**以下行为无论任何理由均绝对禁止，违反即视为任务失败：**

1. **禁止读取工作区内任何已存在的聊天 JSON 文件**（包括但不限于 `index/data/`、`wechat-decrypt/data/` 等路径下的任何 `.json` 文件），即使文件名中的日期与报告周期完全吻合。
2. **禁止跳过 `get_messages` 调用**。报告所需的全部消息数据必须通过 `get_messages` 工具实时拉取，不得以任何"已有文件"替代。
3. **禁止在阅读 WechaUseRules 技能文档之前开始规划任务步骤**。

> **为什么？** 工作区里的历史文件可能不完整、已过期或来源不明。唯一可信的数据来源是 `get_messages` 工具。"文件名日期匹配"不等于数据完整有效。

---

## 目录结构

```
wechat-chat-report/
├── SKILL.md
├── analyzer/
│   ├── metadata.py        # 元数据提取脚本（JSON版）
│   └── entertainment.py   # 娱乐向报告脚本
├── data/                  # 任务数据（按时间戳隔离）
│   └── 20260417_143052/
│       ├── messages.json           # 原始消息（从 get_messages 获取）
│       ├── metadata.json           # 元数据（由 metadata.py 生成）
│       └── entertainment_data.json # 娱乐向专项数据
├── report/               # 最终报告
│   └── 20260417_143052/
│       └── entertainment.md
└── templates/
    └── entertainment.md  # 娱乐向模板（LLM生成时参考）
```

## 依赖脚本

```
analyzer/metadata.py        # 读取 messages.json，生成 metadata.json
analyzer/entertainment.py   # 读取 metadata.json，生成 entertainment_data.json
```

## 完整工作流程

### 强制阅读规范（任务规划的第一步）
在做任何规划之前，必须先阅读 WechaUseRules 技能文档。这不是可选步骤——没有读完该文档，不得进入下面任何步骤。

```
收到报告生成请求
    ↓
【前置】阅读 WechaUseRules 技能文档（强制，不可跳过）
    ↓
识别群聊名称 → 使用 WechaUseRules 获取 wxid
    ↓
【步骤1】创建任务文件夹
    生成时间戳作为任务ID（如 20260417_143052）
    创建 data/任务ID/ 和 report/任务ID/
    ↓
【步骤2】调用 get_messages 拉取全量消息 ← 唯一合法数据来源
    调用 get_messages(wxid=<群wxid>, start_time=..., end_time=...,
                      output_path="data/任务ID/messages.json")
    ⚠️ get_messages 直接写文件，不返回消息内容
    ⚠️ 即使 data/ 下已有同名文件，也必须重新调用覆盖
    ↓
【步骤3】运行元数据提取
    python analyzer/metadata.py data/任务ID/messages.json
    生成 data/任务ID/metadata.json
    ↓
【步骤4】运行专项数据清洗
    python analyzer/entertainment.py data/任务ID/
    生成 data/任务ID/entertainment_data.json
    ↓
【步骤5a】LLM 读取经验库，输出 sender_map.json
    读取 ../wechauserules/experience/contacts/ 所有联系人画像
    输出 data/任务ID/sender_map.json（格式：{"wxid": "昵称"}）
    没有画像的成员用 rankings 里出现的标识符填入
    ↓
【步骤5b】LLM 生成报告
    ⚠️ 必须先读取 entertainment_data.json 的 tips.must_read
    读取 data/任务ID/entertainment_data.json + data/任务ID/messages.json 完整原文
    所有引用必须含时间戳，格式：**昵称**（M月D日 HH:MM）：「原话」
    生成 report/任务ID/entertainment.md
    ↓
【步骤6】验证报告真实性（强制，非0禁止结束）
    python analyzer/verify_report.py report/任务ID/entertainment.md data/任务ID/messages.json data/任务ID/sender_map.json
    返回码非0 → 按错误提示词修改报告 → 重新验证
```

## 脚本说明

### metadata.py — 元数据提取

输入：`raw.md`
输出：`metadata.json`

提取的元数据：
- **基础统计**：总消息数、总行数、发言人数、时间范围
- **内容分布**：文字/图片/视频/语音/链接/小程序/表情包 各数量
- **时间分布**：按小时分布、按天分布
- **发送者统计**：每人消息数、内容类型分布、小时分布
- **事件索引**：撤回（谁、次数、行号）、邀请入群、拍一拍、回复引用
- **@提及网络**：谁被@最多
- **高频词**：Top50
- **互动矩阵**：用户两两之间的消息往来次数

### entertainment.py — 娱乐向报告

输入：`metadata.json` + `raw.md`
输出：`entertainment.md`

基于元数据生成娱乐向报告：
- 基础统计展示
- 发言排行榜
- 各类奖项Top3（互联网嘴替、凌晨发癫、链接狂魔等）
- 关键事件索引

## 报告类型

### 娱乐向（Entertainment）

**生成方式**：`analyzer/entertainment.py`
**模板参考**：[templates/entertainment.md](templates/entertainment.md)

适用场景：轻松、搞笑、玩梗风格的群聊总结

---

其他报告类型待扩展...