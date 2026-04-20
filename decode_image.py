r"""
微信图片 .dat 文件解密模块

支持两种加密格式:
  - 旧格式: 单字节 XOR 加密，key 通过对比文件头与已知图片 magic bytes 自动检测
  - V2 格式 (2025-08+): AES-128-ECB + XOR 混合加密，需要从微信进程内存提取 AES key

V2 文件结构:
  [6B signature: 07 08 V2 08 07] [4B aes_size LE] [4B xor_size LE] [1B padding]
  [aligned_aes_size bytes AES-ECB] [raw_data] [xor_size bytes XOR]

文件路径格式:
  D:\xwechat_files\<wxid>\msg\attach\<md5(username)>\<YYYY-MM>\Img\<file_md5>[_t|_h].dat

映射链:
  message_*.db (local_id) → message_resource.db (packed_info 含 MD5) → .dat 文件 → 解密
"""

import os
import sys
import glob
import hashlib
import sqlite3
import struct
import json

# 加载配置
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(_SCRIPT_DIR, "config.json")
_cfg = {}
if os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, encoding="utf-8") as f:
        _cfg = json.load(f)

# V2 格式完整 magic (6 bytes)
V2_MAGIC = b'\x07\x08\x56\x32'       # 前 4 字节用于快速检测
V2_MAGIC_FULL = b'\x07\x08V2\x08\x07' # 完整 6 字节签名
V1_MAGIC_FULL = b'\x07\x08V1\x08\x07' # V1 签名 (固定 key)

# 常见图片格式的 magic bytes (按长度降序排列，避免短 magic 假阳性)
IMAGE_MAGIC = {
    'png': [0x89, 0x50, 0x4E, 0x47],
    'gif': [0x47, 0x49, 0x46, 0x38],
    'tif': [0x49, 0x49, 0x2A, 0x00],   # little-endian TIFF
    'webp': [0x52, 0x49, 0x46, 0x46],  # RIFF header
    'jpg': [0xFF, 0xD8, 0xFF],
    # BMP 只有 2 字节 magic，容易假阳性，需要额外验证
}


def is_v2_format(dat_path):
    """检测是否是微信 V2 加密格式 (2025-08+)"""
    try:
        with open(dat_path, 'rb') as f:
            magic = f.read(4)
        return magic == V2_MAGIC
    except (OSError, IOError):
        return False


def detect_xor_key(dat_path):
    """通过对比文件头和已知图片 magic bytes 自动检测 XOR key

    返回 key (int) 或 None。V2 格式文件返回 None。
    """
    with open(dat_path, 'rb') as f:
        header = f.read(16)

    if len(header) < 4:
        return None

    # V2 新格式无法用 XOR 解密
    if header[:4] == V2_MAGIC:
        return None

    # 先尝试 3+ 字节 magic 的格式（可靠匹配）
    for fmt, magic in IMAGE_MAGIC.items():
        key = header[0] ^ magic[0]
        match = True
        for i in range(1, len(magic)):
            if i >= len(header):
                break
            if (header[i] ^ key) != magic[i]:
                match = False
                break
        if match:
            return key

    # 最后尝试 BMP (2 字节 magic，需要额外验证)
    bmp_magic = [0x42, 0x4D]
    key = header[0] ^ bmp_magic[0]
    if len(header) >= 2 and (header[1] ^ key) == bmp_magic[1]:
        # 额外验证: XOR 解密后检查 BMP file size 和 offset 字段
        if len(header) >= 14:
            dec = bytes(b ^ key for b in header[:14])
            bmp_size = struct.unpack_from('<I', dec, 2)[0]
            bmp_offset = struct.unpack_from('<I', dec, 10)[0]
            file_size = os.path.getsize(dat_path)
            # BMP file_size 字段应与实际文件大小接近，offset 应在合理范围
            if (abs(bmp_size - file_size) < 1024 and 14 <= bmp_offset <= 1078):
                return key

    return None


def detect_image_format(header_bytes):
    """根据解密后的文件头检测图片格式"""
    if header_bytes[:3] == bytes([0xFF, 0xD8, 0xFF]):
        return 'jpg'
    if header_bytes[:4] == bytes([0x89, 0x50, 0x4E, 0x47]):
        return 'png'
    if header_bytes[:3] == b'GIF':
        return 'gif'
    if header_bytes[:2] == b'BM':
        return 'bmp'
    if header_bytes[:4] == b'RIFF' and len(header_bytes) >= 12 and header_bytes[8:12] == b'WEBP':
        return 'webp'
    if header_bytes[:4] == bytes([0x49, 0x49, 0x2A, 0x00]):
        return 'tif'
    return 'bin'


