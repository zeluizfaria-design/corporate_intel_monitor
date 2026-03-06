"""Análise de sentimento usando FinBERT."""
from transformers import pipeline
from dataclasses import dataclass
from pathlib import Path
import torch

_LOCAL_MODEL = Path(__file__).parent.parent / "models" / "finbert-pt-br"


@dataclass
class SentimentResult:
    label: str           # 'POSITIVE' | 'NEGATIVE' | 'NEUTRAL'
    score: float
    compound: float      # -1.0 a +1.0


class SentimentAnalyzer:
    def __init__(self, model_name: str = "lucas-leme/FinBERT-PT-BR"):
        # Usa cópia local para evitar problema de symlinks do HuggingFace no Windows
        if _LOCAL_MODEL.exists():
            model_name = str(_LOCAL_MODEL)
        device = 0 if torch.cuda.is_available() else -1
        self._pipe = pipeline(
            "text-classification",
            model=model_name,
            device=device,
            truncation=True,
            max_length=512,
        )
        self._label_map = {"POSITIVE": 1.0, "NEUTRAL": 0.0, "NEGATIVE": -1.0}

    def analyze(self, text: str) -> SentimentResult:
        result = self._pipe(text[:2000])[0]
        label = result["label"].upper()
        score = result["score"]
        return SentimentResult(
            label=label,
            score=score,
            compound=self._label_map.get(label, 0.0) * score,
        )
