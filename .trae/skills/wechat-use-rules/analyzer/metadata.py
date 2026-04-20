import re
import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict

class ChatMetadata:
    def __init__(self, raw_content: str):
        self.raw_content = raw_content
        self.lines = raw_content.strip().split('\n')

    def parse_message(self, line):
        pattern = r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] \[([^\]]+)\](.+?)(?=\[\d{4}-\d{2}-\d{2}|$)'
        match = re.match(pattern, line.strip())
        if not match:
            return None
        time_str, sender_with_nick, content = match.groups()
        sender_match = re.match(r'\[([^\]]+)\](.+)', sender_with_nick)
        if sender_match:
            sender = sender_match.group(1)
            nickname = sender_match.group(2)
        else:
            sender = sender_with_nick
            nickname = sender_with_nick
        return {
            'time': time_str,
            'time_obj': datetime.strptime(time_str, '%Y-%m-%d %H:%M'),
            'sender': sender.strip(),
            'nickname': nickname.strip(),
            'content': content.strip(),
            'line_num': self.lines.index(line) + 1
        }

    def extract(self):
        messages = []
        events = {
            'revokes': [],
            'invites': [],
            'patpats': [],
            'replies': []
        }
        sender_stats = defaultdict(lambda: {
            'msg_count': 0,
            'content_types': {'text': 0, 'image': 0, 'video': 0, 'voice': 0, 'link': 0, 'miniprogram': 0, 'emoji': 0},
            'hourly_dist': defaultdict(int),
            'mentioned_by': [],
            'replied_to': []
        })
        content_type_counter = defaultdict(int)
        hourly_dist = defaultdict(int)
        daily_dist = defaultdict(int)
        mentions = []
        reply_chains = defaultdict(list)
        word_freq = defaultdict(int)
        interaction_matrix = defaultdict(lambda: defaultdict(int))

        last_sender = None
        for i, line in enumerate(self.lines):
            stripped = line.strip()
            if stripped.startswith('↳ 回复'):
                reply_match = re.match(r'↳ Reply (.+?):', stripped) or re.match(r'↳ 回复 (.+?):', stripped)
                if reply_match:
                    sender = last_sender if last_sender else 'unknown'
                    reply_chains[sender].append({
                        'line': i + 1,
                        'content_preview': stripped[:80]
                    })
                continue

            msg = self.parse_message(line)
            if msg:
                messages.append(msg)
                sender = msg['sender']
                last_sender = sender
                sender_stats[sender]['msg_count'] += 1

                hour = msg['time_obj'].hour
                sender_stats[sender]['hourly_dist'][hour] += 1
                hourly_dist[hour] += 1
                daily_dist[msg['time_obj'].strftime('%Y-%m-%d')] += 1

                content = msg['content']

                if '[图片]' in content or 'local_id=' in content:
                    sender_stats[sender]['content_types']['image'] += 1
                    content_type_counter['image'] += 1
                elif '[视频]' in content:
                    sender_stats[sender]['content_types']['video'] += 1
                    content_type_counter['video'] += 1
                elif '[语音]' in content:
                    sender_stats[sender]['content_types']['voice'] += 1
                    content_type_counter['voice'] += 1
                elif '[链接' in content:
                    sender_stats[sender]['content_types']['link'] += 1
                    content_type_counter['link'] += 1
                elif '[小程序]' in content:
                    sender_stats[sender]['content_types']['miniprogram'] += 1
                    content_type_counter['miniprogram'] += 1
                elif '[动画表情]' in content:
                    sender_stats[sender]['content_types']['emoji'] += 1
                    content_type_counter['emoji'] += 1
                else:
                    sender_stats[sender]['content_types']['text'] += 1
                    content_type_counter['text'] += 1

                    words = re.findall(r'[\u4e00-\u9fff]+', content)
                    for word in words:
                        if len(word) >= 2:
                            word_freq[word] += 1

                at_matches = re.findall(r'@(\S+?)(?:\s|$|：|:)', content)
                for at in at_matches:
                    mentions.append({'from': sender, 'to': at, 'line': msg['line_num']})
                    sender_stats[msg['sender']]['mentioned_by'].append(at)

                if content.startswith('↳ 回复'):
                    reply_chains[sender].append({
                        'line': msg['line_num'],
                        'content_preview': content[:80]
                    })
                    sender_stats[sender]['replied_to'].append(content)

        for line in self.lines:
            if '撤回了一条消息' in line:
                sender = None
                line_idx = self.lines.index(line) + 1
                for msg in messages:
                    if abs(msg['line_num'] - line_idx) <= 3:
                        sender = msg['sender']
                        break
                if sender:
                    events['revokes'].append({'sender': sender, 'line': line_idx})

            if '拍了拍' in line:
                match = re.search(r'"([^"]+)"\s*拍了拍\s*"([^"]+)"', line)
                if match:
                    patper = match.group(1).strip()
                    patpee = match.group(2).strip().rstrip(']').rstrip('：').rstrip(':')
                    for tag in ['说：', '说:', '表示：', '表示:']:
                        patpee = patpee.replace(tag, '')
                    events['patpats'].append({
                        'patper': patper,
                        'patpee': patpee,
                        'line': self.lines.index(line) + 1
                    })
                    interaction_matrix[patper][patpee] += 1

            if '邀请' in line and '加入了群聊' in line:
                match = re.search(r'"([^"]+)"邀请"([^"]+)"加入了群聊', line)
                if match:
                    inviter = match.group(1)
                    invitee = match.group(2)
                    events['invites'].append({
                        'inviter': inviter,
                        'invitee': invitee,
                        'line': self.lines.index(line) + 1
                    })

        top_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:50]

        metadata = {
            'total_messages': len(messages),
            'total_lines': len(self.lines),
            'unique_senders': len(sender_stats),
            'date_range': {
                'start': messages[0]['time'] if messages else None,
                'end': messages[-1]['time'] if messages else None
            },
            'tips': {
                'report_generation': [
                    '⚠️ 重要：这是元数据文件，仅包含统计数据',
                    '娱乐向报告必须读取同目录下的 entertainment_data.json 获取完整指导',
                    'entertainment_data.json 包含 tips.must_read，要求读取 WechaUseRules 经验库',
                    '报告生成前必须按以下顺序阅读：',
                    '  1. entertainment_data.json 的 tips.must_read',
                    '  2. .trae/skills/wechauserules/experience/contacts/ 目录下所有联系人画像',
                    '  3. entertainment_data.json 的 rankings 和 events',
                    '  4. entertainment_data.json 的 sender_stats',
                    '  5. entertainment_data.json 的 top_words（用于挖掘群聊关键词）',
                    '  6. raw.md 原始聊天记录（用于名场面还原）',
                    '不要直接基于 metadata.json 生成报告，必须以 entertainment_data.json 为准'
                ]
            },
            'content_type_dist': dict(content_type_counter),
            'hourly_dist': dict(hourly_dist),
            'daily_dist': dict(daily_dist),
            'top_words': top_words,
            'sender_stats': {k: {
                'msg_count': v['msg_count'],
                'content_types': dict(v['content_types']),
                'hourly_dist': dict(v['hourly_dist']),
                'mention_count': len(v['mentioned_by']),
                'reply_count': len(v['replied_to'])
            } for k, v in sender_stats.items()},
            'events': {
                'revokes': events['revokes'],
                'invites': events['invites'],
                'patpats': events['patpats'],
                'replies': {k: v for k, v in reply_chains.items()}
            },
            'mentions': mentions,
            'interaction_matrix': {k: dict(v) for k, v in interaction_matrix.items()}
        }

        return metadata

    def save(self, output_path: Path):
        metadata = self.extract()
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        return metadata

