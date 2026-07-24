import sqlite3
import os

# =====================================================
# Database Configuration
# =====================================================

DATABASE_NAME = "mama_ai.db"

DATABASE_PATH = os.path.join(
    os.path.dirname(__file__),
    DATABASE_NAME
)


# =====================================================
# Connection
# =====================================================

def get_connection():

    conn = sqlite3.connect(DATABASE_PATH)

    conn.row_factory = sqlite3.Row

    return conn


# =====================================================
# Initialize Database
# =====================================================

def initialize_database():

    conn = get_connection()

    cursor = conn.cursor()

    # -----------------------------
    # Experiences
    # -----------------------------

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS experiences (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        task TEXT,

        action TEXT,

        result TEXT,

        success INTEGER DEFAULT 0,

        reward INTEGER DEFAULT 0,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # -----------------------------
    # Skills
    # -----------------------------

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS skills (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        name TEXT UNIQUE,

        uses INTEGER DEFAULT 1,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # -----------------------------
    # Goals
    # -----------------------------

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS goals (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        goal TEXT,

        completed INTEGER DEFAULT 0,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # -----------------------------
    # Memory
    # -----------------------------

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS memory (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        owner_id TEXT NOT NULL DEFAULT 'local-user',

        title TEXT,

        content TEXT,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    memory_columns = {
        row["name"]
        for row in cursor.execute(
            "PRAGMA table_info(memory)"
        ).fetchall()
    }

    if "owner_id" not in memory_columns:
        cursor.execute("""
        ALTER TABLE memory
        ADD COLUMN owner_id TEXT NOT NULL
        DEFAULT 'local-user'
        """)

    cursor.execute("""
    UPDATE memory
    SET owner_id = 'local-user'
    WHERE owner_id IS NULL
       OR TRIM(owner_id) = ''
    """)

    cursor.execute("""
    CREATE INDEX IF NOT EXISTS
        idx_memory_owner_created
    ON memory(owner_id, id DESC)
    """)

    # -----------------------------
    # Learning
    # -----------------------------

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS learning (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        task TEXT UNIQUE,

        solution TEXT,

        confidence INTEGER DEFAULT 1,

        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()

    conn.close()

    print("Database initialized.")


# =====================================================
# Helper Functions
# =====================================================

def execute(query, values=()):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(query, values)

    conn.commit()

    conn.close()


def fetch_all(query, values=()):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(query, values)

    rows = cursor.fetchall()

    conn.close()

    return rows


def fetch_one(query, values=()):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(query, values)

    row = cursor.fetchone()

    conn.close()

    return row


# =====================================================
# Table Exists
# =====================================================

def table_exists(table_name):

    row = fetch_one(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        AND name=?
        """,
        (table_name,),
    )

    return row is not None


# =====================================================
# List Tables
# =====================================================

def list_tables():

    rows = fetch_all(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table'
        ORDER BY name
        """
    )

    return [row["name"] for row in rows]


# =====================================================
# Database Exists
# =====================================================

def database_exists():

    return os.path.exists(DATABASE_PATH)


# =====================================================
# Reset Database
# =====================================================

def reset_database():

    if database_exists():

        os.remove(DATABASE_PATH)

    initialize_database()

    print("Database reset complete.")


# =====================================================
# Print Tables
# =====================================================

def print_tables():

    print("\n========== DATABASE TABLES ==========")

    for table in list_tables():

        print(table)


# Auto-initialize database on import
try:
    initialize_database()
except Exception as e:
    print("Database auto-initialization warning:", e)
