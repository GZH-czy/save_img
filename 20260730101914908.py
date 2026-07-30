#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
图片批量转换与压缩工具
支持格式: JPG, PNG, WEBP, AVIF, GIF, BMP, TIFF, ICO, JFIF
功能: 批量转换格式、压缩大小、调整尺寸、保持原结构

使用方式:
  1. 直接运行（自动扫描当前目录所有图片转为 WebP）:
     python img_compress.py
  
  2. 指定参数运行:
     python img_compress.py -i ./images -f webp -q 85
"""

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageOps
from PIL.ExifTags import TAGS
import concurrent.futures
from typing import Tuple, Optional, List

# ================================================================
#  配置（可修改）
# ================================================================

DEFAULT_CONFIG = {
    # 输出质量（1-100，WebP/JPEG 有效）
    'quality': 85,
    # 最大宽度（None 表示不缩放）
    'max_width': None,
    # 最大高度（None 表示不缩放）
    'max_height': None,
    # 是否保持原图比例
    'preserve_ratio': True,
    # 是否保留 EXIF 信息
    'keep_exif': False,
    # 输出目录（None 表示在原目录创建 compressed 文件夹）
    'output_dir': None,
    # 是否覆盖已存在的文件
    'overwrite': False,
    # 并发线程数
    'workers': 4,
    # 是否递归处理子目录
    'recursive': True,
}

# 支持的输入格式（包含 .jfif）
SUPPORTED_INPUT = {
    '.jpg', '.jpeg', '.png', '.webp', '.avif',
    '.gif', '.bmp', '.tiff', '.tif', '.ico', '.jfif'
}

# 输出格式映射
OUTPUT_EXTENSIONS = {
    'jpg': '.jpg',
    'jpeg': '.jpg',
    'png': '.png',
    'webp': '.webp',
    'avif': '.avif',
    'gif': '.gif',
    'bmp': '.bmp',
    'tiff': '.tiff',
    'ico': '.ico',
    'jfif': '.jpg',  # JFIF 转为 JPG
}


# ================================================================
#  核心功能
# ================================================================

class ImageProcessor:
    def __init__(self, config: dict):
        self.config = {**DEFAULT_CONFIG, **config}
        self.stats = {
            'total': 0,
            'processed': 0,
            'failed': 0,
            'skipped': 0,
            'size_before': 0,
            'size_after': 0,
        }

    def get_output_path(self, input_path: Path, output_format: str) -> Path:
        """生成输出文件路径"""
        output_dir = self.config['output_dir']
        if output_dir:
            out_dir = Path(output_dir)
        else:
            # 在原目录创建 compressed 文件夹
            out_dir = input_path.parent / 'compressed'

        # 保持子目录结构
        if self.config['recursive']:
            try:
                rel_path = input_path.parent.relative_to(input_path.parent.parent) if input_path.parent.parent else Path('.')
                out_dir = out_dir / rel_path
            except ValueError:
                pass

        # 生成新文件名（保留原名，只改扩展名）
        stem = input_path.stem
        ext = OUTPUT_EXTENSIONS.get(output_format, '.jpg')
        output_path = out_dir / f"{stem}{ext}"

        return output_path

    def compress_image(self, input_path: Path, output_path: Path) -> Tuple[bool, str]:
        """处理单张图片"""
        try:
            # 读取图片
            with Image.open(input_path) as img:
                original_size = os.path.getsize(input_path)

                # 转换模式（处理透明背景）
                if img.mode in ('RGBA', 'LA', 'P'):
                    # PNG 保持透明度
                    if output_path.suffix.lower() in ('.jpg', '.jpeg'):
                        # JPEG 不支持透明，白色背景
                        background = Image.new('RGB', img.size, (255, 255, 255))
                        if img.mode == 'P':
                            img = img.convert('RGBA')
                        background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                        img = background
                    elif output_path.suffix.lower() in ('.webp', '.avif'):
                        # WebP/AVIF 支持透明
                        if img.mode != 'RGBA':
                            img = img.convert('RGBA')
                else:
                    # 确保 RGB 模式
                    if img.mode not in ('RGB', 'L'):
                        img = img.convert('RGB')

                # 调整尺寸
                max_w = self.config['max_width']
                max_h = self.config['max_height']
                if max_w or max_h:
                    ratio = 1.0
                    if max_w and img.width > max_w:
                        ratio = max_w / img.width
                    if max_h and img.height * ratio > max_h:
                        ratio = max_h / img.height
                    if ratio < 1:
                        new_size = (int(img.width * ratio), int(img.height * ratio))
                        img = img.resize(new_size, Image.Resampling.LANCZOS)

                # 保存图片
                output_path.parent.mkdir(parents=True, exist_ok=True)

                save_kwargs = {
                    'quality': self.config['quality'],
                    'optimize': True,
                }

                # 格式特定参数
                ext = output_path.suffix.lower()
                if ext in ('.jpg', '.jpeg'):
                    save_kwargs['subsampling'] = 0
                    save_kwargs['progressive'] = True
                elif ext == '.png':
                    save_kwargs.pop('quality', None)
                    save_kwargs['compress_level'] = 6
                elif ext == '.webp':
                    save_kwargs['method'] = 6
                elif ext == '.avif':
                    save_kwargs['speed'] = 6
                elif ext == '.gif':
                    save_kwargs.pop('quality', None)

                # 处理 GIF 特殊逻辑
                if ext == '.gif' and getattr(img, 'is_animated', False):
                    img.save(output_path, **save_kwargs)
                else:
                    img.save(output_path, **save_kwargs)

                # 统计
                compressed_size = os.path.getsize(output_path)
                self.stats['size_before'] += original_size
                self.stats['size_after'] += compressed_size

                reduction = (1 - compressed_size / original_size) * 100
                return True, f"{original_size/1024:.1f}KB → {compressed_size/1024:.1f}KB ({reduction:.1f}% 减少)"

        except Exception as e:
            return False, f"错误: {str(e)}"

    def process_file(self, file_path: Path, output_format: str) -> dict:
        """处理单个文件"""
        result = {
            'file': str(file_path),
            'status': 'skipped',
            'message': '',
            'output': '',
        }

        # 检查输入格式
        if file_path.suffix.lower() not in SUPPORTED_INPUT:
            result['message'] = f'不支持的格式: {file_path.suffix}'
            self.stats['skipped'] += 1
            return result

        # 生成输出路径
        output_path = self.get_output_path(file_path, output_format)

        # 检查是否已存在
        if output_path.exists() and not self.config['overwrite']:
            result['message'] = '已存在，跳过'
            self.stats['skipped'] += 1
            return result

        # 压缩
        success, msg = self.compress_image(file_path, output_path)

        if success:
            result['status'] = 'success'
            result['message'] = msg
            result['output'] = str(output_path)
            self.stats['processed'] += 1
        else:
            result['status'] = 'failed'
            result['message'] = msg
            self.stats['failed'] += 1

        self.stats['total'] += 1
        return result

    def find_images(self, input_path: Path) -> List[Path]:
        """递归查找所有图片文件"""
        files = []
        
        if input_path.is_file():
            if input_path.suffix.lower() in SUPPORTED_INPUT:
                files = [input_path]
            return files
        
        if not self.config['recursive']:
            # 不递归：只查找当前目录
            for ext in SUPPORTED_INPUT:
                for f in input_path.glob(f"*{ext}"):
                    if f.is_file():
                        files.append(f)
        else:
            # 递归：查找所有子目录
            for ext in SUPPORTED_INPUT:
                for f in input_path.glob(f"**/*{ext}"):
                    if f.is_file():
                        files.append(f)
        
        return files

    def process_directory(self, input_path: Path, output_format: str) -> List[dict]:
        """处理整个目录"""
        results = []

        # 收集所有图片文件
        files = self.find_images(input_path)

        if not files:
            print(f"⚠️  在 {input_path} 中未找到图片文件")
            print(f"   支持的格式: {', '.join(sorted(SUPPORTED_INPUT))}")
            return results

        print(f"📁 找到 {len(files)} 个图片文件")
        print(f"📤 输出格式: {output_format.upper()}")
        print(f"📊 质量: {self.config['quality']}")
        if self.config['max_width'] or self.config['max_height']:
            print(f"📐 最大尺寸: {self.config['max_width']}x{self.config['max_height']}")
        print("-" * 50)

        # 并发处理
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.config['workers']) as executor:
            futures = {
                executor.submit(self.process_file, f, output_format): f
                for f in files
            }

            for i, future in enumerate(concurrent.futures.as_completed(futures), 1):
                result = future.result()
                results.append(result)

                # 实时输出进度
                status_icon = "✅" if result['status'] == 'success' else "⚠️" if result['status'] == 'skipped' else "❌"
                print(f"[{i}/{len(files)}] {status_icon} {Path(result['file']).name}: {result['message']}")

        return results

    def print_summary(self):
        """打印统计信息"""
        print("-" * 50)
        print("📊 处理完成统计:")
        print(f"   ✅ 成功: {self.stats['processed']}")
        print(f"   ⚠️  跳过: {self.stats['skipped']}")
        print(f"   ❌ 失败: {self.stats['failed']}")
        print(f"   📦 总计: {self.stats['total']}")

        if self.stats['size_before'] > 0:
            before_mb = self.stats['size_before'] / (1024 * 1024)
            after_mb = self.stats['size_after'] / (1024 * 1024)
            reduction = (1 - self.stats['size_after'] / self.stats['size_before']) * 100
            print(f"   💾 压缩前: {before_mb:.2f} MB")
            print(f"   💾 压缩后: {after_mb:.2f} MB")
            print(f"   📉 节省: {reduction:.1f}%")
        print("=" * 50)


# ================================================================
#  命令行界面
# ================================================================

def main():
    parser = argparse.ArgumentParser(
        description="图片批量转换与压缩工具\n无参数运行时，自动扫描当前目录所有图片并转换为 WebP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 直接运行（自动扫描当前目录所有图片转为 WebP）
  python img_compress.py

  # 指定输入目录
  python img_compress.py -i ./images -f webp

  # 转为 JPG，质量 90，最大宽度 1200px
  python img_compress.py -i images -f jpg -q 90 -w 1200

  # 转为 PNG，输出到指定目录
  python img_compress.py -i images -f png -o ./output

  # 处理单张图片
  python img_compress.py -i photo.png -f webp -o ./compressed

  # 不递归子目录
  python img_compress.py -i images -f webp --no-recursive
        """
    )

    parser.add_argument('-i', '--input', type=str, default=None,
                       help='输入文件或目录路径 (默认: 当前目录)')
    parser.add_argument('-f', '--format', choices=['jpg', 'jpeg', 'png', 'webp', 'avif', 'gif', 'bmp', 'tiff', 'ico'],
                       default='webp', help='输出格式 (默认: webp)')
    parser.add_argument('-q', '--quality', type=int, default=85, choices=range(1, 101),
                       help='质量 (1-100, 默认: 85)')
    parser.add_argument('-w', '--max-width', type=int, default=None,
                       help='最大宽度 (保持比例)')
    parser.add_argument('-H', '--max-height', type=int, default=None,
                       help='最大高度 (保持比例)')
    parser.add_argument('-o', '--output', type=str, default=None,
                       help='输出目录 (默认: 原目录/compressed)')
    parser.add_argument('--overwrite', action='store_true',
                       help='覆盖已存在的文件')
    parser.add_argument('--no-recursive', action='store_true',
                       help='不递归处理子目录')
    parser.add_argument('--workers', type=int, default=4,
                       help='并发线程数 (默认: 4)')

    args = parser.parse_args()

    # 构建配置
    config = {
        'quality': args.quality,
        'max_width': args.max_width,
        'max_height': args.max_height,
        'output_dir': args.output,
        'overwrite': args.overwrite,
        'workers': args.workers,
        'recursive': not args.no_recursive,
    }

    # ⭐ 如果没有指定输入路径，默认使用当前目录
    if args.input is None:
        input_path = Path.cwd()
        print("📂 未指定输入目录，自动扫描当前目录")
    else:
        input_path = Path(args.input)

    if not input_path.exists():
        print(f"❌ 错误: {input_path} 不存在")
        sys.exit(1)

    # 创建处理器
    processor = ImageProcessor(config)

    # 执行处理
    print("=" * 50)
    print("🖼️  图片批量转换与压缩工具")
    print("=" * 50)
    print(f"📂 输入目录: {input_path.absolute()}")

    results = processor.process_directory(input_path, args.format)

    # 打印总结
    processor.print_summary()

    # 如果有失败，返回非零退出码
    if processor.stats['failed'] > 0:
        sys.exit(1)


if __name__ == '__main__':
    main()