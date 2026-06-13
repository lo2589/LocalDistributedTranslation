"""
Local Distributed Translation - Client Package

一行调用本地分布式翻译 Master 节点。

安装:
    pip install localtrans

使用:
    from localtrans import translate
    print(translate("Hello world", target_lang="zh"))
"""

from .client import translate, TranslatorClient, TranslationResult

__version__ = "0.1.0"
__all__ = ["translate", "TranslatorClient", "TranslationResult"]