def v2_decrypt_file(dat_path, out_path=None, aes_key=None, xor_key=None):
    """解密 V2 格式 .dat 文件 (AES-ECB + XOR)

    Args:
        dat_path: V2 .dat 文件路径
        out_path: 输出路径 (None 则自动命名)
        aes_key: 16 字节 AES key (bytes 或 str)
        xor_key: XOR key (int, 默认从 config 读取)

    Returns:
        (output_path, format) 或 (None, None)
    """
    if aes_key is None:
        return None, None

    # 默认 XOR key 从 config 读取
    if xor_key is None:
        xor_key = _cfg.get("image_xor_key", 0x88)

    from Crypto.Cipher import AES

    # 确保 key 是 16 字节 bytes
    if isinstance(aes_key, str):
        aes_key = aes_key.encode('ascii')[:16]
    if len(aes_key) < 16:
        return None, None

    with open(dat_path, 'rb') as f:
        data = f.read()

    if len(data) < 15:
        return None, None

    # 解析 header
    sig = data[:6]
    if sig not in (V2_MAGIC_FULL, V1_MAGIC_FULL):
        return None, None

    aes_size, xor_size = struct.unpack_from('<LL', data, 6)

    # V1 用固定 key
    if sig == V1_MAGIC_FULL:
        aes_key = b'cfcd208495d565ef'  # md5("0")[:16]

    # AES 对齐: PKCS7 填充使密文长度是 16 的倍数
    aligned_aes_size = (aes_size + 15) // 16 * 16

    offset = 15
    if offset + aligned_aes_size > len(data):
        return None, None

    # AES-ECB 解密 (直接截取 aes_size 字节，不 unpad)
    aes_data = data[offset:offset + aligned_aes_size]
    try:
        cipher = AES.new(aes_key[:16], AES.MODE_ECB)
        dec_aes = cipher.decrypt(aes_data)[:aes_size]
    except (ValueError, KeyError):
        return None, None
    offset += aligned_aes_size

    # Raw 部分 (不加密)
    raw_end = len(data) - xor_size
    raw_data = data[offset:raw_end] if offset < raw_end else b''
    offset = raw_end

    # XOR 部分
    xor_data = data[offset:]
    dec_xor = bytes(b ^ xor_key for b in xor_data)

    decrypted = dec_aes + raw_data + dec_xor

    # wxgf (HEVC 裸流) 格式必须在 detect_image_format 前检测（后者会返回 'bin'）
    if decrypted[:4] == b'wxgf':
        fmt = 'hevc'
    else:
        fmt = detect_image_format(decrypted[:16])

    # 格式未识别 → AES key 错误（解密产生随机字节），直接失败
    if fmt == 'bin':
        return None, None

    # V2 格式已通过 aes_size / xor_size 字段精确编码各段长度，decrypted 就是完整图片。
    # 不需要搜索结束标记 —— 搜索反而会因 EXIF 内嵌缩略图的 FF D9 等在中间截断图片。
    #
    # 通过尾部特征校验 XOR key 是否正确（xor_size=0 时跳过，无 XOR 段无法验证）：
    if xor_size >= 2:
        if fmt == 'jpg' and decrypted[-2:] != bytes([0xFF, 0xD9]):
            # 末尾不是 FF D9 → XOR key 错误，拒绝写出乱码文件
            return None, None
        elif fmt == 'png' and b'IEND' not in decrypted[-12:]:
            # 末尾不含 IEND chunk → XOR key 错误
            return None, None

    if out_path is None:
        base = os.path.splitext(dat_path)[0]
        for suffix in ('_t', '_h'):
            if base.endswith(suffix):
                base = base[:-len(suffix)]
                break
        out_path = f"{base}.{fmt}"
    else:
        # 确保扩展名正确
        base, ext = os.path.splitext(out_path)
        if ext.lower() != f'.{fmt}':
            out_path = f"{base}.{fmt}"

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'wb') as f:
        f.write(decrypted)

    return out_path, fmt


def xor_decrypt_file(dat_path, out_path=None, key=None):
    """解密单个 .dat 文件，返回 (output_path, format)"""
    if key is None:
        key = detect_xor_key(dat_path)
    if key is None:
        return None, None

    with open(dat_path, 'rb') as f:
        data = f.read()

    decrypted = bytes(b ^ key for b in data)
    fmt = detect_image_format(decrypted[:16])

    if out_path is None:
        base = os.path.splitext(dat_path)[0]
        # 去掉 _t, _h 后缀
        for suffix in ('_t', '_h'):
            if base.endswith(suffix):
                base = base[:-len(suffix)]
                break
        out_path = f"{base}.{fmt}"

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'wb') as f:
        f.write(decrypted)

    return out_path, fmt


