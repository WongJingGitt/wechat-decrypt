"""
verify.py — 经验库建设物理约束验证脚本

用法:
    python analyzer/verify.py arg      <data/{wxid}/{stem}.json>
    python analyzer/verify.py extract  <workspace/{task_id}/extract_{date}.md>
    python analyzer/verify.py contact  <experience/contacts/{wxid}.md>
    python analyzer/verify.py progress <workspace/{task_id}/progress.md>

返回码:
    0 = 通过
    1 = 失败，打印具体不合规项
"""

import sys
import re
from pathlib import Path


def fail(msg: str):
    print(f"  [FAIL] {msg}")


def ok(msg: str):
    print(f"  [OK]   {msg}")


# ─────────────────────────────────────────────────────────────
# 零阶段：验证 get_messages 调用参数（_arg 文件）
# 时间范围超过1天时，删除对应 JSON 并以非零退出
# ─────────────────────────────────────────────────────────────
def verify_arg(json_path: Path) -> int:
    import json
    from datetime import date as _date
    from dateutil import parser as _parser

    print(f"\n验证 arg 文件: {json_path}")

    if not json_path.exists():
        fail(f"JSON 文件不存在: {json_path}")
        return 1

    stem = json_path.stem
    arg_path = json_path.parent / f".{stem}_arg"

    if not arg_path.exists():
        fail(f"_arg 文件不存在: {arg_path}（该文件应由 get_messages 自动生成）")
        return 1

    try:
        with open(arg_path, encoding="utf-8") as f:
            arg = json.load(f)
    except Exception as e:
        fail(f"_arg 文件解析失败: {e}")
        return 1

    start_time = arg.get("start_time", "")
    end_time = arg.get("end_time", "")

    try:
        start_date = _parser.parse(start_time).date()
        end_date = _parser.parse(end_time).date()
    except Exception as e:
        fail(f"_arg 文件时间字段无法解析: {e}")
        return 1

    days = (end_date - start_date).days

    if days < 0:
        fail(f"时间范围异常: start={start_time} > end={end_time}")
        return 1

    if days > 0:
        # 删除 JSON 文件，强制 LLM 重新按天拉取
        try:
            json_path.unlink()
            fail(f"时间范围超过1天（{days+1}天），已删除 {json_path.name}")
            fail(f"必须按天拆分：每次 start_time 和 end_time 只能是同一天")
        except OSError as e:
            fail(f"删除 JSON 失败: {e}")
        return 1

    ok(f"时间范围合规: {start_time} ~ {end_time}（同一天）")
    ok(f"wxid: {arg.get('wxid', '?')}")
    return 0


# ─────────────────────────────────────────────────────────────
# 阶段一：验证单天提取文件 extract_{date}.md
# ─────────────────────────────────────────────────────────────
def verify_extract(path: Path) -> int:
    print(f"\n验证 extract 文件: {path}")
    errors = 0

    if not path.exists():
        fail(f"文件不存在: {path}")
        return 1

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # 必填 section
    required_sections = ["## 特质线索", "## 风格线索", "## 关系线索", "## 解读线索"]
    for sec in required_sections:
        if not any(l.strip() == sec for l in lines):
            fail(f"缺少必填 section: {sec}")
            errors += 1
        else:
            ok(f"section 存在: {sec}")

    # 特质线索和风格线索下的条目：必须有 ⭐ 且携带 wxid
    wxid_pattern = re.compile(r'\[[\w@\.\-]+\]')
    star_pattern = re.compile(r'⭐')

    in_trait_or_style = False
    current_section = ""
    item_errors = []

    for line in lines:
        stripped = line.strip()
        if stripped in ("## 特质线索", "## 风格线索"):
            in_trait_or_style = True
            current_section = stripped
        elif stripped.startswith("## "):
            in_trait_or_style = False

        if in_trait_or_style and stripped.startswith("- "):
            if not star_pattern.search(stripped):
                item_errors.append(f"{current_section} 条目缺少 ⭐: {stripped[:60]}")
            if not wxid_pattern.search(stripped):
                item_errors.append(f"{current_section} 条目缺少 [wxid]: {stripped[:60]}")

    for e in item_errors:
        fail(e)
        errors += 1
    if not item_errors:
        ok("所有特质/风格条目格式合规")

    return 1 if errors else 0


