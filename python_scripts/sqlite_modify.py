import sqlite3

def execute_sql_modify(database_path, query):
    """
    Führt eine oder mehrere SQL-Modifikationsabfragen (INSERT, UPDATE, DELETE) auf einer SQLite-Datenbank aus.

    Parameters:
    database_path (str): Der Pfad zur SQLite-Datenbankdatei.
    query (str or list): Ein einzelner SQL-Befehl als String oder eine Liste von SQL-Befehlen.

    Returns:
    int: Die Anzahl der betroffenen Zeilen.
    """
    conn = sqlite3.connect(database_path)
    cursor = conn.cursor()
    affected_rows = 0

    try:
        if isinstance(query, str):
            queries = [query]
        elif isinstance(query, list):
            queries = query
        else:
            raise ValueError("Query must be a string or a list of strings.")

        for q in queries:
            cursor.execute(q)
            affected_rows += cursor.rowcount

        conn.commit()
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
    finally:
        conn.close()

    return affected_rows