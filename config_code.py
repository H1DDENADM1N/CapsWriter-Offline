class translation_format:
    # 双击离线翻译按键的输出格式
    config_code_offline = f'''
keyboard.write(offline_translated_text)
keyboard.write(" (")
keyboard.write(text)
keyboard.write(")")
    '''

    # 双击在线翻译按键的输出格式
    config_code_online = f'''
keyboard.write(online_translated_text)
keyboard.write(" (")
keyboard.write(text)
keyboard.write(")")
    '''


# 常用要素
"""
text : 初始语音文字(简体中文)
traditional_text : 繁体中文
offline_translated_text : 离线翻译文字
online_translated_text : 在线翻译文字
keyboard.write("[") : 符号 [
keyboard.press_and_release('enter') :  模拟按下以及弹起 回车按键
"""

"""
# 这是第一个例子:
keyboard.write(text)
keyboard.press_and_release('enter')
keyboard.write(offline_translated_text)

# 这是第一个例子的输出:
这是中文
It's Chinese.

# 这是第2个例子:
keyboard.write(offline_translated_text)
keyboard.write(" [")
keyboard.write(traditional_text)
keyboard.write("]")

# 这是第2个例子的输出:
It's Chinese. [這是中文]
"""
