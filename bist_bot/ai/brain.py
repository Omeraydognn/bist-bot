"""
BIST Bot AI Beyin — NVIDIA NIM API Entegrasyonu.

NVIDIA NIM (build.nvidia.com) uzerinden ucretsiz LLM erisimi saglar.
OpenAI uyumlu API kullanir (openai SDK ile calisir).

Gorevleri:
  * Orchestrator'dan gelen analiz paketini prompt'a cevirir
  * NVIDIA API'ye gonderir
  * AI'in kararini parse edip dondurur
  * Hata durumunda matematik motora geri duser (fallback)
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from bist_bot.ai.prompts import SYSTEM_PROMPT, build_analysis_prompt


@dataclass
class AIDecision:
    action: str          # AL / SAT / BEKLE
    confidence: float    # 0.0 - 1.0
    reasoning: str       # Turkce gerekce
    vetoed: bool         # Matematik motoru veto ettiyse True
    raw_response: str    # Ham API yaniti (debug icin)


class AIBrain:
    """
    NVIDIA NIM API uzerinden calisan AI karar motoru.
    
    NVIDIA NIM, OpenAI uyumlu bir API sunar. Ucretsiz katmanda
    cok sayida model (Llama, Mistral, Nemotron vb.) kullanilabilir.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "meta/llama-3.1-70b-instruct",
        temperature: float = 0.1,
        base_url: str = "https://integrate.api.nvidia.com/v1",
    ):
        self.api_key = api_key or os.environ.get("NVIDIA_API_KEY", "")
        self.model = model
        self.temperature = temperature
        self.base_url = base_url
        self.enabled = bool(self.api_key)
        self._client = None
        self.last_error = ""

        if not self.enabled:
            self.last_error = "NVIDIA_API_KEY bulunamadi."
            print("[AI Beyin] NVIDIA_API_KEY tanimli degil — AI devre disi, matematik motor tek basina karar verecek.")

    def _get_client(self):
        """Lazy initialization: openai client'i ilk kullanımda olustur."""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    base_url=self.base_url,
                    api_key=self.api_key,
                )
            except ImportError:
                self.last_error = "openai kütüphanesi kurulu değil."
                print("[AI Beyin] openai paketi kurulu degil. `pip install openai` calistir.")
                self.enabled = False
                return None
        return self._client

    def decide(self, analysis_data: dict) -> AIDecision | None:
        """
        Analiz paketini AI'a gonderip karar alir.
        
        Hata durumunda None doner → orkestrator matematik motora geri duser.
        """
        if not self.enabled:
            return None

        client = self._get_client()
        if client is None:
            return None

        user_prompt = build_analysis_prompt(analysis_data)
        math_action = analysis_data.get("aksiyon", "BEKLE")

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
                max_tokens=300,
            )

            raw = response.choices[0].message.content.strip()
            self.last_error = ""
            return self._parse_response(raw, math_action)

        except Exception as e:
            self.last_error = str(e)
            print(f"[AI Beyin] API hatasi: {e}")
            return None

    def _parse_response(self, raw: str, math_action: str) -> AIDecision:
        """AI'in JSON cevabini parse eder. Bozuk formatta fallback uygular."""
        try:
            # JSON bloğunu bul (```json ... ``` veya düz JSON)
            json_match = re.search(r'\{[^{}]*"karar"[^{}]*\}', raw, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                # Tüm yanıtı JSON olarak dene
                data = json.loads(raw)

            action = data.get("karar", "BEKLE").upper()
            if action not in ("AL", "SAT", "BEKLE"):
                action = "BEKLE"

            confidence = float(data.get("guven", 0.5))
            confidence = max(0.0, min(1.0, confidence))

            reasoning = data.get("gerekce", "AI gerekce uretmedi.")
            vetoed = data.get("veto", False)

            # Ek güvenlik: AI saçmalarsa (güven çok düşük ama AL/SAT diyorsa)
            if action in ("AL", "SAT") and confidence < 0.4:
                action = "BEKLE"
                reasoning = f"[Güvenlik Filtresi] AI güveni düşük ({confidence:.1f}), BEKLE'ye çevrildi. Orijinal: {reasoning}"
                vetoed = True

            return AIDecision(
                action=action,
                confidence=confidence,
                reasoning=reasoning,
                vetoed=(action != math_action) or vetoed,
                raw_response=raw,
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"[AI Beyin] Yanit parse hatasi: {e}")
            print(f"[AI Beyin] Ham yanit: {raw[:200]}")
            return AIDecision(
                action=math_action,  # Parse hatasinda matematik motora geri dus
                confidence=0.5,
                reasoning="AI yanıtı okunamadı, matematik motor kararı korundu.",
                vetoed=False,
                raw_response=raw,
            )
