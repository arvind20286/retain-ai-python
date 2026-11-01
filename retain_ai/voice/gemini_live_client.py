from contextlib import asynccontextmanager
import logging
from typing import AsyncIterator, Optional
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

class GeminiLiveClient:
    """
    Wraps google-genai SDK's Live API session handling (bidirectional audio and text).
    Focuses on the Gemini Live API lifecycle.
    """

    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model_name = model_name
        self.client = genai.Client(api_key=api_key) if api_key else None

    @asynccontextmanager
    async def connect(
        self,
        system_prompt: str,
        voice_name: str = "Puck",
        tools: Optional[list[types.Tool]] = []
    ) -> AsyncIterator[any]:
        """
        Establishes an async bidirectional Live session with Gemini.
        Yields the active AsyncSession.
        """
        if not self.client:
            raise ValueError("GEMINI_API_KEY is not configured.")

        # Ensure model is compatible with Live API
        live_model = self.model_name
        if not ("flash" in live_model.lower() or "live" in live_model.lower()):
            live_model = "gemini-3.8-live"

        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                )
            ),
            system_instruction=system_prompt,
            tools=tools
        )

        logger.info("Connecting to Gemini Live API with model '%s' and voice '%s'...", live_model, voice_name)
        async with self.client.aio.live.connect(model=live_model, config=config) as session:
            logger.info("Successfully connected to Gemini Live session.")
            yield session
            logger.info("Gemini Live session closed.")