# ─────────────────────────────────────────────────────────────
# 阶段二：验证联系人画像 experience/contacts/{wxid}.md
# ─────────────────────────────────────────────────────────────
def verify_contact(path: Path) -> int:
    print(f"\n验证 contact 文件: {path}")
    errors = 0

    if not path.exists():
        fail(f"文件不存在: {path}")
        return 1

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # 必填 section
    required_sections = ["## 身份", "## 基线指标", "## 性格特质", "## 发言风格", "## 更新记录"]
    for sec in required_sections:
        if not any(l.strip() == sec for l in lines):
            fail(f"缺少必填 section: {sec}")
            errors += 1
        else:
            ok(f"section 存在: {sec}")

    # 里程碑事件 section 存在性提示（可选，但存在则格式验证）
    has_milestone = any(l.strip() == "## 里程碑事件" for l in lines)
    if has_milestone:
        ok("section 存在: ## 里程碑事件")
        # 验证格式：每条应含日期和分号
        milestone_pattern = re.compile(r'^- \d{4}-\d{2}-\d{2}.*；影响：')
        in_milestone = False
        milestone_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped == "## 里程碑事件":
                in_milestone = True
                continue
            if in_milestone:
                if stripped.startswith("## "):
                    break
                if stripped.startswith("- ") and not stripped.startswith("> "):
                    milestone_lines.append(stripped)
                    if not milestone_pattern.match(stripped):
                        fail(f"里程碑事件格式错误（需有日期和「；影响：xxx」）: {stripped[:60]}")
                        errors += 1
        if milestone_lines:
            ok(f"里程碑事件 {len(milestone_lines)} 条，格式合规")
        if len(milestone_lines) > 10:
            fail(f"里程碑事件超限: {len(milestone_lines)}/10")
            errors += 1

    # 基线指标非空
    in_baseline = False
    baseline_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped == "## 基线指标":
            in_baseline = True
            continue
        if in_baseline:
            if stripped.startswith("## "):
                break
            if stripped and not stripped.startswith(">"):
                baseline_lines.append(stripped)

    if not baseline_lines:
        fail("## 基线指标 区域为空，脚本应已写入数据")
        errors += 1
    else:
        ok(f"基线指标非空（{len(baseline_lines)} 行）")

    # 统计性格特质和发言风格数量，并检查每个特质的证据数
    wxid_pattern = re.compile(r'\[[\w@\.\-]+\]')

    for section_header in ("## 性格特质", "## 发言风格"):
        in_section = False
        trait_count = 0
        current_trait = None
        evidence_count = 0
        trait_evidence = {}  # trait_name -> evidence_count

        for line in lines:
            stripped = line.strip()
            if stripped == section_header:
                in_section = True
                continue
            if in_section:
                if stripped.startswith("## ") and stripped != section_header:
                    # 保存上一个特质
                    if current_trait:
                        trait_evidence[current_trait] = evidence_count
                    in_section = False
                    break
                if stripped.startswith("### "):
                    if current_trait:
                        trait_evidence[current_trait] = evidence_count
                    current_trait = stripped[4:].strip()
                    trait_count += 1
                    evidence_count = 0
                elif stripped.startswith("- ⭐") or re.match(r'^- ⭐', stripped):
                    evidence_count += 1

        if current_trait:
            trait_evidence[current_trait] = evidence_count

        label = "性格特质" if "性格" in section_header else "发言风格"

        # 数量约束
        if trait_count > 5:
            fail(f"{label} 数量超限: {trait_count}/5")
            errors += 1
        else:
            ok(f"{label} 数量合规: {trait_count}/5")

        # 每个特质证据约束
        for trait, count in trait_evidence.items():
            if count > 3:
                fail(f"{label}「{trait}」证据超限: {count}/3")
                errors += 1
            elif count == 0:
                fail(f"{label}「{trait}」无证据条目")
                errors += 1
            else:
                ok(f"{label}「{trait}」证据: {count}/3")

    # 所有 ⭐ 条目必须携带 wxid
    item_errors = []
    for line in lines:
        stripped = line.strip()
        if re.match(r'^- ⭐', stripped):
            if not wxid_pattern.search(stripped):
                item_errors.append(f"证据条目缺少 [wxid]: {stripped[:60]}")

    for e in item_errors:
        fail(e)
        errors += 1
    if not item_errors:
        ok("所有证据条目携带 [wxid]")

    # 更新记录非空
    in_update = False
    update_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped == "## 更新记录":
            in_update = True
            continue
        if in_update:
            if stripped.startswith("## "):
                break
            if stripped.startswith("- "):
                update_lines.append(stripped)

    if not update_lines:
        fail("## 更新记录 为空")
        errors += 1
    else:
        ok(f"更新记录存在（{len(update_lines)} 条）")

    return 1 if errors else 0


# ─────────────────────────────────────────────────────────────
# 阶段三：验证进度账本 progress.md（extract 文件必须真实存在）
# ─────────────────────────────────────────────────────────────
def verify_progress(path: Path) -> int:
    print(f"\n验证 progress 文件: {path}")
    errors = 0

    if not path.exists():
        fail(f"文件不存在: {path}")
        return 1

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    checked_pattern = re.compile(r'^\s*-\s*\[x\].*?→\s*(.+\.md)')
    pending_pattern = re.compile(r'^\s*-\s*\[\s*\]')

    checked_count = 0
    pending_count = 0

    for line in lines:
        m = checked_pattern.search(line)
        if m:
            checked_count += 1
            extract_path = Path(m.group(1).strip())
            if not extract_path.exists():
                fail(f"已打勾但 extract 文件不存在: {extract_path}")
                errors += 1
            else:
                ok(f"extract 文件存在: {extract_path.name}")
        elif pending_pattern.search(line):
            pending_count += 1

    print(f"  进度: {checked_count} 完成 / {pending_count} 待处理")

    return 1 if errors else 0


# ─────────────────────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 3:
        print("Usage:")
        print("  python verify.py arg      <data/{wxid}/{stem}.json>")
        print("  python verify.py extract  <extract_{date}.md>")
        print("  python verify.py contact  <experience/contacts/{wxid}.md>")
        print("  python verify.py progress <workspace/{task_id}/progress.md>")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    target = Path(sys.argv[2])

    dispatch = {
        "arg": verify_arg,
        "extract": verify_extract,
        "contact": verify_contact,
        "progress": verify_progress,
    }

    if cmd not in dispatch:
        print(f"未知命令: {cmd}，支持: {', '.join(dispatch)}")
        sys.exit(1)

    result = dispatch[cmd](target)

    if result == 0:
        print("\n[PASS] 验证通过")
    else:
        print("\n[FAIL] 验证失败，请修复后再继续")

    sys.exit(result)


if __name__ == "__main__":
    main()
