import json
import warnings

import opencc
import websockets
from loguru import logger

from util.check_libretranslate_service import check_libretranslate_service
from util.client.ai_optimize_language_expression import ai_optimize_language_expression
from util.client.check_websocket import check_websocket
from util.client.cosmic import Cosmic, console
from util.client.hot_sub import hot_sub
from util.client.rename_audio import rename_audio
from util.client.strip_punc import strip_punc
from util.client.type_result import type_result
from util.client.welcome import handle_welcome_message
from util.client.write_md import write_md
from util.config import ClientConfig as Config
from util.safe_logger import init_logging

if not Cosmic.transcribe_subtitles:
    from util.client.translate_offline import translate_offline

    if check_libretranslate_service():
        from util.client.translate_online_libretranslate import translate_online
    else:
        from util.client.translate_online import translate_online

warnings.filterwarnings("ignore")


async def recv_result():
    if not await check_websocket():
        return

    init_logging()

    with console.resize(width=49):
        console.rule("[green]连接成功")

    console.print(
        f"   客户端 WebSocket ID: [cyan]{Cosmic.websocket.id}[/cyan]\n", style="yellow"
    )

    try:
        # 先接收服务端的欢迎消息
        if not await handle_welcome_message():
            console.print("[bold red]无法建立连接或接收欢迎消息[/bold red]")
            return

        # 继续接收和处理音频识别结果
        while True:
            # 接收消息
            message = await Cosmic.websocket.recv()
            message = json.loads(message)
            asr_text = message["text"]
            delay = message["time_complete"] - message["time_submit"]

            # 控制台输出
            console.print(f"    转录时延：{delay:.2f}s")
            # console.print(f"    识别结果：[green]{asr_text}")

            # text 用于打字
            # asr_text 用于录音文件命名和写入 md
            text = asr_text

            # AI优化语言表达
            ai_optimized_done = False
            if Config.enable_ai_optimize_language_expression:
                console.print(
                    f"正在 AI 优化（{Config.ai_provider} {Config.prompt_style_selection}）..."
                )
                ai_optimized_text, ai_delay = ai_optimize_language_expression(text)
            else:
                ai_optimized_text = asr_text
            if text != ai_optimized_text:
                ai_optimized_done = True
                text = ai_optimized_text

            # 消除末尾标点
            text = strip_punc(text)
            asr_text = strip_punc(asr_text)

            # 热词替换
            text = hot_sub(text)
            asr_text = hot_sub(asr_text)

            # 简繁转换
            convert_to_traditional_chinese_done = False
            converter = opencc.OpenCC(Config.opencc_converter)
            traditional_text = converter.convert(text)
            traditional_asr_text = converter.convert(asr_text)
            convert_to_traditional_chinese_done = True

            # 离线翻译
            offline_translate_done = False
            if Cosmic.offline_translate_needed and not Cosmic.transcribe_subtitles:
                offline_translated_text = await translate_offline(text)
                offline_translate_done = True
                Cosmic.offline_translate_needed = False

            # 在线翻译
            online_translate_done = False
            if Cosmic.online_translate_needed and not Cosmic.transcribe_subtitles:
                online_translated_text = translate_online(text)
                online_translate_done = True
                Cosmic.online_translate_needed = False

            if Config.save_audio:
                # 重命名录音文件
                try:
                    file_audio = rename_audio(
                        message["task_id"], asr_text, message["time_start"]
                    )
                except Exception:
                    file_audio = None
            else:
                file_audio = None

            if Config.save_markdown:
                # 记录写入 md 文件
                match Config.convert_to_traditional_chinese_main:
                    case "繁":
                        write_md(
                            traditional_asr_text,
                            traditional_text,
                            message["time_start"],
                            file_audio,
                        )
                    case _:
                        write_md(
                            asr_text,
                            text,
                            message["time_start"],
                            file_audio,
                        )

            # 控制台输出
            if ai_optimized_done:
                console.print(f"    AI优化时延：{ai_delay:.2f}s")
                console.print(f"    AI优化结果：[green]{text}")
            if offline_translate_done:
                console.print(f"    离线翻译结果：[green]{offline_translated_text}")
            if online_translate_done:
                console.print(f"    在线翻译结果：[green]{online_translated_text}")
            if convert_to_traditional_chinese_done and Cosmic.opposite_state:
                console.print(f"    简繁转换结果：[green]{traditional_text}")
            console.line()

            # 打字
            if offline_translate_done:
                await type_result(offline_translated_text)
                offline_translate_done = False
            elif online_translate_done:
                await type_result(online_translated_text)
                online_translate_done = False
            elif convert_to_traditional_chinese_done:
                # 根据'简/繁'转换设定,来选择输出内容的逻辑
                if Config.enable_double_click_opposite_state:
                    match Config.convert_to_traditional_chinese_main:
                        case "繁":
                            if Cosmic.opposite_state:
                                await type_result(text)
                            else:
                                await type_result(traditional_text)
                        case _:
                            if Cosmic.opposite_state:
                                await type_result(traditional_text)
                            else:
                                await type_result(text)
                else:
                    await type_result(text)
                convert_to_traditional_chinese_done = False

            # 清空变量
            asr_text = ""
            text = ""
            traditional_asr_text = ""
            traditional_text = ""
            online_translated_text = ""
            offline_translated_text = ""
            ai_optimized_done = False
            convert_to_traditional_chinese_done = False
            offline_translate_done = False
            online_translate_done = False
            Cosmic.opposite_state = False
    except websockets.ConnectionClosedError:
        with console.resize(width=49):
            console.rule("[red]连接断开")
        init_logging()
        logger.error("连接断开，WebSocket连接关闭错误。")
    except websockets.ConnectionClosedOK:
        with console.resize(width=49):
            console.rule("[red]连接断开")
        init_logging()
        logger.error("连接断开，WebSocket连接正常关闭。")
    except Exception as e:
        init_logging()
        logger.error(f"接收识别结果时出错: {e}")
    finally:
        return


if __name__ == "__main__":
    None
