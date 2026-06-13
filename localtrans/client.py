"""
Local Distributed Translation - Client Implementation
"""

from typing import Optional, Dict, Iterator
import httpx

from .config import get_master_url


class TranslationResult:
    """翻译结果封装"""

    def __init__(self, data: dict):
        self.translated_text: str = data.get("translated_text", "")
        self.model: str = data.get("model", "")
        self.slave_name: Optional[str] = data.get("slave_name")
        self.raw: dict = data

    def __repr__(self):
        return f"TranslationResult(text={self.translated_text!r}, model={self.model!r})"


class TranslatorClient:
    """
    分布式翻译 Master 客户端

    Args:
        master_url: Master 服务地址，默认从环境变量/配置读取
        timeout: HTTP 超时（秒）
    """

    def __init__(self, master_url: Optional[str] = None, timeout: float = 60.0):
        self.master_url = (master_url or get_master_url()).rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout, trust_env=False)

    def health(self) -> dict:
        """Master 健康检查"""
        r = self._client.get(f"{self.master_url}/health")
        r.raise_for_status()
        return r.json()

    def slaves(self) -> list:
        """列出所有从机节点"""
        r = self._client.get(f"{self.master_url}/slaves")
        r.raise_for_status()
        return r.json()

    def translate(
        self,
        text: str,
        target_lang: str = "zh",
        source_lang: str = "auto",
        glossary: Optional[Dict[str, str]] = None,
    ) -> TranslationResult:
        """
        翻译（同步）

        Args:
            text: 待翻译文本
            target_lang: 目标语言，如 zh/en/ja/fr
            source_lang: 源语言，默认 auto 自动检测
            glossary: 术语表，如 {"PyTorch": "PyTorch框架"}
        """
        r = self._client.post(
            f"{self.master_url}/translate",
            json={
                "text": text,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "glossary": glossary,
            },
        )
        r.raise_for_status()
        return TranslationResult(r.json())

    def close(self):
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# 模块级默认 client（一行调用复用）
_default_client: Optional[TranslatorClient] = None


def _get_default_client(master_url: Optional[str] = None) -> TranslatorClient:
    global _default_client
    if _default_client is None:
        _default_client = TranslatorClient(master_url=master_url)
    elif master_url and master_url != _default_client.master_url:
        # 切换 Master 时重建
        _default_client.close()
        _default_client = TranslatorClient(master_url=master_url)
    return _default_client


def translate(
    text: str,
    target_lang: str = "zh",
    source_lang: str = "auto",
    glossary: Optional[Dict[str, str]] = None,
    master_url: Optional[str] = None,
) -> str:
    """
    一行翻译

    Examples:
        >>> translate("Hello world", target_lang="zh")
        '你好世界'

        >>> translate("Bonjour", target_lang="zh", source_lang="fr")
        '你好'

        >>> translate("PyTorch is great", target_lang="zh",
        ...           glossary={"PyTorch": "PyTorch框架"})
        'PyTorch框架很棒'
    """
    client = _get_default_client(master_url)
    result = client.translate(text, target_lang, source_lang, glossary)
    return result.translated_text
