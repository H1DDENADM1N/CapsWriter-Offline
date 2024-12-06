from collections.abc import Iterable
from pathlib import Path


# 服务端配置
class ServerConfig:
    addr = '0.0.0.0'
    speech_recognition_port = '6016'
    offline_translate_port = '6017' # 离线翻译端口
    format_num = True  # 输出时是否将中文数字转为阿拉伯数字
    format_spell = True  # 输出时是否调整中英之间的空格 
    shrink_automatically_to_tray = True     # 启动后不显示主窗口，自动缩小至托盘
    only_run_once = True # 只允许运行一次，禁止多开
    in_the_meantime_start_the_client = True # 启动服务端的同时启动客户端
    in_the_meantime_start_the_client_and_run_as_admin = True    # 启动服务端的同时以管理员权限启动客户端
                                                                # 当某程序以管理员权限运行
                                                                # 可能会出现有识别结果但是却无法在那个程序输入文字的状况
                                                                # 例如：Listary、PixPin等
                                                                # 这是因为 start_client_gui.exe 默认以用户权限运行客户端
                                                                # 运行在用户权限的程序无法控制管理员权限的程序
                                                                # 你可以关闭用户权限运行的客户端
                                                                # 尝试使用 start_client_gui_admin.exe
                                                                # 以管理员权限运行客户端

