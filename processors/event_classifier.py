"""Classificador de tipo de evento corporativo por regex."""
import re
from enum import Enum


class EventType(str, Enum):
    RESULTADO_FINANCEIRO = "resultado_financeiro"
    FUSAO_AQUISICAO      = "fusao_aquisicao"
    DIVIDENDOS           = "dividendos"
    MUDANCA_GESTAO       = "mudanca_gestao"
    INVESTIGACAO_LEGAL   = "investigacao_legal"
    EMISSAO_ACOES        = "emissao_acoes"
    PARCERIA             = "parceria"
    PRODUTO_LANCAMENTO   = "produto_lancamento"
    MACRO_ECONOMICO      = "macro_economico"
    INSIDER_COMPRA       = "insider_compra"
    INSIDER_VENDA        = "insider_venda"
    INSIDER_CONCESSAO    = "insider_concessao"
    POLITICO_COMPRA      = "politico_compra"
    POLITICO_VENDA       = "politico_venda"
    OUTRO                = "outro"


_PATTERNS: dict[EventType, list[str]] = {
    EventType.RESULTADO_FINANCEIRO: [r"\b(resultado|lucro|receita|ebitda|balanço|trimest)\b"],
    EventType.FUSAO_AQUISICAO:      [r"\b(aquisição|fusão|incorporação|merger|takeover|opa)\b"],
    EventType.DIVIDENDOS:           [r"\b(dividendo|jcp|juros capital próprio|provento)\b"],
    EventType.MUDANCA_GESTAO:       [r"\b(ceo|diretor|presidente|renúncia|nomeação|board)\b"],
    EventType.INVESTIGACAO_LEGAL:   [r"\b(investigação|processo|cvm|sec|multa|fraude)\b"],
    EventType.EMISSAO_ACOES:        [r"\b(emissão|follow.on|ipo|oferta|debênture)\b"],
    EventType.INSIDER_COMPRA:       [r"\[INSIDER\]\[COMPRA\]"],
    EventType.INSIDER_VENDA:        [r"\[INSIDER\]\[VENDA\]"],
    EventType.INSIDER_CONCESSAO:    [r"\[INSIDER\]\[CONCESS"],
    EventType.POLITICO_COMPRA:      [r"\[POLÍTICO\]\[COMPRA\]"],
    EventType.POLITICO_VENDA:       [r"\[POLÍTICO\]\[VENDA\]"],
}


def classify_event(title: str, content: str) -> EventType:
    text = (title + " " + content[:500]).lower()
    scores = {et: 0 for et in EventType}
    for event_type, patterns in _PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                scores[event_type] += 1
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else EventType.OUTRO
