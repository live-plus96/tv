# armar.py - arma una lista M3U por caja a partir de iptv-org.
# No hace falta tocar este archivo. Lo unico que se edita a mano es cajas.csv.
import csv, json, re, urllib.request
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

FUENTE = "https://iptv-org.github.io/iptv/index.country.m3u"
CANALES_API = "https://iptv-org.github.io/api/channels.json"
MENSAJE_VENCIDO = "SUSCRIPCION VENCIDA - CONTACTAR PARA RENOVAR"

# Solo contenido explicito. NO poner palabras como "adult" o "hot" (botan canales normales).
PROHIBIDAS = re.compile(r"xxx|porn|er[oó]tic|playboy|hustler|brazzers|18\+", re.I)


def descargar(url):
    req = urllib.request.Request(url, headers={"User-Agent": "armar-listas"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read().decode("utf-8", errors="replace")


def atributo(extinf, nombre):
    m = re.search(nombre + r'="([^"]*)"', extinf)
    return m.group(1) if m else ""


def nombre_canal(extinf):
    # el nombre va despues de la primera coma que este fuera de comillas
    dentro = False
    for i, c in enumerate(extinf):
        if c == '"':
            dentro = not dentro
        elif c == "," and not dentro:
            return extinf[i + 1:]
    return ""


def leer_m3u(texto):
    cabecera, bloques, actual = "#EXTM3U", [], []
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        if linea.startswith("#EXTM3U"):
            cabecera = linea
        elif linea.startswith("#EXTINF"):
            actual = [linea]
        elif actual:
            actual.append(linea)
            if not linea.startswith("#"):  # la URL cierra el bloque
                bloques.append(actual)
                actual = []
    return cabecera, bloques


def main():
    nsfw = {c["id"] for c in json.loads(descargar(CANALES_API)) if c.get("is_nsfw")}
    cabecera, bloques = leer_m3u(descargar(FUENTE))
    if len(bloques) < 1000:
        raise SystemExit(f"La fuente trajo solo {len(bloques)} canales, algo anda mal. No publico nada.")

    buenos, sacados = [], {"geo": 0, "nsfw": 0, "palabras": 0}
    for b in bloques:
        extinf = b[0]
        nombre = nombre_canal(extinf)
        tvg_id = atributo(extinf, "tvg-id")
        if "geo-blocked" in nombre.lower():
            sacados["geo"] += 1
        elif tvg_id.split("@")[0] in nsfw:
            sacados["nsfw"] += 1
        elif PROHIBIDAS.search(" ".join([nombre, tvg_id, atributo(extinf, "group-title")])):
            sacados["palabras"] += 1
        else:
            buenos.append("\n".join(b))

    lista = cabecera + "\n" + "\n".join(buenos) + "\n"
    vencida = ("#EXTM3U\n"
               f'#EXTINF:-1 group-title="AVISO",{MENSAJE_VENCIDO}\n'
               "http://127.0.0.1/vencida\n")

    salida = Path("salida")
    salida.mkdir(exist_ok=True)
    (salida / ".nojekyll").write_text("")
    hoy = datetime.now(ZoneInfo("America/New_York")).date()
    activas = vencidas = 0

    with open("cajas.csv", encoding="utf-8-sig", newline="") as f:
        for fila in csv.DictReader(f):
            caja = (fila.get("caja") or "").strip().lower()
            if not re.fullmatch(r"[a-z0-9-]+", caja):
                print(f"Fila ignorada (caja invalida): {fila}")
                continue
            try:
                vence = date.fromisoformat((fila.get("vence") or "").strip())
            except ValueError:
                print(f"Fila ignorada (fecha invalida, usar AAAA-MM-DD): {fila}")
                continue
            if hoy <= vence:
                (salida / f"{caja}.m3u").write_text(lista, encoding="utf-8")
                activas += 1
            else:
                (salida / f"{caja}.m3u").write_text(vencida, encoding="utf-8")
                vencidas += 1

    print(f"Fuente: {len(bloques)} canales | quedan {len(buenos)} | sacados: {sacados}")
    print(f"Cajas activas: {activas} | vencidas: {vencidas} | fecha NY: {hoy}")


if __name__ == "__main__":
    main()
