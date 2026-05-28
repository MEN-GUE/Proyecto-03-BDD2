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

    def obtener_puzzles(self):
        result = self.session.run(
            """
            MATCH (pz:Puzzle)
            RETURN pz.puzzle_id AS pid,
                   pz.nombre AS nombre,
                   pz.dimensiones AS dim,
                   pz.total_piezas AS total
            """
        )
        return [dict(r) for r in result]

    def pieza_existe(self, puzzle_id, pieza_id):
        r = self.session.run(
            """
            MATCH (p:Pieza {pieza_id: $pid})
            RETURN p.pieza_id AS pieza_id, p.activa AS activa
            LIMIT 1
            """,
            pid=pieza_id,
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

    def obtener_piezas_activas(self):
        result = self.session.run(
            """
            MATCH (p:Pieza)
            WHERE p.activa = true
            RETURN p.pieza_id AS pieza_id
            ORDER BY p.pieza_id
            """
        )
        return [r["pieza_id"] for r in result]

    def marcar_faltantes(self, piezas_faltantes):
        marcadas, no_encontradas = [], []

        for pieza_id in piezas_faltantes:
            r = self.session.run(
                """
                MATCH (p:Pieza {pieza_id: $pid})
                SET p.activa = false
                RETURN p.pieza_id AS id
                """,
                pid=pieza_id,
            ).single()

            if r:
                marcadas.append(pieza_id)
            else:
                no_encontradas.append(pieza_id)

        return marcadas, no_encontradas

    def obtener_vecinos(self, pieza_id):
        result = self.session.run(
            """
            MATCH (p:Pieza {pieza_id: $pid})-[r:CONECTA]->(v:Pieza)
            RETURN r.direccion AS dir,
                   v.pieza_id AS vid,
                   v.activa AS activa
            ORDER BY r.direccion
            """,
            pid=pieza_id,
        )
        return list(result)

    def ensamblar_por_partes(self, puzzle_id, pieza_inicio=None):
        piezas_activas = self.obtener_piezas_activas()
        total = self.contar_piezas(puzzle_id)

        if pieza_inicio:
            info = self.pieza_existe(puzzle_id, pieza_inicio)

            if not info:
                print(f"\nError: la pieza '{pieza_inicio}' no existe en el rompecabezas.")
                return

            if not info["activa"]:
                print(f"\nAdvertencia: la pieza '{pieza_inicio}' está marcada como faltante.")
                print("Elige una pieza activa para comenzar.")
                return

            piezas_activas = [pieza_inicio] + [
                p for p in piezas_activas if p != pieza_inicio
            ]

        visitados_global = set()
        faltantes_global = set()
        parte = 1

        print(f"\n{'=' * 55}")
        print(f"  Rompecabezas : {puzzle_id}")
        print(f"  Modo         : Armado por partes separadas")
        if pieza_inicio:
            print(f"  Inicio       : {pieza_inicio}")
        print(f"{'=' * 55}")

        for inicio in piezas_activas:
            if inicio in visitados_global:
                continue

            print(f"\nParte {parte} | Pieza inicial: {inicio}")
            print("-" * 55)

            cola = deque([inicio])
            visitados_global.add(inicio)
            piezas_parte = {inicio}
            paso = 1

            while cola:
                actual = cola.popleft()
                vecinos = self.obtener_vecinos(actual)

                print(f"Paso {paso:03d} | Pieza actual: {actual}")

                for v in vecinos:
                    dir_, vid, activa = v["dir"], v["vid"], v["activa"]

                    if not activa:
                        if vid not in faltantes_global:
                            print(f"  ➜ {dir_:<5}: [ESPACIO VACÍO] — pieza '{vid}' faltante")
                            faltantes_global.add(vid)
                        else:
                            print(f"  ➜ {dir_:<5}: [ESPACIO VACÍO] — pieza '{vid}' faltante, ya indicada")

                    elif vid not in visitados_global:
                        print(f"  ➜ {dir_:<5}: Ensamblar '{vid}'")
                        visitados_global.add(vid)
                        piezas_parte.add(vid)
                        cola.append(vid)

                    else:
                        print(f"  ➜ {dir_:<5}: '{vid}' ya colocada")

                paso += 1

            print(f"\nParte {parte} terminada con {len(piezas_parte)} pieza(s):")
            print(f"  {', '.join(sorted(piezas_parte))}")
            print("=" * 55)

            parte += 1

        ensambladas = len(visitados_global)
        faltantes = len(faltantes_global)
        cantidad_partes = parte - 1

        print("\nResultado final:")
        print(f"  Piezas ensambladas : {ensambladas} / {total}")

        if faltantes:
            print(f"  Piezas faltantes   : {faltantes} → {', '.join(sorted(faltantes_global))}")

        if ensambladas + faltantes < total:
            print(f"  Piezas no alcanzadas: {total - ensambladas - faltantes}")
            print("  Estado              : Rompecabezas INCOMPLETO")
        elif faltantes:
            print(f"  Estado              : Rompecabezas PARCIALMENTE armado en {cantidad_partes} parte(s)")
        elif cantidad_partes == 1:
            print("  Estado              : Rompecabezas COMPLETO ✓")
        else:
            print(f"  Estado              : Rompecabezas COMPLETO en {cantidad_partes} partes separadas ✓")

        print()

    def ensamblar_todos(self):
        for pz in self.obtener_puzzles():
            self.ensamblar_por_partes(pz["pid"])


def preguntar_piezas_faltantes(armador, puzzle_id):
    print(f"\n¿Hay piezas faltantes en el rompecabezas '{puzzle_id}'? (s/n): ", end="")
    resp = input().strip().lower()

    if resp != "s":
        return

    print("Ingresa los IDs de las piezas faltantes separados por coma")
    print("  Ejemplo: P_1, P_5, P_12")
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
        print(f"\n  {len(marcadas)} pieza(s) faltante(s) registradas.")


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

        print("\n¿Desde qué pieza iniciar?")
        print("  Enter  → armar todo el rompecabezas por partes")
        print("  ID     → armar primero desde esa pieza y luego las demás partes")
        raw = input("  ID de pieza: ").strip()

        armador.ensamblar_por_partes(
            puzzle_id,
            pieza_inicio=raw if raw else None
        )

    driver.close()


if __name__ == "__main__":
    main()