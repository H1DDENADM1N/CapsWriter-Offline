"""

https://share.lanol.cn/

云剪切板

*使用说明:

https://github.com/vastsa/FileCodeBox/blob/master/docs/api/index.md


"""

import json

import requests
from loguru import logger


class CloudClipboard:
    def __init__(self):
        self.upload_url = "https://share.lanol.cn/share/text/"
        self.download_url_template = "https://share.lanol.cn/#/?code={}"

    def post_data(self, text, expire_value=1, expire_style="day"):
        """
        上传文本到云剪切板
        :param text: 要上传的文本
        :param expire_value: 过期数值
        :param expire_style: 过期单位（day, week, month, year）
        :return: 分享链接
        """

        data = {
            "text": (None, text),
            "expire_value": (None, str(expire_value)),
            "expire_style": (None, expire_style),
        }

        try:
            response = requests.post(self.upload_url, files=data)
            response.raise_for_status()
            result = response.json()

            if result.get("code") == 200 and "detail" in result:
                code = result["detail"].get("code")
                if code:
                    url = self.download_url_template.format(code)
                    return url
            else:
                # print(f"上传失败: {result.get('message', '未知错误')}")
                logger.error(f"上传失败: {result.get('message', '未知错误')}")
                return None

        except requests.exceptions.RequestException as e:
            # print(f"网络错误: {e}")
            logger.error(f"网络错误: {e}")
            return None
        except json.JSONDecodeError as e:
            # print(f"解析响应失败: {e}")
            logger.error(f"解析响应失败: {e}")
            if "response" in locals():
                # print(f"响应内容: {response.text}")
                logger.error(f"响应内容: {response.text}")
            return None

    def get_data(self, url): ...


if __name__ == "__main__":
    text = "Hello https://share.lanol.cn/"

    url = CloudClipboard().post_data(text)
    print(f"{url}")
