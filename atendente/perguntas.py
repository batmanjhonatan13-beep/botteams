"""
Uma forma por tipo de pergunta. O modelo nunca recebe conversa — recebe UMA pergunta
fechada, do tamanho do necessario, e a resposta dele e lida e jogada fora.

A licao que este arquivo carrega do dragon_ia esta medida: numa bateria de 400 cadeias de
raciocinio, 31 respostas vieram como "Nao sei." — e a causa nao era o modelo. Era uma
linha do proprio prompt do sistema, que dizia "se nao souber, diga que nao sabe". Modelo
pequeno obedece ao pe da letra. Por isso, aqui, nenhum sistema manda o modelo se recusar:
eles mandam ENDERECAR a pergunta com o que ele tem.
"""

# Nome do time e o que ele faz entram por config (perfil.md), nao aqui: outro time troca
# o arquivo e o bot muda de dono sem tocar em codigo.
BASE = ("Voce e o assistente de um time de plantao. Responda em portugues do Brasil, "
        "direto, sem saudacao e sem se apresentar. ")

PERGUNTAS = {
    # ------------------------------------------------------------------ conversa normal
    "resposta": {
        "fichas_de_saida": 700,
        "temperatura": 0.2,
        "sistema": (
            BASE +
            "Responda a pergunta da pessoa. "
            "Quando vier um bloco FATOS, ele e documentacao interna do time: use os "
            "numeros, nomes e enderecos que estao nele em vez dos seus. "
            "Quando os FATOS nao responderem, responda com o que voce sabe e diga em uma "
            "linha que a documentacao interna consultada nao cobre esse ponto. "
            "Quando vier 'Assunto desta conversa', a pergunta e sobre esse assunto: "
            "responda sobre ele, nao peca para a pessoa repetir."
        ),
        "monta": lambda d: "\n\n".join(p for p in [
            (f"FATOS (documentacao interna):\n{d['fatos']}" if d.get("fatos") else ""),
            (d.get("digesto") or ""),
            (f"PERFIL DO TIME:\n{d['perfil']}" if d.get("perfil") else ""),
            f"PERGUNTA: {d.get('pergunta', '')}",
        ] if p),
        "le": lambda bruto: str(bruto or "").strip(),
        "valida": lambda t: isinstance(t, str) and len(t.strip()) >= 2,
    },

    # ------------------------------------------------------------------ resumo rolante
    "resumo": {
        "fichas_de_saida": 160,
        "temperatura": 0.1,
        "sistema": ("Voce resume uma conversa entre uma pessoa e o assistente do time. "
                    "Escreva no maximo tres linhas dizendo O QUE ESTA SENDO TRATADO e o "
                    "que ja ficou decidido. Nada de saudacao, nada de opiniao, nada de "
                    "codigo."),
        "monta": lambda d: str(d.get("conversa", "")) +
                 "\n\nResuma em ate tres linhas: qual e o assunto e o que ja ficou decidido.",
        "le": lambda bruto: " ".join(str(bruto or "").split()).strip(),
        "valida": lambda t: isinstance(t, str) and len(t) > 10 and "```" not in t,
    },
}
