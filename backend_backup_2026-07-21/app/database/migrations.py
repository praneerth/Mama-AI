from app.database.database import initialize_database, list_tables


# =====================================================
# Run Database Migration
# =====================================================

def migrate():

    print("=" * 50)
    print("Running Mama AI Database Migration...")
    print("=" * 50)

    initialize_database()

    print("\nDatabase initialized successfully.\n")

    print("Available Tables:")

    for table in list_tables():
        print(f"  ✓ {table}")

    print("\nMigration completed successfully.")


# =====================================================
# Main
# =====================================================

if __name__ == "__main__":
    migrate()