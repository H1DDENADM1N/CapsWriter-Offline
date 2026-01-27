import time

from loguru import logger
from openai import OpenAI
from zai import ZhipuAiClient

from util.config import ClientConfig as Config


def ai_optimize_language_expression(text):
    prompt = ""
    match Config.prompt_style_selection:
        case "official":
            prompt = Config.prompt_official
        case "sweetheart":
            prompt = Config.prompt_sweetheart
        case "social":
            prompt = Config.prompt_social
        case "poetry":
            prompt = Config.prompt_poetry
        case "english":
            prompt = Config.prompt_english
        case "academic":
            prompt = Config.prompt_academic
        case "customer_service":
            prompt = Config.prompt_customer_service
        case "creative_writing":
            prompt = Config.prompt_creative_writing
        case _:
            print(
                f"不支持的 AI 提示风格：{Config.prompt_style_selection}，请在 offical、sweetheart、social、poetry、english、academic、customer_service、creative_writing 中选择。"
            )
            return text, 0.0
    if prompt == "":
        print("AI 提示语不能为空，请检查配置文件。")
        print(f"当前提示风格：{Config.prompt_style_selection}")
        return text, 0.0
    match Config.ai_provider:
        case "zhipuai":
            return zhipuai_optimize_language_expression(text, prompt)
        case "openai":
            return openai_optimize_language_expression(text, prompt)
        case _:
            print(
                f"不支持的 AI 提供商：{Config.ai_provider}，请在 openai / zhipuai 中选择。"
            )
            return text, 0.0


def zhipuai_optimize_language_expression(text, prompt):
    start = time.time()
    if Config.zhipuai_api_key == "":
        print("智谱AI API密钥为空，请设置智谱AI API密钥，或者关闭AI优化语言表达功能。")
        return text, time.time() - start
    if Config.zhipuai_model == "":
        print("智谱AI模型名称为空，请设置智谱AI模型名称，或者关闭AI优化语言表达功能。")
        return text, time.time() - start
    try:
        client = ZhipuAiClient(api_key=Config.zhipuai_api_key)
        response = client.chat.completions.create(
            model=Config.zhipuai_model,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                },
                {
                    "role": "assistant",
                    "content": "当然，我将对语音转录生成的文本进行校对和润色，使其更加流畅、准确和易读。",
                },
                {"role": "user", "content": text},
            ],
            thinking={
                "type": "disabled",  # 不启用深度思考模式
            },
            stream=False,  # 不启用流式输出
            max_tokens=4096,  # 最大输出 tokens
            temperature=0.7,  # 控制输出的随机性
        )
        # 获取回复
        optimized_text = response.choices[0].message.content
        # 消除换行符
        optimized_text = optimized_text.replace("\n", "")
        return optimized_text, time.time() - start
    except Exception as e:
        print(f"智谱AI优化语言表达时发生错误： {e}")

        logger.error(f"智谱AI优化语言表达时发生错误： {e}")
        return text, time.time() - start


def openai_optimize_language_expression(text, prompt):
    start = time.time()
    if Config.openai_api_key == "":
        print(
            "OpenAI API密钥为空，请设置OpenAI（兼容） API密钥，或者关闭AI优化语言表达功能。"
        )
        return text, time.time() - start
    if Config.openai_base_url == "":
        print(
            "OpenAI API基础URL为空，请设置OpenAI（兼容） API基础URL，或者关闭AI优化语言表达功能。"
        )
        return text, time.time() - start
    if Config.openai_model == "":
        print("OpenAI模型名称为空，请设置OpenAI模型名称，或者关闭AI优化语言表达功能。")
        return text, time.time() - start
    try:
        client = OpenAI(
            api_key=Config.openai_api_key,
            base_url=Config.openai_base_url,
        )
        response = client.chat.completions.create(
            model=Config.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": prompt,
                },
                {"role": "user", "content": text},
            ],
            stream=False,  # 不启用流式输出
        )
        # 获取回复
        optimized_text = response.choices[0].message.content
        # 消除换行符
        optimized_text = optimized_text.replace("\n", "")
        return optimized_text, time.time() - start
    except Exception as e:
        print(f"OpenAI优化语言表达时发生错误： {e}")

        logger.error(f"OpenAI优化语言表达时发生错误： {e}")
        return text, time.time() - start
