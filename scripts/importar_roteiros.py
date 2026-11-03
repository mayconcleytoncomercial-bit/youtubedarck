#!/usr/bin/env python3
"""Importa os roteiros (narração) do projeto "Recuerdos Dorados" do repo Metaads.

Lê os arquivos Python SEM executá-los (análise estática com `ast`) e junta todos
os campos `say="..."` de cada vídeo em inputs/roteiros/<video>.txt.

Uso:
  python3 scripts/importar_roteiros.py /caminho/para/metaads/facebook-nostalgia
"""
import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DESTINO = REPO_ROOT / "inputs" / "roteiros"
ARQUIVOS = ("build_video.py", "build_motion.py")


def falas(lista: ast.AST) -> list[str]:
    # build_motion.py usa dict(mood=..., scenes=[...]): entra na lista "scenes"
    if isinstance(lista, ast.Call):
        lista = next((kw.value for kw in lista.keywords if kw.arg == "scenes"), lista)
    out = []
    for item in getattr(lista, "elts", []):
        if isinstance(item, ast.Call):
            for kw in item.keywords:
                if kw.arg == "say" and isinstance(kw.value, ast.Constant):
                    out.append(kw.value.value)
    return out


def roteiros(arquivo: Path) -> dict[str, list[str]]:
    achados: dict[str, list[str]] = {}
    for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
        # VIDEOS = {"video1": [...], ...}  /  dicionários de vídeos em geral
        if isinstance(no, ast.Dict):
            for k, v in zip(no.keys, no.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str) and (f := falas(v)):
                    achados[k.value] = f
        # VIDEOS["reel3"] = [...]
        if isinstance(no, ast.Assign) and isinstance(no.targets[0], ast.Subscript):
            chave = no.targets[0].slice
            if isinstance(chave, ast.Constant) and (f := falas(no.value)):
                achados[chave.value] = f
    return achados


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    origem = Path(sys.argv[1])
    DESTINO.mkdir(parents=True, exist_ok=True)
    total = 0
    for nome in ARQUIVOS:
        arq = origem / nome
        if not arq.is_file():
            continue
        for video, linhas in roteiros(arq).items():
            (DESTINO / f"{video}.txt").write_text(" ".join(linhas) + "\n", encoding="utf-8")
            print(f"{video:8s} {len(' '.join(linhas).split()):4d} palavras  <- {nome}")
            total += 1
    print(f"{total} roteiros salvos em {DESTINO}")


if __name__ == "__main__":
    main()
