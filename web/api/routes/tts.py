import os
import base64
import re
import wave
import io
import tempfile
from pathlib import Path
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv

router = APIRouter()
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
AUDIO_DIR = PROJECT_ROOT / "data" / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

class TTSRequest(BaseModel):
    session_id: str
    message_id: str
    text: str
    voice_description: str
    voice_name: str = ""

@router.post("/generate")
def generate_tts(req: TTSRequest):
    safe_msg_id = "".join(c for c in req.message_id if c.isalnum() or c in "_-")
    audio_path = AUDIO_DIR / f"{req.session_id}_{safe_msg_id}.wav"
    
    if audio_path.exists():
        if audio_path.stat().st_size > 0:
            return {"audio_url": f"/api/tts/audio/{req.session_id}_{safe_msg_id}.wav"}
        else:
            audio_path.unlink() # Remove empty file
    
    load_dotenv()
    api_key = os.getenv("MIMO_API_KEY") or os.getenv("SALON_API_KEY")
    if not api_key:
        print("[TTS] MIMO_API_KEY not found. Skipping real TTS generation.")
        return {"audio_url": None}

    if not req.voice_description:
        print("[TTS] No voice_description provided for agent. Skipping TTS.")
        return {"audio_url": None}

    try:
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.xiaomimimo.com/v1"
        )
        
        # Clean text
        clean_text = re.sub(r'[*_#`]', '', req.text)
        clean_text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', clean_text)
        
        # Split text into chunks to bypass 1-minute/length limits
        def split_text(text: str, max_len: int = 150):
            text = text.strip()
            if not text: return []
            sentences = re.split(r'([。！？.!?\n]+)', text)
            chunks = []
            current = ""
            for i in range(0, len(sentences) - 1, 2):
                s = sentences[i] + sentences[i+1]
                if len(current) + len(s) > max_len and current:
                    chunks.append(current.strip())
                    current = s
                else:
                    current += s
            if len(sentences) % 2 != 0 and sentences[-1]:
                if len(current) + len(sentences[-1]) > max_len and current:
                    chunks.append(current.strip())
                    current = sentences[-1]
                else:
                    current += sentences[-1]
            if current.strip(): chunks.append(current.strip())
            
            final_chunks = []
            for c in chunks:
                while len(c) > max_len:
                    split_idx = max(c.rfind('，', 0, max_len), c.rfind(',', 0, max_len), c.rfind('；', 0, max_len), c.rfind('、', 0, max_len))
                    if split_idx <= 0: split_idx = max_len
                    final_chunks.append(c[:split_idx].strip())
                    c = c[split_idx:].strip()
                if c: final_chunks.append(c)
            return final_chunks

        chunks = split_text(clean_text)
        
        def _tts_one_chunk(chunk_text):
            """Request TTS for a single chunk. Returns audio bytes or None."""
            if not chunk_text:
                return None
            payload_audio = {"format": "wav"}
            if req.voice_name:
                payload_audio["voice"] = req.voice_name

            completion = client.chat.completions.create(
                model="mimo-v2.5-tts",
                messages=[
                    {"role": "user", "content": req.voice_description},
                    {"role": "assistant", "content": chunk_text}
                ],
                audio=payload_audio
            )
            
            message = completion.choices[0].message
            audio_obj = getattr(message, 'audio', None)
            if audio_obj:
                if hasattr(audio_obj, 'data'):
                    return base64.b64decode(audio_obj.data)
                elif isinstance(audio_obj, dict) and 'data' in audio_obj:
                    return base64.b64decode(audio_obj['data'])
                else:
                    print(f"[TTS DEBUG] Unexpected audio object type: {type(audio_obj)}")
            else:
                raw_dict = message.model_dump()
                if 'audio' in raw_dict and raw_dict['audio'] and 'data' in raw_dict['audio']:
                    return base64.b64decode(raw_dict['audio']['data'])
            return None

        # Parallel TTS requests, max 4 concurrent
        from concurrent.futures import ThreadPoolExecutor, as_completed
        audio_data_list = [None] * len(chunks)
        with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
            future_to_idx = {pool.submit(_tts_one_chunk, c): i for i, c in enumerate(chunks)}
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    result = future.result()
                    audio_data_list[idx] = result
                except Exception as e:
                    print(f"[TTS] Chunk {idx} failed: {e}")
        
        # Filter out None (failed chunks) while preserving order
        audio_data_list = [d for d in audio_data_list if d is not None]
                
        if not audio_data_list:
            print("[TTS] API response did not contain any valid audio data for chunks")
            return {"audio_url": None}
            
        fd, temp_path = tempfile.mkstemp(dir=AUDIO_DIR.as_posix(), suffix=".wav")
        os.close(fd)
        
        try:
            with wave.open(temp_path, 'wb') as outfile:
                for i, data in enumerate(audio_data_list):
                    with wave.open(io.BytesIO(data), 'rb') as infile:
                        if i == 0:
                            outfile.setparams(infile.getparams())
                        outfile.writeframes(infile.readframes(infile.getnframes()))
            
            os.replace(temp_path, audio_path.as_posix())
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise e
                    
        return {"audio_url": f"/api/tts/audio/{req.session_id}_{safe_msg_id}.wav"}
            
    except Exception as e:
        print(f"[TTS] Error calling MiMo API: {e}")
        return {"audio_url": None}

@router.get("/audio/{filename}")
def get_audio(filename: str):
    audio_path = AUDIO_DIR / filename
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(audio_path, media_type="audio/wav")
