import os
import sys
import uuid
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

URI      = os.getenv("NEO4J_URI")
USER     = os.getenv("NEO4J_USERNAME", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD")
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

OPPOSITE = {"NORTE": "SUR", "SUR": "NORTE", "ESTE": "OESTE", "OESTE": "ESTE"}
DIRS     = {"NORTE", "SUR", "ESTE", "OESTE"}


# ── Entrada del usuario ───────────────────────────────────────────────────

def ask_yes_no(prompt, default_yes=True):
    hint = "[S/n]" if default_yes else "[s/N]"
    while True:
        raw = input(f"{prompt} {hint}: ").strip().lower()
        if raw == "":
            return default_yes
        if raw in ("s", "si", "sí", "y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Responde 's' o 'n'.")


def ask_str(prompt, default=""):
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val if val else default


def ask_int_positivo(prompt, minimo=1):
    while True:
        raw = input(f"{prompt}: ").strip()
        try:
            val = int(raw)
            if val >= minimo:
                return val
            print(f"  Debe ser al menos {minimo}.")
        except ValueError:
            print("  Ingresa un número entero válido.")


def ask_direccion(from_id, to_id):
    while True:
        raw = input(f"    Dirección desde {from_id} hacia {to_id} [NORTE/SUR/ESTE/OESTE]: ").strip().upper()
        if raw in DIRS:
            return raw
        print("  Dirección inválida. Usa NORTE, SUR, ESTE u OESTE.")


def ask_destino(n_total, n_actual):
    while True:
        raw = input(f"    Número de pieza destino (1-{n_total}, distinta de {n_actual}): ").strip()
        try:
            dest = int(raw)
            if dest == n_actual:
                print("  Una pieza no puede conectar consigo misma.")
            elif 1 <= dest <= n_total:
                return dest
            else:
                print(f"  Debe ser entre 1 y {n_total}.")
        except ValueError:
            print("  Ingresa un número entero.")


# ── Recolección de piezas y conexiones ───────────────────────────────────

def recopilar_piezas(total):
    """
    Recolecta datos de cada pieza y sus conexiones.
    Retorna (piezas_dict, conexiones_list).
      piezas_dict  : {n: {pieza_id, descripcion, activa}}
      conexiones_list: [(pid_a, pid_b, dir_ab), ...]  — ya deduplicadas
    """
    piezas      = {}
    conexiones  = []
    pares_vistos = set()  # frozenset({n_a, n_b}) — evita duplicar aristas

    for n in range(1, total + 1):
        print(f"\n--- Pieza {n} de {total} ---")
        desc    = ask_str("  Descripción (opcional)", default="")
        activa  = ask_yes_no("  ¿Activa?", default_yes=True)
        pid     = f"P_{n}"
        piezas[n] = {"pieza_id": pid, "descripcion": desc, "activa": activa}

        if total == 1:
            continue  # con una sola pieza no puede haber conexiones

        print(f"\n  Conexiones de Pieza {n} ({pid}):")
        while ask_yes_no("  ¿Conecta con otra pieza?", default_yes=False):
            destino = ask_destino(total, n)
            par     = frozenset({n, destino})

            if par in pares_vistos:
                pid_dest = f"P_{destino}"
                print(f"    (!) Par {pid} ↔ {pid_dest} ya registrado — se omite.")
                continue

            pid_dest = f"P_{destino}"
            dir_ab   = ask_direccion(pid, pid_dest)
            dir_ba   = OPPOSITE[dir_ab]
            print(f"    ↳ auto-inversa: {pid_dest} -[{dir_ba}]-> {pid}")

            conexiones.append((pid, pid_dest, dir_ab))
            pares_vistos.add(par)

    return piezas, conexiones


# ── Operaciones Neo4j ─────────────────────────────────────────────────────

def limpiar_db(session):
    session.run("MATCH (n) DETACH DELETE n")


def crear_constraints(session):
    session.run(
        "CREATE CONSTRAINT puzzle_id_unique IF NOT EXISTS "
        "FOR (pz:Puzzle) REQUIRE pz.puzzle_id IS UNIQUE"
    )
    session.run(
        "CREATE CONSTRAINT pieza_id_unique IF NOT EXISTS "
        "FOR (p:Pieza) REQUIRE p.pieza_id IS UNIQUE"
    )


def crear_indexes(session):
    session.run(
        "CREATE INDEX pieza_activa_idx IF NOT EXISTS FOR (p:Pieza) ON (p.activa)"
    )


def crear_puzzle(session, puzzle_id, nombre, total_piezas, dimensiones, imagen_url):
    session.run(
        """
        CREATE (:Puzzle {
            puzzle_id:    $pid,
            nombre:       $nombre,
            total_piezas: $total,
            dimensiones:  $dim,
            imagen_url:   $img
        })
        """,
        pid=puzzle_id, nombre=nombre, total=total_piezas, dim=dimensiones, img=imagen_url,
    )


def crear_pieza(session, p):
    session.run(
        """
        CREATE (n:Pieza {
            pieza_id:    $pid,
            descripcion: $desc,
            activa:      $activa
        })
        """,
        pid=p["pieza_id"], desc=p["descripcion"], activa=p["activa"],
    )


def crear_conecta(session, pid_a, pid_b, dir_ab):
    dir_ba = OPPOSITE[dir_ab]
    session.run(
        """
        MATCH (a:Pieza {pieza_id: $a}), (b:Pieza {pieza_id: $b})
        CREATE (a)-[:CONECTA {direccion: $dab, compatible: true, fuerza_encaje: 1.0}]->(b)
        CREATE (b)-[:CONECTA {direccion: $dba, compatible: true, fuerza_encaje: 1.0}]->(a)
        """,
        a=pid_a, b=pid_b, dab=dir_ab, dba=dir_ba,
    )


def crear_primer_paso(session, puzzle_id, inicio_ids):
    for eid in inicio_ids:
        session.run(
            """
            MATCH (pz:Puzzle {puzzle_id: $pid}), (e:Pieza {pieza_id: $eid})
            CREATE (pz)-[:PRIMER_PASO]->(e)
            """,
            pid=puzzle_id, eid=eid,
        )


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("      CARGADOR DE ROMPECABEZAS — Neo4j Aura")
    print("=" * 55)

    if not all([URI, USER, PASSWORD]):
        print("\nError: faltan credenciales en .env (NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD).")
        sys.exit(1)

    print()
    if not ask_yes_no(
        "ADVERTENCIA: se eliminarán TODOS los nodos existentes.\n¿Continuar?",
        default_yes=False,
    ):
        print("Operación cancelada.")
        return

    # ── Metadatos ──
    print("\n--- Datos del Rompecabezas ---")
    nombre       = ask_str("Nombre del rompecabezas")
    total_piezas = ask_int_positivo("Total de piezas")
    auto_id      = "puzzle_" + str(uuid.uuid4())[:8]
    puzzle_id    = ask_str("ID del puzzle", default=auto_id)
    imagen_url   = ask_str("URL de imagen (opcional)", default="")

    # ── Captura pieza por pieza ──
    piezas, conexiones = recopilar_piezas(total_piezas)

    # ── Elegir pieza de inicio (PRIMER_PASO) ──
    primera_activa = next(
        (piezas[n]["pieza_id"] for n in sorted(piezas.keys()) if piezas[n]["activa"]),
        None,
    )
    inicio_ids = []
    if primera_activa:
        print(f"\n¿Desde qué pieza desea iniciar el armado? (1-{total_piezas}, Enter = primera activa)")
        raw_inicio = input("  Número de pieza: ").strip()
        if raw_inicio:
            try:
                n_inicio = int(raw_inicio)
                if 1 <= n_inicio <= total_piezas:
                    if piezas[n_inicio]["activa"]:
                        inicio_ids = [piezas[n_inicio]["pieza_id"]]
                    else:
                        print(f"  La pieza {n_inicio} está inactiva. Se usará la primera activa ({primera_activa}).")
                        inicio_ids = [primera_activa]
                else:
                    print(f"  Número fuera de rango. Se usará la primera activa ({primera_activa}).")
                    inicio_ids = [primera_activa]
            except ValueError:
                print(f"  Entrada inválida. Se usará la primera activa ({primera_activa}).")
                inicio_ids = [primera_activa]
        else:
            inicio_ids = [primera_activa]

    activas   = sum(1 for p in piezas.values() if p["activa"])
    faltantes = total_piezas - activas

    # ── Resumen ──
    print("\n" + "=" * 55)
    print("                   RESUMEN")
    print("=" * 55)
    print(f"  Puzzle       : {nombre} ({puzzle_id})")
    print(f"  Total piezas : {total_piezas}")
    print(f"  Activas      : {activas}/{total_piezas}")
    if faltantes:
        ids_faltantes = [p["pieza_id"] for p in piezas.values() if not p["activa"]]
        print(f"  Faltantes    : {faltantes} → {', '.join(ids_faltantes)}")
    print(f"  Relaciones   : {len(conexiones) * 2} CONECTA ({len(conexiones)} pares bidireccionales)")
    if inicio_ids:
        print(f"  Inicio armado: {', '.join(inicio_ids)}  (PRIMER_PASO)")
    else:
        print(f"  Inicio armado: ninguno (todas las piezas inactivas)")

    if conexiones:
        print("\n  Conexiones declaradas:")
        for pid_a, pid_b, dir_ab in conexiones:
            print(f"    {pid_a} -[{dir_ab}]-> {pid_b}  |  {pid_b} -[{OPPOSITE[dir_ab]}]-> {pid_a}")

    print()
    if not ask_yes_no("¿Confirmar y cargar en Neo4j?", default_yes=False):
        print("Carga cancelada.")
        return

    # ── Conexión y carga ──
    print("\nConectando a Neo4j Aura...")
    try:
        driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
        driver.verify_connectivity()
        print("Conexión exitosa.\n")
    except Exception as e:
        print(f"Error de conexión: {e}")
        sys.exit(1)

    with driver.session(database=DATABASE) as session:
        print("Eliminando nodos existentes...")
        limpiar_db(session)

        print("Creando constraints e índices...")
        crear_constraints(session)
        crear_indexes(session)

        print(f"Creando nodo :Puzzle '{nombre}'...")
        crear_puzzle(
            session, puzzle_id, nombre, total_piezas,
            f"{total_piezas} piezas asimétrico", imagen_url,
        )

        print(f"Creando {total_piezas} nodos :Pieza...")
        for p in piezas.values():
            crear_pieza(session, p)

        if conexiones:
            print(f"Creando {len(conexiones) * 2} relaciones :CONECTA...")
            for pid_a, pid_b, dir_ab in conexiones:
                crear_conecta(session, pid_a, pid_b, dir_ab)

        if inicio_ids:
            print(f"Creando {len(inicio_ids)} relación(es) :PRIMER_PASO...")
            crear_primer_paso(session, puzzle_id, inicio_ids)

    driver.close()
    print(f"\n✓ '{nombre}' cargado en Neo4j Aura.")
    print(f"  {total_piezas} piezas  |  {len(conexiones) * 2} relaciones CONECTA  |  {len(inicio_ids)} punto(s) de inicio\n")


if __name__ == "__main__":
    main()
