# sqlite_query.py
import sqlite3
import pandas as pd

def execute_sql_query(database_path, query):
    """
    Führt eine SQL-Abfrage auf einer SQLite-Datenbank aus.
    Parameters:
    database_path (str): Der Pfad zur SQLite-Datenbankdatei.
    query (str): Die SQL-Abfrage, die ausgeführt werden soll.
    Returns:
    pandas.DataFrame: Ein DataFrame mit den Ergebnissen der Abfrage.
    """
    
    # Erstellen der URI für den schreibgeschützten Modus
    uri = f"file:{database_path}?mode=ro"
    
    try:
        # Verbindung zur Datenbank im schreibgeschützten Modus herstellen
        conn = sqlite3.connect(uri, uri=True)
        cursor = conn.cursor()
        # Abfrage ausführen und Ergebnisse holen
        cursor.execute(query)
        # Spaltennamen aus der Abfrage erhalten
        column_names = [description[0] for description in cursor.description]
    
        data = cursor.fetchall()
    
        # Daten in einen pandas DataFrame umwandeln
        results = pd.DataFrame(data, columns=column_names)
    
        # None-Werte durch leere Strings ersetzen
        results = results.fillna("")
    
        return results
    
    except sqlite3.OperationalError as e:
        print(f"Fehler beim Öffnen der Datenbank: {e}")
        return None
    except pd.io.sql.DatabaseError as e:
        print(f"Fehler bei der Datenbankabfrage: {e}")
        return None
    except Exception as e:
        print(f"Ein unerwarteter Fehler ist aufgetreten: {e}")
        return None
    finally:
        if 'conn' in locals():
            conn.close()