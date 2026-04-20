# 联系人画像建设规范（私聊好友，主 Agent 专用）

> ⛔ **隔离声明：禁止阅读 `sources/subtasks/single-day-task.md`**
> 该文件仅供被派发的子任务/子 Agent 使用。
> 主 Agent 的职责是：编排、派发、收结果、合并。不参与具体分析。

> ✅ **适用范围：本文档仅处理私聊好友的画像建设。**
> 群成员画像建设请使用 `sources/group-builder.md`。

> ⛔ **禁止脚本写入画像文件**
> 画像文件（`experience/contacts/{wxid}.md`）必须由 LLM 亲自读取、分析、撰写，任何脚本均不得直接写入。
> 脚本只负责产出数字（stats），判断和表达是 LLM 的工作。

> ⚠️ **必须亲自合并，不得直接拼接子任务产物**
> 子任务只有单天视角，缺乏全局观。所以你必须通读所有 extract，独立进行跨天归纳、矛盾识别、特质提炼，再写入画像。直接拼接 extract 内容等同于没有合并。

## 适用场景

- 用户要求"总结XX的画像"（私聊联系人）
- 用户要求"建设/更新XX的经验库"

## 文件结构总览

```
# 以下均为 SKILL 根目录的相对路径
experience/contacts/{wxid}.md               # 联系人画像输出

data/{wxid}/{YYYYMMDD_HHMMSS}.json          # 原始消息（只读）
data/{wxid}/.{YYYYMMDD_HHMMSS}_arg          # 调用参数记录（由 get_messages 自动生成）

workspace/{task_id}/                        # 任务工作区，task_id = YYYYMMDD_HHMMSS
  progress.md                              # 任务进度账本
  extract_{date}.md                        # 单天提取摘要（date = YYYYMMDD）
```

---

## 时间粒度约束

> **最小粒度：一天。** `get_messages` 每次调用只能传同一天的 start_time 和 end_time。

- 跨天任务**必须**拆分为多次单天调用
- 如果支持子 Agent 并发，每天派一个子 Agent
- 如果不支持并发，依次按天调用
- 每次调用后**必须**运行验证：
  ```
  python analyzer/verify.py arg data/{wxid}/{stem}.json
  ```
  验证失败（时间超1天）时，JSON 会被自动删除，必须重新按天拆分调用

---

## 任务路由

> ⛔ **路由前置检查（收到任务后第一件事，不得跳过）**
> 1. 解析用户给出的日期范围，计算天数
> 2. **1天** → 直接走「收到单天任务时」节
> 3. **≥2天** → 必须走「收到多天任务时」节，**禁止跳过子任务派发、直接逐天处理**

---

### 收到多天任务时

**总览流程：**
```
1. 解析日期范围，按天拆分
2. 生成任务ID，创建 progress.md
3. 拆分成每天派一个子任务
   - 派发方式：类似Task / SubAgent等等可以派发子任务的工具
   - 要求子任务必须阅读 `sources/subtasks/single-day-task.md`，并严格按照其中的步骤执行。
4. 所有天完成后，读取所有 extract 产物，合并写入经验库
```

**执行步骤：**

1. 生成任务ID（格式：`{YYYYMMDD_HHMMSS}`）
2. 创建 `workspace/{task_id}/progress.md`，写入初始进度表
3. 按天拆分，使用类似Task / SubAgent等等可以派发子任务的工具，以每天为粒度派发独立任务，每个子任务使用下方「子任务派发模板」，照抄填空，不得修改结构
4. 每天完成后在 `progress.md` 对应行打勾，并验证：
   ```
   python analyzer/verify.py progress workspace/{task_id}/progress.md
   ```
5. 所有天完成后：读取所有 `extract_{date}.md` → 执行合并写入经验库

**子任务派发模板（每天一份，照抄填空）：**
```
你是一个单天数据提取子任务执行者。
请阅读 sources/subtasks/single-day-task.md 并严格按照其中的步骤执行，不做任何其他操作。

参数：
- wxid: {wxid}
- date: {YYYY-MM-DD}
- task_id: {task_id}
- output_path: data/{wxid}/{YYYYMMDD_HHMMSS}.json
- extract_path: workspace/{task_id}/extract_{YYYYMMDD}.md

执行完成后回复：完成 / 失败（附原因）
```

**progress.md 格式：**
```markdown
# {wxid} | {task_id}

## 进度
- [ ] 2026-04-17 → workspace/{task_id}/extract_20260417.md
- [ ] 2026-04-18 → workspace/{task_id}/extract_20260418.md
```

> ⚠️ progress.md 只由多天任务读写，单天子任务不得读取或修改

---

### 收到单天任务时

> ⛔ 到此为止。单天任务的所有执行细节在 `sources/subtasks/single-day-task.md`，由被派发的子任务负责阅读执行。你禁止阅读该文件。

---

### 收到合并任务时（多天完成后）

**输入**：wxid、task_id

**执行步骤：**

1. 读取 `progress.md` 确认所有天已完成
2. 读取所有 `extract_{date}.md`
3. 读取现有 `experience/contacts/{wxid}.md`（若存在）
4. 执行特质合并（规则详见 [refs/contact-schema.md](refs/contact-schema.md)）
5. **主动检查跨源矛盾**：同一特质在不同来源相反时，升格为高阶特质，标注「跨源」
6. **合并里程碑事件**：过滤所有 extract 中的里程碑线索，写入画像的里程碑事件节
7. 将脚本汇总的基线指标写入经验库基线指标区
8. 写入 `experience/contacts/{wxid}.md`
9. **运行验证，非 0 禁止结束**：
   ```
   python analyzer/verify.py contact experience/contacts/{wxid}.md
   python analyzer/verify.py progress workspace/{task_id}/progress.md
   ```

---

### 收到多源任务时（跨群/私聊+群）

**执行步骤：**

1. 对每个数据源分别执行多天/单天任务流程
2. 各源均完成后，执行**跨源合并**：
   - 汇总所有来源的 extract 文件
   - 主动寻找矛盾点（同一特质在不同 wxid 来源表现相反）
   - 矛盾点升格为高阶特质，标注「跨源」，保留两边证据
3. 写入 `experience/contacts/{wxid}.md`
4. **运行验证，非 0 禁止结束**：
   ```
   python analyzer/verify.py contact experience/contacts/{wxid}.md
   ```

---

## 画像结构与优胜略汰规则

详见 [refs/contact-schema.md](refs/contact-schema.md)
