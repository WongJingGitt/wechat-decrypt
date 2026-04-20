"""
metadata.py — 群聊消息元数据提取脚本（JSON版）

从 get_messages 输出的 JSON 文件中提取群聊统计信息，
生成 entertainment.py 可消费的 metadata.json。

用法:
    python analyzer/metadata.py <messages.json>

输出:
    与输入文件同目录，输出 metadata.json
"""

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def process(messages_path: Path) -> dict:
    with open(messages_path, "r", encoding="utf-8") as f:
        messages = json.load(f)

    if not messages:
        print("消息列表为空")
        return {}

    total = len(messages)
    senders = set()
    times = []

    # sender → {msg_count, reply_count, hourly_dist, content_types}
    sender_data: dict = defaultdict(lambda: {
        "msg_count": 0,
        "reply_count": 0,    # 被他人引用的次数
        "hourly_dist": defaultdict(int),
        "content_types": defaultdict(int),
    })

    events: dict = {
        "revokes": [],                    # [{sender, content, index}]
        "replies": defaultdict(list),     # sender → [{index, content, refer_fromusr}]
        "patpats": [],                    # [{patper, patpee, index}]
        "invites": [],                    # [{inviter, content, index}]
    }

    word_counter: dict = defaultdict(int)

    for idx, msg in enumerate(messages):
        sender = msg.get("sender", "") or ""
        msg_type = msg.get("type", "") or ""
        content = msg.get("content", "") or ""
        create_time = msg.get("create_time", "") or ""

        # 系统消息（撤回、邀请）通常 sender 为空，其他类型记为发言者
        is_user_msg = bool(sender) and msg_type not in ("系统消息", "系统通知")

        # 时间解析
        if create_time:
            try:
                dt = datetime.strptime(create_time, "%Y-%m-%d %H:%M:%S")
                times.append(create_time)
                if sender:
                    sender_data[sender]["hourly_dist"][dt.hour] += 1
            except ValueError:
                pass

        # 发言者计数（非系统消息）
        if is_user_msg:
            senders.add(sender)
            sender_data[sender]["msg_count"] += 1
            sender_data[sender]["content_types"][msg_type] += 1

        # ── 事件检测 ──────────────────────────────────────────────────

        # 撤回：type="系统消息" + content 含 "撤回了一条消息"
        if msg_type == "系统消息" and "撤回了一条消息" in content:
            # content 通常为 "某人撤回了一条消息"，sender 字段即撤回者 wxid
            events["revokes"].append({
                "sender": sender,
                "content": content,
                "index": idx,
            })

        # 引用/回复：type="引用消息"
        elif msg_type == "引用消息":
            refer_fromusr = msg.get("refer_fromusr", "") or ""
            events["replies"][sender].append({
                "index": idx,
                "content": content,
                "refer_fromusr": refer_fromusr,
                "refer_svrid": msg.get("refer_svrid", "") or "",
            })
            # 被引用者的 reply_count +1
            if refer_fromusr:
                sender_data[refer_fromusr]["reply_count"] += 1

        # 拍一拍：type="拍一拍"
        elif msg_type == "拍一拍":
            events["patpats"].append({
                "patper": msg.get("pat_from_username", "") or "",
                "patpee": msg.get("pat_ted_username", "") or "",
                "index": idx,
            })

        # 邀请入群：type="系统通知" + content 含 "邀请"
        elif msg_type == "系统通知" and "邀请" in content:
            # content 格式通常为 "A邀请B、C加入了群聊"
            m = re.match(r"^(.+?)邀请", content)
            inviter = m.group(1).strip() if m else (sender or content[:20])
            events["invites"].append({
                "inviter": inviter,
                "content": content,
                "index": idx,
            })

        # 词频统计（仅文本消息，长度 > 1）
        if msg_type == "文本消息" and len(content) > 1:
            words = re.findall(r"[\u4e00-\u9fa5]{2,}|[a-zA-Z]{3,}", content)
            for w in words:
                word_counter[w] += 1

    # ── 汇总 ──────────────────────────────────────────────────────────

    date_range = {}
    if times:
        date_range = {"start": min(times), "end": max(times)}

    sender_stats = {
        wxid: {
            "msg_count": d["msg_count"],
            "reply_count": d["reply_count"],
            "hourly_dist": dict(d["hourly_dist"]),
            "content_types": dict(d["content_types"]),
        }
        for wxid, d in sender_data.items()
        if wxid  # 跳过空 sender
    }

    top_words = [
        {"word": w, "count": c}
        for w, c in sorted(word_counter.items(), key=lambda x: x[1], reverse=True)[:50]
    ]

    metadata = {
        "total_messages": total,
        "total_lines": total,   # JSON 中无行号概念，与 total_messages 相同
        "unique_senders": len(senders),
        "date_range": date_range,
        "sender_stats": sender_stats,
        "events": {
            "revokes": events["revokes"],
            "replies": {k: v for k, v in events["replies"].items()},
            "patpats": events["patpats"],
            "invites": events["invites"],
        },
        "top_words": top_words,
    }

    output_path = messages_path.parent / "metadata.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"Metadata saved to: {output_path}")
    print(f"Total: {total} messages, {len(senders)} senders, "
          f"{len(events['revokes'])} revokes, "
          f"{sum(len(v) for v in events['replies'].values())} replies, "
          f"{len(events['patpats'])} patpats, "
          f"{len(events['invites'])} invites")
    return metadata


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python analyzer/metadata.py <messages.json>")
        sys.exit(1)
    process(Path(sys.argv[1]))
