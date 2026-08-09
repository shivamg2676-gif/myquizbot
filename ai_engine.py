import aiohttp
import config

class MultiLLMEngine:
    def __init__(self):
        self.keys = {
            "groq": config.GROQ_API_KEY,
            "cerebras": config.CEREBRAS_API_KEY,
            "gemini": config.GEMINI_API_KEY,
            "mistral": config.MISTRAL_API_KEY,
            "openrouter": config.OPENROUTER_API_KEY,
        }

    async def analyze_context(self, user_message: str) -> bool:
        """
        Detects if user is asking for study material or having a general conversation.
        Returns True for DEMAND, False for DISCUSSION.
        """
        prompt = f"""
        Analyze the following Telegram message:
        Message: "{user_message}"
        Question: Is the user explicitly asking/demanding for study material, notes, or PDFs?
        Respond ONLY with 'DEMAND' or 'DISCUSSION'.
        """
        
        # Primary API Call - Groq Engine
        if self.keys["groq"]:
            try:
                async with aiohttp.ClientSession() as session:
                    headers = {"Authorization": f"Bearer {self.keys['groq']}"}
                    payload = {
                        "model": "llama3-8b-8192",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.1
                    }
                    async with session.post(
                        "https://api.groq.com/openai/v1/chat/completions", 
                        json=payload, 
                        headers=headers
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            res = data['choices'][0]['message']['content'].strip()
                            return "DEMAND" in res.upper()
            except Exception:
                pass
        
        # Fallback heuristic rules if API fails or keys missing
        demand_keywords = ["pdf", "notes", "chahiye", "send", "give", "material", "link", "#"]
        return any(kw in user_message.lower() for kw in demand_keywords)

ai_engine = MultiLLMEngine()
