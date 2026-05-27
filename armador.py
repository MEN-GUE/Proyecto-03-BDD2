from collections import deque

class ArmadorLogico:
    def __init__(self, session):
        """
        Recibe una sesión activa de Neo4j (ej. generada por 'with driver.session() as session:')
        """
        self.session = session

    def obtener_puzzles(self):
        """Devuelve una lista con los IDs de todos los rompecabezas en la base de datos."""
        query = "MATCH (pz:Puzzle) RETURN pz.puzzle_id AS pid"
        resultado = self.session.run(query)
        return [record["pid"] for record in resultado]

    def obtener_inicio(self, puzzle_id):
        """Encuentra una pieza inicial válida (Esquina) que esté activa."""
        query = """
        MATCH (pz:Puzzle {puzzle_id: $pid})-[:PRIMER_PASO]->(inicio:Pieza)
        WHERE inicio.activa = true
        RETURN inicio.pieza_id AS pieza_id LIMIT 1
        """
        resultado = self.session.run(query, pid=puzzle_id).single()
        return resultado["pieza_id"] if resultado else None

    def ensamblar(self, puzzle_id):
        """
        Algoritmo BFS que recorre e imprime los pasos de ensamblaje del rompecabezas.
        Identifica piezas faltantes para cumplir con el ensamblaje parcial.
        """
        pieza_inicial = self.obtener_inicio(puzzle_id)
        if not pieza_inicial:
            print(f"No se pudo iniciar el rompecabezas {puzzle_id}. No hay esquinas activas.")
            return

        print(f"\nIniciando ensamblaje del rompecabezas [{puzzle_id}]")
        print(f"Pieza inicial: {pieza_inicial}\n")
        
        cola = deque([pieza_inicial])
        visitados = set([pieza_inicial])
        paso = 1

        while cola:
            actual = cola.popleft()
            
            # Consultamos los vecinos de la pieza actual basados en la relación CONECTA
            query_vecinos = """
            MATCH (p:Pieza {pieza_id: $pid})-[r:CONECTA]->(vecino:Pieza)
            RETURN r.direccion AS direccion, vecino.pieza_id AS vecino_id, vecino.activa AS activa
            """
            vecinos = self.session.run(query_vecinos, pid=actual)
            
            print(f"Paso {paso:03d} | Evaluando pieza: {actual}")
            tiene_conexiones = False

            for v in vecinos:
                tiene_conexiones = True
                direccion = v["direccion"]
                vecino_id = v["vecino_id"]
                activa = v["activa"]

                # Lógica de ensamblaje y validación de estado
                if not activa:
                    print(f"  ➜ {direccion:<5}: Falta la pieza {vecino_id} (Ensamblaje parcial)")
                
                elif vecino_id not in visitados:
                    print(f"  ➜ {direccion:<5}: Ensamblar con {vecino_id}")
                    visitados.add(vecino_id)
                    cola.append(vecino_id)
                
                else:
                    print(f"  ➜ {direccion:<5}: Conecta con {vecino_id} (Ya colocada)")
            
            if not tiene_conexiones:
                print("  ➜ Sin conexiones adicionales (Pieza aislada).")
                
            print("-" * 50)
            paso += 1

        print(f"Proceso terminado. Total de piezas ensambladas: {len(visitados)}")

    def ensamblar_todos(self):
        """Orquesta el ensamblaje de todos los rompecabezas disponibles en la BD."""
        puzzles = self.obtener_puzzles()
        if not puzzles:
            print("No hay rompecabezas registrados.")
            return
            
        for pid in puzzles:
            self.ensamblar(pid)