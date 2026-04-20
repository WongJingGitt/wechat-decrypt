"""
stats.py — 联系人基线指标提取脚本

专供经验库建设使用，负责从原始消息 JSON 中提取可量化的基线指标。
LLM 不参与此脚本的计算过程。

用法:
    python analyzer/stats.py <messages.json> [--wxid <wxid>]

输出:
    与输入文件同目录，输出 stats_{date}.json
"""

import json
import sys
import re
from pathlib import Path
from collections import defaultdict
from datetime import datetime


def extract_stats(messages: list, target_wxid: str = None) -> dict:
    """
    从消息列表中提取某个 wxid 的基线指标。
    如果 target_wxid 为 None，则提取所有发言者的汇总指标。
    """
    if target_wxid:
        msgs = [m for m in messages if m.get("sender") == target_wxid]
    else:
        msgs = messages

    if not msgs:
        return {"error": "no messages found", "wxid": target_wxid}

    # ── 基础统计 ──────────────────────────────────────────
    total = len(msgs)
    dates = set()
    hourly = defaultdict(int)
    type_counter = defaultdict(int)
    msg_lengths = []
    burst_groups = []  # 连发分组

    last_sender = None
    last_time = None
    current_burst = 1

    for m in sorted(msgs, key=lambda x: x.get("create_time", "")):
        ct = m.get("create_time", "")
        sender = m.get("sender", "")
        content = m.get("content", "") or ""
        msg_type = m.get("type", "文本消息")

        # 日期
        if ct:
            try:
                dt = datetime.strptime(ct, "%Y-%m-%d %H:%M:%S")
                dates.add(dt.strftime("%Y-%m-%d"))
                hourly[dt.hour] += 1
            except ValueError:
                pass

        # 类型分布
        type_counter[msg_type] += 1

        # 消息长度（仅文本类）
        if msg_type in ("文本消息", "引用消息"):
            msg_lengths.append(len(content))

        # 连发分组（同一发送者60秒内连续发送算一组）
        if sender == last_sender and ct and last_time:
            try:
                t1 = datetime.strptime(last_time, "%Y-%m-%d %H:%M:%S")
                t2 = datetime.strptime(ct, "%Y-%m-%d %H:%M:%S")
                if (t2 - t1).total_seconds() <= 60:
                    current_burst += 1
                else:
                    burst_groups.append(current_burst)
                    current_burst = 1
            except ValueError:
                burst_groups.append(current_burst)
                current_burst = 1
        elif sender != last_sender:
            if current_burst > 0:
                burst_groups.append(current_burst)
            current_burst = 1

        last_sender = sender
        last_time = ct

    if current_burst > 0:
        burst_groups.append(current_burst)

    # ── 基线指标 ──────────────────────────────────────────
    active_days = len(dates) or 1
    daily_avg = round(total / active_days, 1)
    avg_len = round(sum(msg_lengths) / len(msg_lengths), 1) if msg_lengths else 0

    # 活跃时段分布（按小时，取 top3）
    hourly_sorted = sorted(hourly.items(), key=lambda x: x[1], reverse=True)
    peak_hours = [f"{h:02d}:00" for h, _ in hourly_sorted[:3]]

    # 活跃时段集中度（top3小时占比）
    peak_count = sum(c for _, c in hourly_sorted[:3])
    peak_ratio = round(peak_count / total * 100, 1) if total else 0

    # 媒体类型比例
    text_types = {"文本消息", "引用消息"}
    image_types = {"图片消息"}
    voice_types = {"语音消息"}
    video_types = {"视频消息"}
    emoji_types = {"表情消息"}

    def ratio(types):
        count = sum(type_counter.get(t, 0) for t in types)
        return round(count / total * 100, 1) if total else 0

    type_ratio = {
        "text": ratio(text_types),
        "image": ratio(image_types),
        "voice": ratio(voice_types),
        "video": ratio(video_types),
        "emoji": ratio(emoji_types),
        "other": round(100 - ratio(text_types) - ratio(image_types)
                       - ratio(voice_types) - ratio(video_types) - ratio(emoji_types), 1)
    }

    # 连发分布
    burst_dist = defaultdict(int)
    for b in burst_groups:
        key = str(b) if b < 5 else "5+"
        burst_dist[key] += 1

    # 回复延迟（引用消息，取创建时间与被引用时间差）
    reply_delays = []
    for m in msgs:
        if m.get("type") == "引用消息" and m.get("refer_svrid"):
            # 简化：通过对比前后消息时间估算，无法精确计算时跳过
            pass  # 需要被引用消息的时间，stats 阶段无法计算，留给 LLM 估算

    # ── 互动统计 ──────────────────────────────────────────
    all_senders = defaultdict(int)
    at_recv = defaultdict(int)
    at_send = defaultdict(int)
    revoke_count = 0

    for m in messages:  # 全量消息做互动统计
        sender = m.get("sender", "")
        msg_type = m.get("type", "")
        at_list = m.get("at_user_list") or []

        all_senders[sender] += 1

        if msg_type == "系统消息" and "撤回" in (m.get("content") or ""):
            revoke_count += 1

        if target_wxid:
            # 统计 target 被@次数
            if target_wxid in at_list:
                at_recv[sender] += 1
            # 统计 target 主动@次数
            if sender == target_wxid:
                for at in at_list:
                    at_send[at] += 1

    # 互动 Top5（与 target 互动最多的人）
    if target_wxid:
        interaction_counter = defaultdict(int)
        for m in messages:
            sender = m.get("sender", "")
            at_list = m.get("at_user_list") or []
            # target 发言中 @ 某人
            if sender == target_wxid:
                for at in at_list:
                    interaction_counter[at] += 1
            # 某人 @ target
            if target_wxid in at_list and sender != target_wxid:
                interaction_counter[sender] += 1
        top_interactions = sorted(interaction_counter.items(), key=lambda x: x[1], reverse=True)[:5]
    else:
        top_interactions = sorted(all_senders.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "wxid": target_wxid,
        "total_messages": total,
        "active_days": active_days,
        "daily_avg": daily_avg,
        "avg_msg_len": avg_len,
        "peak_hours": peak_hours,
        "peak_ratio_pct": peak_ratio,
        "hourly_dist": dict(sorted(hourly.items())),
        "type_ratio": type_ratio,
        "type_counts": dict(type_counter),
        "burst_dist": dict(burst_dist),
        "at_recv_count": sum(at_recv.values()),
        "at_send_count": sum(at_send.values()),
        "revoke_count": revoke_count,
        "top_interactions": [{"wxid": wxid, "count": cnt} for wxid, cnt in top_interactions],
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python stats.py <messages.json> [--wxid <wxid>]")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"File not found: {input_path}")
        sys.exit(1)

    # 解析 --wxid 参数
    target_wxid = None
    if "--wxid" in sys.argv:
        idx = sys.argv.index("--wxid")
        if idx + 1 < len(sys.argv):
            target_wxid = sys.argv[idx + 1]

    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    # 兼容两种格式：直接的消息数组，或包含 messages 字段的对象
    if isinstance(data, list):
        messages = data
    elif isinstance(data, dict) and "messages" in data:
        messages = data["messages"]
    else:
        print("Unsupported JSON format: expected array or {messages: []}")
        sys.exit(1)

    # 提取日期用于输出文件名
    date_str = input_path.stem.split("_")[0] if "_" in input_path.stem else input_path.stem

    stats = extract_stats(messages, target_wxid)

    output_path = input_path.parent / f"stats_{date_str}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"Stats written to: {output_path}")
    print(f"  Total messages : {stats['total_messages']}")
    print(f"  Active days    : {stats['active_days']}")
    print(f"  Daily avg      : {stats['daily_avg']}")
    print(f"  Avg msg length : {stats['avg_msg_len']} chars")
    print(f"  Peak hours     : {', '.join(stats['peak_hours'])} ({stats['peak_ratio_pct']}%)")


if __name__ == "__main__":
    main()
