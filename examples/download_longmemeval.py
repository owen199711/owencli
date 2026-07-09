"""下载 LongMemEval-Cleaned 数据集到本地。

数据集已迁移到 longmemeval-cleaned（原始版本已被废弃）。
文件以 JSON 格式直接托管在 Hugging Face，无需 datasets 库。
"""
import json
import sys
import os
from pathlib import Path

try:
    import requests
except ImportError:
    print("请先安装 requests: pip install requests")
    exit(1)

BASE_URL = "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main"
FILES = {
    "longmemeval_oracle": "longmemeval_oracle.json",      # 15 MB — 标准答案
    "longmemeval_s": "longmemeval_s_cleaned.json",        # 278 MB — small 版
    "longmemeval_m": "longmemeval_m_cleaned.json",        # 2.75 GB — medium 版（可选）
}
TARGET_DIR = Path("data/longmemeval")


def download_file(name: str, filename: str) -> bool:
    url = f"{BASE_URL}/{filename}"
    dest = TARGET_DIR / name
    if dest.exists() and dest.stat().st_size > 1000:
        print(f"  [跳过] {name} 已存在 ({dest.stat().st_size // 1024 // 1024} MB)")
        return True

    print(f"  [下载] {filename} ({url}) ...", end=" ", flush=True)
    try:
        resp = requests.get(url, timeout=300, stream=True)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded * 100 // total
                    print(f"\r  [下载] {filename} ... {pct}% ({downloaded // 1024 // 1024} MB)", end="", flush=True)
        print(f"\r  [完成] {filename} ({downloaded // 1024 // 1024} MB)")
        return True
    except Exception as e:
        print(f"\n  [失败] {filename}: {e}")
        return False


def inspect_oracle(path: Path):
    """检查 oracle 文件结构并输出统计。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    print(f"\n  Oracle 文件结构:")
    print(f"    顶层类型: {type(data).__name__}")

    if isinstance(data, dict):
        print(f"    顶层 keys: {list(data.keys())[:10]}")
        # 可能是 {"data": [...]} 或类似结构
        for key in data:
            val = data[key]
            if isinstance(val, list):
                print(f"    key '{key}' 包含 {len(val)} 条记录")
                if val:
                    sample = val[0]
                    print(f"    样例子段: {list(sample.keys()) if isinstance(sample, dict) else type(sample).__name__}")
                break
    elif isinstance(data, list):
        print(f"    包含 {len(data)} 条记录")
        if data:
            sample = data[0]
            print(f"    样例子段: {list(sample.keys()) if isinstance(sample, dict) else type(sample).__name__}")


def main():
    print("=" * 60)
    print("  LongMemEval-Cleaned 数据集下载")
    print("  仓库: https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned")
    print("=" * 60)
    print()

    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    # 下载文件
    results = {}
    for name, filename in FILES.items():
        ok = download_file(name, filename)
        results[name] = ok
        print()

    # 汇总
    success = sum(1 for v in results.values() if v)
    print(f"下载完成: {success}/{len(results)} 个文件成功")

    # 检查 oracle 结构
    oracle_path = TARGET_DIR / "longmemeval_oracle"
    if oracle_path.exists():
        print("\n--- Oracle 数据结构探查 ---")
        try:
            inspect_oracle(oracle_path)
        except Exception as e:
            print(f"  探查失败: {e}")

    print(f"\n数据目录: {TARGET_DIR.absolute()}")


if __name__ == "__main__":
    main()
