"""Hybrid cloud translator and multimodal Vision Q&A powered by Google Gen AI SDK."""

from __future__ import annotations

import io
import json
import threading
from collections import OrderedDict
from typing import Any, Optional, Sequence

from PIL import Image


class TranslationCache:
    """Thread-safe LRU cache for translated UI strings."""

    def __init__(self, max_entries: int = 1500) -> None:
        self.max_entries = max(10, max_entries)
        self._store: OrderedDict[tuple[str, str], str] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, target_language: str, text: str) -> Optional[str]:
        key = (target_language.lower(), text)
        with self._lock:
            value = self._store.get(key)
            if value is not None:
                self._store.move_to_end(key)
            return value

    def set(self, target_language: str, text: str, translated: str) -> None:
        key = (target_language.lower(), text)
        with self._lock:
            self._store[key] = translated
            self._store.move_to_end(key)
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


def parse_batch_translation_json(raw_text: str, expected_count: int) -> list[str]:
    """Parse a JSON array (or object with 'translations') returned by Gemini."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    data = json.loads(cleaned)
    if isinstance(data, dict) and "translations" in data:
        items = data["translations"]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("Unexpected translation response schema")

    if len(items) != expected_count:
        raise ValueError(
            f"Expected {expected_count} translations, received {len(items)}"
        )
    return [str(x) for x in items]


class GeminiRestClient:
    """Pure-Python REST client for Gemini API.
    
    Provides 100% compatibility without relying on external native binaries/DLLs
    (which can be blocked by Windows Application Control policies), and includes
    automatic fallback across resilient flash models if temporary 503 high-demand
    or connection resets occur.
    """

    def __init__(self, api_key: str, default_model: str = "gemini-3.5-flash") -> None:
        self.api_key = api_key
        self.default_model = default_model
        self.models = GeminiRestModels(api_key, default_model)


# Common English stop words, pronouns, and contractions to ignore during slang extraction
ENGLISH_STOP_WORDS = {
    # Contractions
    "i'm", "i've", "i'll", "i'd", "you're", "you've", "you'll", "you'd",
    "he's", "he'll", "he'd", "she's", "she'll", "she'd", "it's", "it'll",
    "we're", "we've", "we'll", "we'd", "they're", "they've", "they'll", "they'd",
    "don't", "doesn't", "didn't", "can't", "cannot", "won't", "wouldn't",
    "shouldn't", "couldn't", "isn't", "aren't", "wasn't", "weren't",
    "haven't", "hasn't", "hadn't", "there's", "what's", "that's", "who's",
    "let's", "ain't", "im", "ive", "ill", "id", "youre", "youve", "hes", "shes",
    "dont", "doesnt", "didnt", "cant", "wont", "isnt", "arent", "wasnt", "werent",
    # Pronouns
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your",
    "yours", "yourself", "yourselves", "he", "him", "his", "himself", "she",
    "her", "hers", "herself", "it", "its", "itself", "they", "them", "their",
    "theirs", "themselves", "what", "which", "who", "whom", "this", "that",
    "these", "those",
    # Auxiliary & Common Verbs
    "am", "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "having", "do", "does", "did", "doing", "would", "should", "could",
    "ought", "will", "shall", "can", "may", "might", "must", "go", "goes",
    "going", "went", "gone", "come", "comes", "coming", "came", "get", "gets",
    "getting", "got", "make", "makes", "making", "made", "take", "takes",
    "taking", "took", "see", "sees", "seeing", "saw", "seen", "know", "knows",
    "knowing", "knew", "known", "think", "thinks", "thinking", "thought",
    "look", "looks", "looking", "looked", "want", "wants", "wanting", "wanted",
    "give", "gives", "giving", "gave", "given", "use", "uses", "using", "used",
    "find", "finds", "finding", "found", "tell", "tells", "telling", "told",
    # Prepositions, Conjunctions, Articles
    "a", "an", "the", "and", "but", "if", "or", "because", "as", "until",
    "while", "of", "at", "by", "for", "with", "about", "against", "between",
    "into", "through", "during", "before", "after", "above", "below", "to",
    "from", "up", "down", "in", "out", "on", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why", "how",
    "all", "any", "both", "each", "few", "more", "most", "other", "some",
    "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too",
    "very", "s", "t", "just", "now", "also", "really", "already", "still"
}


class OpenAIRestClient:
    """Universal REST client for OpenAI-compatible APIs (Groq, OpenRouter, OpenAI, Ollama)."""

    def __init__(self, api_key: str, endpoint: str, default_model: str) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.default_model = default_model
        self.models = self
        self._session = None

    def _get_session(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
            self._session.trust_env = False
        return self._session

    def generate_content(self, model: str, contents: Any, config: Any = None) -> Any:
        from types import SimpleNamespace

        sess = self._get_session()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "WinScreenLens/1.0",
        }

        prompt_text = ""
        if isinstance(contents, str):
            prompt_text = contents
        elif isinstance(contents, list):
            prompt_text = " ".join([str(p) for p in contents if isinstance(p, str)])

        payload = {
            "model": model or self.default_model,
            "messages": [{"role": "user", "content": prompt_text}],
            "temperature": 0.3,
        }

        resp = sess.post(self.endpoint, json=payload, headers=headers, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        choice_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return SimpleNamespace(text=choice_text)


class GeminiRestModels:
    def __init__(self, api_key: str, default_model: str) -> None:
        self.api_key = api_key
        self.default_model = default_model
        self._session = None

    def _get_session(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
            # Disable reading system/LAN environment proxies that may be dead/unreachable
            self._session.trust_env = False
        return self._session

    def generate_content(self, model: str, contents: Any, config: Any = None) -> Any:
        import base64
        import io
        from types import SimpleNamespace

        payload: dict[str, Any] = {}
        if isinstance(contents, str):
            payload["contents"] = [{"parts": [{"text": contents}]}]
        elif isinstance(contents, list):
            parts = []
            for item in contents:
                if isinstance(item, str):
                    parts.append({"text": item})
                elif hasattr(item, "convert"):  # PIL Image
                    buf = io.BytesIO()
                    item.convert("RGB").save(buf, format="PNG")
                    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                    parts.append({"inlineData": {"mimeType": "image/png", "data": b64}})
                elif isinstance(item, dict):
                    parts.append(item)
                elif hasattr(item, "data"):
                    raw_data = getattr(item, "data", b"")
                    mime = getattr(item, "mime_type", "image/png")
                    b64 = base64.b64encode(raw_data).decode("ascii")
                    parts.append({"inlineData": {"mimeType": mime, "data": b64}})
            payload["contents"] = [{"parts": parts}]

        if config is not None:
            gen_cfg: dict[str, Any] = {}
            if hasattr(config, "temperature") and config.temperature is not None:
                gen_cfg["temperature"] = config.temperature
            elif isinstance(config, dict) and "temperature" in config:
                gen_cfg["temperature"] = config["temperature"]

            if hasattr(config, "response_mime_type") and config.response_mime_type:
                gen_cfg["responseMimeType"] = config.response_mime_type
            elif isinstance(config, dict) and "response_mime_type" in config:
                gen_cfg["responseMimeType"] = config["response_mime_type"]

            if gen_cfg:
                payload["generationConfig"] = gen_cfg

        # Candidate models to try in order of resilience (gemini-3-flash-preview is active & verified)
        candidates: list[str] = []
        for m in (model, "gemini-3-flash-preview", "gemini-3.5-flash-lite", "gemini-flash-latest"):
            if m and m not in candidates:
                candidates.append(m)

        sess = self._get_session()
        headers = {"Content-Type": "application/json", "User-Agent": "WinScreenLens/1.0"}
        last_err: Optional[Exception] = None

        for target_model in candidates:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent?key={self.api_key}"
            try:
                resp = sess.post(url, json=payload, headers=headers, timeout=6)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates_out = data.get("candidates", [])
                    if candidates_out:
                        text = candidates_out[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        return SimpleNamespace(text=text)
                elif resp.status_code in (503, 429, 404):
                    continue
                else:
                    resp.raise_for_status()
            except Exception as exc:
                last_err = exc
                continue

        if last_err:
            raise RuntimeError(f"Gemini API request failed: {last_err}") from last_err
        raise RuntimeError("All Gemini API models failed to respond. Please check your network connection.")


_GOOGLE_TRANSLATE_SESSION = None
_PREFERRED_GOOGLE_CLIENT = "dict-chrome-ex"


def _get_google_session():
    global _GOOGLE_TRANSLATE_SESSION
    if _GOOGLE_TRANSLATE_SESSION is None:
        import requests
        from requests.adapters import HTTPAdapter

        sess = requests.Session()
        sess.trust_env = False
        adapter = HTTPAdapter(pool_connections=4, pool_maxsize=8, max_retries=1)
        sess.mount("https://", adapter)
        sess.mount("http://", adapter)
        _GOOGLE_TRANSLATE_SESSION = sess
    return _GOOGLE_TRANSLATE_SESSION


LANGUAGE_MAP: dict[str, str] = {
    "sinhala": "si",
    "si": "si",
    "sin": "si",
    "english": "en",
    "en": "en",
    "tamil": "ta",
    "ta": "ta",
    "japanese": "ja",
    "ja": "ja",
    "german": "de",
    "de": "de",
    "french": "fr",
    "fr": "fr",
    "spanish": "es",
    "es": "es",
    "hindi": "hi",
    "hi": "hi",
    "chinese": "zh-CN",
    "simplified chinese": "zh-CN",
    "traditional chinese": "zh-TW",
    "zh": "zh-CN",
    "russian": "ru",
    "ru": "ru",
    "arabic": "ar",
    "ar": "ar",
    "korean": "ko",
    "ko": "ko",
}


def resolve_lang_code(target_language: str) -> str:
    """Safely map any language display string (e.g. 'Sinhala (සිංහල)') to standard ISO code."""
    cleaned = target_language.lower().split("(")[0].strip()
    return LANGUAGE_MAP.get(cleaned, LANGUAGE_MAP.get(target_language.lower().strip(), "si"))


def translate_via_google(texts: Sequence[str], target_language: str = "Sinhala") -> list[str]:
    """Fast, resilient direct Google Translate with client rotation and MyMemory fallback.
    
    Zero API key required, zero quotas, and ultra-fast with client rotation.
    """
    if not texts:
        return []

    lang_code = resolve_lang_code(target_language)
    import requests

    sess = _get_google_session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }

    # Resilient Google Translate clients ordered with last working client first
    global _PREFERRED_GOOGLE_CLIENT
    base_clients = ["dict-chrome-ex", "gtx", "t"]
    google_clients = [_PREFERRED_GOOGLE_CLIENT] + [c for c in base_clients if c != _PREFERRED_GOOGLE_CLIENT]

    # 1. Attempt fast batched request (newline separated)
    if len(texts) > 1:
        sanitized = [t.replace("\r", " ").replace("\n", " ").strip() for t in texts]
        joined = "\n".join(sanitized)
        for client in google_clients:
            url = f"https://translate.googleapis.com/translate_a/single?client={client}&sl=auto&tl={lang_code}&dt=t&q={requests.utils.quote(joined)}"
            try:
                resp = sess.get(url, headers=headers, timeout=2.5)
                if resp.status_code == 200:
                    _PREFERRED_GOOGLE_CLIENT = client
                    raw = "".join([p[0] for p in resp.json()[0] if p and p[0]])
                    lines = raw.split("\n")
                    if len(lines) == len(texts):
                        return [line.strip() for line in lines]
            except Exception:
                continue

    # 2. Translate individual texts with client rotation
    results: list[str] = []
    for item in texts:
        translated_item = None
        for client in google_clients:
            url = f"https://translate.googleapis.com/translate_a/single?client={client}&sl=auto&tl={lang_code}&dt=t&q={requests.utils.quote(item)}"
            try:
                resp = sess.get(url, headers=headers, timeout=2.5)
                if resp.status_code == 200:
                    raw = "".join([p[0] for p in resp.json()[0] if p and p[0]])
                    if raw.strip():
                        _PREFERRED_GOOGLE_CLIENT = client
                        translated_item = raw.strip()
                        break
            except Exception:
                continue

        # 3. If Google endpoints are temporarily throttled (429), use MyMemory fallback
        if not translated_item:
            try:
                mm_url = f"https://api.mymemory.translated.net/get?q={requests.utils.quote(item)}&langpair=autodetect|{lang_code}"
                resp = sess.get(mm_url, headers=headers, timeout=3.5)
                if resp.status_code == 200:
                    data = resp.json()
                    candidate = data.get("responseData", {}).get("translatedText", "")
                    if candidate and candidate.strip():
                        translated_item = candidate.strip()
            except Exception:
                pass

        results.append(translated_item or item)

    return results


class HybridTranslator:
    """Fast screen translation powered by direct Google Translate + optional Gemini fallback."""

    def __init__(
        self,
        api_key: str = "",
        model: str = "llama-3.3-70b-versatile",
        cache_max_entries: int = 2000,
        client: Any = None,
        engine: str = "google",
        ai_provider: str = "groq",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.engine = engine
        self.ai_provider = (ai_provider or "groq").lower().strip()
        self.cache = TranslationCache(max_entries=cache_max_entries)
        self._custom_test_client = client
        self._ai_client: Any = None

    def _ensure_client(self) -> Any:
        if self._custom_test_client is not None:
            return self._custom_test_client
        if self._ai_client is not None:
            return self._ai_client

        provider = self.ai_provider
        key = self.api_key

        if not key or key.startswith("your_") or key in ("your_gemini_api_key_here", "your_groq_api_key_here"):
            raise RuntimeError(
                f"{provider.upper()} API key is not configured. Right-click the tray icon and select Settings... or set your key in .env"
            )

        if provider == "groq":
            self._ai_client = OpenAIRestClient(
                api_key=key,
                endpoint="https://api.groq.com/openai/v1/chat/completions",
                default_model=self.model or "llama-3.3-70b-versatile",
            )
            return self._ai_client
        elif provider == "openrouter":
            self._ai_client = OpenAIRestClient(
                api_key=key,
                endpoint="https://openrouter.ai/api/v1/chat/completions",
                default_model=self.model or "meta-llama/llama-3.3-70b-instruct:free",
            )
            return self._ai_client
        elif provider == "openai":
            self._ai_client = OpenAIRestClient(
                api_key=key,
                endpoint="https://api.openai.com/v1/chat/completions",
                default_model=self.model or "gpt-4o-mini",
            )
            return self._ai_client
        else:  # Gemini
            self._ai_client = GeminiRestClient(api_key=key, default_model=self.model or "gemini-2.0-flash")
            return self._ai_client

    def translate_batch(
        self,
        texts: Sequence[str],
        target_language: str = "Sinhala",
    ) -> list[str]:
        """Translate a list of OCR strings, hitting the engine only for cache misses."""
        if not texts:
            return []

        results: list[Optional[str]] = [None] * len(texts)
        missing_indices: list[int] = []
        missing_texts: list[str] = []

        for idx, text in enumerate(texts):
            cached = self.cache.get(target_language, text)
            if cached is not None:
                results[idx] = cached
            else:
                missing_indices.append(idx)
                missing_texts.append(text)

        if not missing_texts:
            return [r or "" for r in results]

        translated_missing: list[str] = []

        # 1. Custom mock client for unit test mocks ONLY
        if self._custom_test_client is not None:
            client = self._custom_test_client
            payload = json.dumps(missing_texts, ensure_ascii=False)
            prompt = (
                f"Translate each string in the following JSON array into {target_language}. "
                "Preserve concise UI phrasing, numbers, and proper nouns. "
                "If a string is already in the target language, return it unchanged. "
                "Return ONLY a JSON object of the form {\"translations\": [...]} "
                f"with exactly {len(missing_texts)} strings in the same order.\n\n"
                f"Input JSON:\n{payload}"
            )
            gen_config: dict[str, Any] = {
                "temperature": 0.1,
                "response_mime_type": "application/json",
            }

            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=gen_config,
            )
            translated_missing = parse_batch_translation_json(
                response.text or "", expected_count=len(missing_texts)
            )
        # 2. Primary Google Translate Engine (Free, Instant, Client-Rotated)
        elif self.engine == "google":
            try:
                translated_missing = translate_via_google(missing_texts, target_language)
            except Exception:
                if self.api_key:
                    try:
                        client = self._ensure_client()
                        payload = json.dumps(missing_texts, ensure_ascii=False)
                        prompt = (
                            f"Translate each string in the following JSON array into {target_language}. "
                            "Return ONLY a JSON object {\"translations\": [...]}.\n\n"
                            f"Input JSON:\n{payload}"
                        )
                        response = client.models.generate_content(model=self.model, contents=prompt)
                        translated_missing = parse_batch_translation_json(
                            response.text or "", expected_count=len(missing_texts)
                        )
                    except Exception:
                        translated_missing = missing_texts
                else:
                    translated_missing = missing_texts
        # 3. AI provider (Groq / Gemini / OpenAI / OpenRouter)
        else:
            client = self._ensure_client()
            payload = json.dumps(missing_texts, ensure_ascii=False)
            prompt = (
                f"Translate each string in the following JSON array into {target_language}. "
                "Return ONLY a JSON object {\"translations\": [...]}.\n\n"
                f"Input JSON:\n{payload}"
            )
            response = client.models.generate_content(model=self.model, contents=prompt)
            translated_missing = parse_batch_translation_json(
                response.text or "", expected_count=len(missing_texts)
            )

        for idx, original, translated in zip(
            missing_indices, missing_texts, translated_missing
        ):
            self.cache.set(target_language, original, translated)
            results[idx] = translated

        return [r or "" for r in results]

    def ask_about_image(
        self,
        image: Image.Image,
        question: str,
        target_language: str = "English",
    ) -> str:
        """Send a snipped screen region and user question to Gemini Vision."""
        client = self._ensure_client()
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="PNG")
        img_bytes = buf.getvalue()

        user_prompt = (
            f"Answer the user's question about this screenshot region in {target_language}. "
            "Be concise, direct, and accurate.\n\n"
            f"Question: {question.strip()}"
        )

        contents = [image, user_prompt]

        response = client.models.generate_content(
            model=self.model,
            contents=contents,
        )
        return (response.text or "").strip()

    def explain_slang_and_indirect_meaning(
        self,
        text: str,
        target_language: str = "Sinhala",
    ) -> str:
        """Analyze text for slang, idioms, metaphors, or indirect meanings in Sinhala.

        Tries Gemini AI first, and seamlessly falls back to a keyless linguistic
        slang & idiom dictionary engine if Gemini API times out or is unavailable.
        """
        cleaned = text.strip()
        if not cleaned:
            return "විශ්ලේෂණය කිරීමට පෙළක් හමු නොවීය. (No text found to analyze.)"

        # 1. Attempt Gemini AI if key is configured
        if self.api_key and self.api_key not in ("your_gemini_api_key_here", "your_gemini_api_key"):
            try:
                client = self._ensure_client()
                prompt = (
                    f"You are an expert bilingual linguist in English and Sinhala (සිංහල).\n"
                    f"Analyze the following text for any indirect meaning, slang, idioms, sarcasm, or colloquial expressions:\n\n"
                    f"Text: \"{cleaned}\"\n\n"
                    f"Explain clearly in natural, conversational Sinhala (සිංහල):\n"
                    f"1. The true indirect / slang meaning (ව්‍යංගාර්ථය / සැබෑ අදහස).\n"
                    f"2. Specific slang words or idioms used and their exact meaning.\n"
                    f"3. Practical context in simple Sinhala.\n"
                    f"Keep it concise, clear, and well-structured with bullet points."
                )

                response = client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                )
                res_text = (response.text or "").strip()
                if res_text:
                    return res_text
            except Exception:
                # Gemini timed out or had network error -> seamlessly fall back to dictionary
                pass

        # 2. Resilient Keyless Slang & Idiom Engine (Zero-Key Fallback)
        return self._explain_slang_fallback(cleaned, target_language)

    def _explain_slang_fallback(self, text: str, target_language: str = "Sinhala") -> str:
        """Keyless fallback for slang & idiom definitions using UrbanDictionary and Google Translate."""
        import re
        import requests

        cleaned = text.strip()
        sess = _get_google_session()

        words = re.findall(r"[A-Za-z']+", cleaned)
        candidates_to_search: list[str] = []

        # 1. Whole phrase if 2-4 words and not just stop words
        if 2 <= len(words) <= 4 and cleaned.lower() not in ENGLISH_STOP_WORDS:
            candidates_to_search.append(cleaned)

        # 2. Multi-word idiom candidate n-grams (e.g. "under the weather", "spill the tea")
        for i in range(len(words) - 1):
            pair = f"{words[i]} {words[i+1]}"
            if pair.lower() not in ENGLISH_STOP_WORDS:
                candidates_to_search.append(pair)
            if i + 2 < len(words):
                triplet = f"{words[i]} {words[i+1]} {words[i+2]}"
                if triplet.lower() not in ENGLISH_STOP_WORDS:
                    candidates_to_search.append(triplet)

        # 3. Individual candidate words (strictly excluding stop words & contractions like "I'm")
        for w in words:
            wl = w.lower()
            if len(wl) >= 3 and wl not in ENGLISH_STOP_WORDS and wl not in candidates_to_search:
                candidates_to_search.append(w)

        found_term = ""
        found_def = ""
        found_example = ""
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

        for term in candidates_to_search[:4]:
            try:
                url = f"https://api.urbandictionary.com/v0/define?term={requests.utils.quote(term)}"
                resp = sess.get(url, headers=headers, timeout=3)
                if resp.status_code == 200:
                    data = resp.json()
                    item_list = data.get("list", [])
                    if item_list:
                        # Find best definition with positive net votes
                        for item in item_list[:3]:
                            up = item.get("thumbs_up", 0)
                            down = item.get("thumbs_down", 0)
                            raw_def = re.sub(r"[\[\]]", "", item.get("definition", "")).strip()
                            raw_ex = re.sub(r"[\[\]]", "", item.get("example", "")).strip()
                            if raw_def and len(raw_def) >= 12 and up >= down:
                                found_term = term
                                found_def = raw_def[:280]
                                found_example = raw_ex[:180]
                                break
                        if found_def:
                            break
            except Exception:
                continue

        # If a valid slang definition was found, translate it to Sinhala
        if found_def:
            texts_to_trans = [found_def]
            if found_example:
                texts_to_trans.append(found_example)

            translated_parts = translate_via_google(texts_to_trans, target_language)
            si_def = translated_parts[0] if translated_parts else found_def
            si_ex = translated_parts[1] if len(translated_parts) > 1 else found_example

            out = [
                f"### 💡 Slang / සැබෑ අදහස (Linguistic Engine):",
                f"* **හඳුනාගත් යෙදුම (Slang/Idiom)**: **{found_term}**",
                f"* **සැබෑ අර්ථය (Meaning)**: {si_def}",
            ]
            if si_ex:
                out.append(f"* **උදාහරණ භාවිතය (Example)**: {si_ex}")
            out.append("\n*(සටහන: Gemini API ප්‍රතිචාර නොදැක්වූ බැවින් Linguistic Dictionary මඟින් සෘජුව පරිවර්තනය කරන ලදී.)*")
            return "\n".join(out)

        # Fallback to direct contextual breakdown via Google Translate
        direct_tr = translate_via_google([cleaned], target_language)
        tr_text = direct_tr[0] if direct_tr else cleaned
        return (
            f"### 💡 පරිවර්තනය සහ සැබෑ අදහස:\n"
            f"* **සෘජු පරිවර්තනය**: {tr_text}\n"
            f"* **විග්‍රහය**: මෙහි විශේෂ slang හෝ idiom එකක් හඳුනා නොගත් අතර, සාමාන්‍ය කතාබහේ සෘජු අර්ථයෙන් භාවිත වේ."
        )