# 客户端配置
class ClientConfig:
    addr = '127.0.0.1'          # Server 地址
    speech_recognition_port = '6016'               # Server 端口
    offline_translate_port = '6017' # 离线翻译端口
    offline_translate_port_gemma2b = '11434' # Gemma 2B 离线翻译端口
    speech_recognition_shortcut     = 'caps lock'  # 控制录音的快捷键，默认是 CapsLock
    offline_translate_shortcut          = 'left shift'          # 控制离线翻译的快捷键，默认是 Left Shift，按住Left Shift再按 CapsLock进行离线翻译
    offline_translate_and_replace_the_selected_text_shortcut = 'ctrl + alt + p' # 控制离线翻译将光标选中的中文翻译并替换为英文的快捷键，光标选择中文文本，按下 ctrl + alt + p 快捷键，替换中文为英文
                                                                        # 如果未选中任何文字,会将剪贴板的文字翻译为英文，并粘贴
    online_translate_shortcut   = 'right shift'         # 控制在线翻译的快捷键，默认是 Right Shift，按住Right Shift再按 CapsLock进行在线翻译
                                                    # 在线翻译基于 DeepLX，过于频繁的请求可能导致 IP 被封
                                                    # 如果出现429错误，则表示你的IP被DeepL暂时屏蔽了，请不要在短时间内频繁请求。
    online_translate_target_languages = 'JA'            # 在线翻译目标语言
                                                    # 常用的 EN JA RU ，更多选择参考 https://www.deepl.com/docs-api/translate-text
    online_translate_and_replace_the_selected_text_shortcut = 'ctrl + alt + [' # 控制在线翻译将光标选中的中文翻译并替换为 在线翻译目标语言 的快捷键，光标选择中文文本，按下 ctrl + alt + [ 快捷键，替换中文为 在线翻译目标语言
                                                                                # 如果未选中任何文字,会将剪贴板的文字翻译为英文，并粘贴
    use_search_selected_text_with_everything_function = True # 设置是否启用 使用 everything 搜索选中的文字
    search_selected_text_with_everything_shortcut = 'ctrl + alt + f'    # 调用 everything 搜索光标选中的字符
                                                                        # 使用前需先安装 everything，https://www.voidtools.com/zh-cn/downloads/
    everything_exe_path = 'C:\Program Files\Everything\Everything.exe'  # 设置 everything 可执行文件位置
    hold_mode    = True         # 长按模式，按下录音，松开停止，像对讲机一样用。
                                # 改为 False，则关闭长按模式，也就是单击模式
                                #       即：单击录音，再次单击停止
                                #       且：长按会执行原本的单击功能
    suppress     = False        # 是否阻塞按键事件（让其它程序收不到这个按键消息）
    restore_key  = True         # 录音完成，松开按键后，是否自动再按一遍，以恢复 CapsLock 或 Shift 等按键之前的状态
    threshold    = 0.3          # 按下快捷键后，触发语音识别的时间阈值
    paste        = True         # 是否以写入剪切板然后模拟 Ctrl-V 粘贴的方式输出结果
    restore_clipboard_after_paste = True         # 模拟粘贴后是否恢复剪贴板

    save_audio = True           # 是否保存录音文件
    save_markdown = True        # 是否将记录写入 md 文件
    audio_name_len = 20         # 将录音识别结果的前多少个字存储到录音文件名中，建议不要超过200
    reduce_audio_files = True # 如果用户已安装 ffmpeg ，调用 ffmpeg 录音时输出 mp3 格式的音频文件，大大减小文件体积，减少磁盘占用

    trash_punc = '，。,.'        # 识别结果要消除的末尾标点

    hot_zh = True               # 是否启用中文热词替换，中文热词存储在 hot_zh.txt 文件里
    多音字 = True                  # True 表示多音字匹配
    声调  = False                 # False 表示忽略声调区别，这样「黄章」就能匹配「慌张」

    hot_en   = True             # 是否启用英文热词替换，英文热词存储在 hot_en.txt 文件里
    hot_rule = True             # 是否启用自定义规则替换，自定义规则存储在 hot_rule.txt 文件里
    hot_kwd  = True             # 是否启用关键词日记功能，自定义关键词存储在 keyword.txt 文件里

    mic_seg_duration = 15           # 麦克风听写时分段长度：15秒
    mic_seg_overlap = 2             # 麦克风听写时分段重叠：2秒

    file_seg_duration = 25           # 转录文件时分段长度
    file_seg_overlap = 2             # 转录文件时分段重叠
    mute_other_audio = True              # 录音时静音其他音频播放
    pause_other_audio = True             # 录音时暂停其他音频播放
    arabic_year_number = True                 # 将****年 大写汉字替换为阿拉伯数字****年，例如一八四八年 替换为1848年
    shrink_automatically_to_tray = False     # 启动后不显示主窗口，自动缩小至托盘
    only_run_once = True # 只允许运行一次，禁止多开
    only_enable_microphones_when_pressed_record_shortcut = True     # 只在按下录音快捷键时启用麦克风
                                                                    # 建议启用，有些蓝牙耳机录音时无法播放
                                                                    # 而且启用后，切换默认麦克风也不用重启客户端
                                                                    # 比如从蓝牙耳机换回笔记本电脑默认麦克风
                                                                    # 缺点就是输入的时候可能会慢些
                                                                    # 毕竟要先建立与麦克风的连接
    vscode_exe_path = 'C:\SSS\VSCode\Code - Insiders.exe'   # 设置 VSCode 可执行文件位置
                                                            # 用于通过客户端托盘图标右键菜单项View 子菜单项
                                                            # 🤓 Open Home Folder With VSCode 
                                                            # 使用 VSCode 快速打开 CapsWriter 主目录
                                                            # 方便调试
    hint_while_recording_at_cursor_position = True  # 是否启用 跟随鼠标光标位置的新版输入状态提示功能
    convert_to_traditional_chinese = False          # 是否启用简繁体中文转换
    convert_to_traditional_chinese_main = '繁'      # `简/繁` 中文作为主要输出
    enable_double_click_opposite_state = True       # 是否启用,双击`录音键`临时转换 `简/繁` 体中文输出的功能
    opencc_converter = "s2t.json"                   # OpenCC转换器
                                                    # s2t.json Simplified Chinese to Traditional Chinese 簡體到繁體
                                                    # t2s.json Traditional Chinese to Simplified Chinese 繁體到簡體
                                                    # s2tw.json Simplified Chinese to Traditional Chinese (Taiwan Standard) 簡體到臺灣正體
                                                    # tw2s.json Traditional Chinese (Taiwan Standard) to Simplified Chinese 臺灣正體到簡體
                                                    # s2hk.json Simplified Chinese to Traditional Chinese (Hong Kong Standard) 簡體到香港繁體（香港小學學習字詞表標準）
                                                    # hk2s.json Traditional Chinese (Hong Kong Standard) to Simplified Chinese 香港繁體（香港小學學習字詞表標準）到簡體
                                                    # s2twp.json Simplified Chinese to Traditional Chinese (Taiwan Standard) with Taiwanese idiom 簡體到繁體（臺灣正體標準）並轉換爲臺灣常用詞彙
                                                    # tw2sp.json Traditional Chinese (Taiwan Standard) to Simplified Chinese with Mainland Chinese idiom 繁體（臺灣正體標準）到簡體並轉換爲中國大陸常用詞彙
                                                    # t2tw.json Traditional Chinese (OpenCC Standard) to Taiwan Standard 繁體（OpenCC 標準）到臺灣正體
                                                    # t2hk.json Traditional Chinese (OpenCC Standard) to Hong Kong Standard 繁體（OpenCC 標準）到香港繁體（香港小學學習字詞表標準）
                                                    # t2jp.json Traditional Chinese Characters (Kyūjitai) to New Japanese Kanji (Shinjitai) 繁體（OpenCC 標準，舊字體）到日文新字體
                                                    # jp2t.json New Japanese Kanji (Shinjitai) to Traditional Chinese Characters (Kyūjitai) 日文新字體到繁體（OpenCC 標準，舊字體）


class DeepLXConfig:
    online_translate_port = '1188'
    exe_path = Path() / 'deeplx_windows_amd64.exe'
    api = "http://127.0.0.1:1188/translate"

class ModelPaths:
    model_dir = Path() / 'models'
    paraformer_path = Path() / 'models' / 'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17' / 'model.int8.onnx'   # 语音模型
    tokens_path = Path() / 'models' / 'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17' / 'tokens.txt'
    # punc_model_dir = Path() / 'models' / 'punc_ct-transformer_cn-en'    # 标点模型
    opus_mt_dir = Path() / 'models' / 'Helsinki-NLP--opus-mt-zh-en'     # 离线翻译模型


class ParaformerArgs:
    model = f'{ModelPaths.paraformer_path}'
    tokens = f'{ModelPaths.tokens_path}'
    num_threads = 6
    sample_rate = 16000
    # feature_dim = 80
    # decoding_method = 'greedy_search'
    use_itn = True
    language = "auto"
    debug = False
    provider = "cpu"


