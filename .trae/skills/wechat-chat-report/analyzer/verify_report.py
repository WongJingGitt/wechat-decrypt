"""
verify_report.py — 娱乐向群聊报告真实性验证脚本

用法：
    python analyzer/verify_report.py <report.md> <messages.json> <sender_map.json>

返回码：
    0 = 全部通过
    1 = 存在验证失败（打印提示词供 LLM 修正）
"""

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path


# ── 引用锚点正则 ──────────────────────────────────────────────────────────────
# 匹配：**昵称**（M月D日 HH:MM）：「内容」
_CITE_RE = re.compile(
    r'\*\*(.+?)\*\*（(\d{1,2})月(\d{1,2})日\s+(\d{2}):(\d{2})）：「(.+?)」'
)

# ── 时间线节点正则 ────────────────────────────────────────────────────────────
# 匹配：- HH:00 或 - HH:XX 开头的 li 条目（时间线格式）
_TIMELINE_ITEM_RE = re.compile(r'^\s*[-*]\s+\d{1,2}:\d{2}')

# ── 成就表格空获得者正则 ──────────────────────────────────────────────────────
_ACHIEVEMENT_EMPTY_RE = re.compile(r'\|\s*(无|—|-|)\s*\|')


def load_messages(messages_path: Path) -> list:
    with open(messages_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_sender_map(sender_map_path: Path) -> dict:
    """返回 {wxid: 昵称} 和反查 {昵称: wxid}"""
    with open(sender_map_path, 'r', encoding='utf-8') as f:
        wxid_to_name = json.load(f)
    name_to_wxid = {v: k for k, v in wxid_to_name.items()}
    return wxid_to_name, name_to_wxid


def parse_report_sections(text: str) -> dict:
    """
    按 ## 标题分割报告，返回 {section_title: content}
    ### 子标题归入最近的 ## 父节
    """
    sections = {}
    current_h2 = None
    buf = []
    for line in text.splitlines(keepends=True):
        if line.startswith('## '):
            if current_h2 is not None:
                sections[current_h2] = ''.join(buf)
            current_h2 = line.strip()
            buf = [line]
        else:
            buf.append(line)
    if current_h2:
        sections[current_h2] = ''.join(buf)
    return sections


def extract_citations(text: str) -> list:
    """提取文本中所有引用锚点，返回 [{name, month, day, hour, minute, content, raw}]"""
    results = []
    for m in _CITE_RE.finditer(text):
        results.append({
            'name': m.group(1),
            'month': int(m.group(2)),
            'day': int(m.group(3)),
            'hour': int(m.group(4)),
            'minute': int(m.group(5)),
            'content': m.group(6),
            'raw': m.group(0),
        })
    return results


def verify_citation_in_messages(cite: dict, messages: list, name_to_wxid: dict,
                                 year: int, window_minutes: int = 1) -> bool:
    """
    检查引用是否能在 messages.json 中找到对应记录。
    匹配条件：
      1. create_time 在 ±window_minutes 分钟内
      2. content 包含引用文字前 10 个字（模糊匹配，允许省略）
    发言人核对（可选）：如果 sender_map 有该昵称对应的 wxid，追加检查 sender 字段。
    """
    try:
        target_dt = datetime(year, cite['month'], cite['day'], cite['hour'], cite['minute'])
    except ValueError:
        return False

    quoted = cite['content'].replace('…', '').strip()
    match_prefix = quoted[:10]
    wxid = name_to_wxid.get(cite['name'])

    for msg in messages:
        ct = msg.get('create_time', '') or ''
        try:
            msg_dt = datetime.strptime(ct, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
        if abs((msg_dt - target_dt).total_seconds()) > window_minutes * 60:
            continue
        content = (msg.get('content', '') or '').strip()
        if match_prefix and match_prefix not in content:
            continue
        # 如果能从 sender_map 找到 wxid，追加 sender 核对
        if wxid and msg.get('sender', '') != wxid:
            continue
        return True
    return False


def infer_year(messages: list) -> int:
    """从消息推断报告年份（取第一条消息的年份）"""
    for msg in messages:
        ct = msg.get('create_time', '') or ''
        try:
            return datetime.strptime(ct, '%Y-%m-%d %H:%M:%S').year
        except ValueError:
            continue
    return datetime.now().year


def check_oscar_citations(sections: dict, messages: list, name_to_wxid: dict, year: int) -> list:
    """检查1：奥斯卡各奖项名场面引用 ≥ 2 条"""
    errors = []
    oscar_section = None
    for title, content in sections.items():
        if '奥斯卡' in title or '颁奖' in title:
            oscar_section = content
            break
    if oscar_section is None:
        return []

    # 按 ### 子标题分割奖项
    award_blocks = re.split(r'(?=### )', oscar_section)
    for block in award_blocks:
        if not block.strip() or not block.startswith('###'):
            continue
        award_title = block.splitlines()[0].strip()
        citations = extract_citations(block)
        if len(citations) < 2:
            errors.append(
                f'「{award_title}」名场面还原引用不足（当前{len(citations)}条，需≥2条）。'
                f'格式：**发言人**（M月D日 HH:MM）：「原话」，请读 messages.json 找真实对话。'
            )
    return errors


def check_citation_authenticity(report_text: str, messages: list,
                                 name_to_wxid: dict, year: int) -> list:
    """检查2：所有引用时间戳可在 messages.json 中核实"""
    errors = []
    citations = extract_citations(report_text)
    for cite in citations:
        if not verify_citation_in_messages(cite, messages, name_to_wxid, year):
            preview = cite['content'][:20]
            errors.append(
                f'引用「{preview}…」（{cite["month"]}月{cite["day"]}日 {cite["hour"]:02d}:{cite["minute"]:02d}，'
                f'{cite["name"]}）在 messages.json 中找不到对应记录，'
                f'请确认时间或内容是否有误。'
            )
    return errors


def check_hot_search_citations(sections: dict) -> list:
    """检查3：热搜榜每条含 ≥ 1 条原话引用"""
    errors = []
    hot_section = None
    for title, content in sections.items():
        if '热搜' in title or '话题榜' in title:
            hot_section = content
            break
    if hot_section is None:
        return []

    topic_blocks = re.split(r'(?=### )', hot_section)
    for block in topic_blocks:
        if not block.strip() or not block.startswith('###'):
            continue
        topic_title = block.splitlines()[0].strip()
        citations = extract_citations(block)
        if len(citations) < 1:
            errors.append(
                f'{topic_title} 缺少原话引用，'
                f'请读 messages.json 找参与者真实发言（格式：**发言人**（月日 时:分）：「原话」）。'
            )
    return errors


def check_timeline(sections: dict) -> list:
    """检查4：时间线每天 ≥ 4 条节点"""
    errors = []
    timeline_section = None
    for title, content in sections.items():
        if '时间线' in title:
            timeline_section = content
            break
    if timeline_section is None:
        return []

    # 按日期行分组（格式：**4月17日** 或 4月17日）
    day_pattern = re.compile(r'\*?\*?(\d{1,2}月\d{1,2}日)\*?\*?')
    current_day = None
    day_items: dict = {}
    for line in timeline_section.splitlines():
        day_match = day_pattern.search(line)
        if day_match and not _TIMELINE_ITEM_RE.match(line):
            current_day = day_match.group(1)
            day_items.setdefault(current_day, 0)
        elif current_day and _TIMELINE_ITEM_RE.match(line):
            day_items[current_day] = day_items.get(current_day, 0) + 1

    for day, count in day_items.items():
        if count < 4:
            errors.append(
                f'{day}时间线仅{count}条，需≥4条，'
                f'且每条须含具体事件（HH:MM 格式），请读 messages.json 回溯该天。'
            )
    return errors


def check_achievement_table(sections: dict) -> list:
    """检查5：成就表格无空获得者行"""
    errors = []
    for title, content in sections.items():
        if '成就' in title:
            # 找表格行，检查获得者列（第2列）是否为空/无
            for line in content.splitlines():
                if not line.strip().startswith('|'):
                    continue
                cols = [c.strip() for c in line.split('|')]
                # cols[0] 为空（左边界），cols[1] 勋章，cols[2] 获得者
                if len(cols) < 4:
                    continue
                obtainer = cols[2]
                if obtainer in ('无', '—', '-', ''):
                    award = cols[1]
                    errors.append(
                        f'成就「{award}」获得者为空，请直接删除该行，不要保留。'
                    )
    return errors


def check_topic_distribution(sections: dict) -> list:
    """检查6：数据卡片含话题分布"""
    errors = []
    card_section = None
    for title, content in sections.items():
        if '数据卡片' in title or '数据概览' in title:
            card_section = content
            break
    if card_section is None:
        # 在全文开头找
        return []
    if '话题分布' not in card_section:
        errors.append(
            '数据卡片缺少话题分布，请读 messages.json 归纳本周期聊了哪些主题，'
            '每主题一句毒舌总结，格式：- 【话题名】简评。'
        )
    return errors


def main():
    if len(sys.argv) < 4:
        print('用法：python analyzer/verify_report.py <report.md> <messages.json> <sender_map.json>')
        sys.exit(1)

    report_path = Path(sys.argv[1])
    messages_path = Path(sys.argv[2])
    sender_map_path = Path(sys.argv[3])

    if not report_path.exists():
        print(f'[ERROR] 报告文件不存在：{report_path}')
        sys.exit(1)
    if not messages_path.exists():
        print(f'[ERROR] messages.json 不存在：{messages_path}')
        sys.exit(1)
    if not sender_map_path.exists():
        print(f'[ERROR] sender_map.json 不存在：{sender_map_path}，请先完成步骤5a（读取经验库并输出该文件）')
        sys.exit(1)

    report_text = report_path.read_text(encoding='utf-8')
    messages = load_messages(messages_path)
    _, name_to_wxid = load_sender_map(sender_map_path)
    year = infer_year(messages)
    sections = parse_report_sections(report_text)

    all_errors = []

    errors = check_oscar_citations(sections, messages, name_to_wxid, year)
    all_errors.extend(errors)

    errors = check_citation_authenticity(report_text, messages, name_to_wxid, year)
    all_errors.extend(errors)

    errors = check_hot_search_citations(sections)
    all_errors.extend(errors)

    errors = check_timeline(sections)
    all_errors.extend(errors)

    errors = check_achievement_table(sections)
    all_errors.extend(errors)

    errors = check_topic_distribution(sections)
    all_errors.extend(errors)

    if all_errors:
        print(f'[verify_report] 发现 {len(all_errors)} 个问题，请修正后重新验证：\n')
        for i, e in enumerate(all_errors, 1):
            print(f'{i}. {e}')
        sys.exit(1)
    else:
        print('[verify_report] 全部验证通过 ✓')
        sys.exit(0)


if __name__ == '__main__':
    main()