def decrypt_dat_file(dat_path, out_path=None, aes_key=None, xor_key=None, force_key=None):
    """智能解密 .dat 文件 (自动检测格式)

    Args:
        dat_path: .dat 文件路径
        out_path: 输出路径
        aes_key: V2 格式的 AES key (str 或 bytes, 16 字节)
        xor_key: XOR key (int, 默认从 config 读取)
        force_key: 强制使用的 key，如果传入则直接用此 key 解密

    Returns:
        (output_path, format) 或 (None, None)
    """
    if xor_key is None:
        xor_key = _cfg.get("image_xor_key", 0x88)

    if force_key:
        return v2_decrypt_file(dat_path, out_path, force_key, xor_key)

    with open(dat_path, 'rb') as f:
        head = f.read(6)

    if head == V2_MAGIC_FULL:
        return v2_decrypt_file(dat_path, out_path, aes_key, xor_key)

    if head == V1_MAGIC_FULL:
        return v2_decrypt_file(dat_path, out_path, b'cfcd208495d565ef', xor_key)

    return xor_decrypt_file(dat_path, out_path)


def extract_md5_from_packed_info(blob):
    """从 message_resource.db 的 packed_info (protobuf) 中提取文件 MD5

    格式: ... \\x12\\x22\\x0a\\x20 + 32 字节 ASCII hex MD5 ...
    """
    if not blob or not isinstance(blob, bytes):
        return None

    # 查找 protobuf 标记
    marker = b'\x12\x22\x0a\x20'
    idx = blob.find(marker)
    if idx >= 0 and idx + len(marker) + 32 <= len(blob):
        md5_bytes = blob[idx + len(marker): idx + len(marker) + 32]
        try:
            md5_str = md5_bytes.decode('ascii')
            # 验证是合法的 hex 字符串
            int(md5_str, 16)
            return md5_str
        except (UnicodeDecodeError, ValueError):
            pass

    # 备用方案：扫描 32 字节连续 hex 字符
    hex_chars = set(b'0123456789abcdef')
    i = 0
    while i <= len(blob) - 32:
        if blob[i] in hex_chars:
            candidate = blob[i:i+32]
            if all(b in hex_chars for b in candidate):
                try:
                    return candidate.decode('ascii')
                except UnicodeDecodeError:
                    pass
            i += 32
        else:
            i += 1

    return None


class ImageResolver:
    """封装从 local_id 到图片文件的完整解析链"""

    def __init__(self, wechat_base_dir, decoded_image_dir, cache, aes_key=None):
        """
        Args:
            wechat_base_dir: 微信数据根目录 (如 D:\\xwechat_files\\<wxid>)
            decoded_image_dir: 解密图片输出目录
            cache: DBCache 实例，用于解密 message_resource.db
            aes_key: V2 格式 AES key (可选，默认从 config.json 读取)
        """
        self.base_dir = wechat_base_dir
        self.attach_dir = os.path.join(wechat_base_dir, "msg", "attach")
        self.out_dir = decoded_image_dir
        self.cache = cache
        self.aes_key = aes_key if aes_key is not None else _cfg.get("image_aes_key")

    def get_image_md5(self, local_id):
        """通过 local_id 查 message_resource.db 获取图片文件 MD5"""
        path = self.cache.get("message/message_resource.db")
        if not path:
            return None

        conn = sqlite3.connect(path)
        try:
            row = conn.execute(
                "SELECT packed_info FROM MessageResourceInfo WHERE message_local_id = ?",
                (local_id,)
            ).fetchone()
            if row and row[0]:
                return extract_md5_from_packed_info(row[0])
        except Exception as e:
            pass
        finally:
            conn.close()

        return None

    def find_dat_files(self, username, file_md5):
        """在 attach 目录下查找对应的 .dat 文件

        路径: attach/<md5(username)>/<YYYY-MM>/Img/<file_md5>[_t|_h].dat
        """
        username_hash = hashlib.md5(username.encode()).hexdigest()
        search_base = os.path.join(self.attach_dir, username_hash)

        if not os.path.isdir(search_base):
            return []

        # 在所有月份目录下搜索
        results = []
        pattern = os.path.join(search_base, "*", "Img", f"{file_md5}*.dat")
        for p in glob.glob(pattern):
            results.append(p)

        return sorted(results)

    def decode_image(self, username, local_id, xml_md5=None):
        """完整流程：local_id → MD5 → .dat → 解密

        Args:
            username: 微信号/群号
            local_id: 消息 local_id
            xml_md5: 从消息 XML 中提取的 MD5（message_resource.db 查不到时使用）
        Returns:
            dict with keys: success, path, format, md5, error
        """
        file_md5 = self.get_image_md5(local_id)
        if not file_md5:
            # 回退：使用调用方从 XML 消息内容中提取的 MD5
            if xml_md5:
                file_md5 = xml_md5
            else:
                return {'success': False, 'error': f'无法从 message_resource.db 找到 local_id={local_id} 的图片信息'}

        dat_files = self.find_dat_files(username, file_md5)
        if not dat_files:
            return {'success': False, 'error': f'找不到 .dat 文件 (MD5={file_md5})', 'md5': file_md5}

        h_file = next((f for f in dat_files if f.endswith('_h.dat')), None)
        if h_file:
            selected = h_file
        else:
            selected = next((f for f in dat_files if not f.endswith('_t.dat')), dat_files[0])

        out_name = f"{file_md5}"
        out_path_base = os.path.join(self.out_dir, out_name)

        result_path, fmt = decrypt_dat_file(selected, f"{out_path_base}.tmp", self.aes_key)
        if not result_path:
            return {'success': False, 'error': f'解密失败，可能缺少有效的 V2 AES key (文件: {selected})', 'md5': file_md5}

        # 重命名为正确扩展名
        final_path = f"{out_path_base}.{fmt}"
        if result_path != final_path:
            if os.path.exists(final_path):
                os.unlink(final_path)
            os.rename(result_path, final_path)

        return {
            'success': True,
            'path': final_path,
            'format': fmt,
            'md5': file_md5,
            'source': selected,
            'size': os.path.getsize(final_path),
        }

    def list_chat_images(self, db_path, table_name, username, limit=20):
        """列出某个聊天中的所有图片消息"""
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute(f"""
                SELECT local_id, create_time
                FROM [{table_name}]
                WHERE local_type = 3
                ORDER BY create_time DESC
                LIMIT ?
            """, (limit,)).fetchall()
        except Exception as e:
            conn.close()
            return []
        conn.close()

        results = []
        for local_id, create_time in rows:
            file_md5 = self.get_image_md5(local_id)
            info = {
                'local_id': local_id,
                'create_time': create_time,
                'md5': file_md5,
            }
            if file_md5:
                dat_files = self.find_dat_files(username, file_md5)
                if dat_files:
                    info['dat_file'] = dat_files[0]
                    try:
                        info['size'] = os.path.getsize(dat_files[0])
                    except OSError:
                        pass
            results.append(info)

        return results


