"""
微信 MCP Server V2 - 结构化 JSON 工具集

与 mcp_server.py 完全独立，底层走 utils.message.MessageDB + MessageProcessor。

工具:
  search_contacts          按关键词模糊搜索联系人
  get_contact_name         按 wxid 查询显示名
  get_messages             获取时间段内全量消息，写入 JSON 文件
  get_message_by_server_id 按 server_id 查询单条消息（引用溯源）

运行:
  python mcp_server_v2.py
"""

import os
import sys
import json
from mcp.server.fastmcp import FastMCP

# 确保项目根目录在 sys.path，以便 utils 包和 decode_image 等模块可以正常 import
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils.message import MessageDB, MessageProcessor
from utils.contact import ContactDB

# ============ MCP 实例 ============

mcp = FastMCP("wechat-v2", instructions="微信数据结构化查询，所有消息返回 JSON 格式")

# 模块级单例，延迟连接 DB（MessageDB.all_db_connection 是 lazy property）
_message_db = MessageDB()
_processor = MessageProcessor()


# ============ 联系人工具 ============

@mcp.tool()
def search_contacts(keyword: str) -> str:
    """按关键词模糊搜索联系人，匹配范围：备注名、昵称、wxid、alias。

    Args:
        keyword: 搜索关键词
    Returns:
        JSON 数组，每项包含 wxid / remark / nick_name / alias
    """
    with ContactDB() as db:
        results = db.get_contact_by_keywords(keyword)
    return json.dumps(
        [
            {
                "wxid": c.username,
                "remark": c.remark,
                "nick_name": c.nick_name,
                "alias": c.alias,
            }
            for c in results
        ],
        ensure_ascii=False,
    )


@mcp.tool()
def get_contact_name(wxid: str) -> str:
    """按 wxid 查询联系人显示名（备注优先，无备注用昵称）。

    Args:
        wxid: 联系人或群聊的 wxid
    Returns:
        JSON 对象，包含 wxid / remark / nick_name / display_name
    """
    try:
        with ContactDB() as db:
            c = db.get_contact_by_wxid(wxid)
        return json.dumps(
            {
                "wxid": c.username,
                "remark": c.remark,
                "nick_name": c.nick_name,
                "display_name": c.format_name,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"error": str(e), "wxid": wxid}, ensure_ascii=False)


# ============ 消息工具 ============

@mcp.tool()
def get_messages(wxid: str, start_time: str, end_time: str, output_path: str) -> str:
    """获取指定会话在时间段内的全量消息，结果写入 JSON 文件。

    最小时间粒度为一天，start_time 和 end_time 必须是同一天（跨天请拆分为多次调用）。
    调用时会在 JSON 同级生成 .{stem}_arg 文件记录调用参数，可用 verify.py arg 验证。

    不分页，一次性返回时间范围内所有消息，保证数据完整性。
    每条消息为 format_message 结构化字典，包含：
      local_id / server_id / sender / create_time / type / content
      at_user_list / select_wxid（以及各消息类型的专有字段）

    Args:
        wxid:        联系人或群聊的 wxid
        start_time:  起始时间，格式 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS（必须与 end_time 同一天）
        end_time:    结束时间，格式 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS（必须与 start_time 同一天）
        output_path: 输出 JSON 文件的完整路径（目录不存在会自动创建）

    Returns:
        JSON 对象，包含文件路径、消息数量、wxid 和时间范围；时间范围超过1天时返回 error
    """
    from datetime import date as _date
    from dateutil import parser as _parser

    # ── 解析并验证时间范围 ──────────────────────────────────────────
    try:
        start_dt = _parser.parse(start_time)
        end_dt = _parser.parse(end_time)
    except Exception as e:
        return json.dumps({"error": f"时间格式无法解析: {e}"}, ensure_ascii=False)

    start_date = start_dt.date()
    end_date = end_dt.date()

    if end_date > start_date:
        return json.dumps(
            {
                "error": "时间范围超过1天，禁止调用。请按天拆分，每次只传同一天的 start_time 和 end_time。",
                "start_time": start_time,
                "end_time": end_time,
                "days": (end_date - start_date).days + 1,
            },
            ensure_ascii=False,
        )

    # ── 确保输出目录存在 ────────────────────────────────────────────
    abs_output = os.path.abspath(output_path)
    out_dir = os.path.dirname(abs_output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # ── 写入 _arg 文件（记录调用参数，供 verify.py 验证）──────────
    stem = os.path.splitext(os.path.basename(abs_output))[0]
    arg_path = os.path.join(out_dir, f".{stem}_arg")
    arg_data = {
        "wxid": wxid,
        "start_time": start_time,
        "end_time": end_time,
        "output_path": abs_output,
        "called_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(arg_path, "w", encoding="utf-8") as f:
        json.dump(arg_data, f, ensure_ascii=False, indent=2)

    # ── 拉取并写入消息 ──────────────────────────────────────────────
    messages = _message_db.get_messages(wxid, start_time, end_time)
    formatted = [_processor.process(msg) for msg in messages]

    with open(abs_output, "w", encoding="utf-8") as f:
        json.dump(formatted, f, ensure_ascii=False, indent=2)

    return json.dumps(
        {
            "path": abs_output,
            "arg_path": arg_path,
            "count": len(formatted),
            "wxid": wxid,
            "start_time": start_time,
            "end_time": end_time,
        },
        ensure_ascii=False,
    )


@mcp.tool()
def get_message_by_server_id(server_id: str, wxid: str) -> str:
    """按 server_id 查询单条消息，用于引用消息溯源。

    Args:
        server_id: 消息的 server_id（从引用消息的 refer_svrid 字段获取）
        wxid:      消息所在会话的 wxid

    Returns:
        JSON 对象，消息的 format_message 结构；找不到时返回 {"error": "..."}
    """
    msg = _message_db.get_message_by_server_id(server_id, wxid)
    if msg is None:
        return json.dumps(
            {"error": f"未找到 server_id={server_id}", "wxid": wxid},
            ensure_ascii=False,
        )
    return json.dumps(_processor.process(msg), ensure_ascii=False)


# ============ 启动 ============

if __name__ == "__main__":
    mcp.run()
