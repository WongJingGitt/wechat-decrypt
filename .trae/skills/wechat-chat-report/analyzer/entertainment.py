import json
from pathlib import Path
from collections import defaultdict

def process(data_dir: Path):
    meta_path = data_dir / 'metadata.json'
    raw_path = data_dir / 'raw.md'
    if not meta_path.exists():
        raise FileNotFoundError(f"metadata.json not found in {data_dir}")
    with open(meta_path, 'r', encoding='utf-8') as f:
        metadata = json.load(f)

    raw_lines = raw_path.read_text(encoding='utf-8').split('\n') if raw_path.exists() else []

    sender_stats = metadata['sender_stats']
    revokes = metadata['events']['revokes']
    replies = metadata['events']['replies']
    patpats = metadata['events']['patpats']
    invites = metadata['events']['invites']

    sorted_senders = sorted(sender_stats.items(), key=lambda x: x[1]['msg_count'], reverse=True)

    revoke_by_sender = defaultdict(int)
    for r in revokes:
        revoke_by_sender[r['sender']] += 1

    late_night = []
    for sender, stats in sender_stats.items():
        lh_count = sum(c for h, c in stats['hourly_dist'].items() if h in ['0', '1', '2', '3', '4', '5'])
        if lh_count > 0:
            late_night.append({'sender': sender, 'count': lh_count})

    reply_ranking = []
    for sender, reply_list in replies.items():
        reply_ranking.append({'sender': sender, 'count': len(reply_list), 'lines': [r['line'] for r in reply_list[:5]]})
    reply_ranking.sort(key=lambda x: x['count'], reverse=True)

    link_ranking = []
    for sender, stats in sender_stats.items():
        link_count = stats['content_types'].get('link', 0) + stats['content_types'].get('miniprogram', 0) + stats['content_types'].get('video', 0)
        if link_count > 0:
            link_ranking.append({'sender': sender, 'count': link_count})
    link_ranking.sort(key=lambda x: x['count'], reverse=True)

    emoji_ranking = []
    for sender, stats in sender_stats.items():
        emoji_count = stats['content_types'].get('emoji', 0)
        emoji_ranking.append({'sender': sender, 'count': emoji_count})
    emoji_ranking.sort(key=lambda x: x['count'], reverse=True)

    inviter_count = defaultdict(int)
    for inv in invites:
        inviter_count[inv['inviter']] += 1
    invite_ranking = [{'sender': k, 'count': v} for k, v in inviter_count.items()]
    invite_ranking.sort(key=lambda x: x['count'], reverse=True)

    saonuo_ranking = []
    for sender, stats in sender_stats.items():
        score = stats['msg_count'] + stats['reply_count'] + revoke_by_sender[sender] * 5
        saonuo_ranking.append({
            'sender': sender,
            'score': score,
            'msgs': stats['msg_count'],
            'replies': stats['reply_count'],
            'revokes': revoke_by_sender[sender]
        })
    saonuo_ranking.sort(key=lambda x: x['score'], reverse=True)

    revoke_ranking = [{'sender': k, 'count': v} for k, v in revoke_by_sender.items()]
    revoke_ranking.sort(key=lambda x: x['count'], reverse=True)

    patpat_sent = defaultdict(int)
    patpat_pairs = []
    for p in patpats:
        patpat_sent[p['patper']] += 1
        patpat_pairs.append({'from': p['patper'], 'to': p['patpee'], 'line': p['line']})
    patpat_ranking = [{'sender': k, 'count': v} for k, v in patpat_sent.items()]
    patpat_ranking.sort(key=lambda x: x['count'], reverse=True)

    data = {
        'type': 'entertainment',
        'tips': {
            'must_read': [
                '⛔ 步骤5a【强制】读取 ../wechauserules/experience/contacts/ 所有联系人画像，输出 data/任务ID/sender_map.json（格式：{"wxid": "昵称"}），没有画像的成员用 rankings 里出现的标识符作为昵称',
                '⛔ 步骤5b【强制】读取 data/任务ID/messages.json 完整原文，所有引用必须来自原文，不得编造',
                '⛔ 引用格式必须严格遵守：**昵称**（M月D日 HH:MM）：「原话」，缺少时间戳的引用视为无效',
                '引用消息（events.replies）含 refer_svrid，需查被引用原文时调用 get_message_by_server_id 工具',
                '⛔ 步骤5c【强制】生成报告后运行：python analyzer/verify_report.py report/任务ID/entertainment.md data/任务ID/messages.json data/任务ID/sender_map.json，非0禁止结束'
            ],
            'report_style': [
                '名场面必须用 ul+li 格式贴出参与者原话（含时间戳），再附毒舌点评，每个奖项≥2条引用',
                '热搜榜必须列关键参与者和至少1条真实原话引用，不得只写词频',
                '时间线每天≥4条节点，精确到小时，禁止写"全天持续活跃"此类空话',
                '成就系统：获得者数据为空的勋章直接跳过，不写入表格',
                '数据卡片：写话题分布（读 messages.json 归纳），不写图片/表情数量'
            ]
        },
        'basic': {
            'total_messages': metadata['total_messages'],
            'total_lines': metadata['total_lines'],
            'unique_senders': metadata['unique_senders'],
            'date_range': metadata['date_range']
        },
        'rankings': {
            'top_senders': [{'sender': s, 'count': stats['msg_count']} for s, stats in sorted_senders],
            'late_night': late_night,
            'replies': reply_ranking,
            'links': link_ranking,
            'emoji': emoji_ranking,
            'invites': invite_ranking,
            'saonuo': saonuo_ranking,
            'revokes': revoke_ranking,
            'patpats': patpat_ranking
        },
        'events': {
            'revokes': revokes,
            'patpats': patpat_pairs,
            'invites': invites,
            'replies': replies
        },
        'sender_stats': sender_stats,
        'top_words': metadata['top_words']
    }

    output_path = data_dir / 'entertainment_data.json'
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Entertainment data saved to: {output_path}")
    return data

if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python entertainment.py <data_dir>")
        sys.exit(1)
    process(Path(sys.argv[1]))
