#!/usr/bin/env python3
"""Gera um vídeo de avatar falante a partir de uma imagem e de um roteiro (.txt).

Usa a CLI do inference.sh (`belt`) com o app `pruna/p-video-avatar`.

Segurança:
  - A chave de API NUNCA fica no código. A `belt` lê a variável de ambiente
    INFERENCE_API_KEY (ou a sessão criada com `belt login`).
  - O script nunca imprime a chave.

Uso:
  export INFERENCE_API_KEY=...      # ou: belt login
  python3 scripts/processar_video.py \
      --imagem inputs/avatar.jpg \
      --roteiro inputs/roteiro.txt

Saída obrigatória: output/videos/video_avatar_final.mp4 (relativo à raiz do repo).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP = "pruna/p-video-avatar@4a8x19t1"
REPO_ROOT = Path(__file__).resolve().parent.parent
PASTA_SAIDA = REPO_ROOT / "output" / "videos"
NOME_FINAL = "video_avatar_final.mp4"

# O app não tem vozes Google/Edge. Mapeamos cada nome para a voz equivalente
# do app (mesmo gênero) e para o idioma correspondente.
MAPA_VOZES = {
    "pt-BR-Wavenet-A": ("Kore (Female)", "Portuguese (Brazil)"),
    "pt-BR-Wavenet-B": ("Puck (Male)", "Portuguese (Brazil)"),
    "pt-BR-Wavenet-C": ("Kore (Female)", "Portuguese (Brazil)"),
    # voz usada nos reels do "Recuerdos Dorados" (repo Metaads)
    "es-MX-JorgeNeural": ("Charon (Male)", "Spanish"),
}
# Mesmo tom calmo dos reels: ritmo lento (~130 palavras/min) para público 50+.
ESTILO_VOZ = {
    "Spanish": "Voz cálida y nostálgica de un narrador latinoamericano, ritmo pausado y tranquilo.",
}
EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".webp"}


def falhar(msg: str) -> None:
    print(f"ERRO: {msg}", file=sys.stderr)
    sys.exit(1)


def belt(*args: str) -> str:
    """Executa a CLI `belt` sem prompts interativos e devolve o stdout."""
    if not shutil.which("belt"):
        falhar("CLI 'belt' não encontrada. Instale: curl -fsSL https://cli.inference.sh | sh")
    proc = subprocess.run(["belt", "--no-input", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        falhar(f"'belt {args[0]} {args[1] if len(args) > 1 else ''}' falhou:\n{proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def procurar_url(obj) -> str | None:
    """Encontra o primeiro campo uri/url em uma resposta JSON."""
    if isinstance(obj, dict):
        for chave in ("uri", "url"):
            if isinstance(obj.get(chave), str):
                return obj[chave]
        for v in obj.values():
            if (achado := procurar_url(v)):
                return achado
    elif isinstance(obj, list):
        for v in obj:
            if (achado := procurar_url(v)):
                return achado
    return None


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--imagem", default=str(REPO_ROOT / "inputs" / "avatar.jpg"))
    p.add_argument("--roteiro", default=str(REPO_ROOT / "inputs" / "roteiro.txt"))
    p.add_argument("--voz", default="pt-BR-Wavenet-C",
                   help="Nome Wavenet/Edge (mapeado) ou voz nativa do app, ex.: 'Kore (Female)'")
    p.add_argument("--idioma", help="Idioma do app, ex.: 'Spanish'. Padrão: o da voz escolhida")
    p.add_argument("--nome", default=NOME_FINAL, help=f"Nome do arquivo final (padrão: {NOME_FINAL})")
    p.add_argument("--resolucao", default="720p", choices=["720p", "1080p"])
    p.add_argument("--estimar", action="store_true", help="Só mostra o custo previsto, sem gerar")
    a = p.parse_args()

    # 1. Validar entradas
    imagem, roteiro = Path(a.imagem), Path(a.roteiro)
    if not imagem.is_file():
        falhar(f"imagem não encontrada: {imagem}")
    if imagem.suffix.lower() not in EXTENSOES_IMAGEM:
        falhar(f"formato de imagem não suportado ({imagem.suffix}). Use jpg, jpeg, png ou webp.")
    if not roteiro.is_file():
        falhar(f"roteiro não encontrado: {roteiro}")
    texto = roteiro.read_text(encoding="utf-8").strip()
    if not texto:
        falhar("o roteiro está vazio")

    voz, idioma = MAPA_VOZES.get(a.voz, (a.voz, "Portuguese (Brazil)"))
    idioma = a.idioma or idioma
    if not a.nome.endswith(".mp4") or "/" in a.nome:
        falhar("--nome deve ser só um nome de arquivo terminado em .mp4")
    print(f"Imagem : {imagem}")
    print(f"Roteiro: {roteiro} ({len(texto.split())} palavras, ~{len(texto.split()) / 130 * 60:.0f} s)")
    print(f"Voz    : {a.voz} -> {voz} / {idioma}")

    # 2. Enviar a imagem para o inference.sh
    print("Enviando imagem...")
    url_imagem = procurar_url(json.loads(belt("file", "upload", str(imagem), "--json")))
    if not url_imagem:
        falhar("upload da imagem não retornou URL")

    entrada = {
        "image": url_imagem,
        "voice_script": texto,
        "voice": voz,
        "voice_language": idioma,
        "resolution": a.resolucao,
    }
    if idioma in ESTILO_VOZ:
        entrada["voice_prompt"] = ESTILO_VOZ[idioma]

    with tempfile.TemporaryDirectory() as tmp:
        arq_entrada = Path(tmp) / "input.json"
        arq_entrada.write_text(json.dumps(entrada, ensure_ascii=False), encoding="utf-8")

        if a.estimar:
            print(belt("app", "run", APP, "--input", f"@{arq_entrada}", "--estimate"))
            return

        # 3. Gerar o vídeo e baixar os arquivos de saída
        print("Gerando vídeo (pode levar alguns minutos)...")
        pasta_download = Path(tmp) / "download"
        belt("app", "run", APP, "--input", f"@{arq_entrada}", f"--download={pasta_download}")

        videos = sorted(pasta_download.rglob("*.mp4")) if pasta_download.exists() else []
        if not videos:
            falhar("a geração terminou, mas nenhum .mp4 foi baixado")

        # 4. Salvar no destino obrigatório
        PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
        destino = PASTA_SAIDA / a.nome
        shutil.move(str(videos[0]), destino)

    # 5. Validação final
    if not destino.is_file() or destino.stat().st_size == 0:
        falhar(f"vídeo não encontrado (ou vazio) em {destino}")
    print(f"OK: vídeo salvo em {destino.resolve()} ({destino.stat().st_size / 1_048_576:.2f} MB)")


if __name__ == "__main__":
    main()
