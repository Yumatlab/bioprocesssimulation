import sqlite3
import pandas as pd

def sql_append(table_name, data_table, database_name):
    """
    Hängt Daten an eine bestehende Tabelle in einer SQLite-Datenbank an.
    
    :param table_name: Der Name der Tabelle in der Datenbank.
    :param data_table: Der pandas DataFrame mit den anzuhängenden Daten.
    :param database_name: Der Name der SQLite-Datenbank.
    """
    
    # Verbindung zur Datenbank herstellen
    conn = sqlite3.connect(database_name)
    
    try:
        # Daten an die bestehende Tabelle anhängen
        data_table.to_sql(table_name, conn, if_exists='append', index=False)
        
    
    except Exception as e:
        print(f"Fehler beim Anhängen der Daten an die Tabelle: {e}")
    
    finally:
        conn.close()

# Die Funktion wird nicht direkt hier aufgerufen, 
# da sie von MATLAB aus verwendet werden soll.