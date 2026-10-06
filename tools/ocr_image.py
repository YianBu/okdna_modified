"""用本机 ok 自带的 PP-OCRv5 识别图片里的文字（离线，模型随 onnxocr 包安装）。

用法:
    python tools/ocr_image.py <图片路径> [--max-side 2000] [--out 结果.txt]

输出: 每行 `x1,y1,x2,y2 <TAB> 置信度 <TAB> 文本`，按图片坐标（长边超过 --max-side 会先等比缩小）。

为什么要这么跑:
  - 助手看不到图片（视觉通道不可用），截图一律先 OCR 再说内容；
  - 引擎是系统 Python（ok 源码版用的那个）里随 ok 装好的 onnxocr；
  - 默认走 OpenVINO 后端（use_openvino=True，和 ok 源码版一致）；本机也装了
    onnxruntime，可用 --backend onnxruntime 切到 onnxocr 的默认后端做对照；
  - 终端是 GBK，中文直接打印会乱码，所以要 --out 写 UTF-8 文件再读。
"""
import argparse

import numpy as np
from PIL import Image
from onnxocr.onnx_paddleocr import ONNXPaddleOcr


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('image', help='图片路径')
    parser.add_argument('--max-side', type=int, default=2000, help='长边上限，超过则等比缩小')
    parser.add_argument('--backend', choices=['openvino', 'onnxruntime'], default='openvino',
                        help='推理后端：openvino（默认，和 ok 源码版一致）或 onnxruntime')
    parser.add_argument('--out', help='把结果写成 UTF-8 文件（终端是 GBK 时用它避免乱码）')
    args = parser.parse_args()

    lines = []
    img = Image.open(args.image).convert('RGB')
    lines.append(f'[image] {args.image} size={img.size}')
    if max(img.size) > args.max_side:
        img.thumbnail((args.max_side, args.max_side), Image.LANCZOS)
        lines.append(f'[image] resized to {img.size}')
    arr = np.array(img)[:, :, ::-1]  # RGB -> BGR

    ocr = ONNXPaddleOcr(use_openvino=args.backend == 'openvino')
    result = ocr.ocr(arr)
    items = result[0] if result else []
    lines.append(f'[ocr] {len(items)} boxes')
    for box, (text, score) in items:
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        lines.append(f'{int(min(xs))},{int(min(ys))},{int(max(xs))},{int(max(ys))}\t{score:.2f}\t{text}')

    for line in lines:
        print(line)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
