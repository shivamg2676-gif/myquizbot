"""AI Service - Multi-provider support (Cerebras, Gemini, Groq, Mistral, OpenRouter, OpenAI).

Uses the first provider with a non-empty key, or a specific provider via AI_DEFAULT_PROVIDER.
Used for:
  - Generating quiz questions from text/PDF
  - Explaining wrong answers
  - Smart context analysis (keyword triggers)
"""

import json
import logging
from typing import Any

import httpx

from config import (
    AI_DEFAULT_PROVIDER,
    CEREBRAS_API_KEY,
    GEMINI_API_KEY,
    GROQ_API_KEY,
    MISTRAL_API_KEY,
    OPENAI_API_KEY,
    OPENROUTER_API_KEY,
)

log = logging.getLogger(__name__)

PROVIDERS = {
    "cerebras": {
        "url": "https://api.cerebras.ai/v1/chat/completions",
        "key": CEREBRAS_API_KEY,
        "model": "llama-3.3-70b",
        "key_header": "Authorization",
        "key_prefix": "Bearer ",
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        "key": GEMINI_API_KEY,
        "model": "gemini-2.0-flash",
        "key_header": "x-goog-api-key",
        "key_prefix": "",
        "is_gemini": True,
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "key": GROQ_API_KEY,
        "model": "llama-3.3-70b-versatile",
        "key_header": "Authorization",
        "key_prefix": "Bearer ",
    },
    "mistral": {
        "url": "https://api.mistral.ai/v1/chat/completions",
        "key": MISTRAL_API_KEY,
        "model": "mistral-large-latest",
        "key_header": "Authorization",
        "key_prefix": "Bearer ",
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key": OPENROUTER_API_KEY,
        "model": "meta-llama/llama-3.3-70b-instruct",
        "key_header": "Authorization",
        "key_prefix": "Bearer ",
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "key": OPENAI_API_KEY,
        "model": "gpt-4o-mini",
        "key_header": "Authorization",
        "key_prefix": "Bearer ",
    },
}


def _pick_provider(provider_name: str | None = None) -> str | None:
    """Pick an available provider."""
    if provider_name and provider_name in PROVIDERS and PROVIDERS[provider_name]["key"]:
        return provider_name
    if AI_DEFAULT_PROVIDER in PROVIDERS and PROVIDERS[AI_DEFAULT_PROVIDER]["key"]:
        return AI_DEFAULT_PROVIDER
    for name, cfg in PROVIDERS.items():
        if cfg["key"]:
            return name
    return None


async def ask_ai(
    prompt: str,
    system: str = "You are a helpful CA Foundation study assistant.",
    provider: str | None = None,
    json_mode: bool = False,
    temperature: float = 0.3,
) -> str | None:
    """Send a prompt to an AI provider and return the text response."""
    p_name = _pick_provider(provider)
    if not p_name:
        log.warning("No AI provider API key configured.")
        return None
    cfg = PROVIDERS[p_name]
    if not cfg["key"]:
        return None

    headers = {cfg["key_header"]: f"{cfg['key_prefix']}{cfg['key']}"}

    try:
        if cfg.get("is_gemini"):
            payload = {
                "contents": [{"parts": [{"text": f"{system}\n\n{prompt}"}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "responseMimeType": "application/json" if json_mode else "text/plain",
                },
            }
        else:
            payload = {
                "model": cfg["model"],
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(cfg["url"], headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if cfg.get("is_gemini"):
                return data["candidates"][0]["content"]["parts"][0]["text"]
            else:
                return data["choices"][0]["message"]["content"]
    except Exception as e:
        log.error("AI request failed (%s): %s", p_name, e)
        return None


async def generate_quiz_from_text(
    text: str, subject: str, chapter: str, count: int = 10
) -> list[dict[str, Any]]:
    """Generate quiz questions from study material text using AI."""
    prompt = f"""Based on the following CA Foundation '{subject}' study material for chapter '{chapter}', generate {count} MCQ questions.

Return strict JSON:
{{
  "questions": [
    {{
      "question": "...",
      "type": "mcq",
      "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
      "correct": "A",
      "explanation": "...",
      "hint": "...",
      "difficulty": "easy|medium|hard"
    }}
  ]
}}

Material:
{text[:6000]}"""
    result = await ask_ai(prompt, json_mode=True)
    if not result:
        return []
    try:
        data = json.loads(result)
        return data.get("questions", [])
    except (json.JSONDecodeError, KeyError):
        log.warning("Failed to parse AI quiz generation response.")
        return []


async def explain_answer(
    question_text: str, correct: str, user_answer: str, explanation: str | None = None
) -> str | None:
    """Generate a personalised wrong-answer explanation via AI (in Hinglish)."""
    if explanation:
        return explanation
    prompt = f"""A CA Foundation student answered wrong on this quiz question.

Question: {question_text}
Correct answer: {correct}
Student's answer: {user_answer}

Explain in short 2-3 sentences why the correct answer is right and the student's answer is wrong. Use Hinglish (Hindi + English mix). Do not use markdown or special formatting."""
    return await ask_ai(prompt)


async def classify_message_intent(text: str) -> str:
    """Classify message intent: 'request_material', 'discussion', or 'other'.
    Used for smart keyword triggers."""
    prompt = f"""Classify this message as one of:
- "request_material": user is asking for study material, PDF, notes, or asking for a link to study content
- "discussion": user is discussing a topic, sharing thoughts, or chatting (not requesting material)

Message: "{text}"

Reply ONLY with JSON: {{"intent": "request_material"}} or {{"intent": "discussion"}}"""
    result = await ask_ai(prompt, json_mode=True, temperature=0.0)
    if result:
        try:
            data = json.loads(result)
            return data.get("intent", "discussion")
        except (json.JSONDecodeError, KeyError):
            pass
    return "discussion"
