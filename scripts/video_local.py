#!/usr/bin/env python3
"""Vídeo de avatar 100% local e gratuito (sem inference.sh).

Faz:
  1. Narração em espanhol com edge-tts (voz es-MX-JorgeNeural, mesma dos reels), com o tempo de cada palavra.
  2. Movimento de câmera lento sobre a foto do avatar (zoom e cortes de detalhe a cada ~5 s), formato 4:5.
  3. Legendas karaokê sincronizadas (blocos de até 4 palavras), grão de filme, vinheta e aviso de IA.
  4. Masterização do áudio em -14 LUFS e H.264, pronto para Facebook/Instagram.

Observação: não há sincronia labial (a boca não mexe). Para isso, use processar_video.py com saldo no inference.sh.

Uso:
  python3 scripts/video_local.py --roteiro inputs/roteiros/reel2.txt
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PASTA_SAIDA = REPO_ROOT / "output" / "videos"
W, H, FPS = 1080, 1350, 30
FONTE = "DejaVu Serif"
AVISO_IA = "Imagen y voz generadas con IA"

# Cortes (x, y, largura, altura) em fração da foto. Vertical 9:16 -> recortes 4:5.
# Pensados para a foto inputs/avatar.jpg (rosto em cima, xícara embaixo à direita).
CENAS = [
    dict(box=(0.00, 0.12, 1.00, 0.70), zoom=(1.00, 1.08)),   # plano geral, aproxima
    dict(box=(0.21, 0.18, 0.56, 0.39), zoom=(1.00, 1.06)),   # rosto
    dict(box=(0.47, 0.63, 0.53, 0.37), zoom=(1.06, 1.00)),   # mãos e café
    dict(box=(0.10, 0.15, 0.79, 0.55), zoom=(1.00, 1.05)),   # meio corpo
    dict(box=(0.00, 0.12, 1.00, 0.70), zoom=(1.08, 1.00)),   # volta ao geral, afasta
]


def rodar(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"ERRO ao rodar {cmd[0]}:\n{p.stderr[-2000:]}")
    return p.stdout


async def narrar(texto: str, voz: str, ritmo: str, destino: Path) -> list[tuple[float, float, str]]:
    import edge_tts
    com = edge_tts.Communicate(texto, voz, rate=ritmo, proxy=os.environ.get("HTTPS_PROXY"),
                               boundary="WordBoundary")
    palavras = []
    with open(destino, "wb") as fh:
        async for ch in com.stream():
            if ch["type"] == "audio":
                fh.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                ini = ch["offset"] / 1e7
                palavras.append((ini, ini + ch["duration"] / 1e7, ch["text"]))
    # devolve a pontuação/acentos do texto original quando o número de palavras bate
    originais = texto.split()
    if len(originais) == len(palavras):
        palavras = [(i, f, o) for (i, f, _), o in zip(palavras, originais)]
    return palavras


def duracao(arq: Path) -> float:
    return float(rodar(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(arq)]).strip())


def ts(s: float) -> str:
    h, r = divmod(max(s, 0), 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def legendas_ass(palavras, destino: Path) -> None:
    """Blocos de até 4 palavras, quebrando na pontuação; palavra falada acende em âmbar."""
    blocos, atual = [], []
    for p in palavras:
        atual.append(p)
        if len(atual) == 4 or re.search(r"[.,;:?!…]$", p[2]):
            blocos.append(atual)
            atual = []
    if atual:
        blocos.append(atual)

    linhas = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        # Primary = palavra já falada (âmbar), Secondary = ainda não falada (creme). Cores em &HBBGGRR.
        f"Style: Leg,{FONTE},74,&H0032B4F5,&H00E6F5FF,&H00101820,&H80000000,1,0,0,0,100,100,0,0,1,5,2,2,70,70,170,1",
        f"Style: Aviso,{FONTE},30,&H00E6F5FF,&H00E6F5FF,&H00101820,&H80000000,0,1,0,0,100,100,0,0,1,2,1,8,40,40,40,1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    fim_total = palavras[-1][1] + 1.0
    linhas.append(f"Dialogue: 0,{ts(0)},{ts(fim_total)},Aviso,,0,0,0,,{AVISO_IA}")
    for i, b in enumerate(blocos):
        ini = b[0][0]
        fim = blocos[i + 1][0][0] if i + 1 < len(blocos) else b[-1][1] + 0.8
        partes, cursor = [], ini
        for (pi, pf, txt) in b:
            if pi > cursor:                       # pausa antes da palavra
                partes.append(f"{{\\k{round((pi - cursor) * 100)}}}")
            partes.append(f"{{\\kf{max(1, round((pf - pi) * 100))}}}{txt} ")
            cursor = pf
        linhas.append(f"Dialogue: 1,{ts(ini)},{ts(fim)},Leg,,0,0,0,,{{\\fad(120,120)}}{''.join(partes).strip()}")
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def cena(imagem: Path, larg: int, alt: int, c: dict, seg: float, destino: Path) -> None:
    x, y, w, h = c["box"]
    z0, z1 = c["zoom"]
    n = round(seg * FPS)
    # recorta a região, amplia 2x (zoom suave sem serrilhado) e aplica zoompan centralizado
    filtro = (
        f"crop={round(w * larg)}:{round(h * alt)}:{round(x * larg)}:{round(y * alt)},"
        f"scale={W * 2}:{H * 2}:flags=lanczos,setsar=1,"
        f"zoompan=z='{z0}+({z1}-{z0})*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={n}:s={W}x{H}:fps={FPS}"
    )
    rodar(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(imagem), "-vf", filtro,
           "-frames:v", str(n), "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "16", "-preset", "fast",
           str(destino)])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--imagem", default=str(REPO_ROOT / "inputs" / "avatar.jpg"))
    p.add_argument("--roteiro", default=str(REPO_ROOT / "inputs" / "roteiros" / "reel2.txt"))
    p.add_argument("--voz", default="es-MX-JorgeNeural")
    p.add_argument("--ritmo", default="-6%", help="velocidade da fala (padrão dos reels: -6%%)")
    p.add_argument("--nome", default="video_avatar_final.mp4")
    a = p.parse_args()

    imagem, roteiro = Path(a.imagem), Path(a.roteiro)
    for arq in (imagem, roteiro):
        if not arq.is_file():
            sys.exit(f"ERRO: arquivo não encontrado: {arq}")
    texto = " ".join(roteiro.read_text(encoding="utf-8").split())
    if not texto:
        sys.exit("ERRO: roteiro vazio")
    if not a.nome.endswith(".mp4") or "/" in a.nome:
        sys.exit("ERRO: --nome deve ser só um nome de arquivo .mp4")

    larg, alt = map(int, rodar(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=width,height", "-of", "csv=p=0", str(imagem)]).strip().split(","))

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        print("1/4 Narração (edge-tts)...")
        voz_mp3 = tmp / "voz.mp3"
        palavras = asyncio.run(narrar(texto, a.voz, a.ritmo, voz_mp3))
        if not palavras:
            sys.exit("ERRO: a narração não devolveu o tempo das palavras")
        total = duracao(voz_mp3) + 1.0              # 1 s de respiro no final

        print(f"2/4 Movimento de câmera ({total:.1f} s, {len(CENAS)} cenas)...")
        fade = 0.6
        seg = (total + fade * (len(CENAS) - 1)) / len(CENAS)
        partes = []
        for i, c in enumerate(CENAS):
            cena(imagem, larg, alt, c, seg, tmp / f"c{i}.mp4")
            partes.append(tmp / f"c{i}.mp4")

        print("3/4 Legendas...")
        legendas_ass(palavras, tmp / "leg.ass")

        print("4/4 Montagem final e áudio em -14 LUFS...")
        entradas, cadeia, ultimo = [], [], "[0:v]"
        for arq in partes:
            entradas += ["-i", str(arq)]
        for i in range(1, len(partes)):
            off = i * (seg - fade)
            cadeia.append(f"{ultimo}[{i}:v]xfade=transition=fade:duration={fade}:offset={off:.3f}[x{i}]")
            ultimo = f"[x{i}]"
        cadeia.append(
            f"{ultimo}noise=alls=7:allf=t,vignette=PI/5,"
            f"ass={tmp / 'leg.ass'}:fontsdir=/usr/share/fonts/truetype/dejavu,format=yuv420p[v]"
        )
        ia = len(partes)
        cadeia.append(
            f"[{ia}:a]highpass=f=80,acompressor=threshold=-18dB:ratio=3:attack=5:release=120,"
            f"apad=pad_dur=1,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"
        )
        PASTA_SAIDA.mkdir(parents=True, exist_ok=True)
        destino = PASTA_SAIDA / a.nome
        rodar(["ffmpeg", "-y", "-loglevel", "error", *entradas, "-i", str(voz_mp3),
               "-filter_complex", ";".join(cadeia), "-map", "[v]", "-map", "[a]",
               "-t", f"{total:.3f}", "-c:v", "libx264", "-profile:v", "high", "-crf", "18", "-preset", "medium",
               "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(destino)])

    if not destino.is_file() or destino.stat().st_size == 0:
        sys.exit(f"ERRO: vídeo não gerado em {destino}")
    print(f"OK: {destino.resolve()} ({duracao(destino):.1f} s, {destino.stat().st_size / 1_048_576:.1f} MB)")


if __name__ == "__main__":
    main()
