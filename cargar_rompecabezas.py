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


# ── Lógica de grilla ──────────────────────────────────────────────────────

def pieza_tipo(fila, col, filas, cols):
    bordes = sum([fila == 0, fila == filas - 1, col == 0, col == cols - 1])
    if bordes >= 2:
        return "Esquina"
    if bordes == 1:
        return "Borde"
    return "Interior"


def pieza_id(tipo, fila, col):
    return f"{tipo[0]}_{fila}_{col}"      # E_0_0 / B_0_1 / I_1_1


def build_grid(filas, cols):
    grid = {}
    for f in range(filas):
        for c in range(cols):
            tipo = pieza_tipo(f, c, filas, cols)
            grid[(f, c)] = {
                "pieza_id": pieza_id(tipo, f, c),
                "tipo": tipo,
                "fila": f,
                "columna": c,
                "activa": True,
            }
    return grid


def ascii_grid(grid, filas, cols):
    ICONS = {"Esquina": "ESQ", "Borde": "BRD", "Interior": "INT"}
    lines = []
    header = "     " + "  ".join(f"c{c:<2}" for c in range(cols))
    lines.append(header)
    for f in range(filas):
        row = f"f{f:<2} ["
        cells = []
        for c in range(cols):
            p = grid[(f, c)]
            icon = ICONS[p["tipo"]]
            marker = "!" if not p["activa"] else " "
            cells.append(f"{marker}{icon}")
        row += " | ".join(cells) + " ]"
        lines.append(row)
    lines.append("  ( ! = faltante )")
    return "\n".join(lines)


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


def ask_dimensions():
    while True:
        raw = input("Dimensiones (FilasxColumnas, ej. 3x3): ").strip().lower()
        try:
            f, c = raw.split("x")
            filas, cols = int(f), int(c)
            if filas >= 2 and cols >= 2:
                return filas, cols
            print("  Mínimo 2x2.")
        except (ValueError, AttributeError):
            print("  Formato inválido. Usa 'FilasxColumnas' (ej. 3x3, 20x20).")


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
    session.run(
        "CREATE INDEX pieza_posicion_idx IF NOT EXISTS FOR (p:Pieza) ON (p.fila, p.columna)"
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
    # Dynamic label (Pieza + subtipo)
    tipo = p["tipo"]
    session.run(
        f"""
        CREATE (n:Pieza:{tipo} {{
            pieza_id: $pid,
            fila:     $fila,
            columna:  $col,
            activa:   $activa
        }})
        """,
        pid=p["pieza_id"], fila=p["fila"], col=p["columna"], activa=p["activa"],
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


def crear_primer_paso(session, puzzle_id, esquina_ids):
    for eid in esquina_ids:
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

    # ── Metadatos del puzzle ──
    print("\n--- Datos del Rompecabezas ---")
    nombre     = ask_str("Nombre del rompecabezas")
    filas, cols = ask_dimensions()
    auto_id    = "puzzle_" + str(uuid.uuid4())[:8]
    puzzle_id  = ask_str("ID del puzzle", default=auto_id)
    imagen_url = ask_str("URL de imagen (opcional)", default="")

    total_piezas = filas * cols
    grid = build_grid(filas, cols)

    # Conteo por tipo
    tipos = {"Esquina": [], "Borde": [], "Interior": []}
    for p in grid.values():
        tipos[p["tipo"]].append(p["pieza_id"])
    esquinas = tipos["Esquina"]

    print(f"\n→ Grilla {filas}×{cols} = {total_piezas} piezas")
    print(f"   Esquinas: {len(esquinas)}  |  Bordes: {len(tipos['Borde'])}  |  Interior: {len(tipos['Interior'])}")
    print()
    print(ascii_grid(grid, filas, cols))

    # ── Piezas faltantes ──
    print("\n¿Hay piezas faltantes? Ingresa los IDs separados por comas")
    print("(ej. E_0_0, B_0_1) o presiona Enter si no hay ninguna:")
    raw_missing = input("  Faltantes: ").strip()

    if raw_missing:
        valid_ids = {p["pieza_id"] for p in grid.values()}
        missing_ids = {pid.strip() for pid in raw_missing.split(",")}
        invalid = missing_ids - valid_ids
        if invalid:
            print(f"  Advertencia — IDs no reconocidos: {', '.join(sorted(invalid))}")
        for p in grid.values():
            if p["pieza_id"] in missing_ids:
                p["activa"] = False

    activas   = sum(1 for p in grid.values() if p["activa"])
    faltantes = total_piezas - activas

    # Relaciones a crear: derecha (ESTE) y abajo (SUR) por cada celda
    n_pares = sum(
        (1 if c + 1 < cols else 0) + (1 if f + 1 < filas else 0)
        for f in range(filas)
        for c in range(cols)
    )

    # ── Resumen ──
    print("\n" + "=" * 55)
    print("                   RESUMEN")
    print("=" * 55)
    print(f"  Puzzle       : {nombre} ({puzzle_id})")
    print(f"  Dimensiones  : {filas}×{cols}  ({total_piezas} piezas)")
    print(f"  Activas      : {activas}/{total_piezas}")
    if faltantes:
        faltantes_ids = [p["pieza_id"] for p in grid.values() if not p["activa"]]
        print(f"  Faltantes    : {faltantes} → {', '.join(faltantes_ids)}")
    print(f"  Relaciones   : {n_pares * 2} CONECTA (bidireccionales)")
    print(f"  Inicio armado: {', '.join(esquinas)}  (PRIMER_PASO)")
    print()
    print(ascii_grid(grid, filas, cols))
    print()

    if not ask_yes_no("¿Confirmar y cargar en Neo4j?", default_yes=False):
        print("Carga cancelada.")
        return

    # ── Conexión ──
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
        crear_puzzle(session, puzzle_id, nombre, total_piezas, f"{filas}x{cols}", imagen_url)

        print(f"Creando {total_piezas} nodos :Pieza...")
        for p in grid.values():
            crear_pieza(session, p)

        print(f"Creando {n_pares * 2} relaciones :CONECTA...")
        for f in range(filas):
            for c in range(cols):
                pid = grid[(f, c)]["pieza_id"]
                if c + 1 < cols:
                    crear_conecta(session, pid, grid[(f, c + 1)]["pieza_id"], "ESTE")
                if f + 1 < filas:
                    crear_conecta(session, pid, grid[(f + 1, c)]["pieza_id"], "SUR")

        print(f"Creando {len(esquinas)} relaciones :PRIMER_PASO...")
        crear_primer_paso(session, puzzle_id, esquinas)

    driver.close()
    print(f"\n✓ '{nombre}' cargado en Neo4j Aura.")
    print(f"  {total_piezas} piezas  |  {n_pares * 2} relaciones CONECTA  |  {len(esquinas)} puntos de inicio\n")


if __name__ == "__main__":
    main()
