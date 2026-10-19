# armar.py - arma una lista M3U por caja a partir de iptv-org.
# No hace falta tocar este archivo. Lo unico que se edita a mano es cajas.csv.
import csv, json, re, urllib.request
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

FUENTE = "https://iptv-org.github.io/iptv/index.country.m3u"
CANALES_API = "https://iptv-org.github.io/api/channels.json"
PAISES_API = "https://iptv-org.github.io/api/countries.json"
REGIONES_API = "https://iptv-org.github.io/api/regions.json"
MENSAJE_VENCIDO = "SUSCRIPCION VENCIDA - CONTACTAR PARA RENOVAR"

# Paises que entran en la lista: toda America (region AMER de iptv-org) + estos.
PAISES_EXTRA = {
    "CN", "IN", "JP", "KR", "SA",          # Asia
    "ZA", "EG", "NG", "KE", "MA",          # Africa
    "DE", "FR", "UK", "IT", "ES",          # Europa
}
# Canales sin pais fijo (feeds mundiales). Poner en False para sacarlos.
INCLUIR_INTERNACIONAL = True

# Numeros de canal fijos (tvg-chno). Una linea por canal: URL<TAB>numero.
# El robot lo actualiza y lo guarda en main en cada corrida. No editar a mano.
NUMEROS = Path("numeros.tsv")

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


def paises_permitidos():
    regiones = json.loads(descargar(REGIONES_API))
    america = set(next(r for r in regiones if r["code"] == "AMER")["countries"])
    codigos = america | PAISES_EXTRA
    nombres = {p["name"] for p in json.loads(descargar(PAISES_API)) if p["code"] in codigos}
    if INCLUIR_INTERNACIONAL:
        nombres.add("International")
    return nombres


def numerar(bloques):
    """Pone tvg-chno="N" en cada canal. Un canal conserva su numero para siempre,
    uno nuevo toma el mas alto + 1 y el de un canal eliminado no se reutiliza.
    Si falta numeros.tsv no numera nada (la app usa su propia numeracion)."""
    if not NUMEROS.exists():
        print("Falta numeros.tsv: publico SIN numeros de canal (no numero desde cero).")
        return bloques
    numeros = {}
    for linea in NUMEROS.read_text(encoding="utf-8").splitlines():
        if "\t" in linea:
            url, n = linea.rsplit("\t", 1)
            numeros[url] = int(n)
    if not numeros:
        print("numeros.tsv vacio: publico SIN numeros de canal.")
        return bloques
    siguiente = max(numeros.values()) + 1
    nuevos = 0
    for b in bloques:
        url = b[-1].strip()
        if url not in numeros:
            numeros[url] = siguiente
            siguiente += 1
            nuevos += 1
    salida = []
    for b in bloques:
        extinf = re.sub(r'\s*tvg-chno="[^"]*"', "", b[0])
        extinf = re.sub(r"^(#EXTINF:-?\d+)", rf'\1 tvg-chno="{numeros[b[-1].strip()]}"', extinf, count=1)
        salida.append([extinf] + b[1:])
    if nuevos:
        NUMEROS.write_text("".join(f"{u}\t{n}\n" for u, n in numeros.items()), encoding="utf-8")
    print(f"Numeros de canal: {len(bloques)} numerados | nuevos {nuevos} | mas alto {siguiente - 1}")
    return salida


def main():
    nsfw = {c["id"] for c in json.loads(descargar(CANALES_API)) if c.get("is_nsfw")}
    permitidos = paises_permitidos()
    cabecera, bloques = leer_m3u(descargar(FUENTE))
    if len(bloques) < 1000:
        raise SystemExit(f"La fuente trajo solo {len(bloques)} canales, algo anda mal. No publico nada.")

    buenos, sacados = [], {"geo": 0, "nsfw": 0, "palabras": 0, "pais": 0}
    for b in bloques:
        extinf = b[0]
        nombre = nombre_canal(extinf)
        tvg_id = atributo(extinf, "tvg-id")
        if atributo(extinf, "group-title") not in permitidos:
            sacados["pais"] += 1
        elif "geo-blocked" in nombre.lower():
            sacados["geo"] += 1
        elif tvg_id.split("@")[0] in nsfw:
            sacados["nsfw"] += 1
        elif PROHIBIDAS.search(" ".join([nombre, tvg_id, atributo(extinf, "group-title")])):
            sacados["palabras"] += 1
        else:
            buenos.append(b)

    if len(buenos) < 1000:
        raise SystemExit(f"Quedaron solo {len(buenos)} canales tras filtrar. No publico nada.")

    salida = Path("salida")
    salida.mkdir(exist_ok=True)
    hoy = datetime.now(ZoneInfo("America/New_York")).date()

    # Paso nuevo: probar los canales y sacar los muertos (ver probar_canales.py).
    # Si la prueba se rompe por lo que sea, se publica la lista sin filtrar.
    try:
        from probar_canales import filtrar_muertos
        buenos = filtrar_muertos(buenos, hoy, salida)
    except Exception as e:
        print(f"La prueba de canales fallo ({e}). Publico la lista sin filtrar.")

    try:
        buenos = numerar(buenos)
    except Exception as e:
        print(f"La numeracion fallo ({e}). Publico SIN numeros de canal.")

    lista = cabecera + "\n" + "\n".join("\n".join(b) for b in buenos) + "\n"
    vencida = ("#EXTM3U\n"
               f'#EXTINF:-1 group-title="AVISO",{MENSAJE_VENCIDO}\n'
               "http://127.0.0.1/vencida\n")

    (salida / ".nojekyll").write_text("")
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
    print(f"Paises permitidos: {len(permitidos)}")
    print(f"Cajas activas: {activas} | vencidas: {vencidas} | fecha NY: {hoy}")


if __name__ == "__main__":
    main()
