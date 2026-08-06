"""Descarga local de los GIF de ejecución.

Opcional. Sin esto la aplicación enlaza los GIF al repositorio original, que
es lo que funciona por defecto y lo que respeta la licencia del material. Con
esto se obtiene una copia local para trabajar sin conexión y para exportar
documentos autocontenidos (`?embed=1`), que es lo práctico si vas a llevarte
la rutina al gimnasio.

El directorio de destino está en `.gitignore`: el material es propiedad de
Gym visual y no debe acabar versionado en este repositorio. Si vas a
distribuir la copia local, revisa antes sus condiciones de uso en
https://gymvisual.com/content/3-terms-and-conditions-of-use

Uso:
    python scripts/fetch_media.py              # todos los ejercicios
    python scripts/fetch_media.py --ids 0025 0043
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "catalog.json"
DEFAULT_DIR = ROOT / "data" / "media"


def download(url: str, target: Path) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
            target.write_bytes(response.read())
        return True
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"  fallo: {url} ({exc})", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(DEFAULT_DIR), help="Directorio de destino")
    parser.add_argument("--ids", nargs="*", help="Descargar solo estos ids")
    args = parser.parse_args()

    if not CATALOG.exists():
        print("Falta data/catalog.json. Ejecuta antes scripts/build_catalog.py.", file=sys.stderr)
        return 1

    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    if args.ids:
        wanted = set(args.ids)
        catalog = [entry for entry in catalog if entry["id"] in wanted]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    downloaded = skipped = failed = 0
    for index, entry in enumerate(catalog, 1):
        name = entry["gif_url"].rsplit("/", 1)[-1]
        target = out / name
        if target.exists() and target.stat().st_size > 0:
            skipped += 1
            continue
        if download(entry["gif_url"], target):
            downloaded += 1
        else:
            failed += 1
            target.unlink(missing_ok=True)
        if index % 50 == 0:
            print(f"  {index}/{len(catalog)}...", file=sys.stderr)

    print(f"descargados {downloaded}, ya presentes {skipped}, fallidos {failed} -> {out}")
    print("© Gym visual — https://gymvisual.com/ (conserva la atribución al usarlos)")
    return 1 if failed and not downloaded else 0


if __name__ == "__main__":
    raise SystemExit(main())
