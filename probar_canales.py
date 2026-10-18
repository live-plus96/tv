# probar_canales.py - prueba los canales y saca los que estan muertos.
# Lo usa armar.py solo. No hace falta tocar este archivo.
#
# Reglas:
#   1. Un canal se saca solo si fallo hoy Y en la corrida de un dia anterior.
#   2. Los canales "Not 24/7" se prueban pero NUNCA se sacan.
#   3. Freno: si falla mas del 40% de la lista, se asume que fallo la red del
#      robot (no los canales) y se publica todo sin sacar nada.
#   4. Si el servidor responde "no autorizado" (401/403/451/429) el canal NO se
#      cuenta como muerto: suele ser bloqueo a servidores de datacenter, y desde
#      la casa del cliente puede andar.
#
# Prueba a mano (no publica nada, solo mide):
#   python probar_canales.py lista.m3u
import json, socket, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

ESTADO_URL = "https://tv.netbodiam.net/estado-canales.json"  # lo que publico ayer
ESTADO_ARCHIVO = "estado-canales.json"                      # lo que publica hoy
HILOS = 100        # canales probados a la vez
TIMEOUT = 10       # segundos por intento
INTENTOS = 2       # un canal "muerto" se reintenta una vez antes de contarlo
FRENO = 0.40       # mas de este % muerto = falla del robot, no de los canales
UA_DEFECTO = "VLC/3.0.20 LibVLC/3.0.20"
RECHAZO = {401, 403, 429, 451}


def url_de(bloque):
    return bloque[-1].strip()


def cabeceras(bloque):
    h = {"User-Agent": UA_DEFECTO}
    for linea in bloque[1:-1]:
        low = linea.lower()
        if low.startswith("#extvlcopt:http-user-agent="):
            h["User-Agent"] = linea.split("=", 1)[1].strip()
        elif low.startswith("#extvlcopt:http-referrer="):
            h["Referer"] = linea.split("=", 1)[1].strip()
    return h


def no_24_7(bloque):
    return "not 24/7" in bloque[0].lower()


def probar_una_vez(bloque):
    url = url_de(bloque)
    if not url.lower().startswith(("http://", "https://")):
        return "vivo"  # rtmp/udp/etc: no se puede probar asi, se deja
    req = urllib.request.Request(url, headers=cabeceras(bloque))
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return "vivo" if r.read(2048) else "muerto"
    except urllib.error.HTTPError as e:
        return "rechazado" if e.code in RECHAZO else "muerto"
    except Exception:
        return "muerto"  # DNS, conexion, timeout, certificado, etc.


def probar(bloque):
    for _ in range(INTENTOS):
        r = probar_una_vez(bloque)
        if r != "muerto":
            return r
    return "muerto"


def probar_todos(bloques):
    socket.setdefaulttimeout(TIMEOUT)
    t0 = time.time()
    with ThreadPoolExecutor(HILOS) as ex:
        res = list(ex.map(probar, bloques))
    return res, time.time() - t0


def cargar_estado():
    try:
        req = urllib.request.Request(ESTADO_URL, headers={"User-Agent": "armar-listas"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return {}


def filtrar_muertos(bloques, hoy, salida):
    """Recibe los bloques ya filtrados por armar.py y devuelve los que quedan."""
    hoy = str(hoy)
    res, seg = probar_todos(bloques)
    muertos = {url_de(b) for b, r in zip(bloques, res) if r == "muerto"}
    rechazados = sum(r == "rechazado" for r in res)
    tasa = len(muertos) / max(len(bloques), 1)
    print(f"Prueba: {len(bloques)} canales en {seg/60:.1f} min | muertos {len(muertos)} "
          f"({tasa:.0%}) | rechazados {rechazados} (se dejan)")

    previo = cargar_estado()
    # "antes" = lo que fallo en la ultima corrida de un DIA anterior.
    # Si hoy ya corrio (ej. editaste cajas.csv), se reusa ese mismo "antes".
    if previo.get("fecha") == hoy:
        antes = set(previo.get("fallaron_antes", []))
    else:
        antes = set(previo.get("fallaron_hoy", []))

    estado = {"fecha": hoy, "fallaron_antes": sorted(antes), "freno": False}

    if tasa > FRENO:
        print(f"FRENO: {tasa:.0%} muerto supera {FRENO:.0%}. Probable falla de red del robot. "
              "Publico la lista SIN sacar nada.")
        estado.update(fallaron_hoy=[], freno=True)
        (salida / ESTADO_ARCHIVO).write_text(json.dumps(estado), encoding="utf-8")
        return bloques

    estado["fallaron_hoy"] = sorted(muertos)
    (salida / ESTADO_ARCHIVO).write_text(json.dumps(estado), encoding="utf-8")

    if not previo:
        print("Sin historial (primera corrida): solo mido, no saco nada.")
        return bloques

    sacar = muertos & antes
    protegidos = {url_de(b) for b in bloques if no_24_7(b) and url_de(b) in sacar}
    sacar -= protegidos
    quedan = [b for b in bloques if url_de(b) not in sacar]
    print(f"Sacados por fallar 2 dias seguidos: {len(sacar)} | "
          f"Not 24/7 caidos pero protegidos: {len(protegidos)} | quedan {len(quedan)}")
    return quedan


if __name__ == "__main__":
    # Modo medicion: python probar_canales.py lista.m3u
    from armar import leer_m3u
    with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
        _, bloques = leer_m3u(f.read())
    res, seg = probar_todos(bloques)
    m = [b for b, r in zip(bloques, res) if r == "muerto"]
    print(f"{len(bloques)} canales en {seg/60:.1f} min | muertos {len(m)} ({len(m)/len(bloques):.0%}) | "
          f"rechazados {res.count('rechazado')} | muertos Not 24/7 {sum(no_24_7(b) for b in m)}")
    with open("muertos.txt", "w", encoding="utf-8") as f:
        for b in m:
            f.write(b[0] + "\n" + url_de(b) + "\n")
    print("Detalle en muertos.txt")
