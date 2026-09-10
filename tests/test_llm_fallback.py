import pytest
from unittest.mock import patch, MagicMock
from app.llm import LLMClient


class TestLLMFallbackLogic:
    def test_primary_groq_success(self):
        client = LLMClient()
        with patch("app.llm.settings") as mock_settings:
            mock_settings.LLM_PRIMARY = "groq"
            mock_settings.LLM_FALLBACK = "gemini"
            mock_groq = MagicMock()
            mock_llm_resp = MagicMock()
            mock_llm_resp.choices = [MagicMock(message=MagicMock(content="ok"))]
            mock_groq.chat.completions.create.return_value = mock_llm_resp
            client._groq = mock_groq
            result = client.complete("sys", "usr")
            assert result == "ok"
            mock_groq.chat.completions.create.assert_called_once()

    def test_primary_groq_fails_falls_to_gemini(self):
        client = LLMClient()
        with patch("app.llm.settings") as mock_settings:
            mock_settings.LLM_PRIMARY = "groq"
            mock_settings.LLM_FALLBACK = "gemini"
            mock_groq = MagicMock()
            mock_groq.chat.completions.create.side_effect = Exception("rate limited")
            client._groq = mock_groq
            mock_gemini = MagicMock()
            mock_gemini_response = MagicMock()
            mock_gemini_response.text = "gemini ok"
            mock_gemini.models.generate_content.return_value = mock_gemini_response
            client._gemini = mock_gemini
            result = client.complete("sys", "usr")
            assert result == "gemini ok"

    def test_primary_groq_fails_gemini_fails_raises_gemini_error(self):
        client = LLMClient()
        with patch("app.llm.settings") as mock_settings:
            mock_settings.LLM_PRIMARY = "groq"
            mock_settings.LLM_FALLBACK = "gemini"
            mock_groq = MagicMock()
            mock_groq.chat.completions.create.side_effect = Exception("groq down")
            client._groq = mock_groq
            mock_gemini = MagicMock()
            mock_gemini.models.generate_content.side_effect = Exception("gemini down")
            client._gemini = mock_gemini
            with pytest.raises(Exception, match="gemini down"):
                client.complete("sys", "usr")

    def test_no_providers_raises_runtime_error(self):
        client = LLMClient()
        with patch("app.llm.settings") as mock_settings:
            mock_settings.LLM_PRIMARY = "none"
            mock_settings.LLM_FALLBACK = "none"
            with pytest.raises(RuntimeError, match="No LLM provider available"):
                client.complete("sys", "usr")

    def test_no_providers_includes_config_in_error(self):
        client = LLMClient()
        with patch("app.llm.settings") as mock_settings:
            mock_settings.LLM_PRIMARY = "unknown"
            mock_settings.LLM_FALLBACK = "unknown"
            with pytest.raises(RuntimeError, match="primary=unknown"):
                client.complete("sys", "usr")

    def test_primary_not_groq_skips_groq(self):
        client = LLMClient()
        with patch("app.llm.settings") as mock_settings:
            mock_settings.LLM_PRIMARY = "gemini"
            mock_settings.LLM_FALLBACK = "gemini"
            mock_gemini = MagicMock()
            mock_gemini_response = MagicMock()
            mock_gemini_response.text = "direct gemini"
            mock_gemini.models.generate_content.return_value = mock_gemini_response
            client._gemini = mock_gemini
            mock_groq = MagicMock()
            client._groq = mock_groq
            result = client.complete("sys", "usr")
            assert result == "direct gemini"
            mock_groq.chat.completions.create.assert_not_called()