if __name__ == '__main__':
    import sys
    import json
    import glob

    if len(sys.argv) < 2:
        print("Usage: python metadata.py <raw.md path or data_dir>")
        sys.exit(1)

    input_path = Path(sys.argv[1])

    if input_path.is_dir():
        raw_files = sorted(input_path.glob('raw*.md'), key=lambda p: p.stem)
        if not raw_files:
            print(f"No raw*.md found in {input_path}")
            sys.exit(1)

        arg_files = sorted(input_path.glob('.raw*_arg'), key=lambda p: p.stem)
        if arg_files:
            def parse_arg_num(filename):
                stem = filename.stem
                if stem == 'raw':
                    return 0
                parts = stem.split('_')
                if len(parts) >= 2 and parts[1].isdigit():
                    return int(parts[1])
                return -1

            sorted_args = sorted(arg_files, key=parse_arg_num)
            for i, arg_file in enumerate(sorted_args):
                try:
                    with open(arg_file, 'r', encoding='utf-8') as f:
                        arg = json.load(f)
                    expected_offset = i * 9999
                    if arg.get('limit') != 9999:
                        print(f"错误：{arg_file.name} 的 limit 必须为 9999，当前为 {arg.get('limit')}")
                        print("提示：必须按每页 9999 条累加获取，直到返回'无消息记录'")
                        for f in raw_files:
                            f.unlink()
                        for a in arg_files:
                            a.unlink()
                        print(f"已删除 {len(raw_files)} 个 raw 文件和 {len(arg_files)} 个 arg 文件，请重新获取")
                        sys.exit(1)
                    if arg.get('offset') != expected_offset:
                        print(f"错误：{arg_file.name} 的 offset 必须为 {expected_offset}，当前为 {arg.get('offset')}")
                        print("提示：必须按 offset 0, 9999, 19999... 递增获取")
                        for f in raw_files:
                            f.unlink()
                        for a in arg_files:
                            a.unlink()
                        print(f"已删除 {len(raw_files)} 个 raw 文件和 {len(arg_files)} 个 arg 文件，请重新获取")
                        sys.exit(1)
                except json.JSONDecodeError:
                    pass

            n_raw = len([f for f in raw_files if f.stem == 'raw' or f.stem.startswith('raw_')])
            last_expected_offset = (n_raw - 1) * 9999
            last_arg_file = sorted_args[-1]
            if last_arg_file:
                try:
                    with open(last_arg_file, 'r', encoding='utf-8') as f:
                        last_arg = json.load(f)
                    if last_arg.get('offset') == last_expected_offset:
                        print(f"提示：已获取 {n_raw} 个分页文件，最后一个 offset={last_arg.get('offset')}")
                        print("如果还有更多记录，请继续获取 offset={} ...".format(last_expected_offset + 9999))
                except json.JSONDecodeError:
                    pass

        combined_lines = []
        for f in raw_files:
            combined_lines.extend(f.read_text(encoding='utf-8').strip().split('\n'))
        combined_content = '\n'.join(combined_lines)
        task_id = input_path.name
        output_path = input_path / 'metadata.json'
    else:
        combined_content = input_path.read_text(encoding='utf-8')
        task_id = input_path.parent.name
        output_path = input_path.parent / 'metadata.json'

    extractor = ChatMetadata(combined_content)
    metadata = extractor.save(output_path)

    print(f"Metadata saved to: {output_path}")
    print(f"Total messages: {metadata['total_messages']}")
    print(f"Unique senders: {metadata['unique_senders']}")