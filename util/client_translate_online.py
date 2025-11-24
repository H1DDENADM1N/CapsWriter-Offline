import json
import httpx
from util.config import ClientConfig as Config
from util.config import DeepLXConfig as DeepLX

def translate_online(text):
    data = {
        "text": text,
        "source_lang": "auto",
        "target_lang": Config.online_translate_target_languages,
    }
    
    # 将字典转为 JSON 字符串
    post_data = json.dumps(data)
    
    try:
        # 超时时间改为 5 秒，防止长时间卡死
        response = httpx.post(url=DeepLX.api, data=post_data, timeout=15)
        r = response.text
        
        # 检查是否返回了空数据 (解决 char 0 报错)
        if not r or not r.strip():
            print("【错误】服务端返回内容为空")
            return "【翻译失败：服务未响应】"

        # 尝试解析 JSON (解决 char 4 报错)
        try:
            data = json.loads(r)
        except json.JSONDecodeError:
            print(f"【错误】无法解析 JSON，返回内容: {r[:50]}...") # 只打印前50个字符
            return f"【翻译失败：返回格式错误】"

        # 处理业务逻辑
        if data.get("code") != 200:
            # 返回错误信息
            return f"【错误 {data.get('code')}】: {data.get('message')}"
            
        # 获取翻译结果
        alternatives = data.get("alternatives", [])
        if alternatives:
            return alternatives[0]
        else:
            return data.get("data", "【翻译结果为空】")

    except httpx.TimeoutException:
        return "【翻译超时：网络连接过慢】"
    except httpx.RequestError as e:
        return f"【网络请求失败】：{e}"
    except Exception as e:
        return f"【未知错误】：{e}"

if __name__ == "__main__":
    print(f"API地址: {DeepLX.api}")
    text = "有朋自远方来，不亦乐乎"
    print("正在测试翻译...")
    online_trans_text = translate_online(text)
    print(f"结果: {online_trans_text}")
