"""LSH deduplication para artigos coletados."""
import hashlib
import re
from datasketch import MinHash, MinHashLSH
from dataclasses import dataclass


@dataclass
class DeduplicationResult:
    is_duplicate: bool
    similar_ids: list[str]
    similarity: float


class Deduplicator:
    """
    Deduplicação em duas camadas:
    1. SHA256 da URL (dedup exata — tratada no banco com UNIQUE)
    2. MinHash LSH para dedup por similaridade de conteúdo (~Jaccard >= threshold)
    """

    def __init__(self, threshold: float = 0.85, num_perm: int = 128):
        self._lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self._num_perm = num_perm
        self._seen_urls: set[str] = set()

    def is_exact_duplicate(self, url: str) -> bool:
        url_hash = hashlib.sha256(url.encode()).hexdigest()
        if url_hash in self._seen_urls:
            return True
        self._seen_urls.add(url_hash)
        return False

    def check_and_add(self, article_id: str, text: str) -> DeduplicationResult:
        """Verifica similaridade via LSH e adiciona ao índice se não duplicado."""
        minhash = self._compute_minhash(text)
        similar = self._lsh.query(minhash)

        if similar:
            return DeduplicationResult(
                is_duplicate=True,
                similar_ids=similar,
                similarity=1.0,  # threshold foi atingido
            )

        try:
            self._lsh.insert(article_id, minhash)
        except ValueError:
            # ID já existe no índice
            pass

        return DeduplicationResult(is_duplicate=False, similar_ids=[], similarity=0.0)

    def _compute_minhash(self, text: str) -> MinHash:
        m = MinHash(num_perm=self._num_perm)
        tokens = self._tokenize(text)
        for token in tokens:
            m.update(token.encode("utf-8"))
        return m

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Tokenização em shingles de 3 palavras."""
        words = re.findall(r"\w+", text.lower())
        if len(words) < 3:
            return words
        return [" ".join(words[i:i+3]) for i in range(len(words) - 2)]
