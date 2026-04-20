# 群成员画像建设规范（主 Agent 专用）

> ⛔ **隔离声明：禁止阅读 `sources/subtasks/member-analysis-task.md`**
> 该文件仅供被派发的子任务使用。

> ✅ **适用范围：从群出发，找成员、分析成员、建成员画像，可选建群整体画像。**
> 私聊联系人画像建设请使用 `sources/profile-builder.md`。

> ⛔ **禁止脚本写入画像文件**
> 画像文件（`experience/members/{wxid}.md`、`experience/groups/{group_wxid}.md`）必须由 LLM 亲自读取、分析、撰写，任何脚本均不得直接写入。
> 脚本只负责产出数字（stats），判断和表达是 LLM 的工作。

> ⚠️ **你必须亲自合并，不得直接拼接子任务产物**
> 子任务只有单成员视角，缺乏全局观。你必须通读所有 extract，独立进行跨成员归纳、群内关系网络识别、矛盾检测，再写入画像。直接拼接 extract 内容等同于没有合并。

## 适用场景

- 用户要求"分析 xxx 群的活跃成员"
- 用户要求"给 xxx 群的成员建画像"
- 用户要求"建设 xxx 群的群画像"

## 文件结构总览

```
# 以下均为 SKILL 根目录的相对路径
experience/members/{wxid}.md              # 群成员画像输出（一人一文件，跨群）
experience/groups/{group_wxid}.md         # 群整体画像输出（可选）

data/{group_wxid}/{YYYYMMDD_HHMMSS}.json  # 群聊原始消息（只读）

workspace/{task_id}/                      # 任务工作区，task_id = YYYYMMDD_HHMMSS
  progress.md                            # 任务进度账本
  extract_{wxid}.md                      # 单成员分析产物
```

---

## 完整流程

### 第一阶段：数据收集（串行，由你执行）

1. 识别群聊，获取 group_wxid（用 search_contacts 搜索群名）
2. 生成任务ID（格式：`{YYYYMMDD_HHMMSS}`）
3. 创建 `workspace/{task_id}/progress.md`，写入初始进度表
4. 按3天为最小单位拉取群全量数据（大于3天必须拆分，每次最大只传3天时间）：
   ```
   对日期范围内每个3天时间：
     get_messages(group_wxid, {date} 00:00:00, {date} 23:59:59, data/{group_wxid}/{YYYYMMDD_HHMMSS}.json)
     python analyzer/verify.py arg data/{group_wxid}/{stem}.json
   ```
5. 对所有 JSON 文件运行预处理，获取活跃成员列表：
   ```
   python analyzer/stats.py data/{group_wxid}/
   ```
6. 读取 stats 产物，得出活跃成员列表（消息数 Top N，或按用户指定阈值筛选）
7. 在 progress.md 写入活跃成员列表

### 第二阶段：成员分析（按成员并发，由你派发子任务）

8. 对每个活跃成员，**使用类似Task / SubAgent等等可以派发子任务的工具**派发 member-analysis-task 子任务，使用下方「子任务派发模板」
9. 每个成员完成后，在 progress.md 对应行打勾

**子任务派发模板（每个成员一份，照抄填空）：**
```
你是一个群成员分析子任务执行者。
请阅读 sources/subtasks/member-analysis-task.md 并严格按照其中的步骤执行，不做任何其他操作。

参数：
- target_wxid: {wxid}
- group_wxid: {group_wxid}
- task_id: {task_id}
- data_paths: [data/{group_wxid}/{file1}.json, data/{group_wxid}/{file2}.json, ...]
- extract_path: workspace/{task_id}/extract_{wxid}.md

执行完成后回复：完成 / 失败（附原因）
```

### 第三阶段：合并写入（由你执行）

10. 确认所有成员任务已完成：
    ```
    python analyzer/verify.py progress workspace/{task_id}/progress.md
    ```
11. 对每个成员：
    - 读取 `workspace/{task_id}/extract_{wxid}.md`
    - 读取现有 `experience/members/{wxid}.md`（若存在）
    - 执行特质合并（规则详见 [refs/group-member-schema.md](refs/group-member-schema.md)）
    - 写入 `experience/members/{wxid}.md`
    - 验证：
      ```
      python analyzer/verify.py contact experience/members/{wxid}.md
      ```
12. （可选）建设群整体画像，基于成员画像 + stats 汇总数据生成：
    - 写入 `experience/groups/{group_wxid}.md`
    - 格式详见 [refs/group-schema.md](refs/group-schema.md)

---

## progress.md 格式

```markdown
# {group_wxid} | {task_id}

## 数据收集
- [x] 2026-04-15~17 → data/{group_wxid}/{file1}.json
- [x] 2026-04-18~20 → data/{group_wxid}/{file2}.json

## 成员分析
- [ ] {wxid_a} → workspace/{task_id}/extract_{wxid_a}.md
- [ ] {wxid_b} → workspace/{task_id}/extract_{wxid_b}.md
```

---

## 画像结构与优胜略汰规则

- 群成员画像详见 [refs/group-member-schema.md](refs/group-member-schema.md)
- 群整体画像详见 [refs/group-schema.md](refs/group-schema.md)