# ============ CLI 测试 ============

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python decode_image.py <dat_file> [output_file]")
        print("  解密单个 .dat 文件")
        print("  --debug   显示详细诊断信息（检测 AES/XOR key 有效性）")
        sys.exit(1)

    debug = '--debug' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--debug']
    dat_file = args[0]
    out_file = args[1] if len(args) > 1 else None

    if not os.path.exists(dat_file):
        print(f"文件不存在: {dat_file}")
        sys.exit(1)

    if debug:
        with open(dat_file, 'rb') as f:
            head = f.read(32)
        file_size = os.path.getsize(dat_file)
        print(f"文件大小: {file_size:,} bytes")
        print(f"文件头 (hex): {head.hex()}")
        if head[:6] == V2_MAGIC_FULL:
            aes_size, xor_size = struct.unpack_from('<LL', head, 6)
            aligned_aes = (aes_size + 15) // 16 * 16
            raw_size = file_size - 15 - aligned_aes - xor_size
            print(f"V2 格式: aes_size={aes_size}, xor_size={xor_size}, raw_size={raw_size}")
            print(f"配置 image_aes_key={_cfg.get('image_aes_key')!r}, image_xor_key=0x{_cfg.get('image_xor_key', 0x88):02X}")
            # 检测 AES key 效果
            from Crypto.Cipher import AES as _AES
            aes_key = _cfg.get("image_aes_key", "")
            if aes_key:
                with open(dat_file, 'rb') as f:
                    f.seek(15)
                    blk = f.read(16)
                cipher = _AES.new(aes_key.encode('ascii')[:16], _AES.MODE_ECB)
                dec16 = cipher.decrypt(blk)
                print(f"AES 解密首 16 字节: {dec16.hex()}  → 格式: {detect_image_format(dec16)}")
            # 检测 XOR key 效果
            xor_key = _cfg.get("image_xor_key", 0x88)
            with open(dat_file, 'rb') as f:
                f.seek(-2, 2)
                tail = f.read(2)
            dec_tail = bytes(b ^ xor_key for b in tail)
            print(f"文件末 2 字节: {tail.hex()} XOR 0x{xor_key:02X} → {dec_tail.hex()} (期望 ffd9 for JPEG)")
        elif head[:6] == V1_MAGIC_FULL:
            print("V1 格式（固定 key）")
        else:
            detected_key = detect_xor_key(dat_file)
            print(f"旧格式 XOR, 检测 key: 0x{detected_key:02X}" if detected_key is not None else "旧格式 XOR, 无法检测 key")
        print("---")

    result_path, fmt = decrypt_dat_file(dat_file, out_file)
    if result_path:
        size = os.path.getsize(result_path)
        print(f"解密成功: {result_path}")
        print(f"格式: {fmt}, 大小: {size:,} bytes")
    else:
        print("解密失败")
        sys.exit(1)
