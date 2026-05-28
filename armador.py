import os
import sys
from collections import deque
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

URI      = os.getenv("NEO4J_URI")
USER     = os.getenv("NEO4J_USERNAME", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD")
DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")


class ArmadorLogico:
    def __init__(self, session):
        self.session = session

    # ── Consultas de apoyo ────────────────────────────────────────────────

    def obtener_puzzles(self):
        result = self.session.run(
            "MATCH (pz:Puzzle) RETURN pz.puzzle_id AS pid, pz.nombre AS nombre, "
            "pz.dimensiones AS dim, pz.total_piezas AS total"
        )
        return [dict(r) for r in result]

    def obtener_inicio_default(self, puzzle_id):
        """Primera esquina activa del puzzle (via PRIMER_PASO)."""
        r = self.session.run(
            """
            MATCH (pz:Puzzle {puzzle_id: $pid})-[:PRIMER_PASO]->(e:Pieza)
            WHERE e.activa = true
            RETURN e.pieza_id AS pieza_id LIMIT 1
            """,
            pid=puzzle_id,
        ).single()
        return r["pieza_id"] if r else None

    def pieza_existe(self, puzzle_id, pieza_id):
        """Valida que una pieza pertenezca al puzzle dado."""
        r = self.session.run(
            """
            MATCH (pz:Puzzle {puzzle_id: $pid})-[:PRIMER_PASO|CONECTA*0..]->(p:Pieza {pieza_id: $pid2})
            RETURN p.pieza_id AS pieza_id, p.activa AS activa LIMIT 1
            """,
            pid=puzzle_id, pid2=pieza_id,
        ).single()
        # Fallback: buscar la pieza directamente (no depende de que sea alcanzable)
        if not r:
            r = self.session.run(
                "MATCH (p:Pieza {pieza_id: $pid2}) RETURN p.pieza_id AS pieza_id, p.activa AS activa LIMIT 1",
                pid2=pieza_id,
            ).single()
        return dict(r) if r else None

    def contar_piezas(self, puzzle_id):
        r = self.session.run(
            """
            MATCH (pz:Puzzle {puzzle_id: $pid})
            RETURN pz.total_piezas AS total
            """,
            pid=puzzle_id,
        ).single()
        return r["total"] if r else 0

    def marcar_faltantes(self, piezas_faltantes):
        """Registra piezas como faltantes (activa=false) en Neo4j."""
        marcadas, no_encontradas = [], []
        for pieza_id in piezas_faltantes:
            r = self.session.run(
                "MATCH (p:Pieza {pieza_id: $pid}) SET p.activa = false RETURN p.pieza_id AS id",
                pid=pieza_id,
            ).single()
            if r:
                marcadas.append(pieza_id)
            else:
                no_encontradas.append(pieza_id)
        return marcadas, no_encontradas

    # ── Algoritmo principal ───────────────────────────────────────────────

    def ensamblar(self, puzzle_id, pieza_id_inicio=None):
        """
        BFS desde pieza_id_inicio (o desde la primera esquina activa si no se indica).
        Imprime cada paso: qué pieza sigue y con qué piezas se ensambla.
        Maneja piezas faltantes (activa=false) indicando ensamblaje parcial.
        """
        if pieza_id_inicio:
            info = self.pieza_existe(puzzle_id, pieza_id_inicio)
            if not info:
                print(f"\nError: la pieza '{pieza_id_inicio}' no existe en el rompecabezas.")
                return
            if not info["activa"]:
                print(f"\nAdvertencia: la pieza '{pieza_id_inicio}' está marcada como faltante.")
                print("Elige una pieza activa para comenzar.")
                return
            inicio = pieza_id_inicio
        else:
            inicio = self.obtener_inicio_default(puzzle_id)
            if not inicio:
                print(f"\nNo hay esquinas activas en '{puzzle_id}'. Carga el rompecabezas primero.")
                return

        total = self.contar_piezas(puzzle_id)

        print(f"\n{'='*55}")
        print(f"  Rompecabezas : {puzzle_id}")
        print(f"  Pieza inicial: {inicio}")
        print(f"{'='*55}\n")

        cola        = deque([inicio])
        visitados   = {inicio}
        faltantes_vistos = set()   # evita reportar la misma pieza faltante más de una vez
        paso        = 1

        while cola:
            actual = cola.popleft()

            vecinos = self.session.run(
                """
                MATCH (p:Pieza {pieza_id: $pid})-[r:CONECTA]->(v:Pieza)
                RETURN r.direccion AS dir, v.pieza_id AS vid, v.activa AS activa
                ORDER BY r.direccion
                """,
                pid=actual,
            )

            print(f"Paso {paso:03d} | Pieza actual: {actual}")

            for v in vecinos:
                dir_, vid, activa = v["dir"], v["vid"], v["activa"]

                if not activa:
                    if vid not in faltantes_vistos:
                        print(f"  ➜ {dir_:<5}: [ESPACIO VACÍO] — pieza '{vid}' faltante, dejar el espacio libre")
                        faltantes_vistos.add(vid)
                    else:
                        print(f"  ➜ {dir_:<5}: [ESPACIO VACÍO] — pieza '{vid}' faltante (ya indicada anteriormente)")
                elif vid not in visitados:
                    print(f"  ➜ {dir_:<5}: Ensamblar '{vid}'")
                    visitados.add(vid)
                    cola.append(vid)
                else:
                    print(f"  ➜ {dir_:<5}: '{vid}' ya colocada")

            print("-" * 55)
            paso += 1

        ensambladas = len(visitados)
        faltantes   = len(faltantes_vistos)
        print(f"\nResultado:")
        print(f"  Piezas ensambladas : {ensambladas} / {total}")
        if faltantes:
            print(f"  Piezas faltantes   : {faltantes} → {', '.join(sorted(faltantes_vistos))}")
            print(f"  Estado             : Rompecabezas PARCIALMENTE armado")
        else:
            print(f"  Estado             : Rompecabezas COMPLETO ✓")
        print()

    def ensamblar_todos(self):
        for pz in self.obtener_puzzles():
            self.ensamblar(pz["pid"])


# ── Entrada de usuario ────────────────────────────────────────────────────

def preguntar_piezas_faltantes(armador, puzzle_id):
    """Pregunta al usuario si hay piezas faltantes y las registra en la BD."""
    print(f"\n¿Hay piezas faltantes en el rompecabezas '{puzzle_id}'? (s/n): ", end="")
    resp = input().strip().lower()
    if resp != "s":
        return

    print("Ingresa los IDs de las piezas faltantes separados por coma")
    print("  Formato de IDs: P_N  (ejemplo: P_1, P_5, P_12)")
    print("  Ejemplo: E_0_0, B_0_1, I_1_1")
    raw = input("  IDs: ").strip()
    if not raw:
        print("  No se ingresaron piezas.")
        return

    piezas = [p.strip() for p in raw.split(",") if p.strip()]
    if not piezas:
        return

    print("\nRegistrando piezas faltantes en la base de datos...")
    marcadas, no_encontradas = armador.marcar_faltantes(piezas)
    for pid in marcadas:
        print(f"  ✓ Pieza '{pid}' registrada como faltante.")
    for pid in no_encontradas:
        print(f"  ✗ Pieza '{pid}' no encontrada — se omite.")
    if marcadas:
        print(f"\n  {len(marcadas)} pieza(s) faltante(s) registradas. El algoritmo dejará esos espacios vacíos.")


def elegir_puzzle(puzzles):
    print("\nPuzzles disponibles:")
    for i, pz in enumerate(puzzles, 1):
        print(f"  {i}. [{pz['pid']}]  {pz['nombre']}  ({pz['dim']}, {pz['total']} piezas)")
    while True:
        raw = input("\nSelecciona un puzzle (número): ").strip()
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(puzzles):
                return puzzles[idx]["pid"]
        except ValueError:
            pass
        print("  Número inválido.")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print("      ARMADOR DE ROMPECABEZAS — Neo4j Aura")
    print("=" * 55)

    if not all([URI, USER, PASSWORD]):
        print("\nError: faltan credenciales en .env.")
        sys.exit(1)

    print("\nConectando a Neo4j Aura...")
    try:
        driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
        driver.verify_connectivity()
        print("Conexión exitosa.")
    except Exception as e:
        print(f"Error de conexión: {e}")
        sys.exit(1)

    with driver.session(database=DATABASE) as session:
        armador = ArmadorLogico(session)
        puzzles = armador.obtener_puzzles()

        if not puzzles:
            print("\nNo hay rompecabezas en la base de datos.")
            print("Carga uno primero con: python3 cargar_rompecabezas.py")
            driver.close()
            return

        puzzle_id = elegir_puzzle(puzzles)

        preguntar_piezas_faltantes(armador, puzzle_id)

        print(f"\n¿Desde qué pieza iniciar? (Enter para usar esquina por defecto)")
        raw = input("  ID de pieza: ").strip()
        pieza_inicio = raw if raw else None

        armador.ensamblar(puzzle_id, pieza_inicio)

    driver.close()


if __name__ == "__main__":
    main()
