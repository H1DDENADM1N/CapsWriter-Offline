import sys

from config import ModelPaths
from util.server_cosmic import console


def check_model():
    for key, path in ModelPaths.__dict__.items():
        if key.startswith("_"):
            continue
        if path.exists():
            continue
        console.print(
            f"""
    未能找到模型文件 

    未找到：{path}

    本服务端需要 SenseVoice 模型，
    请下载模型并放置到： {ModelPaths.model_dir} 
    
    下载地址在： https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html#sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17 

        """,
            style="bright_red",
        )
        input("按回车退出")
        sys.exit()
